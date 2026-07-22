from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/evaluate_multiseed_clean_attention_v1_1.py"


def import_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


MOD = import_module("v211_clean_attention_evaluator_v1_1_test", SOURCE)


class Float32TruthClosureTests(unittest.TestCase):
    def make_seed(self, root: Path, serialized_target: float) -> tuple[Path, dict[str, object]]:
        seed_dir = root / "D1_seed43"
        seed_dir.mkdir()
        prediction = seed_dir / MOD.RUNNER.PREDICTION_NAME
        fields = (
            "candidate_id", "parent_framework_cluster", "target_R_8X6B", "target_R_9E6Y",
            "target_R_dual_min", "prediction_R_8X6B", "prediction_R_9E6Y",
            "prediction_R_dual_min", "exact_min_abs_error",
        )
        with prediction.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerow({
                "candidate_id": "C1",
                "parent_framework_cluster": "P1",
                "target_R_8X6B": f"{serialized_target:.12g}",
                "target_R_9E6Y": "0.6",
                "target_R_dual_min": f"{serialized_target:.12g}",
                "prediction_R_8X6B": "0.51",
                "prediction_R_9E6Y": "0.52",
                "prediction_R_dual_min": "0.51",
                "exact_min_abs_error": "0",
            })
        digest = hashlib.sha256(prediction.read_bytes()).hexdigest()
        (seed_dir / MOD.RUNNER.RESULT_NAME).write_text(json.dumps({
            "status": "PASS_FULL10644_CLEAN_ATTENTION_FIXED_EPOCH_TRAINING",
            "lane": MOD.RUNNER.LANE,
            "seed": 43,
            "exact_min_inference": True,
            "outputs": {MOD.RUNNER.PREDICTION_NAME: digest},
        }), encoding="utf-8")
        truth = {"C1": MOD.RUNNER.CandidateRow("C1", "0" * 64, "ACDE", "P1", 1.0, (0.534006387, 0.6))}
        return seed_dir, truth

    def test_accepts_observed_ieee754_float32_roundtrip_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            seed_dir, truth = self.make_seed(Path(temporary), 0.534006416798)
            prediction, _hashes, audit = MOD.load_seed_prediction(seed_dir, 43, truth)
            self.assertEqual(prediction.shape, (1, 2))
            self.assertGreater(audit["max_receptor_truth_abs_diff"], 2e-8)
            self.assertLessEqual(audit["max_receptor_truth_abs_diff"], MOD.FLOAT32_TRUTH_ATOL)

    def test_rejects_error_above_frozen_v1_1_tolerance(self):
        with tempfile.TemporaryDirectory() as temporary:
            seed_dir, truth = self.make_seed(Path(temporary), 0.534006428)
            with self.assertRaisesRegex(MOD.RUNNER.CleanAttentionError, "seed_truth_mismatch"):
                MOD.load_seed_prediction(seed_dir, 43, truth)


if __name__ == "__main__":
    unittest.main()
