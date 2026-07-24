#!/usr/bin/env python3
"""Aggregate candidate-only Docking results without the 47-control stability gate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import aggregate_results as legacy  # noqa: E402
from validate_protocol import FAIL, NOT_READY, PASS, evaluate as validate_protocol, load_rows  # noqa: E402


TERMINAL_TECHNICAL_NA = {
    "FAILED", "FAIL", "FAILED_MAX_ATTEMPTS", "TECHNICAL_NA", "CANCELLED", "TIMEOUT"
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["entity_id"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(root: Path, expected_total_jobs: int | None = None) -> dict[str, Any]:
    root = root.resolve()
    protocol_path = root / "config/protocol_spec.json"
    jobs_path = root / "manifests/docking_jobs.tsv"
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    validation = validate_protocol(
        protocol_path,
        jobs_path,
        report_dir / "PROTOCOL_VALIDATION_CANDIDATE_ONLY.json",
        expected_total_jobs,
    )
    jobs = load_rows(jobs_path)
    expected = expected_total_jobs if expected_total_jobs is not None else len(jobs)
    results_path = report_dir / "job_results.tsv"
    poses_path = report_dir / "pose_scores.tsv"
    results = legacy.collect_results(root, jobs, results_path, poses_path) if jobs else []

    state_counts = Counter(str(row.get("state", "PENDING")).upper() for row in results)
    pending_states = legacy.PENDING_STATES
    pending = sum(state_counts.get(state, 0) for state in pending_states)
    unknown_terminal = sorted(
        state for state in state_counts
        if state not in pending_states
        and state not in legacy.SUCCESS_STATES
        and state not in TERMINAL_TECHNICAL_NA
    )

    by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_entity[str(row.get("entity_id", ""))].append(row)
    candidate_rows: list[dict[str, Any]] = []
    for entity_id, rows in sorted(by_entity.items()):
        success = [row for row in rows if legacy.is_success(row)]
        technical_na = [
            row for row in rows
            if str(row.get("state", "")).upper() in TERMINAL_TECHNICAL_NA
        ]
        successful_seeds = {
            conformation: len(
                {
                    str(row.get("seed", "")) for row in success
                    if row.get("conformation") == conformation
                }
            )
            for conformation in ("8x6b", "9e6y")
        }
        candidate_rows.append(
            {
                "entity_id": entity_id,
                "successful_jobs": len(success),
                "technical_na_jobs": len(technical_na),
                "pending_jobs": len(rows) - len(success) - len(technical_na),
                "successful_seeds_8x6b": successful_seeds["8x6b"],
                "successful_seeds_9e6y": successful_seeds["9e6y"],
                "two_seed_dual_receptor_success": str(
                    successful_seeds == {"8x6b": 2, "9e6y": 2}
                ).lower(),
                "strict_a_jobs": sum(row.get("representative_pair_label") == "STRICT_A" for row in success),
                "supported_ab_jobs": sum(row.get("representative_pair_label") in {"STRICT_A", "SUPPORTED_AB"} for row in success),
            }
        )
    candidate_summary_path = report_dir / "candidate_only_summary.tsv"
    write_tsv(candidate_summary_path, candidate_rows)

    reasons = []
    if validation["status"] != PASS:
        reasons.append("candidate_only_protocol_validation_not_pass")
    if len(results) != expected:
        reasons.append(f"expected_{expected}_result_rows_got_{len(results)}")
    if pending:
        reasons.append(f"jobs_not_terminal:{pending}")
    if unknown_terminal:
        reasons.append(f"unknown_terminal_states:{','.join(unknown_terminal)}")
    if validation["status"] == FAIL or unknown_terminal:
        status = FAIL
    elif reasons:
        status = NOT_READY
    else:
        status = "PASS_TERMINAL_CANDIDATE_ONLY"
    payload = {
        "schema_version": "pvrig.external_candidate_aggregate.v2",
        "status": status,
        "candidate_only": True,
        "controls_applied": False,
        "calibrated_evaluator_stability_claim": False,
        "expected_jobs": expected,
        "observed_jobs": len(results),
        "candidate_count": len(by_entity),
        "state_counts": dict(state_counts),
        "technical_na_jobs": sum(state_counts.get(state, 0) for state in TERMINAL_TECHNICAL_NA),
        "fully_successful_two_seed_dual_receptor_candidates": sum(
            row["two_seed_dual_receptor_success"] == "true" for row in candidate_rows
        ),
        "reasons": reasons,
        "reports": {
            "protocol_validation": "reports/PROTOCOL_VALIDATION_CANDIDATE_ONLY.json",
            "job_results": "reports/job_results.tsv",
            "pose_scores": "reports/pose_scores.tsv",
            "candidate_summary": "reports/candidate_only_summary.tsv",
        },
        "claim_boundary": (
            "Candidate-only result aggregation. Technical failures are NA, not biological "
            "negatives. No 47-control calibration, binding, Kd, IC50 or experimental blocking claim."
        ),
    }
    write_json(report_dir / "CANDIDATE_ONLY_AGGREGATE.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--expected-total-jobs", type=int)
    args = parser.parse_args()
    payload = aggregate(args.root, args.expected_total_jobs)
    print(json.dumps({"status": payload["status"], "root": str(args.root)}, sort_keys=True))
    return 0 if payload["status"] == "PASS_TERMINAL_CANDIDATE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
