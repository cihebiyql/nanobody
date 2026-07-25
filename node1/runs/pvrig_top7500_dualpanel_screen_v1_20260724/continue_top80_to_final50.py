#!/usr/bin/env python3
"""Execute MD20, final50 selection, final QC and audited freeze after Top80."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GPUS = {0, 1, 2, 4}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run(command: list[str], log_prefix: Path, attempts: int = 1) -> None:
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        with (
            log_prefix.with_suffix(".stdout.log").open("a", encoding="utf-8") as stdout,
            log_prefix.with_suffix(".stderr.log").open("a", encoding="utf-8") as stderr,
        ):
            stdout.write(f"[{now()}] ATTEMPT {attempt} COMMAND {json.dumps(command)}\n")
            stdout.flush()
            result = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
        if result.returncode == 0:
            return
        if attempt < attempts:
            time.sleep(60)
    raise RuntimeError(
        f"command failed after {attempts} attempts; inspect {log_prefix}.*.log"
    )


def top80_ready(root: Path) -> bool:
    tsv = root / "run" / "top80" / "top80_post_static.tsv"
    receipt_path = root / "run" / "top80" / "TOP80_COMPLETE.json"
    if not tsv.is_file() or not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return receipt.get("state") == "TOP80_COMPLETE" and receipt.get("count") == 80


def gpu_capacity() -> tuple[bool, list[dict[str, int]]]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,utilization.gpu,memory.used",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        return False, []
    rows = []
    for line in result.stdout.splitlines():
        index, utilization, memory = [int(part.strip()) for part in line.split(",")]
        if index in GPUS:
            rows.append(
                {"index": index, "utilization": utilization, "memory_mib": memory}
            )
    ready = (
        {row["index"] for row in rows} == GPUS
        and all(row["utilization"] < 50 and row["memory_mib"] < 2000 for row in rows)
    )
    return ready, rows


def main() -> int:
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(range(min(32, os.cpu_count() or 1))))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    root = args.root.resolve()
    status_path = root / "run" / "final_controller" / "STATUS.json"
    lock_path = root / "run" / "final_controller" / "controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another Top80->final50 controller owns the lock")
    final_receipt = root / "run" / "final50" / "FINAL50_COMPLETE.json"
    if final_receipt.is_file():
        write_json(
            status_path,
            {"state": "FINAL50_ALREADY_COMPLETE", "updated_at": now(), "pid": os.getpid()},
        )
        return 0
    while not top80_ready(root):
        write_json(
            status_path,
            {
                "schema_version": "pvrig.top80_to_final50.controller.v1",
                "state": "WAITING_FOR_TOP80",
                "updated_at": now(),
                "pid": os.getpid(),
            },
        )
        time.sleep(max(30, args.interval))
    mdroot = root / "run" / "md"
    logs = root / "logs"
    if not (mdroot / "MD20_PREPARE_COMPLETE.json").is_file():
        write_json(
            status_path,
            {"state": "PREPARING_MD20", "updated_at": now(), "pid": os.getpid()},
        )
        run(
            [
                sys.executable,
                str(root / "prepare_md20.py"),
                "--top80", str(root / "run/top80/top80_post_static.tsv"),
                "--top80-receipt", str(root / "run/top80/TOP80_COMPLETE.json"),
                "--static-manifest", str(root / "run/static_review/STATIC_JOB_MANIFEST.tsv"),
                "--out", str(mdroot),
            ],
            logs / "prepare_md20",
        )
    if not (mdroot / "MD_TOPOLOGY_STATUS.json").is_file() or json.loads(
        (mdroot / "MD_TOPOLOGY_STATUS.json").read_text(encoding="utf-8")
    ).get("state") != "COMPLETE":
        write_json(
            status_path,
            {
                "state": "RUNNING_MD20_TOPOLOGY",
                "updated_at": now(),
                "pid": os.getpid(),
                "cpu_limit": 24,
                "gpu_limit": 0,
            },
        )
        run(
            ["bash", str(root / "run_md20_topology.sh")],
            logs / "md20_topology",
            attempts=2,
        )
    while True:
        ready, gpu_rows = gpu_capacity()
        if ready:
            break
        write_json(
            status_path,
            {
                "state": "WAITING_FOR_GPU_CAPACITY",
                "updated_at": now(),
                "pid": os.getpid(),
                "requested_gpus": sorted(GPUS),
                "observed": gpu_rows,
            },
        )
        time.sleep(300)
    production_status = mdroot / "MD_PRODUCTION_STATUS.json"
    if not production_status.is_file() or json.loads(
        production_status.read_text(encoding="utf-8")
    ).get("state") != "COMPLETE":
        write_json(
            status_path,
            {
                "state": "RUNNING_MD20_PRODUCTION",
                "updated_at": now(),
                "pid": os.getpid(),
                "cpu_limit": 32,
                "gpu_limit": 4,
                "gpus": sorted(GPUS),
                "trajectories": 60,
                "production_ns_each": 2,
            },
        )
        run(
            ["bash", str(root / "run_md20_production.sh")],
            logs / "md20_production",
            attempts=3,
        )
    md_analysis_receipt = mdroot / "reports" / "MD20_ANALYSIS_COMPLETE.json"
    if not md_analysis_receipt.is_file():
        write_json(
            status_path,
            {"state": "ANALYZING_MD20", "updated_at": now(), "pid": os.getpid()},
        )
        run(
            [sys.executable, str(root / "analyze_md20.py"), "--root", str(root)],
            logs / "analyze_md20",
        )
    final_root = root / "run" / "final50"
    preaudit = final_root / "FINAL50_PREAUDIT.json"
    if not preaudit.is_file():
        write_json(
            status_path,
            {"state": "SELECTING_FINAL50", "updated_at": now(), "pid": os.getpid()},
        )
        run(
            [
                sys.executable,
                str(root / "select_final50.py"),
                "--top80", str(root / "run/top80/top80_post_static.tsv"),
                "--top80-receipt", str(root / "run/top80/TOP80_COMPLETE.json"),
                "--md-manifest", str(mdroot / "md_manifest.tsv"),
                "--md-summary", str(mdroot / "reports/md_candidate_summary.tsv"),
                "--out", str(final_root),
            ],
            logs / "select_final50",
        )
    final_qc_root = final_root / "final_qc"
    final_qc = final_qc_root / "FINAL50_QC_RESULTS.tsv"
    if not final_qc.is_file():
        write_json(
            status_path,
            {
                "state": "RUNNING_FINAL50_QC",
                "updated_at": now(),
                "pid": os.getpid(),
                "cpu_limit": 24,
            },
        )
        qc_out = final_qc_root / "qc_out"
        run(
            [
                "nice", "-n", "5",
                "/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc",
                str(final_root / "final50_ranked.fasta"),
                "-o", str(qc_out),
                "--prefix", "final50",
                "--workers", "24",
                "--muscle-bin", str(root / "muscle_single_thread.sh"),
                "--vhh-screen-bin", str(root / "vhh_screen_parallel_tnp.sh"),
                "--tnp-ncores", "1",
                "--identity-cache-size", "500000",
                "--gate-policy", "blocker_calibrated",
                "--docking-summary",
                str(root / "run/candidate_aggregate/candidate_docking_summary.tsv"),
                "--top-n", "50",
                "--reserve-n", "0",
                "--local-positive-cdr-csv",
                "/data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv",
            ],
            logs / "final50_qc",
        )
        source = qc_out / "portfolio_ranked.tsv"
        if not source.is_file() or row_count(source) != 50:
            raise RuntimeError("final QC did not produce exactly 50 portfolio rows")
        final_qc_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, final_qc)
    write_json(
        status_path,
        {"state": "AUDITING_FINAL50", "updated_at": now(), "pid": os.getpid()},
    )
    run(
        [
            sys.executable,
            str(root / "audit_final50.py"),
            "--final-root", str(final_root),
            "--final-qc", str(final_qc),
            "--top80-receipt", str(root / "run/top80/TOP80_COMPLETE.json"),
            "--md-receipt", str(md_analysis_receipt),
        ],
        logs / "audit_final50",
    )
    receipt = json.loads(final_receipt.read_text(encoding="utf-8"))
    if receipt.get("state") != "FINAL50_COMPLETE" or receipt.get("count") != 50:
        raise RuntimeError("final audited receipt is invalid")
    write_json(
        status_path,
        {
            "schema_version": "pvrig.top80_to_final50.controller.v1",
            "state": "FINAL50_COMPLETE",
            "updated_at": now(),
            "pid": os.getpid(),
            "receipt_sha256": sha256_file(final_receipt),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
