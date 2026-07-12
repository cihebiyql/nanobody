#!/usr/bin/env python3
"""Load-aware, resumable dual-baseline scoring queue for V2 HADDOCK models."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def csv_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def selected_count(root: Path, candidate: str) -> int:
    selected = root / "docking/haddock" / candidate / f"run_{candidate}_pvrig_8x6b_full_interface/6_seletopclusts"
    return len(list(selected.glob("cluster_*_model_*.pdb"))) + len(list(selected.glob("cluster_*_model_*.pdb.gz")))


def complete(root: Path, candidate: str, expected: int) -> bool:
    report = root / "docking/postprocessed" / candidate / "reports" / f"{candidate}_8x6b_9e6y_consensus.csv"
    return expected > 0 and csv_rows(report) == expected


def allowed_parallel(current_load: float, max_load: float, cores_per_job: int, limit: int) -> int:
    if current_load >= max_load:
        return 0
    return max(0, min(limit, int((max_load - current_load) // max(cores_per_job, 1))))


def pid_alive(value: object) -> bool:
    try:
        os.kill(int(value), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--python", default="/data/qlyu/anaconda3/envs/boltz/bin/python")
    parser.add_argument("--max-load1", type=float, default=56.0)
    parser.add_argument("--cores-per-job", type=int, default=2)
    parser.add_argument("--max-parallel", type=int, default=8)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()

    root = args.run_root.resolve()
    manifest = args.manifest or root / "docking/manifests/docking_candidates.tsv"
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    state_dir = root / "docking/state/postprocess"
    log_dir = root / "docking/logs/postprocess"
    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    processor = root / "scripts/postprocess_candidate_dual_baseline.py"
    children: dict[str, tuple[subprocess.Popen[bytes], object, int]] = {}

    while True:
        for candidate, (process, log_handle, attempt) in list(children.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            log_handle.close()
            expected = min(4, selected_count(root, candidate))
            status = "success" if return_code == 0 and complete(root, candidate, expected) else "failed"
            write_json(
                state_dir / f"{candidate}.json",
                {
                    "candidate_id": candidate,
                    "stage": "dual_baseline_postprocess",
                    "status": status,
                    "attempt": attempt,
                    "return_code": return_code,
                    "expected_models": expected,
                    "updated_at": now(),
                },
            )
            del children[candidate]

        current_load = os.getloadavg()[0]
        capacity = allowed_parallel(current_load, args.max_load1, args.cores_per_job, args.max_parallel)
        slots = max(0, capacity - len(children))
        pending = 0
        for row in rows:
            candidate = row["candidate_id"]
            if candidate in children:
                continue
            expected = min(4, selected_count(root, candidate))
            state_path = state_dir / f"{candidate}.json"
            state = read_json(state_path)
            if complete(root, candidate, expected):
                if state.get("status") != "success":
                    write_json(state_path, {"candidate_id": candidate, "stage": "dual_baseline_postprocess", "status": "success", "attempt": state.get("attempt", 0), "expected_models": expected, "updated_at": now()})
                continue
            if expected == 0:
                write_json(state_path, {"candidate_id": candidate, "stage": "dual_baseline_postprocess", "status": "missing", "attempt": state.get("attempt", 0), "message": "no selected HADDOCK model", "updated_at": now()})
                continue
            if state.get("status") == "running" and pid_alive(state.get("pid")):
                pending += 1
                continue
            attempt = int(state.get("attempt", 0) or 0)
            if state.get("status") == "failed" and attempt >= args.max_attempts:
                continue
            pending += 1
            if slots <= 0:
                continue
            attempt += 1
            command = [
                args.python,
                str(processor),
                "--run-root", str(root),
                "--candidate-id", candidate,
                "--cdr1", f"{row['cdr1_start_1based']}-{row['cdr1_end_1based']}",
                "--cdr2", f"{row['cdr2_start_1based']}-{row['cdr2_end_1based']}",
                "--cdr3", f"{row['cdr3_start_1based']}-{row['cdr3_end_1based']}",
                "--top-n", "4",
            ]
            log_handle = (log_dir / f"{candidate}.attempt_{attempt}.log").open("wb")
            process = subprocess.Popen(command, cwd=root, stdout=log_handle, stderr=subprocess.STDOUT)
            children[candidate] = (process, log_handle, attempt)
            write_json(state_path, {"candidate_id": candidate, "stage": "dual_baseline_postprocess", "status": "running", "attempt": attempt, "pid": process.pid, "updated_at": now()})
            slots -= 1

        counts: dict[str, int] = {}
        for row in rows:
            status = str(read_json(state_dir / f"{row['candidate_id']}.json").get("status", "pending"))
            counts[status] = counts.get(status, 0) + 1
        write_json(
            root / "docking/state/postprocess_controller.json",
            {
                "updated_at": now(),
                "load1": current_load,
                "max_load1": args.max_load1,
                "active": sorted(children),
                "status_counts": counts,
            },
        )
        if not children and pending == 0:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
