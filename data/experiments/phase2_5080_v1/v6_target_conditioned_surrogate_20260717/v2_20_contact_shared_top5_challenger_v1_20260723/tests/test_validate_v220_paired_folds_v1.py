#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "validate_v220_paired_folds_v1.py"
SPEC = importlib.util.spec_from_file_location("validate_v220_pairs_test", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PairValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.c0, self.c1 = self.root / "C0", self.root / "C1"
        for arm, arm_root in (("C0", self.c0), ("C1", self.c1)):
            for fold in range(5):
                fold_root = arm_root / f"fold_{fold}"
                fold_root.mkdir(parents=True)
                outputs = {}
                for name in MODULE.OUTPUT_NAMES:
                    path = fold_root / name
                    payload = (
                        f"paired-{fold}-{name}"
                        if name == "CONTACT_WEIGHT_CALIBRATION.json"
                        else f"{arm}-{fold}-{name}"
                    )
                    path.write_bytes(payload.encode())
                    outputs[name] = sha(path)
                selected = 0.000625
                result = {
                    "status": f"PASS_V220_{arm}_CONTACT_SHARED_FOLD",
                    "arm": arm,
                    "fold_id": fold,
                    "seed": 43,
                    "split": {"split_id": f"f{fold}", "whole_parent_overlap": 0},
                    "neural_input_firewall": {"outer_score_contact_numeric_reads": 0, "contact_labels_forwarded": False},
                    "exact_min_inference": True,
                    "pairing": {"initial_state_hashes": {"head_state_sha256": "h"}, "serialized_initial_state_sha256": "a" * 64, "optimizer_group_sha256": f"o{fold}", "epoch_batch_order_sha256": [f"e{fold}"], "serialized_initial_state_scope": "model.head", "backbone_binding": {"artifact_identity_sha256": "b" * 64, "runtime_state_sha256": "c" * 64, "state_contract_sha256": "d" * 64, "serialized_in_checkpoint": False}},
                    "contact_weights": {"selected_marginal_weight": selected, "selected_pair_weight": selected * 0.5, "applied_marginal_weight": 0.0 if arm == "C0" else selected, "applied_pair_weight": 0.0 if arm == "C0" else selected * 0.5},
                    "input_bindings": {"fold": fold},
                    "outputs": outputs,
                }
                (fold_root / "RESULT.json").write_text(json.dumps(result))

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_pair_passes(self):
        result = MODULE.validate_pair(self.c0, self.c1)
        self.assertEqual(result["status"], "PASS_V220_C0_C1_FIVE_FOLD_CAUSAL_PAIRING")
        self.assertEqual(len(result["folds"]), 5)

    def test_calibration_mismatch_fails(self):
        path = self.c1 / "fold_3" / "RESULT.json"
        result = json.loads(path.read_text())
        result["contact_weights"]["selected_marginal_weight"] = 0.00125
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(MODULE.PairValidationError, "calibration_selected_mismatch:3"):
            MODULE.validate_pair(self.c0, self.c1)

    def test_batch_order_mismatch_fails(self):
        path = self.c1 / "fold_2" / "RESULT.json"
        result = json.loads(path.read_text())
        result["pairing"]["epoch_batch_order_sha256"] = ["different"]
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(MODULE.PairValidationError, "pairing_mismatch:2:epoch_batch_order"):
            MODULE.validate_pair(self.c0, self.c1)

    def test_calibration_receipt_hash_mismatch_fails(self):
        path = self.c1 / "fold_0" / "CONTACT_WEIGHT_CALIBRATION.json"
        path.write_text("different calibration")
        result_path = self.c1 / "fold_0" / "RESULT.json"
        result = json.loads(result_path.read_text())
        result["outputs"]["CONTACT_WEIGHT_CALIBRATION.json"] = sha(path)
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(
            MODULE.PairValidationError, "calibration_receipt_hash_mismatch:0"
        ):
            MODULE.validate_pair(self.c0, self.c1)

    def test_output_tamper_fails(self):
        (self.c0 / "fold_1" / "fold_predictions.tsv").write_text("tampered")
        with self.assertRaisesRegex(MODULE.PairValidationError, "output_hash:C0:1:fold_predictions"):
            MODULE.validate_pair(self.c0, self.c1)


if __name__ == "__main__":
    unittest.main()
