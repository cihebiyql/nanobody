#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

MODULE_PATH = Path(__file__).with_name("train_phase2_v3_p1_pilot_smoke.py")
SPEC = importlib.util.spec_from_file_location("train_phase2_v3_p1_pilot_smoke", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class V3P1PilotSmokeTest(unittest.TestCase):
    def test_parse_residue_label(self) -> None:
        self.assertEqual(MOD.parse_residue_label("A:101:GLY"), ("A", 101, "", "GLY"))
        self.assertEqual(MOD.parse_residue_label("B:57A:ARG"), ("B", 57, "A", "ARG"))

    def test_contact_matrix(self) -> None:
        record = {
            "pair_frequencies": [
                {"vhh_residue": "A:2:ALA", "pvrig_residue": "B:57:ARG", "frequency": 0.75}
            ]
        }
        matrix = MOD.contact_matrix(record, 3, 4, {("B", 57, ""): 1})
        self.assertEqual(tuple(matrix.shape), (3, 4))
        self.assertAlmostEqual(float(matrix[1, 1]), 0.75)

    def test_ordinal_targets_and_spearman(self) -> None:
        targets = MOD.ordinal_targets(torch.tensor([0, 2, 4]))
        self.assertTrue(torch.equal(targets, torch.tensor([[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0]])))
        self.assertAlmostEqual(MOD.spearman([0, 1, 2], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(MOD.spearman([0, 1, 2], [3, 2, 1]), -1.0)

    def test_target_mapping_inventory(self) -> None:
        target = MOD.read_fasta(MOD.DEFAULT_TARGET)
        weights = MOD.target_weights(MOD.DEFAULT_TARGET_MAPPING, target)
        mapping = MOD.pvrig_pdb_to_model_index(MOD.DEFAULT_RECONCILIATION, target)
        self.assertEqual(len(target), 133)
        self.assertEqual(int((weights > 0).sum()), 23)
        self.assertGreater(len(mapping), 100)


if __name__ == "__main__":
    unittest.main()
