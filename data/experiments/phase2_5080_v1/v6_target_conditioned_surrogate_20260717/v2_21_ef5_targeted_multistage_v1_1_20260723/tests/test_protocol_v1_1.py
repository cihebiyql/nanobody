#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("protocol_v1_1", ROOT / "src" / "protocol_v1_1.py")
assert SPEC and SPEC.loader
protocol = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = protocol
try:
    SPEC.loader.exec_module(protocol)
except BaseException:
    sys.modules.pop(SPEC.name, None)
    raise


def terminal_fixture(**updates):
    row = {
        "scientific_status": "FAIL",
        "technical_closure": "PASS",
        "all_fold_selected_at_grid_max": False,
        "max_achieved_shared_gradient_ratio": 0.02,
        "contact_evaluator_available": True,
        "contact_vs_position_macro_auprc_ci_lower": 0.01,
        "target_permutation_relative_contact_drop": 0.15,
        "shuffle_relative_contact_drop": 0.15,
        "c1_vs_c0_hits_gain": 0,
        "c1_vs_c0_incremental_gate_pass": False,
        "fold_stability_pass": True,
        "source_reliability_stability_pass": True,
        "minimum_source_stratum_delta_ef5": 0.0,
        "maximum_source_stratum_delta_ef5": 0.1,
        "rdual_spearman_delta": 0.0,
        "rdual_relative_mae_improvement": 0.0,
    }
    row.update(updates)
    return row


