#!/usr/bin/env python3
"""Fail-closed remainder-only recovery for the frozen Node1 DeepQC100 run.

The controller never signals or resumes the old NFS process tree. It accepts
pre-existing TNP results only when the per-candidate command log binds the
expected ID and sequence to a successful frozen TNP invocation. Missing or
invalid candidates are recomputed on SSD, summaries are rebuilt with the
frozen vhh_screen implementation, and IgFold is launched once over all 100
candidates before an immutable content-addressed SSD delivery is published.
NFS synchronization is deliberately disabled because paused legacy processes
retain locks that prevent a provable writer-exclusion transaction.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable


BASE = Path("/data1/qlyu/pvrig_migration_20260716")
SSD_ROOT = Path("/data1/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716")
NFS_ROOT = Path("/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716")
TOOLS = Path("/data1/qlyu/software/vhh_eval_tools")
EVAL_PYTHON = Path("/data1/qlyu/software/envs/vhh-eval/bin/python")
IGFOLD_PYTHON = Path("/data1/qlyu/software/envs/vhh-igfold/bin/python")
RECOVERY = BASE / "deepqc_recovery_v1"
FROZEN = BASE / "frozen_recovery_v1"
FROZEN_REUSE = FROZEN / "FROZEN_TNP_REUSE64_V1.tsv"
FROZEN_RERUN = FROZEN / "FROZEN_TNP_RERUN36_V1.tsv"
FROZEN_PROCESSES = FROZEN / "FROZEN_NFS_PROCESS_IDENTITY_V1.tsv"
FROZEN_PARTITION = FROZEN / "FROZEN_RECOVERY_PARTITION_V1.json"

EXPECTED_FASTA_SHA256 = "57245f7ed52d633209d67a59dbc809118bbb06042f54b68dcf29cb3e35182eb0"
EXPECTED_TSV_SHA256 = "2701d5ab43677b3e302924ddc3454639fce1a8a9f8d6102713d6df24156173b5"
EXPECTED_REUSE_MANIFEST_SHA256 = "d4edbb0c703abf0fe8ee0e06080fa426e80a19f354e6340a96e4a26060283b28"
EXPECTED_RERUN_MANIFEST_SHA256 = "9d45525ce3810900e3f6d1018520fd41ee4a13771b7e2687c5f25f6edb4b6fdb"
EXPECTED_PROCESS_MANIFEST_SHA256 = "d93b8673ada7dab23dcd49d5cd013ba473878a3ec3d5e3189180e3007ad05095"
EXPECTED_PARTITION_JSON_SHA256 = "00edc30eaba71a70d4195cda3964d8c596d36fec43be34d7f7a8cc34ae94a0e0"
EXPECTED_CANDIDATES = 100
TNP_CHUNKS = 8
IGFOLD_CHUNKS = 4
TNP_NCORES = 4
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
REQUIRED_TNP_KEYS = {
    "name", "Total CDR Length", "CDR3 Length", "CDR3 Compactness",
    "PSH", "PPC", "PNC", "Flags",
}
REQUIRED_TNP_FLAGS = {"L", "L3", "C", "PSH", "PPC", "PNC"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with tmp.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode)


def atomic_write_json(path: Path, value: Any, mode: int = 0o644) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n", mode)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.tmp.", delete=False) as handle:
        tmp = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    fsync_dir(path.parent)


def tsv_bytes(rows: list[dict[str, Any]], fields: list[str] | None = None) -> bytes:
    if fields is None:
        fields = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode()


def exclusive_write_bytes(path: Path, raw: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchmod(fd, mode)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def parse_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    name: str | None = None
    parts: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(parts).upper()))
            name = line[1:].split()[0]
            parts = []
        else:
            if name is None:
                raise ValueError(f"sequence before FASTA header: {path}")
            parts.append(line)
    if name is not None:
        records.append((name, "".join(parts).upper()))
    ids = [name for name, _ in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate FASTA IDs: {path}")
    for cid, sequence in records:
        invalid = sorted(set(sequence) - STANDARD_AA)
        if invalid:
            raise ValueError(f"non-standard residues for {cid}: {invalid}")
    return records


def load_frozen_partition(expected: dict[str, str] | None = None) -> dict[str, Any]:
    required = {
        FROZEN_REUSE: EXPECTED_REUSE_MANIFEST_SHA256,
        FROZEN_RERUN: EXPECTED_RERUN_MANIFEST_SHA256,
        FROZEN_PROCESSES: EXPECTED_PROCESS_MANIFEST_SHA256,
        FROZEN_PARTITION: EXPECTED_PARTITION_JSON_SHA256,
    }
    for path, digest in required.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"frozen recovery artifact hash mismatch: {path}")
    reuse_rows = read_tsv(FROZEN_REUSE)
    rerun_rows = read_tsv(FROZEN_RERUN)
    process_rows = read_tsv(FROZEN_PROCESSES)
    summary = read_json(FROZEN_PARTITION)
    if len(reuse_rows) != 64 or len(rerun_rows) != 36:
        raise RuntimeError(f"frozen TNP partition count mismatch: {len(reuse_rows)}/{len(rerun_rows)}")
    reuse = {row["candidate_id"]: row for row in reuse_rows}
    rerun = {row["candidate_id"]: row for row in rerun_rows}
    if len(reuse) != 64 or len(rerun) != 36 or set(reuse) & set(rerun):
        raise RuntimeError("frozen TNP partition contains duplicates or overlap")
    if expected is not None:
        if set(reuse) | set(rerun) != set(expected):
            raise RuntimeError("frozen TNP partition does not equal the exact input candidate set")
        for cid, row in {**reuse, **rerun}.items():
            if row["sequence"] != expected[cid] or row["sequence_sha256"] != sha256_bytes(expected[cid].encode()):
                raise RuntimeError(f"frozen sequence binding mismatch: {cid}")
    if summary.get("reuse_manifest_sha256") != EXPECTED_REUSE_MANIFEST_SHA256:
        raise RuntimeError("partition JSON reuse hash mismatch")
    if summary.get("rerun_manifest_sha256") != EXPECTED_RERUN_MANIFEST_SHA256:
        raise RuntimeError("partition JSON rerun hash mismatch")
    if summary.get("process_identity_manifest_sha256") != EXPECTED_PROCESS_MANIFEST_SHA256:
        raise RuntimeError("partition JSON process hash mismatch")
    return {"reuse": reuse, "rerun": rerun, "process_rows": process_rows, "summary": summary}


def tree_sha256(root: Path) -> tuple[str, int, int]:
    rows: list[bytes] = []
    count = 0
    total = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest = sha256_file(path)
        rows.append(f"{rel}\t{size}\t{digest}\n".encode())
        count += 1
        total += size
    return sha256_bytes(b"".join(rows)), count, total


def proc_info(pid: int) -> dict[str, Any] | None:
    proc = Path("/proc") / str(pid)
    try:
        raw_stat = (proc / "stat").read_text()
        after_comm = raw_stat[raw_stat.rfind(")") + 2:].split()
        state = after_comm[0]
        ppid = int(after_comm[1])
        starttime_ticks = int(after_comm[19])
        cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        try:
            cwd = os.readlink(proc / "cwd")
        except OSError:
            cwd = ""
        return {"pid": pid, "ppid": ppid, "state": state, "starttime_ticks": starttime_ticks,
                "cmdline": cmd, "cmdline_sha256": sha256_bytes(cmd.encode()),
                "cwd": cwd, "cwd_sha256": sha256_bytes(cwd.encode())}
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None


def old_nfs_process_guard() -> dict[str, Any]:
    try:
        frozen = load_frozen_partition()
    except Exception as exc:
        return {"status": "FAIL", "reason": f"frozen process identity unavailable: {exc}"}
    expected_rows = frozen["process_rows"]
    expected_by_pid = {int(row["pid"]): row for row in expected_rows}
    if len(expected_by_pid) != len(expected_rows):
        return {"status": "FAIL", "reason": "duplicate PID in frozen process identity manifest"}
    live: dict[int, dict[str, Any]] = {}
    for item in Path("/proc").iterdir():
        if item.name.isdigit():
            info = proc_info(int(item.name))
            if info is not None:
                live[int(item.name)] = info
    checked = []
    bad = []
    for pid, frozen_row in sorted(expected_by_pid.items()):
        observed = live.get(pid)
        required_state = "S" if frozen_row["guard_class"] == "QUIESCENT_PAUSE_SUPERVISOR" else "T"
        mismatches = []
        if observed is None:
            mismatches.append("pid_missing")
        else:
            exact = {
                "ppid": int(frozen_row["ppid"]),
                "starttime_ticks": int(frozen_row["starttime_ticks"]),
                "cmdline": frozen_row["cmdline"],
                "cmdline_sha256": frozen_row["cmdline_sha256"],
                "cwd": frozen_row["cwd"],
                "cwd_sha256": frozen_row["cwd_sha256"],
            }
            for key, value in exact.items():
                if observed[key] != value:
                    mismatches.append(f"{key}_mismatch")
            if observed["state"] != required_state:
                mismatches.append(f"state_expected_{required_state}_observed_{observed['state']}")
        row = {"pid": pid, "guard_class": frozen_row["guard_class"],
               "root_pid": int(frozen_row["root_pid"]), "required_state": required_state,
               "observed": observed or {}, "mismatches": mismatches}
        checked.append(row)
        if mismatches:
            bad.append(row)

    frozen_tree = [row for row in expected_rows if row["guard_class"] == "FROZEN_OLD_PROCESS_TREE"]
    roots = sorted({int(row["root_pid"]) for row in frozen_tree})
    descendant_mismatches = []
    for root in roots:
        observed = {root}
        changed = True
        while changed:
            changed = False
            for pid, info in live.items():
                if info["ppid"] in observed and pid not in observed:
                    observed.add(pid)
                    changed = True
        expected = {int(row["pid"]) for row in frozen_tree if int(row["root_pid"]) == root}
        if observed != expected:
            descendant_mismatches.append({
                "root_pid": root, "expected_pids": sorted(expected), "observed_pids": sorted(observed),
                "missing": sorted(expected - observed), "unexpected": sorted(observed - expected),
            })

    relevant_roots = [
        str(NFS_ROOT),
        "/data/qlyu/projects/pvrig_pre_shortlist100_structure_crosscheck_v1_20260716",
    ]
    unexpected = []
    for pid, info in live.items():
        relevant = any(
            root in info["cmdline"] or info["cwd"] == root or info["cwd"].startswith(root + "/")
            for root in relevant_roots
        )
        if relevant and pid not in expected_by_pid and info["state"] != "Z":
            unexpected.append(info)
    status = "PASS" if not bad and not descendant_mismatches and not unexpected else "FAIL"
    return {
        "status": status,
        "frozen_process_manifest_sha256": EXPECTED_PROCESS_MANIFEST_SHA256,
        "checked_processes": checked,
        "identity_or_state_failures": bad,
        "descendant_closure_failures": descendant_mismatches,
        "unexpected_deepqc_or_crosscheck_processes": unexpected,
    }


def check_marker(path: Path) -> tuple[str, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return "WAITING", f"missing marker {path}"
    return "PASS", sha256_file(path)


def build_candidate_index() -> tuple[dict[str, str], dict[str, str]]:
    records = parse_fasta(SSD_ROOT / "inputs/pre_shortlist100.fasta")
    expected = dict(records)
    if len(records) != EXPECTED_CANDIDATES or len(set(expected.values())) != EXPECTED_CANDIDATES:
        raise ValueError(f"expected 100 unique IDs and sequences, got {len(records)}/{len(set(expected.values()))}")
    chunks: dict[str, str] = {}
    for index in range(TNP_CHUNKS):
        tag = f"tnp_{index:02d}"
        chunk_records = parse_fasta(SSD_ROOT / "chunks" / f"{tag}.fasta")
        for cid, sequence in chunk_records:
            if cid in chunks:
                raise ValueError(f"candidate appears in multiple TNP chunks: {cid}")
            if expected.get(cid) != sequence:
                raise ValueError(f"chunk sequence mismatch: {cid}")
            chunks[cid] = tag
        run = SSD_ROOT / "runs" / tag
        vhh_rows = read_tsv(run / f"{tag}.vhh_eval.tsv")
        numbering_rows = read_json(run / f"{tag}.numbering.json")
        chunk_ids = [cid for cid, _ in chunk_records]
        vhh_ids = [row["id"] for row in vhh_rows]
        numbering_ids = [row["id"] for row in numbering_rows]
        if set(vhh_ids) != set(chunk_ids) or len(vhh_ids) != len(set(vhh_ids)):
            raise ValueError(f"vhh_eval closure failed for {tag}")
        if set(numbering_ids) != set(chunk_ids) or len(numbering_ids) != len(set(numbering_ids)):
            raise ValueError(f"numbering closure failed for {tag}")
    if set(chunks) != set(expected) or len(chunks) != EXPECTED_CANDIDATES:
        raise ValueError("TNP chunk closure does not match input FASTA")
    return expected, chunks


def validate_exact_partition(
    expected: dict[str, str],
    partitions: dict[str, list[tuple[str, str]]],
    expected_partition_count: int,
    expected_total: int,
) -> dict[str, str]:
    if len(partitions) != expected_partition_count:
        raise RuntimeError(f"partition file count mismatch: {len(partitions)} != {expected_partition_count}")
    observed: dict[str, str] = {}
    duplicates: list[str] = []
    for tag, records in sorted(partitions.items()):
        if not records:
            raise RuntimeError(f"empty partition: {tag}")
        for cid, sequence in records:
            if cid in observed:
                duplicates.append(cid)
            observed[cid] = sequence
            if expected.get(cid) != sequence:
                raise RuntimeError(f"partition ID/sequence binding mismatch: {tag}:{cid}")
    if duplicates:
        raise RuntimeError(f"cross-partition duplicate candidates: {sorted(set(duplicates))}")
    if len(observed) != expected_total or set(observed) != set(expected):
        raise RuntimeError(
            f"partition candidate-set closure failed: rows={sum(len(v) for v in partitions.values())} "
            f"unique={len(observed)} missing={sorted(set(expected) - set(observed))} "
            f"unexpected={sorted(set(observed) - set(expected))}"
        )
    return observed


def validate_igfold_chunk_partition(expected: dict[str, str]) -> dict[str, str]:
    partitions = {
        f"igfold_{index:02d}": parse_fasta(SSD_ROOT / "chunks" / f"igfold_{index:02d}.fasta")
        for index in range(IGFOLD_CHUNKS)
    }
    if any(len(records) != 25 for records in partitions.values()):
        raise RuntimeError(f"IgFold chunks must each contain 25 candidates: "
                           f"{ {tag: len(records) for tag, records in partitions.items()} }")
    return validate_exact_partition(expected, partitions, IGFOLD_CHUNKS, EXPECTED_CANDIDATES)


def command_value(tokens: list[str], flag: str) -> str:
    positions = [index for index, token in enumerate(tokens) if token == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(tokens):
        raise ValueError(f"expected one {flag}")
    return tokens[positions[0] + 1]


def validate_tnp_candidate(cid: str, sequence: str, chunk: str, origin: str) -> dict[str, Any]:
    if origin == "ORIGINAL_SSD_SNAPSHOT":
        run = SSD_ROOT / "runs" / chunk
    elif origin == "SSD_RECOVERY_RERUN":
        run = RECOVERY / "tnp_rerun" / "runs" / cid
    else:
        raise ValueError(origin)
    command_log = run / "logs" / f"tnp_{cid}.log"
    candidate_dir = run / "layer3_tnp" / cid
    result_json = candidate_dir / f"TNP_Results_SingleSeqEntry_{cid}.json"
    native_log = candidate_dir / f"{cid}_TNP.log"
    required_files = [
        candidate_dir / "Final_Models" / f"{cid}_NanoBodyBuilder2_Model.pdb",
        candidate_dir / "Final_Models" / f"{cid}_NanoBodyBuilder2_Model_Annotated.pdb",
        candidate_dir / "Final_Models" / f"{cid}_NanoBodyBuilder2_Sequence_Liabilities.json",
    ]
    row: dict[str, Any] = {
        "candidate_id": cid, "chunk": chunk, "origin": origin,
        "sequence_sha256": sha256_bytes(sequence.encode()),
        "status": "INVALID", "reason": "",
        "command_log": str(command_log), "command_log_sha256": "",
        "result_json": str(result_json), "result_json_sha256": "",
        "native_log": str(native_log), "native_log_sha256": "",
        "candidate_tree_sha256": "", "candidate_tree_files": 0, "candidate_tree_bytes": 0,
    }
    reasons: list[str] = []
    if not command_log.is_file() or command_log.stat().st_size == 0:
        reasons.append("command_log_missing_or_empty")
    else:
        row["command_log_sha256"] = sha256_file(command_log)
        text = command_log.read_text(errors="replace")
        lines = text.splitlines()
        try:
            if not lines or not lines[0].startswith("$ "):
                raise ValueError("command prefix missing")
            tokens = shlex.split(lines[0][2:])
            if Path(tokens[0]).name != "TNP":
                raise ValueError("executable is not TNP")
            if command_value(tokens, "--seq") != sequence:
                raise ValueError("sequence mismatch")
            if command_value(tokens, "--name") != cid:
                raise ValueError("candidate ID mismatch")
            if int(command_value(tokens, "--ncores")) != TNP_NCORES:
                raise ValueError("ncores mismatch")
            output = Path(command_value(tokens, "--output"))
            if output.name != cid or output.parent.name != "layer3_tnp":
                raise ValueError("output binding mismatch")
            if origin == "ORIGINAL_SSD_SNAPSHOT" and f"/runs/{chunk}/layer3_tnp/{cid}" not in str(output):
                raise ValueError("original chunk output binding mismatch")
            if origin == "SSD_RECOVERY_RERUN" and str(output) != str(candidate_dir):
                raise ValueError("rerun output path mismatch")
            if not re.search(r"\[exit_code\] 0\s*$", text):
                raise ValueError("successful terminal exit marker missing")
        except Exception as exc:
            reasons.append(f"command_binding:{exc}")
    if not result_json.is_file() or result_json.stat().st_size == 0:
        reasons.append("result_json_missing_or_empty")
    else:
        row["result_json_sha256"] = sha256_file(result_json)
        try:
            data = read_json(result_json)
            if set(data) != {cid}:
                raise ValueError(f"top-level keys={sorted(data)}")
            payload = data[cid]
            if not isinstance(payload, dict) or payload.get("name") != cid:
                raise ValueError("payload name mismatch")
            missing = sorted(REQUIRED_TNP_KEYS - set(payload))
            if missing:
                raise ValueError(f"missing keys={missing}")
            flags = payload.get("Flags")
            if not isinstance(flags, dict) or not REQUIRED_TNP_FLAGS.issubset(flags):
                raise ValueError("incomplete Flags")
            for key in ("Total CDR Length", "CDR3 Length", "CDR3 Compactness", "PSH", "PPC", "PNC"):
                float(payload[key])
        except Exception as exc:
            reasons.append(f"result_json_invalid:{exc}")
    if not native_log.is_file() or native_log.stat().st_size == 0:
        reasons.append("native_tnp_log_missing_or_empty")
    else:
        row["native_log_sha256"] = sha256_file(native_log)
        if f"Summary Statistics for {cid}:" not in native_log.read_text(errors="replace"):
            reasons.append("native_tnp_log_summary_missing")
    for path in required_files:
        if not path.is_file() or path.stat().st_size == 0:
            reasons.append(f"required_artifact_missing:{path.name}")
    if candidate_dir.is_dir():
        digest, count, size = tree_sha256(candidate_dir)
        row.update(candidate_tree_sha256=digest, candidate_tree_files=count, candidate_tree_bytes=size)
    if not reasons:
        row["status"] = "VALID"
        row["reason"] = "id_sequence_command_exit_json_and_artifact_hash_binding_pass"
    else:
        row["reason"] = ";".join(reasons)
    return row


def inventory_tnp(write_prefix: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    expected, chunks = build_candidate_index()
    frozen = load_frozen_partition(expected)
    rows: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rerun: list[dict[str, Any]] = []
    for cid, sequence in expected.items():
        original = validate_tnp_candidate(cid, sequence, chunks[cid], "ORIGINAL_SSD_SNAPSHOT")
        recovery = validate_tnp_candidate(cid, sequence, chunks[cid], "SSD_RECOVERY_RERUN")
        if cid in frozen["reuse"]:
            frozen_row = frozen["reuse"][cid]
            expected_fields = {
                "command_log_sha256": frozen_row["command_log_sha256"],
                "result_json_sha256": frozen_row["result_json_sha256"],
                "native_log_sha256": frozen_row["native_log_sha256"],
                "candidate_tree_sha256": frozen_row["candidate_tree_sha256"],
                "candidate_tree_files": frozen_row["candidate_tree_files"],
                "candidate_tree_bytes": frozen_row["candidate_tree_bytes"],
            }
            mismatches = [key for key, value in expected_fields.items() if str(original[key]) != value]
            if original["status"] != "VALID" or mismatches:
                raise RuntimeError(f"frozen reuse candidate drift: {cid}: {mismatches or original['reason']}")
            if recovery["status"] == "VALID":
                raise RuntimeError(f"frozen reuse candidate has an unauthorized rerun output: {cid}")
            selected = original
            frozen_class = "REUSE64"
        else:
            frozen_row = frozen["rerun"][cid]
            expected_fields = {
                "reason": frozen_row["frozen_reason"],
                "command_log_sha256": frozen_row["observed_command_log_sha256"],
                "result_json_sha256": frozen_row["observed_result_json_sha256"],
                "native_log_sha256": frozen_row["observed_native_log_sha256"],
                "candidate_tree_sha256": frozen_row["observed_candidate_tree_sha256"],
            }
            mismatches = [key for key, value in expected_fields.items() if str(original[key]) != value]
            if original["status"] != "INVALID" or mismatches:
                raise RuntimeError(f"frozen rerun-complement candidate drift: {cid}: {mismatches or original['status']}")
            selected = recovery if recovery["status"] == "VALID" else None
            frozen_class = "RERUN36"
        row = {
            "candidate_id": cid, "sequence": sequence, "chunk": chunks[cid],
            "sequence_sha256": sha256_bytes(sequence.encode()),
            "frozen_partition_class": frozen_class,
            "decision": "ACCEPT_" + selected["origin"] if selected else "RERUN_REQUIRED",
            "selected_origin": selected["origin"] if selected else "",
            "selected_command_log": selected["command_log"] if selected else "",
            "selected_command_log_sha256": selected["command_log_sha256"] if selected else "",
            "selected_result_json": selected["result_json"] if selected else "",
            "selected_result_json_sha256": selected["result_json_sha256"] if selected else "",
            "selected_candidate_tree_sha256": selected["candidate_tree_sha256"] if selected else "",
            "original_status": original["status"], "original_reason": original["reason"],
            "recovery_status": recovery["status"], "recovery_reason": recovery["reason"],
        }
        rows.append(row)
        (accepted if selected else rerun).append(row)
    if write_prefix is not None:
        write_tsv(RECOVERY / f"{write_prefix}_tnp_inventory.tsv", rows)
        write_tsv(RECOVERY / f"{write_prefix}_tnp_accepted_manifest.tsv", accepted)
        write_tsv(RECOVERY / f"{write_prefix}_tnp_rerun_plan.tsv", rerun)
        atomic_write_json(RECOVERY / f"{write_prefix}_tnp_inventory.json", {
            "schema_version": "pvrig_node1_ssd_tnp_inventory_v1",
            "created_at": utc_now(), "candidate_count": len(rows),
            "accepted_count": len(accepted), "rerun_required_count": len(rerun),
            "accepted_original_count": sum(r["selected_origin"] == "ORIGINAL_SSD_SNAPSHOT" for r in accepted),
            "accepted_recovery_count": sum(r["selected_origin"] == "SSD_RECOVERY_RERUN" for r in accepted),
            "frozen_reuse_manifest_sha256": EXPECTED_REUSE_MANIFEST_SHA256,
            "frozen_rerun_manifest_sha256": EXPECTED_RERUN_MANIFEST_SHA256,
            "inventory_sha256": sha256_file(RECOVERY / f"{write_prefix}_tnp_inventory.tsv"),
            "status": "PASS" if len(rows) == EXPECTED_CANDIDATES else "FAIL",
        })
    return rows, accepted, rerun


def freeze_final_inventory(rows: list[dict[str, Any]]) -> Path:
    if len(rows) != EXPECTED_CANDIDATES or len({row["candidate_id"] for row in rows}) != EXPECTED_CANDIDATES:
        raise RuntimeError("cannot freeze a non-closed TNP final inventory")
    if any(not row["selected_result_json_sha256"] or not row["selected_candidate_tree_sha256"] for row in rows):
        raise RuntimeError("cannot freeze TNP inventory with unbound selected artifacts")
    raw = tsv_bytes(rows)
    digest = sha256_bytes(raw)
    snapshots = RECOVERY / "immutable_snapshots"
    snapshot = snapshots / f"tnp_final_inventory_{digest}.tsv"
    if snapshot.exists():
        if snapshot.read_bytes() != raw:
            raise RuntimeError(f"immutable snapshot path collision: {snapshot}")
    else:
        exclusive_write_bytes(snapshot, raw, 0o444)
    pointer = {
        "schema_version": "pvrig_node1_ssd_tnp_final_snapshot_v1",
        "status": "FROZEN_IMMUTABLE",
        "candidate_count": EXPECTED_CANDIDATES,
        "snapshot_path": str(snapshot),
        "snapshot_sha256": digest,
        "frozen_reuse_manifest_sha256": EXPECTED_REUSE_MANIFEST_SHA256,
        "frozen_rerun_manifest_sha256": EXPECTED_RERUN_MANIFEST_SHA256,
    }
    pointer_raw = (json.dumps(pointer, indent=2, sort_keys=True) + "\n").encode()
    pointer_path = snapshots / f"tnp_final_snapshot_{sha256_bytes(pointer_raw)}.json"
    if pointer_path.exists():
        if pointer_path.read_bytes() != pointer_raw:
            raise RuntimeError(f"immutable snapshot pointer collision: {pointer_path}")
    else:
        exclusive_write_bytes(pointer_path, pointer_raw, 0o444)
    return snapshot


def finalizer_stages() -> tuple[str, dict[str, str]]:
    path = BASE / "finalizer_status.tsv"
    if not path.is_file() or path.stat().st_size == 0:
        return "WAITING", {}
    latest: dict[str, str] = {}
    for row in read_tsv(path):
        latest[row["stage"]] = row["status"]
    required = {"parity", "relocate", "import_smoke", "tnp_smoke", "igfold_smoke"}
    if any(latest.get(stage) not in {None, "RUNNING", "COMPLETE"} for stage in required):
        return "FAIL", latest
    return ("PASS" if all(latest.get(stage) == "COMPLETE" for stage in required) else "WAITING"), latest


def validate_smokes() -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {}
    try:
        for name in ("eval_import_smoke.json", "igfold_import_smoke.json"):
            data = read_json(BASE / name)
            if not data or any(not str(value).startswith("/data1/") for value in data.values()):
                raise ValueError(f"invalid {name}")
            details[name] = sha256_file(BASE / name)
        tnp_run = SSD_ROOT / "runs/ssd_migration_smoke_tnp"
        tnp_rows = read_tsv(tnp_run / "screen_summary.tsv")
        tnp_json = list(tnp_run.glob("layer3_tnp/*/TNP_Results_SingleSeqEntry_*.json"))
        if len(tnp_rows) != 1 or len(tnp_json) != 1:
            raise ValueError("TNP smoke closure failed")
        json.loads(tnp_json[0].read_text())
        ig_run = SSD_ROOT / "runs/ssd_migration_smoke_igfold"
        ig_rows = read_tsv(ig_run / "screen_summary.tsv")
        ig_pdbs = list(ig_run.glob("structures/*/igfold.pdb"))
        if len(ig_rows) != 1 or len(ig_pdbs) != 1 or ig_pdbs[0].stat().st_size == 0:
            raise ValueError("IgFold smoke closure failed")
        details.update(tnp_smoke_rows=1, tnp_smoke_json=1, igfold_smoke_rows=1, igfold_smoke_pdb=1)
        return "PASS", details
    except FileNotFoundError as exc:
        return "WAITING", {"reason": str(exc)}
    except Exception as exc:
        return "FAIL", {"reason": str(exc)}


def run_checked(cmd: list[str], *, cwd: Path | None = None, log: Path | None = None,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    if log is None:
        return subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as handle:
        handle.write("$ " + shlex.join(cmd) + "\n\n")
        handle.flush()
        proc = subprocess.run(cmd, cwd=cwd, env=merged, text=True, stdout=handle, stderr=subprocess.STDOUT)
        handle.write(f"\n[controller_exit_code] {proc.returncode}\n")
    return proc


def preflight() -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for name in ("MIGRATION_COMPLETE", "RUNTIME_CLOSURE_COMPLETE", "SSD_SMOKE_PASS"):
        status, detail = check_marker(BASE / name)
        checks[name] = {"status": status, "detail": detail}
    stage_status, stage_detail = finalizer_stages()
    checks["finalizer_stages"] = {"status": stage_status, "detail": stage_detail}
    parity = BASE / "source_target_parity.json"
    if not parity.is_file():
        checks["source_target_parity"] = {"status": "WAITING", "detail": "missing"}
    else:
        try:
            data = read_json(parity)
            status = "PASS" if data.get("status") == "PASS" and not data.get("mismatches") else "FAIL"
            checks["source_target_parity"] = {"status": status, "detail": data,
                                               "sha256": sha256_file(parity)}
        except Exception as exc:
            checks["source_target_parity"] = {"status": "FAIL", "detail": str(exc)}
    smoke_status, smoke_detail = validate_smokes()
    checks["ssd_smokes"] = {"status": smoke_status, "detail": smoke_detail}
    checks["old_nfs_process_tree_stopped"] = old_nfs_process_guard()
    try:
        expected, chunks = build_candidate_index()
        frozen = load_frozen_partition(expected)
        checks["candidate_and_base_output_closure"] = {
            "status": "PASS", "candidate_count": len(expected), "chunk_binding_count": len(chunks),
            "frozen_reuse_count": len(frozen["reuse"]), "frozen_rerun_count": len(frozen["rerun"]),
            "frozen_partition_sha256": EXPECTED_PARTITION_JSON_SHA256}
        validate_igfold_chunk_partition(expected)
        checks["igfold_chunk_partition"] = {
            "status": "PASS", "chunk_count": IGFOLD_CHUNKS, "candidate_count": EXPECTED_CANDIDATES,
            "unique_candidate_count": EXPECTED_CANDIDATES, "exact_candidate_set": True}
    except Exception as exc:
        checks["candidate_and_base_output_closure"] = {"status": "FAIL", "detail": str(exc)}
        checks["igfold_chunk_partition"] = {"status": "FAIL", "detail": str(exc)}
    try:
        _, frozen_accepted, frozen_rerun = inventory_tnp(None)
        if len(frozen_accepted) != 64 or len(frozen_rerun) != 36:
            raise RuntimeError(f"expected frozen 64/36 snapshot, found {len(frozen_accepted)}/{len(frozen_rerun)}")
        checks["frozen_tnp_64_36_snapshot"] = {
            "status": "PASS", "reuse_count": 64, "rerun_count": 36,
            "reuse_manifest_sha256": EXPECTED_REUSE_MANIFEST_SHA256,
            "rerun_manifest_sha256": EXPECTED_RERUN_MANIFEST_SHA256,
        }
    except Exception as exc:
        checks["frozen_tnp_64_36_snapshot"] = {"status": "FAIL", "detail": str(exc)}
    try:
        if sha256_file(SSD_ROOT / "inputs/pre_shortlist100.fasta") != EXPECTED_FASTA_SHA256:
            raise ValueError("SSD FASTA hash mismatch")
        if sha256_file(SSD_ROOT / "inputs/pre_shortlist100.tsv") != EXPECTED_TSV_SHA256:
            raise ValueError("SSD TSV hash mismatch")
        if sha256_file(NFS_ROOT / "inputs/pre_shortlist100.fasta") != EXPECTED_FASTA_SHA256:
            raise ValueError("NFS FASTA hash mismatch")
        if sha256_file(NFS_ROOT / "inputs/pre_shortlist100.tsv") != EXPECTED_TSV_SHA256:
            raise ValueError("NFS TSV hash mismatch")
        config = read_json(SSD_ROOT / "deepqc_config.json")
        if config.get("input_fasta_sha256") != EXPECTED_FASTA_SHA256 or config.get("input_tsv_sha256") != EXPECTED_TSV_SHA256:
            raise ValueError("frozen config input hash mismatch")
        if config.get("tnp", {}).get("chunks") != TNP_CHUNKS or config.get("tnp", {}).get("cores_per_chunk") != TNP_NCORES:
            raise ValueError("frozen TNP config mismatch")
        if config.get("igfold", {}).get("chunks") != IGFOLD_CHUNKS or config.get("igfold", {}).get("gpus") != [0, 1, 2, 3]:
            raise ValueError("frozen IgFold config mismatch")
        checks["frozen_inputs_and_config"] = {"status": "PASS", "config_sha256": sha256_file(SSD_ROOT / "deepqc_config.json")}
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        checks["frozen_inputs_and_config"] = {"status": "WAITING", "detail": str(exc)}
    except Exception as exc:
        checks["frozen_inputs_and_config"] = {"status": "FAIL", "detail": str(exc)}
    try:
        required = [TOOLS / "bin/vhh-screen", TOOLS / "bin/TNP", TOOLS / "bin/igfold-predict",
                    EVAL_PYTHON, IGFOLD_PYTHON, TOOLS / "vhh_screen.py"]
        missing = [str(path) for path in required if not path.exists() or (path.name != "vhh_screen.py" and not os.access(path, os.X_OK))]
        if missing:
            raise FileNotFoundError(", ".join(missing))
        if "/data/qlyu/software" in (TOOLS / "vhh_screen.py").read_text(errors="replace"):
            raise ValueError("vhh_screen.py retains NFS software path after relocation")
        checks["ssd_tools"] = {"status": "PASS", "vhh_screen_sha256": sha256_file(TOOLS / "vhh_screen.py")}
    except FileNotFoundError as exc:
        checks["ssd_tools"] = {"status": "WAITING", "detail": str(exc)}
    except Exception as exc:
        checks["ssd_tools"] = {"status": "FAIL", "detail": str(exc)}
    try:
        if SSD_ROOT.resolve() != SSD_ROOT or NFS_ROOT.resolve() != NFS_ROOT:
            raise ValueError("project root is a symlink")
        if os.stat(SSD_ROOT).st_dev != os.stat("/data1").st_dev:
            raise ValueError("SSD root is not on /data1 device")
        free = shutil.disk_usage(SSD_ROOT).free
        if free < 50 * 1024**3:
            raise ValueError(f"less than 50 GiB free on SSD: {free}")
        checks["ssd_filesystem"] = {"status": "PASS", "free_bytes": free}
    except Exception as exc:
        checks["ssd_filesystem"] = {"status": "FAIL", "detail": str(exc)}
    existing_ig = [str(SSD_ROOT / "runs" / f"igfold_{index:02d}") for index in range(IGFOLD_CHUNKS)
                   if (SSD_ROOT / "runs" / f"igfold_{index:02d}").exists()]
    launch_marker = RECOVERY / "igfold_launch_frozen.json"
    checks["igfold_not_previously_launched"] = (
        {"status": "FAIL", "existing_paths": existing_ig, "launch_marker_exists": launch_marker.exists(),
         "detail": "exactly-once IgFold contract forbids an automatic relaunch"}
        if existing_ig or launch_marker.exists() else {"status": "PASS"})
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                              text=True, capture_output=True, timeout=20)
        indices = [int(line.strip()) for line in proc.stdout.splitlines() if line.strip().isdigit()]
        if proc.returncode != 0 or not {0, 1, 2, 3}.issubset(indices):
            raise ValueError(proc.stderr.strip() or f"GPU indices={indices}")
        checks["gpus_0_3"] = {"status": "PASS", "visible_indices": indices}
    except Exception as exc:
        checks["gpus_0_3"] = {"status": "FAIL", "detail": str(exc)}
    active = []
    for name in ("migration.pid", "runtime_closure.pid", "finalizer.pid"):
        path = BASE / name
        if path.is_file():
            try:
                pid = int(path.read_text().strip())
                info = proc_info(pid)
                if info is not None and info["state"] != "Z":
                    active.append({"pid": pid, "file": name, "state": info["state"],
                                   "starttime_ticks": info["starttime_ticks"],
                                   "cmdline": info["cmdline"]})
            except ValueError:
                active.append({"pid": "INVALID", "file": name})
    checks["migration_and_finalizer_exited"] = {"status": "PASS" if not active else "WAITING", "active": active}
    statuses = [value.get("status") for value in checks.values()]
    overall = "FAIL" if "FAIL" in statuses else ("PASS" if all(s == "PASS" for s in statuses) else "WAITING")
    result = {"schema_version": "pvrig_node1_ssd_recovery_preflight_v1", "created_at": utc_now(),
              "overall_status": overall, "checks": checks,
              "claim_boundary": "TNP and monomer structure QC only; no PVRIG binding, docking, or blocking claim."}
    RECOVERY.mkdir(parents=True, exist_ok=True)
    atomic_write_json(RECOVERY / "preflight_latest.json", result)
    return result


def set_status(state: str, phase: str, reason: str, extra: dict[str, Any] | None = None) -> None:
    if state == "COMPLETE":
        raise ValueError("recovery_status must never claim COMPLETE before the receipt-last commit")
    value: dict[str, Any] = {
        "schema_version": "pvrig_node1_ssd_recovery_status_v1", "status": state,
        "phase": phase, "reason": reason, "updated_at": utc_now(), "pid": os.getpid(),
        "receipt_pending": True,
        "terminal": False,
    }
    if extra:
        value.update(extra)
    atomic_write_json(RECOVERY / "recovery_status.json", value)


def commit_terminal_receipt(receipt: dict[str, Any]) -> None:
    receipt_path = RECOVERY / "ssd_recovery_receipt.json"
    if receipt_path.exists():
        raise RuntimeError("terminal receipt already exists")
    receipt_raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    receipt_sha = sha256_bytes(receipt_raw)
    # Phase 1 is explicitly non-terminal. Consumers must not treat status alone as success.
    atomic_write_json(RECOVERY / "recovery_status.json", {
        "schema_version": "pvrig_node1_ssd_recovery_status_v1",
        "status": "PREPARED_FOR_RECEIPT",
        "phase": "RECEIPT_COMMIT",
        "reason": "all work verified; terminal success exists only after receipt hash closure",
        "updated_at": utc_now(),
        "pid": os.getpid(),
        "receipt_pending": True,
        "terminal": False,
        "expected_receipt_path": str(receipt_path),
        "expected_receipt_sha256": receipt_sha,
    })
    # Phase 2: the immutable terminal receipt is the final successful filesystem write.
    exclusive_write_bytes(receipt_path, receipt_raw, 0o444)
    if sha256_file(receipt_path) != receipt_sha:
        raise RuntimeError("terminal receipt post-write hash mismatch")


def assert_guard() -> None:
    guard = old_nfs_process_guard()
    atomic_write_json(RECOVERY / "old_nfs_process_guard_latest.json", guard)
    if guard.get("status") != "PASS":
        raise RuntimeError(f"old NFS process guard failed: {guard}")


def run_tnp_remainder(rerun_rows: list[dict[str, Any]], expected: dict[str, str]) -> list[dict[str, Any]]:
    root = RECOVERY / "tnp_rerun"
    fasta_dir, run_dir, log_dir = root / "fasta", root / "runs", root / "controller_logs"
    for path in (fasta_dir, run_dir, log_dir):
        path.mkdir(parents=True, exist_ok=True)
    cache_home = BASE / "cache/home"
    torch_home = BASE / "cache/torch"
    hf_home = BASE / "cache/huggingface"
    for path in (cache_home, torch_home, hf_home):
        path.mkdir(parents=True, exist_ok=True)
    slots: queue.Queue[int] = queue.Queue()
    for slot in range(8):
        slots.put(slot)
    plan_rows = []
    for row in rerun_rows:
        cid, sequence = row["candidate_id"], expected[row["candidate_id"]]
        fasta = fasta_dir / f"{cid}.fasta"
        expected_text = f">{cid}\n{sequence}\n"
        if fasta.exists() and fasta.read_text() != expected_text:
            raise RuntimeError(f"existing recovery FASTA conflict: {cid}")
        if not fasta.exists():
            atomic_write_text(fasta, expected_text)
        output = run_dir / cid
        if output.exists():
            check = validate_tnp_candidate(cid, sequence, row["chunk"], "SSD_RECOVERY_RERUN")
            if check["status"] != "VALID":
                raise RuntimeError(f"invalid pre-existing rerun output; refuse overwrite: {cid}: {check['reason']}")
            continue
        plan_rows.append({"candidate_id": cid, "chunk": row["chunk"],
                          "sequence_sha256": sha256_bytes(sequence.encode()),
                          "fasta": str(fasta), "fasta_sha256": sha256_file(fasta),
                          "output": str(output), "tnp_ncores": TNP_NCORES})
    write_tsv(RECOVERY / "tnp_rerun_launch_manifest.tsv", plan_rows)
    atomic_write_json(RECOVERY / "tnp_rerun_launch_frozen.json", {
        "schema_version": "pvrig_node1_ssd_tnp_rerun_launch_v1", "created_at": utc_now(),
        "planned_count": len(plan_rows), "manifest_sha256": sha256_file(RECOVERY / "tnp_rerun_launch_manifest.tsv"),
        "semantics": ["--skip-abnativ", "--skip-sapiens", "--tnp-ncores", "4"],
        "maximum_concurrent_jobs": 8, "cpu_affinity": "0-31 in eight disjoint 4-core slots",
    })
    mutex = threading.Lock()
    results: list[dict[str, Any]] = []

    def worker(row: dict[str, Any]) -> dict[str, Any]:
        slot = slots.get()
        started, cid = utc_now(), row["candidate_id"]
        cpus = f"{slot * 4}-{slot * 4 + 3}"
        cmd = ["taskset", "-c", cpus, "env", "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1",
               "OPENBLAS_NUM_THREADS=1", f"HOME={cache_home}", f"TORCH_HOME={torch_home}",
               f"HF_HOME={hf_home}", str(TOOLS / "bin/vhh-screen"), row["fasta"],
               "-o", row["output"], "--prefix", "tnp_recovery", "--skip-abnativ",
               "--skip-sapiens", "--tnp-ncores", str(TNP_NCORES)]
        try:
            proc = run_checked(cmd, cwd=SSD_ROOT, log=log_dir / f"{cid}.log")
            result = {"candidate_id": cid, "cpu_affinity": cpus, "started_at": started,
                      "finished_at": utc_now(), "returncode": proc.returncode,
                      "command_sha256": sha256_bytes(shlex.join(cmd).encode()),
                      "controller_log": str(log_dir / f"{cid}.log"),
                      "controller_log_sha256": sha256_file(log_dir / f"{cid}.log")}
        finally:
            slots.put(slot)
        with mutex:
            results.append(result)
        return result

    if plan_rows:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for future in as_completed([pool.submit(worker, row) for row in plan_rows]):
                future.result()
    results.sort(key=lambda row: row["candidate_id"])
    write_tsv(RECOVERY / "tnp_rerun_results.tsv", results)
    failed = [row for row in results if row["returncode"] != 0]
    if failed:
        raise RuntimeError(f"TNP remainder jobs failed: {[row['candidate_id'] for row in failed]}")
    return results


def load_frozen_module():
    path = TOOLS / "vhh_screen.py"
    spec = importlib.util.spec_from_file_location("pvrig_frozen_vhh_screen", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def internal_reconstruct(inventory_path: Path, output_dir: Path) -> int:
    module = load_frozen_module()
    inventory = read_tsv(inventory_path)
    selected = {row["candidate_id"]: Path(row["selected_result_json"]) for row in inventory}
    if len(inventory) != EXPECTED_CANDIDATES or len(selected) != EXPECTED_CANDIDATES:
        raise RuntimeError("final inventory is not 100 unique candidates")
    for row in inventory:
        result_json = Path(row["selected_result_json"])
        if sha256_file(result_json) != row["selected_result_json_sha256"]:
            raise RuntimeError(f"snapshot-to-JSON hash detachment: {row['candidate_id']}")
        tree_digest, _, _ = tree_sha256(result_json.parent)
        if tree_digest != row["selected_candidate_tree_sha256"]:
            raise RuntimeError(f"snapshot-to-tree hash detachment: {row['candidate_id']}")
    candidates = module.read_candidates(SSD_ROOT / "inputs/pre_shortlist100.fasta")
    for index in range(TNP_CHUNKS):
        tag = f"tnp_{index:02d}"
        run = SSD_ROOT / "runs" / tag
        vhh_rows = module.read_tsv(run / f"{tag}.vhh_eval.tsv")
        numbering = {row["id"]: row["numbering"] for row in read_json(run / f"{tag}.numbering.json")}
        for cid, _ in parse_fasta(SSD_ROOT / "chunks" / f"{tag}.fasta"):
            candidate = candidates[cid]
            candidate.vhh_eval = vhh_rows[cid]
            candidate.numbering = numbering[cid]
            module.layer1_numbering_integrity(candidate)
    for candidate in candidates.values():
        if candidate.layer_status.get("L1") == "FAIL":
            raise RuntimeError(f"unexpected L1 failure in frozen Top100: {candidate.seq_id}")
        module.layer2_vhh_features(candidate)
        if candidate.layer_status.get("L2") == "FAIL":
            raise RuntimeError(f"unexpected L2 failure in frozen Top100: {candidate.seq_id}")
        candidate.tnp = read_json(selected[candidate.seq_id])[candidate.seq_id]
        module.layer3_developability(candidate)
        if candidate.layer_status.get("L3") == "FAIL":
            candidate.layer_status["L4"] = "SKIPPED"
            module.add_reason(candidate, "L4", "INFO", "skipped_after_L3_fail")
        else:
            module.layer4_structure(candidate, [])
    output_dir.mkdir(parents=True, exist_ok=False)
    module.write_summary(candidates, output_dir)
    rows = read_tsv(output_dir / "screen_summary.tsv")
    if len(rows) != EXPECTED_CANDIDATES or len({row["id"] for row in rows}) != EXPECTED_CANDIDATES:
        raise RuntimeError("frozen-logic TNP reconstruction failed 100-row closure")
    return 0


def reconstruct_tnp(final_inventory: Path) -> None:
    staging = RECOVERY / f"tnp_reconstructed.staging.{os.getpid()}"
    if staging.exists():
        raise RuntimeError(f"staging path already exists: {staging}")
    proc = run_checked([str(EVAL_PYTHON), str(Path(__file__).resolve()), "--internal-reconstruct",
                        str(final_inventory), str(staging)], log=RECOVERY / "tnp_reconstruct.log")
    if proc.returncode != 0:
        raise RuntimeError(f"TNP reconstruction failed rc={proc.returncode}")
    rows = read_tsv(staging / "screen_summary.tsv")
    if len(rows) != EXPECTED_CANDIDATES or len({row["id"] for row in rows}) != EXPECTED_CANDIDATES:
        raise RuntimeError("reconstructed TNP summary closure failed")
    final_dir = RECOVERY / "tnp_reconstructed"
    if final_dir.exists():
        raise RuntimeError(f"refuse overwrite existing reconstruction: {final_dir}")
    os.replace(staging, final_dir)
    fsync_dir(final_dir.parent)
    atomic_write_bytes(SSD_ROOT / "reports/tnp_summary.tsv", (final_dir / "screen_summary.tsv").read_bytes())
    accepted = read_tsv(final_inventory)
    atomic_write_json(SSD_ROOT / "reports/tnp_merge.json", {
        "status": "PASS", "rows": len(rows), "unique_ids": len({row["id"] for row in rows}),
        "tnp_json_count": len(accepted),
        "reused_original_count": sum(row["selected_origin"] == "ORIGINAL_SSD_SNAPSHOT" for row in accepted),
        "rerun_count": sum(row["selected_origin"] == "SSD_RECOVERY_RERUN" for row in accepted),
        "immutable_inventory_path": str(final_inventory),
        "immutable_inventory_sha256": sha256_file(final_inventory),
        "vhh_screen_sha256": sha256_file(TOOLS / "vhh_screen.py"),
        "reconstruction": "frozen vhh_screen layer1/layer2/layer3/layer4 and collect_summary logic",
    })


def run_igfold_once(expected: dict[str, str]) -> None:
    launch_marker = RECOVERY / "igfold_launch_frozen.json"
    outputs = [SSD_ROOT / "runs" / f"igfold_{index:02d}" for index in range(IGFOLD_CHUNKS)]
    if launch_marker.exists() or any(path.exists() for path in outputs):
        raise RuntimeError("IgFold exact-once precondition violated: launch marker or output already exists")
    validate_igfold_chunk_partition(expected)
    manifest = []
    commands: list[tuple[int, list[str], Path]] = []
    cache_home = BASE / "cache/home"
    torch_home = BASE / "cache/torch"
    hf_home = BASE / "cache/huggingface"
    for path in (cache_home, torch_home, hf_home):
        path.mkdir(parents=True, exist_ok=True)
    for index in range(IGFOLD_CHUNKS):
        tag = f"igfold_{index:02d}"
        fasta = SSD_ROOT / "chunks" / f"{tag}.fasta"
        records = parse_fasta(fasta)
        if len(records) != 25:
            raise RuntimeError(f"expected 25 candidates in {tag}, found {len(records)}")
        for cid, sequence in records:
            if expected.get(cid) != sequence:
                raise RuntimeError(f"IgFold chunk binding mismatch: {cid}")
        cpus = f"{index * 8}-{index * 8 + 7}"
        output, log = SSD_ROOT / "runs" / tag, SSD_ROOT / "logs" / f"{tag}.log"
        cmd = ["taskset", "-c", cpus, "env", "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1",
               "OPENBLAS_NUM_THREADS=1", f"HOME={cache_home}", f"TORCH_HOME={torch_home}",
               f"HF_HOME={hf_home}", str(TOOLS / "bin/vhh-screen"), str(fasta),
               "-o", str(output), "--prefix", tag, "--skip-abnativ", "--skip-sapiens",
               "--skip-tnp", "--structure-tools", "igfold", "--gpu", str(index),
               "--igfold-models", "1"]
        commands.append((index, cmd, log))
        manifest.append({"chunk": tag, "candidate_count": len(records), "gpu": index,
                         "cpu_affinity": cpus, "input_fasta": str(fasta),
                         "input_fasta_sha256": sha256_file(fasta), "output": str(output),
                         "log": str(log), "command": shlex.join(cmd),
                         "command_sha256": sha256_bytes(shlex.join(cmd).encode())})
    write_tsv(RECOVERY / "igfold_launch_manifest.tsv", manifest)
    atomic_write_json(launch_marker, {
        "schema_version": "pvrig_node1_ssd_igfold_exactly_once_launch_v1",
        "created_at": utc_now(), "candidate_count": EXPECTED_CANDIDATES,
        "chunks": IGFOLD_CHUNKS, "gpus": [0, 1, 2, 3], "models_per_candidate": 1,
        "manifest_sha256": sha256_file(RECOVERY / "igfold_launch_manifest.tsv"),
        "automatic_relaunch_allowed": False,
    })

    def worker(item: tuple[int, list[str], Path]) -> dict[str, Any]:
        index, cmd, log = item
        started = utc_now()
        proc = run_checked(cmd, cwd=SSD_ROOT, log=log)
        return {"chunk": f"igfold_{index:02d}", "gpu": index, "started_at": started,
                "finished_at": utc_now(), "returncode": proc.returncode,
                "log": str(log), "log_sha256": sha256_file(log)}

    results = []
    with ThreadPoolExecutor(max_workers=IGFOLD_CHUNKS) as pool:
        for future in as_completed([pool.submit(worker, item) for item in commands]):
            results.append(future.result())
    results.sort(key=lambda row: row["chunk"])
    write_tsv(RECOVERY / "igfold_chunk_results.tsv", results)
    failed = [row for row in results if row["returncode"] != 0]
    if failed:
        raise RuntimeError(f"IgFold chunk failure; exact-once contract prevents automatic retry: {failed}")


def count_pdb_ca(path: Path) -> int:
    seen = set()
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            seen.add((line[21:22], line[22:27]))
    return len(seen)


def validate_and_merge_igfold(expected: dict[str, str]) -> None:
    rows: list[dict[str, str]] = []
    manifest: list[dict[str, Any]] = []
    observed: set[str] = set()
    for index in range(IGFOLD_CHUNKS):
        tag = f"igfold_{index:02d}"
        run = SSD_ROOT / "runs" / tag
        rows.extend(read_tsv(run / "screen_summary.tsv"))
        for cid, sequence in parse_fasta(SSD_ROOT / "chunks" / f"{tag}.fasta"):
            if cid in observed:
                raise RuntimeError(f"duplicate IgFold candidate {cid}")
            observed.add(cid)
            structure = run / "structures" / cid
            sequence_fasta, pdb = structure / f"{cid}.fasta", structure / "igfold.pdb"
            command_log = run / "logs" / f"structure_{cid}_igfold.log"
            if parse_fasta(sequence_fasta) != [(cid, sequence)]:
                raise RuntimeError(f"IgFold structure FASTA binding mismatch: {cid}")
            if not pdb.is_file() or pdb.stat().st_size == 0:
                raise RuntimeError(f"IgFold PDB missing: {cid}")
            text = command_log.read_text(errors="replace")
            if not re.search(r"\[exit_code\] 0\s*$", text):
                raise RuntimeError(f"IgFold command did not terminate successfully: {cid}")
            tokens = shlex.split(text.splitlines()[0][2:])
            if Path(tokens[0]).name != "igfold-predict" or command_value(tokens, "--models") != "1":
                raise RuntimeError(f"IgFold frozen command mismatch: {cid}")
            ca_count = count_pdb_ca(pdb)
            if ca_count < int(0.9 * len(sequence)):
                raise RuntimeError(f"IgFold low CA coverage: {cid} ca={ca_count} len={len(sequence)}")
            manifest.append({"candidate_id": cid, "chunk": tag, "gpu": index,
                             "sequence_sha256": sha256_bytes(sequence.encode()),
                             "sequence_fasta": str(sequence_fasta), "sequence_fasta_sha256": sha256_file(sequence_fasta),
                             "pdb": str(pdb), "pdb_bytes": pdb.stat().st_size, "pdb_sha256": sha256_file(pdb),
                             "ca_count": ca_count, "command_log": str(command_log),
                             "command_log_sha256": sha256_file(command_log), "status": "VALID"})
    ids = [row["id"] for row in rows]
    if len(rows) != EXPECTED_CANDIDATES or len(set(ids)) != EXPECTED_CANDIDATES or set(ids) != set(expected):
        raise RuntimeError(f"IgFold summary closure failed rows={len(rows)} unique={len(set(ids))}")
    if len(manifest) != EXPECTED_CANDIDATES or observed != set(expected):
        raise RuntimeError("IgFold artifact closure failed")
    write_tsv(SSD_ROOT / "reports/igfold_summary.tsv", sorted(rows, key=lambda row: row["id"]), list(rows[0]))
    write_tsv(RECOVERY / "igfold_artifact_manifest.tsv", sorted(manifest, key=lambda row: row["candidate_id"]))
    atomic_write_json(SSD_ROOT / "reports/igfold_merge.json", {
        "status": "PASS", "rows": len(rows), "unique_ids": len(set(ids)),
        "igfold_pdb_count": len(manifest), "gpus": [0, 1, 2, 3], "models_per_candidate": 1,
        "artifact_manifest_sha256": sha256_file(RECOVERY / "igfold_artifact_manifest.tsv"),
        "exactly_once_launch_manifest_sha256": sha256_file(RECOVERY / "igfold_launch_manifest.tsv"),
    })


def write_deepqc_complete_status() -> None:
    atomic_write_json(SSD_ROOT / "status/deepqc_status.json", {
        "status": "SSD_DELIVERY_PREPARED_NONTERMINAL",
        "reason": "TNP/IgFold verified; terminal readiness requires the immutable SSD publication receipt",
        "updated_at": utc_now(), "recovery_root": str(RECOVERY),
        "terminal": False, "receipt_pending": True,
        "claim_boundary": "TNP and monomer structure QC only; not PVRIG binding, affinity, docking, or blocking evidence.",
    })


def package_delivery(final_inventory_snapshot: Path) -> list[Path]:
    root = SSD_ROOT
    tnp, igfold = read_tsv(root / "reports/tnp_summary.tsv"), read_tsv(root / "reports/igfold_summary.tsv")
    tnp_ids, ig_ids = {row["id"] for row in tnp}, {row["id"] for row in igfold}
    pdbs = sorted(root.glob("runs/igfold_*/structures/*/igfold.pdb"))
    if len(tnp) != 100 or len(tnp_ids) != 100 or len(igfold) != 100 or len(ig_ids) != 100 or tnp_ids != ig_ids:
        raise RuntimeError("delivery row and ID closure failed")
    if len(pdbs) != 100:
        raise RuntimeError(f"delivery IgFold PDB closure failed: {len(pdbs)}")
    write_deepqc_complete_status()
    files = [
        root / "run_deepqc.sh", root / "deepqc_config.json", root / "input_audit.json",
        root / "inputs/pre_shortlist100.fasta", root / "inputs/pre_shortlist100.tsv",
        root / "reports/tnp_summary.tsv", root / "reports/tnp_merge.json",
        root / "reports/igfold_summary.tsv", root / "reports/igfold_merge.json",
        root / "reports/INPUT_SHA256SUMS.txt", root / "status/deepqc_status.json", *pdbs,
    ]
    manifest = root / "reports/delivery_file_manifest.tsv"
    write_tsv(manifest, [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                          "sha256": sha256_file(path)} for path in files], ["path", "bytes", "sha256"])
    receipt = root / "reports/deepqc_delivery_receipt_v1.json"
    atomic_write_json(receipt, {
        "schema_version": "pvrig_pre_shortlist100_deepqc_delivery_v1",
        "status": "PASS_DEEPQC100_DELIVERY_READY", "candidate_count": 100,
        "tnp_row_count": len(tnp), "igfold_row_count": len(igfold),
        "igfold_pdb_count": len(pdbs), "id_parity": tnp_ids == ig_ids,
        "delivery_manifest_sha256": sha256_file(manifest),
        "run_deepqc_sha256": sha256_file(root / "run_deepqc.sh"),
        "deepqc_config_sha256": sha256_file(root / "deepqc_config.json"),
        "input_audit_sha256": sha256_file(root / "input_audit.json"),
        "input_fasta_sha256": sha256_file(root / "inputs/pre_shortlist100.fasta"),
        "ssd_recovery": True,
        "tnp_inventory_snapshot_path": str(final_inventory_snapshot),
        "tnp_inventory_sha256": sha256_file(final_inventory_snapshot),
        "igfold_artifact_manifest_sha256": sha256_file(RECOVERY / "igfold_artifact_manifest.tsv"),
        "claim_boundary": "TNP and monomer-structure QC annotations only; not PVRIG binding, affinity, docking, or experimental blocking evidence.",
    })
    tar_path = root / "reports/deepqc_delivery_v1.tar.gz"
    tar_members = files + [manifest, receipt]
    with tarfile.open(tar_path, "w:gz") as archive:
        for path in tar_members:
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    with tarfile.open(tar_path, "r:gz") as archive:
        names = archive.getnames()
    expected_names = [path.relative_to(root).as_posix() for path in tar_members]
    if names != expected_names:
        raise RuntimeError("delivery tar member closure failed")
    sha_path = root / "reports/deepqc_delivery_v1.tar.gz.sha256"
    atomic_write_text(sha_path, f"{sha256_file(tar_path)}  reports/deepqc_delivery_v1.tar.gz\n")
    atomic_write_json(RECOVERY / "delivery_verification.json", {
        "status": "PASS", "created_at": utc_now(), "candidate_count": 100,
        "tar_sha256": sha256_file(tar_path), "tar_member_count": len(names),
        "delivery_receipt_sha256": sha256_file(receipt),
        "delivery_manifest_sha256": sha256_file(manifest),
    })
    return files + [manifest, receipt, tar_path, sha_path]


def refuse_nfs_syncback() -> None:
    raise RuntimeError(
        "NFS sync-back is disabled: paused legacy processes retain the original locks, "
        "so writer exclusion and a provable cross-file CAS cannot be established"
    )


def capture_publication_payloads(sources: list[Path]) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    for index, path in enumerate(sources):
        # This single byte capture is the publication authority; later source mutation is irrelevant.
        raw = path.read_bytes()
        destination = f"payload_{index:04d}_{path.name}"
        captured.append({
            "source": str(path),
            "destination_relative_name": destination,
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "captured_bytes": raw,
        })
    destinations = [row["destination_relative_name"] for row in captured]
    if len(destinations) != len(set(destinations)):
        raise RuntimeError("publication destination names are not unique")
    return captured


def verify_publication_destinations(root: Path, manifest_rows: list[dict[str, Any]]) -> None:
    expected = {row["destination_relative_name"]: row for row in manifest_rows}
    observed = {path.name for path in root.iterdir() if path.is_file()}
    allowed_metadata = {"PUBLICATION_MANIFEST.tsv"}
    unexpected = observed - set(expected) - allowed_metadata
    missing = set(expected) - observed
    if unexpected or missing:
        raise RuntimeError(
            f"publication destination set mismatch: missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
    for name, row in expected.items():
        destination = root / name
        size = destination.stat().st_size
        digest = sha256_file(destination)
        if size != int(row["bytes"]) or digest != row["sha256"]:
            raise RuntimeError(
                f"publication destination payload mismatch: {name}: "
                f"size={size}/{row['bytes']} sha={digest}/{row['sha256']}"
            )


def publish_content_addressed_ssd_delivery(
    delivery_paths: list[Path],
    final_inventory_snapshot: Path,
) -> Path:
    publications = BASE / "immutable_deliveries"
    publications.mkdir(parents=True, exist_ok=True)
    sources = sorted(set(delivery_paths + [
        final_inventory_snapshot,
        RECOVERY / "igfold_artifact_manifest.tsv",
        RECOVERY / "final_working_tnp_inventory.tsv",
    ]), key=str)
    captured = capture_publication_payloads(sources)
    rows = [{key: row[key] for key in ("source", "destination_relative_name", "bytes", "sha256")}
            for row in captured]
    manifest_raw = tsv_bytes(rows, ["source", "destination_relative_name", "bytes", "sha256"])
    content_id = sha256_bytes(manifest_raw)
    final_dir = publications / f"deepqc100_{content_id}"
    if final_dir.exists():
        raise RuntimeError(f"content-addressed delivery already exists; refusing mutation: {final_dir}")
    staging = publications / f".staging_{content_id}_{os.getpid()}_{time.time_ns()}"
    os.mkdir(staging, 0o700)
    try:
        exclusive_write_bytes(staging / "PUBLICATION_MANIFEST.tsv", manifest_raw, 0o444)
        for row in captured:
            exclusive_write_bytes(
                staging / row["destination_relative_name"],
                row["captured_bytes"],
                0o444,
            )
        verify_publication_destinations(staging, rows)
        publication = {
            "schema_version": "pvrig_node1_ssd_content_addressed_delivery_v1",
            "status": "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH",
            "content_id": content_id,
            "candidate_count": EXPECTED_CANDIDATES,
            "payload_count": len(rows),
            "publication_manifest_sha256": sha256_bytes(manifest_raw),
            "tnp_inventory_snapshot_path": str(final_inventory_snapshot),
            "tnp_inventory_snapshot_sha256": sha256_file(final_inventory_snapshot),
            "nfs_syncback_performed": False,
            "nfs_syncback_reason": "legacy NFS locks are retained by paused processes; no provable writer exclusion",
            "required_next_action": "switch the downstream watcher input path to this immutable SSD delivery",
            "claim_boundary": "TNP and monomer-structure QC only; not binding, docking, or blocking evidence.",
        }
        exclusive_write_bytes(
            staging / "SSD_DELIVERY_PUBLICATION.json",
            (json.dumps(publication, indent=2, sort_keys=True) + "\n").encode(),
            0o444,
        )
        for path in staging.iterdir():
            if path.is_file() and not (path.stat().st_mode & 0o222) == 0:
                raise RuntimeError(f"publication file is writable: {path}")
        os.mkdir(final_dir, 0o700)
        publication_receipt = staging / "SSD_DELIVERY_PUBLICATION.json"
        for path in sorted(p for p in staging.iterdir() if p != publication_receipt):
            os.link(path, final_dir / path.name)
        fsync_dir(final_dir)
        # Re-read the final destination bytes and prove manifest closure before readiness exists.
        verify_publication_destinations(final_dir, rows)
        if (final_dir / "PUBLICATION_MANIFEST.tsv").stat().st_size != len(manifest_raw):
            raise RuntimeError("publication manifest destination size mismatch")
        if sha256_file(final_dir / "PUBLICATION_MANIFEST.tsv") != content_id:
            raise RuntimeError("publication manifest destination hash mismatch")
        # The ready receipt is linked last; an interrupted publication is never terminal.
        os.link(publication_receipt, final_dir / publication_receipt.name)
        fsync_dir(final_dir)
        os.chmod(final_dir, 0o555)
        fsync_dir(publications)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if sha256_file(final_dir / "PUBLICATION_MANIFEST.tsv") != content_id:
        raise RuntimeError("content-addressed publication hash mismatch")
    return final_dir


def run_recovery() -> None:
    RECOVERY.mkdir(parents=True, exist_ok=True)
    lock_handle = (RECOVERY / "recovery.lock").open("a+")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError("another SSD recovery controller holds the lock") from exc
    pre = preflight()
    if pre["overall_status"] != "PASS":
        set_status("NOT_STARTED", "PREFLIGHT", f"preconditions={pre['overall_status']}")
        raise RuntimeError(f"preflight is not PASS: {pre['overall_status']}")
    if (RECOVERY / "ssd_recovery_receipt.json").exists():
        raise RuntimeError("terminal recovery receipt already exists; refusing duplicate execution")
    set_status("RUNNING", "INVENTORY", "validating SSD TNP results with command-log ID/sequence binding")
    assert_guard()
    expected, _ = build_candidate_index()
    _, accepted, rerun = inventory_tnp("initial")
    if (len(accepted), len(rerun)) != (64, 36):
        raise RuntimeError(f"initial frozen TNP partition mismatch: {len(accepted)}/{len(rerun)}")
    if any(row["frozen_partition_class"] != "REUSE64" for row in accepted):
        raise RuntimeError("initial accepted set is not exactly the frozen reuse64")
    if any(row["frozen_partition_class"] != "RERUN36" for row in rerun):
        raise RuntimeError("initial rerun set is not exactly the frozen complement36")
    set_status("RUNNING", "TNP_REMAINDER", f"reused={len(accepted)} rerun={len(rerun)}")
    run_tnp_remainder(rerun, expected)
    assert_guard()
    final_rows, accepted_final, rerun_final = inventory_tnp("final_working")
    if len(accepted_final) != EXPECTED_CANDIDATES or rerun_final:
        raise RuntimeError(f"final TNP closure failed accepted={len(accepted_final)} missing={len(rerun_final)}")
    final_inventory_snapshot = freeze_final_inventory(final_rows)
    set_status("RUNNING", "TNP_RECONSTRUCT", "rebuilding 100 rows with frozen vhh_screen logic")
    reconstruct_tnp(final_inventory_snapshot)
    assert_guard()
    set_status("RUNNING", "IGFOLD100", "launching exactly once on GPUs 0-3")
    run_igfold_once(expected)
    assert_guard()
    validate_and_merge_igfold(expected)
    set_status("RUNNING", "PACKAGE", "building and verifying DeepQC100 delivery")
    delivery = package_delivery(final_inventory_snapshot)
    set_status("RUNNING", "SSD_PUBLICATION", "publishing immutable content-addressed SSD delivery")
    ssd_delivery = publish_content_addressed_ssd_delivery(delivery, final_inventory_snapshot)
    assert_guard()
    commit_terminal_receipt({
        "schema_version": "pvrig_node1_ssd_deepqc_recovery_receipt_v1",
        "status": "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH",
        "created_at": utc_now(), "candidate_count": EXPECTED_CANDIDATES,
        "tnp_reused_original_count": sum(row["selected_origin"] == "ORIGINAL_SSD_SNAPSHOT" for row in accepted_final),
        "tnp_rerun_count": sum(row["selected_origin"] == "SSD_RECOVERY_RERUN" for row in accepted_final),
        "tnp_inventory_snapshot_path": str(final_inventory_snapshot),
        "tnp_inventory_sha256": sha256_file(final_inventory_snapshot),
        "frozen_reuse_manifest_sha256": EXPECTED_REUSE_MANIFEST_SHA256,
        "frozen_rerun_manifest_sha256": EXPECTED_RERUN_MANIFEST_SHA256,
        "frozen_process_manifest_sha256": EXPECTED_PROCESS_MANIFEST_SHA256,
        "tnp_summary_sha256": sha256_file(SSD_ROOT / "reports/tnp_summary.tsv"),
        "igfold_candidate_count": 100, "igfold_gpus": [0, 1, 2, 3],
        "igfold_launch_manifest_sha256": sha256_file(RECOVERY / "igfold_launch_manifest.tsv"),
        "igfold_artifact_manifest_sha256": sha256_file(RECOVERY / "igfold_artifact_manifest.tsv"),
        "delivery_tar_sha256": sha256_file(SSD_ROOT / "reports/deepqc_delivery_v1.tar.gz"),
        "ssd_content_addressed_delivery": str(ssd_delivery),
        "ssd_publication_receipt_sha256": sha256_file(ssd_delivery / "SSD_DELIVERY_PUBLICATION.json"),
        "nfs_syncback_performed": False,
        "nfs_syncback_reason": "legacy NFS locks retained by paused processes prevent provable writer exclusion",
        "required_next_action": "switch the downstream watcher input path to the immutable SSD delivery",
        "old_nfs_process_tree_signaled": False,
        "claim_boundary": "TNP and monomer-structure QC annotations only; not PVRIG binding, affinity, docking, or experimental blocking evidence.",
    })


def self_test() -> int:
    global RECOVERY
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fasta = root / "x.fasta"
        atomic_write_text(fasta, ">A\nACDEFGHIK\n>B\nLMNPQRSTV\n")
        assert parse_fasta(fasta) == [("A", "ACDEFGHIK"), ("B", "LMNPQRSTV")]
        assert sha256_file(fasta) == sha256_bytes(fasta.read_bytes())
        tsv = root / "x.tsv"
        write_tsv(tsv, [{"a": "1", "b": "2"}])
        assert read_tsv(tsv) == [{"a": "1", "b": "2"}]
        assert command_value(shlex.split("TNP --seq AAA --name X --ncores 4 --output /x/X"), "--name") == "X"
        exact = {"A": "ACD", "B": "EFG"}
        assert validate_exact_partition(exact, {"x": [("A", "ACD")], "y": [("B", "EFG")]}, 2, 2) == exact
        try:
            validate_exact_partition(exact, {"x": [("A", "ACD")], "y": [("A", "ACD")]}, 2, 2)
            raise AssertionError("duplicate partition was accepted")
        except RuntimeError:
            pass
        immutable = root / "immutable"
        exclusive_write_bytes(immutable, b"v1")
        try:
            exclusive_write_bytes(immutable, b"v2")
            raise AssertionError("immutable file was overwritten")
        except FileExistsError:
            pass

        try:
            refuse_nfs_syncback()
            raise AssertionError("NFS sync-back policy did not fail closed")
        except RuntimeError:
            pass

        previous_recovery = RECOVERY
        RECOVERY = root / "receipt"
        try:
            commit_terminal_receipt({"schema_version": "test", "status": "PASS"})
            status = read_json(RECOVERY / "recovery_status.json")
            assert status["status"] == "PREPARED_FOR_RECEIPT"
            assert status["terminal"] is False and status["receipt_pending"] is True
            assert sha256_file(RECOVERY / "ssd_recovery_receipt.json") == status["expected_receipt_sha256"]
        finally:
            RECOVERY = previous_recovery
        identity = proc_info(os.getpid())
        assert identity and identity["starttime_ticks"] > 0 and identity["cmdline_sha256"]
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--internal-reconstruct", nargs=2, metavar=("INVENTORY", "OUTPUT"))
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.internal_reconstruct:
        return internal_reconstruct(Path(args.internal_reconstruct[0]), Path(args.internal_reconstruct[1]))
    if args.preflight:
        result = preflight()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["overall_status"] == "PASS" else (3 if result["overall_status"] == "WAITING" else 2)
    try:
        run_recovery()
        return 0
    except Exception as exc:
        RECOVERY.mkdir(parents=True, exist_ok=True)
        if (RECOVERY / "ssd_recovery_receipt.json").exists():
            # Never write after the receipt-last commit, even on an impossible postcommit exception.
            raise
        set_status("FAILED", "ABORTED_FAIL_CLOSED", str(exc))
        atomic_write_json(RECOVERY / "failure.json", {
            "status": "FAILED_FAIL_CLOSED", "failed_at": utc_now(), "error": str(exc),
            "old_nfs_process_tree_signaled": False,
        })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
