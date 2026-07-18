#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE = Path(__file__).resolve().parents[1] / "src" / "pca8_fold_transformer_v1.py"
SPEC = importlib.util.spec_from_file_location("pca8_fold_transformer_v1", MODULE)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class FoldLocalPCA8Test(unittest.TestCase):
    def test_fit_is_train_only_and_transform_does_not_mutate_state(self):
        rng = np.random.default_rng(1931)
        train = rng.normal(size=(40, 12))
        score_a = rng.normal(size=(7, 12))
        score_b = score_a.copy()
        score_b[:, 0] += 1000.0
        state = mod.fit_pca8(train)
        components_before = state.components.copy()
        transformed_a = mod.transform_pca8(score_a, state)
        transformed_b = mod.transform_pca8(score_b, state)
        self.assertEqual(transformed_a.shape, (7, 8))
        self.assertFalse(np.allclose(transformed_a, transformed_b))
        self.assertTrue(np.array_equal(components_before, state.components))

    def test_constant_columns_are_filtered_from_train_only(self):
        rng = np.random.default_rng(42)
        train = rng.normal(size=(30, 12))
        train[:, 3] = 5.0
        state = mod.fit_pca8(train)
        self.assertNotIn(3, state.retained_columns.tolist())


if __name__ == "__main__":
    unittest.main()
