import importlib.util
import pathlib
import unittest

import numpy as np


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("diagnostic", HERE / "analyze_adaptive_scalar_update_v1.py")
assert SPEC and SPEC.loader
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


class DiagnosticTests(unittest.TestCase):
    def test_rankdata_ties_and_spearman(self):
        values = np.asarray([3.0, 1.0, 1.0, 2.0])
        self.assertTrue(np.array_equal(diagnostic.rankdata(values), np.asarray([3.0, 0.5, 0.5, 2.0])))
        self.assertAlmostEqual(diagnostic.spearman(values, values), 1.0)

    def test_summary_detects_changes_and_top_overlap(self):
        old = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5])
        new = np.asarray([0.5, 0.2, 0.3, 0.4, 0.1])
        result = diagnostic.summarize(old, new)
        self.assertEqual(result["rows"], 5)
        self.assertEqual(result["changed_rows_at_1e_12"], 2)
        self.assertEqual(result["top20_overlap"]["budget"], 1)
        self.assertEqual(result["top20_overlap"]["retained"], 0)

    def test_exact_min_mismatch_rejected(self):
        training = []
        adaptive = []
        tiers = ["DUAL_3_SEED"] * 123 + ["DUAL_2_SEED"] * 241 + ["DUAL_1_SEED"] * 917
        for index, tier in enumerate(tiers):
            candidate = f"C{index:04d}"
            r8, r9 = 0.4 + index * 1e-5, 0.5 + index * 1e-5
            training.append({
                "candidate_id": candidate, "teacher_source": diagnostic.V4H_SOURCE,
                "R_8X6B": str(r8), "R_9E6Y": str(r9), "R_dual_min": str(min(r8, r9)),
            })
            adaptive.append({
                "candidate_id": candidate, "docking_evidence_tier": tier,
                "median_score_8X6B": str(r8), "median_score_9E6Y": str(r9),
                "R_dual_min": str(min(r8, r9)), "seed_dispersion_max": "0",
            })
        for index in range(226):
            training.append({
                "candidate_id": f"D{index:04d}", "teacher_source": "V4D_OPEN_MULTI_SEED",
                "R_8X6B": "0.4", "R_9E6Y": "0.5", "R_dual_min": "0.4",
            })
        for index in range(39):
            adaptive.append({"candidate_id": f"X{index:04d}", "docking_evidence_tier": "TECHNICAL_INCOMPLETE"})
        adaptive[0]["R_dual_min"] = "0.9"
        with self.assertRaisesRegex(diagnostic.DiagnosticError, "adaptive_exact_min_failures"):
            diagnostic.build_report(training, adaptive)


if __name__ == "__main__":
    unittest.main()
