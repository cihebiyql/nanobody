#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("collect_early_enrichment_v1.py")
SPEC = importlib.util.spec_from_file_location("early", MODULE_PATH)
assert SPEC and SPEC.loader
early = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(early)


class EarlyEnrichmentTests(unittest.TestCase):
    def test_perfect_top10_enrichment(self) -> None:
        truth = {f"c{i:03d}": float(100 - i) for i in range(100)}
        result = early.enrichment_block(truth, truth)
        block = result["true_top_10pct"]["budgets"]["pred_top_10pct"]
        self.assertEqual(block["hits"], 10)
        self.assertAlmostEqual(block["recall"], 1.0)
        self.assertAlmostEqual(block["precision"], 1.0)
        self.assertAlmostEqual(block["enrichment_factor"], 10.0)
        self.assertAlmostEqual(block["binary_ndcg"], 1.0)

    def test_ceil_budget_contract(self) -> None:
        truth = {f"c{i:03d}": float(i) for i in range(184)}
        result = early.enrichment_block(truth, truth)
        self.assertEqual(result["true_top_10pct"]["positive_count"], 19)
        self.assertEqual(result["true_top_20pct"]["positive_count"], 37)
        self.assertEqual(result["true_top_10pct"]["budgets"]["pred_top_5pct"]["budget_count"], 10)
        self.assertEqual(
            result["true_top_10pct"]["budgets"]["pred_top_5pct"]["floor_rounding_sensitivity"]["budget_count"],
            9,
        )

    def test_ensemble_derives_min_after_receptor_mean(self) -> None:
        maps = [
            {"a": {"R8": 0.1, "R9": 0.9}},
            {"a": {"R8": 0.9, "R9": 0.1}},
        ]
        self.assertAlmostEqual(early.aggregate(maps)["a"], 0.5)

    def test_within_parent_perfect(self) -> None:
        truth = {f"c{i}": {"parent": "p", "Rdual": float(i)} for i in range(10)}
        pred = {candidate: row["Rdual"] for candidate, row in truth.items()}
        block = early.within_parent(truth, pred)
        self.assertAlmostEqual(block["macro_recall_true_top20_at_pred_top20"], 1.0)
        self.assertAlmostEqual(block["macro_enrichment_true_top20_at_pred_top20"], 5.0)

    def test_dcg_is_finite(self) -> None:
        self.assertTrue(math.isfinite(early.dcg([1, 0, 1])))

    def test_boundary_tie_reports_hit_bounds(self) -> None:
        prediction = {"a": 1.0, "b": 0.5, "c": 0.5, "d": 0.5, "e": 0.0}
        block = early.boundary_tie_hits({"a", "d"}, prediction, 2)
        self.assertEqual(block["cutoff_exact_tie_count"], 3)
        self.assertEqual(block["slots_selected_from_cutoff_tie"], 1)
        self.assertEqual(block["worst_case_hits"], 1)
        self.assertEqual(block["best_case_hits"], 2)
        self.assertAlmostEqual(block["uniform_random_tie_expected_hits"], 4 / 3)
        self.assertEqual(block["deterministic_candidate_id_tiebreak_hits"], 1)

    def test_score_tie_diagnostics(self) -> None:
        block = early.score_tie_diagnostics({"a": 1.0, "b": 0.5, "c": 0.5})
        self.assertEqual(block["unique_score_count"], 2)
        self.assertEqual(block["maximum_exact_tie_size"], 2)
        self.assertEqual(block["rows_in_nontrivial_exact_ties"], 2)


if __name__ == "__main__":
    unittest.main()
