#!/usr/bin/env python3
"""Recover and select hash-closed Pilot64 V1.2 ``4_emref`` Top-8 poses.

The adapter reuses the frozen V1.1 Pilot64 runs only at the HADDOCK ``4_emref``
stage.  It synchronizes the exact files referenced by ``io.json``, verifies the
frozen run inputs, and selects a deterministic Top-8 by HADDOCK score.  The
result is development-only computational geometry evidence.
"""
from __future__ import annotations

import argparse
import base64
import configparser
import csv
import gzip
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_MANIFEST = (
    EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package_v2/manifests/run_manifest.csv"
)
DEFAULT_FAILED_AUDIT = EXP_DIR / "audits/phase2_v3_p2_docking_gold_v2_audit.json"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_node1_selected"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_v1_2_pilot64_emref_recovery_audit.json"
DEFAULT_REMOTE_ROOT = "/data/qlyu/projects/pvrig_v3_p2_dual_docking_pilot64_v2_20260714"

PROTOCOL_ID = "DG_A_PVRIG_V1_2_DEV"
SOURCE_PROTOCOL_ID = "DG_A_PILOT64_V1_1"
SOURCE_STAGE = "4_emref"
SOURCE_PROTOCOL = "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1"
EXECUTION_MODE = "REUSE_HASH_CLOSED_EMREF"
FORMAL_ELIGIBLE = False
K = 8
CLAIM_BOUNDARY = (
    "hash-closed fixed-Top-8 HADDOCK 4_emref reuse for V1.2 development; "
    "not formal validation and not experimental binding, affinity, or blocking truth"
)

SMOKE_PILOTS = ("P2PILOT_001", "P2PILOT_033")
RECEPTORS = ("8X6B", "9E6Y")
SEED_ROLES = ("main", "replicate")
EXPECTED_COHORTS = {
    "smoke8": {"runs": 8, "source_poses": 78, "selected_poses": 64},
    "failed52": {"runs": 52, "source_poses": 518, "selected_poses": 416},
}
SEED_BY_RECEPTOR_ROLE = {
    ("8X6B", "main"): 917,
    ("8X6B", "replicate"): 10917,
    ("9E6Y", "main"): 20917,
    ("9E6Y", "replicate"): 30917,
}

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^P2PILOT_[0-9]{3}__(8X6B|9E6Y)__(main|replicate)$")
RANGE_RE = re.compile(r"^([1-9][0-9]*)-([1-9][0-9]*)$")

REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "protocol_id",
    "run_id",
    "pilot_rank",
    "pilot_id",
    "source_cohort",
    "source_candidate_id",
    "receptor_id",
    "seed_role",
    "iniseed",
    "topoaa_iniseed",
    "rigidbody_iniseed",
    "rigidbody_seed_start",
    "rigidbody_seed_end",
    "config_relpath",
    "config_sha256",
    "run_workspace_relpath",
    "run_dir_relpath",
    "completion_relpath",
    "monomer_relpath",
    "monomer_sha256",
    "receptor_relpath",
    "receptor_sha256",
    "restraint_relpath",
    "restraint_sha256",
    "hotspot_relpath",
    "hotspot_sha256",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "expected_min_poses",
    "expected_min_clusters",
    "per_candidate_failure_tolerance_override",
    "tolerance_relaxed",
    "haddock3_version_contract",
}

CSV_FIELDS = (
    "schema_version",
    "protocol_id",
    "source_protocol_id",
    "source_protocol",
    "source_stage",
    "selection_cohort",
    "run_id",
    "case_id",
    "candidate_id",
    "family",
    "role",
    "pilot_rank",
    "pilot_id",
    "source_cohort",
    "source_candidate_id",
    "source_docking_receptor",
    "receptor_id",
    "seed_role",
    "iniseed",
    "topoaa_iniseed",
    "rigidbody_iniseed",
    "rigidbody_seed_start",
    "rigidbody_seed_end",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "canonical_rank",
    "source_output_index",
    "source_output_file",
    "source_score",
    "source_seed",
    "source_pose_relpath",
    "remote_source_pose_relpath",
    "source_pose_format",
    "source_pose_sha256",
    "source_pose_bytes",
    "compressed_source_sha256",
    "compressed_source_bytes",
    "decompressed_coordinate_sha256",
    "decompressed_coordinate_bytes",
    "vhh_chain_id",
    "vhh_atom_count",
    "vhh_residue_count",
    "vhh_atom_heavy_atom_count",
    "vhh_atom_residue_count",
    "vhh_hetatm_heavy_atom_count",
    "vhh_hetatm_residue_count",
    "vhh_excluded_hydrogen_or_deuterium_count",
    "vhh_chain_inventory_json",
    "pvrig_chain_id",
    "pvrig_atom_count",
    "pvrig_residue_count",
    "pvrig_atom_heavy_atom_count",
    "pvrig_atom_residue_count",
    "pvrig_hetatm_heavy_atom_count",
    "pvrig_hetatm_residue_count",
    "pvrig_excluded_hydrogen_or_deuterium_count",
    "pvrig_chain_inventory_json",
    "completion_status",
    "config_relpath",
    "completion_relpath",
    "monomer_relpath",
    "receptor_relpath",
    "restraint_relpath",
    "hotspot_relpath",
    "emref_params_relpath",
    "completion_sha256",
    "config_sha256",
    "monomer_sha256",
    "receptor_sha256",
    "restraint_sha256",
    "hotspot_sha256",
    "emref_params_sha256",
    "source_io_sha256",
    "source_io_relpath",
    "remote_source_io_relpath",
    "source_manifest_relpath",
    "source_manifest_sha256",
    "source_manifest_row_sha256",
    "source_failed_audit_relpath",
    "source_failed_audit_sha256",
    "remote_inventory_request_sha256",
    "remote_file_hash_chain",
    "local_file_hash_chain",
    "selector_implementation_relpath",
    "selector_implementation_sha256",
    "execution_mode",
    "formal_eligible",
    "claim_boundary",
    "selection_row_sha256",
)


class RecoveryError(RuntimeError):
    """Raised when the Pilot64 emref reuse contract cannot be proven."""


@dataclass(frozen=True)
class ManifestData:
    path: Path
    sha256: str
    rows: tuple[dict[str, str], ...]
    row_hashes: Mapping[str, str]


@dataclass(frozen=True)
class PoseRecord:
    output_index: int
    file_name: str
    score: float
    seed: int
    remote_relpath: str
    local_path: Path
    source_sha256: str
    source_bytes: int
    coordinate_sha256: str
    coordinate_bytes: int
    vhh_inventory: Mapping[str, Any]
    pvrig_inventory: Mapping[str, Any]


SyncRunner = Callable[[Mapping[str, Any], Path, str, str, str], None]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise RecoveryError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: Mapping[str, Any], hash_field: str) -> str:
    return sha256_bytes(
        canonical_json({key: value for key, value in row.items() if key != hash_field}).encode(
            "utf-8"
        )
    )


