from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "src/build_primary_d0_d1_teacher_v1.py"
STAGE0_PATH = ROOT / "src/run_sequence_stage0_expanded_v2_9.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module("v29_primary_builder", BUILDER_PATH)
STAGE0 = load_module("v29_stage0_for_builder_test", STAGE0_PATH)


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    names = fieldnames or list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sequence_for(index: int) -> tuple[str, str, str, str]:
    aa = "ACDEFGHIKLMNPQRSTVWY"
    cdr1 = "ACD" + aa[index % 20] + aa[(index // 20) % 20]
    cdr2 = "FGH" + aa[(index + 3) % 20]
    cdr3 = "KLMNP" + aa[(index + 7) % 20]
    sequence = "QVQLVESGGGLVQSGGSLRLSCAAS" + cdr1 + "WYRQAPGKERELVA" + cdr2 + "RFTISRDFSRSTMYLQMNSLKPEDTAIYYCAA" + cdr3 + "WGQGTQVTVSS"
    return sequence, cdr1, cdr2, cdr3


def seq_fields(candidate_id: str, parent: str, index: int) -> dict[str, str]:
    sequence, cdr1, cdr2, cdr3 = sequence_for(index)
    return {
        "candidate_id": candidate_id,
        "sequence": sequence,
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        "cdr1": cdr1,
        "cdr2": cdr2,
        "cdr3": cdr3,
        "parent_framework_cluster": parent,
    }


def old_row(candidate_id: str, parent: str, index: int) -> dict[str, str]:
    row = seq_fields(candidate_id, parent, index)
    r8 = 0.45 + index * 0.005
    r9 = 0.46 + index * 0.004
    row.update({
        "sample_weight": "1.0",
        "R_8X6B": f"{r8:.9f}",
        "R_9E6Y": f"{r9:.9f}",
        "R_dual_min": f"{min(r8, r9):.9f}",
        "teacher_source": "OLD",
        "teacher_reliability": "MULTI_SEED",
    })
    return row


def snapshot_row(candidate_id: str, index: int, bad: bool = False) -> dict[str, str]:
    r8 = 0.51 + index * 0.003
    r9 = 0.52 + index * 0.002
    return {
        "candidate_id": candidate_id,
        "sample_weight": "SECRET" if bad else "0.65",
        "R_8X6B": "SECRET" if bad else f"{r8:.9f}",
        "R_9E6Y": "SECRET" if bad else f"{r9:.9f}",
        "R_dual_min": "SECRET" if bad else f"{min(r8, r9):.9f}",
        "teacher_source": "V29_OPEN",
        "teacher_reliability": "DUAL_1_SEED",
    }


def make_fixture(root: Path, frozen_in_snapshot: bool = False) -> dict[str, Path | str]:
    old = root / "old3388_fixture.tsv"
    old_rows = []
    index = 0
    for parent in ("P_OLD_ONLY", "P_TRAIN", "P_DEV", "P_FROZEN"):
        for _ in range(2):
            old_rows.append(old_row(f"OLD_{index}", parent, index))
            index += 1
    write_tsv(old, old_rows)

    candidate_specs = [
        ("V_TRAIN", "P_TRAIN", "train"),
        ("V_DEV", "P_DEV", "development"),
        ("V_FROZEN", "P_FROZEN", "frozen_test"),
        ("V_NEW_TRAIN", "P_NEW_TRAIN", "train"),
        ("V_NEW_DEV", "P_NEW_DEV", "development"),
        ("V_NEW_FROZEN", "P_NEW_FROZEN", "frozen_test"),
    ]
    candidates = root / "candidates_128.tsv"
    candidate_rows = []
    for offset, (candidate_id, parent, split) in enumerate(candidate_specs, start=20):
        row = seq_fields(candidate_id, parent, offset)
        row["model_split"] = split
        candidate_rows.append(row)
    write_tsv(candidates, candidate_rows)

    snapshot = root / "open_snapshot.tsv"
    if frozen_in_snapshot:
        snapshot_rows = [snapshot_row("V_FROZEN", 1, bad=True)]
    else:
        snapshot_rows = [
            snapshot_row("V_TRAIN", 1),
            snapshot_row("V_DEV", 2),
            snapshot_row("V_NEW_TRAIN", 3),
            snapshot_row("V_NEW_DEV", 4),
        ]
    write_tsv(snapshot, snapshot_rows)
    return {
        "old": old,
        "old_sha": MOD.sha256_file(old),
        "candidates": candidates,
        "candidates_sha": MOD.sha256_file(candidates),
        "snapshot": snapshot,
        "snapshot_sha": MOD.sha256_file(snapshot),
    }


def run_materialize(root: Path, fixture: dict[str, Path | str], **kwargs):
    return MOD.materialize(
        old_teacher_tsv=fixture["old"],
        old_teacher_sha256=fixture["old_sha"],
        v29_candidates_tsv=fixture["candidates"],
        v29_candidates_sha256=fixture["candidates_sha"],
        v29_open_snapshot_tsv=fixture["snapshot"],
        v29_open_snapshot_sha256=fixture["snapshot_sha"],
        output_dir=root / "prepared",
        split_id_prefix="fixture_primary",
        **kwargs,
    )


class PrimaryTeacherBuilderTests(unittest.TestCase):
    def test_primary_d0_d1_rules_and_stage0_manifest_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root)
            receipt = run_materialize(
                root, fixture,
                expected_d0_rows=6,
                expected_d0_train_rows=4,
                expected_d0_dev_rows=2,
            )
            self.assertEqual(receipt["counts"]["old_rows_excluded_for_v29_frozen_parents"], 2)
            self.assertEqual(receipt["counts"]["D0_rows"], 6)
            self.assertEqual(receipt["counts"]["D1_rows"], 10)
            self.assertEqual(receipt["counts"]["v29_frozen_label_rows_read"], 0)
            prepared = root / "prepared"
            d0 = prepared / "primary_D0_teacher.tsv"
            d1 = prepared / "primary_D1_teacher.tsv"
            d0_split = prepared / "primary_D0_split_manifest.json"
            d1_split = prepared / "primary_D1_split_manifest.json"
            with d0.open() as handle:
                d0_rows = list(csv.DictReader(handle, delimiter="\t"))
            with d1.open() as handle:
                d1_rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertFalse(any(row["parent_framework_cluster"] == "P_FROZEN" for row in d0_rows + d1_rows))
            manifest = json.loads(d1_split.read_text())
            self.assertIn("P_OLD_ONLY", manifest["train_parents"])
            self.assertIn("P_DEV", manifest["score_parents"])
            self.assertIn("P_FROZEN", manifest["frozen_test_parents"])
            loaded_d0, _ = STAGE0.load_rows(d0, d0_split, MOD.sha256_file(d0), "D0")
            loaded_d1, _ = STAGE0.load_rows(d1, d1_split, MOD.sha256_file(d1), "D1")
            self.assertEqual(len(loaded_d0), 6)
            self.assertEqual(len(loaded_d1), 10)

    def test_frozen_snapshot_candidate_rejected_before_numeric_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root, frozen_in_snapshot=True)
            with self.assertRaisesRegex(RuntimeError, "before_label_parse:V_FROZEN"):
                run_materialize(root, fixture)
            self.assertFalse((root / "prepared").exists())

    def test_expected_d0_count_gate_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root)
            with self.assertRaisesRegex(RuntimeError, "expected_d0_rows_mismatch:6"):
                run_materialize(root, fixture, expected_d0_rows=3054)
            self.assertFalse((root / "prepared").exists())

    def test_parent_split_inconsistency_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root)
            with Path(fixture["candidates"]).open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            extra = dict(rows[0])
            extra["candidate_id"] = "V_CONFLICT"
            extra.update(seq_fields("V_CONFLICT", "P_TRAIN", 60))
            extra["model_split"] = "development"
            rows.append(extra)
            write_tsv(Path(fixture["candidates"]), rows)
            fixture["candidates_sha"] = MOD.sha256_file(Path(fixture["candidates"]))
            with self.assertRaisesRegex(RuntimeError, "v29_parent_split_inconsistent:P_TRAIN"):
                run_materialize(root, fixture)

    def test_snapshot_exact_min_failure_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root)
            with Path(fixture["snapshot"]).open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            rows[0]["R_dual_min"] = "0.999"
            write_tsv(Path(fixture["snapshot"]), rows)
            fixture["snapshot_sha"] = MOD.sha256_file(Path(fixture["snapshot"]))
            with self.assertRaisesRegex(RuntimeError, "truth_exact_min:V_TRAIN"):
                run_materialize(root, fixture)
            self.assertFalse((root / "prepared").exists())

    def test_output_hash_receipt_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root)
            run_materialize(root, fixture)
            prepared = root / "prepared"
            receipt = json.loads((prepared / "MATERIALIZATION_RECEIPT.json").read_text())
            for name, expected in receipt["output_sha256"].items():
                self.assertEqual(MOD.sha256_file(prepared / name), expected)
            lines = (prepared / "SHA256SUMS").read_text().strip().splitlines()
            self.assertEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main()
