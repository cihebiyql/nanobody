import csv
import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "collect_residue_oof_v1_1.py"
spec = importlib.util.spec_from_file_location("residue_oof_v1_1", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestIndependentOofCollector(unittest.TestCase):
    def test_parent_bootstrap_is_deterministic_and_promotes_clear_improvement(self):
        rows = []
        for parent_index in range(12):
            for variant in range(4):
                truth = 0.42 + 0.015 * parent_index + 0.004 * variant
                rows.append({
                    "candidate_id": f"P{parent_index}_V{variant}",
                    "parent_framework_cluster": f"P{parent_index}",
                    "R_dual_min": truth,
                    "m2_prediction": 0.5 + 0.001 * ((parent_index + variant) % 3),
                    "residue_prediction": truth + 0.0001 * ((variant % 2) - 0.5),
                })
        first = mod.parent_bootstrap(rows, replicates=200, seed=43)
        second = mod.parent_bootstrap(rows, replicates=200, seed=43)
        self.assertEqual(first, second)
        decision = mod.promotion_decision(rows, first)
        self.assertEqual(decision["status"], "PROMOTE_RESIDUE_V1_1_OVER_M2")

    def test_exact_oof_candidate_closure_rejects_duplicate(self):
        rows = [
            {"candidate_id": "C1", "parent_framework_cluster": "P1", "R_dual_min": 0.5, "m2_prediction": 0.4, "residue_prediction": 0.5},
            {"candidate_id": "C1", "parent_framework_cluster": "P1", "R_dual_min": 0.5, "m2_prediction": 0.4, "residue_prediction": 0.5},
        ]
        with self.assertRaisesRegex(Exception, "duplicate_oof_candidate"):
            mod.validate_oof_rows(rows)


if __name__ == "__main__":
    unittest.main()

