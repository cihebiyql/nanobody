#!/usr/bin/env python3

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FROZEN_C2_SRC = ROOT.parent / "v2_5_coarse_pose_pilot_v1_20260718" / "src"
sys.path.insert(0, str(FROZEN_C2_SRC))

from c2_fold_local_v1 import (
    fit_fold_local_pca8_ridge,
    predict_fold_local_pca8_ridge,
    select_c2_alpha_inner_oof,
)
from meta_noise_stack_v1 import MetaNoiseError
from evaluate_nested_oof_challengers_v1 import ridge_predict
from pca8_fold_transformer_v1 import fit_pca8, transform_pca8


class C2FoldLocalTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1931)
        self.x = rng.normal(size=(60, 12))
        self.y = np.column_stack([
            0.5 + 0.02 * self.x[:, 0] - 0.01 * self.x[:, 2],
            0.48 + 0.01 * self.x[:, 1] + 0.02 * self.x[:, 3],
        ])
        self.names = [f"feature_{i}" for i in range(self.x.shape[1])]

    def test_fit_accepts_train_only_and_score_cannot_change_model(self):
        model = fit_fold_local_pca8_ridge(
            self.x, self.y, np.ones(len(self.x)), self.names, ridge_alpha=1.0,
        )
        before = dataclasses.asdict(model)
        score_a = np.zeros((7, 12))
        score_b = np.full((7, 12), 1e9)
        pred_a = predict_fold_local_pca8_ridge(model, score_a)
        pred_b = predict_fold_local_pca8_ridge(model, score_b)
        self.assertEqual(before, dataclasses.asdict(model))
        self.assertEqual(pred_a.shape, pred_b.shape)
        self.assertFalse(np.allclose(pred_a, pred_b))

    def test_reproduces_existing_frozen_c2_transform_and_ridge(self):
        score = self.x[:9] + 0.2
        alpha = 10.0
        model = fit_fold_local_pca8_ridge(
            self.x, self.y, np.ones(len(self.x)), self.names, ridge_alpha=alpha,
        )
        observed = predict_fold_local_pca8_ridge(model, score)
        state = fit_pca8(self.x, components=8)
        expected = ridge_predict(
            transform_pca8(self.x, state), self.y,
            transform_pca8(score, state), np.ones(len(self.x)), alpha,
        )
        np.testing.assert_allclose(observed, expected, atol=1e-12, rtol=1e-12)

    def test_identifier_feature_fails_closed(self):
        names = list(self.names)
        names[2] = "parent_id"
        with self.assertRaises(MetaNoiseError):
            fit_fold_local_pca8_ridge(
                self.x, self.y, np.ones(len(self.x)), names, ridge_alpha=1.0,
            )

    def test_inner_oof_alpha_selection_and_largest_tie(self):
        truth = self.y[:20]
        predictions = {
            0.1: truth + 0.01,
            1.0: truth.copy(),
            10.0: truth.copy(),
        }
        selected = select_c2_alpha_inner_oof(truth, predictions, np.ones(len(truth)))
        self.assertEqual(selected, 10.0)


if __name__ == "__main__":
    unittest.main()
