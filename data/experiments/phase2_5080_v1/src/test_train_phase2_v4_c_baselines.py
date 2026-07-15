#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("train_phase2_v4_c_baselines.py")
SPEC = importlib.util.spec_from_file_location("train_phase2_v4_c_baselines", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class TrainV4CBaselinesTest(unittest.TestCase):
    def synthetic_rows(self) -> list[dict[str, str]]:
        rows = []
        for group in range(20):
            for replicate in range(3):
                cdr3 = "CAR" + "A" * (group % 5 + 2) + "Y" * replicate
                rows.append(
                    {
                        "candidate_id": f"c{group:02d}_{replicate}",
                        "sequence": "QVQLVESGGGLVQPGGSLRLSCAAS" + "A" * 70 + cdr3 + "WGQGTLVTVSS",
                        "cdr1": "GADFSTY",
                        "cdr2": "DGATGF",
                        "cdr3": cdr3,
                        "near_cdr3_family_id": f"f{group:02d}",
                        "scaffold_id": ["s1", "s2", "s3"][group % 3],
                        "phase": f"P{group % 6 + 1}",
                        "selection_bucket": f"b{group % 5}",
                        "h3_regime": "L" if group % 4 else "S",
                    }
                )
        return rows

    def test_grouped_folds_do_not_split_families(self) -> None:
        rows = self.synthetic_rows()
        folds = MOD.grouped_folds(rows)
        by_family = {}
        for row, fold in zip(rows, folds):
            by_family.setdefault(row["near_cdr3_family_id"], set()).add(fold)
        self.assertTrue(all(len(values) == 1 for values in by_family.values()))
        self.assertEqual(set(folds), set(range(MOD.FOLDS)))

    def test_ridge_learns_simple_sequence_signal(self) -> None:
        rows = self.synthetic_rows()
        y = np.asarray([len(row["cdr3"]) / 20.0 for row in rows])
        folds = MOD.grouped_folds(rows)
        _alpha, prediction, score = MOD.select_alpha(rows, y, "cdr3_only", folds)
        self.assertGreater(score["spearman"], 0.8)
        self.assertGreater(MOD.ndcg(y, prediction), 0.9)

    def test_rank_metrics_have_expected_bounds(self) -> None:
        y = np.asarray([0.1, 0.2, 0.3, 0.4])
        self.assertAlmostEqual(MOD.spearman(y, y), 1.0)
        self.assertAlmostEqual(MOD.ndcg(y, y), 1.0)
        self.assertAlmostEqual(MOD.top_quartile_recall(y, y), 1.0)
        self.assertEqual(MOD.spearman(y, np.ones_like(y)), 0.0)


if __name__ == "__main__":
    unittest.main()
