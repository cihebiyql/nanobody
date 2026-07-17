#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

import prepare_phase2_v4_d_open_teacher as base
from prepare_pvrig_v4e_open_research_teacher import (
    filter_native_overlay_qc,
    validate_v4e_gate,
)


EVALUATOR_SHA = "evaluator-sha"
RESULTS_SHA = "results-sha"
POSES_SHA = "poses-sha"
METHOD_SHA = "method-sha"
DECLARATION_SHA = "declaration-sha"


def valid_inputs():
    gates = {
        "all_jobs_terminal": {"status": "PASS"},
        "candidate_threshold_sensitivity": {"status": "FAIL"},
        "other": {"status": "PASS"},
    }
    evaluator = {
        "status": "FAIL", "unlockable": False, "evidence_mode": "production_pose_backed",
        "job_count": base.EXPECTED_TOTAL_JOBS,
        "job_manifest_sha256": base.EXPECTED_JOB_MANIFEST_SHA256,
        "protocol_lock_sha256": base.EXPECTED_PROTOCOL_LOCK_SHA256,
        "protocol_core_sha256": base.EXPECTED_PROTOCOL_CORE_SHA256,
        "candidates_sha256": base.EXPECTED_CANDIDATES_SHA256,
        "stability_gate_spec_sha256": base.EXPECTED_STABILITY_SPEC_SHA256,
        "job_results_sha256": RESULTS_SHA, "pose_scores_sha256": POSES_SHA,
        "gates": gates,
    }
    method = {
        "status": "PASS_METHOD_AUDIT",
        "governance": {
            "original_v4d_evaluator_modified": False,
            "original_v4d_evaluator_released": False,
            "candidate_level_labels_emitted": False,
            "prospective_test_validity_claimed": False,
        },
        "campaigns": [
            {"campaign": "historical_v3", "status": "PASS"},
            {"campaign": "target_v4d", "status": "PASS", "pose_scores_sha256": POSES_SHA, "source_evaluator_sha256": EVALUATOR_SHA},
        ],
    }
    declaration = {
        "status": "FROZEN_POST_V4D_FAILURE_BEFORE_ANY_ROW_LEVEL_V4E_TEACHER_RELEASE",
        "governance": {
            "original_v4d_evaluator_remains_fail": True,
            "original_v4d_teacher_release_forbidden": True,
            "current_32_candidate_test_not_valid_for_formal_prospective_claim_after_cohort_level_method_selection": True,
        },
        "source_bindings": {"v4d_evaluator_sha256": EVALUATOR_SHA, "v4d_pose_scores_sha256": POSES_SHA},
    }
    receipt = {
        "status": "PASS_RETROSPECTIVE_METHOD_AUDIT_NO_LABEL_RELEASE",
        "method_audit_sha256": METHOD_SHA,
        "declaration_sha256": DECLARATION_SHA,
        "original_v4d_evaluator_sha256": EVALUATOR_SHA,
        "candidate_level_labels_emitted": False,
        "prospective_claim": False,
    }
    return evaluator, method, declaration, receipt


class V4EOpenResearchGateTests(unittest.TestCase):
    def call(self, values) -> None:
        evaluator, method, declaration, receipt = values
        validate_v4e_gate(
            evaluator, EVALUATOR_SHA, RESULTS_SHA, POSES_SHA,
            method, METHOD_SHA, declaration, DECLARATION_SHA, receipt,
        )

    def test_accepts_exact_single_gate_v4d_failure_and_bound_method_audit(self) -> None:
        self.call(valid_inputs())

    def test_rejects_any_second_failed_v4d_gate(self) -> None:
        values = list(valid_inputs())
        values[0] = copy.deepcopy(values[0])
        values[0]["gates"]["other"] = {"status": "FAIL"}
        with self.assertRaises(base.TeacherBuildError):
            self.call(values)

    def test_rejects_prospective_claim_or_hash_drift(self) -> None:
        values = list(valid_inputs())
        values[3] = copy.deepcopy(values[3])
        values[3]["prospective_claim"] = True
        with self.assertRaises(base.TeacherBuildError):
            self.call(values)

    def test_native_overlay_qc_drops_model_pair_but_retains_four_models(self) -> None:
        jobs = [{"job_id": "job", "conformation": "8x6b"}]
        rows = []
        for index in range(5):
            for reference in base.CONFORMATIONS:
                rows.append({
                    "job_id": "job", "model": f"m{index}",
                    "scoring_reference": reference,
                    "overlay_rmsd_a": "2.0" if index == 0 and reference == "8x6b" else "0.5",
                })
        kept, audit = filter_native_overlay_qc(rows, jobs)
        self.assertEqual(len(kept), 8)
        self.assertEqual(audit["dropped_complete_model_pair_count"], 1)
        self.assertEqual(audit["minimum_retained_models_per_successful_job"], 4)

    def test_native_overlay_qc_fails_if_fewer_than_four_models_remain(self) -> None:
        jobs = [{"job_id": "job", "conformation": "8x6b"}]
        rows = []
        for index in range(4):
            for reference in base.CONFORMATIONS:
                rows.append({
                    "job_id": "job", "model": f"m{index}",
                    "scoring_reference": reference,
                    "overlay_rmsd_a": "2.0" if index == 0 and reference == "8x6b" else "0.5",
                })
        with self.assertRaises(base.TeacherBuildError):
            filter_native_overlay_qc(rows, jobs)
        values = list(valid_inputs())
        values[1] = copy.deepcopy(values[1])
        values[1]["campaigns"][1]["pose_scores_sha256"] = "wrong"
        with self.assertRaises(base.TeacherBuildError):
            self.call(values)


if __name__ == "__main__":
    unittest.main()
