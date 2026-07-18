#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import build_adaptive_dual_contact_targets_v3 as mod  # noqa: E402
from test_build_adaptive_dual_pair_contact_targets_v3 import Inputs, write_tsv  # noqa: E402


class MarginalInputs(Inputs):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        with self.training.open() as handle:
            training_rows = list(csv.DictReader(handle, delimiter="\t"))
        by_candidate = {row["candidate_id"]: row for row in training_rows}
        self.v4d_marginal = root / "v4d_marginal.tsv.gz"
        drows = []
        for receptor in mod.RECEPTORS:
            for index, aa in enumerate(by_candidate["D"]["sequence"], start=1):
                values = [0.1 * index, 0.2 * index, 0.3 * index]
                mean = sum(values) / 3; variance = sum((value - mean) ** 2 for value in values) / 3
                drows.append({
                    "candidate_id": "D", "sequence_sha256": by_candidate["D"]["sequence_sha256"],
                    "parent_framework_cluster": "PD", "receptor": receptor, "vhh_sequence_index": index, "vhh_aa": aa,
                    "contact_marginal_mean": mean, "contact_marginal_variance": variance,
                    "contact_marginal_uncertainty_weight": 1 / (1 + 4 * variance), "observed_seed_count": 3, "expected_seed_count": 3,
                })
        write_tsv(self.v4d_marginal, list(drows[0]), drows, True)
        v4d_receipt = json.loads(self.v4d_receipt.read_text())
        v4d_receipt["outputs"]["residue_marginal_sha256"] = mod.sha256_file(self.v4d_marginal)
        self.v4d_receipt.write_text(json.dumps(v4d_receipt))

        self.v4h_residue = root / "v4h_residue.tsv.gz"
        hrows = []
        for receptor in mod.RECEPTORS:
            for index, aa in enumerate(by_candidate["H"]["sequence"], start=1):
                values = [0.1 * index, 0.2 * index]
                mean = sum(values) / 2; variance = sum((value - mean) ** 2 for value in values) / 2
                hrows.append({
                    "schema_version": "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2", "teacher_state": "VALID_DUAL_2_SEED_CONTACT",
                    "candidate_id": "H", "sequence_sha256": by_candidate["H"]["sequence_sha256"], "parent_framework_cluster": "PH",
                    "receptor": receptor, "observed_seed_count": 2, "observed_seed_ids": "917;1931",
                    "vhh_sequence_index": index, "vhh_aa": aa, "contact_marginal_mean": mean,
                    "contact_marginal_variance": variance, "contact_marginal_uncertainty_weight": 1 / (1 + 4 * variance),
                    "supporting_seed_count": 2, "seed_marginal_values": f"917:{values[0]};1931:{values[1]}",
                })
        write_tsv(self.v4h_residue, list(hrows[0]), hrows, True)
        v4h_receipt = json.loads(self.v4h_receipt.read_text())
        v4h_receipt["output_hashes"][self.v4h_residue.name] = mod.sha256_file(self.v4h_residue)
        v4h_receipt["output_hashes"]["v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz"] = mod.sha256_file(self.v4h_residue)
        self.v4h_receipt.write_text(json.dumps(v4h_receipt))

    def build_marginal(self, output: Path):
        return mod.build_targets(
            self.training, self.v4d_marginal, self.v4d_receipt,
            self.v4h_residue, self.v4h_candidates, self.v4h_receipt, output,
            expected_source_counts={mod.V4D: 1, mod.V4H: 1},
        )


class Tests(unittest.TestCase):
    def test_preserves_adaptive_seed_mean_variance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = MarginalInputs(root); receipt = inputs.build_marginal(root / "out")
            self.assertEqual(receipt["status"], mod.RECEIPT_STATUS)
            self.assertEqual(receipt["counts"]["target_candidates"], 2)
            self.assertEqual(receipt["counts"]["target_rows"], 8)
            self.assertEqual(receipt["counts"]["v4h_technical_na_candidate_rows"], 39)
            with gzip.open(root / "out" / mod.OUTPUT_NAME, "rt") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            row = next(item for item in rows if item["candidate_id"] == "H" and item["vhh_sequence_index"] == "2")
            self.assertAlmostEqual(float(row["contact_target_8x6b"]), 0.3)
            self.assertAlmostEqual(float(row["contact_variance_8x6b"]), 0.01)
            self.assertEqual(row["observed_seed_count_8x6b"], "2")
            self.assertEqual(row["expected_seed_count_8x6b"], "2")

    def test_receipt_hash_mismatch_fails_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = MarginalInputs(root)
            receipt = json.loads(inputs.v4h_receipt.read_text())
            receipt["output_hashes"][inputs.v4h_residue.name] = "0" * 64
            inputs.v4h_receipt.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(mod.ContactTargetError, "v4h_residue_hash"):
                inputs.build_marginal(root / "out")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
