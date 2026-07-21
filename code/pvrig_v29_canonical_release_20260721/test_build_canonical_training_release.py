from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_canonical_training_release.py")
SPEC = importlib.util.spec_from_file_location("canonical_release", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GeometryTests(unittest.TestCase):
    def test_threshold_pose_is_class_a_and_margin_one(self) -> None:
        values = {
            "hotspot_overlap": 14,
            "holdout_overlap": 8,
            "total_occlusion": 500,
            "cdr3_occlusion": 100,
            "cdr3_fraction": 0.15,
        }
        self.assertEqual(MODULE.geometry_class_from_values(14, 500, 100, 0.15), "A")
        self.assertAlmostEqual(MODULE.geometry_margin(values), 1.0)

    def test_missing_required_metric_fails_closed(self) -> None:
        with self.assertRaises(MODULE.ReleaseError):
            MODULE.normalized_score_from_raw({"reference_id": "8x6b"})

    def test_exact_min_pair_label(self) -> None:
        self.assertEqual(MODULE.pair_label("A", "A"), "STRICT_A")
        self.assertEqual(MODULE.pair_label("A", "B"), "SUPPORTED_AB")
        self.assertEqual(MODULE.pair_label("A", "E"), "OTHER")


class FamilyTests(unittest.TestCase):
    def test_hamming80_family(self) -> None:
        families = MODULE.cdr3_families(["AAAAAAAAAA", "AAAAAAAATA", "CCCCCCCCCC"])
        self.assertEqual(families["AAAAAAAAAA"], families["AAAAAAAATA"])
        self.assertNotEqual(families["AAAAAAAAAA"], families["CCCCCCCCCC"])

    def test_cross_fold_family_is_quarantined(self) -> None:
        rows = [
            {
                "candidate_id": "a",
                "sequence_sha256": "a",
                "cdr3": "AAAAAAAAAA",
                "parent_framework_cluster": "P1",
                "model_split": "train",
            },
            {
                "candidate_id": "b",
                "sequence_sha256": "b",
                "cdr3": "AAAAAAAATA",
                "parent_framework_cluster": "P2",
                "model_split": "development",
            },
            {
                "candidate_id": "c",
                "sequence_sha256": "c",
                "cdr3": "CCCCCCCCCC",
                "parent_framework_cluster": "P3",
                "model_split": "frozen_test",
            },
        ]
        assignment, audit = MODULE.assign_leakage_safe_splits(rows)
        self.assertEqual(assignment["a"], "train")
        self.assertEqual(assignment["b"], "quarantine_cdr3_overlap")
        self.assertEqual(assignment["c"], "frozen_test")
        self.assertEqual(audit["parent_cross_split_count"], 0)
        self.assertEqual(audit["cdr3_family_cross_split_count"], 0)


if __name__ == "__main__":
    unittest.main()
