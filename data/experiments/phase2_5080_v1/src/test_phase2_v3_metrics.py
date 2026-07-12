#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2_v3_metrics import (  # noqa: E402
    average_precision,
    binary_ranking_metrics,
    formal_gate_decision,
    macro_target_average_precision,
    paired_bootstrap_ap_delta,
    paired_permutation_ap_test,
    roc_auc,
)


class Phase2V3MetricTests(unittest.TestCase):
    def test_perfect_and_tied_metrics(self) -> None:
        labels = [1, 0, 1, 0]
        self.assertEqual(average_precision(labels, [4, 1, 3, 0]), 1.0)
        self.assertEqual(roc_auc(labels, [4, 1, 3, 0]), 1.0)
        self.assertEqual(average_precision(labels, [0, 0, 0, 0]), 0.5)
        self.assertEqual(roc_auc(labels, [0, 0, 0, 0]), 0.5)

    def test_macro_target_average_precision(self) -> None:
        value, groups = macro_target_average_precision(
            [1, 0, 1, 0], [1.0, 0.0, 0.0, 1.0], ["a", "a", "b", "b"]
        )
        self.assertEqual(groups["a"], 1.0)
        self.assertEqual(groups["b"], 0.5)
        self.assertEqual(value, 0.75)

    def test_paired_statistics_are_deterministic(self) -> None:
        labels = [1, 0] * 50
        model = [1.0 if label else 0.0 for label in labels]
        baseline = [0.5] * len(labels)
        first = paired_bootstrap_ap_delta(labels, model, baseline, 100, 7)
        second = paired_bootstrap_ap_delta(labels, model, baseline, 100, 7)
        self.assertEqual(first, second)
        permutation = paired_permutation_ap_test(labels, model, baseline, 100, 7)
        self.assertGreater(first["ci95_lower"], 0.0)
        self.assertLess(permutation["two_sided_p_value"], 0.05)

    def test_gate_enforces_every_preregistered_condition(self) -> None:
        passed = formal_gate_decision(
            [0.1, 0.2, 0.3],
            {"observed_delta": 0.2, "ci95_lower": 0.01},
            {"two_sided_p_value": 0.01},
            False,
            False,
        )
        self.assertEqual(passed["status"], "PASS_IMPROVED_PRIOR")
        failed = formal_gate_decision(
            [0.1, -0.01, 0.3],
            {"observed_delta": 0.2, "ci95_lower": -0.01},
            {"two_sided_p_value": 0.2},
            False,
            False,
        )
        self.assertEqual(failed["status"], "FAIL_FALLBACK_TO_BASELINE")

    def test_binary_metrics_report_prevalence(self) -> None:
        metrics = binary_ranking_metrics([1, 0, 0, 0], [0.9, 0.3, 0.2, 0.1])
        self.assertEqual(metrics["prevalence"], 0.25)
        self.assertEqual(metrics["average_precision"], 1.0)


if __name__ == "__main__":
    unittest.main()
