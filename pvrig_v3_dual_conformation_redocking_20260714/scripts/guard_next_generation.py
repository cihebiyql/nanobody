#!/usr/bin/env python3
"""Block any P2/P3/P4 generation until the exact frozen evaluator is stable."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import project_root, read_json, sha256_file


def blocked(reason: str) -> int:
    print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=project_root())
    parser.add_argument("--evaluator", default="reports/EVALUATOR_STABLE.json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    evaluator_path = Path(args.evaluator)
    if not evaluator_path.is_absolute():
        evaluator_path = root / evaluator_path
    lock_path = root / "PROTOCOL_LOCK.json"
    manifest_path = root / "manifests/docking_jobs.tsv"
    for path, label in ((evaluator_path, "evaluator"), (lock_path, "protocol_lock"), (manifest_path, "job_manifest")):
        if not path.is_file():
            return blocked(f"missing_{label}:{path}")
    evaluator = read_json(evaluator_path)
    lock = read_json(lock_path)
    if evaluator.get("status") != "PASS":
        return blocked(f"evaluator_status_not_pass:{evaluator.get('status', 'MISSING')}")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        return blocked(f"evaluator_evidence_mode_not_production:{evaluator.get('evidence_mode', 'MISSING')}")
    if any(item.get("status") != "PASS" for item in evaluator.get("gates", {}).values()):
        return blocked("one_or_more_evaluator_gates_not_pass")
    if lock.get("status") != "LOCKED":
        return blocked(f"protocol_lock_status_not_locked:{lock.get('status', 'MISSING')}")
    if evaluator.get("protocol_core_sha256") != lock.get("protocol_core_sha256"):
        return blocked("protocol_core_sha256_mismatch")
    if evaluator.get("protocol_lock_sha256") != lock.get("protocol_lock_sha256"):
        return blocked("protocol_lock_sha256_mismatch")
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != lock.get("job_manifest_sha256") or manifest_sha != evaluator.get("job_manifest_sha256"):
        return blocked("job_manifest_sha256_mismatch")
    print(
        json.dumps(
            {
                "status": "UNLOCKED",
                "evaluator": str(evaluator_path),
                "protocol_lock_sha256": lock["protocol_lock_sha256"],
                "job_manifest_sha256": manifest_sha,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
