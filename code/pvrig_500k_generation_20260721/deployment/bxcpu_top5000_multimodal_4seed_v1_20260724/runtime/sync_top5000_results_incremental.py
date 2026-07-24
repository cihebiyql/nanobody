#!/usr/bin/env python3
"""Four-way incremental bxcpu -> bounded local spool -> Node1 result relay."""

from __future__ import annotations

import argparse
import datetime as dt
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
import tarfile
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


EXPECTED_JOBS = 40_000
EXPECTED_SYNC_SHARDS = 4
PROJECT_NAME = os.environ.get(
    "PVRIG_TOP5000_PROJECT_NAME",
    "pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724",
)
BXCPU_HOME = os.environ.get(
    "PVRIG_BXCPU_HOME", "/publicfs04/fs04-al/home/als001821"
)
BXCPU_RESULT_ROOT = os.environ.get(
    "PVRIG_TOP5000_BXCPU_RESULT_ROOT",
    f"{BXCPU_HOME}/{PROJECT_NAME}_bxcpu_results",
)
LOCAL_ROOT = pathlib.Path(
    os.environ.get(
        "PVRIG_TOP5000_SYNC_LOCAL_ROOT",
        "/mnt/d/work/抗体/node1/"
        "pvrig_top5000_multimodal_4seed_bxcpu_incremental_spool_20260724/"
        "shard00",
    )
)
NODE1_ROOT = os.environ.get(
    "PVRIG_TOP5000_NODE1_RESULT_ROOT",
    "/data/qlyu/projects/"
    "pvrig_node1_generated100k_multimodal_top5000_4seed_docking_results_v1_20260724",
)
BXCPU_HOST = os.environ.get("PVRIG_BXCPU_HOST", "bxcpu")
BXCPU_SSH = os.environ.get(
    "PVRIG_BXCPU_SSH", "/mnt/c/Windows/System32/OpenSSH/ssh.exe"
)
NODE1_HOST = os.environ.get("PVRIG_NODE1_HOST", "node1")
NODE1_SSH = os.environ.get(
    "PVRIG_NODE1_SSH", "/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe"
)
REMOTE_PRUNE_HELPER = os.environ.get(
    "PVRIG_TOP5000_BXCPU_PRUNE_HELPER",
    f"{BXCPU_HOME}/.local/share/"
    "bxcpu_top5000_multimodal_4seed_v1_20260724/runtime/"
    "prune_bxcpu_payload.py",
)
LOCAL_PRUNE_HELPER = pathlib.Path(__file__).with_name("prune_bxcpu_payload.py")
EXPECTED_PRUNE_HELPER_SHA256 = os.environ.get(
    "PVRIG_TOP5000_PRUNE_HELPER_SHA256", ""
)

BATCH_SIZE = int(os.environ.get("PVRIG_TOP5000_SYNC_BATCH_SIZE", "60"))
STABLE_AGE_SECONDS = int(
    os.environ.get("PVRIG_TOP5000_SYNC_STABLE_AGE_SECONDS", "90")
)
POLL_SECONDS = int(os.environ.get("PVRIG_TOP5000_SYNC_POLL_SECONDS", "10"))
MIN_LOCAL_FREE_BYTES = (
    int(os.environ.get("PVRIG_TOP5000_SYNC_MIN_LOCAL_FREE_GIB", "10")) * 1024**3
)
MAX_LOCAL_SPOOL_BYTES = (
    int(
        os.environ.get(
            "PVRIG_TOP5000_SYNC_MAX_SPOOL_GIB_PER_SHARD",
            "4",
        )
    )
    * 1024**3
)
SHARD_COUNT = int(os.environ.get("PVRIG_TOP5000_SYNC_SHARD_COUNT", "4"))
SHARD_INDEX = int(os.environ.get("PVRIG_TOP5000_SYNC_SHARD_INDEX", "0"))
SHARD_TAG = f"shard{SHARD_INDEX:02d}of{SHARD_COUNT:02d}"
SAFE_JOB_ID = re.compile(r"[A-Za-z0-9_.-]+")


