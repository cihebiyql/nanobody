#!/usr/bin/env python3
"""Fail-closed verifier for the V4-D open-teacher release.

This verifier intentionally never parses the teacher TSV.  It checks only
hashes and release-boundary metadata so the prospective TEST32 remains sealed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_OUTPUT_SUMS = {
    "outputs/v4d_open_teacher.tsv",
    "outputs/v4d_open_teacher.tsv.audit.json",
    "outputs/EVALUATOR_STABLE.json",
    "outputs/open_teacher_postprocess_receipt.json",
}
REQUIRED_EVALUATOR_GATES = {
    "all_jobs_terminal",
    "manifest_bound_pose_evidence",
    "minimum_completed_seeds_per_entity_conformation",
    "row_artifacts_present",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}:root_not_object")
    return payload


def parse_sha256_file(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise ValueError(f"{path.name}:malformed_sha256_line")
        digest, name = fields
        name = name.lstrip("* ")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"{path.name}:invalid_digest")
        if name in entries:
            raise ValueError(f"{path.name}:duplicate_entry:{name}")
        entries[name] = digest
    return entries


def assess(root: Path) -> dict[str, Any]:
    reasons: list[str] = []
    outputs = root / "outputs"
    paths = {
        "status": root / "status/postprocess_status.json",
        "teacher": outputs / "v4d_open_teacher.tsv",
        "audit": outputs / "v4d_open_teacher.tsv.audit.json",
        "evaluator": outputs / "EVALUATOR_STABLE.json",
        "receipt": outputs / "open_teacher_postprocess_receipt.json",
        "sums": outputs / "SHA256SUMS",
        "archive": outputs / "v4d_open_teacher_delivery_v1.tar.gz",
        "archive_sum": outputs / "v4d_open_teacher_delivery_v1.tar.gz.sha256",
        "builder": root / "prepare_phase2_v4_d_open_teacher.py",
    }
    for name, path in paths.items():
        if not path.is_file() or path.is_symlink():
            reasons.append(f"missing_or_nonregular:{name}")

    if reasons:
        return {"status": "BLOCKED", "reasons": sorted(reasons), "test32_sealed": False}

    try:
        status = load_object(paths["status"])
        receipt = load_object(paths["receipt"])
        audit = load_object(paths["audit"])
        evaluator = load_object(paths["evaluator"])
        sums = parse_sha256_file(paths["sums"])
        archive_sums = parse_sha256_file(paths["archive_sum"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "BLOCKED",
            "reasons": [f"unreadable_release_metadata:{type(exc).__name__}:{exc}"],
            "test32_sealed": False,
        }

    if status.get("status") != "COMPLETE":
        reasons.append(f"postprocess_status_not_complete:{status.get('status', 'MISSING')}")

    expected_receipt = {
        "status": "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
        "row_count": 258,
        "split_counts": {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32},
        "sealed_test_raw_job_results_opened": 0,
        "sealed_metrics_used_for_teacher_or_ranking": False,
        "full_aggregate_streamed_only_for_open_row_closure": True,
    }
    for key, expected in expected_receipt.items():
        if receipt.get(key) != expected:
            reasons.append(f"receipt_field_mismatch:{key}")

    boundary = audit.get("sealed_data_boundary")
    if not isinstance(boundary, dict):
        reasons.append("audit_sealed_boundary_missing")
        boundary = {}
    expected_boundary = {
        "raw_job_results_opened": 0,
        "candidate_level_aggregate_rows_retained_or_released": 0,
        "sealed_metrics_used_for_teacher_or_ranking": False,
    }
    for key, expected in expected_boundary.items():
        if boundary.get(key) != expected:
            reasons.append(f"audit_sealed_boundary_mismatch:{key}")
    if audit.get("status") != "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE":
        reasons.append("audit_release_status_not_pass")

    closure = ((audit.get("inputs") or {}).get("raw_aggregate_closure") or {})
    if closure.get("status") != "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES":
        reasons.append("raw_aggregate_closure_not_pass")
    if int(closure.get("job_count", 0) or 0) != 1548:
        reasons.append("raw_aggregate_open_job_count_mismatch")
    if receipt.get("raw_aggregate_closure_sha256") != closure.get("closure_sha256"):
        reasons.append("raw_aggregate_closure_hash_mismatch")

    if evaluator.get("status") != "PASS" or evaluator.get("unlockable") is not True:
        reasons.append("evaluator_not_releasable")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        reasons.append("evaluator_evidence_mode_mismatch")
    if int(evaluator.get("job_count", 0) or 0) != 2022:
        reasons.append("evaluator_job_count_mismatch")
    gates = evaluator.get("gates")
    if not isinstance(gates, dict):
        reasons.append("evaluator_gates_missing")
        gates = {}
    for gate in sorted(REQUIRED_EVALUATOR_GATES):
        result = gates.get(gate)
        if not isinstance(result, dict) or result.get("status") != "PASS":
            reasons.append(f"evaluator_gate_not_pass:{gate}")

    expected_hashes = {
        "teacher_sha256": sha256_file(paths["teacher"]),
        "teacher_audit_sha256": sha256_file(paths["audit"]),
        "evaluator_sha256": sha256_file(paths["evaluator"]),
        "builder_sha256": sha256_file(paths["builder"]),
    }
    for key, observed in expected_hashes.items():
        if receipt.get(key) != observed:
            reasons.append(f"receipt_hash_mismatch:{key}")
    for key in ("job_manifest_sha256", "job_results_sha256", "pose_scores_sha256"):
        if receipt.get(key) != evaluator.get(key):
            reasons.append(f"receipt_evaluator_binding_mismatch:{key}")

    if set(sums) != EXPECTED_OUTPUT_SUMS:
        reasons.append("release_sha256sum_members_mismatch")
    else:
        for relative, expected in sorted(sums.items()):
            if sha256_file(root / relative) != expected:
                reasons.append(f"release_sha256_mismatch:{relative}")

    expected_archive_name = "outputs/v4d_open_teacher_delivery_v1.tar.gz"
    if set(archive_sums) != {expected_archive_name}:
        reasons.append("archive_sha256sum_members_mismatch")
    elif sha256_file(paths["archive"]) != archive_sums[expected_archive_name]:
        reasons.append("archive_sha256_mismatch")

    sealed = not any(
        reason.startswith((
            "receipt_field_mismatch:sealed_",
            "audit_sealed_",
            "raw_aggregate_",
        ))
        for reason in reasons
    )
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "reasons": sorted(reasons),
        "test32_sealed": sealed and not reasons,
        "release_receipt_sha256": sha256_file(paths["receipt"]),
        "delivery_archive_sha256": sha256_file(paths["archive"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    result = assess(parse_args().root)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
