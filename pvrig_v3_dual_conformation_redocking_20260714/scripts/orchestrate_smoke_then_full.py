#!/usr/bin/env python3
"""Run the fixed smoke matrix, verify 2x2 evidence, then enter the full queue."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from common import project_root, read_json, read_tsv, write_json


def verify_smoke(root: Path) -> dict[str, object]:
    rows = read_tsv(root / "manifests/smoke_jobs.tsv")
    lock = read_json(root / "PROTOCOL_LOCK.json")
    reasons: list[str] = []
    details: list[dict[str, object]] = []
    expected = int(read_json(root / "config/protocol_spec.json")["docking"]["expected_smoke_jobs"])
    if len(rows) != expected:
        reasons.append(f"expected_{expected}_smoke_jobs_got_{len(rows)}")
    for row in rows:
        state = read_json(root / "status/jobs" / f"{row['job_id']}.json", {})
        evidence_path = root / str(state.get("evidence") or f"results/{row['job_id']}/job_result.json")
        evidence = read_json(evidence_path, {})
        pose_scores = evidence.get("pose_scores", []) if isinstance(evidence, dict) else []
        reference_sets = [
            {score.get("reference_id") for score in pose.get("scores", [])}
            for pose in pose_scores
            if isinstance(pose, dict)
        ]
        job_reasons: list[str] = []
        if state.get("status") != "SUCCESS":
            job_reasons.append(f"state_{state.get('status', 'MISSING')}")
        if not evidence_path.is_file():
            job_reasons.append("evidence_missing")
        if evidence.get("job_hash") != row["job_hash"]:
            job_reasons.append("job_hash_mismatch")
        if evidence.get("protocol_core_sha256") != lock.get("protocol_core_sha256"):
            job_reasons.append("protocol_core_sha256_mismatch")
        if int(evidence.get("selected_model_count", 0) or 0) < 1:
            job_reasons.append("no_selected_models")
        if not reference_sets or any(refs != {"8x6b", "9e6y"} for refs in reference_sets):
            job_reasons.append("native_cross_2x2_incomplete")
        reasons.extend(f"{row['job_id']}:{reason}" for reason in job_reasons)
        details.append(
            {
                "job_id": row["job_id"],
                "entity_id": row["entity_id"],
                "conformation": row["conformation"],
                "seed": row["seed"],
                "status": "PASS" if not job_reasons else "FAIL",
                "reasons": job_reasons,
                "selected_model_count": evidence.get("selected_model_count", 0),
            }
        )
    payload = {
        "status": "PASS" if not reasons else "FAIL",
        "protocol_core_sha256": lock.get("protocol_core_sha256", ""),
        "protocol_lock_sha256": lock.get("protocol_lock_sha256", ""),
        "smoke_job_count": len(rows),
        "reasons": reasons,
        "jobs": details,
    }
    write_json(root / "reports/SMOKE_VALIDATION.json", payload)
    return payload


def main() -> int:
    root = Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()
    python = sys.executable
    validate = subprocess.run([python, str(root / "scripts/validate_protocol.py")], cwd=root, env=os.environ)
    if validate.returncode != 0:
        return validate.returncode
    smoke = subprocess.run(
        [
            python,
            str(root / "scripts/run_controller.py"),
            "--job-list",
            "manifests/smoke_jobs.tsv",
            "--poll-seconds",
            "15",
        ],
        cwd=root,
        env=os.environ,
    )
    if smoke.returncode != 0:
        verify_smoke(root)
        return smoke.returncode
    payload = verify_smoke(root)
    if payload["status"] != "PASS":
        return 1
    write_json(root / "status/orchestrator.json", {"status": "SMOKE_PASS_STARTING_FULL", "smoke_validation": "reports/SMOKE_VALIDATION.json"})
    full = subprocess.run(
        [python, str(root / "scripts/run_controller.py"), "--poll-seconds", "60"],
        cwd=root,
        env={**os.environ, "PVRIG_PROJECT_ROOT": str(root)},
    )
    aggregate = subprocess.run(
        [python, str(root / "scripts/aggregate_results.py")],
        cwd=root,
        env={**os.environ, "PVRIG_PROJECT_ROOT": str(root)},
    )
    write_json(
        root / "status/orchestrator.json",
        {
            "status": "COMPLETE" if full.returncode == 0 and aggregate.returncode == 0 else "COMPLETE_REVIEW_REQUIRED",
            "full_controller_returncode": full.returncode,
            "aggregate_returncode": aggregate.returncode,
            "smoke_validation": "reports/SMOKE_VALIDATION.json",
            "evaluator": "reports/EVALUATOR_STABLE.json",
        },
    )
    return aggregate.returncode if full.returncode == 0 else full.returncode


if __name__ == "__main__":
    raise SystemExit(main())
