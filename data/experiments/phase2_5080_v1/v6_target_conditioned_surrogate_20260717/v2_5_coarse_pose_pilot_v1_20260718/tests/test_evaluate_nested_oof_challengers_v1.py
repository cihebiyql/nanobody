#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))
MODULE = ROOT / "evaluate_nested_oof_challengers_v1.py"
SPEC = importlib.util.spec_from_file_location("evaluate_nested_oof_challengers_v1", MODULE)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class NestedOOFUtilitiesTest(unittest.TestCase):
    def test_hierarchical_weights_equalize_sources_and_parents(self):
        ids = ["a1", "a2", "b1", "c1", "c2", "c3"]
        metadata = {
            "a1": {"teacher_source": "S1", "parent_framework_cluster": "A"},
            "a2": {"teacher_source": "S1", "parent_framework_cluster": "A"},
            "b1": {"teacher_source": "S1", "parent_framework_cluster": "B"},
            "c1": {"teacher_source": "S2", "parent_framework_cluster": "C"},
            "c2": {"teacher_source": "S2", "parent_framework_cluster": "C"},
            "c3": {"teacher_source": "S2", "parent_framework_cluster": "C"},
        }
        weights = mod.hierarchical_weights(ids, metadata)
        self.assertAlmostEqual(weights[:3].sum(), weights[3:].sum())
        self.assertAlmostEqual(weights[:2].sum(), weights[2])

    def test_exact_min_is_derived_not_independent(self):
        values = np.array([[0.4, 0.6], [0.8, 0.3]])
        self.assertTrue(np.array_equal(mod.exact_min(values), np.array([0.4, 0.3])))

    def test_ridge_prediction_is_finite(self):
        rng = np.random.default_rng(5)
        x = rng.normal(size=(30, 5)); y = rng.normal(size=(30, 2)); z = rng.normal(size=(4, 5))
        prediction = mod.ridge_predict(x, y, z, np.ones(30), 1.0)
        self.assertEqual(prediction.shape, (4, 2))
        self.assertTrue(np.isfinite(prediction).all())


if __name__ == "__main__":
    unittest.main()
