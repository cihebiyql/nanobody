#!/usr/bin/env python3
"""Monitor Node1 ProteinMPNN and bxcpu Docking every 30 minutes."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
LATEST = RUNTIME / "LATEST.json"
HISTORY = RUNTIME / "history.jsonl"
LOCK = RUNTIME / "monitor.lock"

NODE1_ROOT = Path(
    "/data1/qlyu/projects/pvrig_1m_fixed_pose_mpnn150k_v1_20260722"
)
NODE1_DOCKING_ROOT = Path(
    "/data1/qlyu/projects/"
    "pvrig_c2_new4220_seed42_3047_docking_results_v1_20260723/"
    "c2_new4220_seed42_3047"
)
BXCPU_ROOT = (
    "$HOME/pvrig_c2_new4220_seed42_3047_v1_20260723_bxcpu_results"
)
EXPECTED_MPNN_OUTPUTS = 237_600
EXPECTED_MPNN_POSES = 99
EXPECTED_DOCKING_JOBS = 16_880


def run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_json_output(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    if result.returncode != 0:
        return {
            "probe_status": "ERROR",
            "probe_label": label,
            "return_code": result.returncode,
            "stderr": result.stderr[-4000:],
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "probe_status": "ERROR",
            "probe_label": label,
            "return_code": result.returncode,
            "parse_error": str(exc),
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
    payload["probe_status"] = "PASS"
    return payload


def probe_node1() -> dict[str, Any]:
    remote = f"""python3 - <<'PY'
import json, os, re, shutil
from pathlib import Path

root = Path({str(NODE1_ROOT)!r})
docking = Path({str(NODE1_DOCKING_ROOT)!r})

def count_files(base, pattern):
    return sum(1 for _ in base.glob(pattern)) if base.exists() else 0

controller = {{}}
try:
    controller = json.loads((root / "status/controller.json").read_text())
except Exception as exc:
    controller = {{"state": "UNKNOWN", "read_error": str(exc)}}

outputs = count_files(root / "generation", "workers/*/outputs/*_dldesign_*.pdb")
checkpoints = 0
for path in (root / "generation").glob("workers/*/status/mpnn.checkpoint"):
    try:
        checkpoints += sum(1 for line in path.open() if line.strip())
    except OSError:
        pass
workers_complete = count_files(root / "generation", "workers/*/status/complete")

error_pattern = re.compile(r"failed in|output mismatch|out of memory|Traceback", re.I)
errors = 0
for base in (root / "generation", root / "logs"):
    if not base.exists():
        continue
    for path in base.rglob("*.log"):
        try:
            errors += sum(1 for line in path.open(errors="replace") if error_pattern.search(line))
        except OSError:
            pass

disk = shutil.disk_usage("/data1")
pid = controller.get("pid")
controller_alive = bool(pid and Path(f"/proc/{{pid}}").exists())

payload = {{
    "host": os.uname().nodename,
    "controller": controller,
    "controller_alive": controller_alive,
    "generation_outputs": outputs,
    "generation_expected": {EXPECTED_MPNN_OUTPUTS},
    "generation_fraction": outputs / {EXPECTED_MPNN_OUTPUTS},
    "pose_checkpoints": checkpoints,
    "pose_expected": {EXPECTED_MPNN_POSES},
    "workers_complete": workers_complete,
    "worker_expected": 21,
    "error_lines": errors,
    "data1_free_bytes": disk.free,
    "data1_total_bytes": disk.total,
    "docking_sync_status_files": count_files(docking, "status/jobs/*.json"),
    "docking_sync_result_files": count_files(docking, "results/*/job_result.json"),
}}
print(json.dumps(payload, sort_keys=True))
PY"""
    result = run(
        [
            "ssh.exe",
            "-o",
            "BatchMode=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=6",
            "node1",
            remote,
        ]
    )
    return parse_json_output(result, "node1")


def probe_bxcpu() -> dict[str, Any]:
    remote = f"""python3 - <<'PY'
import collections, json, os, subprocess, time
from pathlib import Path

