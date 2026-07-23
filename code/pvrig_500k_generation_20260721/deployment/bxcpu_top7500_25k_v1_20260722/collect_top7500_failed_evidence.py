#!/usr/bin/env python3
"""Archive exact-protocol technical failures before Slurm node scratch disappears."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
import tarfile
import time
from typing import Any


SSH = "/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe"
ARRAY_JOB = "11942310"
PROJECT = "pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722"
REMOTE_RESULTS = f"{PROJECT}_bxcpu_results"
NODE1_PACKAGE = pathlib.PurePosixPath("/data1/qlyu/projects") / PROJECT
NODE1_RESULTS = pathlib.PurePosixPath(
    "/data1/qlyu/projects/"
    "pvrig_priority_top7500_dualreceptor_multiseed_docking_results_v1_20260722/"
    "top7500_25k"
)
LOCAL_ROOT = pathlib.Path(
    "/mnt/d/work/抗体/node1/"
    "pvrig_top7500_25k_bxcpu_incremental_spool_20260722/monitor/failed_evidence"
)
DEPLOY = pathlib.Path(__file__).resolve().parent
SAFE_JOB = re.compile(r"[A-Za-z0-9_.-]+")


def run(command: list[str], *, input_text: str | None = None, timeout: int = 300) -> str:
    result = subprocess.run(
        command,
        input=input_text,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed rc={result.returncode}: {' '.join(command)}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def run_retry(
    command: list[str],
    *,
    attempts: int = 3,
    timeout: int = 120,
) -> str:
    """Retry bounded transfers instead of blocking the health loop indefinitely."""

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return run(command, timeout=timeout)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(5 * attempt)
    assert last_error is not None
    raise last_error


def ssh(host: str, command: str, *, input_text: str | None = None, timeout: int = 300) -> str:
    return run(
        [SSH, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, command],
        input_text=input_text,
        timeout=timeout,
    )


def failed_statuses() -> dict[str, dict[str, Any]]:
    code = r'''import json, pathlib
r=pathlib.Path.home()/"''' + REMOTE_RESULTS + r'''"/"status/jobs"
for p in sorted(r.glob("*.json")):
    try: d=json.load(open(str(p)))
    except Exception: continue
    if "FAIL" in str(d.get("status")): print(json.dumps(d,sort_keys=True))
'''
    output = ssh("bxcpu", "python3 -c " + shlex.quote(code))
    statuses = {}
    for line in output.splitlines():
        if line.strip():
            payload = json.loads(line)
            statuses[payload["job_id"]] = payload
    return statuses


def node1_evidence() -> set[str]:
    code = (
        "from pathlib import Path; "
        f"p=Path({str(NODE1_RESULTS / 'failed_evidence')!r}); "
        "print('\\n'.join(sorted(x.stem.replace('.tar','') for x in p.glob('*.tar.gz'))))"
    )
    return {
        line.strip()
        for line in ssh(
            "node1", "python3 -c " + shlex.quote(code), timeout=30
        ).splitlines()
        if line.strip()
    }


def shard_index(job_id: str) -> int:
    code = r'''import pathlib,sys
job=sys.argv[1]
root=pathlib.Path(sys.argv[2])/"manifests/shards_recommended_8"
for p in sorted(root.glob("shard_*.tsv")):
    with p.open() as h:
        if any(line.startswith(job+"\t") for line in h):
            print(int(p.stem.rsplit("_",1)[1])); raise SystemExit(0)
raise SystemExit(2)
'''
    try:
        output = ssh(
            "node1",
            "python3 -c " + shlex.quote(code) + " " + shlex.quote(job_id) + " " + shlex.quote(str(NODE1_PACKAGE)),
            timeout=30,
        )
        return int(output.strip())
    except Exception:
        # Node1 may be temporarily unreachable.  The live Slurm tasks retain
        # the exact failed-attempt directory, so locate its owning task there
        # rather than postponing evidence capture until the scratch vanishes.
        fallback = f'''set -euo pipefail
J={shlex.quote(job_id)}
P={shlex.quote(PROJECT)}
for task in 1 2 3 4 5 6 7 8; do
    if srun --jobid={ARRAY_JOB}_$task --overlap --nodes=1 --ntasks=1 \
        bash -lc "test -d /tmp/\\$USER/$P/{ARRAY_JOB}_$task/$P/failed_attempts/$J" \
        >/dev/null 2>&1; then
        echo $((task-1))
        exit 0
    fi
done
exit 2
'''
        return int(ssh("bxcpu", fallback, timeout=120).strip())


def create_remote_archive(job_id: str, task: int) -> str:
    inner = f'''set -euo pipefail
J={shlex.quote(job_id)}
B=/tmp/$USER/{PROJECT}/{ARRAY_JOB}_{task}
P="$B/{PROJECT}"
R="$HOME/{REMOTE_RESULTS}"
test -d "$P/failed_attempts/$J"
test -d "$B/job-scratch/$J"
mkdir -p "$R/failed_evidence"
T="$R/failed_evidence/.$J.tar.gz.partial.$SLURM_JOB_ID.$$"
tar -czf "$T" -C "$P" "failed_attempts/$J" "status/jobs/$J.json" -C "$B" "job-scratch/$J"
tar -tzf "$T" >/dev/null
mv -f "$T" "$R/failed_evidence/$J.tar.gz"
sha256sum "$R/failed_evidence/$J.tar.gz"
'''
    command = (
        f"srun --jobid={ARRAY_JOB}_{task} --overlap --nodes=1 --ntasks=1 "
        "bash -s"
    )
    return ssh("bxcpu", command, input_text=inner, timeout=300)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def diagnostic_tail(archive: pathlib.Path) -> list[str]:
    lines: list[str] = []
    with tarfile.open(archive, "r:gz") as tar:
        names = [
            member
            for member in tar.getmembers()
            if member.isfile() and member.name.endswith("haddock.stdout.log")
        ]
        for member in names:
            handle = tar.extractfile(member)
            if handle is None:
                continue
            text = handle.read().decode(errors="replace")
            relevant = [
                line.strip()
                for line in text.splitlines()
                if "ERROR" in line or "RuntimeError" in line
            ]
            lines.extend(relevant[-8:])
    return lines[-16:]


def validate_archive(archive: pathlib.Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        if not tar.getmembers():
            raise RuntimeError(f"empty failure archive: {archive}")


def download_remote_archive(job_id: str) -> pathlib.Path:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    archive = LOCAL_ROOT / f"{job_id}.tar.gz"
    if archive.is_file():
        validate_archive(archive)
        return archive
    run_retry(
        [
            "rsync", "-a", "--partial", "--timeout=60", "-e", SSH,
            f"bxcpu:{REMOTE_RESULTS}/failed_evidence/{job_id}.tar.gz",
            str(LOCAL_ROOT) + "/",
        ],
        timeout=120,
    )
    validate_archive(archive)
    return archive


def write_pending_receipt(
    job_id: str,
    status: dict[str, Any],
    shard: int,
    archive: pathlib.Path,
    error: str,
) -> None:
    pending_dir = LOCAL_ROOT / "pending_receipts"
    pending_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "pvrig_top7500_pending_technical_failure_v1",
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "job_id": job_id,
        "array_task": shard + 1,
        "status": status,
        "label": "NA_TECHNICAL_FAILURE",
        "protocol_changed": False,
        "evidence_sha256": sha256(archive),
        "evidence_bytes": archive.stat().st_size,
        "local_evidence": str(archive),
        "diagnostic_tail": diagnostic_tail(archive),
        "node1_delivery": "PENDING_NODE1_UNREACHABLE",
        "delivery_error": error,
    }
    (pending_dir / f"{job_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def relay(job_id: str, status: dict[str, Any], shard: int) -> dict[str, Any]:
    archive = download_remote_archive(job_id)
    digest = sha256(archive)
    ssh("node1", f"mkdir -p {shlex.quote(str(NODE1_RESULTS / 'failed_evidence'))} {shlex.quote(str(NODE1_RESULTS.parent / 'run_control/technical_failures'))}")
    run_retry(
        [
            "rsync", "-a", "--partial", "--timeout=60", "-e", SSH, str(archive),
            f"node1:{NODE1_RESULTS}/failed_evidence/",
        ],
        timeout=120,
    )
    remote_sha = ssh("node1", f"sha256sum {shlex.quote(str(NODE1_RESULTS / 'failed_evidence' / archive.name))}").split()[0]
    if remote_sha != digest:
        raise RuntimeError(f"Node1 failure evidence SHA mismatch for {job_id}")
    receipt = {
        "schema_version": "pvrig_top7500_technical_failure_receipt_v1",
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "job_id": job_id,
        "array_task": shard + 1,
        "status": status,
        "label": "NA_TECHNICAL_FAILURE",
        "protocol_changed": False,
        "evidence_sha256": digest,
        "evidence_bytes": archive.stat().st_size,
        "node1_evidence": str(NODE1_RESULTS / "failed_evidence" / archive.name),
        "diagnostic_tail": diagnostic_tail(archive),
    }
    receipt_dir = LOCAL_ROOT / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{job_id}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    run_retry(
        [
            "rsync", "-a", "--timeout=60", "-e", SSH, str(receipt_path),
            f"node1:{NODE1_RESULTS.parent}/run_control/technical_failures/",
        ],
        timeout=120,
    )
    code = (
        "from pathlib import Path; "
        f"p=Path.home()/{REMOTE_RESULTS!r}/'failed_evidence'/{archive.name!r}; "
        "p.unlink() if p.exists() else None"
    )
    ssh("bxcpu", "python3 -c " + shlex.quote(code))
    pending = LOCAL_ROOT / "pending_receipts" / f"{job_id}.json"
    pending.unlink(missing_ok=True)
    return receipt


def update_aggregate(receipts: list[dict[str, Any]]) -> None:
    path = DEPLOY / "TECHNICAL_FAILURES_V1.json"
    current = json.loads(path.read_text()) if path.is_file() else {"failures": []}
    by_id = {item["job_id"]: item for item in current.get("failures", [])}
    for receipt in receipts:
        by_id[receipt["job_id"]] = {
            "job_id": receipt["job_id"],
            "attempts": receipt["status"].get("attempts"),
            "stage": receipt["status"].get("stage"),
            "error": receipt["status"].get("error"),
            "label": receipt["label"],
            "protocol_changed": receipt["protocol_changed"],
            "node1_evidence": receipt["node1_evidence"],
            "evidence_sha256": receipt["evidence_sha256"],
            "diagnostic_tail": receipt["diagnostic_tail"],
        }
    payload = {
        "schema_version": "pvrig_top7500_technical_failures_v1",
        "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "failure_semantics": "Technical failures are NA and are never negative Docking labels.",
        "protocol_changed": False,
        "failures": [by_id[key] for key in sorted(by_id)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    run_retry(
        [
            "rsync", "-a", "--timeout=60", "-e", SSH, str(path),
            f"node1:{NODE1_RESULTS.parent}/run_control/TECHNICAL_FAILURES_V1.json",
        ],
        timeout=120,
    )


def locally_recorded_deliveries() -> set[str]:
    path = DEPLOY / "TECHNICAL_FAILURES_V1.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text())
        return {item["job_id"] for item in payload.get("failures", [])}
    except Exception:
        return set()


def main() -> int:
    statuses = failed_statuses()
    try:
        existing = node1_evidence()
        node1_available = True
        node1_error = ""
    except Exception as exc:
        # This ledger is only updated after a hash-verified Node1 delivery, so
        # it is a safe offline substitute and avoids re-queuing old failures.
        existing = locally_recorded_deliveries()
        node1_available = False
        node1_error = repr(exc)
    collected: list[dict[str, Any]] = []
    pending: list[str] = []
    for job_id, status in statuses.items():
        if not SAFE_JOB.fullmatch(job_id):
            raise RuntimeError(f"unsafe job ID: {job_id!r}")
        if job_id in existing:
            (LOCAL_ROOT / "pending_receipts" / f"{job_id}.json").unlink(
                missing_ok=True
            )
            continue
        shard = shard_index(job_id)
        archive = LOCAL_ROOT / f"{job_id}.tar.gz"
        if not archive.is_file():
            create_remote_archive(job_id, shard + 1)
            archive = download_remote_archive(job_id)
        else:
            validate_archive(archive)
        if not node1_available:
            write_pending_receipt(job_id, status, shard, archive, node1_error)
            pending.append(job_id)
            continue
        try:
            collected.append(relay(job_id, status, shard))
        except Exception as exc:
            node1_available = False
            node1_error = repr(exc)
            write_pending_receipt(job_id, status, shard, archive, node1_error)
            pending.append(job_id)
    if node1_available:
        # Also refresh a previously completed local ledger after a transient
        # outage, even when this cycle had no newly delivered failures.
        update_aggregate(collected)
    print(json.dumps({
        "failed": len(statuses),
        "newly_delivered_to_node1": len(collected),
        "pending_node1_delivery": len(pending),
        "node1_available": node1_available,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
