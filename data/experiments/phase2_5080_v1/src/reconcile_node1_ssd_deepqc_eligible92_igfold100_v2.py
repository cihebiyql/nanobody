#!/usr/bin/env python3
"""Reconcile the eligible-only SSD Deep-QC run into an immutable delivery (V2).

This adapter preserves the eight frozen L2 hard failures, accepts TNP output only
for the 92 eligible candidates, and closes monomer structure coverage at 100.
Seven preregistered null TNP payloads are rerun with the frozen TNP command.
It never resumes or writes to the legacy NFS run.
"""

from __future__ import annotations

import argparse
import csv
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
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EXPECTED_FASTA_SHA256 = "57245f7ed52d633209d67a59dbc809118bbb06042f54b68dcf29cb3e35182eb0"
EXPECTED_FORMAL_RECOVERY_SHA256 = "fe6ed34167848d11856bcb0ce8dc1192ebdee5852b87f3f158dc7161947fc9b1"
EXPECTED_PROCESS_MANIFEST_SHA256 = "d93b8673ada7dab23dcd49d5cd013ba473878a3ec3d5e3189180e3007ad05095"
EXPECTED_CANDIDATES = 100
EXPECTED_TNP_ELIGIBLE = 92
EXPECTED_HARD_FAILS = {
    "RFV1__PLDNANO_VHH_00863__A_CENTER__H1H3__B10__M02",
    "RFV1__PLDNANO_VHH_00863__A_CENTER__H3__B01__M02",
    "RFV1__PLDNANO_VHH_00863__C_CROSS__H1H3__B02__M02",
    "RFV1__PLDNANO_VHH_00863__C_CROSS__H3__B05__M00",
    "RFV1__PLDNANO_VHH_00895__A_CENTER__H3__B01__M01",
    "RFV1__PLDNANO_VHH_00895__A_CENTER__H3__B07__M01",
    "RFV1__PLDNANO_VHH_00895__B_LOWER__H1H3__B02__M02",
    "RFV1__PLDNANO_VHH_00895__B_LOWER__H3__B11__M00",
}
EXPECTED_TNP_NULL_RERUNS = {
    "RFV1__PLDNANO_VHH_00197__A_CENTER__H1H3__B02__M01",
    "RFV1__PLDNANO_VHH_00327__C_CROSS__H3__B09__M02",
    "RFV1__PLDNANO_VHH_00376__A_CENTER__H3__B07__M00",
    "RFV1__PLDNANO_VHH_00376__C_CROSS__H1H3__B07__M00",
    "RFV1__PLDNANO_VHH_00698__A_CENTER__H1H3__B05__M02",
    "RFV1__PLDNANO_VHH_00874__B_LOWER__H3__B05__M00",
    "RFV1__PLDNANO_VHH_00882__A_CENTER__H1H3__B08__M01",
}
REQUIRED_TNP_KEYS = {
    "name", "Total CDR Length", "CDR3 Length", "CDR3 Compactness",
    "PSH", "PPC", "PNC", "Flags",
}
REQUIRED_TNP_FLAGS = {"L", "L3", "C", "PSH", "PPC", "PNC"}
CLAIM_BOUNDARY = (
    "Sequence/developability QC and VHH monomer structure predictions only; "
    "not PVRIG binding, affinity, docking, competition, or experimental blocking evidence."
)


