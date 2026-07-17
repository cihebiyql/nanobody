#!/usr/bin/env python3
"""Label-free contract tests for the V4-H-QC96 formal preregistration.

These tests open only the V4-H preregistration/protocol/template and the
already-frozen V4-F V2 preregistration. They never resolve or open a Docking
label, prediction, one-shot lock, or formal output path.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any


SRC_DIR = Path(__file__).resolve().parent
EXP_DIR = SRC_DIR.parent
PREREG = EXP_DIR / "audits/phase2_v4_h_qc96_formal_evaluator_v1_preregistration.json"
PROTOCOL = EXP_DIR / "audits/phase2_v4_h_qc96_formal_evaluator_v1_protocol.md"
TEMPLATE = SRC_DIR / "templates/pvrig_v4_h_qc96_formal_evaluator_inputs_v1.json.in"
V4F_V2 = EXP_DIR / "audits/phase2_v4_f96_formal_evaluator_v2_preregistration.json"
EXPECTED_V4F_V2_SHA256 = "05d5727c7568ac9563c75d7ec7b916f172eefd915a728b829d29c25a12079fc3"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class V4HFormalPreregistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v4h = load_json(PREREG)
        cls.v4f = load_json(V4F_V2)
        cls.template = load_json(TEMPLATE)

    def test_v4f_v2_reference_is_the_hash_frozen_source(self) -> None:
        self.assertEqual(sha256_file(V4F_V2), EXPECTED_V4F_V2_SHA256)
        lineage = self.v4h["lineage_and_nonrevision"]
        self.assertEqual(lineage["v4_f_v2_preregistration_sha256"], EXPECTED_V4F_V2_SHA256)

    def test_estimand_is_qc_qualified_new_parent_design_universe(self) -> None:
        estimand = self.v4h["estimand"]
        self.assertEqual(estimand["name"], "V4_H_QC_QUALIFIED_NEW_PARENT_DESIGN_UNIVERSE")
        self.assertIn("Full-QC", estimand["target_population"])
        self.assertIn("first four", estimand["evaluation_sample"])
        self.assertIn("six patch-by-mode strata", estimand["evaluation_sample"])

    def test_panel_contract_is_balanced_96_without_replacement(self) -> None:
        panel = self.v4h["future_panel_contract"]
        self.assertEqual(panel["required_row_count"], 96)
        self.assertEqual(panel["required_parent_cluster_count"], 4)
        self.assertEqual(panel["required_candidates_per_parent"], 24)
        self.assertEqual(panel["required_strata_per_parent"], 6)
        self.assertEqual(panel["required_candidates_per_parent_stratum"], 4)
        self.assertEqual(4 * 6 * 4, panel["required_row_count"])
        self.assertIn("No replacement", panel["replacement_policy"])
        self.assertEqual(panel["artifact_state_at_preregistration"], "UNBOUND_NO_MANIFEST_HASH_ACCEPTED")

    def test_all_v4f_v2_mandatory_and_conditional_thresholds_are_unchanged(self) -> None:
        source = self.v4f["frozen_decision_thresholds"]
        target = self.v4h["scientific_evaluation_contract"]["frozen_decision_thresholds"]
        for key in (
            "applicability",
            "mandatory_absolute_gates",
            "conditional_shortcut_gates_if_shortcut_predictions_present",
            "random_ranking_ef_at_top10_baseline",
            "secondary_diagnostics_not_standalone_pass_gates",
        ):
            self.assertEqual(target[key], source[key], key)
        self.assertEqual(
            sha256_json(source),
            self.v4h["contract_equivalence_anchors"]["v4_f_v2_frozen_decision_thresholds_payload_sha256"],
        )

    def test_all_v4f_v2_metric_definitions_are_unchanged(self) -> None:
        source = self.v4f["metric_definitions"]
        target = self.v4h["scientific_evaluation_contract"]["metric_definitions"]
        self.assertEqual(target, source)
        self.assertEqual(
            sha256_json(source),
            self.v4h["contract_equivalence_anchors"]["v4_f_v2_metric_definitions_payload_sha256"],
        )

    def test_all_v4f_v2_minimum_denominators_are_unchanged(self) -> None:
        source = self.v4f["minimum_denominator_policy"]
        target = self.v4h["scientific_evaluation_contract"]["minimum_denominator_policy"]
        self.assertEqual(target, source)
        self.assertGreaterEqual(target["minimum_analyzable_count"], 64)
        self.assertGreaterEqual(target["required_parent_cluster_count"], 4)
        self.assertEqual(
            sha256_json(source),
            self.v4h["contract_equivalence_anchors"]["v4_f_v2_minimum_denominator_policy_payload_sha256"],
        )

    def test_prediction_scientific_policy_fields_are_unchanged(self) -> None:
        keys = (
            "primary_model_family",
            "primary_prediction_column",
            "primary_uncertainty_column",
            "primary_model_selection",
            "primary_endpoint",
            "endpoint_direction",
            "primary_metric",
            "secondary_metrics",
            "resampling_unit",
            "confidence_interval",
            "multiplicity_policy",
            "tie_break",
            "full_qc_attrition",
        )
        source_policy = self.v4f["frozen_prediction_gate"]["prediction_policy"]
        target_policy = self.v4h["future_prediction_freeze_contract"]
        source_subset = {key: source_policy[key] for key in keys}
        target_subset = {key: target_policy[key] for key in keys}
        self.assertEqual(target_subset, source_subset)
        self.assertEqual(
            sha256_json(source_subset),
            self.v4h["contract_equivalence_anchors"]["v4_f_v2_prediction_scientific_policy_subset_sha256"],
        )

    def test_docking_endpoint_seed_and_missingness_contract_are_unchanged(self) -> None:
        keys = (
            "allowed_seeds",
            "analyzable_status",
            "endpoint_bounds",
            "endpoint_direction",
            "independent_8X6B_and_9E6Y_docking_required",
            "minimum_successful_seeds_per_candidate_receptor",
            "primary_endpoint",
            "technical_failure_policy",
            "technical_failure_status",
        )
        source_contract = self.v4f["dual_docking_label_contract"]
        target_contract = self.v4h["future_dual_docking_label_contract"]
        source_subset = {key: source_contract[key] for key in keys}
        target_subset = {key: target_contract[key] for key in keys}
        self.assertEqual(target_subset, source_subset)
        self.assertEqual(
            sha256_json(source_subset),
            self.v4h["contract_equivalence_anchors"]["v4_f_v2_docking_endpoint_sampling_subset_sha256"],
        )

    def test_label_access_is_zero_and_no_formal_execution_is_declared(self) -> None:
        access = self.v4h["label_access_at_preregistration"]
        for key, value in access.items():
            if key.endswith("_read"):
                self.assertIs(value, False, key)
            else:
                self.assertEqual(value, 0, key)
        one_shot = self.v4h["one_shot_and_failure_policy"]
        self.assertIs(one_shot["one_shot_lock_created_at_preregistration"], False)
        self.assertIs(one_shot["one_shot_lock_path_bound_at_preregistration"], False)
        self.assertIs(one_shot["formal_evaluator_executed_at_preregistration"], False)

    def test_template_is_non_executable_and_every_future_input_is_unbound(self) -> None:
        self.assertEqual(
            self.template["status"],
            "TEMPLATE_ONLY_NOT_EXECUTABLE_ALL_FORMAL_INPUTS_UNBOUND",
        )
        artifacts = self.template["artifacts"]
        for name, artifact in artifacts.items():
            if "sha256" in artifact:
                self.assertTrue(artifact["sha256"].startswith("__UNBOUND_"), name)
            if name not in {"manifest", "manifest_audit", "manifest_receipt", "formal_output_directory"}:
                self.assertTrue(artifact["path"].startswith("__UNBOUND_"), name)
        self.assertIs(artifacts["one_shot_lock"]["created"], False)
        self.assertIs(self.template["formal_evaluator_executed"], False)
        for key, value in self.template["label_access"].items():
            if key.endswith("_read"):
                self.assertIs(value, False, key)
            else:
                self.assertEqual(value, 0, key)

    def test_current_scope_forbids_evaluator_lock_outputs_and_labels(self) -> None:
        forbidden = set(self.v4h["forbidden_current_artifacts"])
        self.assertIn("V4-H formal evaluator implementation", forbidden)
        self.assertIn("V4-H one-shot lock", forbidden)
        self.assertIn("V4-H formal evaluation output or receipt", forbidden)
        self.assertIn("V4-H Docking-label receipt or label table", forbidden)
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("one-shot lock created           = false", protocol)
        self.assertIn("V4-H label files opened         = 0", protocol)


if __name__ == "__main__":
    unittest.main()
