import pathlib
import sys
import unittest

import numpy as np


HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_m2_exact_min_baselines_v1 as mod


class M2DiagnosticTests(unittest.TestCase):
    def test_hierarchical_weights_balance_sources_and_parents(self):
        rows = [
            {"teacher_source": "A", "parent_framework_cluster": "A1", "development_reliability_weight": "1"},
            {"teacher_source": "A", "parent_framework_cluster": "A1", "development_reliability_weight": "0.5"},
            {"teacher_source": "A", "parent_framework_cluster": "A2", "development_reliability_weight": "1"},
            {"teacher_source": "B", "parent_framework_cluster": "B1", "development_reliability_weight": "1"},
        ]
        indices = np.arange(4)
        weights = mod.hierarchical_weights(rows, indices, reliability=False)
        self.assertAlmostEqual(weights[:3].sum(), 0.5)
        self.assertAlmostEqual(weights[3], 0.5)
        self.assertAlmostEqual(weights[:2].sum(), 0.25)
        self.assertAlmostEqual(weights[2], 0.25)

    def test_fixed_tier_only_changes_within_parent_candidate_allocation(self):
        rows = [
            {"teacher_source": "A", "parent_framework_cluster": "A1", "development_reliability_weight": "1"},
            {"teacher_source": "A", "parent_framework_cluster": "A1", "development_reliability_weight": "0.5"},
            {"teacher_source": "B", "parent_framework_cluster": "B1", "development_reliability_weight": "1"},
        ]
        weights = mod.hierarchical_weights(rows, np.arange(3), reliability=True)
        self.assertAlmostEqual(weights[:2].sum(), 0.5)
        self.assertAlmostEqual(weights[0] / weights[1], 2.0)
        self.assertAlmostEqual(weights[2], 0.5)

    def test_ridge_predictions_are_finite(self):
        x = np.arange(24, dtype=float).reshape(8, 3)
        y = np.column_stack((x[:, 0] / 10, x[:, 1] / 10))
        state = mod.fit_ridge(x, y, np.ones(8), 10.0)
        prediction = (x - state[0]) / state[1] @ state[3] + state[2]
        self.assertTrue(np.isfinite(prediction).all())


if __name__ == "__main__":
    unittest.main()
