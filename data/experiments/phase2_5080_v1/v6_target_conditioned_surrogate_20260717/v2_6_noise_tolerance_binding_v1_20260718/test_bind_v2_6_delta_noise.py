#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("binding", ROOT / "bind_v2_6_delta_noise.py")
assert spec and spec.loader
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)


class BindingTests(unittest.TestCase):
    def test_mad(self):
        self.assertAlmostEqual(binding.median_absolute_deviation([1.0, 2.0, 10.0]), 1.0)

    def test_formula_and_lower_clip(self):
        values = {f"C{i}": [0.5, 0.501, 0.499] for i in range(5)}
        result = binding.bind_delta_noise(values)
        self.assertAlmostEqual(result["unclipped_delta_noise"], 0.001 * 1.4826 * math.sqrt(2))
        self.assertEqual(result["delta_noise"], 0.01)

    def test_upper_clip(self):
        values = {f"C{i}": [0.1, 0.5, 0.9] for i in range(5)}
        self.assertEqual(binding.bind_delta_noise(values)["delta_noise"], 0.03)

    def test_rejects_non_three_seed_candidate(self):
        with self.assertRaisesRegex(binding.BindingError, "not_exactly_three"):
            binding.bind_delta_noise({"C1": [0.1, 0.2]})


if __name__ == "__main__":
    unittest.main()
