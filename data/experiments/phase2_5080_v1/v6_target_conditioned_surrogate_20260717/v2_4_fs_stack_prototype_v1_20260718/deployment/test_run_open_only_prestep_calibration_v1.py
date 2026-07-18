import json
import tempfile
import unittest
from pathlib import Path

from . import run_open_only_prestep_calibration_v1 as mod


class CalibrationRunnerTests(unittest.TestCase):
    def manifest(self):
        return {
            "claim_boundary": "computational only",
            "artifacts": {
                "trainer": {"sha256": "a" * 64},
                "calibration_runner": {"sha256": "b" * 64},
            },
            "calibration_contract": {
                "fixed_grid": [0.0001, 0.001],
                "pair_to_marginal_ratio": 0.5,
                "target_gradient_fraction_band": [0.05, 0.2],
                "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0},
            },
        }

    def observation(self, lane):
        marginal = 0.001
        return {
            "status": "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4",
            "lane": lane, "open_only": True, "optimizer_constructed": False,
            "optimizer_steps_before_observation": 0, "outer_metrics_access_count": 0,
            "prediction_metrics_access_count": 0, "v4_f_test32_access_count": 0,
            "fixed_grid": [0.0001, 0.001], "pair_to_marginal_ratio": 0.5,
            "target_gradient_fraction_band": [0.05, 0.2],
            "selected_contact_weights": {
                "marginal": marginal,
                "pair": 0.0 if lane == "C_SPLIT_MARGINAL" else marginal * 0.5,
            },
        }

    def test_aggregates_real_lane_observation_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); manifest_path = root / "manifest.json"; manifest_path.write_text("{}")
            observations = {}
            for lane in mod.CALIBRATION_LANES:
                path = root / f"{lane}.json"; payload = self.observation(lane)
                path.write_text(json.dumps(payload)); observations[lane] = (path, payload, lane)
            receipt = mod.aggregate_receipt(manifest_path, self.manifest(), observations)
            self.assertEqual(receipt["optimizer_steps_before_observation"], 0)
            self.assertFalse(receipt["implementation_freeze_created"])
            self.assertEqual(receipt["frozen_lane_contact_weights"]["A_VHH_ONLY"], {"marginal": 0.0, "pair": 0.0})

    def test_rejects_post_step_observation(self):
        payload = self.observation("C_SPLIT_MARGINAL")
        payload["optimizer_steps_before_observation"] = 1
        with self.assertRaisesRegex(mod.deployment.DeploymentError, "optimizer_step_nonzero"):
            mod.validate_observation(payload, self.manifest(), "C_SPLIT_MARGINAL")


if __name__ == "__main__":
    unittest.main()
