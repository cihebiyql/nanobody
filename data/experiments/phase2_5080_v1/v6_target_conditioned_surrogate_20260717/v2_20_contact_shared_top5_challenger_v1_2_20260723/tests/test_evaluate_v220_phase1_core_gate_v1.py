#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "evaluate_v220_phase1_core_gate_v1.py"
SPEC = importlib.util.spec_from_file_location("evaluate_v220_phase1_gate_test", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def metric(ef5, hits, ef10=3.0, rho=0.6, mae=0.03):
    return {
        "EF_true_top10_at_budget5": ef5,
        "hits_at_budget5": hits,
        "EF_true_top10_at_budget10": ef10,
        "Rdual_Spearman": rho,
        "Rdual_MAE": mae,
    }


def bootstrap(c0_lower=0.1, b0_lower=0.1):
    return {"paired_deltas": {"C1_minus_C0": {"paired_percentile_95_ci": [c0_lower, 1.0]}, "C1_minus_B0": {"paired_percentile_95_ci": [b0_lower, 1.0]}}}


def folds(delta=0.0):
    return {str(fold): {"C0": metric(3.0, 30), "C1": metric(3.0 + delta, 31), "B0": metric(2.9, 29)} for fold in range(5)}


class Phase1GateTests(unittest.TestCase):
    def _receipt_fixture(self, root: Path):
        paths = {name: root / f"{name}.tsv" for name in ("B0", "C0", "C1")}
        for name, path in paths.items():
            path.write_text(name)
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        b0 = {
            "status": "PASS_V213_B0_OOF_BYTE_EXACT_REPLAY",
            "counts": {"rows": 1, "parents": 1},
            "hashes": {"aggregate": digest(paths["B0"])},
        }
        receipts = {}
        for arm in ("C0", "C1"):
            receipts[arm] = {
                "status": f"PASS_V220_{arm}_TRAIN9849_WHOLE_PARENT_OOF",
                "counts": {"rows": 1, "parents": 1, "folds": 5},
                "outputs": {
                    f"V220_{arm}_TRAIN9849_OOF_PREDICTIONS.tsv": digest(paths[arm])
                },
                "inputs": {
                    "folds": {
                        str(fold): {"result_sha256": f"{arm}-{fold}"}
                        for fold in range(5)
                    }
                },
            }
        pairing = {
            "status": "PASS_V220_C0_C1_FIVE_FOLD_CAUSAL_PAIRING",
            "folds": [
                {
                    "fold_id": fold,
                    "C0_result_sha256": f"C0-{fold}",
                    "C1_result_sha256": f"C1-{fold}",
                }
                for fold in range(5)
            ],
        }
        objects = {"b0": b0, "c0": receipts["C0"], "c1": receipts["C1"], "pairing": pairing}
        json_paths = {}
        for name, value in objects.items():
            json_paths[name] = root / f"{name}.json"
            json_paths[name].write_text(json.dumps(value))
        return paths, json_paths

    def test_all_core_gates_pass(self):
        metrics = {"B0": metric(3.08, 152), "C0": metric(3.10, 153), "C1": metric(3.30, 160)}
        checks, passed = MODULE.gate_decision(metrics, bootstrap(), folds(0.1))
        self.assertTrue(passed)
        self.assertTrue(all(checks.values()))

    def test_ef5_gain_is_strictly_enforced(self):
        metrics = {"B0": metric(3.08, 152), "C0": metric(3.10, 153), "C1": metric(3.15, 160)}
        checks, passed = MODULE.gate_decision(metrics, bootstrap(), folds(0.1))
        self.assertFalse(passed)
        self.assertFalse(checks["pooled_ef5_gain"])

    def test_bootstrap_lower_bound_must_be_positive(self):
        metrics = {"B0": metric(3.08, 152), "C0": metric(3.10, 153), "C1": metric(3.30, 160)}
        checks, passed = MODULE.gate_decision(metrics, bootstrap(c0_lower=0.0), folds(0.1))
        self.assertFalse(passed)
        self.assertFalse(checks["bootstrap_C1_minus_C0_lower_positive"])

    def test_bad_single_fold_fails(self):
        metrics = {"B0": metric(3.08, 152), "C0": metric(3.10, 153), "C1": metric(3.30, 160)}
        per_fold = folds(0.1)
        per_fold["4"]["C1"] = metric(2.0, 20)
        checks, passed = MODULE.gate_decision(metrics, bootstrap(), per_fold)
        self.assertFalse(passed)
        self.assertFalse(checks["minimum_fold_stability"])

    def test_pairing_receipt_cross_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, receipts = self._receipt_fixture(Path(temporary))
            hashes = MODULE.verify_receipts(
                b0_path=paths["B0"],
                c0_path=paths["C0"],
                c1_path=paths["C1"],
                b0_replay_path=receipts["b0"],
                c0_receipt_path=receipts["c0"],
                c1_receipt_path=receipts["c1"],
                pairing_receipt_path=receipts["pairing"],
                expected_rows=1,
                expected_parents=1,
            )
            self.assertEqual(len(hashes), 4)

    def test_mixed_pairing_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, receipts = self._receipt_fixture(Path(temporary))
            pairing = json.loads(receipts["pairing"].read_text())
            pairing["folds"][2]["C1_result_sha256"] = "another-run"
            receipts["pairing"].write_text(json.dumps(pairing))
            with self.assertRaisesRegex(
                MODULE.Phase1GateError, "pairing_C1_result_closure:2"
            ):
                MODULE.verify_receipts(
                    b0_path=paths["B0"],
                    c0_path=paths["C0"],
                    c1_path=paths["C1"],
                    b0_replay_path=receipts["b0"],
                    c0_receipt_path=receipts["c0"],
                    c1_receipt_path=receipts["c1"],
                    pairing_receipt_path=receipts["pairing"],
                    expected_rows=1,
                    expected_parents=1,
                )


if __name__ == "__main__":
    unittest.main()
