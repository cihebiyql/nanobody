#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("fast_gate_pvrig_formal_candidates.py")
SPEC = importlib.util.spec_from_file_location("fast_gate_pvrig_formal_candidates", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class FastGatePVRIGCandidatesTest(unittest.TestCase):
    def test_aligned_identity_handles_length_difference(self) -> None:
        self.assertEqual(MOD.aligned_identity("ABCDE", "ABXDE"), 80.0)
        self.assertEqual(MOD.aligned_identity("ABCDE", "ABCDEY"), 100.0 * 5 / 6)

    def test_liability_helpers(self) -> None:
        self.assertEqual(MOD.glyco_motifs("ANNSTNPT"), ["NNS"])
        self.assertEqual(MOD.longest_run("QQAVILWQQ", MOD.HYDROPHOBIC), 5)
        self.assertEqual(MOD.max_homopolymer("AAABBBBBCC"), 5)

    def test_all_known_positive_cdrs_resolve(self) -> None:
        positives = MOD.load_positive_cdrs(MOD.DEFAULT_POSITIVES)
        self.assertEqual(len(positives), 11)
        self.assertTrue(all(row["cdr1"] and row["cdr2"] and row["cdr3"] for row in positives))


if __name__ == "__main__":
    unittest.main()
