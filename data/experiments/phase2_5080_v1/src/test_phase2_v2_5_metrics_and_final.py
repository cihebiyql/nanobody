#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2_v2_5_metrics import (  # noqa: E402
    bootstrap_metric_ci,
    compute_group_ranking_metrics,
    exact_random_expectations,
    macro_summary,
    permutation_test_group_labels,
)
from validate_phase2_v2_5_final import build_audit, file_sha256, parse_args  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class Phase2V25MetricTests(unittest.TestCase):
    def test_group_macro_pairwise_excludes_ambiguous_ties_and_computes_secondaries(self) -> None:
        frame = pd.DataFrame([
            {"group_id": "g1", "sample_id": "a", "label_value": 3.0, "label_direction": "higher_is_better", "score": 0.8, "ambiguous_tie": False},
            {"group_id": "g1", "sample_id": "b", "label_value": 2.0, "label_direction": "higher_is_better", "score": 0.6, "ambiguous_tie": False},
            {"group_id": "g1", "sample_id": "c", "label_value": 1.0, "label_direction": "higher_is_better", "score": 0.1, "ambiguous_tie": False},
            {"group_id": "g1", "sample_id": "tie", "label_value": 3.0, "label_direction": "higher_is_better", "score": 0.0, "ambiguous_tie": True},
            {"group_id": "g2", "sample_id": "d", "label_value": 10.0, "label_direction": "lower_is_better", "score": 0.1, "ambiguous_tie": False},
            {"group_id": "g2", "sample_id": "e", "label_value": 1.0, "label_direction": "lower_is_better", "score": 0.9, "ambiguous_tie": False},
        ])
        group_metrics = compute_group_ranking_metrics(frame)
        summary = macro_summary(group_metrics)
        self.assertEqual(int(group_metrics.loc[group_metrics.group_id == "g1", "comparable_pair_count"].iloc[0]), 3)
        self.assertAlmostEqual(summary["macro_group_pairwise_preference_accuracy"], 1.0)
        self.assertAlmostEqual(summary["hit_at_1"], 1.0)
        self.assertGreater(summary["macro_group_ndcg_all"], 0.99)

    def test_exact_random_expectations_are_closed_form_for_unique_best(self) -> None:
        randoms = exact_random_expectations([3.0, 2.0, 1.0])
        self.assertAlmostEqual(randoms["pairwise_preference_accuracy"], 0.5)
        self.assertAlmostEqual(randoms["hit_at_1"], 1.0 / 3.0)
        self.assertAlmostEqual(randoms["mrr"], (1.0 + 0.5 + 1.0 / 3.0) / 3.0)
        self.assertTrue(0.0 < randoms["ndcg_all"] < 1.0)

    def test_bootstrap_and_permutation_are_group_level_and_reproducible(self) -> None:
        values = pd.DataFrame([
            {"group_id": "g1", "metric": 1.0, "assay": "a"},
            {"group_id": "g2", "metric": 0.5, "assay": "a"},
            {"group_id": "g3", "metric": 0.0, "assay": "b"},
        ])
        ci_a = bootstrap_metric_ci(values, "metric", strata_cols=["assay"], n=100, seed=7)
        ci_b = bootstrap_metric_ci(values, "metric", strata_cols=["assay"], n=100, seed=7)
        self.assertEqual(ci_a, ci_b)
        self.assertAlmostEqual(ci_a["point"], 0.5)
        frame = pd.DataFrame([
            {"group_id": "g1", "label_value": 3.0, "score": 0.9},
            {"group_id": "g1", "label_value": 1.0, "score": 0.1},
            {"group_id": "g2", "label_value": 2.0, "score": 0.8},
            {"group_id": "g2", "label_value": 0.0, "score": 0.0},
        ])
        def stat(df: pd.DataFrame) -> float:
            return float(macro_summary(compute_group_ranking_metrics(df, group_col="group_id"))["macro_group_pairwise_preference_accuracy"])
        result = permutation_test_group_labels(frame, stat, n=50, seed=11)
        self.assertAlmostEqual(result["observed"], 1.0)
        self.assertTrue(0.0 <= result["p_two_sided"] <= 1.0)


