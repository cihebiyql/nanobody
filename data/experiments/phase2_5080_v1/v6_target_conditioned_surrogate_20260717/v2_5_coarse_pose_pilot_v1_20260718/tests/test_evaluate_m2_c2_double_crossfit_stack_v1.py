import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evaluate_m2_c2_double_crossfit_stack_v1 import (  # noqa: E402
    fit_m2_ridge,
    fit_nonnegative_shared_slope,
    m2_hierarchical_weights,
    stack_predict,
)


class StrictDoubleCrossfitStackUtilitiesTest(unittest.TestCase):
    def test_meta_head_is_shared_nonnegative_convex_slope(self):
        truth = np.asarray([[0.2, 0.3], [0.4, 0.5], [0.7, 0.8]])
        m2 = truth - 0.10
        c2 = truth + 0.02
        weight, audit = fit_nonnegative_shared_slope(
            truth, m2, c2, np.ones(3) / 3.0, penalty=0.001,
        )
        self.assertGreaterEqual(weight, 0.0)
        self.assertLessEqual(weight, 1.0)
        self.assertAlmostEqual(audit["m2_weight"] + audit["c2_weight"], 1.0)
        stacked = stack_predict(m2, c2, weight)
        np.testing.assert_allclose(stacked, (1.0 - weight) * m2 + weight * c2)

    def test_harmful_c2_is_clipped_to_zero(self):
        truth = np.asarray([[0.2, 0.3], [0.4, 0.5]])
        m2 = truth.copy()
        c2 = truth + 1.0
        weight, _ = fit_nonnegative_shared_slope(
            truth, m2, c2, np.ones(2) / 2.0, penalty=0.001,
        )
        self.assertEqual(weight, 0.0)

    def test_m2_weights_equalize_sources_and_parents(self):
        metadata = {
            "a": {"teacher_source": "S1", "parent_framework_cluster": "P1"},
            "b": {"teacher_source": "S1", "parent_framework_cluster": "P1"},
            "c": {"teacher_source": "S1", "parent_framework_cluster": "P2"},
            "d": {"teacher_source": "S2", "parent_framework_cluster": "P3"},
        }
        weights = m2_hierarchical_weights(["a", "b", "c", "d"], metadata)
        self.assertAlmostEqual(float(weights.sum()), 1.0)
        self.assertAlmostEqual(float(weights[0] + weights[1] + weights[2]), 0.5)
        self.assertAlmostEqual(float(weights[3]), 0.5)
        self.assertAlmostEqual(float(weights[0] + weights[1]), float(weights[2]))

    def test_m2_ridge_returns_two_finite_outputs(self):
        rng = np.random.default_rng(11)
        x = rng.normal(size=(30, 7))
        y = rng.normal(size=(30, 2))
        prediction = fit_m2_ridge(x[:24], y[:24], x[24:], np.ones(24) / 24.0, 10.0)
        self.assertEqual(prediction.shape, (6, 2))
        self.assertTrue(np.isfinite(prediction).all())


if __name__ == "__main__":
    unittest.main()
