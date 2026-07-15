#!/usr/bin/env python3
"""Run the resumable load-aware queue until the selected docking jobs finish."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from common import project_root, read_tsv, write_json
from run_job import read_state, write_state


TERMINAL = {"SUCCESS", "FAILED_MAX_ATTEMPTS"}
ACTIVE = {"QUEUED", "RUNNING"}


def root() -> Path:
    return Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def load_limit(load1: float, max_parallel: int = 4, cpu_count: int = 64) -> int:
    if max_parallel < 1 or cpu_count < 1:
        raise ValueError("max_parallel and cpu_count must be positive")
    if load1 >= cpu_count - 2:
        return 0
    if load1 >= cpu_count * 0.875:
        if max_parallel > 4:
            return max(1, (max_parallel + 1) // 2)
        return max(1, (max_parallel + 3) // 4)
    if load1 >= cpu_count * 0.75:
        if max_parallel > 4:
            return max(1, (max_parallel * 3 + 3) // 4)
        return max(1, (max_parallel + 1) // 2)
    return max_parallel


def pid_alive(value: object) -> bool:
    try:
        os.kill(int(value), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def pid_matches_job(value: object, job_id: str) -> bool:
    if not pid_alive(value):
        return False
    try:
        cmdline = (Path("/proc") / str(int(value)) / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
    except (OSError, TypeError, ValueError):
        return False
    return "run_job.py" in cmdline and job_id in cmdline


def selected_rows(job_ids: set[str], entity_ids: set[str]) -> list[dict[str, str]]:
    manifest = root() / "manifests/docking_jobs.tsv"
    if not manifest.is_file():
        raise RuntimeError(f"job manifest missing: {manifest}")
    rows = sorted(read_tsv(manifest), key=lambda row: int(row["priority"]))
    if job_ids:
        rows = [row for row in rows if row["job_id"] in job_ids]
        missing = job_ids - {row["job_id"] for row in rows}
        if missing:
            raise RuntimeError(f"unknown requested job IDs: {sorted(missing)}")
    if entity_ids:
        rows = [row for row in rows if row["entity_id"] in entity_ids]
        missing = entity_ids - {row["entity_id"] for row in rows}
        if missing:
            raise RuntimeError(f"unknown requested entity IDs: {sorted(missing)}")
    if not rows:
        raise RuntimeError("job selection is empty")
    return rows


def effective_status(row: dict[str, str], max_attempts: int) -> str:
    state = read_state(row["job_id"])
    status = str(state.get("status") or "PENDING")
    attempts = int(state.get("attempts", 0) or 0)
    if status in ACTIVE and not pid_matches_job(state.get("pid"), row["job_id"]):
        write_state(
            row["job_id"],
            {
                "status": "FAILED",
                "stage": state.get("stage", "controller_recovery"),
                "attempts": attempts,
                "error": "stale active state recovered by controller",
            },
        )
        status = "FAILED"
    if status == "FAILED" and attempts >= max_attempts:
        write_state(row["job_id"], {**state, "status": "FAILED_MAX_ATTEMPTS", "attempts": attempts})
        status = "FAILED_MAX_ATTEMPTS"
    return status


def launch(row: dict[str, str], max_attempts: int, dry_run: bool) -> int | None:
    if dry_run:
        return None
    log_dir = root() / "logs/jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "nice",
        "-n",
        "15",
        sys.executable,
        str(root() / "scripts/run_job.py"),
        row["job_id"],
        "--max-attempts",
        str(max_attempts),
    ]
    with (log_dir / f"{row['job_id']}.controller.log").open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=root(),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PVRIG_PROJECT_ROOT": str(root())},
        )
    return process.pid


def snapshot(rows: list[dict[str, str]], max_attempts: int) -> tuple[dict[str, str], Counter[str]]:
    statuses = {row["job_id"]: effective_status(row, max_attempts) for row in rows}
    return statuses, Counter(statuses.values())


def scheduling_pass(
    rows: list[dict[str, str]],
    max_attempts: int,
    dry_run: bool = False,
    forced_load: float | None = None,
    max_parallel: int = 4,
    cpu_count: int | None = None,
) -> dict[str, object]:
    statuses, counts = snapshot(rows, max_attempts)
    load1 = os.getloadavg()[0] if forced_load is None else forced_load
    detected_cpu_count = cpu_count or os.cpu_count() or 64
    parallel_limit = load_limit(load1, max_parallel=max_parallel, cpu_count=detected_cpu_count)
    active_count = sum(status in ACTIVE for status in statuses.values())
    slots = max(0, parallel_limit - active_count)
    launched: list[dict[str, object]] = []
    for row in rows:
        if len(launched) >= slots:
            break
        status = statuses[row["job_id"]]
        if status in TERMINAL or status in ACTIVE:
            continue
        pid = launch(row, max_attempts, dry_run)
        launched.append({"job_id": row["job_id"], "pid": pid})
    payload = {
        "status": "RUNNING" if counts.get("SUCCESS", 0) + counts.get("FAILED_MAX_ATTEMPTS", 0) < len(rows) else "COMPLETE",
        "controller_pid": os.getpid(),
        "selected_job_count": len(rows),
        "load1": load1,
        "cpu_count": detected_cpu_count,
        "max_parallel": max_parallel,
        "parallel_limit": parallel_limit,
        "active_before": active_count,
        "available_slots": slots,
        "counts_before": dict(sorted(counts.items())),
        "launched": launched,
        "dry_run": dry_run,
    }
    write_json(root() / "status/controller.json", payload)
    return payload


def run_loop(args: argparse.Namespace) -> int:
    requested_jobs = set(args.job_id)
    if args.job_list:
        job_list_path = Path(args.job_list)
        if not job_list_path.is_absolute():
            job_list_path = root() / job_list_path
        requested_jobs.update(row["job_id"] for row in read_tsv(job_list_path))
    rows = selected_rows(requested_jobs, set(args.entity_id))
    while True:
        payload = scheduling_pass(
            rows,
            args.max_attempts,
            args.dry_run,
            args.load1,
            max_parallel=args.max_parallel,
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
        if args.once or args.dry_run:
            return 0
        statuses, counts = snapshot(rows, args.max_attempts)
        if all(status in TERMINAL for status in statuses.values()):
            final = {
                **payload,
                "status": "COMPLETE" if counts.get("FAILED_MAX_ATTEMPTS", 0) == 0 else "COMPLETE_WITH_FAILURES",
                "counts": dict(sorted(counts.items())),
            }
            write_json(root() / "status/controller.json", final)
            return 0 if final["status"] == "COMPLETE" else 1
        time.sleep(args.poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", action="append", default=[], help="Limit queue to one or more exact job IDs")
    parser.add_argument("--job-list", help="TSV containing a job_id column, e.g. manifests/smoke_jobs.tsv")
    parser.add_argument("--entity-id", action="append", default=[], help="Limit queue to complete 2x3 matrix for entity")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--max-parallel", type=int, default=int(os.environ.get("PVRIG_MAX_PARALLEL", "4")))
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--load1", type=float, help="Testing override; do not use for production")
    args = parser.parse_args(argv)
    if args.max_parallel < 1:
        parser.error("--max-parallel must be positive")
    # Jobs are tracked through atomic state files; auto-reap children to avoid one zombie per completed job.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    lock_path = root() / "status/controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ERROR: another controller holds status/controller.lock", file=sys.stderr)
            return 75
        try:
            return run_loop(args)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
