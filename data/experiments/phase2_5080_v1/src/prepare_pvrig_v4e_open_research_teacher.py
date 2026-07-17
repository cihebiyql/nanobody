#!/usr/bin/env python3
"""Build an open-only V4-E research teacher after the original V4-D gate failed.

The original V4-D evaluator remains failed.  This builder requires a separate,
hash-bound retrospective method audit, opens raw evidence only for the 258 open
candidates, and never grants a prospective-test claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import prepare_phase2_v4_d_open_teacher as base


SCHEMA_VERSION = "pvrig_v4e_open_research_teacher_v1"
METHOD_STATUS = "PASS_METHOD_AUDIT"
RECEIPT_STATUS = "PASS_RETROSPECTIVE_METHOD_AUDIT_NO_LABEL_RELEASE"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise base.TeacherBuildError(f"json_root_not_object:{path}")
    return payload


def validate_v4e_gate(
    evaluator: Mapping[str, Any],
    evaluator_sha256: str,
    job_results_sha256: str,
    pose_scores_sha256: str,
    method_audit: Mapping[str, Any],
    method_audit_sha256: str,
    declaration: Mapping[str, Any],
    declaration_sha256: str,
    receipt: Mapping[str, Any],
) -> None:
    failures: list[str] = []
    if evaluator.get("status") != "FAIL" or evaluator.get("unlockable") is not False:
        failures.append("original_v4d_not_fail_closed")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        failures.append("original_v4d_not_pose_backed")
    bindings = {
        "job_count": base.EXPECTED_TOTAL_JOBS,
        "job_manifest_sha256": base.EXPECTED_JOB_MANIFEST_SHA256,
        "protocol_lock_sha256": base.EXPECTED_PROTOCOL_LOCK_SHA256,
        "protocol_core_sha256": base.EXPECTED_PROTOCOL_CORE_SHA256,
        "candidates_sha256": base.EXPECTED_CANDIDATES_SHA256,
        "stability_gate_spec_sha256": base.EXPECTED_STABILITY_SPEC_SHA256,
        "job_results_sha256": job_results_sha256,
        "pose_scores_sha256": pose_scores_sha256,
    }
    for key, expected in bindings.items():
        if evaluator.get(key) != expected:
            failures.append(f"original_v4d_binding_mismatch:{key}")
    gates = evaluator.get("gates")
    if not isinstance(gates, Mapping) or not gates:
        failures.append("original_v4d_gates_missing")
        gates = {}
    failed_gates = sorted(
        name for name, payload in gates.items()
        if not isinstance(payload, Mapping) or payload.get("status") != "PASS"
    )
    if failed_gates != ["candidate_threshold_sensitivity"]:
        failures.append("unexpected_original_v4d_failed_gates:" + ";".join(failed_gates))
    if gates.get("all_jobs_terminal", {}).get("status") != "PASS":
        failures.append("original_v4d_jobs_not_terminal")

    if method_audit.get("status") != METHOD_STATUS:
        failures.append("v4e_method_audit_not_pass")
    governance = method_audit.get("governance", {})
    if (
        governance.get("original_v4d_evaluator_modified") is not False
        or governance.get("original_v4d_evaluator_released") is not False
        or governance.get("candidate_level_labels_emitted") is not False
        or governance.get("prospective_test_validity_claimed") is not False
    ):
        failures.append("v4e_method_audit_governance_invalid")
    campaigns = {
        row.get("campaign"): row
        for row in method_audit.get("campaigns", [])
        if isinstance(row, Mapping)
    }
    if set(campaigns) != {"historical_v3", "target_v4d"}:
        failures.append("v4e_method_audit_campaign_set_invalid")
    elif any(row.get("status") != "PASS" for row in campaigns.values()):
        failures.append("v4e_method_audit_campaign_nonpass")
    target = campaigns.get("target_v4d", {})
    if target.get("pose_scores_sha256") != pose_scores_sha256:
        failures.append("v4e_target_pose_hash_mismatch")
    if target.get("source_evaluator_sha256") != evaluator_sha256:
        failures.append("v4e_target_evaluator_hash_mismatch")

    if declaration.get("status") != "FROZEN_POST_V4D_FAILURE_BEFORE_ANY_ROW_LEVEL_V4E_TEACHER_RELEASE":
        failures.append("v4e_declaration_status_invalid")
    declaration_governance = declaration.get("governance", {})
    if (
        declaration_governance.get("original_v4d_evaluator_remains_fail") is not True
        or declaration_governance.get("original_v4d_teacher_release_forbidden") is not True
        or declaration_governance.get(
            "current_32_candidate_test_not_valid_for_formal_prospective_claim_after_cohort_level_method_selection"
        ) is not True
    ):
        failures.append("v4e_declaration_governance_invalid")
    source_bindings = declaration.get("source_bindings", {})
    if source_bindings.get("v4d_evaluator_sha256") != evaluator_sha256:
        failures.append("v4e_declaration_evaluator_hash_mismatch")
    if source_bindings.get("v4d_pose_scores_sha256") != pose_scores_sha256:
        failures.append("v4e_declaration_pose_hash_mismatch")

    if receipt.get("status") != RECEIPT_STATUS:
        failures.append("v4e_method_receipt_status_invalid")
    if receipt.get("method_audit_sha256") != method_audit_sha256:
        failures.append("v4e_method_receipt_audit_hash_mismatch")
    if receipt.get("declaration_sha256") != declaration_sha256:
        failures.append("v4e_method_receipt_declaration_hash_mismatch")
    if receipt.get("original_v4d_evaluator_sha256") != evaluator_sha256:
        failures.append("v4e_method_receipt_evaluator_hash_mismatch")
    if receipt.get("candidate_level_labels_emitted") is not False or receipt.get("prospective_claim") is not False:
        failures.append("v4e_method_receipt_governance_invalid")

    if failures:
        raise base.TeacherBuildError("v4e_open_research_gate_failed:" + ",".join(failures))


def read_selected_open_evidence(
    results_root: Path,
    status_root: Path,
    selected_jobs: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], str]:
    successful_jobs = [
        job for job in selected_jobs
        if (results_root / job["job_id"] / "job_result.json").is_file()
    ]
    raw_poses, raw_results, bindings, _ = base.raw_pose_rows_for_jobs(
        results_root, successful_jobs
    )
    successful_ids = {row["job_id"] for row in raw_results}
    for job in selected_jobs:
        if job["job_id"] in successful_ids:
            continue
        status_path = status_root / f"{job['job_id']}.json"
        if not status_path.is_file():
            raise base.TeacherBuildError(f"selected_open_failure_status_missing:{job['job_id']}")
        raw = status_path.read_bytes()
        state = json.loads(raw)
        if state.get("status") != "FAILED_MAX_ATTEMPTS":
            raise base.TeacherBuildError(f"selected_open_missing_result_not_terminal_failure:{job['job_id']}")
        if state.get("job_id") != job["job_id"]:
            raise base.TeacherBuildError(f"selected_open_failure_status_identity_mismatch:{job['job_id']}")
        raw_results.append(
            {
                "job_id": job["job_id"],
                "job_hash": job["job_hash"],
                "state": "FAILED_MAX_ATTEMPTS",
                "pose_backed_2x2": "false",
                "selected_model_count": "",
            }
        )
        bindings.append(
            {
                "job_id": job["job_id"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_kind": "terminal_failure_status",
            }
        )
    bindings.sort(key=lambda row: row["job_id"])
    chain = hashlib.sha256(
        json.dumps(bindings, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return raw_poses, raw_results, bindings, chain


def verify_open_closure_with_failures(
    selected_jobs: list[dict[str, str]],
    raw_results: list[dict[str, str]],
    raw_pose_rows: list[dict[str, str]],
    aggregate_results: list[dict[str, str]],
    aggregate_pose_rows: list[dict[str, str]],
    raw_bindings: list[dict[str, str]],
) -> dict[str, Any]:
    raw_by_job = {row["job_id"]: row for row in raw_results}
    aggregate_by_job = {row["job_id"]: row for row in aggregate_results}
    jobs_by_id = {row["job_id"]: row for row in selected_jobs}
    if set(raw_by_job) != set(jobs_by_id) or set(aggregate_by_job) != set(jobs_by_id):
        raise base.TeacherBuildError("v4e_open_job_set_closure_failed")
    success_ids = {
        job_id for job_id, row in raw_by_job.items()
        if row["state"] in base.SUCCESS_STATES
    }
    raw_pose_by_key = {
        (row["job_id"], row["model"], row["scoring_reference"]): row
        for row in raw_pose_rows
    }
    aggregate_pose_by_key = {
        (row["job_id"], row["model"], row["scoring_reference"]): row
        for row in aggregate_pose_rows
    }
    if len(raw_pose_by_key) != len(raw_pose_rows) or len(aggregate_pose_by_key) != len(aggregate_pose_rows):
        raise base.TeacherBuildError("v4e_duplicate_pose_key")
    if set(raw_pose_by_key) != set(aggregate_pose_by_key):
        raise base.TeacherBuildError("v4e_raw_aggregate_pose_set_mismatch")
    pose_fields = (
        "haddock_score", "air_energy", "hotspot_overlap", "anchor_overlap",
        "holdout_overlap", "total_occlusion", "cdr3_occlusion", "cdr3_fraction",
        "clash_atom_pairs", "clash_residue_pairs", "overlay_rmsd_a",
    )
    for key, raw in raw_pose_by_key.items():
        aggregate = aggregate_pose_by_key[key]
        for field in pose_fields:
            if not base.numbers_equal(raw[field], aggregate.get(field)):
                raise base.TeacherBuildError(
                    f"v4e_raw_aggregate_pose_metric_mismatch:{':'.join(key)}:{field}"
                )
        if aggregate.get("geometry_class") != base.classify_geometry(raw):
            raise base.TeacherBuildError(f"v4e_raw_aggregate_pose_class_mismatch:{':'.join(key)}")
    failure_ids = sorted(set(jobs_by_id) - success_ids)
    pose_job_ids = {row["job_id"] for row in raw_pose_rows}
    for job_id in sorted(success_ids):
        raw = raw_by_job[job_id]
        aggregate = aggregate_by_job[job_id]
        if aggregate.get("job_hash") != jobs_by_id[job_id].get("job_hash"):
            raise base.TeacherBuildError(f"v4e_success_job_hash_mismatch:{job_id}")
        if aggregate.get("state", "").upper() != raw.get("state", "").upper():
            raise base.TeacherBuildError(f"v4e_success_state_mismatch:{job_id}")
        if aggregate.get("selected_model_count", "") != raw.get("selected_model_count", ""):
            raise base.TeacherBuildError(f"v4e_success_model_count_mismatch:{job_id}")
        if aggregate.get("pose_backed_2x2", "").lower() != "true":
            raise base.TeacherBuildError(f"v4e_success_not_pose_backed:{job_id}")
    for job_id in failure_ids:
        raw = raw_by_job[job_id]
        aggregate = aggregate_by_job[job_id]
        if raw["state"] != "FAILED_MAX_ATTEMPTS" or aggregate.get("state") != "FAILED_MAX_ATTEMPTS":
            raise base.TeacherBuildError(f"v4e_failure_state_mismatch:{job_id}")
        if aggregate.get("job_hash") != jobs_by_id[job_id].get("job_hash"):
            raise base.TeacherBuildError(f"v4e_failure_job_hash_mismatch:{job_id}")
        if aggregate.get("pose_backed_2x2", "").lower() != "false" or job_id in pose_job_ids:
            raise base.TeacherBuildError(f"v4e_failure_has_pose_evidence:{job_id}")
    canonical = json.dumps(
        {
            "failure_ids": failure_ids,
            "raw_bindings": raw_bindings,
            "aggregate_results": sorted(aggregate_results, key=lambda row: row["job_id"]),
            "aggregate_pose_rows": sorted(
                aggregate_pose_rows,
                key=lambda row: (row["job_id"], row["model"], row["scoring_reference"]),
            ),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "status": "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES_WITH_TERMINAL_FAILURES",
        "job_count": len(selected_jobs),
        "successful_job_count": len(success_ids),
        "failed_max_attempts_count": len(failure_ids),
        "failed_job_ids": failure_ids,
        "pose_row_count": len(raw_pose_rows),
        "closure_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def filter_native_overlay_qc(
    raw_pose_rows: list[dict[str, str]],
    selected_jobs: list[dict[str, str]],
    maximum_native_overlay_rmsd_a: float = 1.0,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    jobs = {row["job_id"]: row for row in selected_jobs}
    grouped: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in raw_pose_rows:
        grouped[(row["job_id"], row["model"])][row["scoring_reference"]] = row
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, Any]] = []
    valid_models_by_job: dict[str, int] = defaultdict(int)
    for (job_id, model), refs in sorted(grouped.items()):
        if set(refs) != set(base.CONFORMATIONS):
            raise base.TeacherBuildError(f"v4e_incomplete_model_pair:{job_id}:{model}")
        dock_conformation = jobs[job_id]["conformation"]
        native_rmsd = base.as_float(
            refs[dock_conformation].get("overlay_rmsd_a"), field="overlay_rmsd_a"
        )
        if native_rmsd > maximum_native_overlay_rmsd_a:
            dropped.append(
                {
                    "job_id": job_id,
                    "model": model,
                    "dock_conformation": dock_conformation,
                    "native_overlay_rmsd_a": native_rmsd,
                }
            )
            continue
        kept.extend(refs[reference] for reference in base.CONFORMATIONS)
        valid_models_by_job[job_id] += 1
    successful_job_ids = {
        row["job_id"] for row in raw_pose_rows
    }
    deficient = sorted(
        (job_id, valid_models_by_job[job_id])
        for job_id in successful_job_ids
        if valid_models_by_job[job_id] < 4
    )
    if deficient:
        raise base.TeacherBuildError(f"v4e_overlay_qc_fewer_than_4_models:{deficient[:10]}")
    return kept, {
        "status": "PASS_NATIVE_OVERLAY_MODEL_QC",
        "maximum_native_overlay_rmsd_a": maximum_native_overlay_rmsd_a,
        "input_complete_model_pair_count": len(grouped),
        "retained_complete_model_pair_count": len(grouped) - len(dropped),
        "dropped_complete_model_pair_count": len(dropped),
        "affected_job_count": len({row["job_id"] for row in dropped}),
        "minimum_retained_models_per_successful_job": min(valid_models_by_job.values()),
        "maximum_dropped_native_overlay_rmsd_a": max(
            (row["native_overlay_rmsd_a"] for row in dropped), default=0.0
        ),
        "dropped_models": dropped,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--job-results", type=Path, required=True)
    parser.add_argument("--pose-scores", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--status-root", type=Path, required=True)
    parser.add_argument("--v4d-evaluator", type=Path, required=True)
    parser.add_argument("--method-audit", type=Path, required=True)
    parser.add_argument("--method-declaration", type=Path, required=True)
    parser.add_argument("--method-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if base.sha256_file(args.split_manifest) != base.EXPECTED_SPLIT_MANIFEST_SHA256:
        raise base.TeacherBuildError("split_manifest_file_sha256_mismatch")
    split_rows = base.select_open_split(base.read_tsv(args.split_manifest))
    allowed_entities = {row["candidate_id"] for row in split_rows}
    job_results_sha = base.sha256_file(args.job_results)
    pose_scores_sha = base.sha256_file(args.pose_scores)
    evaluator_sha = base.sha256_file(args.v4d_evaluator)
    method_audit_sha = base.sha256_file(args.method_audit)
    declaration_sha = base.sha256_file(args.method_declaration)
    validate_v4e_gate(
        load_json(args.v4d_evaluator), evaluator_sha, job_results_sha, pose_scores_sha,
        load_json(args.method_audit), method_audit_sha,
        load_json(args.method_declaration), declaration_sha,
        load_json(args.method_receipt),
    )
    if base.sha256_file(args.job_manifest) != base.EXPECTED_JOB_MANIFEST_SHA256:
        raise base.TeacherBuildError("job_manifest_file_sha256_mismatch")
    selected_jobs = base.select_open_candidate_jobs(base.read_tsv(args.job_manifest), allowed_entities)
    raw_poses, raw_results, raw_bindings, raw_chain = read_selected_open_evidence(
        args.results_root, args.status_root, selected_jobs
    )
    selected_ids = {row["job_id"] for row in selected_jobs}
    aggregate_results, result_scan = base.read_tsv_for_job_ids(args.job_results, selected_ids)
    aggregate_poses, pose_scan = base.read_tsv_for_job_ids(args.pose_scores, selected_ids)
    closure = verify_open_closure_with_failures(
        selected_jobs, raw_results, raw_poses, aggregate_results, aggregate_poses, raw_bindings
    )
    filtered_poses, overlay_qc = filter_native_overlay_qc(raw_poses, selected_jobs)
    teacher = base.build_teacher_rows(
        split_rows, selected_jobs, raw_results, filtered_poses
    )
    base.write_tsv(args.out, teacher)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V4E_OPEN258_RETROSPECTIVE_RESEARCH_TEACHER",
        "row_count": len(teacher),
        "split_counts": base.OPEN_SPLIT_COUNTS,
        "original_v4d_evaluator_status": "FAIL",
        "prospective_claim": False,
        "formal_test_release_authorized": False,
        "sealed_test_boundary": {
            "model_split": base.SEALED_SPLIT,
            "row_count": base.SEALED_ROW_COUNT,
            "raw_job_results_opened": 0,
            "candidate_level_rows_released": 0,
            "valid_for_formal_prospective_claim": False,
            "new_independent_test_required": True,
        },
        "inputs": {
            "split_manifest_sha256": base.sha256_file(args.split_manifest),
            "job_manifest_sha256": base.sha256_file(args.job_manifest),
            "job_results_sha256": job_results_sha,
            "pose_scores_sha256": pose_scores_sha,
            "original_v4d_evaluator_sha256": evaluator_sha,
            "method_audit_sha256": method_audit_sha,
            "method_declaration_sha256": declaration_sha,
            "method_receipt_sha256": base.sha256_file(args.method_receipt),
            "selected_open_job_count": len(selected_jobs),
            "selected_raw_result_hash_bindings": raw_bindings,
            "selected_raw_result_sha256_chain": raw_chain,
            "aggregate_open_result_scan": result_scan,
            "aggregate_open_pose_scan": pose_scan,
            "raw_aggregate_closure": closure,
            "native_overlay_model_qc": overlay_qc,
        },
        "output": {"path": str(args.out), "sha256": base.sha256_file(args.out)},
        "primary_target": "R_dual_min",
        "claim_boundary": "Retrospective open-only computational geometry research teacher; not original V4-D release, prospective validation, binding, affinity, competition, or experimental blocking.",
    }
    audit_path = args.out.with_suffix(args.out.suffix + ".audit.json")
    base.write_json(audit_path, audit)
    print(json.dumps({"status": audit["status"], "rows": len(teacher), "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
