#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "src" / "audit_and_compress_features_v1.py"
SPEC = importlib.util.spec_from_file_location("audit_and_compress_features_v1", MODULE)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class CompactFeaturesTest(unittest.TestCase):
    def test_compact_row_is_symmetric_and_12d(self):
        row = {
            "candidate_id": "X",
            "8x6b__best_composite": "0.7", "9e6y__best_composite": "0.5",
            "8x6b__top20_composite_mean": "0.6", "9e6y__top20_composite_mean": "0.4",
            "8x6b__best_shape": "0.8", "9e6y__best_shape": "0.6",
            "8x6b__best_hotspot": "0.9", "9e6y__best_hotspot": "0.7",
            "8x6b__best_cdr3_orientation": "0.3", "9e6y__best_cdr3_orientation": "0.4",
            "dual__common_acceptable_fraction": "0.2",
            "dual__acceptable_jaccard": "0.25",
            "dual__top20_min_composite_std": "0.03",
        }
        output = mod.compact_row(row)
        numeric = [field for field in output if field not in {"candidate_id", "feature_schema"}]
        self.assertEqual(len(numeric), 12)
        self.assertAlmostEqual(output["sym_best_composite_mean"], 0.6)
        self.assertAlmostEqual(output["sym_best_composite_min"], 0.5)
        self.assertAlmostEqual(output["sym_best_composite_gap"], 0.2)


if __name__ == "__main__":
    unittest.main()
