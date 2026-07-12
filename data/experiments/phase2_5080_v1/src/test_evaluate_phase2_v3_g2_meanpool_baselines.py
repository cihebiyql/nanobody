#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).with_name("evaluate_phase2_v3_g2_meanpool_baselines.py")
SPEC = importlib.util.spec_from_file_location("evaluate_phase2_v3_g2_meanpool_baselines", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class V3G2MeanPoolEvaluationTest(unittest.TestCase):
    def test_metric_bundle_reports_macro_target_ap(self) -> None:
        metrics = MOD.metric_bundle(
            np.asarray([0, 1, 0, 1]),
            np.asarray([0.1, 0.9, 0.2, 0.8]),
            ["a", "a", "b", "b"],
        )
        self.assertEqual(metrics["macro_target_average_precision"], 1.0)
        self.assertEqual(metrics["target_average_precision"], {"a": 1.0, "b": 1.0})

    def test_eligible_baseline_order_is_frozen(self) -> None:
        self.assertEqual(
            MOD.ELIGIBLE,
            ("prevalence", "frozen_esm2_cosine", "vhh_only", "esm2_pair", "v3_full"),
        )


if __name__ == "__main__":
    unittest.main()
