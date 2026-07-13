#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch

MODULE_PATH = Path(__file__).with_name("prepare_pvrig_formal_teacher500_model_inputs.py")
SPEC = importlib.util.spec_from_file_location("prepare_pvrig_formal_teacher500_model_inputs", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def encode_index(index: int) -> str:
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    output = []
    for _ in range(3):
        output.append(alphabet[index % len(alphabet)])
        index //= len(alphabet)
    return "".join(output)


def synthetic_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(MOD.EXPECTED_CANDIDATES):
        cdr1, cdr2, cdr3 = "ARND", "CQEG", "HILK"
        sequence = "QVQLVESGGG" + encode_index(index) + "AAAAA" + cdr1 + "CCCCC" + cdr2 + "DDDDD" + cdr3 + "EEEEE"
        starts = {
            "cdr1": sequence.index(cdr1) + 1,
            "cdr2": sequence.index(cdr2) + 1,
            "cdr3": sequence.index(cdr3) + 1,
        }
        rows.append(
            {
                "candidate_id": f"candidate_{index:03d}",
                "vhh_sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "sequence_length": str(len(sequence)),
                "cdr1_after": cdr1,
                "cdr2_after": cdr2,
                "cdr3_after": cdr3,
                "cdr1_start_1based": str(starts["cdr1"]),
                "cdr1_end_1based": str(starts["cdr1"] + len(cdr1) - 1),
                "cdr2_start_1based": str(starts["cdr2"]),
                "cdr2_end_1based": str(starts["cdr2"] + len(cdr2) - 1),
                "cdr3_start_1based": str(starts["cdr3"]),
                "cdr3_end_1based": str(starts["cdr3"] + len(cdr3) - 1),
                "parent_id": f"parent_{index % 40:02d}",
                "parent_framework_cluster": f"cluster_{index % 40:02d}",
                "target_patch_id": ("A", "B", "C")[index % 3],
                "design_mode": ("H3", "H1H3")[index % 2],
                "formal_split": "train" if index < 350 else "dev" if index < 425 else "test",
                "selection_rank": str(index + 1),
            }
        )
    return rows


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_fake_cache(outdir: Path, model_path: Path) -> None:
    sequences = MOD.read_csv(outdir / "sequence_manifest.csv")
    cache_dir = outdir / "esm2_8m_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    shard_path = cache_dir / "shard_00000.pt"
    payload = {
        row["sequence_sha256"]: torch.zeros((int(row["sequence_length"]), 320), dtype=torch.float16)
        for row in sequences
    }
    torch.save(payload, shard_path)
    model_hash = MOD.compute_model_sha256(model_path)
    cache_rows = [
        {
            "model_path": str(model_path),
            "model_sha256": model_hash,
            "sequence_sha256": row["sequence_sha256"],
            "sequence_length": row["sequence_length"],
            "cached_length": row["sequence_length"],
            "truncation_policy": "none",
            "chain_type": row["chain_type"],
            "shard_path": shard_path.name,
            "shard_key": row["sequence_sha256"],
        }
        for row in sequences
    ]
    MOD.write_cache_manifest(cache_dir / "manifest.csv", cache_rows)


class PrepareFormalTeacher500InputsTest(unittest.TestCase):
    def test_current_formal_selection_builds_exact_frozen_sequence_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            audit, sequences = MOD.prepare_sequence_inputs(MOD.DEFAULT_SELECTION, MOD.DEFAULT_TARGET, outdir)
            self.assertEqual(audit["candidate_count"], 500)
            self.assertEqual(audit["unique_vhh_sequence_count"], 500)
            self.assertEqual(audit["sequence_manifest_count"], 501)
            self.assertEqual(audit["formal_split_counts"], {"dev": 75, "test": 75, "train": 350})
            self.assertEqual(audit["parent_framework_cluster_count"], 40)
            self.assertEqual(audit["sha256"]["selection"], MOD.EXPECTED_SELECTION_SHA256)
            self.assertEqual({row["chain_type"] for row in sequences}, {"antigen", "vhh"})

            masks = MOD.read_csv(outdir / "vhh_cdr_type_masks.csv")
            self.assertEqual(len(masks), 500)
            self.assertEqual({row["status"] for row in masks}, {"exact_annotation"})
            for row in masks:
                mask = json.loads(row["cdr_mask_json"])
                spans = json.loads(row["spans_json"])
                self.assertEqual(len(mask), int(row["vhh_len"]))
                self.assertEqual(set(mask), {0, 1, 2, 3})
                for cdr_type, name in enumerate(("cdr1", "cdr2", "cdr3"), start=1):
                    start, end = spans[name]
                    self.assertTrue(all(value == cdr_type for value in mask[start:end]))
                    self.assertEqual(row["vhh_seq"][start:end], row[f"{name}_seq"])

    def test_rejects_duplicate_vhh_sequence_even_with_unique_candidate_ids(self) -> None:
        rows = synthetic_rows()
        rows[-1]["vhh_sequence"] = rows[0]["vhh_sequence"]
        rows[-1]["sequence_sha256"] = rows[0]["sequence_sha256"]
        rows[-1]["sequence_length"] = rows[0]["sequence_length"]
        with tempfile.TemporaryDirectory() as tmp:
            selection = Path(tmp) / "selection.csv"
            write_rows(selection, rows)
            with self.assertRaisesRegex(ValueError, "exact-unique VHH sequences"):
                MOD.validate_selection(selection, expected_selection_sha256=None)

    def test_rejects_sequence_hash_or_frozen_coordinate_drift(self) -> None:
        rows = synthetic_rows()
        rows[0]["sequence_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            selection = Path(tmp) / "selection.csv"
            write_rows(selection, rows)
            with self.assertRaisesRegex(ValueError, "sequence SHA256 mismatch"):
                MOD.validate_selection(selection, expected_selection_sha256=None)

        rows = synthetic_rows()
        rows[0]["cdr3_start_1based"] = str(int(rows[0]["cdr3_start_1based"]) - 1)
        with tempfile.TemporaryDirectory() as tmp:
            selection = Path(tmp) / "selection.csv"
            write_rows(selection, rows)
            with self.assertRaisesRegex(ValueError, "frozen coordinates do not match"):
                MOD.validate_selection(selection, expected_selection_sha256=None)

    def test_validates_501_tensor_cache_and_resume_skips_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outdir = root / "model_inputs"
            model_path = root / "model.bin"
            model_path.write_bytes(b"frozen-test-model")
            MOD.prepare_sequence_inputs(MOD.DEFAULT_SELECTION, MOD.DEFAULT_TARGET, outdir)
            write_fake_cache(outdir, model_path)

            audit = MOD.validate_model_inputs(outdir)
            self.assertEqual(audit["cache_rows"], 501)
            self.assertEqual(audit["cache_chain_type_counts"], {"antigen": 1, "vhh": 500})
            self.assertEqual(audit["cache_embedding_dimensions"], [320])

            sequences = MOD.read_csv(outdir / "sequence_manifest.csv")
            summary = MOD.build_resumable_cache(
                sequences,
                model_path,
                outdir / "esm2_8m_cache",
                "cpu",
                batch_size=8,
                attention_budget=100_000,
                shard_size=256,
            )
            self.assertEqual(summary["resumed_sequences"], 501)
            self.assertEqual(summary["new_sequences"], 0)

    def test_rejects_pair_identity_or_cache_manifest_metadata_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outdir = root / "model_inputs"
            model_path = root / "model.bin"
            model_path.write_bytes(b"frozen-test-model")
            MOD.prepare_sequence_inputs(MOD.DEFAULT_SELECTION, MOD.DEFAULT_TARGET, outdir)
            write_fake_cache(outdir, model_path)

            pairs = MOD.read_csv(outdir / "pvrig_formal_teacher500_pair_inputs.csv")
            pairs[0]["sample_id"] = "wrong_candidate"
            write_rows(outdir / "pvrig_formal_teacher500_pair_inputs.csv", pairs)
            with self.assertRaisesRegex(ValueError, "candidate-ID sets differ"):
                MOD.validate_model_inputs(outdir)

        for field, replacement, message in (
            ("cached_length", "1", "tensor validation failed"),
            ("shard_key", "wrong_key", "tensor validation failed"),
            ("model_sha256", "0" * 64, "multiple model hashes"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                outdir = root / "model_inputs"
                model_path = root / "model.bin"
                model_path.write_bytes(b"frozen-test-model")
                MOD.prepare_sequence_inputs(MOD.DEFAULT_SELECTION, MOD.DEFAULT_TARGET, outdir)
                write_fake_cache(outdir, model_path)
                manifest_path = outdir / "esm2_8m_cache/manifest.csv"
                rows = MOD.read_csv(manifest_path)
                rows[0][field] = replacement
                MOD.write_cache_manifest(manifest_path, rows)
                with self.assertRaisesRegex(ValueError, message):
                    MOD.validate_model_inputs(outdir)


if __name__ == "__main__":
    unittest.main()
