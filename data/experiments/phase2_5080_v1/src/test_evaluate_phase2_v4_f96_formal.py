#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import evaluate_phase2_v4_f96_formal as MOD


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...] | list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = root / "panel.tsv"
        self.panel_audit = root / "panel.audit.json"
        self.panel_receipt = root / "panel.receipt.json"
        self.predictions = root / "predictions.tsv"
        self.prediction_audit = root / "predictions.audit.json"
        self.prediction_receipt = root / "predictions.receipt.json"
        self.eligibility = root / "eligibility.tsv"
        self.eligibility_receipt = root / "eligibility.receipt.json"
        self.labels = root / "labels.tsv"
        self.label_receipt = root / "labels.receipt.json"
        self.output = root / "formal_output"
        self.panel_rows: list[dict[str, object]] = []
        self.prediction_rows: list[dict[str, object]] = []
        self.eligibility_rows: list[dict[str, object]] = []
        self.label_rows: list[dict[str, object]] = []
        self._build_rows()
        self.publish_all()

    def _build_rows(self) -> None:
        for parent_index, parent in enumerate(MOD.EXPECTED_PARENT_CLUSTERS):
            for local_index in range(24):
                candidate = f"CAND_{parent}_{local_index:02d}"
                sequence_hash = hashlib.sha256(candidate.encode()).hexdigest()
                identity = {
                    "candidate_id": candidate,
                    "sequence_sha256": sequence_hash,
                    "model_split": MOD.MODEL_SPLIT,
                    "parent_id": f"PARENT_{parent}",
                    "parent_framework_cluster": parent,
                    "design_method": "RFANTIBODY",
                    "design_mode": "H3" if local_index % 2 == 0 else "H1H3",
                    "target_patch_id": ("A_CENTER", "B_LOWER", "C_CROSS")[local_index % 3],
                    "cdr3_length": str(15 + local_index % 6),
                }
                self.panel_rows.append({**identity, "sequence": "A" * 120})
                truth = 0.10 + 0.75 * local_index / 23.0 + parent_index * 0.005
                uncertainty = 0.01 + 0.99 * local_index / 23.0
                error = 0.002 + 0.04 * uncertainty
                self.prediction_rows.append({
                    **identity,
                    "base_selected_model": "frozen_feature_ridge",
                    "base_predicted_geometry_score": 1.0 - truth,
                    "base_prediction_uncertainty": 0.5,
                    "embedding_selected_model": "joint_ridge",
                    "embedding_predicted_geometry_score": truth * 0.8 + 0.05,
                    "embedding_prediction_uncertainty": 0.2,
                    "contact_selected_model": "embedding_contact_fusion",
                    "contact_predicted_geometry_score": truth + error,
                    "contact_prediction_uncertainty": uncertainty,
                })
                self.eligibility_rows.append({
                    "candidate_id": candidate, "sequence_sha256": sequence_hash,
                    "parent_framework_cluster": parent, "model_split": MOD.MODEL_SPLIT,
                    "full_qc_hard_pass": "true", "full_qc_status": "PASS",
                    "replacement_used": "false",
                })
                self.label_rows.append({
                    "candidate_id": candidate, "sequence_sha256": sequence_hash,
                    "parent_framework_cluster": parent, "model_split": MOD.MODEL_SPLIT,
                    "docking_status": MOD.ANALYZABLE_STATUS,
                    "R_dual_min": format(truth, ".9g"),
                    "successful_seed_count_8X6B": "3",
                    "successful_seed_ids_8X6B": "917,1931,3253",
                    "successful_seed_count_9E6Y": "3",
                    "successful_seed_ids_9E6Y": "917,1931,3253",
                    "independent_receptor_docking": "true",
                    "technical_failure_reason": "",
                })

    def publish_panel(self) -> None:
        fields = list(MOD.IDENTITY_FIELDS) + ["sequence"]
        write_tsv(self.manifest, self.panel_rows, fields)
        write_json(self.panel_audit, {"execution_mode": "test_only", "row_count": 96})
        write_json(self.panel_receipt, {
            "execution_mode": "test_only", "manifest_sha256": sha(self.manifest),
            "audit_file_sha256": sha(self.panel_audit),
        })

    def publish_predictions(self) -> None:
        write_tsv(self.predictions, self.prediction_rows, MOD.PREDICTION_FIELDS)
        models = {
            family: str(self.prediction_rows[0][f"{family}_selected_model"])
            for family in ("base", "embedding", "contact")
        }
        write_json(self.prediction_audit, {
            "status": MOD.PREDICTION_STATUS, "execution_mode": "test_only", "row_count": 96,
            "v4_f_labels_read": False, "v4_f_label_files_opened": 0,
            "v4_f_label_paths_accepted": 0, "prediction_sha256": sha(self.predictions),
            "primary_evaluation_policy": MOD.PRIMARY_POLICY,
            "primary_evaluation_policy_sha256": MOD.sha256_json(MOD.PRIMARY_POLICY),
            "prediction_models": models,
        })
        write_json(self.prediction_receipt, {
            "schema_version": MOD.PREDICTION_SCHEMA_VERSION,
            "status": MOD.PREDICTION_STATUS, "execution_mode": "test_only", "row_count": 96,
            "v4_f_labels_read": False, "v4_f_label_paths_accepted": 0,
            "primary_evaluation_policy": MOD.PRIMARY_POLICY,
            "primary_evaluation_policy_sha256": MOD.sha256_json(MOD.PRIMARY_POLICY),
            "prediction_models": models,
            "holdout": {
                "manifest_sha256": sha(self.manifest), "audit_sha256": sha(self.panel_audit),
                "manifest_receipt_sha256": sha(self.panel_receipt),
            },
            "outputs": {
                "predictions": {"path": str(self.predictions.resolve()), "sha256": sha(self.predictions)},
                "audit": {"path": str(self.prediction_audit.resolve()), "sha256": sha(self.prediction_audit)},
            },
        })

    def publish_eligibility(self) -> None:
        write_tsv(self.eligibility, self.eligibility_rows, MOD.ELIGIBILITY_FIELDS)
        hard_pass = sum(str(row["full_qc_hard_pass"]).lower() == "true" for row in self.eligibility_rows)
        write_json(self.eligibility_receipt, {
            "schema_version": MOD.ELIGIBILITY_SCHEMA_VERSION, "status": MOD.ELIGIBILITY_STATUS,
            "execution_mode": "test_only", "manifest_sha256": sha(self.manifest),
            "row_count": 96, "hard_pass_count": hard_pass, "replacement_count": 0,
            "eligibility": {"path": str(self.eligibility.resolve()), "sha256": sha(self.eligibility)},
        })

    def publish_labels(self) -> None:
        write_tsv(self.labels, self.label_rows, MOD.LABEL_FIELDS)
        analyzable = sum(row["docking_status"] == MOD.ANALYZABLE_STATUS for row in self.label_rows)
        technical = sum(row["docking_status"] == MOD.TECHNICAL_FAILURE_STATUS for row in self.label_rows)
        expected_jobs = len(self.label_rows) * 2 * len(MOD.EXPECTED_SEEDS)
        write_json(self.label_receipt, {
            "schema_version": MOD.LABEL_SCHEMA_VERSION, "status": MOD.LABEL_STATUS,
            "execution_mode": "test_only",
            "prediction_receipt_sha256": sha(self.prediction_receipt),
            "evaluator_preregistration_sha256": MOD.EXPECTED_PREREG_SHA256,
            "evaluator_implementation_sha256": sha(MOD.SCRIPT_PATH),
            "manifest_sha256": sha(self.manifest),
            "eligibility_sha256": sha(self.eligibility),
            "eligible_hard_pass_count": len(self.label_rows), "label_row_count": len(self.label_rows),
            "analyzable_count": analyzable, "technical_failure_count": technical,
            "all_jobs_terminal": True, "receptors": ["8X6B", "9E6Y"],
            "seeds": list(MOD.EXPECTED_SEEDS),
            "expected_receptor_seed_job_count": expected_jobs,
            "terminal_receptor_seed_job_count": expected_jobs,
            "labels": {"path": str(self.labels.resolve()), "sha256": sha(self.labels)},
        })

    def publish_all(self) -> None:
        self.publish_panel()
        self.publish_predictions()
        self.publish_eligibility()
        self.publish_labels()

    def config(self, *, output: Path | None = None) -> MOD.EvaluationInputs:
        return MOD.EvaluationInputs(
            self.manifest, self.panel_audit, self.panel_receipt, self.prediction_receipt,
            self.eligibility_receipt, self.label_receipt, output or self.output,
            test_only=True, bootstrap_replicates=300,
        )


