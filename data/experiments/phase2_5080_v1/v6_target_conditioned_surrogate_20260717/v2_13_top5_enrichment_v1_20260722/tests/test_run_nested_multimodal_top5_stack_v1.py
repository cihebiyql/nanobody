from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


PKG = Path(__file__).resolve().parents[1]


def load_module():
    path = PKG / "src/run_nested_multimodal_top5_stack_v1.py"
    spec = importlib.util.spec_from_file_location("v213_nested_top5_stack_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def synthetic_dataset() -> MOD.Dataset:
    rng = np.random.default_rng(43)
    count = 500
    parents = [f"P{index//50:02d}" for index in range(count)]
    folds = np.asarray([(index//50) % 5 for index in range(count)], dtype=np.int64)
    signal = rng.uniform(0.15, 0.85, size=count)
    truth = np.column_stack([signal + rng.normal(0, 0.02, count), signal + rng.normal(0, 0.02, count)])
    noise = {"S0": 0.08, "M2": 0.07, "C2": 0.09, "B": 0.06}
    bases = {
        name: truth + rng.normal(0, scale, size=truth.shape)
        for name, scale in noise.items()
    }
    return MOD.Dataset(
        [f"C{index:04d}" for index in range(count)],
        [f"{index:064x}" for index in range(count)],
        parents,
        folds,
        truth,
        bases,
        rng.uniform(0, 0.03, count),
        rng.uniform(0, 1, count),
        MOD.exact_min(bases["B"] + rng.normal(0, 0.01, size=truth.shape)),
    )


CONTRACT = {
    "positive_ridge_alpha_grid": [0.1, 1.0],
    "logistic_c_grid": [0.01, 0.1],
    "hgb": {
        "max_depth": 2,
        "max_iter": 16,
        "learning_rate": 0.05,
        "min_samples_leaf": 32,
        "l2_regularization": 5.0,
    },
    "promotion_gate": {
        "minimum_ef5_increment": 0.1,
        "maximum_ef10_decrement": 0.1,
        "maximum_median_fold_ef5_decrement": 0.2,
        "maximum_worst_fold_ef5_decrement": 0.5,
        "minimum_folds_with_delta_at_least_minus_0p5": 4,
        "minimum_single_fold_delta": -1.0,
    },
}


class NestedTop5StackTests(unittest.TestCase):
    def test_weight_grid_is_bounded_simplex(self) -> None:
        grid = MOD.weight_grid()
        self.assertGreater(len(grid), 1)
        for weights in grid:
            self.assertAlmostEqual(float(weights.sum()), 1.0)
            self.assertTrue(np.all(weights >= 0.1))
            self.assertTrue(np.all(weights <= 0.5))

    def test_nested_oof_is_complete_and_finite(self) -> None:
        data = synthetic_dataset()
        scores, hyperparameters, models = MOD.nested_oof(data, CONTRACT)
        self.assertEqual(set(scores), set(MOD.METHODS))
        self.assertEqual(set(hyperparameters), {"0", "1", "2", "3", "4"})
        self.assertEqual(set(models), {"0", "1", "2", "3", "4"})
        for score in scores.values():
            self.assertEqual(score.shape, (500,))
            self.assertTrue(np.isfinite(score).all())

    def test_meta_features_are_label_free_shape_19(self) -> None:
        data = synthetic_dataset()
        train = np.flatnonzero(data.folds != 0)
        test = np.flatnonzero(data.folds == 0)
        transform = MOD.fit_transform(data, train)
        features = MOD.transform_features(data, test, transform)
        self.assertEqual(features.shape, (len(test), 19))
        self.assertTrue(np.isfinite(features).all())

    def test_promotion_falls_back_when_no_increment(self) -> None:
        base = {
            "pooled_ef5": 3.0, "pooled_ef10": 2.0, "binary_ndcg_true_top10_at_budget5": 0.4,
            "spearman": 0.5, "fold_ef5": [3.0]*5, "median_fold_ef5": 3.0, "worst_fold_ef5": 3.0,
        }
        observed = {name: dict(base) for name in MOD.METHODS}
        selected, audit = MOD.select_method(observed, CONTRACT)
        self.assertEqual(selected, "F0_EQUAL_RANK4")
        self.assertTrue(all(not value["eligible"] for value in audit.values()))


if __name__ == "__main__":
    unittest.main()
