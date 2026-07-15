#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v4_c_sequence_support.py")
SPEC = importlib.util.spec_from_file_location("build_phase2_v4_c_sequence_support", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BuildV4CSequenceSupportTest(unittest.TestCase):
    def test_levenshtein(self) -> None:
        self.assertEqual(MOD.levenshtein("CAR", "CAR"), 0)
        self.assertEqual(MOD.levenshtein("CAR", "CAAR"), 1)
        self.assertAlmostEqual(MOD.normalized_edit_distance("CAR", "CAAR"), 0.25)

    def test_identical_kmer_vectors_have_zero_distance(self) -> None:
        vector = MOD.kmer_vector("QVQLVESGGGLVQPGGSLRLSCAAS")
        self.assertAlmostEqual(float(1.0 - vector @ vector), 0.0)

    def test_thresholds_require_cross_family_neighbors(self) -> None:
        rows = [
            {"sequence": "QVQLVESGGGLVQPGGSLRLSCAAS", "cdr3": "CARAAA", "near_cdr3_family_id": "f1"},
            {"sequence": "QVQLVESGGGLVQPGGSLRLSCAAT", "cdr3": "CARAAT", "near_cdr3_family_id": "f2"},
        ]
        full, cdr3 = MOD.leave_family_out_thresholds(rows)
        self.assertGreaterEqual(full, 0.0)
        self.assertGreaterEqual(cdr3, 0.0)


if __name__ == "__main__":
    unittest.main()
