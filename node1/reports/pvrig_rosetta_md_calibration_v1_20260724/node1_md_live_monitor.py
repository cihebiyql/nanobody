#!/usr/bin/env python3
"""Continuously publish atomic live status for MD production and analysis."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def pid_state(path: Path) -> dict[str, object]:
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return {"pid": None, "alive": False}
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    return {"pid": pid, "alive": alive}


def latest_step(log: Path) -> tuple[int, float]:
    if not log.is_file():
        return 0, 0.0
    matches = re.findall(
        r"^\s*(\d+)\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        log.read_text(encoding="utf-8", errors="replace"),
        flags=re.MULTILINE,
    )
    return (int(matches[-1][0]), float(matches[-1][1])) if matches else (0, 0.0)


def actual_errors(directory: Path) -> list[dict[str, object]]:
    patterns = (
        re.compile(r"\bLINCS WARNING\b"),
        re.compile(r"\bFatal error\b", re.IGNORECASE),
        re.compile(r"\bsegmentation fault\b", re.IGNORECASE),
        re.compile(r"\bNaN\b"),
        re.compile(r"\bcore dumped\b", re.IGNORECASE),
    )
    errors = []
    for path in sorted(directory.glob("*mdrun.stderr.log")) + sorted(directory.glob("prod.log")):
        if not path.is_file():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if any(pattern.search(line) for pattern in patterns):
                errors.append({"file": str(path), "line": number, "text": line[:500]})
    return errors


def gpu_snapshot() -> list[dict[str, object]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,pstate,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        lines = subprocess.check_output(command, text=True, timeout=20).splitlines()
    except Exception as exc:
        return [{"error": repr(exc)}]
    result = []
    for line in lines:
        fields = [field.strip() for field in line.split(",")]
        result.append(
            {
                "index": int(fields[0]),
                "pstate": fields[1],
                "memory_used_mib": int(fields[2]),
                "memory_total_mib": int(fields[3]),
                "utilization_percent": int(fields[4]),
                "temperature_c": int(fields[5]),
                "power_w": float(fields[6]),
            }
        )
    return result


def disk_snapshot(path: Path) -> dict[str, int | str]:
    stat = os.statvfs(path)
    return {
        "path": str(path),
        "total_bytes": stat.f_blocks * stat.f_frsize,
        "free_bytes": stat.f_bavail * stat.f_frsize,
    }


def build_snapshot(
    root: Path,
    manifest: Path,
    production: Path,
    controller_pid_file: Path,
    analysis_pid_file: Path | None,
    analysis_status: Path,
) -> dict[str, object]:
    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8"), delimiter="\t"))
    jobs = []
    elapsed_completed = []
    all_errors = []
    for row in rows:
        directory = production / row["system_id"] / f'seed_{row["md_seed"]}'
        complete_path = directory / "COMPLETE.json"
        failed_path = directory / "FAILED.json"
        stage, step, simulation_ps = "PENDING", 0, 0.0
        if complete_path.is_file():
            stage = "COMPLETE"
            try:
                elapsed_completed.append(float(json.loads(complete_path.read_text())["elapsed_seconds"]))
            except Exception:
                pass
            step, simulation_ps = latest_step(directory / "prod.log")
        elif failed_path.is_file():
            stage = "FAILED"
        elif (directory / "prod.log").is_file():
            stage = "PRODUCTION"
            step, simulation_ps = latest_step(directory / "prod.log")
        elif (directory / "npt.log").is_file():
            stage = "NPT"
            step, simulation_ps = latest_step(directory / "npt.log")
        elif (directory / "nvt.log").is_file():
            stage = "NVT"
            step, simulation_ps = latest_step(directory / "nvt.log")
        errors = actual_errors(directory)
        all_errors.extend(errors)
        prod_log = directory / "prod.log"
        stalled = (
            stage == "PRODUCTION"
            and prod_log.is_file()
            and time.time() - prod_log.stat().st_mtime > 300
            and step < 1_000_000
        )
        completion_valid = None
        if stage == "COMPLETE":
            completion_valid = (
                all((directory / name).is_file() and (directory / name).stat().st_size > 0
                    for name in ("prod.tpr", "prod.xtc", "prod.cpt", "prod.gro", "prod.log"))
                and step >= 1_000_000
                and "Finished mdrun on rank 0"
                in (directory / "prod.log").read_text(encoding="utf-8", errors="replace")
            )
        jobs.append(
            {
                "system_id": row["system_id"],
                "seed": int(row["md_seed"]),
                "gpu": int(row["gpu"]),
                "stage": stage,
                "step": step,
                "simulation_ps": simulation_ps,
                "production_fraction": round(step / 1_000_000, 6) if stage in {"PRODUCTION", "COMPLETE"} else 0,
                "stalled": stalled,
                "completion_valid": completion_valid,
                "error_count": len(errors),
            }
        )
    counts = {state: sum(job["stage"] == state for job in jobs) for state in (
        "COMPLETE", "FAILED", "PRODUCTION", "NPT", "NVT", "PENDING"
    )}
    typical_seconds = sorted(elapsed_completed)[len(elapsed_completed) // 2] if elapsed_completed else 600.0
    remaining_by_gpu: dict[int, float] = {}
    for job in jobs:
        if job["stage"] == "COMPLETE":
            remaining = 0.0
        elif job["stage"] == "PRODUCTION":
            remaining = typical_seconds * (1.0 - float(job["production_fraction"]))
        elif job["stage"] in {"NPT", "NVT"}:
            remaining = typical_seconds
        elif job["stage"] == "PENDING":
            remaining = typical_seconds
        else:
            remaining = 0.0
        remaining_by_gpu[int(job["gpu"])] = remaining_by_gpu.get(int(job["gpu"]), 0.0) + remaining
    eta_seconds = max(remaining_by_gpu.values(), default=0.0)
    analysis_state = "PENDING"
    if analysis_status.is_file():
        try:
            analysis_state = str(json.loads(analysis_status.read_text()).get("state", "UNKNOWN"))
        except Exception:
            analysis_state = "INVALID_JSON"
    controller = pid_state(controller_pid_file)
    stalled_jobs = [job for job in jobs if job["stalled"]]
    invalid_complete_jobs = [
        job for job in jobs if job["stage"] == "COMPLETE" and not job["completion_valid"]
    ]
    if (
        counts["FAILED"]
        or all_errors
        or stalled_jobs
        or invalid_complete_jobs
        or (counts["COMPLETE"] < len(jobs) and not controller["alive"])
    ):
        overall = "ALERT"
    elif counts["COMPLETE"] == len(jobs):
        overall = "ANALYSIS_COMPLETE" if analysis_state.endswith("ANALYSIS_COMPLETE") else "ANALYSIS_PENDING"
    else:
        overall = "MD_RUNNING"
    return {
        "schema_version": 1,
        "updated_at": utc_now(),
        "state": overall,
        "root": str(root),
        "counts": counts,
        "jobs": jobs,
        "actual_error_count": len(all_errors),
        "actual_errors": all_errors[-20:],
        "stalled_jobs": stalled_jobs,
        "invalid_complete_jobs": invalid_complete_jobs,
        "controller": controller,
        "analysis_watcher": pid_state(analysis_pid_file) if analysis_pid_file else None,
        "analysis_state": analysis_state,
        "eta_seconds_estimate": round(eta_seconds),
        "eta_minutes_estimate": round(eta_seconds / 60, 1),
        "gpu": gpu_snapshot(),
        "disk": [disk_snapshot(Path("/data")), disk_snapshot(Path("/data1"))],
    }


parser = argparse.ArgumentParser()
parser.add_argument(
    "--root",
    default="/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724",
)
parser.add_argument("--interval", type=int, default=60)
parser.add_argument("--once", action="store_true")
parser.add_argument("--manifest")
parser.add_argument("--production-dir")
parser.add_argument("--controller-pid-file")
parser.add_argument("--analysis-pid-file")
parser.add_argument("--analysis-status-file")
parser.add_argument("--output-status-file")
parser.add_argument("--lock-file")
parser.add_argument("--log-file")
args = parser.parse_args()
root = Path(args.root)
status_dir = root / "status"
status_dir.mkdir(parents=True, exist_ok=True)
manifest = Path(args.manifest) if args.manifest else root / "manifests/MD_PRODUCTION_MANIFEST.tsv"
production = Path(args.production_dir) if args.production_dir else root / "md/production"
controller_pid_file = Path(args.controller_pid_file) if args.controller_pid_file else status_dir / "MD_PRODUCTION_CONTROLLER.pid"
analysis_pid_file = Path(args.analysis_pid_file) if args.analysis_pid_file else status_dir / "MD_ANALYSIS_WATCHER.pid"
analysis_status = Path(args.analysis_status_file) if args.analysis_status_file else status_dir / "MD_ANALYSIS_STATUS.json"
output_status = Path(args.output_status_file) if args.output_status_file else status_dir / "MD_LIVE_STATUS.json"
lock_file = Path(args.lock_file) if args.lock_file else status_dir / "MD_LIVE_MONITOR.lock"
log_file = Path(args.log_file) if args.log_file else root / "logs/md_live_monitor.log"
lock_handle = lock_file.open("w")
try:
    fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("another MD live monitor owns the lock")

last_summary = None
while True:
    snapshot = build_snapshot(
        root, manifest, production, controller_pid_file, analysis_pid_file, analysis_status
    )
    atomic_json(output_status, snapshot)
    summary = (
        snapshot["state"],
        tuple(snapshot["counts"].items()),
        snapshot["actual_error_count"],
        len(snapshot["stalled_jobs"]),
    )
    if summary != last_summary:
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"updated_at": snapshot["updated_at"], "summary": summary}) + "\n")
        last_summary = summary
    if args.once or snapshot["state"] in {"ANALYSIS_COMPLETE", "ALERT"}:
        break
    time.sleep(max(10, args.interval))