@dataclass(frozen=True)
class Paths:
    base: Path = Path("/data1/qlyu/pvrig_migration_20260716")
    root: Path = Path("/data1/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716")
    formal_recovery: Path = Path("/data1/qlyu/pvrig_migration_20260716/resume_ssd_deepqc.py")
    prereg: Path = Path("/data1/qlyu/pvrig_migration_20260716/reconciliation_deployment_v2/node1_ssd_deepqc_eligible92_igfold100_reconciliation_v2_preregistration.json")
    adapter: Path = Path("/data1/qlyu/pvrig_migration_20260716/reconciliation_deployment_v2/reconcile_node1_ssd_deepqc_eligible92_igfold100_v2.py")

    @property
    def reconciliation(self) -> Path:
        return self.base / "deepqc_reconciliation_eligible92_igfold100_v2"

    @property
    def canonical_recovery_receipt(self) -> Path:
        return self.base / "deepqc_recovery_v1/ssd_recovery_receipt.json"

    @property
    def path_switch_receipt(self) -> Path:
        return self.base / "ACTIVE_DEEPQC_DELIVERY_PATH_SWITCH.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def parse_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    current: str | None = None
    parts: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current is not None:
                records.append((current, "".join(parts)))
            current = line[1:].split()[0]
            parts = []
        elif current is None:
            raise ValueError(f"FASTA sequence before header: {path}")
        else:
            parts.append(line)
    if current is not None:
        records.append((current, "".join(parts)))
    if not records or any(not cid or not seq for cid, seq in records):
        raise ValueError(f"invalid or empty FASTA: {path}")
    return records


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def tsv_bytes(rows: list[dict[str, Any]], fields: list[str] | None = None) -> bytes:
    if not rows:
        raise ValueError("refuse empty TSV")
    fields = fields or list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def exclusive_write(path: Path, raw: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    os.chmod(path, mode)


def write_or_verify(path: Path, raw: bytes, mode: int = 0o444) -> None:
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != raw:
            raise RuntimeError(f"existing immutable artifact conflict: {path}")
        return
    exclusive_write(path, raw, mode)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_formal_module(paths: Paths):
    if sha256_file(paths.formal_recovery) != EXPECTED_FORMAL_RECOVERY_SHA256:
        raise RuntimeError("formal recovery implementation hash drift")
    spec = importlib.util.spec_from_file_location("pvrig_frozen_ssd_recovery", paths.formal_recovery)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load formal recovery implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_old_nfs_guard(paths: Paths) -> dict[str, Any]:
    process_manifest = paths.base / "frozen_recovery_v1/FROZEN_NFS_PROCESS_IDENTITY_V1.tsv"
    if sha256_file(process_manifest) != EXPECTED_PROCESS_MANIFEST_SHA256:
        raise RuntimeError("frozen NFS process manifest hash drift")
    guard = load_formal_module(paths).old_nfs_process_guard()
    if guard.get("status") != "PASS":
        raise RuntimeError(f"old NFS process guard failed: {guard}")
    return guard


def active_reconciliation_producers(paths: Paths) -> list[dict[str, Any]]:
    needles = ("resume_deepqc_ssd.sh", "runs_ssd_resume", "vhh_screen_cached_tnp.py")
    active = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            state = (entry / "stat").read_text().split()[2]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if state != "Z" and any(needle in cmd for needle in needles):
            active.append({"pid": int(entry.name), "state": state, "cmdline": cmd})
    return sorted(active, key=lambda row: row["pid"])


def candidate_index(paths: Paths) -> dict[str, str]:
    fasta = paths.root / "inputs/pre_shortlist100.fasta"
    if sha256_file(fasta) != EXPECTED_FASTA_SHA256:
        raise RuntimeError("input FASTA hash drift")
    records = parse_fasta(fasta)
    index = dict(records)
    if len(records) != EXPECTED_CANDIDATES or len(index) != EXPECTED_CANDIDATES:
        raise RuntimeError("input FASTA candidate closure failed")
    if len(set(index.values())) != EXPECTED_CANDIDATES:
        raise RuntimeError("input FASTA sequence uniqueness failed")
    return index


def classify_qc_rows(
    rows: list[dict[str, str]],
    expected_ids: set[str],
    hard_fail_ids: set[str] = EXPECTED_HARD_FAILS,
    expected_eligible: int = EXPECTED_TNP_ELIGIBLE,
) -> tuple[set[str], set[str]]:
    ids = [row.get("id", "") for row in rows]
    if len(rows) != len(expected_ids) or len(set(ids)) != len(expected_ids) or set(ids) != expected_ids:
        raise RuntimeError("QC summary ID closure failed")
    hard = {
        row["id"] for row in rows
        if row.get("L1_numbering_integrity") == "FAIL" or row.get("L2_vhh_features") == "FAIL"
    }
    if hard != hard_fail_ids:
        raise RuntimeError(f"hard-fail set drift: missing={sorted(hard_fail_ids-hard)} extra={sorted(hard-hard_fail_ids)}")
    if any(row.get("L1_numbering_integrity") == "FAIL" for row in rows if row["id"] in hard):
        raise RuntimeError("preregistered hard failures must remain L2, not L1, failures")
    eligible = expected_ids - hard
    if len(eligible) != expected_eligible:
        raise RuntimeError(f"eligible count drift: {len(eligible)} != {expected_eligible}")
    return eligible, hard


def validate_tnp_payload(path: Path, cid: str, sequence: str, origin: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"invalid TNP result file: {path}")
    data = read_json(path)
    if set(data) != {cid} or not isinstance(data[cid], dict) or data[cid].get("name") != cid:
        raise RuntimeError(f"TNP candidate binding failed: {cid}")
    payload = data[cid]
    if not REQUIRED_TNP_KEYS.issubset(payload):
        raise RuntimeError(f"TNP required keys missing: {cid}")
    if not isinstance(payload["Flags"], dict) or not REQUIRED_TNP_FLAGS.issubset(payload["Flags"]):
        raise RuntimeError(f"TNP flags incomplete: {cid}")
    for key in ("Total CDR Length", "CDR3 Length", "CDR3 Compactness", "PSH", "PPC", "PNC"):
        float(payload[key])
    return {
        "candidate_id": cid,
        "sequence_sha256": sha256_bytes(sequence.encode()),
        "result_json": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "origin": origin,
        "status": "VALID_ELIGIBLE_TNP",
    }


def scan_initial_tnp_outputs(
    paths: Paths,
    candidates: dict[str, str],
    eligible: set[str],
    expected_null: set[str] = EXPECTED_TNP_NULL_RERUNS,
    expected_valid_count: int = 85,
) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    found: dict[str, Path] = {}
    for path in sorted((paths.root / "runs_ssd_resume").glob(
        "tnp_*/layer3_tnp/*/TNP_Results_SingleSeqEntry_*.json"
    )):
        cid = path.name.removeprefix("TNP_Results_SingleSeqEntry_").removesuffix(".json")
        if cid in found:
            raise RuntimeError(f"duplicate TNP result JSON: {cid}")
        found[cid] = path
    if set(found) != eligible:
        raise RuntimeError(f"TNP eligible-result closure failed: missing={sorted(eligible-set(found))} extra={sorted(set(found)-eligible)}")
    valid: dict[str, dict[str, Any]] = {}
    null: dict[str, Path] = {}
    for cid in sorted(eligible):
        path = found[cid]
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"invalid TNP result file: {path}")
        data = read_json(path)
        if set(data) == {cid} and data[cid] is None:
            null[cid] = path
            continue
        valid[cid] = validate_tnp_payload(path, cid, candidates[cid], "AD_HOC_VALID_PAYLOAD")
    if set(null) != expected_null:
        raise RuntimeError(
            f"initial null TNP set drift: missing={sorted(expected_null-set(null))} "
            f"extra={sorted(set(null)-expected_null)}"
        )
    if len(valid) != expected_valid_count:
        raise RuntimeError(f"initial valid TNP count drift: {len(valid)}")
    return valid, null