class Phase2V25FinalAuditTests(unittest.TestCase):
    registry_fields = [
        "sample_id", "vhh_sequence", "sequence_sha256", "target_id", "target_sequence_sha256", "target_construct",
        "label_axis", "evidence_level", "ground_truth_kind", "label_value", "label_unit", "label_direction",
        "assay_type", "assay_batch", "replicate_count", "source_id", "source_path_or_locator",
        "allowed_use", "forbidden_use", "family_id", "leakage_group_id", "split_group_id", "sealed_status",
        "dataset_version", "mutation", "reference_sample_id", "pose_id", "pose_qc_status", "ordinary_bce_eligible",
        "missing_reason",
    ]

    def make_args(self, root: Path):
        exp = root / "experiments/phase2_5080_v1"
        return parse_args([
            "--exp-dir", str(exp),
            "--no-write",
        ])

    def registry_row(self, sample_id: str, evidence_level: str, kind: str, allowed_use: str, forbidden_use: str = "", **extra: object) -> dict[str, object]:
        row = {
            "sample_id": sample_id,
            "vhh_sequence": "AAAA",
            "sequence_sha256": f"sha-{sample_id}",
            "target_id": "PVRIG",
            "target_sequence_sha256": "target-sha",
            "target_construct": "PVRIG_ECD",
            "label_axis": "binding",
            "evidence_level": evidence_level,
            "ground_truth_kind": kind,
            "label_value": 1.0 if evidence_level in {"E4", "E5", "E6"} else "",
            "label_unit": "nM" if evidence_level in {"E4", "E5", "E6"} else "",
            "label_direction": "lower_is_better" if evidence_level in {"E4", "E5", "E6"} else "",
            "assay_type": "SPR" if evidence_level in {"E4", "E5", "E6"} else "",
            "assay_batch": "batch1" if evidence_level in {"E4", "E5", "E6"} else "",
            "replicate_count": 2 if evidence_level in {"E4", "E5", "E6"} else "",
            "source_id": "src1",
            "source_path_or_locator": "local.csv:1",
            "allowed_use": allowed_use,
            "forbidden_use": forbidden_use or "not_applicable",
            "family_id": "fam1",
            "leakage_group_id": f"leak-{sample_id}",
            "split_group_id": f"split-{sample_id}",
            "sealed_status": "DEV",
            "dataset_version": "v2_5_fixture",
            "mutation": "",
            "reference_sample_id": "",
            "pose_id": "",
            "pose_qc_status": "",
            "ordinary_bce_eligible": False,
            "missing_reason": "not_applicable_proxy" if evidence_level in {"E2", "E3"} else "not_applicable_no_mutation_or_pose",
        }
        row.update(extra)
        return row

    def write_fixture(
        self,
        root: Path,
        metrics_extra: dict[str, object] | None = None,
        bad_proxy_truth: bool = False,
        blinded_exposes_label: bool = False,
        bad_pose_gate: bool = False,
        registry_extra_rows: list[dict[str, object]] | None = None,
        external_overrides: dict[str, object] | None = None,
    ) -> None:
        exp = root / "experiments/phase2_5080_v1"
        rows = [
            self.registry_row("pos1", "E4", "assay_backed_positive", "EXPERIMENTAL_RANKING_ONLY"),
            self.registry_row("proxy1", "E2", "constructed_proxy", "proxy_stress_only", "ordinary_bce,verified_nonbinder", ordinary_bce_eligible=False),
            self.registry_row("ctrl1", "E4", "assay_backed_positive", "known_positive_calibration", "ordinary_train,ordinary_test,ordinary_candidate"),
        ]
        rows.extend(registry_extra_rows or [])
        if bad_proxy_truth:
            rows[1]["ground_truth_kind"] = "verified_nonbinder"
            rows[1]["ordinary_bce_eligible"] = True
        write_csv(exp / "data_splits/evidence_registry_v2_5.csv", rows, self.registry_fields)
        write_csv(exp / "prepared/phase2_v2_5_generic/nanobind_affinity_formal_blinded_v2_5.csv", [{"sample_id": "f1", **({"label_value": 1.0} if blinded_exposes_label else {"feature": 0.1})}])
        write_csv(exp / "prepared/phase2_v2_5_generic/nanobind_affinity_formal_labels_sealed_v2_5.csv", [{"sample_id": "f1", "label_value": 1.0}])
        external_row = {
            "source_id": "ext1", "source_version": "2026-07", "source_path_or_locator": "local/nanobind",
            "license_or_usage_status": "REVIEWED_LOCAL_USE", "redistribution_allowed": "false",
            "forbidden_use": "REDISTRIBUTION|BLOCKER_TRUTH", "enters_training_or_evaluation": "true",
            "accession_mapping_status": "complete", "sequence_mapping_status": "complete", "unit_normalization_status": "complete",
            "duplicate_policy": "dedupe_by_sequence_assay", "excluded_row_count": 0,
        }
        external_row.update(external_overrides or {})
        write_csv(exp / "data_splits/external_dataset_usage_manifest_v2_5.csv", [external_row])
        write_csv(exp / "prepared/pvrig_pose_proxy_summary_v2_5.csv", [
            {"sample_id": f"p{i}", "pose_id": f"pose{i}", "pose_qc_status": "exact_qc_pass" if i < 2 else "failed"}
            for i in range(4)
        ])
        metrics = {
            "calibration": {"status": "NOT_APPLICABLE", "reason": "no verified positive-and-negative probability labels"},
            "pose": {"global_fusion_applied": bad_pose_gate, "missingness_audit_pass": True},
            "generic_transfer_formal_pass": True,
            "formal_decision": {"claim_boundary": "ranking_evidence_not_experimental_blocker_validation"},
            "boundary": "generic transfer only; not biologically validated for PVRIG blockers",
        }
        if metrics_extra:
            metrics.update(metrics_extra)
        metrics_path = exp / "reports/phase2_v2_5_metrics_v1.json"
        write_json(metrics_path, metrics)
        write_json(exp / "audits/phase2_v2_5_preregistration_v1.json", {"status": "FROZEN_BEFORE_FORMAL_RUNS"})
        metrics["input_sha256"] = {"metrics_json": file_sha256(metrics_path)}
        write_json(metrics_path, metrics)

    def test_final_audit_passes_data_not_ready_and_keeps_generic_transfer_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root)
            result = build_audit(self.make_args(root))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["data_readiness"]["status"], "DATA_NOT_READY")
            self.assertEqual(result["formal_decision"]["status"], "PASS_GENERIC_TRANSFER_ONLY")
            self.assertEqual(result["calibration"]["status"], "NOT_APPLICABLE")

    def test_nanobind_generic_groups_cannot_satisfy_pvrig_target_readiness(self) -> None:
        generic_rows = []
        for group_index in range(8):
            for candidate_index in range(3):
                generic_rows.append(self.registry_row(
                    f"nanobind-{group_index}-{candidate_index}",
                    "E4",
                    "verified_negative" if candidate_index == 0 else "assay_backed_positive",
                    "EXPERIMENTAL_RANKING_ONLY",
                    target_id=f"NanoBind_generic_target_{group_index}",
                    target_sequence_sha256=f"nanobind-target-{group_index}",
                    target_construct="NanoBind_generic_antigen",
                    assay_batch=f"nanobind-batch-{group_index}",
                    source_id="nanobind",
                    family_id=f"nanobind-family-{group_index}",
                    split_group_id=f"nanobind-group-{group_index}",
                ))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(
                root,
                registry_extra_rows=generic_rows,
                metrics_extra={
                    "data_readiness": {
                        "status": "TARGET_FORMAL_READY",
                        "assay_backed_rank_groups": 8,
                        "verified_binary_positive": 16,
                        "verified_binary_negative": 8,
                        "independent_family_assay_blocks": 8,
                        "power_simulation": {
                            "estimated_power": 0.99,
                            "expected_ci_half_width": 0.01,
                            "formal_split_group_count": 8,
                            "formal_assay_or_source_block_count": 8,
                            "formal_labels_read": False,
                        },
                    },
                    "formal_decision": {
                        "primary_delta_vs_strong_baseline_ci_low_gt_zero": True,
                        "permutation_pass": True,
                        "seed_consistency_pass": True,
                        "contact_guardrail_pass": True,
                        "paratope_guardrail_pass": True,
                        "claim_boundary": "ranking_evidence_not_experimental_blocker_validation",
                    },
                },
            )
            result = build_audit(self.make_args(root))
            readiness = result["data_readiness"]
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(readiness["status"], "DATA_NOT_READY")
            self.assertEqual(readiness["assay_backed_rank_groups"], 0)
            self.assertEqual(readiness["verified_binary_negative"], 0)
            self.assertEqual(readiness["evidence_level_counts"], {"E4": 2, "E2": 1})
            self.assertEqual(result["formal_decision"]["status"], "PASS_GENERIC_TRANSFER_ONLY")

    def test_control_only_pvrig_groups_do_not_count_toward_target_readiness(self) -> None:
        control_rows = []
        for group_index in range(8):
            for candidate_index in range(3):
                control_rows.append(self.registry_row(
                    f"pvrig-control-{group_index}-{candidate_index}",
                    "E5",
                    "blocker_positive",
                    "CALIBRATION_LEAKAGE_CONTROL_ONLY",
                    "ordinary_train,ordinary_test,target_training,target_formal",
                    target_id="PVRIG_HUMAN_Q6DKI7",
                    assay_batch=f"control-batch-{group_index}",
                    source_id="historical-control-source",
                    family_id=f"control-family-{group_index}",
                    split_group_id=f"control-group-{group_index}",
                ))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, registry_extra_rows=control_rows)
            result = build_audit(self.make_args(root))
            readiness = result["data_readiness"]
            self.assertEqual(readiness["status"], "DATA_NOT_READY")
            self.assertEqual(readiness["assay_backed_rank_groups"], 0)
            self.assertEqual(readiness["verified_binary_positive"], 1)
            self.assertEqual(readiness["target_model_eligible_assay_rows"], 1)
            self.assertEqual(readiness["target_non_model_eligible_assay_rows"], 25)
            self.assertEqual(readiness["target_control_only_assay_rows"], 25)

    def test_nonranking_high_evidence_rows_do_not_count_toward_target_readiness(self) -> None:
        rows = []
        uses = ("POSE_PROXY_TRIAGE_ONLY", "CONTACT_SITE_GUARDRAIL_ONLY", "PROXY_STRESS_ONLY")
        for group_index in range(8):
            for candidate_index in range(3):
                rows.append(self.registry_row(
                    f"nonranking-{group_index}-{candidate_index}",
                    "E5",
                    "assay_backed_positive",
                    uses[group_index % len(uses)],
                    target_id="PVRIG_HUMAN_Q6DKI7",
                    assay_batch=f"nonranking-batch-{group_index}",
                    source_id="nonranking-source",
                    family_id=f"nonranking-family-{group_index}",
                    split_group_id=f"nonranking-group-{group_index}",
                ))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, registry_extra_rows=rows)
            readiness = build_audit(self.make_args(root))["data_readiness"]
            self.assertEqual(readiness["assay_backed_rank_groups"], 0)
            self.assertEqual(readiness["target_model_eligible_assay_rows"], 1)
            self.assertEqual(readiness["target_non_model_eligible_assay_rows"], 25)
            self.assertEqual(readiness["target_control_only_assay_rows"], 1)

    def test_external_reviewed_local_use_requires_nonredistribution_controls(self) -> None:
        invalid_overrides = [
            {"redistribution_allowed": "true"},
            {"forbidden_use": "BLOCKER_TRUTH"},
        ]
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_fixture(root, external_overrides=overrides)
                result = build_audit(self.make_args(root))
                self.assertIn("reviewed_local_use_training_requires_redistribution_prohibition", result["failed_checks"])

    def test_external_unapproved_usage_cannot_enter_training_or_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, external_overrides={"license_or_usage_status": "UNAPPROVED"})
            result = build_audit(self.make_args(root))
            self.assertIn("external_dataset_usage_approved_when_entering_training_or_evaluation", result["failed_checks"])

    def test_exp_dir_drives_default_formal_and_audit_paths(self) -> None:
        exp = Path("/tmp/custom_phase2_v2_5_exp")
        args = parse_args(["--exp-dir", str(exp), "--no-write"])
        self.assertEqual(args.evidence_registry, exp / "data_splits/evidence_registry_v2_5.csv")
        self.assertEqual(args.formal_manifest_blinded, exp / "prepared/phase2_v2_5_generic/nanobind_affinity_formal_blinded_v2_5.csv")
        self.assertEqual(args.formal_labels_sealed, exp / "prepared/phase2_v2_5_generic/nanobind_affinity_formal_labels_sealed_v2_5.csv")
        self.assertEqual(args.external_dataset_manifest, exp / "data_splits/external_dataset_usage_manifest_v2_5.csv")
        self.assertEqual(args.json_out, exp / "audits/phase2_v2_5_final_audit_v1.json")
        self.assertEqual(args.markdown_out, exp / "audits/PHASE2_V2_5_FINAL_AUDIT_V1.md")

    def test_missing_required_formal_or_external_artifact_is_invalid(self) -> None:
        for relative in (
            "prepared/phase2_v2_5_generic/nanobind_affinity_formal_blinded_v2_5.csv",
            "prepared/phase2_v2_5_generic/nanobind_affinity_formal_labels_sealed_v2_5.csv",
            "data_splits/external_dataset_usage_manifest_v2_5.csv",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_fixture(root)
                (root / "experiments/phase2_5080_v1" / relative).unlink()
                result = build_audit(self.make_args(root))
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["formal_decision"]["status"], "INVALID_RUN")

    def test_final_audit_hard_fails_proxy_truth_contamination_and_bce(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, bad_proxy_truth=True)
            result = build_audit(self.make_args(root))
            self.assertEqual(result["formal_decision"]["status"], "INVALID_RUN")
            self.assertIn("proxy_evidence_not_used_as_verified_truth", result["failed_checks"])
            self.assertIn("constructed_proxy_not_ordinary_bce_eligible", result["failed_checks"])

    def test_final_audit_hard_fails_blinded_label_exposure_and_bad_pose_fusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, blinded_exposes_label=True, bad_pose_gate=True)
            result = build_audit(self.make_args(root))
            self.assertIn("formal_blinded_manifest_does_not_expose_labels", result["failed_checks"])
            self.assertIn("pose_global_fusion_requires_80pct_exact_qc_coverage", result["failed_checks"])

    def test_final_audit_hard_fails_sha_mismatch_and_forbidden_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, metrics_extra={"boundary": "validated blocker with calibrated blocker probability"})
            exp = root / "experiments/phase2_5080_v1"
            metrics_path = exp / "reports/phase2_v2_5_metrics_v1.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["input_sha256"] = {"evidence_registry": "definitely-wrong"}
            write_json(metrics_path, metrics)
            result = build_audit(self.make_args(root))
            self.assertIn("registered_input_sha256_values_match", result["failed_checks"])
            self.assertIn("claim_boundary_excludes_forbidden_biological_claims", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
