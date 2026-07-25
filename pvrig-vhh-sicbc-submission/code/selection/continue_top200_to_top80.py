#!/usr/bin/env python3
"""Wait for a frozen Top200, then execute static review and freeze Top80."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run(command: list[str], log_prefix: Path) -> None:
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    with (
        log_prefix.with_suffix(".stdout.log").open("w", encoding="utf-8") as stdout,
        log_prefix.with_suffix(".stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        result = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed rc={result.returncode}; inspect {log_prefix}.*.log"
        )


def top200_ready(root: Path) -> bool:
    tsv = root / "run" / "top200" / "top200_pre_static.tsv"
    receipt_path = root / "run" / "top200" / "TOP200_RECEIPT.json"
    if not tsv.is_file() or not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        receipt.get("status") == "PASS_TOP200_FROZEN"
        and receipt.get("count") == 200
        and receipt.get("output_hashes", {}).get(tsv.name) == sha256_file(tsv)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.workers < 1 or args.workers > 4:
        parser.error("workers must be 1..4 under the frozen resource contract")
    status_path = root / "run" / "static_controller" / "STATUS.json"
    lock_path = root / "run" / "static_controller" / "controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another Top200->Top80 controller owns the lock")
    top80_receipt = root / "run" / "top80" / "TOP80_COMPLETE.json"
    if top80_receipt.is_file():
        write_json(
            status_path,
            {
                "schema_version": "pvrig.top200_to_top80.controller.v1",
                "state": "TOP80_ALREADY_COMPLETE",
                "updated_at": now(),
                "pid": os.getpid(),
            },
        )
        return 0
    while not top200_ready(root):
        write_json(
            status_path,
            {
                "schema_version": "pvrig.top200_to_top80.controller.v1",
                "state": "WAITING_FOR_TOP200",
                "updated_at": now(),
                "pid": os.getpid(),
                "workers": args.workers,
            },
        )
        time.sleep(args.interval)
    scripts = root
    top200 = root / "run" / "top200" / "top200_pre_static.tsv"
    old_jobs = root / "run" / "docking_aggregate" / "OLD_PRIORITY_JOB_RESULTS_25000.tsv"
    c2_jobs = root / "run" / "docking_aggregate" / "C2_JOB_RESULTS_41760.tsv"
    static_root = root / "run" / "static_review"
    write_json(
        status_path,
        {
            "schema_version": "pvrig.top200_to_top80.controller.v1",
            "state": "PREPARING_STATIC_PANEL",
            "updated_at": now(),
            "pid": os.getpid(),
        },
    )
    if not (static_root / "STATIC_PREPARE_COMPLETE.json").is_file():
        run(
            [
                sys.executable,
                str(scripts / "prepare_top200_static.py"),
                "--top200", str(top200),
                "--old-jobs", str(old_jobs),
                "--c2-jobs", str(c2_jobs),
                "--out", str(static_root),
            ],
            root / "logs" / "prepare_top200_static",
        )
    write_json(
        status_path,
        {
            "schema_version": "pvrig.top200_to_top80.controller.v1",
            "state": "RUNNING_STATIC_PANEL",
            "updated_at": now(),
            "pid": os.getpid(),
            "workers": args.workers,
        },
    )
    if not (static_root / "STATIC_COMPLETE.json").is_file():
        run(
            [
                sys.executable,
                str(scripts / "run_top200_static.py"),
                "--manifest", str(static_root / "STATIC_JOB_MANIFEST.tsv"),
                "--out", str(static_root),
                "--workers", str(args.workers),
            ],
            root / "logs" / "run_top200_static",
        )
    write_json(
        status_path,
        {
            "schema_version": "pvrig.top200_to_top80.controller.v1",
            "state": "SELECTING_TOP80",
            "updated_at": now(),
            "pid": os.getpid(),
        },
    )
    run(
        [
            sys.executable,
            str(scripts / "select_top80.py"),
            "--top200", str(top200),
            "--static-metrics", str(static_root / "STATIC_POSE_METRICS.tsv"),
            "--static-receipt", str(static_root / "STATIC_COMPLETE.json"),
            "--out", str(root / "run" / "top80"),
        ],
        root / "logs" / "select_top80",
    )
    receipt = json.loads(top80_receipt.read_text(encoding="utf-8"))
    if receipt.get("state") != "TOP80_COMPLETE" or receipt.get("count") != 80:
        raise RuntimeError("Top80 receipt failed final validation")
    write_json(
        status_path,
        {
            "schema_version": "pvrig.top200_to_top80.controller.v1",
            "state": "TOP80_COMPLETE",
            "updated_at": now(),
            "pid": os.getpid(),
            "top80_receipt_sha256": sha256_file(top80_receipt),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
