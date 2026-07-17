#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("train_phase2_v4_d_structure_fusion_surrogate_v1.py")
SPEC = importlib.util.spec_from_file_location("structure_fusion_v1", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class StructureFusionTrainerTests(unittest.TestCase):
    def test_group_folds_have_no_group_leakage_and_cover_all_rows(self) -> None:
        groups = [f"G{group:02d}" for group in range(10) for _ in range(group % 3 + 2)]
        folds = MOD.build_group_folds(groups, 5)
        self.assertEqual(sorted(np.concatenate(folds).tolist()), list(range(len(groups))))
        observed = set()
        for fold in folds:
            fold_groups = {groups[index] for index in fold}
            self.assertFalse(observed & fold_groups)
            observed |= fold_groups
        self.assertEqual(observed, set(groups))

    def test_train_only_group_cv_selects_from_frozen_grid(self) -> None:
        rng = np.random.default_rng(7)
        groups = [f"G{group:02d}" for group in range(10) for _ in range(4)]
        x = rng.normal(size=(len(groups), 8))
        y = 0.8 * x[:, 0] - 0.4 * x[:, 1] + rng.normal(scale=0.05, size=len(groups))
        alpha, metrics = MOD.select_alpha_group_cv(x, y, groups)
        self.assertIn(alpha, MOD.ALPHAS)
        self.assertEqual(set(metrics), {str(float(value)) for value in MOD.ALPHAS})
        self.assertTrue(all(np.isfinite(item["spearman"]) for item in metrics.values()))

    def test_dual_ridge_handles_more_features_than_rows(self) -> None:
        rng = np.random.default_rng(11)
        x = rng.normal(size=(24, 80))
        y = x[:, 0] - 0.5 * x[:, 1]
        fitted = MOD.fit_ridge_auto(x, y, 1.0)
        prediction = MOD.base.predict_ridge(x, fitted)
        self.assertGreater(MOD.base.spearman(y, prediction), 0.95)
        self.assertEqual(fitted.coefficient.shape, (80,))

    def test_parent_categorical_unknown_development_group_is_zero(self) -> None:
        train = [
            {"parent_framework_cluster": "A", "design_mode": "H3", "target_patch_id": "P1"},
            {"parent_framework_cluster": "B", "design_mode": "H1H3", "target_patch_id": "P2"},
        ]
        development = [
            {"parent_framework_cluster": "UNSEEN", "design_mode": "H3", "target_patch_id": "P1"}
        ]
        spec = MOD.categorical_spec(train)
        matrix, names = MOD.categorical_matrix(development, spec)
        parent_columns = [index for index, name in enumerate(names) if name.startswith("parent_framework_cluster=")]
        self.assertEqual(float(matrix[0, parent_columns].sum()), 0.0)
        self.assertGreater(float(matrix.sum()), 0.0)

    def test_paired_bootstrap_is_deterministic(self) -> None:
        truth = np.linspace(0.0, 1.0, 32)
        better = truth + 0.01 * np.sin(np.arange(32))
        worse = truth[::-1]
        first = MOD.paired_bootstrap_spearman_delta(truth, better, worse, replicates=200, seed=17)
        second = MOD.paired_bootstrap_spearman_delta(truth, better, worse, replicates=200, seed=17)
        self.assertEqual(first, second)
        self.assertGreater(first["median_delta"], 0.0)
        self.assertGreater(first["positive_fraction"], 0.95)


if __name__ == "__main__":
    unittest.main()
