from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "src/evaluate_budget_contact_rank_blend.py"
SPEC = importlib.util.spec_from_file_location("evaluate_budget_contact_rank_blend", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BudgetContactBlendTests(unittest.TestCase):
    def test_percentile_train_is_monotonic_and_bounded(self) -> None:
        values = np.asarray([3.0, 1.0, 4.0, 2.0])
        ranks = MOD.percentile_train(values)
        self.assertEqual(ranks.tolist(), [2 / 3, 0.0, 1.0, 1 / 3])
        self.assertTrue(np.all((ranks >= 0.0) & (ranks <= 1.0)))

    def test_percentile_apply_uses_only_reference_distribution(self) -> None:
        reference = np.asarray([1.0, 2.0, 3.0, 4.0])
        values = np.asarray([0.0, 2.5, 5.0])
        np.testing.assert_allclose(MOD.percentile_apply(reference, values), [0.0, 0.5, 1.0])

    def test_gamma_selection_rejects_the_constant_half_blend_when_contact_reverses_order(self) -> None:
        groups = [f"P{index // 5}" for index in range(50)]
        y = np.arange(50, dtype=float)
        c0 = y.copy()
        contact = -y
        gamma, _blend, grid = MOD.select_gamma(y, c0, contact, groups)
        self.assertLess(gamma, 0.5)
        self.assertTrue(grid["0.0"]["eligible"])
        self.assertFalse(grid["0.5"]["eligible"])

    def test_gamma_selection_can_use_contact_when_top20_improves_without_rank_damage(self) -> None:
        rng = np.random.default_rng(17)
        groups = [f"P{index // 10}" for index in range(100)]
        y = np.linspace(0.0, 1.0, 100)
        c0 = y + rng.normal(0.0, 0.08, 100)
        contact = c0.copy()
        contact[-20:] = y[-20:] + 0.2
        gamma, blend, grid = MOD.select_gamma(y, c0, contact, groups)
        self.assertIn(gamma, MOD.GAMMAS)
        self.assertTrue(grid[str(gamma)]["eligible"])
        self.assertEqual(blend.shape, y.shape)


if __name__ == "__main__":
    unittest.main()
