#!/usr/bin/env python3
"""Fail-closed independent audit for a V2.2.2 strict nested package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(root: Path) -> dict:
    root = root.resolve()
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        raise RuntimeError("missing_SHA256SUMS")
    checked = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing_or_symlink:{relative}")
        observed = sha256_file(path)
        if observed != expected:
            raise RuntimeError(f"sha256_mismatch:{relative}:{observed}")
        checked += 1
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    graph_path = root / manifest["graph"]["relative_path"]
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if manifest["status"] != "PASS_AUDITED_DRY_RUN_NOT_AUTHORIZED_NOT_LAUNCHED":
        raise RuntimeError("manifest_status")
    if manifest["launch_authorized"] or manifest["training_or_prediction_executed"]:
        raise RuntimeError("manifest_execution_boundary")
    if graph["execution_authorized"] or graph["status"] != "DRY_RUN_PENDING_POSTCALIBRATION_FREEZE_DO_NOT_EXECUTE":
        raise RuntimeError("graph_execution_boundary")
    jobs = graph["jobs"]
    gpu = [job for job in jobs if job["kind"].startswith("GPU_")]
    if len(jobs) != 195 or len(gpu) != 90 or any(job.get("command") is not None for job in gpu):
        raise RuntimeError("job_or_command_contract")
    if {job["physical_gpu"] for job in gpu} != {2, 4, 5}:
        raise RuntimeError("gpu_contract")
    return {
        "schema_version": "pvrig_v2_4_v2_2_2_strict_nested_execution_package_independent_audit_v1",
        "status": "PASS_IMMUTABLE_NON_LAUNCHING_PACKAGE",
        "checked_file_count": checked,
        "job_count": len(jobs),
        "gpu_job_count": len(gpu),
        "cpu_job_count": len(jobs) - len(gpu),
        "physical_gpus": [2, 4, 5],
        "training_or_prediction_executed": False,
        "launch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()
    result = audit(args.package_root)
    if args.report_json:
        args.report_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