def workspace_relative(path: Path, workspace_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise RecoveryError(f"Path is outside workspace root: {resolved}") from error


def safe_relative_path(raw: str, label: str) -> str:
    value = str(raw).strip()
    if not value or "\x00" in value or "\\" in value:
        raise RecoveryError(f"Invalid {label} relative path: {raw!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryError(f"Unsafe {label} relative path: {raw!r}")
    return path.as_posix()


def contained_path(root: Path, relpath: str, label: str) -> Path:
    safe = safe_relative_path(relpath, label)
    root_resolved = root.resolve()
    path = (root_resolved / PurePosixPath(safe)).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as error:
        raise RecoveryError(f"{label} escapes root {root_resolved}: {relpath}") from error
    return path


def parse_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise RecoveryError(f"{label} is not an integer: {value!r}")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise RecoveryError(f"{label} is not an integer: {value!r}") from error
    return parsed


def parse_float(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise RecoveryError(f"{label} is not numeric: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise RecoveryError(f"{label} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise RecoveryError(f"{label} is not finite: {value!r}")
    return parsed


def require_hash(value: str, label: str) -> str:
    normalized = str(value).strip().lower()
    if not HASH_RE.fullmatch(normalized):
        raise RecoveryError(f"{label} is not a lowercase SHA256: {value!r}")
    return normalized


def parse_range(value: str, label: str) -> tuple[int, int]:
    match = RANGE_RE.fullmatch(str(value).strip())
    if not match:
        raise RecoveryError(f"Malformed {label}: {value!r}")
    start, end = (int(item) for item in match.groups())
    if start > end:
        raise RecoveryError(f"Reversed {label}: {value!r}")
    return start, end


def validate_manifest_row(row: Mapping[str, str], row_number: int) -> dict[str, str]:
    missing = sorted(field for field in REQUIRED_MANIFEST_FIELDS if not str(row.get(field, "")).strip())
    if missing:
        raise RecoveryError(f"Manifest row {row_number} is missing fields: {missing}")
    normalized = {str(key): str(value) for key, value in row.items()}
    run_id = normalized["run_id"].strip()
    match = RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise RecoveryError(f"Malformed Pilot64 run_id at row {row_number}: {run_id!r}")
    receptor, seed_role = match.groups()
    if normalized["protocol_id"] != SOURCE_PROTOCOL_ID:
        raise RecoveryError(f"Unexpected source protocol for {run_id}: {normalized['protocol_id']}")
    if normalized["receptor_id"] != receptor or normalized["seed_role"] != seed_role:
        raise RecoveryError(f"run_id/receptor/seed-role mismatch for {run_id}")
    if run_id != f"{normalized['pilot_id']}__{receptor}__{seed_role}":
        raise RecoveryError(f"run_id/pilot_id mismatch for {run_id}")
    expected_seed = SEED_BY_RECEPTOR_ROLE[(receptor, seed_role)]
    for field in ("iniseed", "rigidbody_iniseed"):
        if parse_int(normalized[field], f"{run_id}.{field}") != expected_seed:
            raise RecoveryError(f"Frozen seed mismatch for {run_id}.{field}")
    if parse_int(normalized["topoaa_iniseed"], f"{run_id}.topoaa_iniseed") != 917:
        raise RecoveryError(f"Frozen topoaa seed mismatch for {run_id}")
    if parse_int(normalized["rigidbody_seed_start"], f"{run_id}.rigidbody_seed_start") != expected_seed + 1:
        raise RecoveryError(f"Rigidbody seed start mismatch for {run_id}")
    if parse_int(normalized["rigidbody_seed_end"], f"{run_id}.rigidbody_seed_end") < expected_seed + 1:
        raise RecoveryError(f"Rigidbody seed end mismatch for {run_id}")
    if parse_int(normalized["expected_min_poses"], f"{run_id}.expected_min_poses") != K:
        raise RecoveryError(f"Expected-min-pose contract mismatch for {run_id}")
    if normalized["per_candidate_failure_tolerance_override"].lower() != "false":
        raise RecoveryError(f"Failure-tolerance override is not frozen false for {run_id}")
    if normalized["tolerance_relaxed"].lower() != "false":
        raise RecoveryError(f"Tolerance relaxation is not frozen false for {run_id}")

    ranges = [parse_range(normalized[f"cdr{index}_range"], f"{run_id}.cdr{index}_range") for index in (1, 2, 3)]
    if not (ranges[0][1] < ranges[1][0] and ranges[1][1] < ranges[2][0]):
        raise RecoveryError(f"CDR ranges overlap or are out of order for {run_id}: {ranges}")

    expected_paths = {
        "config_relpath": f"runs/{run_id}/{run_id}.cfg",
        "run_workspace_relpath": f"runs/{run_id}",
        "run_dir_relpath": f"runs/{run_id}/run_{run_id}",
        "completion_relpath": f"runs/{run_id}/{run_id}.complete.json",
    }
    for field in (
        "config_relpath",
        "run_workspace_relpath",
        "run_dir_relpath",
        "completion_relpath",
        "monomer_relpath",
        "receptor_relpath",
        "restraint_relpath",
        "hotspot_relpath",
    ):
        normalized[field] = safe_relative_path(normalized[field], f"{run_id}.{field}")
    for field, expected in expected_paths.items():
        if normalized[field] != expected:
            raise RecoveryError(f"Frozen path mismatch for {run_id}.{field}: {normalized[field]}")
    for field in (
        "config_sha256",
        "monomer_sha256",
        "receptor_sha256",
        "restraint_sha256",
        "hotspot_sha256",
    ):
        normalized[field] = require_hash(normalized[field], f"{run_id}.{field}")
    return normalized


def read_manifest(path: Path) -> ManifestData:
    path = path.resolve()
    if not path.is_file():
        raise RecoveryError(f"Run manifest is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise RecoveryError(f"Run manifest has no header: {path}")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise RecoveryError(f"Run manifest has duplicate fields: {path}")
        missing = sorted(REQUIRED_MANIFEST_FIELDS - set(reader.fieldnames))
        if missing:
            raise RecoveryError(f"Run manifest is missing columns: {missing}")
        raw_rows = list(reader)
    if not raw_rows:
        raise RecoveryError("Run manifest is empty")
    rows: list[dict[str, str]] = []
    row_hashes: dict[str, str] = {}
    for row_number, raw in enumerate(raw_rows, start=2):
        row = validate_manifest_row(raw, row_number)
        run_id = row["run_id"]
        if run_id in row_hashes:
            raise RecoveryError(f"Duplicate run_id in manifest: {run_id}")
        rows.append(row)
        row_hashes[run_id] = sha256_bytes(canonical_json(raw).encode("utf-8"))
    return ManifestData(path, sha256_file(path), tuple(rows), row_hashes)


def read_failed_audit(path: Path, manifest_run_ids: set[str]) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    path = path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Cannot read V1.1 failed audit: {path}") from error
    if not isinstance(payload, dict):
        raise RecoveryError("V1.1 failed audit is not an object")
    if payload.get("protocol_id") != SOURCE_PROTOCOL_ID:
        raise RecoveryError("V1.1 failed audit protocol mismatch")
    if payload.get("status") != "FAIL_DOCKING_GOLD_NOT_VALIDATED":
        raise RecoveryError("V1.1 failed audit status is not the frozen rejection status")
    raw_failures = payload.get("failed_receptor_runs")
    if not isinstance(raw_failures, list):
        raise RecoveryError("V1.1 failed audit has no failed_receptor_runs list")
    failed: list[str] = []
    for index, item in enumerate(raw_failures):
        if not isinstance(item, dict) or not str(item.get("run_id", "")).strip():
            raise RecoveryError(f"Invalid failed_receptor_runs[{index}]")
        failed.append(str(item["run_id"]).strip())
    if len(failed) != 52 or len(set(failed)) != 52:
        raise RecoveryError(f"Expected 52 unique frozen failed runs, found {len(failed)}/{len(set(failed))}")
    unknown = sorted(set(failed) - manifest_run_ids)
    if unknown:
        raise RecoveryError(f"Failed audit contains unknown run IDs: {unknown}")
    return payload, sha256_file(path), tuple(sorted(failed))


def select_rows(
    manifest: ManifestData,
    failed_run_ids: Sequence[str],
    cohort: str | None,
    explicit_run_ids: Sequence[str] | None,
) -> tuple[str, list[dict[str, str]], dict[str, int] | None]:
    by_id = {row["run_id"]: row for row in manifest.rows}
    explicit = list(explicit_run_ids or [])
    if explicit and cohort:
        raise RecoveryError("Explicit --run-id and --cohort are mutually exclusive")
    if explicit:
        if len(set(explicit)) != len(explicit):
            raise RecoveryError("Duplicate explicit run IDs are not allowed")
        missing = sorted(set(explicit) - set(by_id))
        if missing:
            raise RecoveryError(f"Unknown explicit run IDs: {missing}")
        label = "explicit"
        selected_ids = sorted(explicit)
        expected = None
    elif cohort == "smoke8":
        selected_ids = sorted(
            f"{pilot}__{receptor}__{role}"
            for pilot in SMOKE_PILOTS
            for receptor in RECEPTORS
            for role in SEED_ROLES
        )
        missing = sorted(set(selected_ids) - set(by_id))
        if missing:
            raise RecoveryError(f"Smoke8 manifest closure is incomplete: {missing}")
        label = cohort
        expected = EXPECTED_COHORTS[cohort]
    elif cohort == "failed52":
        selected_ids = sorted(failed_run_ids)
        label = cohort
        expected = EXPECTED_COHORTS[cohort]
    else:
        raise RecoveryError("Choose --cohort smoke8|failed52 or at least one --run-id")
    rows = [by_id[run_id] for run_id in selected_ids]
    if expected and len(rows) != expected["runs"]:
        raise RecoveryError(f"{label} run count mismatch: {len(rows)} != {expected['runs']}")
    return label, rows, expected


def stage_relpaths(row: Mapping[str, str]) -> tuple[str, str]:
    run_dir = safe_relative_path(row["run_dir_relpath"], f"{row['run_id']}.run_dir_relpath")
    return f"{run_dir}/{SOURCE_STAGE}/io.json", f"{run_dir}/{SOURCE_STAGE}/params.cfg"


def build_sync_request(rows: Sequence[Mapping[str, str]], remote_root: str) -> dict[str, Any]:
    remote_path = PurePosixPath(remote_root)
    if not remote_root or not remote_path.is_absolute() or "\x00" in remote_root:
        raise RecoveryError(f"Remote root must be an absolute POSIX path: {remote_root!r}")
    required: set[str] = set()
    runs: list[dict[str, str]] = []
    for row in rows:
        io_relpath, params_relpath = stage_relpaths(row)
        required.update(
            {
                row["config_relpath"],
                row["completion_relpath"],
                row["monomer_relpath"],
                row["receptor_relpath"],
                row["restraint_relpath"],
                row["hotspot_relpath"],
                io_relpath,
                params_relpath,
            }
        )
        runs.append({"run_id": row["run_id"], "io_relpath": io_relpath})
    base = {
        "schema_version": "phase2_v3_p2_v1_2_pilot64_emref_sync_request_v1",
        "remote_root": remote_root,
        "required_relpaths": sorted(required),
        "runs": sorted(runs, key=lambda item: item["run_id"]),
    }
    request_sha256 = sha256_bytes(canonical_json(base).encode("utf-8"))
    return {
        **base,
        "request_sha256": request_sha256,
        "inventory_relpath": f".v1_2_remote_inventory/{request_sha256}.json",
    }


def resolve_io_pose_relpath(stage_relpath: str, file_name: str, available: Callable[[str], bool]) -> str:
    name = str(file_name).strip()
    path = PurePosixPath(name)
    if path.name != name or path.is_absolute() or not (name.endswith(".pdb") or name.endswith(".pdb.gz")):
        raise RecoveryError(f"Unsafe or unsupported emref file_name: {file_name!r}")
    stage = PurePosixPath(stage_relpath).parent
    options = [(stage / name).as_posix()]
    if name.endswith(".pdb"):
        options.append((stage / f"{name}.gz").as_posix())
    else:
        options.append((stage / name[:-3]).as_posix())
    matches = [item for item in options if available(item)]
    if len(matches) != 1:
        raise RecoveryError(f"Expected one coordinate source for {name!r}, found {matches}")
    return matches[0]


def expand_request_file_relpaths(root: Path, request: Mapping[str, Any]) -> list[str]:
    root = root.resolve()
    required = [safe_relative_path(item, "requested file") for item in request["required_relpaths"]]
    paths = set(required)
    for run in request["runs"]:
        io_relpath = safe_relative_path(run["io_relpath"], f"{run['run_id']}.io_relpath")
        io_path = contained_path(root, io_relpath, "emref io")
        try:
            payload = json.loads(io_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RecoveryError(f"Cannot read requested emref io: {io_path}") from error
        outputs = payload.get("output") if isinstance(payload, dict) else None
        if not isinstance(outputs, list):
            raise RecoveryError(f"Requested emref io has no output list: {io_path}")
        seen: set[str] = set()
        for index, record in enumerate(outputs):
            if not isinstance(record, dict):
                raise RecoveryError(f"{io_path} output[{index}] is not an object")
            file_name = str(record.get("file_name", "")).strip()
            if not file_name or file_name in seen:
                raise RecoveryError(f"Missing or duplicate file_name in {io_path} output[{index}]")
            seen.add(file_name)
            pose_relpath = resolve_io_pose_relpath(
                io_relpath,
                file_name,
                lambda relpath: contained_path(root, relpath, "pose").is_file(),
            )
            paths.add(pose_relpath)
    for relpath in paths:
        path = contained_path(root, relpath, "requested file")
        if not path.is_file() or path.stat().st_size == 0:
            raise RecoveryError(f"Requested file is missing or empty: {path}")
    return sorted(paths)


def file_inventory(root: Path, relpaths: Sequence[str]) -> dict[str, Any]:
    entries = []
    for relpath in sorted(relpaths):
        path = contained_path(root, relpath, "inventory file")
        entries.append({"relpath": relpath, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    chain = sha256_bytes("\n".join(canonical_json(entry) for entry in entries).encode("utf-8"))
    return {
        "file_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "file_hash_chain": chain,
        "files": entries,
    }


REMOTE_ARCHIVE_PY = r'''
import base64, hashlib, io, json, math, pathlib, sys, tarfile

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sha(data):
    return hashlib.sha256(data).hexdigest()

request = json.loads(base64.urlsafe_b64decode(sys.argv[1].encode("ascii")))
base = {key: request[key] for key in ("schema_version", "remote_root", "required_relpaths", "runs")}
if sha(canonical(base).encode("utf-8")) != request["request_sha256"]:
    raise SystemExit("request hash mismatch")
root = pathlib.Path(request["remote_root"]).resolve(strict=True)

def safe_rel(raw):
    value = str(raw).strip()
    path = pathlib.PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SystemExit("unsafe relative path: " + repr(raw))
    return path.as_posix()

def local(rel):
    rel = safe_rel(rel)
    path = (root / pathlib.PurePosixPath(rel)).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        raise SystemExit("path escapes remote root: " + rel)
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit("missing or empty requested file: " + rel)
    return path

paths = set(safe_rel(item) for item in request["required_relpaths"])
for run in request["runs"]:
    io_rel = safe_rel(run["io_relpath"])
    payload = json.loads(local(io_rel).read_text(encoding="utf-8"))
    outputs = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(outputs, list):
        raise SystemExit("emref io has no output list: " + io_rel)
    seen = set()
    for index, record in enumerate(outputs):
        if not isinstance(record, dict):
            raise SystemExit("emref output is not an object")
        name = str(record.get("file_name", "")).strip()
        pure = pathlib.PurePosixPath(name)
        if not name or name in seen or pure.name != name or pure.is_absolute() or not (name.endswith(".pdb") or name.endswith(".pdb.gz")):
            raise SystemExit("unsafe, missing, or duplicate emref file_name: " + repr(name))
        seen.add(name)
        stage = pathlib.PurePosixPath(io_rel).parent
        options = [(stage / name).as_posix()]
        options.append((stage / (name + ".gz")).as_posix() if name.endswith(".pdb") else (stage / name[:-3]).as_posix())
        matches = []
        for rel in options:
            try:
                path = local(rel)
            except (FileNotFoundError, SystemExit):
                continue
            matches.append((rel, path))
        if len(matches) != 1:
            raise SystemExit("expected one coordinate source for " + repr(name))
        paths.add(matches[0][0])

entries = []
for rel in sorted(paths):
    data = local(rel).read_bytes()
    entries.append({"relpath": rel, "sha256": sha(data), "bytes": len(data)})
inventory = {
    "schema_version": "phase2_v3_p2_v1_2_remote_file_inventory_v1",
    "request_sha256": request["request_sha256"],
    "file_count": len(entries),
    "total_bytes": sum(item["bytes"] for item in entries),
    "file_hash_chain": sha("\n".join(canonical(item) for item in entries).encode("utf-8")),
    "files": entries,
}
inventory_bytes = (canonical(inventory) + "\n").encode("utf-8")
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    for entry in entries:
        rel = entry["relpath"]
        info = tarfile.TarInfo(rel)
        info.size = entry["bytes"]
        info.mode = 0o644
        info.mtime = 0
        with local(rel).open("rb") as handle:
            archive.addfile(info, handle)
    info = tarfile.TarInfo(request["inventory_relpath"])
    info.size = len(inventory_bytes)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(inventory_bytes))
'''


def ssh_command_args(ssh_executable: str, host: str, request: Mapping[str, Any]) -> list[str]:
    if not ssh_executable.strip() or "\x00" in ssh_executable:
        raise RecoveryError("SSH executable is empty or invalid")
    if not host.strip() or "\x00" in host or any(character.isspace() for character in host):
        raise RecoveryError(f"SSH host is invalid: {host!r}")
    encoded = base64.urlsafe_b64encode(canonical_json(request).encode("utf-8")).decode("ascii")
    remote_command = shlex.join(["python3", "-c", REMOTE_ARCHIVE_PY, encoded])
    return [ssh_executable, host, remote_command]


def read_inventory_payload(payload: bytes, request: Mapping[str, Any]) -> dict[str, Any]:
    try:
        inventory = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError("Remote file inventory is not valid JSON") from error
    if not isinstance(inventory, dict):
        raise RecoveryError("Remote file inventory is not an object")
    if inventory.get("schema_version") != "phase2_v3_p2_v1_2_remote_file_inventory_v1":
        raise RecoveryError("Remote file inventory schema mismatch")
    if inventory.get("request_sha256") != request["request_sha256"]:
        raise RecoveryError("Remote file inventory request hash mismatch")
    files = inventory.get("files")
    if not isinstance(files, list) or not files:
        raise RecoveryError("Remote file inventory is empty")
    normalized = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise RecoveryError(f"Remote inventory files[{index}] is not an object")
        relpath = safe_relative_path(str(item.get("relpath", "")), "remote inventory file")
        if relpath in seen:
            raise RecoveryError(f"Duplicate remote inventory path: {relpath}")
        seen.add(relpath)
        normalized.append(
            {
                "relpath": relpath,
                "sha256": require_hash(str(item.get("sha256", "")), f"remote inventory {relpath}"),
                "bytes": parse_int(item.get("bytes"), f"remote inventory {relpath} bytes"),
            }
        )
    if normalized != sorted(normalized, key=lambda item: item["relpath"]):
        raise RecoveryError("Remote inventory files are not deterministically sorted")
    chain = sha256_bytes("\n".join(canonical_json(item) for item in normalized).encode("utf-8"))
    if chain != inventory.get("file_hash_chain"):
        raise RecoveryError("Remote inventory hash chain mismatch")
    if inventory.get("file_count") != len(normalized):
        raise RecoveryError("Remote inventory file count mismatch")
    if inventory.get("total_bytes") != sum(item["bytes"] for item in normalized):
        raise RecoveryError("Remote inventory byte count mismatch")
    return {**inventory, "files": normalized}


def safe_extract_archive(archive_path: Path, outdir: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    inventory_relpath = safe_relative_path(request["inventory_relpath"], "inventory member")
    try:
        archive = tarfile.open(archive_path, mode="r:*")
    except (OSError, tarfile.TarError) as error:
        raise RecoveryError(f"Cannot read remote archive: {archive_path}") from error
    with archive:
        members = archive.getmembers()
        names: list[str] = []
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            name = safe_relative_path(member.name, "archive member")
            if not member.isfile():
                raise RecoveryError(f"Remote archive contains non-regular member: {name}")
            if name in by_name:
                raise RecoveryError(f"Remote archive contains duplicate member: {name}")
            names.append(name)
            by_name[name] = member
        if inventory_relpath not in by_name:
            raise RecoveryError("Remote archive is missing its file inventory")
        inventory_handle = archive.extractfile(by_name[inventory_relpath])
        if inventory_handle is None:
            raise RecoveryError("Cannot read remote inventory archive member")
        inventory = read_inventory_payload(inventory_handle.read(), request)
        expected_names = {item["relpath"] for item in inventory["files"]} | {inventory_relpath}
        if set(names) != expected_names:
            raise RecoveryError(
                f"Remote archive member set mismatch: missing={sorted(expected_names-set(names))}, "
                f"extra={sorted(set(names)-expected_names)}"
            )
        expected_by_path = {item["relpath"]: item for item in inventory["files"]}
        for name in sorted(expected_by_path):
            handle = archive.extractfile(by_name[name])
            if handle is None:
                raise RecoveryError(f"Cannot read remote archive member: {name}")
            payload = handle.read()
            expected = expected_by_path[name]
            if len(payload) != expected["bytes"] or sha256_bytes(payload) != expected["sha256"]:
                raise RecoveryError(f"Remote archive payload hash mismatch: {name}")
            destination = contained_path(outdir, name, "archive destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
            os.replace(temporary, destination)
        inventory_destination = contained_path(outdir, inventory_relpath, "inventory destination")
        inventory_destination.parent.mkdir(parents=True, exist_ok=True)
        inventory_payload = (canonical_json(inventory) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile("wb", dir=inventory_destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(inventory_payload)
        os.replace(temporary, inventory_destination)
    return inventory


def sync_from_remote(
    request: Mapping[str, Any],
    outdir: Path,
    ssh_executable: str,
    host: str,
    _remote_root: str,
) -> None:
    outdir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb", prefix=f".{outdir.name}.v1_2.", suffix=".tar", dir=outdir.parent, delete=False
    ) as output:
        archive_path = Path(output.name)
        result = subprocess.run(
            ssh_command_args(ssh_executable, host, request),
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    try:
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[-4000:]
            raise RecoveryError(f"Remote emref archive command failed ({result.returncode}): {stderr}")
        safe_extract_archive(archive_path, outdir, request)
    finally:
        archive_path.unlink(missing_ok=True)


def load_and_verify_inventory(outdir: Path, request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    inventory_path = contained_path(outdir, request["inventory_relpath"], "persisted inventory")
    remote_inventory = read_inventory_payload(inventory_path.read_bytes(), request)
    expected_relpaths = expand_request_file_relpaths(outdir, request)
    remote_relpaths = [item["relpath"] for item in remote_inventory["files"]]
    if expected_relpaths != remote_relpaths:
        raise RecoveryError(
            f"Remote/local requested path closure mismatch: "
            f"missing={sorted(set(remote_relpaths)-set(expected_relpaths))}, "
            f"extra={sorted(set(expected_relpaths)-set(remote_relpaths))}"
        )
    local_inventory = file_inventory(outdir, expected_relpaths)
    if local_inventory["files"] != remote_inventory["files"]:
        raise RecoveryError("Remote/local file inventories differ")
    if local_inventory["file_hash_chain"] != remote_inventory["file_hash_chain"]:
        raise RecoveryError("Remote/local file hash chains differ")
    return remote_inventory, local_inventory


def read_coordinate_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if not raw:
        raise RecoveryError(f"Coordinate source is empty: {path}")
    if path.name.endswith(".gz"):
        try:
            coordinates = gzip.decompress(raw)
        except (OSError, EOFError) as error:
            raise RecoveryError(f"Cannot decompress coordinate source: {path}") from error
    else:
        coordinates = raw
    if not coordinates:
        raise RecoveryError(f"Decompressed coordinates are empty: {path}")
    return coordinates


def parse_chain_inventory(coordinates: bytes, path: Path) -> dict[str, dict[str, Any]]:
    try:
        text = coordinates.decode("ascii")
    except UnicodeDecodeError as error:
        raise RecoveryError(f"PDB is not ASCII: {path}") from error
    parsed = {"A": 0, "B": 0}
    heavy = {"A": 0, "B": 0}
    atom_heavy = {"A": 0, "B": 0}
    hetatm_heavy = {"A": 0, "B": 0}
    residues = {"A": set(), "B": set()}
    atom_residues = {"A": set(), "B": set()}
    hetatm_residues = {"A": set(), "B": set()}
    altlocs = {"A": set(), "B": set()}
    altloc_heavy = {"A": 0, "B": 0}
    for line_number, line in enumerate(text.splitlines(), start=1):
        record = line[:6].strip()
        if record not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54:
            raise RecoveryError(f"Truncated coordinate record in {path}:{line_number}")
        chain = line[21:22]
        if chain not in parsed:
            continue
        try:
            serial = int(line[6:11])
            residue_number = int(line[22:26])
            xyz = tuple(float(line[start:end]) for start, end in ((30, 38), (38, 46), (46, 54)))
        except ValueError as error:
            raise RecoveryError(f"Unparseable coordinate record in {path}:{line_number}") from error
        if serial < 1 or not all(math.isfinite(value) for value in xyz):
            raise RecoveryError(f"Invalid coordinate values in {path}:{line_number}")
        resname = line[17:20].strip()
        atom_name = line[12:16].strip()
        if not resname or not atom_name:
            raise RecoveryError(f"Missing residue/atom name in {path}:{line_number}")
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        parsed[chain] += 1
        is_heavy = element not in {"H", "D"} if element else not atom_name.upper().startswith(("H", "D"))
        if not is_heavy:
            continue
        residue_key = (resname, str(residue_number), line[26:27].strip())
        heavy[chain] += 1
        residues[chain].add(residue_key)
        if record == "ATOM":
            atom_heavy[chain] += 1
            atom_residues[chain].add(residue_key)
        else:
            hetatm_heavy[chain] += 1
            hetatm_residues[chain].add(residue_key)
        altloc = line[16:17].strip()
        if altloc:
            altlocs[chain].add(altloc)
            altloc_heavy[chain] += 1
    inventory: dict[str, dict[str, Any]] = {}
    for chain in ("A", "B"):
        inventory[chain] = {
            "chain": chain,
            "selection_rule": "heavy ATOM and HETATM records retained for pose protein chains",
            "parsed_atom_and_hetatm_count": parsed[chain],
            "selected_heavy_atom_count": heavy[chain],
            "selected_residue_count": len(residues[chain]),
            "atom_heavy_atom_count": atom_heavy[chain],
            "atom_residue_count": len(atom_residues[chain]),
            "hetatm_heavy_atom_count": hetatm_heavy[chain],
            "hetatm_residue_count": len(hetatm_residues[chain]),
            "excluded_hydrogen_or_deuterium_count": parsed[chain] - heavy[chain],
            "altloc_heavy_atom_count": altloc_heavy[chain],
            "altloc_labels": sorted(altlocs[chain]),
        }
    return inventory


def require_chain(inventory: Mapping[str, Mapping[str, Any]], chain: str, label: str, path: Path) -> None:
    if inventory[chain]["selected_heavy_atom_count"] < 1 or inventory[chain]["selected_residue_count"] < 1:
        raise RecoveryError(f"{label} has no heavy chain {chain} records: {path}")


def validate_file_hash(outdir: Path, row: Mapping[str, str], rel_field: str, hash_field: str) -> Path:
    path = contained_path(outdir, row[rel_field], f"{row['run_id']}.{rel_field}")
    observed = sha256_file(path)
    if observed != row[hash_field]:
        raise RecoveryError(
            f"Frozen hash mismatch for {row['run_id']}.{rel_field}: {observed} != {row[hash_field]}"
        )
    return path


def validate_completion(path: Path, row: Mapping[str, str], io_count: int) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Cannot read completion marker: {path}") from error
    if not isinstance(payload, dict):
        raise RecoveryError(f"Completion marker is not an object: {path}")
    expected = {
        "protocol_id": SOURCE_PROTOCOL_ID,
        "run_id": row["run_id"],
        "pilot_id": row["pilot_id"],
        "receptor_id": row["receptor_id"],
        "seed_role": row["seed_role"],
        "iniseed": parse_int(row["iniseed"], "manifest iniseed"),
        "config_sha256": row["config_sha256"],
        "monomer_sha256": row["monomer_sha256"],
        "receptor_sha256": row["receptor_sha256"],
        "per_candidate_failure_tolerance_override": False,
        "tolerance_relaxed": False,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise RecoveryError(f"Completion contract mismatch for {row['run_id']}.{field}")
    if payload.get("exit_code") != 0:
        raise RecoveryError(f"Completion exit code is not zero for {row['run_id']}")
    if payload.get("status") not in {"PASS_DOCKING_OUTPUT_COMPLETE", "FAIL_DOCKING_OUTPUT_INCOMPLETE"}:
        raise RecoveryError(f"Unexpected completion status for {row['run_id']}: {payload.get('status')}")
    stage_counts = payload.get("stage_output_counts")
    if not isinstance(stage_counts, dict) or stage_counts.get("emref") != io_count:
        raise RecoveryError(f"Completion/emref output count mismatch for {row['run_id']}")
    return payload


def validate_params(path: Path, row: Mapping[str, str]) -> None:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error) as error:
        raise RecoveryError(f"Cannot parse emref params: {path}") from error
    if not parser.has_section("emref"):
        raise RecoveryError(f"emref params has no [emref] section: {path}")
    expected_seed = parse_int(row["iniseed"], f"{row['run_id']}.iniseed")
    try:
        observed_seed = parser.getint("emref", "iniseed")
        tolerance = parser.getfloat("emref", "tolerance")
    except (ValueError, configparser.Error) as error:
        raise RecoveryError(f"Invalid emref seed/tolerance in {path}") from error
    if observed_seed != expected_seed or tolerance != 20.0:
        raise RecoveryError(f"Frozen emref params mismatch for {row['run_id']}")


def load_pose_records(outdir: Path, io_relpath: str) -> tuple[list[PoseRecord], dict[str, Any]]:
    io_path = contained_path(outdir, io_relpath, "emref io")
    try:
        payload = json.loads(io_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Cannot read emref io: {io_path}") from error
    outputs = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(outputs, list) or len(outputs) < K:
        count = len(outputs) if isinstance(outputs, list) else 0
        raise RecoveryError(f"emref output has {count} records, fewer than fixed K={K}: {io_path}")
    records: list[PoseRecord] = []
    audit_outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(outputs):
        if not isinstance(raw, dict):
            raise RecoveryError(f"emref output[{index}] is not an object: {io_path}")
        file_name = str(raw.get("file_name", "")).strip()
        if not file_name or file_name in seen:
            raise RecoveryError(f"Missing or duplicate emref file_name at output[{index}]: {io_path}")
        seen.add(file_name)
        score = parse_float(raw.get("score"), f"{io_path}.output[{index}].score")
        seed_value = parse_float(raw.get("seed"), f"{io_path}.output[{index}].seed")
        if not seed_value.is_integer():
            raise RecoveryError(f"Non-integer pose seed at output[{index}]: {io_path}")
        remote_relpath = resolve_io_pose_relpath(
            io_relpath,
            file_name,
            lambda relpath: contained_path(outdir, relpath, "pose").is_file(),
        )
        local_path = contained_path(outdir, remote_relpath, "pose")
        source = local_path.read_bytes()
        coordinates = read_coordinate_bytes(local_path)
        inventory = parse_chain_inventory(coordinates, local_path)
        require_chain(inventory, "A", "Pose VHH", local_path)
        require_chain(inventory, "B", "Pose PVRIG", local_path)
        record = PoseRecord(
            output_index=index,
            file_name=file_name,
            score=score,
            seed=int(seed_value),
            remote_relpath=remote_relpath,
            local_path=local_path,
            source_sha256=sha256_bytes(source),
            source_bytes=len(source),
            coordinate_sha256=sha256_bytes(coordinates),
            coordinate_bytes=len(coordinates),
            vhh_inventory=inventory["A"],
            pvrig_inventory=inventory["B"],
        )
        records.append(record)
        audit_outputs.append(
            {
                "source_output_index": index,
                "file_name": file_name,
                "score": format(score, ".17g"),
                "seed": int(seed_value),
                "remote_source_pose_relpath": remote_relpath,
                "source_pose_sha256": record.source_sha256,
                "source_pose_bytes": record.source_bytes,
                "decompressed_coordinate_sha256": record.coordinate_sha256,
                "decompressed_coordinate_bytes": record.coordinate_bytes,
                "vhh_chain_inventory": record.vhh_inventory,
                "pvrig_chain_inventory": record.pvrig_inventory,
            }
        )
    selected = sorted(records, key=lambda item: (item.score, item.output_index, item.file_name))[:K]
    if len(selected) != K:
        raise RecoveryError(f"Internal fixed-Top-8 selection failure: {io_path}")
    return selected, {"source_output_count": len(records), "outputs": audit_outputs}


def write_csv_atomic(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS), extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def build(
    manifest_path: Path,
    failed_audit_path: Path,
    outdir: Path,
    audit_path: Path,
    cohort: str | None = None,
    explicit_run_ids: Sequence[str] | None = None,
    output_csv: Path | None = None,
    inventory_only: bool = False,
    ssh_executable: str = "ssh.exe",
    host: str = "node1",
    remote_root: str = DEFAULT_REMOTE_ROOT,
    workspace_root: Path = WORKSPACE_ROOT,
    sync_runner: SyncRunner | None = None,
) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    failed_payload, failed_audit_sha256, failed_run_ids = read_failed_audit(
        failed_audit_path, {row["run_id"] for row in manifest.rows}
    )
    selection_label, selected_rows, expected = select_rows(
        manifest, failed_run_ids, cohort, explicit_run_ids
    )
    outdir = outdir.resolve()
    workspace_root = workspace_root.resolve()
    audit_path = audit_path.resolve()
    if output_csv is None:
        output_csv = outdir / f"v1_2_{selection_label}_emref_top8_selector.csv"
    output_csv = output_csv.resolve()
    if output_csv == audit_path:
        raise RecoveryError("Selector CSV and audit JSON paths must differ")
    request = build_sync_request(selected_rows, remote_root)
    runner = sync_runner or sync_from_remote
    if not inventory_only:
        outdir.mkdir(parents=True, exist_ok=True)
        runner(request, outdir, ssh_executable, host, remote_root)
    remote_inventory, local_inventory = load_and_verify_inventory(outdir, request)

    script_path = Path(__file__).resolve()
    script_sha256 = sha256_file(script_path)
    output_rows: list[dict[str, str]] = []
    run_audits: list[dict[str, Any]] = []
    source_pose_count = 0
    for row in selected_rows:
        run_id = row["run_id"]
        config_path = validate_file_hash(outdir, row, "config_relpath", "config_sha256")
        monomer_path = validate_file_hash(outdir, row, "monomer_relpath", "monomer_sha256")
        receptor_path = validate_file_hash(outdir, row, "receptor_relpath", "receptor_sha256")
        restraint_path = validate_file_hash(outdir, row, "restraint_relpath", "restraint_sha256")
        hotspot_path = validate_file_hash(outdir, row, "hotspot_relpath", "hotspot_sha256")
        completion_path = contained_path(outdir, row["completion_relpath"], f"{run_id}.completion")
        io_relpath, params_relpath = stage_relpaths(row)
        io_path = contained_path(outdir, io_relpath, f"{run_id}.emref_io")
        params_path = contained_path(outdir, params_relpath, f"{run_id}.emref_params")
        validate_params(params_path, row)

        monomer_inventory = parse_chain_inventory(read_coordinate_bytes(monomer_path), monomer_path)
        receptor_inventory = parse_chain_inventory(read_coordinate_bytes(receptor_path), receptor_path)
        require_chain(monomer_inventory, "A", "Frozen monomer", monomer_path)
        require_chain(receptor_inventory, "B", "Frozen receptor", receptor_path)

        selected, source_inventory = load_pose_records(outdir, io_relpath)
        source_pose_count += source_inventory["source_output_count"]
        completion = validate_completion(completion_path, row, source_inventory["source_output_count"])
        selected_indices = [record.output_index for record in selected]
        completion_sha256 = sha256_file(completion_path)
        io_sha256 = sha256_file(io_path)
        params_sha256 = sha256_file(params_path)
        for rank, record in enumerate(selected, start=1):
            vhh = record.vhh_inventory
            pvrig = record.pvrig_inventory
            output: dict[str, Any] = {
                "schema_version": "phase2_v3_p2_v1_2_pilot64_emref_top8_selection_v1",
                "protocol_id": PROTOCOL_ID,
                "source_protocol_id": SOURCE_PROTOCOL_ID,
                "source_protocol": SOURCE_PROTOCOL,
                "source_stage": SOURCE_STAGE,
                "selection_cohort": selection_label,
                "run_id": run_id,
                "case_id": row["pilot_id"],
                "candidate_id": row["pilot_id"],
                "family": row["source_cohort"],
                "role": row["seed_role"],
                "pilot_rank": row["pilot_rank"],
                "pilot_id": row["pilot_id"],
                "source_cohort": row["source_cohort"],
                "source_candidate_id": row["source_candidate_id"],
                "source_docking_receptor": row["receptor_id"].lower(),
                "receptor_id": row["receptor_id"],
                "seed_role": row["seed_role"],
                "iniseed": row["iniseed"],
                "topoaa_iniseed": row["topoaa_iniseed"],
                "rigidbody_iniseed": row["rigidbody_iniseed"],
                "rigidbody_seed_start": row["rigidbody_seed_start"],
                "rigidbody_seed_end": row["rigidbody_seed_end"],
                "cdr1_range": row["cdr1_range"],
                "cdr2_range": row["cdr2_range"],
                "cdr3_range": row["cdr3_range"],
                "canonical_rank": rank,
                "source_output_index": record.output_index,
                "source_output_file": record.file_name,
                "source_score": format(record.score, ".17g"),
                "source_seed": record.seed,
                "source_pose_relpath": workspace_relative(record.local_path, workspace_root),
                "remote_source_pose_relpath": record.remote_relpath,
                "source_pose_format": "pdb.gz" if record.local_path.name.endswith(".gz") else "pdb",
                "source_pose_sha256": record.source_sha256,
                "source_pose_bytes": record.source_bytes,
                "compressed_source_sha256": record.source_sha256,
                "compressed_source_bytes": record.source_bytes,
                "decompressed_coordinate_sha256": record.coordinate_sha256,
                "decompressed_coordinate_bytes": record.coordinate_bytes,
                "vhh_chain_id": "A",
                "vhh_atom_count": vhh["selected_heavy_atom_count"],
                "vhh_residue_count": vhh["selected_residue_count"],
                "vhh_atom_heavy_atom_count": vhh["atom_heavy_atom_count"],
                "vhh_atom_residue_count": vhh["atom_residue_count"],
                "vhh_hetatm_heavy_atom_count": vhh["hetatm_heavy_atom_count"],
                "vhh_hetatm_residue_count": vhh["hetatm_residue_count"],
                "vhh_excluded_hydrogen_or_deuterium_count": vhh["excluded_hydrogen_or_deuterium_count"],
                "vhh_chain_inventory_json": canonical_json(vhh),
                "pvrig_chain_id": "B",
                "pvrig_atom_count": pvrig["selected_heavy_atom_count"],
                "pvrig_residue_count": pvrig["selected_residue_count"],
                "pvrig_atom_heavy_atom_count": pvrig["atom_heavy_atom_count"],
                "pvrig_atom_residue_count": pvrig["atom_residue_count"],
                "pvrig_hetatm_heavy_atom_count": pvrig["hetatm_heavy_atom_count"],
                "pvrig_hetatm_residue_count": pvrig["hetatm_residue_count"],
                "pvrig_excluded_hydrogen_or_deuterium_count": pvrig["excluded_hydrogen_or_deuterium_count"],
                "pvrig_chain_inventory_json": canonical_json(pvrig),
                "completion_status": completion["status"],
                "config_relpath": row["config_relpath"],
                "completion_relpath": row["completion_relpath"],
                "monomer_relpath": row["monomer_relpath"],
                "receptor_relpath": row["receptor_relpath"],
                "restraint_relpath": row["restraint_relpath"],
                "hotspot_relpath": row["hotspot_relpath"],
                "emref_params_relpath": params_relpath,
                "completion_sha256": completion_sha256,
                "config_sha256": sha256_file(config_path),
                "monomer_sha256": sha256_file(monomer_path),
                "receptor_sha256": sha256_file(receptor_path),
                "restraint_sha256": sha256_file(restraint_path),
                "hotspot_sha256": sha256_file(hotspot_path),
                "emref_params_sha256": params_sha256,
                "source_io_sha256": io_sha256,
                "source_io_relpath": workspace_relative(io_path, workspace_root),
                "remote_source_io_relpath": io_relpath,
                "source_manifest_relpath": workspace_relative(manifest.path, workspace_root),
                "source_manifest_sha256": manifest.sha256,
                "source_manifest_row_sha256": manifest.row_hashes[run_id],
                "source_failed_audit_relpath": workspace_relative(
                    failed_audit_path.resolve(), workspace_root
                ),
                "source_failed_audit_sha256": failed_audit_sha256,
                "remote_inventory_request_sha256": request["request_sha256"],
                "remote_file_hash_chain": remote_inventory["file_hash_chain"],
                "local_file_hash_chain": local_inventory["file_hash_chain"],
                "selector_implementation_relpath": workspace_relative(script_path, workspace_root),
                "selector_implementation_sha256": script_sha256,
                "execution_mode": EXECUTION_MODE,
                "formal_eligible": "false",
                "claim_boundary": CLAIM_BOUNDARY,
                "selection_row_sha256": "",
            }
            output = {field: str(output.get(field, "")) for field in CSV_FIELDS}
            output["selection_row_sha256"] = row_sha256(output, "selection_row_sha256")
            output_rows.append(output)
        run_audits.append(
            {
                "run_id": run_id,
                "pilot_id": row["pilot_id"],
                "source_candidate_id": row["source_candidate_id"],
                "source_docking_receptor": row["receptor_id"].lower(),
                "receptor_id": row["receptor_id"],
                "seed_role": row["seed_role"],
                "iniseed": parse_int(row["iniseed"], f"{run_id}.iniseed"),
                "cdr_ranges": {name: row[f"{name}_range"] for name in ("cdr1", "cdr2", "cdr3")},
                "completion_status": completion["status"],
                "input_relpaths": {
                    "config": row["config_relpath"],
                    "completion": row["completion_relpath"],
                    "monomer": row["monomer_relpath"],
                    "receptor": row["receptor_relpath"],
                    "restraint": row["restraint_relpath"],
                    "hotspot": row["hotspot_relpath"],
                    "emref_params": params_relpath,
                    "emref_io": io_relpath,
                },
                "completion_sha256": completion_sha256,
                "config_sha256": row["config_sha256"],
                "monomer_sha256": row["monomer_sha256"],
                "receptor_sha256": row["receptor_sha256"],
                "restraint_sha256": row["restraint_sha256"],
                "hotspot_sha256": row["hotspot_sha256"],
                "emref_params_sha256": params_sha256,
                "source_io_sha256": io_sha256,
                "source_output_count": source_inventory["source_output_count"],
                "selected_pose_count": K,
                "selected_source_output_indices": selected_indices,
                "monomer_chain_inventory": monomer_inventory["A"],
                "receptor_chain_inventory": receptor_inventory["B"],
                "outputs": source_inventory["outputs"],
            }
        )

    if len(output_rows) != len(selected_rows) * K:
        raise RecoveryError("Fixed-Top-8 output cardinality mismatch")
    if expected:
        observed = {
            "runs": len(selected_rows),
            "source_poses": source_pose_count,
            "selected_poses": len(output_rows),
        }
        if observed != expected:
            raise RecoveryError(f"{selection_label} frozen count mismatch: {observed} != {expected}")
    if sha256_file(manifest.path) != manifest.sha256 or sha256_file(failed_audit_path.resolve()) != failed_audit_sha256:
        raise RecoveryError("Manifest or V1.1 failed audit changed during recovery")
    refreshed_inventory = file_inventory(outdir, [item["relpath"] for item in local_inventory["files"]])
    if refreshed_inventory != local_inventory:
        raise RecoveryError("Recovered input changed while selecting fixed Top-8")

    write_csv_atomic(output_csv, output_rows)
    audit: dict[str, Any] = {
        "schema_version": "phase2_v3_p2_v1_2_pilot64_emref_recovery_audit_v1",
        "status": "PASS_V1_2_PILOT64_EMREF_RECOVERY_SELECTED",
        "protocol_id": PROTOCOL_ID,
        "source_protocol_id": SOURCE_PROTOCOL_ID,
        "source_protocol": SOURCE_PROTOCOL,
        "source_stage": SOURCE_STAGE,
        "selection_cohort": selection_label,
        "execution_mode": EXECUTION_MODE,
        "formal_eligible": FORMAL_ELIGIBLE,
        "claim_boundary": CLAIM_BOUNDARY,
        "inventory_only": inventory_only,
        "host": host,
        "remote_root": remote_root,
        "k": K,
        "selection_order": ["ascending_haddock_score", "original_io_index", "file_name"],
        "selection_backfill": False,
        "source_stage_exclusive": True,
        "counts": {
            "manifest_runs": len(manifest.rows),
            "failed_audit_runs": len(failed_run_ids),
            "selected_runs": len(selected_rows),
            "source_poses": source_pose_count,
            "selected_poses": len(output_rows),
        },
        "expected_counts": expected,
        "source_docking_receptor_counts": dict(Counter(row["receptor_id"].lower() for row in selected_rows)),
        "seed_role_counts": dict(Counter(row["seed_role"] for row in selected_rows)),
        "inputs": {
            "run_manifest": {
                "relpath": workspace_relative(manifest.path, workspace_root),
                "sha256": manifest.sha256,
            },
            "v1_1_failed_audit": {
                "relpath": workspace_relative(failed_audit_path.resolve(), workspace_root),
                "sha256": failed_audit_sha256,
                "status": failed_payload["status"],
            },
        },
        "remote_inventory": {
            "request_sha256": request["request_sha256"],
            "inventory_relpath": request["inventory_relpath"],
            "file_count": remote_inventory["file_count"],
            "total_bytes": remote_inventory["total_bytes"],
            "file_hash_chain": remote_inventory["file_hash_chain"],
        },
        "local_inventory": {
            "file_count": local_inventory["file_count"],
            "total_bytes": local_inventory["total_bytes"],
            "file_hash_chain": local_inventory["file_hash_chain"],
        },
        "remote_local_hash_chain_equal": remote_inventory["file_hash_chain"] == local_inventory["file_hash_chain"],
        "runs": run_audits,
        "selector": {
            "relpath": workspace_relative(script_path, workspace_root),
            "sha256": script_sha256,
        },
        "output_csv": {
            "relpath": workspace_relative(output_csv, workspace_root),
            "sha256": sha256_file(output_csv),
            "rows": len(output_rows),
            "selection_row_hash_chain": sha256_bytes(
                "\n".join(row["selection_row_sha256"] for row in output_rows).encode("ascii")
            ),
        },
    }
    write_json_atomic(audit_path, audit)
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--failed-audit", type=Path, default=DEFAULT_FAILED_AUDIT)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--cohort", choices=tuple(EXPECTED_COHORTS))
    selection.add_argument("--run-id", action="append", dest="run_ids")
    parser.add_argument("--ssh-executable", default="ssh.exe")
    parser.add_argument("--host", default="node1")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--inventory-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    audit = build(
        manifest_path=args.manifest,
        failed_audit_path=args.failed_audit,
        outdir=args.outdir,
        audit_path=args.audit,
        cohort=args.cohort,
        explicit_run_ids=args.run_ids,
        output_csv=args.output_csv,
        inventory_only=args.inventory_only,
        ssh_executable=args.ssh_executable,
        host=args.host,
        remote_root=args.remote_root,
    )
    print(
        json.dumps(
            {
                "status": audit["status"],
                "selection_cohort": audit["selection_cohort"],
                "selected_runs": audit["counts"]["selected_runs"],
                "source_poses": audit["counts"]["source_poses"],
                "selected_poses": audit["counts"]["selected_poses"],
                "output_csv": audit["output_csv"]["relpath"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
