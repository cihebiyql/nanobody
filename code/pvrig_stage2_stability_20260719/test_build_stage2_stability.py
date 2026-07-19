import importlib.util
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_stage2_stability.py")
SPEC = importlib.util.spec_from_file_location("stage2_stability", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StabilityHelpersTest(unittest.TestCase):
    def test_average_ranks_with_ties(self):
        self.assertEqual(MODULE.average_ranks([10.0, 20.0, 20.0, 30.0]), [1.0, 2.5, 2.5, 4.0])

    def test_correlations(self):
        self.assertTrue(math.isclose(MODULE.pearson([1, 2, 3], [2, 4, 6]), 1.0))
        self.assertTrue(math.isclose(MODULE.spearman([1, 2, 3], [3, 2, 1]), -1.0))

    def test_confidence_factor_is_frozen(self):
        self.assertEqual(MODULE.confidence_factor(0), 0.0)
        self.assertEqual(MODULE.confidence_factor(1), 0.80)
        self.assertEqual(MODULE.confidence_factor(2), 0.90)
        self.assertEqual(MODULE.confidence_factor(3), 1.0)

    def test_percentile_linear_interpolation(self):
        self.assertEqual(MODULE.percentile([0.0, 10.0], 0.5), 5.0)
        self.assertIsNone(MODULE.percentile([], 0.5))


if __name__ == "__main__":
    unittest.main()
