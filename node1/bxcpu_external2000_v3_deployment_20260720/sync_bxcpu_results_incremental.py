#!/usr/bin/env python3
"""Incrementally relay stable bxcpu docking outputs through a bounded local spool to Node1."""

from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time


CAMPAIGNS = {
    "stage2": {
        "expected": 10500,
        "remote": "pvrig_v29_bxcpu_stage2_10500_v1_20260720_bxcpu_results",
    },
    "stage3_node20": {
        "expected": 734,
        "remote": "pvrig_v29_bxcpu_stage3_node20_v1_20260720_bxcpu_results",
    },
}
LOCAL_ROOT = pathlib.Path(
    os.environ.get(
        "PVRIG_BXCPU_SYNC_LOCAL_ROOT",
        "/mnt/d/work/抗体/node1/bxcpu_incremental_spool_20260720",
    )
)
NODE1_ROOT = os.environ.get(
    "PVRIG_BXCPU_SYNC_NODE1_ROOT",
    "/data/qlyu/projects/pvrig_v29_bxcpu_results_mirror_20260720",
)
BXCPU_HOME = os.environ.get(
    "PVRIG_BXCPU_HOME",
    "/publicfs04/fs04-al/home/als001821",
)
NODE1_SSH = os.environ.get(
    "PVRIG_NODE1_SSH",
    "/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe",
)
BATCH_SIZE = int(os.environ.get("PVRIG_BXCPU_SYNC_BATCH_SIZE", "5"))
STABLE_AGE_SECONDS = int(os.environ.get("PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS", "600"))
POLL_SECONDS = int(os.environ.get("PVRIG_BXCPU_SYNC_POLL_SECONDS", "60"))
MIN_LOCAL_FREE_BYTES = int(os.environ.get("PVRIG_BXCPU_SYNC_MIN_LOCAL_FREE_GIB", "5")) * 1024**3
SHARD_COUNT = int(os.environ.get("PVRIG_BXCPU_SYNC_SHARD_COUNT", "1"))
SHARD_INDEX = int(os.environ.get("PVRIG_BXCPU_SYNC_SHARD_INDEX", "0"))
if SHARD_COUNT < 1 or not 0 <= SHARD_INDEX < SHARD_COUNT:
    raise RuntimeError("invalid sync shard configuration")
SHARD_TAG = "" if SHARD_COUNT == 1 else f".shard{SHARD_INDEX:02d}of{SHARD_COUNT:02d}"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def log(message: str, **fields: object) -> None:
    payload = {"time": now(), "message": message, **fields}
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    with (LOCAL_ROOT / "state/sync_events.jsonl").open("a") as handle:
        handle.write(line + "\n")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def run_retry(
    command: list[str], *, accepted: tuple[int, ...] = (0,), attempts: int = 4
) -> subprocess.CompletedProcess[str]:
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        result = run(command, check=False)
        if result.returncode in accepted:
            return result
        if attempt < attempts:
            time.sleep(5 * attempt)
    assert result is not None
    raise RuntimeError(
        f"command failed after {attempts} attempts rc={result.returncode}: {result.stdout}"
    )


def rsync_base() -> list[str]:
    return [
        "rsync",
        "-az",
        "--partial",
        "--partial-dir=.rsync-partial",
        "--timeout=300",
    ]


