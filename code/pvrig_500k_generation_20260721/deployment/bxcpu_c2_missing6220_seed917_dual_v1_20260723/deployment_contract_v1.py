#!/usr/bin/env python3
"""Pure validation helpers for the C2-only 6,220-candidate bxcpu deployment."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable


PROJECT = "pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723"
HANDOFF_PACKAGE_VERSION = "pvrig_c2_missing6220_seed917_dual_handoff_v1"
EXPECTED_CANDIDATES = 6_220
EXPECTED_JOBS = 12_440
SHARD_COUNT = 8
EXPECTED_SHARD_SIZES = (1_555,) * SHARD_COUNT
SEED = "917"
CONFORMATIONS = {"8x6b", "9e6y"}
DOCKING_STAGE = "C2_GAP_STAGE1_ALL6220_SEED917"
PROTOCOL_CORE = "8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3"
CFG_HASHES = {
    "8x6b": "e163c08b04a1b3315589b17ab3b439ddd791224da6419154a3697161f79d5e88",
    "9e6y": "981649a809b861fc99c1838d4ab62144e10441485ae8b665eff412435f2b577e",
}
HEX64 = re.compile(r"[0-9a-f]{64}")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_tsv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"missing TSV header: {path}")
        return list(reader.fieldnames), list(reader)


def write_tsv(path: pathlib.Path, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def is_terminal_state(state: str) -> bool:
    return state in {"SUCCESS", "FAILED", "FAILED_MAX_ATTEMPTS"}


def require_hex64(value: object, label: str) -> str:
    text = str(value or "")
    if HEX64.fullmatch(text) is None:
        raise ValueError(f"{label} is not a lowercase SHA256")
    return text


def safe_relative(value: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    return path


def load_frozen_anchors(path: pathlib.Path) -> dict[str, Any]:
    data = read_json(path)
    if data.get("schema_version") != "pvrig.c2_missing6220.bxcpu_input_anchors.v1":
        raise ValueError("input anchor schema mismatch")
    if data.get("status") != "SEALED_NODE1_HANDOFF_PASS_READY_FOR_BXCPU_PREFLIGHT":
        raise ValueError("input anchors are not sealed")
    if int(data.get("required_candidates", -1)) != EXPECTED_CANDIDATES:
        raise ValueError("input anchor candidate count mismatch")
    if int(data.get("required_jobs", -1)) != EXPECTED_JOBS:
        raise ValueError("input anchor job count mismatch")
    if data.get("project") != PROJECT:
        raise ValueError("input anchor project mismatch")
    if data.get("docking_started") is not False:
        raise ValueError("input anchors say Docking already started")
    if data.get("overlap1280_reuse_authorized") is not False:
        raise ValueError("overlap1280 reuse is forbidden")
    for key in (
        "archive_sha256", "handoff_receipt_sha256", "job_manifest_sha256",
        "deployment_bundle_receipt_sha256",
    ):
        require_hex64(data.get(key), key)
    if int(data.get("archive_bytes", 0)) <= 0:
        raise ValueError("archive_bytes must be positive")
    return data


def validate_handoff_receipt(
    receipt: dict[str, Any], *, expected_candidates: int = EXPECTED_CANDIDATES,
    expected_jobs: int = EXPECTED_JOBS,
) -> None:
    if receipt.get("status") != "READY_FOR_EXTERNAL_DOCKING_SUBMISSION":
        raise ValueError("handoff receipt status is not ready")
    if receipt.get("package_version") != HANDOFF_PACKAGE_VERSION:
        raise ValueError("handoff package version mismatch")
    if receipt.get("production") is not True:
        raise ValueError("handoff is not production")
    if receipt.get("docking_started") is not False:
        raise ValueError("handoff says Docking already started")
    if receipt.get("overlap1280_reuse_authorized") is not False:
        raise ValueError("handoff authorizes forbidden overlap1280 reuse")
    counts = receipt.get("counts", {})
    if int(counts.get("candidates", -1)) != expected_candidates:
        raise ValueError("handoff candidate count mismatch")
    if int(counts.get("jobs", -1)) != expected_jobs:
        raise ValueError("handoff job count mismatch")
    protocol = receipt.get("protocol", {})
    if str(protocol.get("seed")) != SEED:
        raise ValueError("handoff seed mismatch")
    if set(protocol.get("conformations", [])) != CONFORMATIONS:
        raise ValueError("handoff conformations mismatch")
    if protocol.get("protocol_core_sha256") != PROTOCOL_CORE:
        raise ValueError("handoff protocol core mismatch")
    if protocol.get("cfg_hashes") != CFG_HASHES:
        raise ValueError("handoff cfg hashes mismatch")


def validate_manifest_rows(
    rows: list[dict[str, str]], *, expected_candidates: int = EXPECTED_CANDIDATES,
    expected_jobs: int = EXPECTED_JOBS,
) -> None:
    if len(rows) != expected_jobs:
        raise ValueError(f"job manifest count mismatch: {len(rows)} != {expected_jobs}")
    job_ids: set[str] = set()
    job_hashes: set[str] = set()
    priorities: set[int] = set()
    pairs: dict[str, set[str]] = {}
    sequence_hash: dict[str, str] = {}
    monomer_hash: dict[str, str] = {}
    required = {
        "job_id", "priority", "entity_type", "entity_id", "conformation", "seed",
        "sequence_sha256", "monomer_sha256", "protocol_core_sha256", "cfg_hash",
        "job_hash", "docking_stage",
    }
    for row in rows:
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"job manifest missing fields: {missing}")
        job_id = row["job_id"]
        if not job_id or job_id in job_ids:
            raise ValueError(f"duplicate/empty job_id: {job_id!r}")
        job_ids.add(job_id)
        require_hex64(row["job_hash"], "job_hash")
        if row["job_hash"] in job_hashes:
            raise ValueError("duplicate job_hash")
        job_hashes.add(row["job_hash"])
        priority = int(row["priority"])
        if priority in priorities:
            raise ValueError("duplicate priority")
        priorities.add(priority)
        if row["entity_type"] != "candidate":
            raise ValueError("non-candidate entity in C2 missing manifest")
        if row["seed"] != SEED:
            raise ValueError("non-seed917 job in C2 missing manifest")
        conformation = row["conformation"]
        if conformation not in CONFORMATIONS:
            raise ValueError("unexpected receptor conformation")
        if row["protocol_core_sha256"] != PROTOCOL_CORE:
            raise ValueError("protocol core mismatch")
        if row["cfg_hash"] != CFG_HASHES[conformation]:
            raise ValueError("cfg hash mismatch")
        if row["docking_stage"] != DOCKING_STAGE:
            raise ValueError("docking_stage is not the C2-only gap stage")
        entity = row["entity_id"]
        pairs.setdefault(entity, set())
        if conformation in pairs[entity]:
            raise ValueError(f"duplicate candidate/conformation pair: {entity}/{conformation}")
        pairs[entity].add(conformation)
        seq = require_hex64(row["sequence_sha256"], "sequence_sha256")
        monomer = require_hex64(row["monomer_sha256"], "monomer_sha256")
        if entity in sequence_hash and sequence_hash[entity] != seq:
            raise ValueError("candidate sequence hash differs between receptors")
        if entity in monomer_hash and monomer_hash[entity] != monomer:
            raise ValueError("candidate monomer hash differs between receptors")
        sequence_hash[entity] = seq
        monomer_hash[entity] = monomer
    if len(pairs) != expected_candidates:
        raise ValueError(f"candidate count mismatch: {len(pairs)} != {expected_candidates}")
    if any(confs != CONFORMATIONS for confs in pairs.values()):
        raise ValueError("candidate dual-receptor pair closure failed")
    if priorities != set(range(1, expected_jobs + 1)):
        raise ValueError("priorities are not exactly 1..expected_jobs")


def split_contiguous(rows: list[dict[str, str]], *, shard_count: int = SHARD_COUNT) -> list[list[dict[str, str]]]:
    if shard_count <= 0 or len(rows) % shard_count:
        raise ValueError("rows must divide exactly into shard_count")
    width = len(rows) // shard_count
    return [rows[index * width:(index + 1) * width] for index in range(shard_count)]


def verify_sha256_manifest(root: pathlib.Path, manifest: pathlib.Path) -> int:
    listed: set[pathlib.PurePosixPath] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        digest, sep, relative_text = line.partition("  ")
        if sep != "  ":
            raise ValueError("malformed SHA256SUMS line")
        require_hex64(digest, "listed sha256")
        relative = safe_relative(relative_text)
        if relative in listed:
            raise ValueError("duplicate SHA256SUMS path")
        listed.add(relative)
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"listed path missing/non-regular/symlinked: {relative}")
        if sha256_file(path) != digest:
            raise ValueError(f"listed path hash mismatch: {relative}")
    actual = {
        pathlib.PurePosixPath(path.relative_to(root).as_posix())
        for path in root.rglob("*")
        if path.is_file() and path.name != manifest.name
    }
    symlinks = [path for path in root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise ValueError(f"handoff contains symlinks: {symlinks[:3]}")
    if listed != actual:
        raise ValueError(
            f"SHA256SUMS file-set mismatch missing={sorted(map(str, actual-listed))[:3]} "
            f"extra={sorted(map(str, listed-actual))[:3]}"
        )
    return len(listed)
