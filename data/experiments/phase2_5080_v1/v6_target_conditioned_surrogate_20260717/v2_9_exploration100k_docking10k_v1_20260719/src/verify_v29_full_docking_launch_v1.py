#!/usr/bin/env python3
"""Validate the frozen V2.9 full-Docking launch and first shard activity."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_ROOT = Path("/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720")
CLAIM = (
    "Launch/provenance validation for an independent 8X6B/9E6Y computational Docking geometry teacher; "
    "not binding, affinity, experimental blocking, expression, purity, or Docking Gold."
)


class WaitingForActivity(RuntimeError):
    """The launch is structurally valid but a shard has not emitted a status yet."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, object]:
    require(path.is_file(), f"missing_json:{path}")
    return json.loads(path.read_text())


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing_tsv:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def pid_alive_local(pid: int) -> bool:
    return subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid="],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).returncode == 0


def pid_alive_remote(host: str, pid: int) -> bool:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "ps", "-p", str(pid), "-o", "pid="],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).returncode == 0


def validate(root: Path, require_first_status: bool, skip_pid_check: bool) -> dict[str, object]:
    staged = read_json(root / "status/STAGED.json")
    launched = read_json(root / "status/LAUNCHED.json")
    lock = read_json(root / "PROTOCOL_LOCK.json")
    require(staged.get("status") == "PASS_FULL_DOCKING_STAGED", "bad_staged_status")
    require(launched.get("status") == "RUNNING_FULL_DOCKING", "bad_launched_status")
    require(lock.get("status") == "LOCKED", "bad_protocol_lock_status")

    frozen = read_tsv(root / "inputs/docking_allocation25000_frozen_all.tsv")
    executable = read_tsv(root / "inputs/docking_allocation25000.tsv")
    jobs = read_tsv(root / "manifests/docking_jobs.tsv")
    node1 = read_tsv(root / "manifests/node1_jobs.tsv")
    node23 = read_tsv(root / "manifests/node23_jobs.tsv")

    frozen_ids = [row["job_id"] for row in frozen]
    executable_ids = [row["job_id"] for row in executable]
    job_ids = [row["job_id"] for row in jobs]
    node1_ids = {row["job_id"] for row in node1}
    node23_ids = {row["job_id"] for row in node23}
    require(len(frozen_ids) == 25000 and len(set(frozen_ids)) == 25000, "frozen_allocation_not_25000_unique")
    require(len(executable_ids) == len(set(executable_ids)), "duplicate_executable_job_id")
    require(len(job_ids) == len(set(job_ids)), "duplicate_job_manifest_id")
    allocation_keys = {(row["candidate_id"], row["receptor"].lower(), row["seed"]) for row in executable}
    manifest_keys = {(row["entity_id"], row["conformation"].lower(), row["seed"]) for row in jobs}
    require(allocation_keys == manifest_keys, "executable_manifest_semantic_job_set_mismatch")
    require(not (node1_ids & node23_ids), "node_shards_overlap")
    require(node1_ids | node23_ids == set(job_ids), "node_shards_do_not_close")
    require(len(jobs) == staged.get("executable_job_count"), "staged_job_count_mismatch")
    require(len(node1) == staged.get("node1_job_count"), "node1_staged_count_mismatch")
    require(len(node23) == staged.get("node23_job_count"), "node23_staged_count_mismatch")
    require(len(jobs) == launched.get("executable_job_count"), "launched_job_count_mismatch")

    hash_checks = {
        "core_lock_sha256": root / "PROTOCOL_CORE_LOCK.json",
        "job_manifest_sha256": root / "manifests/docking_jobs.tsv",
        "node1_jobs_sha256": root / "manifests/node1_jobs.tsv",
        "node23_jobs_sha256": root / "manifests/node23_jobs.tsv",
        "reference_normalization_summary_sha256": root / "reports/reference_normalization_summary.json",
    }
    for field, path in hash_checks.items():
        require(lock.get(field) == sha256_file(path), f"hash_mismatch:{field}")

    node1_pid = int(launched["node1_pid"])
    node23_pid = int(launched["node23_pid"])
    if not skip_pid_check:
        require(pid_alive_local(node1_pid), f"node1_shard_pid_not_alive:{node1_pid}")
        require(pid_alive_remote("node23", node23_pid), f"node23_shard_pid_not_alive:{node23_pid}")

    status_ids = {path.stem for path in (root / "status/jobs").glob("*.json")}
    node1_started = len(status_ids & node1_ids)
    node23_started = len(status_ids & node23_ids)
    if require_first_status and (node1_started == 0 or node23_started == 0):
        raise WaitingForActivity(f"waiting_first_status:node1={node1_started}:node23={node23_started}")

    payload = {
        "schema_version": "pvrig_v29_full_docking_launch_acceptance_v1",
        "status": "PASS_FULL_DOCKING_LAUNCH_ACCEPTANCE",
        "frozen_allocation_count": len(frozen),
        "executable_job_count": len(jobs),
        "node1_job_count": len(node1),
        "node23_job_count": len(node23),
        "node1_status_count_at_acceptance": node1_started,
        "node23_status_count_at_acceptance": node23_started,
        "node1_pid": node1_pid,
        "node23_pid": node23_pid,
        "protocol_lock_sha256": lock["protocol_lock_sha256"],
        "claim_boundary": CLAIM,
    }
    write_json(root / "status/LAUNCH_ACCEPTANCE.json", payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--require-first-status", action="store_true")
    parser.add_argument("--skip-pid-check", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.root, args.require_first_status, args.skip_pid_check), indent=2, sort_keys=True))
    except WaitingForActivity as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(3)
