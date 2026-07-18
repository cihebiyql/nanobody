#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "src" / "run_v5_tb_open_train.py"
SPEC = importlib.util.spec_from_file_location("run_v5_tb_open_train", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class V5TBTests(unittest.TestCase):
    def test_pairwise_rows_stay_within_parent_and_respect_margin(self) -> None:
        x = np.asarray([[0.0], [0.1], [1.0], [1.3]], dtype=float)
        y = np.asarray([0.50, 0.51, 0.40, 0.50], dtype=float)
        groups = ["A", "A", "B", "B"]
        pair_x, pair_y, count = MOD.build_pairwise_rows(x, y, groups, 0.02)
        self.assertEqual(count, 1)
        self.assertEqual(pair_x.shape, (2, 1))
        self.assertTrue(np.allclose(pair_y, [-0.10, 0.10]))

    def test_parent_center_removes_group_offsets(self) -> None:
        values = np.asarray([1.0, 3.0, 10.0, 14.0])
        centered = MOD.parent_center(values, ["A", "A", "B", "B"])
        self.assertTrue(np.allclose(centered, [-1.0, 1.0, -2.0, 2.0]))

    def test_dual_crossfit_is_group_disjoint_and_finite(self) -> None:
        rng = np.random.default_rng(7)
        groups = [f"P{i}" for i in range(10) for _ in range(6)]
        x = rng.normal(size=(60, 8))
        y8 = 0.5 + 0.04 * x[:, 0] - 0.02 * x[:, 1]
        y9 = 0.5 + 0.03 * x[:, 0] + 0.01 * x[:, 2]
        p8, p9, pmin = MOD.crossfit_dual(x, y8, y9, groups, 1.0, 5)
        self.assertTrue(np.isfinite(p8).all())
        self.assertTrue(np.isfinite(p9).all())
        self.assertTrue(np.allclose(pmin, np.minimum(p8, p9)))

    def test_nested_evaluate_emits_every_preregistered_model(self) -> None:
        rng = np.random.default_rng(11)
        rows = []
        groups = []
        for parent in range(10):
            for index in range(6):
                rows.append({"candidate_id": f"C{parent}_{index}"})
                groups.append(f"P{parent}")
        structure = rng.normal(size=(60, 12))
        physchem = rng.normal(size=(60, 4))
        y8 = 0.54 + 0.03 * structure[:, 0] - 0.015 * structure[:, 1]
        y9 = 0.55 + 0.025 * structure[:, 0] + 0.01 * structure[:, 2]
        dataset = MOD.Dataset(
            rows=rows,
            structure_x=structure,
            physchem_x=physchem,
            structure_feature_names=[f"f{i}" for i in range(12)],
            y8=y8,
            y9=y9,
            ydual=np.minimum(y8, y9),
            ygap=np.abs(y8 - y9),
            groups=groups,
        )
        result = MOD.nested_evaluate(
            dataset,
            alphas=(0.1, 1.0),
            weights=(0.0, 0.5, 1.0),
            outer_folds=5,
            inner_folds=5,
            pairwise_minimum_delta=0.005,
        )
        self.assertEqual(set(result.predictions), set(MOD.MODELS))
        self.assertTrue(all(np.isfinite(value).all() for value in result.predictions.values()))
        self.assertEqual(sorted(set(result.outer_fold.tolist())), [0, 1, 2, 3, 4])

    def test_top20_average_precision_is_one_for_perfect_ranking(self) -> None:
        y = np.arange(10, dtype=float)
        self.assertAlmostEqual(MOD.average_precision_for_top20(y, y), 1.0)


if __name__ == "__main__":
    unittest.main()