def validate_configuration() -> None:
    if SHARD_COUNT != EXPECTED_SYNC_SHARDS:
        raise RuntimeError("incremental sync requires exactly four parallel shards")
    if not 0 <= SHARD_INDEX < SHARD_COUNT:
        raise RuntimeError("invalid incremental sync shard index")
    if BATCH_SIZE < 1:
        raise RuntimeError("batch size must be positive")
    if MAX_LOCAL_SPOOL_BYTES <= 0:
        raise RuntimeError("bounded spool limit must be positive")
    for name, value in (
        ("bxcpu result root", BXCPU_RESULT_ROOT),
        ("Node1 result root", NODE1_ROOT),
    ):
        if "\n" in value:
            raise RuntimeError(f"unsafe newline in {name}")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def log(message: str, **fields: Any) -> None:
    payload = {"time": now(), "message": message, **fields}
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    state = LOCAL_ROOT / "state"
    state.mkdir(parents=True, exist_ok=True)
    with (state / "sync_events.jsonl").open("a") as handle:
        handle.write(line + "\n")


def run(
    command: List[str],
    *,
    check: bool = True,
    input_text: Optional[str] = None,
    timeout_seconds: int = 900,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=check,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_seconds,
    )


def run_retry(
    command: List[str],
    *,
    accepted: Tuple[int, ...] = (0,),
    attempts: int = 4,
) -> subprocess.CompletedProcess:
    result = None
    for attempt in range(1, attempts + 1):
        try:
            result = run(command, check=False)
        except subprocess.TimeoutExpired as exc:
            if attempt == attempts:
                raise RuntimeError(
                    f"command timed out after {attempts} attempts: {command}"
                ) from exc
            time.sleep(5 * attempt)
            continue
        if result.returncode in accepted:
            return result
        if attempt < attempts:
            time.sleep(5 * attempt)
    assert result is not None
    raise RuntimeError(
        f"command failed after {attempts} attempts rc={result.returncode}: "
        f"{result.stdout}"
    )


def bxcpu_ssh(command: str) -> List[str]:
    return [
        BXCPU_SSH,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=4",
        BXCPU_HOST,
        command,
    ]


def node1_ssh(command: str) -> List[str]:
    return [
        NODE1_SSH,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=4",
        NODE1_HOST,
        command,
    ]


def rsync_base() -> List[str]:
    return [
        "rsync",
        "-az",
        "--partial",
        "--partial-dir=.rsync-partial",
        "--timeout=300",
        "-e",
        BXCPU_SSH,
    ]


def terminal(payload: Dict[str, Any]) -> bool:
    state = payload.get("status")
    return state in {"SUCCESS", "FAILED_MAX_ATTEMPTS"} or (
        state == "FAILED" and int(payload.get("attempts", 0) or 0) >= 2
    )