class MetricTests(unittest.TestCase):
    def test_exact_metric_uses_985_493_and_sha_ties(self):
        sha = [f"{i:064x}" for i in range(protocol.ROWS)]
        truth = [float(i) for i in range(protocol.ROWS)]
        scores = truth[:]
        result = protocol.exact_ef5(truth, scores, sha)
        self.assertEqual(result["hits"], protocol.BUDGET)
        self.assertEqual(result["selected"], 493)
        self.assertEqual(result["positives"], 985)
        tied = protocol.ranked_indices([1.0, 1.0], ["b" * 64, "a" * 64])
        self.assertEqual(tied, [1, 0])

    def test_metric_rejects_non_exact_row_count(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.exact_ef5([1.0], [1.0], ["a"])

    def test_metric_rejects_invalid_sha_and_non_finite_values(self):
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_sequence_sha256"):
            protocol.ranked_indices([1.0], ["not-a-sha"])
        with self.assertRaisesRegex(protocol.ProtocolError, "non_finite:score"):
            protocol.ranked_indices([float("nan")], ["0" * 64])

    def test_fit_cdf_never_self_ranks_queries(self):
        self.assertEqual(protocol.fit_cdf([0.0, 1.0], [0.5, 2.0]), [0.5, 1.0])

    def test_union_has_exact_model_set_and_top5(self):
        sha = [f"{i:064x}" for i in range(100)]
        scores = {
            "L1": list(range(100)),
            "B": list(reversed(range(100))),
            "M2": [float(i % 17) for i in range(100)],
            "C2": [float(i % 13) for i in range(100)],
        }
        pool = protocol.union_pool(scores, sha)
        self.assertGreaterEqual(len(pool), 5)
        self.assertLessEqual(len(pool), 20)
        with self.assertRaises(protocol.ProtocolError):
            protocol.union_pool({"B": scores["B"], "L1": scores["L1"], "M2": scores["M2"], "C2": scores["C2"]}, sha)
        with self.assertRaisesRegex(protocol.ProtocolError, "union_requires_frozen_top5_fraction"):
            protocol.union_pool(scores, sha, per_model_fraction=0.0500000001)


class DispatcherTests(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        result = protocol.dispatch_terminal({"scientific_status": "FAIL"})
        self.assertTrue(result.startswith("STOP_MISSING_TERMINAL_EVIDENCE:"))

    def test_technical_failure_stops(self):
        self.assertEqual(
            protocol.dispatch_terminal(terminal_fixture(technical_closure="FAIL")),
            "STOP_INVALID_V220_TECHNICAL_CLOSURE",
        )

    def test_scientific_pass_selects_pass_branch(self):
        self.assertEqual(
            protocol.dispatch_terminal(terminal_fixture(scientific_status="PASS")),
            "PASS_BRANCH_P1_CONTACT_CAUSAL",
        )

    def test_f1_first_match(self):
        row = terminal_fixture(
            all_fold_selected_at_grid_max=True,
            max_achieved_shared_gradient_ratio=0.004,
            contact_vs_position_macro_auprc_ci_lower=-1.0,
        )
        self.assertEqual(protocol.dispatch_terminal(row), "F1_UNDERPOWERED_CONTACT_LOSS")

    def test_f2_requires_causal_contact_and_failed_scalar_gate(self):
        self.assertEqual(
            protocol.dispatch_terminal(terminal_fixture()),
            "F2_CONTACT_LEARNABLE_SCALAR_PATH_INEFFECTIVE",
        )

    def test_f3_target_blind(self):
        row = terminal_fixture(target_permutation_relative_contact_drop=0.05)
        self.assertEqual(protocol.dispatch_terminal(row), "F3_CONTACT_NOT_LEARNABLE_OR_TARGET_BLIND")

    def test_missing_contact_evaluator_does_not_fall_through(self):
        row = terminal_fixture(contact_evaluator_available=False)
        self.assertEqual(protocol.dispatch_terminal(row), "STOP_MISSING_CONTACT_EVALUATOR_EVIDENCE")

    def test_malformed_boolean_cannot_route_to_a_favorable_branch(self):
        row = terminal_fixture(all_fold_selected_at_grid_max="yes")
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_boolean"):
            protocol.dispatch_terminal(row)

    def test_fractional_hits_gain_is_rejected_not_truncated(self):
        row = terminal_fixture(c1_vs_c0_hits_gain=3.7)
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_integer"):
            protocol.dispatch_terminal(row)

    def test_scientific_pass_still_validates_required_evidence(self):
        row = terminal_fixture(scientific_status="PASS", max_achieved_shared_gradient_ratio=float("nan"))
        with self.assertRaisesRegex(
            protocol.ProtocolError,
            "non_finite:max_achieved_shared_gradient_ratio",
        ):
            protocol.dispatch_terminal(row)

    def test_f4_instability(self):
        row = terminal_fixture(
            c1_vs_c0_incremental_gate_pass=True,
            c1_vs_c0_hits_gain=3,
            fold_stability_pass=False,
        )
        self.assertEqual(protocol.dispatch_terminal(row), "F4_FOLD_SOURCE_RELIABILITY_INSTABILITY")

    def test_f5_scalar_only_gain(self):
        row = terminal_fixture(
            rdual_spearman_delta=0.02,
        )
        self.assertEqual(protocol.dispatch_terminal(row), "F5_SCALAR_IMPROVES_TOP5_DOES_NOT")


class DagAndReliabilityTests(unittest.TestCase):
    def test_p1_fail_goes_to_base_only_p3(self):
        evidence = protocol.StageEvidence(False, False, False, [])
        self.assertEqual(protocol.next_stage("P1_CONTACT_CAUSAL", evidence), "P3_BASE_ONLY")

    def test_stage_evidence_rejects_non_boolean_flags(self):
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_boolean"):
            protocol.StageEvidence("false", False, False, [])

    def test_p4_requires_all_five_fit_only_oracles(self):
        evidence = protocol.StageEvidence(True, True, True, [5.6] * 5)
        self.assertEqual(protocol.next_stage("P3_WITH_MULTISEED", evidence), "P4_LAMBDARANK")
        evidence = protocol.StageEvidence(True, True, True, [5.6] * 4 + [5.49])
        self.assertEqual(
            protocol.next_stage("P3_WITH_MULTISEED", evidence),
            "STOP_INSUFFICIENT_FIT_ONLY_UNION_SIGNAL",
        )

    def test_reliability_is_loss_weight_and_parent_normalized(self):
        weights = protocol.reliability_weights([0.0, 1.0, 2.0, 3.0], ["a", "a", "b", "b"])
        self.assertAlmostEqual(sum(weights[:2]) / 2.0, 1.0)
        self.assertAlmostEqual(sum(weights[2:]) / 2.0, 1.0)
        # The frozen median is the conventional even-sample median, 1.5,
        # rather than silently choosing the lower middle value, 1.0.
        self.assertAlmostEqual(weights[0], 8.0 / 7.0, places=5)

    def test_reliability_rejects_invalid_parent_and_boolean_variance(self):
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_parent_id"):
            protocol.reliability_weights([1.0], [""])
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_number:sigma2"):
            protocol.reliability_weights([True], ["a"])

    def test_forbidden_features_rejected(self):
        protocol.validate_feature_names(["L1_Rdual", "model_disagreement"])
        with self.assertRaises(protocol.ProtocolError):
            protocol.validate_feature_names(["L1_Rdual", "parent_id"])

    def test_feature_validation_is_allowlist_based_and_nonempty(self):
        for name in (
            "parent_framework_cluster",
            "sequence_sha256",
            "teacher_reliability",
            "contact_availability",
            "R_dual_min",
            "arbitrary_new_feature",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(protocol.ProtocolError, "forbidden_or_unknown_features"):
                    protocol.validate_feature_names(["L1_Rdual", name])
        with self.assertRaisesRegex(protocol.ProtocolError, "empty_feature_set"):
            protocol.validate_feature_names([])


class NestedSplitFirewallTests(unittest.TestCase):
    def setUp(self):
        self.parents = ["A", "A", "B", "B", "C", "C", "D", "D", "E", "E", "F", "F"]
        self.outer_fit = list(range(8))
        self.outer_test = list(range(8, 12))
        self.inner = []
        for validation_parent in ("A", "B", "C", "D"):
            validation = [
                index
                for index in self.outer_fit
                if self.parents[index] == validation_parent
            ]
            fit = [index for index in self.outer_fit if index not in validation]
            self.inner.append((fit, validation))

    def test_whole_parent_outer_and_inner_partitions_close(self):
        protocol.validate_whole_parent_nested_split(
            self.parents, self.outer_fit, self.outer_test, self.inner
        )

    def test_outer_parent_leakage_fails_closed(self):
        parents = self.parents[:]
        parents[8] = "A"
        with self.assertRaisesRegex(protocol.ProtocolError, "outer_parent_leakage"):
            protocol.validate_whole_parent_nested_split(
                parents, self.outer_fit, self.outer_test, self.inner
            )

    def test_inner_parent_leakage_fails_closed(self):
        inner = self.inner[:]
        inner[0] = (list(range(1, 8)), [0])
        with self.assertRaisesRegex(protocol.ProtocolError, "inner_parent_leakage"):
            protocol.validate_whole_parent_nested_split(
                self.parents, self.outer_fit, self.outer_test, inner
            )

    def test_inner_validation_must_cover_each_parent_once(self):
        inner = self.inner[:]
        inner[3] = self.inner[0]
        with self.assertRaisesRegex(
            protocol.ProtocolError, "inner_validation_(rows|parents)_not_exactly_once"
        ):
            protocol.validate_whole_parent_nested_split(
                self.parents, self.outer_fit, self.outer_test, inner
            )


class FitOnlyLabelFirewallTests(unittest.TestCase):
    def setUp(self):
        self.fit = list(range(10))
        self.test = [10, 11]
        self.truth = {index: float(index) for index in self.fit}
        self.sha = {index: f"{index:064x}" for index in self.fit}

    def test_fit_only_top10_threshold_uses_exact_fit_rows(self):
        threshold = protocol.fit_only_top10_threshold(
            self.truth, self.sha, self.fit, self.test
        )
        self.assertEqual(threshold.fit_rows, 10)
        self.assertEqual(threshold.positive_count, 1)
        self.assertEqual(threshold.positive_indices, (9,))
        self.assertEqual(threshold.cutoff, 9.0)

    def test_outer_test_label_access_is_rejected(self):
        contaminated_truth = dict(self.truth)
        contaminated_truth[10] = 100.0
        contaminated_sha = dict(self.sha)
        contaminated_sha[10] = f"{10:064x}"
        with self.assertRaisesRegex(
            protocol.ProtocolError, "fit_only_label_firewall_violation"
        ):
            protocol.fit_only_top10_threshold(
                contaminated_truth,
                contaminated_sha,
                self.fit,
                self.test,
            )

    def test_fit_only_union_oracle_is_exact_and_rejects_test_rows(self):
        result = protocol.fit_only_union_oracle_ef5(
            self.truth,
            self.sha,
            self.fit,
            self.test,
            [9, 8, 7],
        )
        self.assertEqual(result["budget"], 1)
        self.assertEqual(result["oracle_hits"], 1)
        self.assertEqual(result["oracle_ef5"], 10.0)
        with self.assertRaisesRegex(
            protocol.ProtocolError, "outer_test_or_unknown_row_in_fit_union"
        ):
            protocol.fit_only_union_oracle_ef5(
                self.truth,
                self.sha,
                self.fit,
                self.test,
                [9, 10],
            )

    def test_threshold_and_oracle_fractions_are_frozen(self):
        with self.assertRaisesRegex(protocol.ProtocolError, "requires_frozen_top10_fraction"):
            protocol.fit_only_top10_threshold(
                self.truth, self.sha, self.fit, self.test, positive_fraction=0.100001
            )
        with self.assertRaisesRegex(protocol.ProtocolError, "requires_frozen_top5_budget"):
            protocol.fit_only_union_oracle_ef5(
                self.truth,
                self.sha,
                self.fit,
                self.test,
                [9, 8, 7],
                budget_fraction=0.050001,
            )


class ParentPoolAndAblationTests(unittest.TestCase):
    def test_parent_cap_and_zero_positive_fallback(self):
        scores = [0.9, 0.8, 0.7, 0.6, 0.1, 0.4, 0.3, 0.2]
        sha = [f"{index:064x}" for index in range(8)]
        parents = ["A"] * 4 + ["B"] * 4
        positives = [True, True, False, False] + [False] * 4
        selected = protocol.parent_capped_rank_pool(
            scores,
            sha,
            parents,
            positives,
            per_parent_cap=3,
            zero_positive_sentinels=2,
        )
        self.assertEqual(selected[:3], [0, 1, 2])
        self.assertEqual(selected[3:], [5, 6])
        self.assertEqual(sum(parents[index] == "A" for index in selected), 3)
        self.assertEqual(sum(parents[index] == "B" for index in selected), 2)

    def test_parent_pool_rejects_non_boolean_relevance(self):
        with self.assertRaisesRegex(protocol.ProtocolError, "invalid_boolean:positive_flag"):
            protocol.parent_capped_rank_pool(
                [1.0],
                ["0" * 64],
                ["A"],
                [1],
                per_parent_cap=1,
                zero_positive_sentinels=1,
            )

    def test_contact_shuffle_preserves_vhh_target_margins_and_density(self):
        matrix = (
            (1, 0, 1, 0),
            (0, 1, 0, 1),
            (1, 0, 0, 1),
        )
        shuffled = protocol.degree_preserving_contact_shuffle(
            matrix, seed=20260723, swaps=3
        )
        repeated = protocol.degree_preserving_contact_shuffle(
            matrix, seed=20260723, swaps=3
        )
        self.assertEqual(shuffled, repeated)
        self.assertNotEqual(shuffled, matrix)
        self.assertEqual([sum(row) for row in shuffled], [sum(row) for row in matrix])
        self.assertEqual(
            [sum(row[column] for row in shuffled) for column in range(4)],
            [sum(row[column] for row in matrix) for column in range(4)],
        )
        self.assertEqual(sum(map(sum, shuffled)), sum(map(sum, matrix)))

    def test_contact_shuffle_rejects_nonshuffleable_or_nonbinary_matrix(self):
        with self.assertRaisesRegex(protocol.ProtocolError, "contact_shuffle_not_possible"):
            protocol.degree_preserving_contact_shuffle(
                ((1, 1), (0, 0)), seed=1, swaps=1
            )
        with self.assertRaisesRegex(
            protocol.ProtocolError, "contact_matrix_requires_binary_integers"
        ):
            protocol.degree_preserving_contact_shuffle(
                ((1, 2), (0, 0)), seed=1, swaps=1
            )

    def test_target_permutation_and_conformer_swap_are_closed(self):
        target = {"R1": "feature-1", "R2": "feature-2", "R3": "feature-3"}
        permuted = protocol.apply_target_residue_permutation(
            target, {"R1": "R2", "R2": "R3", "R3": "R1"}
        )
        self.assertEqual(set(permuted), set(target))
        self.assertCountEqual(permuted.values(), target.values())
        self.assertEqual(permuted["R1"], "feature-2")
        payloads = {"8X6B": {"graph": 8}, "9E6Y": {"graph": 9}}
        swapped = protocol.swap_dual_conformer_payloads(payloads)
        self.assertIs(swapped["8X6B"], payloads["9E6Y"])
        self.assertIs(swapped["9E6Y"], payloads["8X6B"])

    def test_target_and_conformer_mapping_must_be_exact_bijections(self):
        with self.assertRaisesRegex(
            protocol.ProtocolError, "target_permutation_not_closed_bijection"
        ):
            protocol.apply_target_residue_permutation(
                {"R1": 1, "R2": 2}, {"R1": "R2", "R2": "R2"}
            )
        with self.assertRaisesRegex(
            protocol.ProtocolError, "dual_conformer_mapping_not_closed"
        ):
            protocol.swap_dual_conformer_payloads({"8X6B": 8})


class ProspectiveFirewallTests(unittest.TestCase):
    def test_nonprospective_training_path_and_allowed_features_pass(self):
        protocol.validate_training_input_firewall(
            ["experiments/phase2_5080_v1/prepared/train9849_teacher.tsv"],
            ["L1_Rdual", "predicted_hotspot_mass"],
        )

    def test_prospective_open_or_sealed_paths_fail_before_access(self):
        for path in (
            "/data1/qlyu/projects/V4-F/prospective/test32.tsv",
            "prepared/open_development/candidates.tsv",
            "prepared/sealed_holdout.tsv",
            "prepared/top7500/predictions.tsv",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    protocol.ProtocolError,
                    "prospective_or_open_development_path_forbidden",
                ):
                    protocol.validate_nonprospective_paths([path])

    def test_prospective_or_teacher_features_are_not_allowlisted(self):
        for name in ("prospective_rank", "sealed_label", "R_dual_min"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    protocol.ProtocolError, "forbidden_or_unknown_features"
                ):
                    protocol.validate_training_input_firewall(
                        ["prepared/train9849_teacher.tsv"], ["L1_Rdual", name]
                    )


if __name__ == "__main__":
    unittest.main()