def validate_supplemental_tnp_candidate(
    cid: str,
    sequence: str,
    candidate_dir: Path,
    controller_log: Path,
) -> dict[str, Any]:
    result = candidate_dir / f"TNP_Results_SingleSeqEntry_{cid}.json"
    row = validate_tnp_payload(result, cid, sequence, "RECONCILIATION_NULL_RERUN")
    native_log = candidate_dir / f"{cid}_TNP.log"
    required = [
        candidate_dir / "Final_Models" / f"{cid}_NanoBodyBuilder2_Model.pdb",
        candidate_dir / "Final_Models" / f"{cid}_NanoBodyBuilder2_Model_Annotated.pdb",
        candidate_dir / "Final_Models" / f"{cid}_NanoBodyBuilder2_Sequence_Liabilities.json",
        native_log,
        controller_log,
    ]
    if any(not path.is_file() or path.stat().st_size == 0 for path in required):
        raise RuntimeError(f"supplemental TNP artifact closure failed: {cid}")
    text = controller_log.read_text(errors="replace")
    if not re.search(r"\[exit_code\]\s+0\s*$", text):
        raise RuntimeError(f"supplemental TNP command exit marker missing: {cid}")
    if f"Summary Statistics for {cid}:" not in native_log.read_text(errors="replace"):
        raise RuntimeError(f"supplemental TNP native summary missing: {cid}")
    row.update({
        "controller_log": str(controller_log),
        "controller_log_sha256": sha256_file(controller_log),
        "native_log": str(native_log),
        "native_log_sha256": sha256_file(native_log),
    })
    return row


