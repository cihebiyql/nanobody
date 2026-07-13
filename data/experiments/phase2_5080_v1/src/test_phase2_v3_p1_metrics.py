#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phase2_v3_p1_metrics import (
    enrichment_factor_at_fraction,
    geometry_metrics,
    ndcg,
    ordinal_ranking_metrics,
    paired_parent_cluster_bootstrap,
    paired_parent_cluster_permutation,
    recall_at_fraction,
    spearman_correlation,
)


class V3P1MetricsTest(unittest.TestCase):
    def test_primary_ranking_metrics(self) -> None:
        relevance = [4, 3, 2, 1, 4, 3, 2, 1, 0, 0]
        scores = [10, 8, 6, 4, 9, 7, 5, 3, 2, 1]
        recall = recall_at_fraction(relevance, scores, 0.20)
        enrichment = enrichment_factor_at_fraction(relevance, scores, 0.10)
        metrics = ordinal_ranking_metrics(relevance, scores)
        self.assertEqual(recall["positive_found"], 2)
        self.assertAlmostEqual(float(recall["recall"]), 0.5)
        self.assertAlmostEqual(float(enrichment["enrichment_factor"]), 2.5)
        self.assertAlmostEqual(ndcg(relevance, scores), 1.0)
        self.assertAlmostEqual(float(metrics["ordinal_ndcg_at_100"]), 1.0)
        self.assertGreater(float(metrics["relevance_spearman"]), 0.9)

    def test_ties_and_constant_spearman_are_deterministic(self) -> None:
        self.assertEqual(spearman_correlation([1, 1, 1], [3, 2, 1]), 0.0)
        self.assertAlmostEqual(spearman_correlation([0, 1, 2], [2, 1, 0]), -1.0)
        first = ndcg([4, 0, 3, 0], [1, 1, 1, 1])
        second = ndcg([4, 0, 3, 0], [1, 1, 1, 1])
        self.assertEqual(first, second)

    def test_geometry_metrics_are_per_field_and_macro(self) -> None:
        result = geometry_metrics(
            {"a": [0, 1, 2], "b": [10, 20, 30]},
            {"a": [0, 1, 3], "b": [30, 20, 10]},
        )
        self.assertAlmostEqual(result["per_field"]["a"]["mae"], 1 / 3)
        self.assertAlmostEqual(result["per_field"]["a"]["spearman"], 1.0)
        self.assertAlmostEqual(result["per_field"]["b"]["spearman"], -1.0)
        self.assertEqual(result["field_count"], 2)

    def test_parent_cluster_inference_is_paired_and_reproducible(self) -> None:
        relevance: list[int] = []
        candidate: list[float] = []
        baseline: list[float] = []
        clusters: list[str] = []
        for cluster in range(10):
            relevance.extend([4, 0])
            candidate.extend([2.0, 0.0])
            baseline.extend([0.0, 2.0])
            clusters.extend([f"p{cluster}", f"p{cluster}"])
        first = paired_parent_cluster_bootstrap(
            relevance, candidate, baseline, clusters, replicates=200, seed=7
        )
        second = paired_parent_cluster_bootstrap(
            relevance, candidate, baseline, clusters, replicates=200, seed=7
        )
        permutation = paired_parent_cluster_permutation(
            relevance, candidate, baseline, clusters, replicates=1023, seed=11
        )
        self.assertEqual(first, second)
        self.assertGreater(first["ci95_lower"], 0.0)
        self.assertLess(permutation["two_sided_p_value"], 0.05)
        self.assertEqual(permutation["cluster_count"], 10)

    def test_invalid_inputs_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            ordinal_ranking_metrics([1, 2], [1, np.nan])
        with self.assertRaises(ValueError):
            geometry_metrics({"a": [1]}, {"b": [1]})
        with self.assertRaises(ValueError):
            paired_parent_cluster_bootstrap([1], [1], [0], [""], replicates=1)


if __name__ == "__main__":
    unittest.main()
