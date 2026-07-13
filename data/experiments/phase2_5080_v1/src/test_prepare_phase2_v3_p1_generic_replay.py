#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_phase2_v3_p1_generic_replay.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v3_p1_generic_replay", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def contact_row(index: int, split: str = "train", **overrides: object) -> dict[str, object]:
    variant = "ACDEFGHIK"[index % 9]
    row: dict[str, object] = {
        "complex_id": f"sample_{index}",
        "pdb": f"pdb_{index}",
        "split": split,
        "vhh_seq": f"ACDEFGHIKLMNPQRS{variant}W",
        "antigen_seq": f"YWVTSRQPNMLKIHGF{variant}C",
        "positive_pairs": [[1, 2], [3, 4], [1, 2]],
        "structure_group": f"structure_{index}",
        "split_group_id": f"split_group_{index}",
        "vhh_cluster_id": f"vhh_cluster_{index}",
        "antigen_cluster_id": f"antigen_cluster_{index}",
    }
    row.update(overrides)
    return row


class GenericReplayPreparationTest(unittest.TestCase):
    def fixture(self, root: Path, rows: list[dict[str, object]], teacher_vhh: str = "QQQQ") -> tuple[Path, ...]:
        source = root / "source.jsonl"
        cache = root / "cache.csv"
        masks = root / "masks.csv"
        teacher = root / "teacher.csv"
        write_jsonl(source, rows)
        sequences = {
            MODULE.sequence_sha256(str(row[key]))
            for row in rows
            for key in ("vhh_seq", "antigen_seq")
        }
        write_csv(cache, [{"sequence_sha256": digest, "shard_path": "unused.pt"} for digest in sorted(sequences)])
        unique_vhhs = sorted({str(row["vhh_seq"]) for row in rows})
        write_csv(
            masks,
            [
                {
                    "sequence_hash": MODULE.sequence_sha256(sequence),
                    "vhh_seq": sequence,
                    "vhh_len": str(len(sequence)),
                    "cdr_mask_json": json.dumps([0] * (len(sequence) - 3) + [3, 3, 3]),
                    "status": "exact_annotation",
                }
                for sequence in unique_vhhs
            ],
        )
        write_csv(
            teacher,
            [
                {
                    "candidate_id": "teacher_1",
                    "vhh_sequence": teacher_vhh,
                    "sequence_sha256": MODULE.sequence_sha256(teacher_vhh),
                    "formal_split": "test",
                    "target_sequence_sha256": MODULE.sequence_sha256("PVRIG"),
                }
            ],
        )
        return source, cache, masks, teacher

    def test_deterministic_diverse_contract_and_masks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [contact_row(index) for index in range(7)]
            source, cache, masks, teacher = self.fixture(root, rows)
            output_a, audit_a = root / "a.csv", root / "a.json"
            output_b, audit_b = root / "b.csv", root / "b.json"
            result = MODULE.prepare(source, cache, masks, teacher, output_a, audit_a, expected_rows=4)
            write_jsonl(source, list(reversed(rows)))
            MODULE.prepare(source, cache, masks, teacher, output_b, audit_b, expected_rows=4)

            self.assertEqual(output_a.read_bytes(), output_b.read_bytes())
            with output_a.open(newline="", encoding="utf-8") as handle:
                selected = list(csv.DictReader(handle))
            self.assertEqual(list(selected[0]), list(MODULE.OUTPUT_FIELDS))
            self.assertEqual(len(selected), 4)
            self.assertEqual(result["selected_diversity"]["unique_structure_groups"], 4)
            self.assertEqual(result["selected_diversity"]["unique_antigen_clusters"], 4)
            self.assertEqual(result["selected_diversity"]["unique_vhh_clusters"], 4)
            for row in selected:
                pairs = json.loads(row["contact_pairs_json"])
                self.assertEqual(pairs, [[1, 2], [3, 4]])
                self.assertEqual(row["vhh_paratope_mask"].count("1"), 2)
                self.assertEqual(row["antigen_epitope_mask"].count("1"), 2)
            self.assertEqual(result["source_holdout_overlap"], {key: 0 for key in result["source_holdout_overlap"]})
            self.assertEqual(result["teacher500_overlap"], {key: 0 for key in result["teacher500_overlap"]})

    def test_rejects_source_holdout_cluster_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                contact_row(1, antigen_cluster_id="shared_antigen"),
                contact_row(2, split="test", antigen_cluster_id="shared_antigen"),
            ]
            source, cache, masks, teacher = self.fixture(root, rows)
            with self.assertRaisesRegex(ValueError, "overlaps source holdout"):
                MODULE.prepare(source, cache, masks, teacher, root / "out.csv", root / "audit.json", expected_rows=1)

    def test_rejects_teacher500_vhh_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [contact_row(1)]
            source, cache, masks, teacher = self.fixture(root, rows, teacher_vhh=str(rows[0]["vhh_seq"]))
            with self.assertRaisesRegex(ValueError, "overlaps Teacher500"):
                MODULE.prepare(source, cache, masks, teacher, root / "out.csv", root / "audit.json", expected_rows=1)

    def test_requires_cache_and_resolved_cdr3_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [contact_row(1)]
            source, cache, masks, teacher = self.fixture(root, rows)
            with cache.open(newline="", encoding="utf-8") as handle:
                cache_rows = list(csv.DictReader(handle))
            vhh_hash = MODULE.sequence_sha256(str(rows[0]["vhh_seq"]))
            write_csv(cache, [row for row in cache_rows if row["sequence_sha256"] != vhh_hash])
            with self.assertRaisesRegex(ValueError, "Could select only 0/1"):
                MODULE.prepare(source, cache, masks, teacher, root / "out.csv", root / "audit.json", expected_rows=1)


if __name__ == "__main__":
    unittest.main()