def run_supplemental_tnp(
    paths: Paths,
    candidates: dict[str, str],
    null_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if null_ids != EXPECTED_TNP_NULL_RERUNS:
        raise RuntimeError("supplemental TNP set is not the frozen seven-candidate set")
    root = paths.reconciliation / "supplemental_tnp"
    runs, logs = root / "runs", root / "logs"
    runs.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    plan = []
    for slot, cid in enumerate(sorted(null_ids)):
        output = runs / cid
        log = logs / f"{cid}.log"
        cmd = [
            "/data1/qlyu/software/envs/vhh-eval/bin/TNP",
            "--seq", candidates[cid], "--name", cid,
            "--output", str(output), "--ncores", "4",
        ]
        plan.append({
            "candidate_id": cid, "sequence_sha256": sha256_bytes(candidates[cid].encode()),
            "cpu_affinity": f"{slot*4}-{slot*4+3}", "output": str(output),
            "controller_log": str(log), "command": shlex.join(cmd),
            "command_sha256": sha256_bytes(shlex.join(cmd).encode()),
        })
    write_or_verify(paths.reconciliation / "supplemental_tnp_launch_manifest.tsv", tsv_bytes(plan))

    def worker(row: dict[str, Any]) -> dict[str, Any]:
        cid = row["candidate_id"]
        output, log = Path(row["output"]), Path(row["controller_log"])
        if output.exists() or log.exists():
            return validate_supplemental_tnp_candidate(cid, candidates[cid], output, log)
        cmd = shlex.split(row["command"])
        wrapped = ["taskset", "-c", row["cpu_affinity"], "env", "OMP_NUM_THREADS=1",
                   "MKL_NUM_THREADS=1", "OPENBLAS_NUM_THREADS=1", *cmd]
        env = os.environ.copy()
        env.update({
            "HOME": str(paths.base / "cache/home"),
            "TORCH_HOME": str(paths.base / "cache/torch"),
            "HF_HOME": str(paths.base / "cache/huggingface"),
            "OPENMM_PLUGIN_DIR": "/data1/qlyu/anaconda3/envs/boltz/lib/plugins",
        })
        proc = subprocess.run(wrapped, cwd=paths.root, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        raw = (
            f"$ {shlex.join(cmd)}\n[started_at] frozen-launch-v2\n{proc.stdout}\n"
            f"[finished_at] {utc_now()}\n[exit_code] {proc.returncode}\n"
        ).encode()
        exclusive_write(log, raw, 0o444)
        if proc.returncode != 0:
            raise RuntimeError(f"supplemental TNP failed: {cid}: rc={proc.returncode}")
        return validate_supplemental_tnp_candidate(cid, candidates[cid], output, log)

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        for future in as_completed([pool.submit(worker, row) for row in plan]):
            row = future.result()
            results[row["candidate_id"]] = row
    if set(results) != null_ids:
        raise RuntimeError("supplemental TNP result closure failed")
    return results


def reconcile_tnp_outputs(
    paths: Paths,
    candidates: dict[str, str],
    eligible: set[str],
) -> list[dict[str, Any]]:
    valid, null = scan_initial_tnp_outputs(paths, candidates, eligible)
    rerun = run_supplemental_tnp(paths, candidates, set(null))
    combined = {**valid, **rerun}
    if set(combined) != eligible or len(combined) != EXPECTED_TNP_ELIGIBLE:
        raise RuntimeError("post-rerun valid TNP closure failed")
    return [combined[cid] for cid in sorted(combined)]


def ca_count(path: Path) -> int:
    seen = set()
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            seen.add((line[21:22], line[22:27]))
    return len(seen)


def validate_structure_triplet(cid: str, sequence: str, fasta: Path, pdb: Path, log: Path) -> dict[str, Any]:
    for path in (fasta, pdb, log):
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or unsafe IgFold artifact: {path}")
    if parse_fasta(fasta) != [(cid, sequence)]:
        raise RuntimeError(f"IgFold FASTA binding failed: {cid}")
    text = log.read_text(errors="replace")
    if not re.search(r"\[exit_code\]\s+0\s*$", text):
        raise RuntimeError(f"IgFold command exit marker missing: {cid}")
    count = ca_count(pdb)
    minimum = int(0.9 * len(sequence))
    if count < minimum:
        raise RuntimeError(f"IgFold CA coverage failed: {cid}: {count} < {minimum}")
    return {
        "candidate_id": cid,
        "sequence_sha256": sha256_bytes(sequence.encode()),
        "sequence_fasta": str(fasta),
        "sequence_fasta_sha256": sha256_file(fasta),
        "pdb": str(pdb),
        "pdb_bytes": pdb.stat().st_size,
        "pdb_sha256": sha256_file(pdb),
        "command_log": str(log),
        "command_log_sha256": sha256_file(log),
        "ca_count": count,
        "minimum_ca_count": minimum,
        "status": "VALID",
    }


def find_ad_hoc_structures(paths: Paths, candidates: dict[str, str]) -> dict[str, tuple[Path, Path, Path]]:
    found: dict[str, tuple[Path, Path, Path]] = {}
    for pdb in sorted((paths.root / "runs_ssd_resume").glob("igfold_*/structures/*/igfold.pdb")):
        cid = pdb.parent.name
        if cid not in candidates or cid in found:
            raise RuntimeError(f"unexpected or duplicate ad-hoc IgFold structure: {cid}")
        fasta = pdb.parent / f"{cid}.fasta"
        log = pdb.parent.parent.parent / "logs" / f"structure_{cid}_igfold.log"
        validate_structure_triplet(cid, candidates[cid], fasta, pdb, log)
        found[cid] = (fasta, pdb, log)
    return found


def run_supplemental_igfold(paths: Paths, candidates: dict[str, str], missing: list[str]) -> None:
    if not missing:
        return
    root = paths.reconciliation / "supplemental_igfold"
    root.mkdir(parents=True, exist_ok=True)
    slots: queue.Queue[int] = queue.Queue()
    for gpu in range(4):
        slots.put(gpu)

    def worker(cid: str) -> dict[str, Any]:
        gpu = slots.get()
        try:
            candidate_dir = root / cid
            candidate_dir.mkdir(parents=True, exist_ok=True)
            fasta = candidate_dir / f"{cid}.fasta"
            pdb = candidate_dir / "igfold.pdb"
            log = candidate_dir / f"structure_{cid}_igfold.log"
            fasta_raw = f">{cid}\n{candidates[cid]}\n".encode()
            if fasta.exists() and fasta.read_bytes() != fasta_raw:
                raise RuntimeError(f"supplemental FASTA conflict: {cid}")
            if not fasta.exists():
                exclusive_write(fasta, fasta_raw, 0o444)
            if pdb.exists() or log.exists():
                validate_structure_triplet(cid, candidates[cid], fasta, pdb, log)
                return {"candidate_id": cid, "gpu": gpu, "reused": True}
            cmd = [
                "/data1/qlyu/software/envs/vhh-igfold/bin/python",
                "/data1/qlyu/software/vhh_eval_tools/igfold_predict.py",
                str(fasta), "-o", str(pdb), "--models", "1",
            ]
            env = os.environ.copy()
            env.update({
                "CUDA_VISIBLE_DEVICES": str(gpu),
                "HOME": str(paths.base / "cache/home"),
                "TORCH_HOME": str(paths.base / "cache/torch"),
                "HF_HOME": str(paths.base / "cache/huggingface"),
                "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            })
            started = utc_now()
            proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            raw = (
                f"$ {shlex.join(cmd)}\n[started_at] {started}\n[gpu] {gpu}\n"
                f"{proc.stdout}\n[finished_at] {utc_now()}\n[exit_code] {proc.returncode}\n"
            ).encode()
            exclusive_write(log, raw, 0o444)
            if proc.returncode != 0:
                raise RuntimeError(f"supplemental IgFold failed: {cid}: rc={proc.returncode}")
            os.chmod(pdb, 0o444)
            validate_structure_triplet(cid, candidates[cid], fasta, pdb, log)
            return {"candidate_id": cid, "gpu": gpu, "reused": False}
        finally:
            slots.put(gpu)

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(worker, cid) for cid in missing]):
            results.append(future.result())
    results.sort(key=lambda row: row["candidate_id"])
    write_or_verify(paths.reconciliation / "supplemental_igfold_results.tsv", tsv_bytes(results))


def freeze_igfold100(paths: Paths, candidates: dict[str, str]) -> list[dict[str, Any]]:
    ad_hoc = find_ad_hoc_structures(paths, candidates)
    missing = sorted(set(candidates) - set(ad_hoc))
    run_supplemental_igfold(paths, candidates, missing)
    supplemental = paths.reconciliation / "supplemental_igfold"
    final = paths.reconciliation / "igfold100"
    final.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cid in sorted(candidates):
        origin = "AD_HOC_SSD_RUN"
        if cid in ad_hoc:
            source_fasta, source_pdb, source_log = ad_hoc[cid]
        else:
            origin = "RECONCILIATION_SUPPLEMENT"
            source = supplemental / cid
            source_fasta, source_pdb, source_log = (
                source / f"{cid}.fasta", source / "igfold.pdb", source / f"structure_{cid}_igfold.log"
            )
        source_row = validate_structure_triplet(cid, candidates[cid], source_fasta, source_pdb, source_log)
        destination = final / cid
        destination.mkdir(parents=True, exist_ok=True)
        fasta, pdb, log = destination / f"{cid}.fasta", destination / "igfold.pdb", destination / "command.log"
        write_or_verify(fasta, source_fasta.read_bytes())
        write_or_verify(pdb, source_pdb.read_bytes())
        write_or_verify(log, source_log.read_bytes())
        row = validate_structure_triplet(cid, candidates[cid], fasta, pdb, log)
        if row["pdb_sha256"] != source_row["pdb_sha256"]:
            raise RuntimeError(f"IgFold copy hash mismatch: {cid}")
        row.update({"origin": origin, "source_pdb": str(source_pdb), "source_pdb_sha256": source_row["pdb_sha256"]})
        manifest.append(row)
    if len(manifest) != EXPECTED_CANDIDATES:
        raise RuntimeError("IgFold100 manifest closure failed")
    return manifest


def validate_ad_hoc_terminal(paths: Paths) -> tuple[dict[str, str], list[dict[str, str]], set[str], set[str]]:
    active = active_reconciliation_producers(paths)
    if active:
        raise RuntimeError(f"ad-hoc SSD runner still active: {active}")
    status = read_json(paths.root / "status/deepqc_ssd_resume_status.json")
    if status.get("status") != "COMPLETE" or status.get("old_nfs_processes_resumed") is not False:
        raise RuntimeError(f"ad-hoc terminal status invalid: {status}")
    complete = read_json(paths.root / "reports_ssd/deepqc_ssd_complete.json")
    if complete.get("status") != "PASS" or int(complete.get("rows", -1)) != EXPECTED_CANDIDATES:
        raise RuntimeError(f"ad-hoc completion report invalid: {complete}")
    if complete.get("old_nfs_processes_resumed") is not False:
        raise RuntimeError("ad-hoc completion report claims NFS resume")
    candidates = candidate_index(paths)
    tnp_rows = read_tsv(paths.root / "reports_ssd/tnp_summary.tsv")
    eligible, hard = classify_qc_rows(tnp_rows, set(candidates))
    if int(complete.get("tnp_json_count", -1)) != EXPECTED_TNP_ELIGIBLE:
        raise RuntimeError("terminal TNP count drift")
    return candidates, tnp_rows, eligible, hard


def verify_publication(delivery: Path) -> dict[str, Any]:
    publication_path = delivery / "SSD_DELIVERY_PUBLICATION.json"
    manifest_path = delivery / "PUBLICATION_MANIFEST.tsv"
    publication = read_json(publication_path)
    manifest_raw = manifest_path.read_bytes()
    content_id = sha256_bytes(manifest_raw)
    if publication.get("status") != "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH":
        raise RuntimeError("publication status invalid")
    if publication.get("content_id") != content_id or delivery.name != f"deepqc100_{content_id}":
        raise RuntimeError("publication content address invalid")
    rows = list(csv.DictReader(io.StringIO(manifest_raw.decode()), delimiter="\t"))
    if not rows or len(rows) != int(publication.get("payload_count", -1)):
        raise RuntimeError("publication payload count invalid")
    names = set()
    for row in rows:
        name = row["destination_relative_name"]
        path = delivery / name
        if Path(name).name != name or name in names or path.parent != delivery:
            raise RuntimeError("publication payload path invalid")
        names.add(name)
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"publication payload missing: {name}")
        if path.stat().st_size != int(row["bytes"]) or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"publication payload hash invalid: {name}")
    actual = {path.name for path in delivery.iterdir()}
    if actual != names | {"PUBLICATION_MANIFEST.tsv", "SSD_DELIVERY_PUBLICATION.json"}:
        raise RuntimeError("publication exact file set invalid")
    if any(path.stat().st_mode & 0o222 for path in [delivery, *delivery.iterdir()]):
        raise RuntimeError("publication remains writable")
    return publication


