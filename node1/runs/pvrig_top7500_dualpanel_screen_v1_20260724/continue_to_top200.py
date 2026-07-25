#!/usr/bin/env python3
"""Wait for docking post-processing, then build evidence, full QC and Top200."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_logged(command: list[str], stdout_path: Path, stderr_path: Path) -> None:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open(
        "a", encoding="utf-8"
    ) as stderr:
        stdout.write(f"[{now_iso()}] COMMAND {json.dumps(command)}\n")
        stdout.flush()
        process = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"command failed with exit {process.returncode}: {command}")


def validate_prerequisites(root: Path) -> dict[str, Any] | None:
    fast = root / "run/union13720_cascade/fast_merged.tsv"
    c2 = root / "run/docking_aggregate/C2_JOB_RESULTS_41760.tsv"
    old = root / "run/docking_aggregate/OLD_PRIORITY_JOB_RESULTS_25000.tsv"
    c2_receipt_path = c2.with_suffix(c2.suffix + ".receipt.json")
    old_receipt_path = old.with_suffix(old.suffix + ".receipt.json")
    required = [fast, c2, old, c2_receipt_path, old_receipt_path]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        return None
    counts = {"fast": row_count(fast), "c2": row_count(c2), "old": row_count(old)}
    if counts != {"fast": 13720, "c2": 41760, "old": 25000}:
        raise ValueError(f"prerequisite row-count mismatch: {counts}")
    c2_receipt = read_json(c2_receipt_path)
    old_receipt = read_json(old_receipt_path)
    def validate_terminal_counts(
        label: str,
        counts: dict[str, Any],
        expected_success: int,
        expected_technical: int,
    ) -> None:
        normalized = {str(key).upper(): int(value) for key, value in counts.items()}
        success = normalized.get("SUCCESS", 0)
        technical = sum(
            value for state, value in normalized.items() if state != "SUCCESS"
        )
        if success != expected_success or technical != expected_technical:
            raise ValueError(
                f"{label} state-count mismatch: {normalized}; expected "
                f"success={expected_success}, technical_terminal={expected_technical}"
            )

    validate_terminal_counts(
        "C2", c2_receipt.get("state_counts", {}), 41735, 25
    )
    validate_terminal_counts(
        "old", old_receipt.get("state_counts", {}), 24985, 15
    )
    return {
        "counts": counts,
        "hashes": {str(path): sha256_file(path) for path in required},
        "validated_at": now_iso(),
    }


def main() -> int:
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(range(min(32, os.cpu_count() or 1))))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    root = args.root.resolve()
    logs = root / "logs"
    controller_status = root / "run/controller/STATUS.json"
    lock_path = root / "run/controller/controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another Top7500 continuation controller is active")

        while True:
            prerequisites = validate_prerequisites(root)
            if prerequisites is not None:
                break
            write_json(
                controller_status,
                {
                    "schema_version": "pvrig.top7500.continue_to_top200.v1",
                    "state": "WAITING_FOR_DOCKING_PREREQUISITES",
                    "updated_at": now_iso(),
                },
            )
            time.sleep(max(30, args.interval))

        write_json(
            controller_status,
            {
                "schema_version": "pvrig.top7500.continue_to_top200.v1",
                "state": "BUILDING_CANDIDATE_EVIDENCE",
                "updated_at": now_iso(),
                "prerequisites": prerequisites,
            },
        )
        python = "/data/qlyu/software/envs/vhh-eval/bin/python"
        aggregate_out = root / "run/candidate_aggregate"
        evidence_receipt = aggregate_out / "CANDIDATE_EVIDENCE_RECEIPT.json"
        if not evidence_receipt.is_file():
            run_logged(
                [
                    python,
                    str(root / "build_candidate_evidence.py"),
                    "--membership",
                    str(root / "inputs/TOP7500_UNION_13720_MEMBERSHIP.tsv"),
                    "--fast",
                    str(root / "run/union13720_cascade/fast_merged.tsv"),
                    "--old-jobs",
                    str(root / "run/docking_aggregate/OLD_PRIORITY_JOB_RESULTS_25000.tsv"),
                    "--c2-jobs",
                    str(root / "run/docking_aggregate/C2_JOB_RESULTS_41760.tsv"),
                    "--multimetric",
                    str(root / "inputs/fixed_pose_top150k_multimetric.tsv.gz"),
                    "--surrogate",
                    str(root / "inputs/surrogate_high_support_snapshot.tsv"),
                    "--competition-qc-module",
                    "/data/qlyu/software/vhh_eval_tools/competition_qc/vhh_competition_qc.py",
                    "--out",
                    str(aggregate_out),
                    "--full-qc-limit",
                    "2000",
                ],
                logs / "candidate_evidence.stdout.log",
                logs / "candidate_evidence.stderr.log",
            )
        evidence_receipt_payload = read_json(evidence_receipt)
        if not evidence_receipt_payload.get("strict_regression_pass"):
            write_json(
                controller_status,
                {
                    "schema_version": "pvrig.top7500.continue_to_top200.v1",
                    "state": "STOPPED_STRICT_DOCKING_REGRESSION",
                    "updated_at": now_iso(),
                    "candidate_evidence_receipt": evidence_receipt_payload,
                },
            )
            return 2

        full_qc_root = root / "run/full_qc"
        qc_out = full_qc_root / "qc_out"
        full_qc_results = full_qc_root / "FULL_QC_RESULTS.tsv"
        if not full_qc_results.is_file():
            write_json(
                controller_status,
                {
                    "schema_version": "pvrig.top7500.continue_to_top200.v1",
                    "state": "RUNNING_FULL_QC_2000",
                    "updated_at": now_iso(),
                    "cpu_limit": 24,
                    "gpu_limit": 0,
                },
            )
            run_logged(
                [
                    "nice",
                    "-n",
                    "5",
                    "/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc",
                    str(aggregate_out / "full_qc_input_2000.fasta"),
                    "-o",
                    str(qc_out),
                    "--prefix",
                    "top2000",
                    "--workers",
                    "24",
                    "--muscle-bin",
                    str(root / "muscle_single_thread.sh"),
                    "--vhh-screen-bin",
                    str(root / "vhh_screen_parallel_tnp.sh"),
                    "--tnp-ncores",
                    "1",
                    "--identity-cache-size",
                    "500000",
                    "--skip-team-diversity",
                    "--gate-policy",
                    "blocker_calibrated",
                    "--docking-summary",
                    str(aggregate_out / "candidate_docking_summary.tsv"),
                    "--top-n",
                    "2000",
                    "--reserve-n",
                    "0",
                    "--local-positive-cdr-csv",
                    "/data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv",
                ],
                logs / "full_qc_2000.stdout.log",
                logs / "full_qc_2000.stderr.log",
            )
            source_portfolio = qc_out / "portfolio_ranked.tsv"
            if not source_portfolio.is_file() or row_count(source_portfolio) != 2000:
                raise ValueError("full QC portfolio is absent or does not contain 2000 rows")
            full_qc_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_portfolio, full_qc_results)
            write_json(
                full_qc_root / "FULL_QC_COMPLETE.json",
                {
                    "schema_version": "pvrig.top7500.full_qc_2000.v1",
                    "status": "PASS_FULL_QC_2000",
                    "rows": row_count(full_qc_results),
                    "sha256": sha256_file(full_qc_results),
                    "completed_at": now_iso(),
                    "cpu_limit": 24,
                    "gpu_limit": 0,
                },
            )

        top200_root = root / "run/top200"
        top200_receipt = top200_root / "TOP200_RECEIPT.json"
        if not top200_receipt.is_file():
            write_json(
                controller_status,
                {
                    "schema_version": "pvrig.top7500.continue_to_top200.v1",
                    "state": "SELECTING_TOP200",
                    "updated_at": now_iso(),
                },
            )
            run_logged(
                [
                    python,
                    str(root / "select_top200.py"),
                    "--evidence",
                    str(aggregate_out / "candidate_evidence_table.tsv"),
                    "--full-qc",
                    str(full_qc_results),
                    "--out",
                    str(top200_root),
                ],
                logs / "select_top200.stdout.log",
                logs / "select_top200.stderr.log",
            )
        receipt = read_json(top200_receipt)
        if receipt.get("count") != 200 or receipt.get("status") != "PASS_TOP200_FROZEN":
            raise ValueError(f"invalid Top200 receipt: {receipt}")
        write_json(
            controller_status,
            {
                "schema_version": "pvrig.top7500.continue_to_top200.v1",
                "state": "TOP200_COMPLETE",
                "updated_at": now_iso(),
                "top200_receipt": receipt,
            },
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
