import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
COLLECTOR_PATH = ROOT / "src" / "collect_residue_oof_v1_5.py"
TRAINER_PATH = ROOT / "src" / "train_nested_residue_surrogate_v1_5.py"
GOVERNANCE = ROOT.parent / "PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json"
FREEZE = ROOT / "IMPLEMENTATION_FREEZE_V1_5.json"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


collector = load("residue_collector_v1_5", COLLECTOR_PATH)
trainer = load("residue_trainer_v1_5", TRAINER_PATH)


def clear_improvement_rows():
    return [
        {
            "candidate_id": f"candidate_{index}",
            "parent_framework_cluster": "parent_a" if index < 2 else "parent_b",
            "outer_fold": 0 if index < 2 else 1,
            "R_dual_min": float(index),
            "m2_prediction": float(3 - index),
            "residue_prediction": float(index),
        }
        for index in range(4)
    ]


class TestV15VersionContract(unittest.TestCase):
    def test_schema_labels_are_v15_but_frozen_matrix_is_unchanged(self):
        self.assertEqual(collector.SCHEMA_VERSION, "pvrig_v6_residue_v1_5_oof_collector")
        self.assertEqual(trainer.SCHEMA_VERSION, "pvrig_v6_nested_residue_surrogate_v1_5")
        self.assertEqual(collector.COLLECTOR_MATRIX, trainer.COLLECTOR_MATRIX)
        self.assertEqual(
            collector.COLLECTOR_MATRIX["schema_version"],
            "pvrig_v6_residue_v1_4_collector_matrix",
        )
        self.assertEqual(
            collector.COLLECTOR_MATRIX_SHA256,
            "6d0f3cbcc155564f0ba9e4dadd8d646405bc31072e4e3ab25b11316edb4d2116",
        )
        self.assertEqual(collector.FORMAL_EVIDENCE_LABELS, trainer.FORMAL_EVIDENCE_LABELS)
        collector.validate_formal_evidence_labels(
            {"formal_evidence_labels": dict(collector.FORMAL_EVIDENCE_LABELS)}
        )
        trainer.validate_formal_evidence_labels(
            {"formal_evidence_labels": dict(trainer.FORMAL_EVIDENCE_LABELS)}
        )
        tampered = {"formal_evidence_labels": dict(collector.FORMAL_EVIDENCE_LABELS)}
        tampered["formal_evidence_labels"]["positive_status"] = "PROMOTE_RESIDUE_V1_3_OVER_M2"
        with self.assertRaisesRegex(Exception, "freeze_formal_evidence_labels_mismatch"):
            collector.validate_formal_evidence_labels(tampered)

    def test_positive_promotion_label_is_exactly_v15(self):
        bootstrap = {
            "positive_fraction": 0.80,
            "median_delta_spearman": 0.01,
            "ci95_lower": -0.1,
            "ci95_upper": 0.2,
        }
        decision = collector.promotion_decision(clear_improvement_rows(), bootstrap)
        self.assertEqual(decision["status"], "PROMOTE_RESIDUE_V1_5_OVER_M2")
        self.assertTrue(all(decision["gates"].values()))
        self.assertNotIn("V1_3", decision["status"])
        self.assertNotIn("V1_4", decision["status"])

    def test_negative_promotion_label_is_exactly_v15(self):
        bootstrap = {
            "positive_fraction": 0.79,
            "median_delta_spearman": 0.01,
            "ci95_lower": -0.1,
            "ci95_upper": 0.2,
        }
        decision = collector.promotion_decision(clear_improvement_rows(), bootstrap)
        self.assertEqual(decision["status"], "DO_NOT_PROMOTE_RESIDUE_V1_5")
        self.assertFalse(decision["gates"]["parent_bootstrap_direction_stable"])
        self.assertNotIn("V1_3", decision["status"])
        self.assertNotIn("V1_4", decision["status"])

    def test_real_v15_freeze_closes_for_trainer_and_collector(self):
        collector_hashes = collector.validate_implementation_freeze(FREEZE, ROOT, GOVERNANCE)
        trainer_hashes = trainer.validate_implementation_freeze(FREEZE, ROOT, GOVERNANCE)
        self.assertEqual(collector_hashes, trainer_hashes)
        self.assertEqual(
            collector_hashes["src/collect_residue_oof_v1_5.py"],
            collector.sha256_file(COLLECTOR_PATH),
        )
        self.assertEqual(
            trainer_hashes["src/train_nested_residue_surrogate_v1_5.py"],
            trainer.sha256_file(TRAINER_PATH),
        )


if __name__ == "__main__":
    unittest.main()
