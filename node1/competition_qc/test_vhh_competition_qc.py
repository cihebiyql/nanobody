#!/usr/bin/env python3
"""Regression tests for the competition QC core."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

import vhh_competition_qc as qc


class CompetitionQCRegressionTests(unittest.TestCase):
    def test_missing_binding_and_blocking_evidence_are_not_neutral_scores(self) -> None:
        self.assertIsNone(qc.score_binding({}))
        self.assertIsNone(qc.score_blocking({}))

    def test_binding_score_is_independent_from_blocker_class(self) -> None:
        self.assertIsNone(qc.score_binding({"blocker_class": "CONSENSUS_BLOCKER_LIKE_A"}))
        self.assertEqual(qc.score_binding({"binding_prior_consensus": "0.82"}), 82.0)

    def test_expression_and_purity_are_separate_proxies(self) -> None:
        row = {
            "pI": "7.2",
            "charge_pH7_4": "1.0",
            "instability_index": "28",
            "abnativ_vhh_score": "0.85",
            "gravy": "0.35",
            "hydrophobic_5_count": "1",
            "cys_count": "2",
            "polyreactivity_proxy": "high",
        }
        expression = qc.score_expression(row)
        purity = qc.score_purity(row)
        self.assertGreater(expression, purity)
        self.assertLess(purity, 50.0)

    def test_dual_reference_multiseed_jobs_form_strict_consensus(self) -> None:
        rows = []
        for conformation in ("8x6b", "9e6y"):
            for seed in ("42", "3047"):
                rows.append(
                    {
                        "entity_id": "candidate_a",
                        "state": "SUCCESS",
                        "conformation": conformation,
                        "seed": seed,
                        "representative_pair_label": "STRICT_A",
                        "model_pair_consensus_fraction": "0.75",
                        "model_native_cross_support_agreement_fraction": "1.0",
                        "model_strict_a_fraction": "0.75",
                        "native_hotspot_overlap": "16",
                        "cross_hotspot_overlap": "15",
                        "native_total_occlusion": "620",
                        "cross_total_occlusion": "580",
                        "native_cdr3_occlusion": "140",
                        "cross_cdr3_occlusion": "120",
                        "native_cdr3_fraction": "0.22",
                        "cross_cdr3_fraction": "0.19",
                    }
                )
        summary = qc.aggregate_docking_rows(rows)["candidate_a"]
        self.assertEqual(summary["blocker_class"], "CONSENSUS_BLOCKER_LIKE_A")
        self.assertEqual(summary["successful_docking_job_count"], "4")
        self.assertEqual(summary["dual_conformation_coverage"], "1.000000")
        self.assertEqual(summary["strict_a_job_fraction"], "1.000000")
        self.assertGreater(qc.score_blocking(summary), 80.0)
        self.assertGreater(qc.score_pose_robustness(summary), 80.0)

    def test_partial_raw_docking_cannot_inherit_high_confidence_class(self) -> None:
        rows = [
            {
                "entity_id": "candidate_partial",
                "state": "SUCCESS",
                "conformation": "8x6b",
                "seed": "42",
                "blocker_class": "CONSENSUS_BLOCKER_LIKE_A",
                "representative_pair_label": "STRICT_A",
                "native_hotspot_overlap": "16",
                "cross_hotspot_overlap": "15",
                "native_total_occlusion": "620",
                "cross_total_occlusion": "580",
                "native_cdr3_occlusion": "140",
                "cross_cdr3_occlusion": "120",
                "native_cdr3_fraction": "0.22",
                "cross_cdr3_fraction": "0.19",
            }
        ]
        summary = qc.aggregate_docking_rows(rows)["candidate_partial"]
        self.assertEqual(summary["blocker_class"], "EVIDENCE_INFERENCE_ONLY_E")
        self.assertEqual(summary["docking_evidence_status"], "PARTIAL_DOCKING_EVIDENCE")

    def test_duplicate_conformation_seed_rows_fail_closed(self) -> None:
        rows = []
        for conformation in ("8x6b", "9e6y"):
            for seed in ("42", "3047"):
                row = {
                    "entity_id": "candidate_duplicate",
                    "state": "SUCCESS",
                    "conformation": conformation,
                    "seed": seed,
                    "representative_pair_label": "STRICT_A",
                }
                rows.extend([row, dict(row)] if conformation == "8x6b" and seed == "42" else [row])
        summary = qc.aggregate_docking_rows(rows)["candidate_duplicate"]
        self.assertEqual(summary["duplicate_conformation_seed_jobs"], "1")
        self.assertNotEqual(summary["blocker_class"], "CONSENSUS_BLOCKER_LIKE_A")
        self.assertEqual(summary["docking_evidence_status"], "PARTIAL_DOCKING_EVIDENCE")

    def test_zero_production_score_does_not_fall_back_to_sequence_priority(self) -> None:
        status, score = qc.production_rank_score(
            binding_score=60.0,
            blocking_score=0.0,
            pose_robustness_score=0.0,
            developability_score=0.0,
            expression_score=0.0,
            purity_score=0.0,
            structure_score=0.0,
            docking_consensus_complete=True,
        )
        self.assertEqual(status, "PRODUCTION_RANK_READY")
        self.assertEqual(score, 6.0)

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
