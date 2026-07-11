#!/usr/bin/env python3
"""Regression tests for the competition QC core."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

import vhh_competition_qc as qc


class CompetitionQCRegressionTests(unittest.TestCase):
    def test_parse_fasta_normalizes_and_deduplicates_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "input.fasta"
            fasta.write_text(
                ">same id one\nacde*\n>same id two\nACDF\n",
                encoding="utf-8",
            )
            records = qc.parse_fasta(fasta)
        self.assertEqual([record.name for record in records], ["same", "same_2"])
        self.assertEqual([record.sequence for record in records], ["ACDE", "ACDF"])

    def test_default_competition_policy_keeps_existing_hard_fail_behavior(self) -> None:
        hard_fail, recommendation, reasons = qc.classify_candidate(
            candidate={
                "L1_numbering_integrity": "PASS",
                "imgt_ok": "True",
                "L2_vhh_features": "FAIL",
                "single_domain_suitability": "poor",
                "invalid_aa_count": "0",
                "cys_count": "2",
                "hydrophobic_5_count": "1",
                "L4_structure_stability": "NOT_RUN",
                "L3_developability": "WARN",
            },
            official={"has_failure": False},
            novelty={"pass_similarity_filter": "PASS", "novelty_margin_flag": "SAFE"},
            developability_score=80,
            expression_score=80,
            structure_score=60,
        )
        self.assertTrue(hard_fail)
        self.assertEqual(recommendation, "REJECT_HARD_GATE")
        self.assertIn("not_vhh_like", reasons)
        self.assertIn("hydrophobic_run", reasons)

    def test_select_portfolio_enforces_cluster_limit(self) -> None:
        args = argparse.Namespace(top_n=3, reserve_n=2, cluster_limit=1)
        rows = [
            {"candidate_id": "a", "hard_fail": "False", "intra_team_cluster_id": "C1"},
            {"candidate_id": "b", "hard_fail": "False", "intra_team_cluster_id": "C1"},
            {"candidate_id": "c", "hard_fail": "False", "intra_team_cluster_id": "C2"},
        ]
        selected, reserve = qc.select_portfolio(args, rows)
        self.assertEqual([row["candidate_id"] for row in selected], ["a", "c"])
        self.assertEqual([row["candidate_id"] for row in reserve], ["b"])

    def test_blocker_calibrated_policy_preserves_vhh_like_and_hydrophobic_warnings(self) -> None:
        hard_fail, recommendation, reasons = qc.classify_candidate(
            candidate={
                "L1_numbering_integrity": "PASS",
                "imgt_ok": "True",
                "L2_vhh_features": "FAIL",
                "single_domain_suitability": "poor",
                "invalid_aa_count": "0",
                "cys_count": "2",
                "hydrophobic_5_count": "1",
                "L4_structure_stability": "NOT_RUN",
                "L3_developability": "WARN",
            },
            official={"has_failure": False},
            novelty={"pass_similarity_filter": "PASS", "novelty_margin_flag": "SAFE"},
            developability_score=80,
            expression_score=80,
            structure_score=60,
            gate_policy="blocker_calibrated",
        )
        self.assertFalse(hard_fail)
        self.assertEqual(recommendation, "REVIEW_DEVELOPABILITY")
        self.assertIn("not_vhh_like", reasons)
        self.assertIn("hydrophobic_run", reasons)

    def test_large_scale_fast_shorthand_is_conservative_and_deferred(self) -> None:
        args = qc.parse_args(
            [
                "input.fasta",
                "-o",
                "out",
                "--large-scale-fast",
            ]
        )
        self.assertTrue(args.skip_abnativ)
        self.assertTrue(args.skip_sapiens)
        self.assertTrue(args.skip_tnp)
        self.assertTrue(args.skip_team_diversity)
        self.assertTrue(args.defer_official_validator)
        self.assertFalse(args.novelty_only_official_pass)
        self.assertEqual(args.gate_policy, "blocker_calibrated")

    def test_lcs_upper_bound_pruning_keeps_exact_best(self) -> None:
        calls: list[tuple[str, str]] = []

        def identity(a: str, b: str) -> float:
            calls.append((a, b))
            return sum(x == y for x, y in zip(a, b)) / max(len(a), len(b))

        best, name, refset, stats = qc.best_identity_against_references(
            "AAAAAA",
            [
                ("unrelated", "test", "CCCCCC"),
                ("near", "test", "AAAACC"),
                ("exact", "test", "AAAAAA"),
            ],
            identity,
        )
        self.assertEqual(best, 1.0)
        self.assertEqual(name, "exact")
        self.assertEqual(refset, "test")
        self.assertEqual(stats["identity_requests"], 1)
        self.assertEqual(stats["upper_bound_pruned"], 2)
        self.assertEqual(len(calls), 1)

    def test_deferred_diversity_does_not_trigger_cluster_limit(self) -> None:
        candidates = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        rows, cluster_map, cluster_sizes = qc.make_independent_team_diversity(candidates)
        self.assertEqual(len(set(cluster_map.values())), 3)
        self.assertTrue(all(size == 1 for size in cluster_sizes.values()))
        self.assertTrue(all(row["diversity_status"] == "DEFERRED_TO_SHORTLIST" for row in rows))


if __name__ == "__main__":
    unittest.main()
