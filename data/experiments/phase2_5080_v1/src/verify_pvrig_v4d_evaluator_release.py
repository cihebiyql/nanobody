#!/usr/bin/env python3
"""Fail-closed release gate for a terminal PVRIG V4-D evaluator artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_GATES = {
    "all_jobs_terminal",
    "manifest_bound_pose_evidence",
    "minimum_completed_seeds_per_entity_conformation",
    "row_artifacts_present",
}


def assess(payload: dict[str, Any], expected_job_count: int) -> dict[str, Any]:
    gates = payload.get("gates")
    reasons: list[str] = []

    if payload.get("status") != "PASS":
        reasons.append("evaluator_status_not_pass")
    if payload.get("unlockable") is not True:
        reasons.append("evaluator_not_unlockable")
    if payload.get("evidence_mode") != "production_pose_backed":
        reasons.append("evidence_mode_not_production_pose_backed")
    if int(payload.get("job_count", 0) or 0) != expected_job_count:
        reasons.append("job_count_mismatch")
    if not isinstance(gates, dict) or not gates:
        reasons.append("gates_missing")
        gates = {}

    missing = sorted(REQUIRED_GATES - set(gates))
    reasons.extend(f"required_gate_missing:{name}" for name in missing)
    reasons.extend(
        f"gate_not_pass:{name}"
        for name, result in sorted(gates.items())
        if not isinstance(result, dict) or result.get("status") != "PASS"
    )

    return {
        "status": "READY" if not reasons else "BLOCKED",
        "reason": "all_evaluator_gates_pass" if not reasons else ",".join(reasons),
        "expected_job_count": expected_job_count,
        "observed_job_count": int(payload.get("job_count", 0) or 0),
        "failed_max_attempts": int(
            (gates.get("all_jobs_terminal") or {}).get("counts", {}).get(
                "FAILED_MAX_ATTEMPTS", 0
            )
            or 0
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--expected-job-count", type=int, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = json.loads(args.evaluator.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("evaluator root must be an object")
        result = assess(payload, args.expected_job_count)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "status": "BLOCKED",
            "reason": f"evaluator_unreadable:{type(exc).__name__}",
            "expected_job_count": args.expected_job_count,
            "observed_job_count": 0,
            "failed_max_attempts": 0,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