def publish(paths: Paths, sources: list[Path], audit: dict[str, Any]) -> Path:
    captured = []
    for index, source in enumerate(sorted(set(sources), key=str)):
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"unsafe publication source: {source}")
        raw = source.read_bytes()
        captured.append({
            "source": str(source),
            "destination_relative_name": f"payload_{index:04d}_{source.name}",
            "bytes": len(raw), "sha256": sha256_bytes(raw), "raw": raw,
        })
    rows = [{key: row[key] for key in ("source", "destination_relative_name", "bytes", "sha256")} for row in captured]
    manifest_raw = tsv_bytes(rows, ["source", "destination_relative_name", "bytes", "sha256"])
    content_id = sha256_bytes(manifest_raw)
    publications = paths.base / "immutable_deliveries"
    publications.mkdir(parents=True, exist_ok=True)
    final = publications / f"deepqc100_{content_id}"
    if final.exists():
        verify_publication(final)
        return final
    staging = publications / f".staging_reconcile_{content_id}_{os.getpid()}_{time.time_ns()}"
    os.mkdir(staging, 0o700)
    try:
        exclusive_write(staging / "PUBLICATION_MANIFEST.tsv", manifest_raw)
        for row in captured:
            exclusive_write(staging / row["destination_relative_name"], row["raw"])
        publication = {
            "schema_version": "pvrig_node1_ssd_content_addressed_delivery_v1",
            "status": "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH",
            "content_id": content_id,
            "candidate_count": EXPECTED_CANDIDATES,
            "tnp_eligible_count": EXPECTED_TNP_ELIGIBLE,
            "hard_fail_before_tnp_count": len(EXPECTED_HARD_FAILS),
            "igfold_pdb_count": EXPECTED_CANDIDATES,
            "payload_count": len(rows),
            "publication_manifest_sha256": content_id,
            "reconciliation_audit_sha256": sha256_bytes(json_bytes(audit)),
            "nfs_syncback_performed": False,
            "nfs_syncback_reason": "legacy NFS processes remain frozen under the exact identity guard",
            "required_next_action": "switch the downstream watcher input path to this immutable SSD delivery",
            "claim_boundary": CLAIM_BOUNDARY,
        }
        exclusive_write(staging / "SSD_DELIVERY_PUBLICATION.json", json_bytes(publication))
        os.mkdir(final, 0o700)
        receipt = staging / "SSD_DELIVERY_PUBLICATION.json"
        for source in sorted(path for path in staging.iterdir() if path != receipt):
            os.link(source, final / source.name)
        fsync_dir(final)
        # The publication receipt is linked only after all payload hashes close.
        for row in rows:
            destination = final / row["destination_relative_name"]
            if destination.stat().st_size != row["bytes"] or sha256_file(destination) != row["sha256"]:
                raise RuntimeError("final publication payload changed before receipt")
        os.link(receipt, final / receipt.name)
        os.chmod(final, 0o555)
        fsync_dir(final)
        fsync_dir(publications)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    verify_publication(final)
    return final


