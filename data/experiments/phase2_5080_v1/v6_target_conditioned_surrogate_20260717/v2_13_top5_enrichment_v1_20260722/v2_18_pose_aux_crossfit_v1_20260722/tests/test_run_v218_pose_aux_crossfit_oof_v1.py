from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "run_v218_pose_aux_crossfit_oof_v1.py"
SPEC = importlib.util.spec_from_file_location("v218_runner", SOURCE)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class CrossfitTests(unittest.TestCase):
    def test_parent_folds_do_not_overlap(self) -> None:
        parents = np.asarray([f"P{i//3}" for i in range(15)])
        indices = np.arange(15)
        folds = MOD.balanced_parent_folds(parents, indices, 4)
        self.assertEqual(set(np.concatenate(folds).tolist()), set(indices.tolist()))
        for fold in folds:
            train = np.setdiff1d(indices, fold)
            self.assertFalse(set(parents[train]) & set(parents[fold]))

    def test_top_weight_is_positive_and_prioritizes_high_truth(self) -> None:
        truth = np.linspace(0.0, 1.0, 100)
        weight = MOD.top_weight(truth, np.ones(100))
        self.assertTrue(np.all(weight > 0))
        self.assertGreater(weight[-1], weight[0] * 3.0)

    def test_raw_feature_firewall(self) -> None:
        names = [f"ALL__f{i}" for i in range(162)] + ["candidate_id", "R_dual_min"]
        observed = MOD.raw_feature_names(names)
        self.assertEqual(len(observed), 162)
        self.assertNotIn("candidate_id", observed)
        self.assertNotIn("R_dual_min", observed)


if __name__ == "__main__":
    unittest.main()
