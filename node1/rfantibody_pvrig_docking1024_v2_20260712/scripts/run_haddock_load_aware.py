#!/usr/bin/env python3
"""Central load-aware HADDOCK3 queue for resumable candidate docking."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load1() -> float:
    return os.getloadavg()[0]


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def pid_alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def terminal_status(
    state: dict[str, object], retry_failed: bool = False, max_attempts: int = 1
) -> str | None:
    status = str(state.get("status") or "")
    if status == "failed" and retry_failed and int(state.get("attempt", 0) or 0) < max_attempts:
        return None
    if status in {"success", "failed", "missing"}:
        return status
    if status == "running" and pid_alive(state.get("pid")):
        return "running"
    return None


def completed_haddock_model(run_root: Path, cid: str) -> bool:
    run_dir = run_root / "docking" / "haddock" / cid / f"run_{cid}_pvrig_8x6b_full_interface"
    return any(run_dir.rglob("cluster_*_model_*.pdb")) or any(run_dir.rglob("cluster_*_model_*.pdb.gz"))


def active_children(children: dict[str, subprocess.Popen[bytes]]) -> dict[str, subprocess.Popen[bytes]]:
    return {cid: proc for cid, proc in children.items() if proc.poll() is None}


def allowed_parallel(current_load: float, max_load1: float, cores_per_job: int, max_parallel: int) -> int:
    if current_load >= max_load1:
        return 0
    capacity = int((max_load1 - current_load) // max(cores_per_job, 1))
    return max(0, min(max_parallel, capacity))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--max-load1", type=float, default=56.0, help="wait when 1-minute load is at/above this; node1 currently near 60")
    parser.add_argument("--cores-per-job", type=int, default=4)
    parser.add_argument("--max-parallel", type=int, default=8)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true", help="perform one scheduling pass, useful for tests")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    docking_root = run_root / "docking"
    manifest = args.manifest or docking_root / "manifests" / "docking_candidates.tsv"
    rows = read_manifest(manifest)
    state_dir = docking_root / "state" / "haddock"
    controller_state = docking_root / "state" / "haddock_controller.json"
    script = run_root / "scripts" / "run_haddock_one.sh"
    children: dict[str, subprocess.Popen[bytes]] = {}
    launched_once = False

    while True:
        children = active_children(children)
        current = load1()
        slots = max(0, allowed_parallel(current, args.max_load1, args.cores_per_job, args.max_parallel) - len(children))
        summary = {
            "updated_at": utc_now(),
            "load1": current,
            "max_load1": args.max_load1,
            "cores_per_job": args.cores_per_job,
            "max_parallel": args.max_parallel,
            "active_jobs": sorted(children),
            "available_slots": slots,
            "dry_run": args.dry_run,
        }
        write_json_atomic(controller_state, summary)

        if slots <= 0:
            print(f"LOAD_GATE_WAIT load1={current:.2f} threshold={args.max_load1} active={len(children)} time={utc_now()}", flush=True)
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
            continue

        launched_this_pass = 0
        for row in rows:
            if launched_this_pass >= slots:
                break
            cid = row["candidate_id"]
            state = read_json(state_dir / f"{cid}.json")
            status = terminal_status(state, args.retry_failed, args.max_attempts)
            if status in {"success", "failed", "missing", "running"}:
                continue
            if completed_haddock_model(run_root, cid):
                write_json_atomic(state_dir / f"{cid}.json", {"candidate_id": cid, "stage": "haddock", "status": "success", "message": "existing cluster model found", "updated_at": utc_now()})
                continue
            nbb2_state = read_json(docking_root / "state" / "nbb2" / f"{cid}.json")
            if nbb2_state.get("status") != "success" or not (docking_root / "haddock" / cid / "data" / f"{cid}_vhh_chainA.pdb").is_file():
                continue
            command = ["bash", str(script), cid]
            print(f"HADDOCK_QUEUE_START cid={cid} load1={current:.2f} time={utc_now()}", flush=True)
            if args.dry_run:
                write_json_atomic(state_dir / f"{cid}.json", {"candidate_id": cid, "stage": "haddock", "status": "dry_run", "command": command, "updated_at": utc_now()})
            else:
                children[cid] = subprocess.Popen(command, cwd=str(run_root), env={**os.environ, "RUN_ROOT": str(run_root)})
            launched_this_pass += 1
            launched_once = True

        all_states = [
            terminal_status(
                read_json(state_dir / f"{row['candidate_id']}.json"),
                args.retry_failed,
                args.max_attempts,
            )
            for row in rows
        ]
        if all(status in {"success", "failed", "missing"} for status in all_states) and not children:
            return 0
        if args.once or (args.dry_run and launched_once):
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
