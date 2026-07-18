import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "collect_residue_oof_v1_2.py"
spec = importlib.util.spec_from_file_location("residue_oof_v1_2", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestFrozenAmendmentPromotion(unittest.TestCase):
    def rows_with_worse_mae_but_better_ranking(self):
        rows = []
        for parent_index in range(12):
            for variant in range(5):
                truth = 0.4 + parent_index * 0.02 + variant * 0.002
                rows.append({
                    "candidate_id": f"P{parent_index}_V{variant}",
                    "parent_framework_cluster": f"P{parent_index}",
                    "outer_fold": parent_index % 5,
                    "R_dual_min": truth,
                    "m2_prediction": truth + (0.003 if (parent_index + variant) % 3 == 0 else -0.003),
                    "residue_prediction": truth * 10.0,
                })
        return rows

    def test_mae_is_diagnostic_only_under_exact_frozen_gate(self):
        rows = self.rows_with_worse_mae_but_better_ranking()
        bootstrap = {
            "median_delta_spearman": 0.05,
            "positive_fraction": 0.85,
            "ci95_lower": -0.01,
            "ci95_upper": 0.10,
        }
        decision = mod.promotion_decision(rows, bootstrap)
        self.assertEqual(decision["status"], "PROMOTE_RESIDUE_V1_2_OVER_M2")
        self.assertFalse(decision["diagnostics"]["mae_improves"])
        self.assertNotIn("mae_improves", decision["gates"])

    def test_positive_fraction_and_median_are_the_only_bootstrap_gates(self):
        rows = self.rows_with_worse_mae_but_better_ranking()
        rejected_fraction = mod.promotion_decision(rows, {
            "median_delta_spearman": 0.1, "positive_fraction": 0.79,
            "ci95_lower": 0.05, "ci95_upper": 0.2,
        })
        rejected_median = mod.promotion_decision(rows, {
            "median_delta_spearman": 0.0, "positive_fraction": 0.9,
            "ci95_lower": -0.2, "ci95_upper": 0.2,
        })
        accepted_negative_ci = mod.promotion_decision(rows, {
            "median_delta_spearman": 0.1, "positive_fraction": 0.8,
            "ci95_lower": -0.5, "ci95_upper": 0.3,
        })
        self.assertEqual(rejected_fraction["status"], "DO_NOT_PROMOTE_RESIDUE_V1_2")
        self.assertEqual(rejected_median["status"], "DO_NOT_PROMOTE_RESIDUE_V1_2")
        self.assertEqual(accepted_negative_ci["status"], "PROMOTE_RESIDUE_V1_2_OVER_M2")

    def test_parent_bootstrap_reports_frozen_statistics(self):
        summary = mod.parent_bootstrap(self.rows_with_worse_mae_but_better_ranking(), replicates=200, seed=43)
        self.assertEqual(summary["repetitions"], 200)
        for field in ("median_delta_spearman", "positive_fraction", "ci95_lower", "ci95_upper"):
            self.assertIn(field, summary)


if __name__ == "__main__":
    unittest.main()

