#!/usr/bin/env python3
"""Independent immutable audit of the explicit authorization package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path) -> dict:
    root = root.resolve()
    count = 0
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or path.is_symlink() or sha(path) != expected:
            raise RuntimeError(f"immutable_hash_gate:{relative}")
        count += 1
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text())
    graph = json.loads((root / manifest["job_graph"]["relative_path"]).read_text())
    overlay = json.loads((root / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json").read_text())
    if manifest["status"] != "PASS_EXPLICIT_AUTHORIZATION_LAYER_AUDITED_READY_TO_LAUNCH" or not manifest["launch_authorized"]:
        raise RuntimeError("authorization_manifest_gate")
    if graph["status"] != "READY_EXECUTABLE_POSTCALIBRATION_FREEZE" or graph["execution_authorized"] is not True:
        raise RuntimeError("authorization_graph_gate")
    if graph["sealed_evaluation_access_count"] != 0 or graph["prediction_metrics_access_count"] != 0:
        raise RuntimeError("sealed_access_gate")
    jobs = graph["jobs"]
    gpu = [j for j in jobs if j["kind"].startswith("GPU_")]
    if len(jobs) != 195 or len(gpu) != 90 or {j["physical_gpu"] for j in gpu} != {2, 4, 5}:
        raise RuntimeError("job_gpu_gate")
    if any(not isinstance(j.get("command"), list) or not j["command"] for j in gpu):
        raise RuntimeError("gpu_command_gate")
    if overlay["base_ready_manifest_sha256"] != manifest["base_ready_manifest_sha256"]:
        raise RuntimeError("base_ready_binding")
    return {
        "schema_version": "pvrig_v2_4_v2_2_2_authorized_package_independent_audit_v1",
        "status": "PASS_AUTHORIZED_PACKAGE_READY_TO_LAUNCH",
        "checked_file_count": count,
        "job_count": 195,
        "gpu_job_count": 90,
        "cpu_job_count": 105,
        "physical_gpus": [2, 4, 5],
        "sealed_evaluation_access_count": 0,
        "training_or_prediction_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()
    result = audit(args.package_root)
    if args.report_json:
        args.report_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
