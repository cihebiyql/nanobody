import csv
import tempfile
import unittest
from pathlib import Path

from .diagnose_prearchitecture_limits_v1 import build_diagnostic


class PrearchitectureDiagnosticTests(unittest.TestCase):
    def test_oracle_cap_and_candidate_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.tsv"
            prediction = root / "prediction.tsv"
            teacher_fields = [
                "candidate_id", "parent_framework_cluster", "target_patch_id", "design_mode",
                "development_reliability_tier", "teacher_uncertainty", "R_8X6B", "R_9E6Y", "R_dual_min",
            ]
            prediction_fields = [
                "candidate_id", "lane", "truth_R8", "truth_R9", "M2_R8", "M2_R9",
            ]
            teacher_rows = [
                ["a", "p1", "A", "H3", "A", "0.01", "0.60", "0.55", "0.55"],
                ["b", "p2", "B", "H1H3", "B", "0.02", "0.40", "0.45", "0.40"],
            ]
            prediction_rows = [
                ["a", "A_VHH_ONLY", "0.60", "0.55", "0.50", "0.54"],
                ["b", "A_VHH_ONLY", "0.40", "0.45", "0.41", "0.46"],
            ]
            for path, fields, rows in (
                (teacher, teacher_fields, teacher_rows),
                (prediction, prediction_fields, prediction_rows),
            ):
                with path.open("w", newline="") as handle:
                    writer = csv.writer(handle, delimiter="\t")
                    writer.writerow(fields)
                    writer.writerows(rows)
            payload = build_diagnostic(teacher, [prediction], [0.02])
            self.assertEqual(payload["rows"], 2)
            cap = payload["oracle_clipped_m2_residual"]["cap_0.020"]
            self.assertEqual(cap["receptors"]["R8"]["required_residual_abs_gt_cap_fraction"], 0.5)
            self.assertEqual(payload["inputs"]["sealed_v4_f_access_count"], 0)


if __name__ == "__main__":
    unittest.main()