class MetricTests(unittest.TestCase):
    def test_average_tie_spearman(self) -> None:
        self.assertAlmostEqual(MOD.spearman(np.array([1, 1, 3, 4]), np.array([2, 2, 3, 5])), 1.0)

    def test_exact_twenty_percent_budget_uses_ceil_and_fixed_tie_break(self) -> None:
        labels = np.arange(10, dtype=float)
        scores = np.arange(10, dtype=float)
        result = MOD.top_quartile_recall_at_20pct(labels, scores, [f"C{i}" for i in range(10)])
        self.assertEqual(result["truth_top_quartile_count"], 3)
        self.assertEqual(result["budget_count"], 2)
        self.assertAlmostEqual(result["value"], 2 / 3)
        self.assertAlmostEqual(result["realized_budget_fraction"], 0.2)

    def test_ef10_uses_top_quartile_truth_and_random_baseline_one(self) -> None:
        labels = np.arange(20, dtype=float)
        scores = np.arange(20, dtype=float)
        result = MOD.enrichment_factor_at_10pct(
            labels, scores, [f"C{i:02d}" for i in range(20)]
        )
        self.assertEqual(result["truth_top_quartile_count"], 5)
        self.assertEqual(result["budget_count"], 2)
        self.assertEqual(result["hit_count"], 2)
        self.assertAlmostEqual(result["value"], 4.0)
        self.assertEqual(result["random_ranking_baseline"], 1.0)

    def test_constant_spearman_is_explicit_na(self) -> None:
        self.assertIsNone(MOD.spearman(np.arange(5), np.ones(5)))

    def test_zero_low_uncertainty_mae_never_serializes_infinity(self) -> None:
        rows = []
        for index in range(8):
            truth = index / 10
            rows.append({
                "candidate_id": f"C{index}", "R_dual_min": truth,
                "contact_predicted_geometry_score": truth if index < 2 else truth + 0.1,
                "contact_prediction_uncertainty": index,
            })
        result = MOD.uncertainty_selective_risk(rows)
        self.assertIsNone(result["high_vs_low_uncertainty_quartile_mae_ratio"])
        self.assertEqual(result["high_vs_low_ratio_zero_denominator_case"], "HIGH_POSITIVE_LOW_ZERO")
        json.dumps(result, allow_nan=False)


class FormalEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_one_shot_pass_and_lightweight_outputs(self) -> None:
        result = MOD.run_evaluation(self.fixture.config())
        self.assertEqual(result["status"], "PASS_V4_F96_COMPUTATIONAL_GEOMETRY_SURROGATE")
        self.assertEqual(result["hard_pass_count"], 96)
        self.assertEqual(result["analyzable_count"], 96)
        self.assertTrue(all(result["decision_gates"].values()))
        self.assertGreaterEqual(
            result["metrics"]["contact_primary"]["enrichment_factor_at_10pct"]["value"],
            3.0,
        )
        self.assertIn("ndcg", result["metrics"]["parent_macro"]["contact"])
        self.assertEqual(result["metrics"]["parent_macro"]["contact"]["defined_parent_count"], 4)
        self.assertEqual(sorted(path.name for path in self.fixture.output.iterdir()), sorted(MOD.OUTPUT_FILES))
        self.assertNotIn("sequence", (self.fixture.output / MOD.OUTPUT_FILES[0]).read_text())

    def test_prediction_receipt_failure_occurs_before_missing_label_path_is_opened(self) -> None:
        receipt = json.loads(self.fixture.prediction_receipt.read_text())
        receipt["status"] = "TAMPERED"
        write_json(self.fixture.prediction_receipt, receipt)
        self.fixture.label_receipt.unlink()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "prediction_receipt_status_invalid"):
            MOD.run_evaluation(self.fixture.config())

    def test_prediction_hash_tamper_fails_closed(self) -> None:
        self.fixture.predictions.write_text(self.fixture.predictions.read_text() + "\n")
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "prediction_tsv_hash_mismatch"):
            MOD.run_evaluation(self.fixture.config())

    def test_all_family_model_identities_are_checked_before_label_open(self) -> None:
        self.fixture.prediction_rows[-1]["base_selected_model"] = "other_model"
        self.fixture.publish_predictions()
        self.fixture.label_receipt.unlink()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "base_model_identity_varies_by_row"):
            MOD.run_evaluation(self.fixture.config())

    def test_exact_sequence_hash_join_is_required(self) -> None:
        self.fixture.label_rows[0]["sequence_sha256"] = "0" * 64
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "docking_label_identity_mismatch:sequence_sha256"):
            MOD.run_evaluation(self.fixture.config())

    def test_no_replacement_is_absolute(self) -> None:
        self.fixture.eligibility_rows[0]["replacement_used"] = "true"
        self.fixture.publish_eligibility()
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "replacement_forbidden"):
            MOD.run_evaluation(self.fixture.config())

    def test_full_qc_hard_fail_is_attrition_and_not_replaced(self) -> None:
        failed = self.fixture.eligibility_rows[:4]
        for row in failed:
            row["full_qc_hard_pass"] = "false"
            row["full_qc_status"] = "HARD_FAIL"
        failed_ids = {str(row["candidate_id"]) for row in failed}
        self.fixture.label_rows = [row for row in self.fixture.label_rows if str(row["candidate_id"]) not in failed_ids]
        self.fixture.publish_eligibility()
        self.fixture.publish_labels()
        result = MOD.run_evaluation(self.fixture.config())
        self.assertEqual(result["hard_pass_count"], 92)
        self.assertEqual(result["full_qc_hard_fail_count"], 4)
        self.assertEqual(result["analyzable_count"], 92)

    def test_technical_failure_is_na_and_below_coverage_becomes_insufficient(self) -> None:
        for row in self.fixture.label_rows[:40]:
            row["docking_status"] = MOD.TECHNICAL_FAILURE_STATUS
            row["R_dual_min"] = ""
            row["successful_seed_count_8X6B"] = "1"
            row["successful_seed_ids_8X6B"] = "917"
            row["successful_seed_count_9E6Y"] = "0"
            row["successful_seed_ids_9E6Y"] = ""
            row["technical_failure_reason"] = "HADDOCK_TECHNICAL_FAILURE"
        self.fixture.publish_labels()
        result = MOD.run_evaluation(self.fixture.config())
        self.assertEqual(result["status"], "INSUFFICIENT_TECHNICAL_COVERAGE")
        self.assertEqual(result["technical_failure_count"], 40)
        self.assertEqual(result["analyzable_count"], 56)

    def test_one_two_or_three_analyzable_rows_return_insufficient_not_exception(self) -> None:
        for keep in (1, 2, 3):
            with self.subTest(analyzable=keep):
                fixture = Fixture(self.root / f"small_{keep}")
                for row in fixture.label_rows[keep:]:
                    row["docking_status"] = MOD.TECHNICAL_FAILURE_STATUS
                    row["R_dual_min"] = ""
                    row["technical_failure_reason"] = "TECHNICAL"
                fixture.publish_labels()
                result = MOD.run_evaluation(fixture.config())
                self.assertEqual(result["status"], "INSUFFICIENT_TECHNICAL_COVERAGE")
                self.assertEqual(result["analyzable_count"], keep)
                self.assertIsNone(result["metrics"])

    def test_analyzable_requires_two_independent_seeds_per_receptor(self) -> None:
        row = self.fixture.label_rows[0]
        row["successful_seed_count_9E6Y"] = "1"
        row["successful_seed_ids_9E6Y"] = "917"
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "analyzable_seed_completeness_failed"):
            MOD.run_evaluation(self.fixture.config())

    def test_seed_count_and_id_set_must_match(self) -> None:
        self.fixture.label_rows[0]["successful_seed_count_8X6B"] = "2"
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "seed_ids_count_or_duplicate"):
            MOD.run_evaluation(self.fixture.config())

    def test_noninteger_seed_id_is_controlled_fail_closed(self) -> None:
        self.fixture.label_rows[0]["successful_seed_ids_8X6B"] = "917,BAD,3253"
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "invalid_seed_id"):
            MOD.run_evaluation(self.fixture.config())

    def test_technical_failure_must_not_use_na_string_or_numeric_sentinel(self) -> None:
        row = self.fixture.label_rows[0]
        row["docking_status"] = MOD.TECHNICAL_FAILURE_STATUS
        row["R_dual_min"] = "NA"
        row["technical_failure_reason"] = "FAILED"
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "technical_failure_R_dual_min_must_be_blank"):
            MOD.run_evaluation(self.fixture.config())

    def test_label_receipt_must_bind_prediction_prereg_and_evaluator(self) -> None:
        receipt = json.loads(self.fixture.label_receipt.read_text())
        receipt["prediction_receipt_sha256"] = "0" * 64
        write_json(self.fixture.label_receipt, receipt)
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "label_receipt_prediction_binding_mismatch"):
            MOD.run_evaluation(self.fixture.config())

    def test_label_release_requires_all_receptor_seed_jobs_terminal(self) -> None:
        receipt = json.loads(self.fixture.label_receipt.read_text())
        receipt["all_jobs_terminal"] = False
        receipt["terminal_receptor_seed_job_count"] -= 1
        write_json(self.fixture.label_receipt, receipt)
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "label_receipt_jobs_not_all_terminal"):
            MOD.run_evaluation(self.fixture.config())

    def test_fixed_contact_model_is_not_replaced_when_base_is_better(self) -> None:
        for pred, label in zip(self.fixture.prediction_rows, self.fixture.label_rows):
            truth = float(label["R_dual_min"])
            pred["contact_predicted_geometry_score"] = 1.0 - truth
            pred["base_predicted_geometry_score"] = truth
        self.fixture.publish_predictions()
        self.fixture.publish_labels()
        result = MOD.run_evaluation(self.fixture.config())
        self.assertEqual(result["status"], "FAIL_V4_F96_COMPUTATIONAL_GEOMETRY_SURROGATE")
        self.assertLess(result["metrics"]["contact_primary"]["spearman"], 0)
        self.assertGreater(result["metrics"]["base_descriptive"]["spearman"], 0)
        self.assertEqual(result["primary_model_family"], "contact")

    def test_predeclared_single_shortcut_is_compared_conditionally(self) -> None:
        for pred in self.fixture.prediction_rows:
            pred["base_selected_model"] = "cdr3_only"
        self.fixture.publish_predictions()
        prediction_receipt = json.loads(self.fixture.prediction_receipt.read_text())
        prediction_receipt["strongest_shortcut_model"] = "cdr3_only"
        write_json(self.fixture.prediction_receipt, prediction_receipt)
        self.fixture.publish_labels()
        result = MOD.run_evaluation(self.fixture.config())
        shortcut = result["metrics"]["conditional_shortcut"]
        self.assertEqual(shortcut["name"], "cdr3_only")
        self.assertTrue(all(shortcut["gates"].values()))

    def test_multiple_shortcuts_without_unique_prefrozen_comparator_fail(self) -> None:
        for pred in self.fixture.prediction_rows:
            pred["base_selected_model"] = "cdr3_only"
            pred["embedding_selected_model"] = "generic_prior_only"
        self.fixture.publish_predictions()
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "shortcut_present_without_prefrozen"):
            MOD.run_evaluation(self.fixture.config())

    def test_one_shot_refuses_existing_nonempty_output(self) -> None:
        self.fixture.output.mkdir()
        (self.fixture.output / "prior.txt").write_text("prior\n")
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "formal_output_directory_not_empty"):
            MOD.run_evaluation(self.fixture.config())

    def test_failed_unseal_consumes_external_one_shot_lock(self) -> None:
        receipt = json.loads(self.fixture.label_receipt.read_text())
        receipt["all_jobs_terminal"] = False
        write_json(self.fixture.label_receipt, receipt)
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "label_receipt_jobs_not_all_terminal"):
            MOD.run_evaluation(self.fixture.config())
        self.fixture.publish_labels()
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "formal_one_shot_lock_already_exists"):
            MOD.run_evaluation(self.fixture.config())

    def test_final_component_symlink_is_rejected(self) -> None:
        target = self.root / "target.txt"
        link = self.root / "link.txt"
        target.write_text("x\n")
        link.symlink_to(target)
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "symlink_forbidden"):
            MOD.snapshot(link, "adversarial")

    def test_production_path_overrides_are_forbidden(self) -> None:
        config = self.fixture.config()
        production = MOD.EvaluationInputs(
            config.manifest, config.manifest_audit, config.manifest_receipt,
            config.prediction_receipt, config.eligibility_receipt,
            config.label_receipt, config.output_dir, trust_anchor=self.root / "anchor.json",
            test_only=False,
        )
        with self.assertRaisesRegex(MOD.FormalEvaluationError, "production_path_override_forbidden"):
            MOD.guard_production_paths(production)

    def test_cli_does_not_accept_model_selection_or_threshold_arguments(self) -> None:
        parser = MOD.parser()
        option_strings = {option for action in parser._actions for option in action.option_strings}
        for forbidden in ("--model", "--threshold", "--primary-column", "--endpoint", "--bootstrap-seed"):
            self.assertNotIn(forbidden, option_strings)

    def test_preregistration_hash_is_frozen_and_label_blind(self) -> None:
        self.assertEqual(sha(MOD.PREREG_PATH), MOD.EXPECTED_PREREG_SHA256)
        payload = json.loads(MOD.PREREG_PATH.read_text())
        self.assertFalse(payload["label_access_at_freeze"]["v4_f96_docking_labels_read"])
        self.assertEqual(payload["frozen_decision_thresholds"]["mandatory_absolute_gates"]["overall_contact_spearman_minimum"], 0.30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