def load_ids(path: pathlib.Path) -> Set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def append_ids(path: pathlib.Path, job_ids: Iterable[str]) -> None:
    existing = load_ids(path)
    new_ids = [job_id for job_id in job_ids if job_id not in existing]
    if not new_ids:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for job_id in new_ids:
            handle.write(job_id + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def atomic_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def sync_metadata(local_payload: pathlib.Path) -> None:
    for subdir in ("status/jobs", "markers", "reports"):
        destination = local_payload / subdir
        destination.mkdir(parents=True, exist_ok=True)
        command = rsync_base() + [
            f"{BXCPU_HOST}:{BXCPU_RESULT_ROOT}/{subdir}/",
            str(destination) + "/",
        ]
        try:
            run_retry(command, accepted=(0, 23))
        except RuntimeError as exc:
            raise RuntimeError(f"bxcpu metadata rsync failed for {subdir}: {exc}")


def sync_small_metadata_to_node1(local_payload: pathlib.Path) -> None:
    node1_prepare()
    for subdir in ("status", "markers", "reports"):
        source = local_payload / subdir
        if not source.exists():
            continue
        run_retry(
            [
                "rsync",
                "-az",
                "--partial",
                "--timeout=300",
                "-e",
                NODE1_SSH,
                str(source) + "/",
                f"{NODE1_HOST}:{NODE1_ROOT}/{subdir}/",
            ],
            accepted=(0, 23),
        )


def eligible_jobs(local_payload: pathlib.Path, delivered: Set[str]) -> List[str]:
    cutoff = time.time() - STABLE_AGE_SECONDS
    candidates: List[Tuple[float, str]] = []
    for status_path in (local_payload / "status/jobs").glob("*.json"):
        job_id = status_path.stem
        if not SAFE_JOB_ID.fullmatch(job_id):
            continue
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


def requested_roots(job_ids: Iterable[str]) -> List[str]:
    roots: List[str] = []
    for job_id in job_ids:
        if not SAFE_JOB_ID.fullmatch(job_id):
            raise RuntimeError(f"unsafe job ID: {job_id!r}")
        roots.extend(
            [
                f"status/jobs/{job_id}.json",
                f"results/{job_id}",
                f"runs/{job_id}",
                f"worker_logs/{job_id}.log",
                f"compressed_queue/{job_id}.tar.gz",
            ]
        )
    return roots


def remote_inventory(job_ids: List[str]) -> Dict[str, int]:
    root = BXCPU_RESULT_ROOT.rstrip("/")
    lines = ["set -euo pipefail", f"ROOT={shlex.quote(root)}"]
    for relative in requested_roots(job_ids):
        quoted = shlex.quote(relative)
        lines.append(
            f'if [[ -e "$ROOT"/{quoted} ]]; then '
            f'find "$ROOT"/{quoted} -type f -printf "%p\\t%s\\n"; fi'
        )
    result = run(bxcpu_ssh("bash -s"), input_text="\n".join(lines) + "\n")
    inventory: Dict[str, int] = {}
    prefix = root + "/"
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        path, size = line.rsplit("\t", 1)
        if not path.startswith(prefix):
            raise RuntimeError(f"unexpected remote inventory path: {path}")
        inventory[path[len(prefix) :]] = int(size)
    return inventory


def local_inventory(
    local_payload: pathlib.Path, job_ids: List[str]
) -> Dict[str, int]:
    inventory: Dict[str, int] = {}
    for relative in requested_roots(job_ids):
        path = local_payload / relative
        if path.is_file():
            inventory[relative] = path.stat().st_size
        elif path.is_dir():
            for item in path.rglob("*"):
                if item.is_file() and ".rsync-partial" not in item.parts:
                    inventory[str(item.relative_to(local_payload))] = item.stat().st_size
    return inventory


def directory_size(root: pathlib.Path) -> int:
    total = 0
    if not root.exists():
        return total
    for directory, _, files in os.walk(root):
        base = pathlib.Path(directory)
        for name in files:
            try:
                total += (base / name).stat().st_size
            except FileNotFoundError:
                continue
    return total


def choose_bounded_jobs(
    jobs: List[str],
) -> Tuple[List[str], Dict[str, int]]:
    selected = list(jobs)
    while selected:
        inventory = remote_inventory(selected)
        remote_bytes = sum(inventory.values())
        current_bytes = directory_size(LOCAL_ROOT)
        # During relay, one batch can temporarily exist as fetched tar,
        # extracted files, and a Node1 transport tar.
        projected_bytes = current_bytes + 3 * remote_bytes + 64 * 1024**2
        free_bytes = shutil.disk_usage(LOCAL_ROOT).free
        if (
            projected_bytes <= MAX_LOCAL_SPOOL_BYTES
            and free_bytes - 3 * remote_bytes >= MIN_LOCAL_FREE_BYTES
        ):
            return selected, inventory
        if len(selected) == 1:
            log(
                "single job exceeds bounded spool budget",
                job_id=selected[0],
                remote_bytes=remote_bytes,
                current_bytes=current_bytes,
                projected_bytes=projected_bytes,
                max_spool_bytes=MAX_LOCAL_SPOOL_BYTES,
                free_bytes=free_bytes,
            )
            return [], {}
        selected = selected[: max(1, len(selected) // 2)]
    return [], {}


def cleanup_local_payload(local_payload: pathlib.Path, job_ids: Iterable[str]) -> None:
    for job_id in job_ids:
        for path in (
            local_payload / "results" / job_id,
            local_payload / "runs" / job_id,
            local_payload / "worker_logs" / f"{job_id}.log",
            local_payload / "compressed_queue" / f"{job_id}.tar.gz",
        ):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()


def cleanup_transients() -> None:
    state = LOCAL_ROOT / "state"
    for pattern in ("*.tar", "*.tar.partial", "*.tar.sha256"):
        for path in state.glob(pattern):
            path.unlink(missing_ok=True)
    for path in (state / "batches").glob("*.pending") if (state / "batches").exists() else []:
        path.unlink(missing_ok=True)


def fetch_batch(
    local_payload: pathlib.Path,
    job_ids: List[str],
    expected_inventory: Dict[str, int],
) -> pathlib.Path:
    state = LOCAL_ROOT / "state"
    requested = state / "current_bxcpu_files.txt"
    requested.write_text("\n".join(requested_roots(job_ids)) + "\n")
    cleanup_local_payload(local_payload, job_ids)
    archive = state / f"current_bxcpu_payload_{os.getpid()}.tar"
    partial = archive.with_suffix(".tar.partial")
    partial.unlink(missing_ok=True)
    archive.unlink(missing_ok=True)
    remote_command = (
        f"tar -C {shlex.quote(BXCPU_RESULT_ROOT)} "
        "--ignore-failed-read -cf - -T -"
    )
    with partial.open("wb") as output:
        result = subprocess.run(
            bxcpu_ssh(remote_command),
            input=requested.read_bytes(),
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
            timeout=900,
        )
    if result.returncode != 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"bxcpu tar stream failed rc={result.returncode}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    os.replace(partial, archive)
    listing = run(["tar", "-tf", str(archive)]).stdout.splitlines()
    allowed = {"status", "results", "runs", "worker_logs", "compressed_queue"}
    for member in listing:
        pure = pathlib.PurePosixPath(member)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise RuntimeError(f"unsafe tar member: {member}")
        if pure.parts[0] not in allowed:
            raise RuntimeError(f"unexpected tar member: {member}")
    run(["tar", "-xf", str(archive), "-C", str(local_payload)])
    observed = local_inventory(local_payload, job_ids)
    if observed != expected_inventory:
        missing = sorted(set(expected_inventory) - set(observed))[:10]
        changed = sorted(
            path
            for path in set(expected_inventory).intersection(observed)
            if expected_inventory[path] != observed[path]
        )[:10]
        raise RuntimeError(
            f"fetched inventory mismatch missing={missing} changed={changed}"
        )
    return archive


def validate_local_job(
    local_payload: pathlib.Path, job_id: str
) -> List[pathlib.Path]:
    status_path = local_payload / "status/jobs" / f"{job_id}.json"
    status = json.loads(status_path.read_text())
    if status.get("job_id") not in (None, job_id) or not terminal(status):
        raise RuntimeError(f"non-terminal or mismatched status for {job_id}")
    roots: List[pathlib.Path] = [status_path]
    if status.get("status") == "SUCCESS":
        result_path = local_payload / "results" / job_id / "job_result.json"
        compact_path = local_payload / "compressed_queue" / f"{job_id}.tar.gz"
        if not result_path.is_file() or not compact_path.is_file():
            raise RuntimeError(f"SUCCESS payload is incomplete for {job_id}")
        result = json.loads(result_path.read_text())
        if result.get("state") != "SUCCESS":
            raise RuntimeError(f"result state mismatch for {job_id}")
        if result.get("job_id") not in (None, job_id):
            raise RuntimeError(f"result identity mismatch for {job_id}")
        for key in ("job_hash", "protocol_core_sha256"):
            if status.get(key) and result.get(key) != status.get(key):
                raise RuntimeError(f"{key} mismatch for {job_id}")
        with tarfile.open(compact_path, "r:gz") as archive:
            names = set(archive.getnames())
        required = {
            f"runs/{job_id}/COMPACT_EVIDENCE.json",
            f"results/{job_id}/job_result.json",
        }
        if not required.issubset(names):
            raise RuntimeError(f"compressed evidence incomplete for {job_id}")
        roots.extend([result_path, compact_path])
    else:
        roots.extend(
            [
                local_payload / "results" / job_id,
                local_payload / "runs" / job_id,
                local_payload / "worker_logs" / f"{job_id}.log",
            ]
        )
    worker_log = local_payload / "worker_logs" / f"{job_id}.log"
    if worker_log.is_file():
        roots.append(worker_log)
    files: List[pathlib.Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                path
                for path in root.rglob("*")
                if path.is_file() and ".rsync-partial" not in path.parts
            )
    if status_path not in files:
        raise RuntimeError(f"status missing from validated payload for {job_id}")
    return sorted(set(files))


def node1_prepare() -> None:
    command = (
        f"mkdir -p {shlex.quote(NODE1_ROOT)}/"
        "{status/jobs,results,worker_logs,compressed_queue,markers,reports,"
        "state/incoming,state/batches}"
    )
    run_retry(node1_ssh(command))


def relay_and_verify(
    local_payload: pathlib.Path,
    job_ids: List[str],
    fetched_archive: pathlib.Path,
) -> Dict[str, Any]:
    files: List[pathlib.Path] = []
    for job_id in job_ids:
        files.extend(validate_local_job(local_payload, job_id))
    relative = sorted({str(path.relative_to(local_payload)) for path in files})
    batch_id = (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        + f"_{SHARD_TAG}_{time.time_ns()}_{os.getpid()}"
    )
    state = LOCAL_ROOT / "state"
    local_batches = state / "batches"
    local_batches.mkdir(parents=True, exist_ok=True)
    files_from = state / "current_node1_files.txt"
    files_from.write_text("\n".join(relative) + "\n")

    file_manifest = local_batches / f"{batch_id}.files.sha256.pending"
    file_manifest.write_text(
        "".join(f"{sha256(local_payload / path)}  {path}\n" for path in relative)
    )
    receipt = local_batches / f"{batch_id}.receipt.json.pending"
    receipt_payload = {
        "schema_version": "pvrig.top5000_multimodal_4seed.node1_batch.v1",
        "status": "PENDING_NODE1_HASH_VERIFICATION",
        "batch_id": batch_id,
        "sync_shard": SHARD_INDEX,
        "sync_shard_count": SHARD_COUNT,
        "job_ids": job_ids,
        "file_count": len(relative),
        "file_manifest_sha256": sha256(file_manifest),
        "created_at_utc": now(),
    }
    atomic_json(receipt, receipt_payload)

    archive = state / f"{batch_id}.tar"
    partial = archive.with_suffix(".tar.partial")
    run(
        [
            "tar",
            "-C",
            str(local_payload),
            "-cf",
            str(partial),
            "-T",
            str(files_from),
        ]
    )
    run(
        [
            "tar",
            "-C",
            str(LOCAL_ROOT),
            "-rf",
            str(partial),
            str(file_manifest.relative_to(LOCAL_ROOT)),
            str(receipt.relative_to(LOCAL_ROOT)),
        ]
    )
    run(["tar", "-tf", str(partial)])
    os.replace(partial, archive)
    fetched_archive.unlink(missing_ok=True)
    archive_sha = archive.with_suffix(".tar.sha256")
    archive_sha.write_text(f"{sha256(archive)}  {archive.name}\n")
    final_archive_sha256 = sha256(archive)

    node1_prepare()
    incoming = f"{NODE1_ROOT}/state/incoming"
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
                f"{NODE1_HOST}:{incoming}/",
            ]
        )

    pending_manifest = f"state/batches/{file_manifest.name}"
    final_manifest = pending_manifest.removesuffix(".pending")
    pending_receipt = f"state/batches/{receipt.name}"
    final_receipt = pending_receipt.removesuffix(".pending")
    verify_python = (
        "import datetime,json,os,pathlib,sys;"
        "src=pathlib.Path(sys.argv[1]);dst=pathlib.Path(sys.argv[2]);"
        "d=json.loads(src.read_text());"
        "d['status']='VERIFIED_ON_NODE1_BEFORE_BXCPU_PRUNE';"
        "d['verified_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();"
        "d['archive_sha256']=sys.argv[3];"
        "tmp=dst.with_name('.'+dst.name+'.partial');"
        "tmp.write_text(json.dumps(d,indent=2,sort_keys=True)+'\\n');"
        "os.replace(tmp,dst);src.unlink()"
    )
    verify_manifest_anchor_python = (
        "import hashlib,json,pathlib,sys;"
        "receipt=json.loads(pathlib.Path(sys.argv[1]).read_text());"
        "actual=hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest();"
        "assert receipt['file_manifest_sha256']==actual,(receipt,actual)"
    )
    verify_existing_python = (
        "import json,pathlib,sys;"
        "d=json.loads(pathlib.Path(sys.argv[1]).read_text());"
        "assert d['status']=='VERIFIED_ON_NODE1_BEFORE_BXCPU_PRUNE';"
        "assert d['batch_id']==sys.argv[2];"
        "assert d['archive_sha256']==sys.argv[3]"
    )
    inner = (
        "set -euo pipefail; "
        f"if [[ -f {shlex.quote(NODE1_ROOT + '/' + final_receipt)} ]]; then "
        f"python3 -c {shlex.quote(verify_existing_python)} "
        f"{shlex.quote(NODE1_ROOT + '/' + final_receipt)} "
        f"{shlex.quote(batch_id)} {shlex.quote(final_archive_sha256)}; "
        "exit 0; fi; "
        f"cd {shlex.quote(incoming)}; "
        f"sha256sum -c {shlex.quote(archive_sha.name)}; "
        f"tar -xf {shlex.quote(incoming + '/' + archive.name)} "
        f"-C {shlex.quote(NODE1_ROOT)}; "
        f"cd {shlex.quote(NODE1_ROOT)}; "
        f"python3 -c {shlex.quote(verify_manifest_anchor_python)} "
        f"{shlex.quote(pending_receipt)} {shlex.quote(pending_manifest)}; "
        f"sha256sum -c {shlex.quote(pending_manifest)}; "
        f"mv {shlex.quote(pending_manifest)} {shlex.quote(final_manifest)}; "
        f"python3 -c {shlex.quote(verify_python)} "
        f"{shlex.quote(pending_receipt)} {shlex.quote(final_receipt)} "
        f"{shlex.quote(final_archive_sha256)}; "
        f"cp {shlex.quote(incoming + '/' + archive_sha.name)} "
        f"{shlex.quote(NODE1_ROOT + '/state/batches/' + archive_sha.name)}; "
        f"rm -f {shlex.quote(incoming + '/' + archive.name)} "
        f"{shlex.quote(incoming + '/' + archive_sha.name)}"
    )
    verify_command = (
        "set -euo pipefail; "
        f"flock -x {shlex.quote(NODE1_ROOT + '/state/extract.lock')} "
        f"-c {shlex.quote(inner)}"
    )
    run_retry(node1_ssh(verify_command), attempts=2)

    verification = {
        **receipt_payload,
        "status": "VERIFIED_ON_NODE1_BEFORE_BXCPU_PRUNE",
        "archive_sha256": final_archive_sha256,
        "verified_at_utc": now(),
    }
    with (state / "verified_batches.jsonl").open("a") as handle:
        handle.write(json.dumps(verification, sort_keys=True) + "\n")
    for path in (archive, archive_sha, file_manifest, receipt):
        path.unlink(missing_ok=True)
    return verification


def sync_state_file_to_node1(path: pathlib.Path) -> None:
    run_retry(
        [
            "rsync",
            "-a",
            "-e",
            NODE1_SSH,
            str(path),
            f"{NODE1_HOST}:{NODE1_ROOT}/state/{path.name}",
        ]
    )


def prune_bxcpu_verified_payload(job_ids: List[str]) -> List[str]:
    if not job_ids:
        return []
    expected_helper_sha = EXPECTED_PRUNE_HELPER_SHA256 or sha256(LOCAL_PRUNE_HELPER)
    remote_command = (
        "set -euo pipefail; "
        f"[[ $(sha256sum {shlex.quote(REMOTE_PRUNE_HELPER)} | awk '{{print $1}}') "
        f"== {shlex.quote(expected_helper_sha)} ]]; "
        f"python3 {shlex.quote(REMOTE_PRUNE_HELPER)} "
        f"--root {shlex.quote(BXCPU_RESULT_ROOT)}"
    )
    result = run(
        bxcpu_ssh(remote_command),
        check=False,
        input_text="\n".join(job_ids) + "\n",
    )
    if result.returncode not in (0, 2):
        raise RuntimeError(
            f"bxcpu prune command failed rc={result.returncode}: {result.stdout}"
        )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:
        raise RuntimeError(f"invalid bxcpu prune response: {result.stdout}") from exc
    event = {
        "time": now(),
        "requested": len(job_ids),
        "node1_hash_verification_required": True,
        **payload,
    }
    with (LOCAL_ROOT / "state/bxcpu_prune_events.jsonl").open("a") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    if payload["errors"]:
        log("bxcpu prune had errors", errors=payload["errors"])
    return list(payload["pruned"])


def campaign_cycle() -> Dict[str, Any]:
    cleanup_transients()
    local_payload = LOCAL_ROOT / "payload"
    local_payload.mkdir(parents=True, exist_ok=True)
    delivered_path = (
        LOCAL_ROOT / "state" / f"top5000_multimodal.{SHARD_TAG}.delivered_job_ids.txt"
    )
    pruned_path = (
        LOCAL_ROOT / "state" / f"top5000_multimodal.{SHARD_TAG}.pruned_job_ids.txt"
    )

    sync_metadata(local_payload)
    sync_small_metadata_to_node1(local_payload)
    delivered = load_ids(delivered_path)
    pruned = load_ids(pruned_path)

    prune_backlog = sorted(delivered - pruned)[:BATCH_SIZE]
    if prune_backlog:
        newly_pruned = prune_bxcpu_verified_payload(prune_backlog)
        append_ids(pruned_path, newly_pruned)
        pruned.update(newly_pruned)
        sync_state_file_to_node1(pruned_path)

    candidate_jobs = eligible_jobs(local_payload, delivered)
    if not candidate_jobs:
        return {
            "expected_jobs": EXPECTED_JOBS,
            "delivered": len(delivered),
            "pruned": len(pruned),
            "batch": 0,
            "spool_bytes": directory_size(LOCAL_ROOT),
            "max_spool_bytes": MAX_LOCAL_SPOOL_BYTES,
        }

    jobs, inventory = choose_bounded_jobs(candidate_jobs)
    if not jobs:
        return {
            "expected_jobs": EXPECTED_JOBS,
            "delivered": len(delivered),
            "pruned": len(pruned),
            "batch": 0,
            "bounded_spool_deferred": len(candidate_jobs),
            "spool_bytes": directory_size(LOCAL_ROOT),
            "max_spool_bytes": MAX_LOCAL_SPOOL_BYTES,
        }

    fetched = fetch_batch(local_payload, jobs, inventory)
    valid_jobs: List[str] = []
    for job_id in jobs:
        try:
            validate_local_job(local_payload, job_id)
            valid_jobs.append(job_id)
        except Exception as exc:
            log("job deferred after validation", job_id=job_id, error=repr(exc))
            cleanup_local_payload(local_payload, [job_id])
    if not valid_jobs:
        fetched.unlink(missing_ok=True)
        return {
            "expected_jobs": EXPECTED_JOBS,
            "delivered": len(delivered),
            "pruned": len(pruned),
            "batch": 0,
        }

    try:
        verification = relay_and_verify(local_payload, valid_jobs, fetched)
        append_ids(delivered_path, valid_jobs)
        sync_state_file_to_node1(delivered_path)
        newly_pruned = prune_bxcpu_verified_payload(valid_jobs)
        append_ids(pruned_path, newly_pruned)
        pruned.update(newly_pruned)
        sync_state_file_to_node1(pruned_path)
    finally:
        cleanup_local_payload(local_payload, valid_jobs)

    return {
        "expected_jobs": EXPECTED_JOBS,
        "delivered": len(delivered) + len(valid_jobs),
        "pruned": len(pruned),
        "batch": len(valid_jobs),
        "verified_batch_id": verification["batch_id"],
        "spool_bytes": directory_size(LOCAL_ROOT),
        "max_spool_bytes": MAX_LOCAL_SPOOL_BYTES,
    }


def cycle() -> bool:
    try:
        summary = campaign_cycle()
        success = True
    except Exception as exc:
        summary = {"error": repr(exc)}
        success = False
        log("incremental sync cycle failed", error=repr(exc))
    payload = {
        "schema_version": "pvrig.top5000_multimodal_4seed.incremental_sync.v1",
        "updated_at_utc": now(),
        "expected_jobs": EXPECTED_JOBS,
        "bxcpu_result_root": BXCPU_RESULT_ROOT,
        "local_root": str(LOCAL_ROOT),
        "node1_result_root": NODE1_ROOT,
        "batch_size": BATCH_SIZE,
        "stable_age_seconds": STABLE_AGE_SECONDS,
        "max_local_spool_bytes": MAX_LOCAL_SPOOL_BYTES,
        "minimum_local_free_bytes": MIN_LOCAL_FREE_BYTES,
        "sync_shard_count": SHARD_COUNT,
        "sync_shard_index": SHARD_INDEX,
        "summary": summary,
    }
    atomic_json(LOCAL_ROOT / "state" / f"SYNC_STATUS.{SHARD_TAG}.json", payload)
    log("incremental sync cycle complete", summary=summary)
    return success


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    validate_configuration()
    (LOCAL_ROOT / "state").mkdir(parents=True, exist_ok=True)
    lock_handle = (LOCAL_ROOT / "state" / f"sync.{SHARD_TAG}.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another sync process owns the shard lock", file=sys.stderr)
        return 0
    while True:
        success = cycle()
        if args.once:
            return 0 if success else 2
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