def commit_receipts(paths: Paths, delivery: Path, audit: dict[str, Any]) -> tuple[Path, Path]:
    publication = verify_publication(delivery)
    publication_path = delivery / "SSD_DELIVERY_PUBLICATION.json"
    publication_sha = sha256_file(publication_path)
    assert_old_nfs_guard(paths)
    receipt = {
        "schema_version": "pvrig_node1_ssd_deepqc_eligible92_igfold100_reconciliation_receipt_v2",
        "status": "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH",
        "created_at": utc_now(),
        "candidate_count": EXPECTED_CANDIDATES,
        "tnp_eligible_count": EXPECTED_TNP_ELIGIBLE,
        "tnp_hard_fail_count": len(EXPECTED_HARD_FAILS),
        "tnp_initial_valid_count": 85,
        "tnp_null_rerun_count": len(EXPECTED_TNP_NULL_RERUNS),
        "igfold_candidate_count": EXPECTED_CANDIDATES,
        "formal_64_36_success_claimed": False,
        "reconciliation_audit_sha256": sha256_bytes(json_bytes(audit)),
        "ssd_content_addressed_delivery": str(delivery),
        "ssd_publication_receipt_sha256": publication_sha,
        "nfs_syncback_performed": False,
        "old_nfs_process_tree_signaled": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_raw = json_bytes(receipt)
    if paths.canonical_recovery_receipt.exists():
        if paths.canonical_recovery_receipt.read_bytes() != receipt_raw:
            existing = read_json(paths.canonical_recovery_receipt)
            if existing.get("ssd_content_addressed_delivery") != str(delivery):
                raise RuntimeError("canonical recovery receipt conflict")
    else:
        exclusive_write(paths.canonical_recovery_receipt, receipt_raw)
    recovery_sha = sha256_file(paths.canonical_recovery_receipt)
    assert_old_nfs_guard(paths)
    verify_publication(delivery)
    switch = {
        "schema_version": "pvrig_node1_ssd_deepqc_path_switch_v1",
        "status": "PASS_SSD_DEEPQC_DELIVERY_PATH_SWITCHED",
        "created_at": utc_now(),
        "active_delivery_path": str(delivery),
        "content_id": publication["content_id"],
        "publication_receipt_sha256": publication_sha,
        "recovery_receipt_sha256": recovery_sha,
        "nfs_source_selected": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    switch_raw = json_bytes(switch)
    if paths.path_switch_receipt.exists():
        existing = read_json(paths.path_switch_receipt)
        if existing.get("active_delivery_path") != str(delivery):
            raise RuntimeError("path-switch receipt conflict")
    else:
        exclusive_write(paths.path_switch_receipt, switch_raw)
    return paths.canonical_recovery_receipt, paths.path_switch_receipt


def run(paths: Paths) -> dict[str, Any]:
    paths.reconciliation.mkdir(parents=True, exist_ok=True)
    lock_path = paths.reconciliation / "reconciliation.lock"
    lock = lock_path.open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError("another reconciliation controller holds the lock") from exc
    if not paths.prereg.is_file() or not paths.adapter.is_file():
        raise RuntimeError("frozen reconciliation deployment is incomplete")
    prereg = read_json(paths.prereg)
    if prereg.get("status") != "FROZEN_AFTER_V1_NULL_PAYLOAD_DIAGNOSIS_BEFORE_RERUN":
        raise RuntimeError("reconciliation preregistration status invalid")
    if set(prereg.get("expected_hard_fail_ids", [])) != EXPECTED_HARD_FAILS:
        raise RuntimeError("preregistered hard-fail set drift")
    if int(prereg.get("expected_tnp_eligible_count", -1)) != EXPECTED_TNP_ELIGIBLE:
        raise RuntimeError("preregistered TNP count drift")
    if set(prereg.get("expected_tnp_null_rerun_ids", [])) != EXPECTED_TNP_NULL_RERUNS:
        raise RuntimeError("preregistered null TNP rerun set drift")
    if int(prereg.get("expected_initial_valid_tnp_payload_count", -1)) != 85:
        raise RuntimeError("preregistered initial valid TNP count drift")
    if int(prereg.get("expected_vhh_monomer_pdb_count", -1)) != EXPECTED_CANDIDATES:
        raise RuntimeError("preregistered IgFold count drift")
    assert_old_nfs_guard(paths)
    candidates, tnp_rows, eligible, hard = validate_ad_hoc_terminal(paths)
    tnp_manifest = reconcile_tnp_outputs(paths, candidates, eligible)
    assert_old_nfs_guard(paths)
    igfold_manifest = freeze_igfold100(paths, candidates)
    assert_old_nfs_guard(paths)

    hard_rows = []
    by_id = {row["id"]: row for row in tnp_rows}
    for cid in sorted(hard):
        hard_rows.append({
            "candidate_id": cid,
            "sequence_sha256": sha256_bytes(candidates[cid].encode()),
            "L1_numbering_integrity": by_id[cid]["L1_numbering_integrity"],
            "L2_vhh_features": by_id[cid]["L2_vhh_features"],
            "L1_reasons": by_id[cid].get("L1_reasons", ""),
            "L2_reasons": by_id[cid].get("L2_reasons", ""),
            "tnp_result_present": False,
            "status": "PRESERVED_FROZEN_L2_HARD_FAIL",
        })
    tnp_manifest_path = paths.reconciliation / "tnp_eligible92_manifest.tsv"
    hard_manifest_path = paths.reconciliation / "hard_fail8_manifest.tsv"
    igfold_manifest_path = paths.reconciliation / "igfold100_manifest.tsv"
    write_or_verify(tnp_manifest_path, tsv_bytes(tnp_manifest))
    write_or_verify(hard_manifest_path, tsv_bytes(hard_rows))
    write_or_verify(igfold_manifest_path, tsv_bytes(igfold_manifest))
    terminal_updated_at = read_json(paths.root / "status/deepqc_ssd_resume_status.json")["updated_at"]
    audit = {
        "schema_version": "pvrig_node1_ssd_deepqc_eligible92_igfold100_reconciliation_audit_v2",
        "status": "PASS_RECONCILED_85_PLUS_7_TNP_IGFOLD100",
        "created_at": terminal_updated_at,
        "candidate_count": len(candidates),
        "tnp_eligible_count": len(tnp_manifest),
        "tnp_initial_valid_count": sum(row["origin"] == "AD_HOC_VALID_PAYLOAD" for row in tnp_manifest),
        "tnp_null_rerun_count": sum(row["origin"] == "RECONCILIATION_NULL_RERUN" for row in tnp_manifest),
        "hard_fail_before_tnp_count": len(hard_rows),
        "igfold_pdb_count": len(igfold_manifest),
        "igfold_ad_hoc_count": sum(row["origin"] == "AD_HOC_SSD_RUN" for row in igfold_manifest),
        "igfold_supplement_count": sum(row["origin"] == "RECONCILIATION_SUPPLEMENT" for row in igfold_manifest),
        "hard_fail_ids": sorted(hard),
        "input_fasta_sha256": sha256_file(paths.root / "inputs/pre_shortlist100.fasta"),
        "preregistration_sha256": sha256_file(paths.prereg),
        "adapter_sha256": sha256_file(paths.adapter),
        "formal_recovery_sha256": sha256_file(paths.formal_recovery),
        "formal_64_36_success_claimed": False,
        "tnp_manifest_sha256": sha256_file(tnp_manifest_path),
        "hard_fail_manifest_sha256": sha256_file(hard_manifest_path),
        "igfold_manifest_sha256": sha256_file(igfold_manifest_path),
        "nfs_syncback_performed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path = paths.reconciliation / "reconciliation_audit.json"
    write_or_verify(audit_path, json_bytes(audit))
    sources = [
        paths.prereg, paths.adapter,
        paths.root / "run_deepqc.sh", paths.root / "deepqc_config.json", paths.root / "input_audit.json",
        paths.root / "inputs/pre_shortlist100.fasta", paths.root / "inputs/pre_shortlist100.tsv",
        paths.root / "reports_ssd/tnp_summary.tsv", paths.root / "reports_ssd/tnp_resume_merge.json",
        paths.root / "reports_ssd/deepqc_combined_summary.tsv", paths.root / "reports_ssd/deepqc_ssd_complete.json",
        paths.root / "status/deepqc_ssd_resume_status.json",
        tnp_manifest_path, hard_manifest_path, igfold_manifest_path, audit_path,
    ]
    sources.extend(Path(row["result_json"]) for row in tnp_manifest)
    for row in igfold_manifest:
        sources.extend([Path(row["sequence_fasta"]), Path(row["pdb"]), Path(row["command_log"])])
    delivery = publish(paths, sources, audit)
    assert_old_nfs_guard(paths)
    recovery_receipt, switch_receipt = commit_receipts(paths, delivery, audit)
    return {
        "status": "PASS_SSD_RECONCILIATION_PUBLISHED_AND_PATH_SWITCHED",
        "delivery": str(delivery),
        "content_id": delivery.name.removeprefix("deepqc100_"),
        "recovery_receipt": str(recovery_receipt),
        "recovery_receipt_sha256": sha256_file(recovery_receipt),
        "path_switch_receipt": str(switch_receipt),
        "path_switch_receipt_sha256": sha256_file(switch_receipt),
        "audit": str(audit_path),
        "audit_sha256": sha256_file(audit_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--show-active", action="store_true")
    args = parser.parse_args()
    paths = Paths()
    if args.show_active:
        print(json.dumps(active_reconciliation_producers(paths), indent=2, sort_keys=True))
        return 0
    if not args.run:
        parser.error("one of --run or --show-active is required")
    try:
        result = run(paths)
    except Exception as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