def terminal(payload: dict[str, object]) -> bool:
    state = payload.get("status")
    return state in {"SUCCESS", "FAILED_MAX_ATTEMPTS"} or (
        state == "FAILED" and int(payload.get("attempts", 0) or 0) >= 2
    )


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_delivered(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def append_delivered(path: pathlib.Path, job_ids: list[str]) -> None:
    with path.open("a") as handle:
        for job_id in job_ids:
            handle.write(job_id + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_unique(path: pathlib.Path, job_ids: list[str]) -> None:
    existing = load_delivered(path)
    append_delivered(path, [job_id for job_id in job_ids if job_id not in existing])


def sync_metadata(name: str, remote_name: str, local_campaign: pathlib.Path) -> None:
    for subdir in ("status/jobs", "markers", "reports"):
        destination = local_campaign / subdir
        destination.mkdir(parents=True, exist_ok=True)
        command = rsync_base() + [
            f"bxcpu:{BXCPU_HOME}/{remote_name}/{subdir}/",
            str(destination) + "/",
        ]
        try:
            run_retry(command, accepted=(0, 23))
        except RuntimeError as exc:
            raise RuntimeError(f"metadata rsync failed for {name}/{subdir}: {exc}") from exc


def eligible_jobs(local_campaign: pathlib.Path, delivered: set[str]) -> list[str]:
    cutoff = time.time() - STABLE_AGE_SECONDS
    candidates: list[tuple[float, str]] = []
    for status_path in (local_campaign / "status/jobs").glob("*.json"):
        job_id = status_path.stem
        shard = int(hashlib.sha256(job_id.encode()).hexdigest()[:16], 16) % SHARD_COUNT
        if shard != SHARD_INDEX:
            continue
        if job_id in delivered or status_path.stat().st_mtime > cutoff:
            continue
        try:
            payload = json.loads(status_path.read_text())
        except Exception:
            continue
        if payload.get("job_id") not in (None, job_id) or not terminal(payload):
            continue
        candidates.append((status_path.stat().st_mtime, job_id))
    return [job_id for _, job_id in sorted(candidates)[:BATCH_SIZE]]


def write_requested_paths(path: pathlib.Path, job_ids: list[str]) -> None:
    lines = []
    for job_id in job_ids:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id):
            raise RuntimeError(f"unsafe job ID in transport request: {job_id!r}")
        lines.extend(
            [
                f"status/jobs/{job_id}.json",
                f"results/{job_id}/",
                f"runs/{job_id}/",
                f"worker_logs/{job_id}.log",
                f"compressed_queue/{job_id}.tar.gz",
            ]
        )
    path.write_text("\n".join(lines) + "\n")


def fetch_batch(
    remote_name: str, local_campaign: pathlib.Path, job_ids: list[str]
) -> pathlib.Path:
    requested = LOCAL_ROOT / "state/current_bxcpu_files.txt"
    write_requested_paths(requested, job_ids)
    cleanup_local_payload(local_campaign, job_ids)
    archive = LOCAL_ROOT / "state" / f"current_bxcpu_payload_{os.getpid()}.tar.gz"
    partial = archive.with_suffix(".tar.gz.partial")
    partial.unlink(missing_ok=True)
    archive.unlink(missing_ok=True)
    root = f"{BXCPU_HOME}/{remote_name}"
    remote_command = (
        f"tar -C {shlex.quote(root)} --ignore-failed-read -czf - -T -"
    )
    with partial.open("wb") as output:
        result = subprocess.run(
            ["ssh", "bxcpu", remote_command],
            input=requested.read_bytes(),
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"bxcpu tar stream failed rc={result.returncode}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    os.replace(partial, archive)
    run(["tar", "-tzf", str(archive)])
    run(["tar", "-xzf", str(archive), "-C", str(local_campaign)])
    for job_id in job_ids:
        compact = local_campaign / "compressed_queue" / f"{job_id}.tar.gz"
        if compact.is_file():
            run(["tar", "-tzf", str(compact)])
    return archive


def requested_roots(job_ids: list[str]) -> list[str]:
    roots = []
    for job_id in job_ids:
        roots.extend(
            [
                f"status/jobs/{job_id}.json",
                f"results/{job_id}",
                f"runs/{job_id}",
                f"worker_logs/{job_id}.log",
            ]
        )
    return roots


def remote_inventory(remote_name: str, job_ids: list[str]) -> dict[str, int]:
    root = f"{BXCPU_HOME}/{remote_name}"
    lines = ["set -euo pipefail", f"ROOT={root}"]
    for relative in requested_roots(job_ids):
        lines.append(
            f"if [[ -e \"$ROOT/{relative}\" ]]; then "
            f"find \"$ROOT/{relative}\" -type f -printf '%p\\t%s\\n'; fi"
        )
    result = subprocess.run(
        ["ssh", "bxcpu", "bash", "-s"],
        input="\n".join(lines) + "\n",
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    inventory = {}
    prefix = root + "/"
    for line in result.stdout.splitlines():
        path, size = line.rsplit("\t", 1)
        if not path.startswith(prefix):
            raise RuntimeError(f"unexpected remote inventory path: {path}")
        inventory[path[len(prefix) :]] = int(size)
    return inventory


def local_inventory(local_campaign: pathlib.Path, job_ids: list[str]) -> dict[str, int]:
    inventory = {}
    for relative in requested_roots(job_ids):
        path = local_campaign / relative
        if path.is_file():
            inventory[relative] = path.stat().st_size
        elif path.is_dir():
            for item in path.rglob("*"):
                if item.is_file() and ".rsync-partial" not in item.parts:
                    inventory[str(item.relative_to(local_campaign))] = item.stat().st_size
    return inventory


def validate_local_job(local_campaign: pathlib.Path, job_id: str) -> list[pathlib.Path]:
    status_path = local_campaign / "status/jobs" / f"{job_id}.json"
    payload = json.loads(status_path.read_text())
    if payload.get("job_id") not in (None, job_id) or not terminal(payload):
        raise RuntimeError(f"non-terminal or mismatched status for {job_id}")
    if payload.get("status") == "SUCCESS":
        result_path = local_campaign / "results" / job_id / "job_result.json"
        run_path = local_campaign / "runs" / job_id
        compact_path = local_campaign / "compressed_queue" / f"{job_id}.tar.gz"
        if not result_path.is_file() or not (run_path.is_dir() or compact_path.is_file()):
            raise RuntimeError(f"stable SUCCESS payload is incomplete for {job_id}")
        result = json.loads(result_path.read_text())
        if result.get("state") != "SUCCESS":
            raise RuntimeError(f"result state mismatch for {job_id}")
        for key in ("job_hash", "protocol_core_sha256"):
            if payload.get(key) and result.get(key) != payload.get(key):
                raise RuntimeError(f"{key} mismatch for {job_id}")
    compact_path = local_campaign / "compressed_queue" / f"{job_id}.tar.gz"
    if compact_path.is_file():
        roots = [status_path, local_campaign / "results" / job_id / "job_result.json"]
    else:
        roots = [
            status_path,
            local_campaign / "results" / job_id,
            local_campaign / "runs" / job_id,
            local_campaign / "worker_logs" / f"{job_id}.log",
        ]
    files: list[pathlib.Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file() and ".rsync-partial" not in path.parts)
    if status_path not in files:
        raise RuntimeError(f"status file missing from payload for {job_id}")
    return sorted(set(files))


def node1_prepare(campaign: str) -> None:
    command = f"mkdir -p {NODE1_ROOT}/{campaign}/state/batches"
    run_retry([NODE1_SSH, "node1", command])


def relay_and_verify(
    campaign: str,
    local_campaign: pathlib.Path,
    job_ids: list[str],
    archive: pathlib.Path,
) -> None:
    files: list[pathlib.Path] = []
    for job_id in job_ids:
        files.extend(validate_local_job(local_campaign, job_id))
    relative = sorted({str(path.relative_to(local_campaign)) for path in files})
    batch_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"_{os.getpid()}"
    files_from = LOCAL_ROOT / "state/current_node1_files.txt"
    files_from.write_text("\n".join(relative) + "\n")
    batch_manifest = LOCAL_ROOT / "state" / f"{campaign}_{batch_id}.sha256"
    batch_manifest.write_text(
        "".join(f"{sha256(local_campaign / rel)}  {rel}\n" for rel in relative)
    )
    node1_prepare(campaign)
    archive_sha = archive.with_suffix(".tar.gz.sha256")
    archive_sha.write_text(f"{sha256(archive)}  {archive.name}\n")
    incoming = f"{NODE1_ROOT}/{campaign}/state/incoming"
    run_retry([NODE1_SSH, "node1", f"mkdir -p {incoming}"])
    for source in (archive, archive_sha):
        run_retry(
            [
                "rsync",
                "-a",
                "--partial",
                "--partial-dir=.rsync-partial",
                "--timeout=600",
                "-e",
                NODE1_SSH,
                str(source),
                f"node1:{incoming}/",
            ]
        )
    remote_manifest = f"{NODE1_ROOT}/{campaign}/state/batches/{batch_manifest.name}"
    run_retry(
        [
            "rsync",
            "-a",
            "-e",
            NODE1_SSH,
            str(batch_manifest),
            f"node1:{remote_manifest}",
        ]
    )
    remote_campaign = f"{NODE1_ROOT}/{campaign}"
    verify_extract = (
        f"set -euo pipefail; cd {shlex.quote(incoming)}; "
        f"sha256sum -c {shlex.quote(archive_sha.name)}; "
        f"cp {shlex.quote(archive_sha.name)} ../batches/; "
        f"tar -xzf {shlex.quote(archive.name)} -C {shlex.quote(remote_campaign)}; "
        + " ".join(
            f"p={shlex.quote(remote_campaign + '/compressed_queue/' + job_id + '.tar.gz')}; "
            f"if [[ -f \"$p\" ]]; then tar -tzf \"$p\"; "
            f"tar -xzf \"$p\" -C {shlex.quote(remote_campaign)}; rm -f \"$p\"; fi;"
            for job_id in job_ids
        )
        + f" rm -f {shlex.quote(archive.name)} {shlex.quote(archive_sha.name)}"
    )
    run_retry([NODE1_SSH, "node1", verify_extract], attempts=2)
    archive.unlink(missing_ok=True)
    archive_sha.unlink(missing_ok=True)


def sync_small_metadata_to_node1(campaign: str, local_campaign: pathlib.Path) -> None:
    node1_prepare(campaign)
    for subdir in ("status", "markers", "reports"):
        source = local_campaign / subdir
        if not source.exists():
            continue
        try:
            run_retry(
                [
                    "rsync",
                    "-az",
                    "--partial",
                    "-e",
                    NODE1_SSH,
                    str(source) + "/",
                    f"node1:{NODE1_ROOT}/{campaign}/{subdir}/",
                ],
                accepted=(0, 23),
            )
        except RuntimeError as exc:
            raise RuntimeError(f"Node1 metadata sync failed for {campaign}/{subdir}: {exc}") from exc


def cleanup_local_payload(local_campaign: pathlib.Path, job_ids: list[str]) -> None:
    for job_id in job_ids:
        for path in (
            local_campaign / "results" / job_id,
            local_campaign / "runs" / job_id,
            local_campaign / "worker_logs" / f"{job_id}.log",
            local_campaign / "compressed_queue" / f"{job_id}.tar.gz",
        ):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()


def prune_bxcpu_verified_payload(
    campaign: str, remote_name: str, job_ids: list[str]
) -> list[str]:
    """Remove heavy bxcpu payload only after Node1 hash verification.

    The SUCCESS status and job_result.json are retained because the Stage2/Stage3
    workers and aggregators use them as durable resume stubs.
    """
    if not job_ids:
        return []
    code = r'''import json, os, shutil, sys
from pathlib import Path
root = Path(sys.argv[1])
pruned, skipped, errors = [], [], []
for job_id in [line.strip() for line in sys.stdin if line.strip()]:
    status_path = root / "status/jobs" / f"{job_id}.json"
    result_dir = root / "results" / job_id
    result_path = result_dir / "job_result.json"
    run_dir = root / "runs" / job_id
    try:
        status = json.loads(status_path.read_text())
        result = json.loads(result_path.read_text())
        if status.get("status") != "SUCCESS" or result.get("state") != "SUCCESS":
            skipped.append({"job_id": job_id, "reason": "not_success"})
            continue
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
        for child in list(result_dir.iterdir()):
            if child.name == "job_result.json":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
        worker_log = root / "worker_logs" / f"{job_id}.log"
        if worker_log.exists():
            worker_log.unlink()
        compact = root / "compressed_queue" / f"{job_id}.tar.gz"
        if compact.exists():
            compact.unlink()
        minimal_result = {
            "state": "SUCCESS",
            "job_id": result.get("job_id", job_id),
            "job_hash": result.get("job_hash"),
            "protocol_core_sha256": result.get("protocol_core_sha256"),
            "selected_model_count": result.get("selected_model_count"),
            "offloaded_to_node1": True,
        }
        result_tmp = result_path.with_suffix(".json.offload_tmp")
        result_tmp.write_text(json.dumps(minimal_result, sort_keys=True) + "\n")
        os.replace(str(result_tmp), str(result_path))
        if not status_path.is_file() or not result_path.is_file():
            raise RuntimeError("resume stubs missing after prune")
        pruned.append(job_id)
    except Exception as exc:
        errors.append({"job_id": job_id, "error": repr(exc)})
print(json.dumps({"pruned": pruned, "skipped": skipped, "errors": errors}))
'''
    remote_root = f"{BXCPU_HOME}/{remote_name}"
    remote_command = (
        f"python3 -c {shlex.quote(code)} {shlex.quote(remote_root)}"
    )
    result = subprocess.run(
        ["ssh", "bxcpu", remote_command],
        input="\n".join(job_ids) + "\n",
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"bxcpu prune command failed rc={result.returncode}: {result.stderr.strip()}"
        )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    event = {
        "time": now(),
        "campaign": campaign,
        "requested": len(job_ids),
        **payload,
    }
    with (LOCAL_ROOT / "state/bxcpu_prune_events.jsonl").open("a") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    if payload["errors"]:
        log("bxcpu verified-payload prune had errors", campaign=campaign, errors=payload["errors"])
    return list(payload["pruned"])


def campaign_cycle(name: str, config: dict[str, object]) -> dict[str, object]:
    cycle_started = time.monotonic()
    checkpoint = cycle_started

    def timed(stage: str) -> None:
        nonlocal checkpoint
        current = time.monotonic()
        log(
            "campaign stage timing",
            campaign=name,
            stage=stage,
            stage_seconds=round(current - checkpoint, 3),
            cycle_seconds=round(current - cycle_started, 3),
        )
        checkpoint = current

    local_campaign = LOCAL_ROOT / name
    local_campaign.mkdir(parents=True, exist_ok=True)
    delivered_path = LOCAL_ROOT / "state" / f"{name}{SHARD_TAG}.delivered_job_ids.txt"
    pruned_path = LOCAL_ROOT / "state" / f"{name}{SHARD_TAG}.pruned_job_ids.txt"
    sync_metadata(name, str(config["remote"]), local_campaign)
    sync_small_metadata_to_node1(name, local_campaign)
    timed("metadata")
    delivered = load_delivered(delivered_path)
    pruned = load_delivered(pruned_path)
    prune_backlog = sorted(delivered - pruned)[:BATCH_SIZE]
    if prune_backlog:
        newly_pruned = prune_bxcpu_verified_payload(
            name, str(config["remote"]), prune_backlog
        )
        append_unique(pruned_path, newly_pruned)
        pruned.update(newly_pruned)
    jobs = eligible_jobs(local_campaign, delivered)
    if not jobs:
        return {
            "campaign": name,
            "delivered": len(delivered),
            "pruned": len(pruned),
            "batch": 0,
        }
    if shutil.disk_usage(LOCAL_ROOT).free < MIN_LOCAL_FREE_BYTES:
        raise RuntimeError("local spool has less than the configured free-space reserve")
    archive = fetch_batch(str(config["remote"]), local_campaign, jobs)
    timed("fetch_tar_stream")
    timed("archive_extract")
    valid_jobs = []
    for job_id in jobs:
        try:
            validate_local_job(local_campaign, job_id)
            valid_jobs.append(job_id)
        except Exception as exc:
            log("job deferred after incomplete fetch", campaign=name, job_id=job_id, error=str(exc))
    if not valid_jobs:
        return {"campaign": name, "delivered": len(delivered), "batch": 0}
    relay_and_verify(name, local_campaign, valid_jobs, archive)
    timed("relay_archive_to_node1")
    append_delivered(delivered_path, valid_jobs)
    run_retry(
        [
            "rsync",
            "-a",
            "-e",
            NODE1_SSH,
            str(delivered_path),
            f"node1:{NODE1_ROOT}/{name}/state/{delivered_path.name}",
        ]
    )
    newly_pruned = prune_bxcpu_verified_payload(name, str(config["remote"]), valid_jobs)
    timed("remote_prune")
    append_unique(pruned_path, newly_pruned)
    pruned.update(newly_pruned)
    run_retry(
        [
            "rsync",
            "-a",
            "-e",
            NODE1_SSH,
            str(pruned_path),
            f"node1:{NODE1_ROOT}/{name}/state/{pruned_path.name}",
        ]
    )
    cleanup_local_payload(local_campaign, valid_jobs)
    return {
        "campaign": name,
        "delivered": len(delivered) + len(valid_jobs),
        "pruned": len(pruned),
        "batch": len(valid_jobs),
    }


def cycle() -> None:
    summaries = []
    for name, config in CAMPAIGNS.items():
        try:
            summaries.append(campaign_cycle(name, config))
        except Exception as exc:
            summaries.append({"campaign": name, "error": repr(exc)})
            log("campaign cycle failed", campaign=name, error=repr(exc))
    receipt = {
        "schema_version": "pvrig_bxcpu_incremental_sync_status_v1",
        "updated_at_utc": now(),
        "local_root": str(LOCAL_ROOT),
        "node1_root": NODE1_ROOT,
        "batch_size": BATCH_SIZE,
        "stable_age_seconds": STABLE_AGE_SECONDS,
        "shard_count": SHARD_COUNT,
        "shard_index": SHARD_INDEX,
        "campaigns": summaries,
    }
    path = LOCAL_ROOT / "state" / f"SYNC_STATUS{SHARD_TAG}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
    log("sync cycle complete", campaigns=summaries)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    (LOCAL_ROOT / "state").mkdir(parents=True, exist_ok=True)
    lock_handle = (LOCAL_ROOT / "state" / f"sync{SHARD_TAG}.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another sync process owns the lock", file=sys.stderr)
        return 0
    while True:
        try:
            cycle()
        except Exception as exc:
            log("top-level cycle failed", error=repr(exc))
        if args.once:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
