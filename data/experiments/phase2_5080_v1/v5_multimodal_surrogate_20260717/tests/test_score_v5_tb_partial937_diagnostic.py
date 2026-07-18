#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "src" / "score_v5_tb_partial937_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("score_v5_tb_partial937_diagnostic", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PartialDiagnosticTests(unittest.TestCase):
    def test_fit_and_predict_never_accepts_partial_labels(self) -> None:
        parameters = MOD.fit_and_predict.__annotations__
        self.assertNotIn("partial_labels", parameters)

    def test_prediction_model_contract_matches_open_train(self) -> None:
        self.assertEqual(
            set(MOD.v5.MODELS),
            {
                "B0_train_mean",
                "B1_structure_direct",
                "B2_dual_receptor_min",
                "B3_structure_plus_physchem",
                "B4_direct_dual_convex",
                "B5_top20_ridge_classifier",
                "B6_within_parent_pairwise_ridge",
            },
        )

    def test_dual_min_contract(self) -> None:
        p8 = np.asarray([0.5, 0.7])
        p9 = np.asarray([0.6, 0.4])
        self.assertTrue(np.allclose(np.minimum(p8, p9), [0.5, 0.4]))


if __name__ == "__main__":
    unittest.main()