root = Path(os.path.expandvars({BXCPU_ROOT!r}))
counts = collections.Counter()
newest = 0.0
for path in (root / "status/jobs").glob("*.json"):
    try:
        data = json.loads(path.read_text())
        counts[data.get("status", "UNKNOWN")] += 1
        newest = max(newest, path.stat().st_mtime)
    except Exception:
        counts["PARSE_ERROR"] += 1

def state(job_id):
    q = subprocess.run(
        ["squeue", "-h", "-j", job_id, "-o", "%T"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    ).stdout.strip().splitlines()
    if q:
        return q[0]
    a = subprocess.run(
        ["sacct", "-j", job_id, "-X", "--format=State", "-n"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    ).stdout.strip().splitlines()
    return a[0].strip().split()[0] if a else "MISSING"

stat = os.statvfs(root if root.exists() else Path.home())
payload = {{
    "host": os.uname().nodename,
    "status_counts": dict(counts),
    "terminal": sum(counts.values()),
    "expected": {EXPECTED_DOCKING_JOBS},
    "terminal_fraction": sum(counts.values()) / {EXPECTED_DOCKING_JOBS},
    "job_results": sum(1 for _ in (root / "results").glob("*/job_result.json")),
    "compressed_queue_archives": sum(1 for _ in (root / "compressed_queue").glob("*.tar.gz")),
    "latest_status_age_seconds": (time.time() - newest) if newest else None,
    "array_job_id": "11944867",
    "array_state": state("11944867"),
    "audit_job_id": "11944875",
    "audit_state": state("11944875"),
    "filesystem_free_bytes": stat.f_bavail * stat.f_frsize,
    "filesystem_total_bytes": stat.f_blocks * stat.f_frsize,
}}
print(json.dumps(payload, sort_keys=True))
PY"""
    result = run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=6",
            "bxcpu",
            remote,
        ]
    )
    return parse_json_output(result, "bxcpu")


def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def collect() -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    node1 = probe_node1()
    bxcpu = probe_bxcpu()
    alerts: list[str] = []

    if node1.get("probe_status") != "PASS":
        alerts.append("NODE1_PROBE_ERROR")
    else:
        state = node1.get("controller", {}).get("state")
        if state in {"FAILED", "BLOCKED", "HOLD"}:
            alerts.append(f"NODE1_CONTROLLER_{state}")
        if node1.get("error_lines", 0):
            alerts.append("NODE1_MPNN_ERRORS_PRESENT")
        if node1.get("data1_free_bytes", 0) < 20 * 1024**3:
            alerts.append("NODE1_DATA1_FREE_BELOW_20_GIB")

    if bxcpu.get("probe_status") != "PASS":
        alerts.append("BXCPU_PROBE_ERROR")
    else:
        if bxcpu.get("latest_status_age_seconds") is not None and bxcpu[
            "latest_status_age_seconds"
        ] > 1800:
            alerts.append("BXCPU_STATUS_STALE")
        if bxcpu.get("status_counts", {}).get("PARSE_ERROR", 0):
            alerts.append("BXCPU_STATUS_PARSE_ERROR")

    complete = (
        node1.get("probe_status") == "PASS"
        and node1.get("controller", {}).get("state") == "COMPLETE"
        and bxcpu.get("probe_status") == "PASS"
        and bxcpu.get("terminal") == EXPECTED_DOCKING_JOBS
        and bxcpu.get("audit_state") == "COMPLETED"
    )
    payload = {
        "schema_version": "pvrig.node1_bxcpu.combined_monitor.v1",
        "generated_at_utc": generated_at,
        "interval_seconds": 1800,
        "status": "PASS" if not alerts else "ATTENTION",
        "alerts": alerts,
        "complete": complete,
        "node1": node1,
        "bxcpu": bxcpu,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=1800)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    RUNTIME.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("node1-bxcpu combined monitor already running")
            return 0

        lock_handle.write(str(os.getpid()) + "\n")
        lock_handle.flush()
        while True:
            payload = collect()
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            atomic_write(LATEST, text)
            with HISTORY.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
            if args.once or payload["complete"]:
                return 0
            time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    raise SystemExit(main())
