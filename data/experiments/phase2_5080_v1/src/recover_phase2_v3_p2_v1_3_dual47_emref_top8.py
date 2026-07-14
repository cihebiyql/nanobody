#!/usr/bin/env python3
"""Recover the V1.3 dual-receptor cohort and select fixed ``4_emref`` Top-8.

The selector joins the frozen 94-run V1.3 manifest to its 64-run exact-reuse
ledger, retrieves old Pilot64 and new V1.3 runs from separate remote roots,
and materializes one deterministic 752-pose table.  It never launches docking,
scores blocker geometry, or releases training labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

try:
    from experiments.phase2_5080_v1.src import (
        recover_phase2_v3_p2_v1_2_pilot64_emref_top8 as recovery_base,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution from src/
    import recover_phase2_v3_p2_v1_2_pilot64_emref_top8 as recovery_base


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
DEFAULT_PACKAGE = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_completion15_package"
)
DEFAULT_RUN_MANIFEST = DEFAULT_PACKAGE / "manifests/run_manifest.csv"
DEFAULT_REUSE_MANIFEST = DEFAULT_PACKAGE / "manifests/exact_reuse_manifest.csv"
DEFAULT_PACKAGE_AUDIT = DEFAULT_PACKAGE / "package_audit.json"
DEFAULT_EXECUTION_RELEASE_MANIFEST = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_docking_execution_release_manifest.json"
)
FROZEN_EXECUTION_RELEASE_SHA256 = "4a0f1a63ef3dc16220beb9d821db71e500d4e512195e7f19a3e112d1d7a2db21"
DEFAULT_OUTDIR = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_top8_recovery"
)
OUTPUT_CSV_NAME = "pvrig_v1_3_dual47_emref_top8_selector.csv"
AUDIT_NAME = "pvrig_v1_3_dual47_emref_top8_recovery_audit.json"
DEFAULT_OUTPUT_CSV = DEFAULT_OUTDIR / "current" / OUTPUT_CSV_NAME
DEFAULT_AUDIT = DEFAULT_OUTDIR / "current" / AUDIT_NAME
DEFAULT_OLD_REMOTE_ROOT = "/data/qlyu/projects/pvrig_v3_p2_dual_docking_pilot64_v2_20260714"
DEFAULT_NEW_REMOTE_ROOT = "/data/qlyu/projects/pvrig_v3_p2_docking_gold_v1_3_dual47_completion15_20260714"

PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
OLD_PROTOCOL_ID = "DG_A_PILOT64_V1_1"
SOURCE_STAGE = "4_emref"
SOURCE_PROTOCOL = "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1"
REUSE_MODE = "REUSE_OLD_PILOT64_MAIN"
NEW_MODE = "NEW_DUAL_DOCKING_COMPLETION"
SOURCE_MODES = (REUSE_MODE, NEW_MODE)
K = 8
EXPECTED_CASES = 47
EXPECTED_RUNS = 94
EXPECTED_REUSE_RUNS = 64
EXPECTED_NEW_RUNS = 30
EXPECTED_POSES = EXPECTED_RUNS * K
EXPECTED_BY_RECEPTOR = {"8X6B": 47, "9E6Y": 47}
EXPECTED_POSES_BY_RECEPTOR = {key: value * K for key, value in EXPECTED_BY_RECEPTOR.items()}
EXPECTED_RUNS_BY_MODE = {REUSE_MODE: EXPECTED_REUSE_RUNS, NEW_MODE: EXPECTED_NEW_RUNS}
EXPECTED_POSES_BY_MODE = {key: value * K for key, value in EXPECTED_RUNS_BY_MODE.items()}
SEED_BY_RECEPTOR = {"8X6B": 917, "9E6Y": 20917}
STAGE_OUTPUT_REQUIREMENTS = {
    "topoaa": ("eq", 2),
    "rigidbody": ("ge", 38),
    "seletop": ("eq", 10),
    "flexref": ("ge", 8),
    "emref": ("ge", 8),
}
CLAIM_BOUNDARY = (
    "development-only independent dual-receptor fixed-Top-8 computational docking poses; "
    "not training Gold, formal validation, experimental binding, affinity, or blocking truth"
)

RUN_ID_RE = re.compile(r"^V13CAL_([0-9]{3})__(8X6B|9E6Y)__main$")
OLD_RUN_ID_RE = re.compile(r"^P2PILOT_[0-9]{3}__(8X6B|9E6Y)__main$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

RUN_REQUIRED_FIELDS = {
    "schema_version", "protocol_id", "run_id", "case_rank", "case_id",
    "candidate_id", "family", "anchor_class", "calibration_role", "sequence_sha256",
    "teacher_manifest_relpath", "teacher_manifest_sha256", "teacher_manifest_row_sha256",
    "execution_mode", "receptor_id", "seed_role", "topoaa_iniseed",
    "rigidbody_iniseed", "rigidbody_seed_start", "rigidbody_seed_end", "ncores",
    "rigidbody_sampling", "rigidbody_tolerance", "seletop_select", "flexref_tolerance",
    "emref_tolerance", "cdr1_range", "cdr2_range", "cdr3_range", "source_run_id",
    "fixed_top8_policy", "formal_eligible", "training_label_release_eligible",
    "docking_gold_release_eligible", "claim_boundary", "run_manifest_row_sha256",
}
REUSE_REQUIRED_FIELDS = RUN_REQUIRED_FIELDS | {
    "source_protocol_id", "source_old_remote_root", "source_old_package_relpath",
    "source_old_package_audit_sha256", "source_old_controller_relpath",
    "source_old_controller_sha256", "source_old_run_manifest_relpath",
    "source_old_run_manifest_sha256", "source_old_run_manifest_row_sha256",
    "source_config_relpath", "source_config_sha256", "source_completion_relpath",
    "source_completion_sha256", "source_completion_status", "source_completion_exit_code",
    "source_stage_output_counts_json", "source_emref_io_relpath", "source_emref_io_sha256",
    "source_emref_output_count", "source_emref_params_relpath",
    "source_emref_params_sha256", "v1_3_emref_gate_status",
    "source_final_stage_ignored", "exact_reuse_run_identity_hash_closed",
    "source_emref_coordinate_payload_hash_closed", "coordinate_payload_state",
    "reuse_manifest_row_sha256",
}

CSV_FIELDS = (
    "schema_version", "protocol_id", "source_protocol_id", "source_protocol", "source_stage", "source_mode",
    "run_id", "source_run_id", "case_rank", "case_id", "candidate_id", "family",
    "anchor_class", "calibration_role", "sequence_sha256", "teacher_manifest_relpath",
    "teacher_manifest_sha256", "teacher_manifest_row_sha256", "generation_receptor",
    "receptor_id", "seed_role",
    "topoaa_iniseed", "rigidbody_iniseed", "rigidbody_seed_start", "rigidbody_seed_end",
    "cdr1_range", "cdr2_range", "cdr3_range", "native_rank", "canonical_rank",
    "source_output_index", "source_output_file", "source_score", "source_seed",
    "source_pose_relpath", "remote_source_pose_relpath", "materialized_coordinate_relpath",
    "source_pose_format", "source_pose_sha256", "source_pose_bytes",
    "compressed_source_sha256", "compressed_source_bytes", "decompressed_coordinate_sha256",
    "decompressed_coordinate_bytes", "materialized_coordinate_sha256",
    "materialized_coordinate_bytes", "vhh_chain_id", "vhh_atom_count",
    "vhh_residue_count", "vhh_atom_heavy_atom_count", "vhh_atom_residue_count",
    "vhh_hetatm_heavy_atom_count", "vhh_hetatm_residue_count",
    "vhh_excluded_hydrogen_or_deuterium_count", "vhh_chain_inventory_json",
    "pvrig_chain_id", "pvrig_atom_count", "pvrig_residue_count",
    "pvrig_atom_heavy_atom_count", "pvrig_atom_residue_count",
    "pvrig_hetatm_heavy_atom_count", "pvrig_hetatm_residue_count",
    "pvrig_excluded_hydrogen_or_deuterium_count", "pvrig_chain_inventory_json",
    "monomer_atom_identity_sha256", "monomer_residue_identity_sha256",
    "pose_vhh_atom_identity_sha256", "pose_vhh_residue_identity_sha256",
    "receptor_atom_identity_sha256", "receptor_residue_identity_sha256",
    "pose_pvrig_atom_identity_sha256", "pose_pvrig_residue_identity_sha256",
    "completion_status", "completion_exit_code", "source_final_stage_ignored",
    "remote_root", "config_relpath", "remote_config_relpath", "completion_relpath",
    "remote_completion_relpath", "monomer_relpath", "remote_monomer_relpath",
    "receptor_relpath", "remote_receptor_relpath", "restraint_relpath",
    "remote_restraint_relpath", "hotspot_relpath", "remote_hotspot_relpath",
    "source_params_relpath", "remote_source_params_relpath", "source_io_relpath",
    "remote_source_io_relpath", "completion_sha256", "config_sha256", "monomer_sha256",
    "receptor_sha256", "restraint_sha256", "hotspot_sha256", "source_params_sha256",
    "source_io_sha256", "run_manifest_relpath", "run_manifest_sha256",
    "run_manifest_row_sha256", "exact_reuse_manifest_relpath",
    "exact_reuse_manifest_sha256", "exact_reuse_manifest_row_sha256",
    "source_old_run_manifest_relpath", "source_old_run_manifest_sha256",
    "source_old_run_manifest_row_sha256", "execution_release_manifest_relpath",
    "execution_release_manifest_sha256", "publication_release_id",
    "remote_inventory_request_sha256",
    "remote_file_hash_chain", "local_file_hash_chain", "selector_implementation_relpath",
    "selector_implementation_sha256", "selector_helper_relpath", "selector_helper_sha256",
    "formal_eligible", "training_label_release_eligible", "docking_gold_release_eligible",
    "claim_boundary", "selection_row_sha256",
)

RecoveryError = recovery_base.RecoveryError
SyncRunner = Callable[[Mapping[str, Any], Path, str, str, str], None]
PointerPromoter = Callable[[Path, Path], None]


@dataclass(frozen=True)
class ManifestData:
    path: Path
    sha256: str
    rows: tuple[dict[str, str], ...]
    by_run_id: Mapping[str, dict[str, str]]


@dataclass(frozen=True)
class ExecutionRelease:
    path: Path
    sha256: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class SourceDescriptor:
    run: Mapping[str, str]
    source_mode: str
    source_protocol_id: str
    source_run_id: str
    remote_root: str
    config_relpath: str
    completion_relpath: str
    monomer_relpath: str
    receptor_relpath: str
    restraint_relpath: str
    hotspot_relpath: str
    run_dir_relpath: str
    expected_hashes: Mapping[str, str]
    reuse: Mapping[str, str] | None
    old_manifest_relpath: str
    old_manifest_sha256: str
    old_manifest_row_sha256: str


def canonical_json(value: Any) -> str:
    return recovery_base.canonical_json(value)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return recovery_base.sha256_file(path)


def row_sha256(row: Mapping[str, Any], hash_field: str) -> str:
    return recovery_base.row_sha256(row, hash_field)


def require_hash(value: str, label: str) -> str:
    normalized = str(value).strip().lower()
    if not HASH_RE.fullmatch(normalized):
        raise RecoveryError(f"{label} is not a lowercase SHA256: {value!r}")
    return normalized


def parse_int(value: Any, label: str) -> int:
    return recovery_base.parse_int(value, label)


def safe_relative_path(value: str, label: str) -> str:
    return recovery_base.safe_relative_path(value, label)


def contained_path(root: Path, relpath: str, label: str) -> Path:
    return recovery_base.contained_path(root, relpath, label)


def workspace_relative(path: Path, workspace_root: Path) -> str:
    return recovery_base.workspace_relative(path, workspace_root)


def workspace_relative_lexical(path: Path, workspace_root: Path) -> str:
    absolute = Path(os.path.abspath(path))
    try:
        return absolute.relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise RecoveryError(f"Path is outside workspace root: {absolute}") from error


def read_csv_rows(path: Path, required: set[str], hash_field: str) -> ManifestData:
    path = path.resolve()
    if not path.is_file():
        raise RecoveryError(f"Manifest is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise RecoveryError(f"Manifest header is empty or duplicated: {path}")
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise RecoveryError(f"Manifest is missing columns {missing}: {path}")
        rows = [{str(key): str(value) for key, value in row.items()} for row in reader]
    if not rows:
        raise RecoveryError(f"Manifest is empty: {path}")
    by_run_id: dict[str, dict[str, str]] = {}
    for line, row in enumerate(rows, start=2):
        run_id = row.get("run_id", "").strip()
        if not run_id or run_id in by_run_id:
            raise RecoveryError(f"Missing or duplicate run_id at {path}:{line}: {run_id!r}")
        expected = require_hash(row.get(hash_field, ""), f"{run_id}.{hash_field}")
        observed = row_sha256(row, hash_field)
        if observed != expected:
            raise RecoveryError(f"Manifest row hash mismatch for {run_id}: {observed} != {expected}")
        by_run_id[run_id] = row
    return ManifestData(path, sha256_file(path), tuple(rows), by_run_id)


def validate_run_row(row: Mapping[str, str]) -> None:
    run_id = row["run_id"]
    match = RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise RecoveryError(f"Malformed V1.3 run_id: {run_id!r}")
    rank, receptor = match.groups()
    if row["protocol_id"] != PROTOCOL_ID or row["receptor_id"] != receptor:
        raise RecoveryError(f"Protocol or receptor mismatch for {run_id}")
    if row["seed_role"] != "main" or parse_int(row["case_rank"], f"{run_id}.case_rank") != int(rank):
        raise RecoveryError(f"Rank or seed-role mismatch for {run_id}")
    expected_seed = SEED_BY_RECEPTOR[receptor]
    expected_values = {
        "topoaa_iniseed": 917,
        "rigidbody_iniseed": expected_seed,
        "rigidbody_seed_start": expected_seed + 1,
        "rigidbody_seed_end": expected_seed + 40,
        "ncores": 4,
        "rigidbody_sampling": 40,
        "rigidbody_tolerance": 5,
        "seletop_select": 10,
        "flexref_tolerance": 20,
        "emref_tolerance": 20,
    }
    for field, expected in expected_values.items():
        if parse_int(row[field], f"{run_id}.{field}") != expected:
            raise RecoveryError(f"Frozen protocol mismatch for {run_id}.{field}")
    for field in ("cdr1_range", "cdr2_range", "cdr3_range"):
        recovery_base.parse_range(row[field], f"{run_id}.{field}")
    if row["execution_mode"] not in SOURCE_MODES:
        raise RecoveryError(f"Unexpected execution mode for {run_id}: {row['execution_mode']}")
    if row["fixed_top8_policy"] != "deferred_4_emref_score_order_no_backfill":
        raise RecoveryError(f"Top-8 policy mismatch for {run_id}")
    for field in ("formal_eligible", "training_label_release_eligible", "docking_gold_release_eligible"):
        if row[field].lower() != "false":
            raise RecoveryError(f"Eligibility must remain false for {run_id}.{field}")
    require_hash(row["sequence_sha256"], f"{run_id}.sequence_sha256")
    safe_relative_path(row["teacher_manifest_relpath"], f"{run_id}.teacher_manifest_relpath")
    require_hash(row["teacher_manifest_sha256"], f"{run_id}.teacher_manifest_sha256")
    require_hash(row["teacher_manifest_row_sha256"], f"{run_id}.teacher_manifest_row_sha256")
    if row["execution_mode"] == REUSE_MODE:
        if not OLD_RUN_ID_RE.fullmatch(row["source_run_id"]):
            raise RecoveryError(f"Missing old source_run_id for {run_id}")
        for field in ("config_relpath", "completion_relpath", "monomer_relpath", "receptor_relpath"):
            if row[field]:
                raise RecoveryError(f"Reuse row unexpectedly materializes V1.3 {field}: {run_id}")
    else:
        if row["source_run_id"]:
            raise RecoveryError(f"New row unexpectedly has source_run_id: {run_id}")
        expected_paths = {
            "config_relpath": f"runs/{run_id}/{run_id}.cfg",
            "run_workspace_relpath": f"runs/{run_id}",
            "run_dir_relpath": f"runs/{run_id}/run_{run_id}",
            "completion_relpath": f"runs/{run_id}/{run_id}.complete.json",
        }
        for field in ("config_relpath", "run_workspace_relpath", "run_dir_relpath", "completion_relpath",
                      "monomer_relpath", "receptor_relpath", "restraint_relpath", "hotspot_relpath"):
            safe_relative_path(row[field], f"{run_id}.{field}")
        for field, expected in expected_paths.items():
            if row[field] != expected:
                raise RecoveryError(f"New-run path mismatch for {run_id}.{field}")
        for field in ("config_sha256", "monomer_sha256", "receptor_sha256", "restraint_sha256", "hotspot_sha256"):
            require_hash(row[field], f"{run_id}.{field}")


def load_inputs(run_manifest_path: Path, reuse_manifest_path: Path) -> tuple[ManifestData, ManifestData]:
    runs = read_csv_rows(run_manifest_path, RUN_REQUIRED_FIELDS, "run_manifest_row_sha256")
    reuse = read_csv_rows(reuse_manifest_path, REUSE_REQUIRED_FIELDS, "reuse_manifest_row_sha256")
    if len(runs.rows) != EXPECTED_RUNS or len(reuse.rows) != EXPECTED_REUSE_RUNS:
        raise RecoveryError(
            f"V1.3 run closure mismatch: runs={len(runs.rows)}, reuse={len(reuse.rows)}"
        )
    for row in runs.rows:
        validate_run_row(row)
    expected_reuse_ids = {row["run_id"] for row in runs.rows if row["execution_mode"] == REUSE_MODE}
    if set(reuse.by_run_id) != expected_reuse_ids:
        raise RecoveryError("Exact-reuse manifest run set does not equal the 64 reuse rows")
    for run_id, extended in reuse.by_run_id.items():
        base = runs.by_run_id[run_id]
        for field, value in base.items():
            if extended.get(field) != value:
                raise RecoveryError(f"Run/reuse manifest mismatch for {run_id}.{field}")
        if extended["source_protocol_id"] != OLD_PROTOCOL_ID:
            raise RecoveryError(f"Old protocol mismatch for {run_id}")
        if extended["v1_3_emref_gate_status"] != "PASS_4_EMREF_TOP8_READY":
            raise RecoveryError(f"Reuse emref gate is not passed for {run_id}")
        if extended["source_final_stage_ignored"].lower() != "true":
            raise RecoveryError(f"Reuse final-stage ignore is not explicit for {run_id}")
        if extended["exact_reuse_run_identity_hash_closed"].lower() != "true":
            raise RecoveryError(f"Reuse identity is not hash-closed for {run_id}")
        if extended["source_emref_coordinate_payload_hash_closed"].lower() != "false":
            raise RecoveryError(f"Reuse coordinate closure must remain pending before recovery: {run_id}")
        if extended["coordinate_payload_state"] != "REMOTE_RECOVERY_REQUIRED_BEFORE_SCORING":
            raise RecoveryError(f"Unexpected reuse coordinate state for {run_id}")
        if extended["source_completion_status"] not in {
            "PASS_DOCKING_OUTPUT_COMPLETE", "FAIL_DOCKING_OUTPUT_INCOMPLETE"
        } or parse_int(extended["source_completion_exit_code"], f"{run_id}.source_completion_exit_code") != 0:
            raise RecoveryError(f"Unexpected reuse completion contract for {run_id}")
        if parse_int(extended["source_emref_output_count"], f"{run_id}.source_emref_output_count") < K:
            raise RecoveryError(f"Reuse ledger records fewer than fixed K={K} poses for {run_id}")
        for field in ("source_config_sha256", "source_completion_sha256", "source_emref_io_sha256",
                      "source_emref_params_sha256", "source_old_package_audit_sha256",
                      "source_old_controller_sha256", "source_old_run_manifest_sha256",
                      "source_old_run_manifest_row_sha256"):
            require_hash(extended[field], f"{run_id}.{field}")
    modes = Counter(row["execution_mode"] for row in runs.rows)
    receptors = Counter(row["receptor_id"] for row in runs.rows)
    if dict(modes) != EXPECTED_RUNS_BY_MODE or dict(receptors) != EXPECTED_BY_RECEPTOR:
        raise RecoveryError(f"V1.3 mode/receptor closure mismatch: {modes}, {receptors}")
    case_receptors: dict[str, set[str]] = {}
    for row in runs.rows:
        case_receptors.setdefault(row["case_id"], set()).add(row["receptor_id"])
    if len(case_receptors) != EXPECTED_CASES or any(value != set(EXPECTED_BY_RECEPTOR) for value in case_receptors.values()):
        raise RecoveryError("Every V1.3 case must have exactly one 8X6B and one 9E6Y run")
    return runs, reuse


def load_execution_release(
    path: Path,
    data_root: Path,
    expected_sha256: str = FROZEN_EXECUTION_RELEASE_SHA256,
) -> ExecutionRelease:
    path = path.resolve()
    expected_sha256 = require_hash(expected_sha256, "execution release expected SHA256")
    observed_sha256 = sha256_file(path)
    if observed_sha256 != expected_sha256:
        raise RecoveryError(
            f"Frozen execution release hash mismatch: {observed_sha256} != {expected_sha256}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Cannot read frozen execution release: {path}") from error
    if not isinstance(payload, dict):
        raise RecoveryError("Frozen execution release is not an object")
    expected_scalars = {
        "schema_version": "phase2_v3_p2_v1_3_docking_execution_release_v1",
        "protocol_id": PROTOCOL_ID,
        "status": "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE",
        "remote_launch_eligible": True,
        "remote_launch_run_count": EXPECTED_NEW_RUNS,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
    }
    for field, expected in expected_scalars.items():
        if payload.get(field) != expected:
            raise RecoveryError(f"Frozen execution release mismatch for {field}")
    remote_root = str(payload.get("remote_root", ""))
    if not remote_root or not PurePosixPath(remote_root).is_absolute() or "\x00" in remote_root:
        raise RecoveryError("Frozen execution release new remote root is invalid")
    launch = payload.get("remote_launch_contract")
    expected_launch = {
        "expected_new_cases": 15,
        "expected_new_runs": EXPECTED_NEW_RUNS,
        "fixed_top_k": K,
        "source_stage": SOURCE_STAGE,
        "success_status": "PASS_4_EMREF_TOP8_READY",
        "backfill_allowed": False,
    }
    if not isinstance(launch, dict):
        raise RecoveryError("Frozen execution release has no launch contract")
    for field, expected in expected_launch.items():
        if launch.get(field) != expected:
            raise RecoveryError(f"Frozen launch contract mismatch for {field}")
    closure = payload.get("execution_closure")
    expected_closure = {
        "candidate_count": EXPECTED_CASES,
        "new_completion15_run_count": EXPECTED_NEW_RUNS,
        "reused_pilot64_main_run_count": EXPECTED_REUSE_RUNS,
        "run_count_per_receptor": EXPECTED_BY_RECEPTOR["8X6B"],
        "total_main_run_count": EXPECTED_RUNS,
    }
    if not isinstance(closure, dict):
        raise RecoveryError("Frozen execution release has no execution closure")
    for field, expected in expected_closure.items():
        if closure.get(field) != expected:
            raise RecoveryError(f"Frozen execution closure mismatch for {field}")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RecoveryError("Frozen execution release artifact ledger is empty")
    seen: set[str] = set()
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            raise RecoveryError(f"Execution release artifact[{index}] is not an object")
        relpath = safe_relative_path(str(item.get("path", "")), f"release artifact[{index}]")
        if relpath in seen:
            raise RecoveryError(f"Duplicate execution release artifact path: {relpath}")
        seen.add(relpath)
        expected_hash = require_hash(str(item.get("sha256", "")), f"release artifact {relpath}")
        expected_bytes = parse_int(item.get("bytes"), f"release artifact {relpath} bytes")
        artifact_path = contained_path(data_root.resolve(), relpath, f"release artifact {relpath}")
        if not artifact_path.is_file():
            raise RecoveryError(f"Frozen execution release artifact is missing: {artifact_path}")
        if artifact_path.stat().st_size != expected_bytes or sha256_file(artifact_path) != expected_hash:
            raise RecoveryError(f"Frozen execution release artifact hash/size mismatch: {relpath}")
    return ExecutionRelease(path, observed_sha256, payload)


def release_artifact_binding(
    release: ExecutionRelease, data_root: Path, path: Path, label: str
) -> Mapping[str, Any]:
    target = path.resolve()
    for item in release.payload["artifacts"]:
        artifact = contained_path(data_root.resolve(), str(item["path"]), f"{label} artifact")
        if artifact == target:
            return item
    raise RecoveryError(f"{label} is not bound by the frozen execution release: {target}")


def load_package_audit(
    path: Path,
    runs: ManifestData,
    reuse: ManifestData,
    release: ExecutionRelease,
    release_data_root: Path,
) -> dict[str, Any]:
    path = path.resolve()
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Cannot read V1.3 package audit: {path}") from error
    if not isinstance(audit, dict) or audit.get("status") != "PASS_V1_3_DUAL47_COMPLETION15_PACKAGE_READY":
        raise RecoveryError("V1.3 package audit is not the frozen ready package")
    if audit.get("protocol_id") != PROTOCOL_ID or audit.get("run_count") != EXPECTED_RUNS:
        raise RecoveryError("V1.3 package audit protocol/run count mismatch")
    manifests = audit.get("manifests", {})
    if manifests.get("run", {}).get("sha256") != runs.sha256:
        raise RecoveryError("Package audit/run manifest hash mismatch")
    if manifests.get("reuse", {}).get("sha256") != reuse.sha256:
        raise RecoveryError("Package audit/reuse manifest hash mismatch")
    release_package_path = contained_path(
        release_data_root.resolve(),
        str(release.payload.get("package_audit_path", "")),
        "release package audit",
    )
    if release_package_path != path:
        raise RecoveryError("Package audit path differs from the frozen execution release")
    for bound_path, label in (
        (path, "package audit"),
        (runs.path, "run manifest"),
        (reuse.path, "exact reuse manifest"),
    ):
        binding = release_artifact_binding(release, release_data_root, bound_path, label)
        if binding["sha256"] != sha256_file(bound_path):
            raise RecoveryError(f"Frozen execution release {label} binding drift")
    for field in ("formal_eligible", "training_label_release_eligible", "docking_gold_release_eligible"):
        if audit.get(field) is not False:
            raise RecoveryError(f"Package audit unexpectedly enables {field}")
    return audit


def workspace_input(workspace_root: Path, relpath: str, label: str) -> Path:
    return contained_path(workspace_root, safe_relative_path(relpath, label), label)


def validate_local_hash(path: Path, expected: str, label: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise RecoveryError(f"{label} hash mismatch: {observed} != {expected}")


def old_manifest_context(
    reuse: ManifestData, workspace_root: Path
) -> tuple[ManifestData, dict[str, str]]:
    relpaths = {row["source_old_run_manifest_relpath"] for row in reuse.rows}
    hashes = {row["source_old_run_manifest_sha256"] for row in reuse.rows}
    if len(relpaths) != 1 or len(hashes) != 1:
        raise RecoveryError("Exact-reuse rows do not bind one old run manifest")
    relpath = next(iter(relpaths))
    path = workspace_input(workspace_root, relpath, "old run manifest")
    if sha256_file(path) != next(iter(hashes)):
        raise RecoveryError("Old run manifest hash does not match exact-reuse ledger")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = [{str(key): str(value) for key, value in row.items()} for row in reader]
    by_id = {row.get("run_id", ""): row for row in rows}
    if len(by_id) != len(rows):
        raise RecoveryError("Old run manifest contains duplicate run IDs")
    data = ManifestData(path.resolve(), sha256_file(path), tuple(rows), by_id)
    for row in reuse.rows:
        old = by_id.get(row["source_run_id"])
        if old is None:
            raise RecoveryError(f"Old source run is absent: {row['source_run_id']}")
        if sha256_bytes(canonical_json(old).encode("utf-8")) != row["source_old_run_manifest_row_sha256"]:
            raise RecoveryError(f"Old manifest row hash mismatch for {row['run_id']}")
    return data, {"relpath": relpath, "sha256": data.sha256}


def validate_bound_old_files(reuse: ManifestData, workspace_root: Path) -> None:
    bindings = (
        ("source_old_package_relpath", "source_old_package_audit_sha256", "package_audit.json"),
        ("source_old_controller_relpath", "source_old_controller_sha256", None),
    )
    for rel_field, hash_field, suffix in bindings:
        pairs = {(row[rel_field], row[hash_field]) for row in reuse.rows}
        if len(pairs) != 1:
            raise RecoveryError(f"Reuse ledger has multiple {rel_field}/{hash_field} bindings")
        relpath, expected = next(iter(pairs))
        path = workspace_input(workspace_root, relpath, rel_field)
        if suffix:
            path = path / suffix
        validate_local_hash(path, expected, rel_field)


def source_descriptors(
    runs: ManifestData,
    reuse: ManifestData,
    old_manifest: ManifestData,
    old_remote_root: str,
    new_remote_root: str,
) -> list[SourceDescriptor]:
    descriptors: list[SourceDescriptor] = []
    for run in runs.rows:
        run_id = run["run_id"]
        if run["execution_mode"] == REUSE_MODE:
            ledger = reuse.by_run_id[run_id]
            old = old_manifest.by_run_id[run["source_run_id"]]
            if old.get("protocol_id") != OLD_PROTOCOL_ID or old.get("seed_role") != "main":
                raise RecoveryError(f"Old source protocol/role mismatch for {run_id}")
            if old.get("receptor_id") != run["receptor_id"]:
                raise RecoveryError(f"Old/new receptor mismatch for {run_id}")
            for field in ("config_relpath", "completion_relpath", "monomer_relpath", "receptor_relpath",
                          "restraint_relpath", "hotspot_relpath", "run_dir_relpath"):
                safe_relative_path(old[field], f"{run_id}.old.{field}")
            expected_hashes = {
                "config": old["config_sha256"], "monomer": old["monomer_sha256"],
                "receptor": old["receptor_sha256"], "restraint": old["restraint_sha256"],
                "hotspot": old["hotspot_sha256"], "completion": ledger["source_completion_sha256"],
                "io": ledger["source_emref_io_sha256"], "params": ledger["source_emref_params_sha256"],
            }
            if expected_hashes["config"] != ledger["source_config_sha256"]:
                raise RecoveryError(f"Old config hash disagreement for {run_id}")
            suffixes = {
                "source_config_relpath": old["config_relpath"],
                "source_completion_relpath": old["completion_relpath"],
                "source_emref_io_relpath": f"{old['run_dir_relpath']}/4_emref/io.json",
                "source_emref_params_relpath": f"{old['run_dir_relpath']}/4_emref/params.cfg",
            }
            for field, suffix in suffixes.items():
                if not ledger[field].replace("\\", "/").endswith(suffix):
                    raise RecoveryError(f"Reuse path binding mismatch for {run_id}.{field}")
            descriptor = SourceDescriptor(
                run, REUSE_MODE, OLD_PROTOCOL_ID, old["run_id"], old_remote_root,
                old["config_relpath"], old["completion_relpath"], old["monomer_relpath"],
                old["receptor_relpath"], old["restraint_relpath"], old["hotspot_relpath"],
                old["run_dir_relpath"], expected_hashes, ledger,
                ledger["source_old_run_manifest_relpath"], ledger["source_old_run_manifest_sha256"],
                ledger["source_old_run_manifest_row_sha256"],
            )
        else:
            expected_hashes = {
                "config": run["config_sha256"], "monomer": run["monomer_sha256"],
                "receptor": run["receptor_sha256"], "restraint": run["restraint_sha256"],
                "hotspot": run["hotspot_sha256"],
            }
            descriptor = SourceDescriptor(
                run, NEW_MODE, PROTOCOL_ID, run_id, new_remote_root,
                run["config_relpath"], run["completion_relpath"], run["monomer_relpath"],
                run["receptor_relpath"], run["restraint_relpath"], run["hotspot_relpath"],
                run["run_dir_relpath"], expected_hashes, None, "", "", "",
            )
        for value in descriptor.expected_hashes.values():
            require_hash(value, f"{run_id}.source hash")
        descriptors.append(descriptor)
    return descriptors


def validate_dual_lane_identity(descriptors: Sequence[SourceDescriptor]) -> None:
    by_case: dict[str, list[SourceDescriptor]] = {}
    for descriptor in descriptors:
        by_case.setdefault(descriptor.run["case_id"], []).append(descriptor)
    if len(by_case) != EXPECTED_CASES:
        raise RecoveryError(f"Dual-lane case count mismatch: {len(by_case)} != {EXPECTED_CASES}")
    identity_fields = (
        "case_rank", "candidate_id", "family", "sequence_sha256",
        "cdr1_range", "cdr2_range", "cdr3_range", "teacher_manifest_relpath",
        "teacher_manifest_sha256", "teacher_manifest_row_sha256", "execution_mode",
    )
    for case_id, lanes in by_case.items():
        if len(lanes) != 2 or {lane.run["receptor_id"] for lane in lanes} != set(EXPECTED_BY_RECEPTOR):
            raise RecoveryError(f"Case {case_id} does not have exactly two native receptor lanes")
        first, second = lanes
        for field in identity_fields:
            if first.run[field] != second.run[field]:
                raise RecoveryError(f"Dual-lane identity mismatch for {case_id}.{field}")
        if first.expected_hashes["monomer"] != second.expected_hashes["monomer"]:
            raise RecoveryError(f"Dual-lane identity mismatch for {case_id}.monomer_sha256")


def descriptor_sync_row(descriptor: SourceDescriptor) -> dict[str, str]:
    return {
        "run_id": descriptor.source_run_id,
        "config_relpath": descriptor.config_relpath,
        "completion_relpath": descriptor.completion_relpath,
        "monomer_relpath": descriptor.monomer_relpath,
        "receptor_relpath": descriptor.receptor_relpath,
        "restraint_relpath": descriptor.restraint_relpath,
        "hotspot_relpath": descriptor.hotspot_relpath,
        "run_dir_relpath": descriptor.run_dir_relpath,
    }


def parse_config_assignments(path: Path) -> tuple[str, dict[tuple[str, str], str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RecoveryError(f"Cannot read HADDOCK config: {path}") from error
    section = "root"
    assignments: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        assignments[(section, key.strip().lower())] = value.strip().rstrip(",")
    return text, assignments


def validate_config(path: Path, descriptor: SourceDescriptor) -> None:
    run = descriptor.run
    text, values = parse_config_assignments(path)
    marker = f"# Protocol: {descriptor.source_protocol_id}"
    if marker not in text:
        raise RecoveryError(f"Config protocol marker mismatch: {path}")
    expected = {
        ("root", "run_dir"): json.dumps(f"run_{descriptor.source_run_id}"),
        ("root", "ncores"): "4",
        ("topoaa", "iniseed"): "917",
        ("rigidbody", "iniseed"): run["rigidbody_iniseed"],
        ("rigidbody", "tolerance"): "5",
        ("rigidbody", "sampling"): "40",
        ("seletop", "select"): "10",
        ("flexref", "tolerance"): "20",
        ("emref", "tolerance"): "20",
    }
    for key, wanted in expected.items():
        if values.get(key) != wanted:
            raise RecoveryError(f"Config parameter mismatch in {path}: {key}={values.get(key)!r} != {wanted!r}")


def atom_heavy_identity_signature(
    coordinates: bytes, chain: str, path: Path
) -> dict[str, Any]:
    """Hash chain identity while deliberately excluding coordinates and HETATM."""
    try:
        text = coordinates.decode("ascii")
    except UnicodeDecodeError as error:
        raise RecoveryError(f"PDB is not ASCII: {path}") from error
    atoms: list[tuple[str, str, str, str, str, str]] = []
    residues: set[tuple[str, str, str]] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("ATOM  ") or len(line) < 54 or line[21:22] != chain:
            continue
        try:
            residue_number = int(line[22:26])
        except ValueError as error:
            raise RecoveryError(f"Unparseable ATOM residue number in {path}:{line_number}") from error
        resname = line[17:20].strip()
        atom_name = line[12:16].strip()
        insertion = line[26:27].strip()
        altloc = line[16:17].strip()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not resname or not atom_name:
            raise RecoveryError(f"Missing ATOM identity in {path}:{line_number}")
        is_heavy = element not in {"H", "D"} if element else not atom_name.upper().startswith(("H", "D"))
        if not is_heavy:
            continue
        residue_key = (str(residue_number), insertion, resname)
        atom_key = (*residue_key, atom_name, altloc, element)
        residues.add(residue_key)
        atoms.append(atom_key)
    if not atoms or not residues:
        raise RecoveryError(f"Chain {chain} has no heavy ATOM identity records: {path}")
    if len(atoms) != len(set(atoms)):
        raise RecoveryError(f"Chain {chain} has duplicate heavy ATOM identities: {path}")
    sorted_atoms = sorted(atoms)
    sorted_residues = sorted(residues)
    return {
        "chain": chain,
        "selection_rule": "ATOM-only heavy atoms; coordinates, serials, occupancy, and B-factor excluded",
        "atom_count": len(sorted_atoms),
        "residue_count": len(sorted_residues),
        "atom_identity_sha256": sha256_bytes(canonical_json(sorted_atoms).encode("utf-8")),
        "residue_identity_sha256": sha256_bytes(canonical_json(sorted_residues).encode("utf-8")),
    }


def require_identity_match(
    frozen: Mapping[str, Any], pose: Mapping[str, Any], label: str
) -> None:
    for field in (
        "atom_count", "residue_count", "atom_identity_sha256", "residue_identity_sha256"
    ):
        if frozen.get(field) != pose.get(field):
            raise RecoveryError(
                f"{label} ATOM identity mismatch for {field}: {pose.get(field)!r} != {frozen.get(field)!r}"
            )


def validate_stage_counts(counts: Any, io_count: int, label: str) -> dict[str, int]:
    if not isinstance(counts, dict):
        raise RecoveryError(f"{label} stage_output_counts is not an object")
    normalized = {key: parse_int(counts.get(key), f"{label}.{key}") for key in STAGE_OUTPUT_REQUIREMENTS}
    if normalized["emref"] != io_count:
        raise RecoveryError(f"{label} completion/io emref count mismatch")
    for stage, (operator, expected) in STAGE_OUTPUT_REQUIREMENTS.items():
        observed = normalized[stage]
        if (operator == "eq" and observed != expected) or (operator == "ge" and observed < expected):
            raise RecoveryError(f"{label} does not pass the V1.3 {stage} gate: {observed}")
    return normalized


def read_completion(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Cannot read completion marker: {path}") from error
    if not isinstance(payload, dict):
        raise RecoveryError(f"Completion marker is not an object: {path}")
    return payload


def validate_completion(
    path: Path, descriptor: SourceDescriptor, io_count: int
) -> tuple[dict[str, Any], dict[str, int]]:
    payload = read_completion(path)
    run = descriptor.run
    if descriptor.source_mode == REUSE_MODE:
        old = descriptor.reuse
        assert old is not None
        expected = {
            "protocol_id": OLD_PROTOCOL_ID,
            "run_id": descriptor.source_run_id,
            "receptor_id": run["receptor_id"],
            "seed_role": "main",
            "config_sha256": descriptor.expected_hashes["config"],
            "monomer_sha256": descriptor.expected_hashes["monomer"],
            "receptor_sha256": descriptor.expected_hashes["receptor"],
        }
        for field, value in expected.items():
            if payload.get(field) != value:
                raise RecoveryError(f"Old completion mismatch for {run['run_id']}.{field}")
        if str(payload.get("status", "")) != old["source_completion_status"]:
            raise RecoveryError(f"Old completion status drift for {run['run_id']}")
        if payload.get("status") not in {"PASS_DOCKING_OUTPUT_COMPLETE", "FAIL_DOCKING_OUTPUT_INCOMPLETE"}:
            raise RecoveryError(f"Unexpected old completion status for {run['run_id']}")
        if parse_int(payload.get("exit_code"), f"{run['run_id']}.exit_code") != 0:
            raise RecoveryError(f"Old completion exit code is not zero for {run['run_id']}")
        if payload.get("status") == "FAIL_DOCKING_OUTPUT_INCOMPLETE":
            if old["source_final_stage_ignored"].lower() != "true" or old["v1_3_emref_gate_status"] != "PASS_4_EMREF_TOP8_READY":
                raise RecoveryError(f"Old FAIL completion is not eligible for emref-only reuse: {run['run_id']}")
        counts = validate_stage_counts(payload.get("stage_output_counts"), io_count, run["run_id"])
        if canonical_json(counts) != old["source_stage_output_counts_json"]:
            raise RecoveryError(f"Old completion stage counts drift for {run['run_id']}")
    else:
        expected = {
            "protocol_id": PROTOCOL_ID,
            "run_id": run["run_id"],
            "case_id": run["case_id"],
            "candidate_id": run["candidate_id"],
            "receptor_id": run["receptor_id"],
            "status": "PASS_4_EMREF_TOP8_READY",
            "exit_code": 0,
            "config_sha256": descriptor.expected_hashes["config"],
            "monomer_sha256": descriptor.expected_hashes["monomer"],
            "receptor_sha256": descriptor.expected_hashes["receptor"],
            "fixed_top8_selection_performed": False,
            "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill",
            "formal_eligible": False,
            "training_label_release_eligible": False,
            "docking_gold_release_eligible": False,
        }
        for field, value in expected.items():
            if payload.get(field) != value:
                raise RecoveryError(f"New completion mismatch for {run['run_id']}.{field}")
        counts = validate_stage_counts(payload.get("stage_output_counts"), io_count, run["run_id"])
        requirements = payload.get("stage_output_requirements")
        if not isinstance(requirements, dict):
            raise RecoveryError(f"New completion lacks stage requirements: {run['run_id']}")
        expected_requirements = {
            stage: {"operator": operator, "value": expected}
            for stage, (operator, expected) in STAGE_OUTPUT_REQUIREMENTS.items()
        }
        if requirements != expected_requirements:
            raise RecoveryError(f"New completion stage requirements drift for {run['run_id']}")
    return payload, counts


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    os.replace(temporary, path)


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


def directory_inventory(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relpath = path.relative_to(root).as_posix()
        files.append({"relpath": relpath, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "file_hash_chain": sha256_bytes(
            "\n".join(canonical_json(item) for item in files).encode("utf-8")
        ),
        "files": files,
    }


def promote_current_symlink(release_dir: Path, current_link: Path) -> None:
    current_link.parent.mkdir(parents=True, exist_ok=True)
    if current_link.exists() and not current_link.is_symlink():
        raise RecoveryError(f"Current publication pointer is not a symlink: {current_link}")
    temporary = current_link.with_name(f".{current_link.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    target = os.path.relpath(release_dir, current_link.parent)
    os.symlink(target, temporary, target_is_directory=True)
    try:
        os.replace(temporary, current_link)
    finally:
        temporary.unlink(missing_ok=True)


def promote_versioned_release(
    staging: Path,
    release_dir: Path,
    current_link: Path,
    pointer_promoter: PointerPromoter,
) -> None:
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    if current_link.exists() and not current_link.is_symlink():
        raise RecoveryError(f"Current publication pointer is not a symlink: {current_link}")
    previous_release = current_link.resolve() if current_link.is_symlink() else None
    created = False
    if release_dir.exists():
        if directory_inventory(staging) != directory_inventory(release_dir):
            raise RecoveryError(f"Immutable publication version collision: {release_dir.name}")
        shutil.rmtree(staging)
    else:
        os.replace(staging, release_dir)
        created = True
    try:
        pointer_promoter(release_dir, current_link)
        if not current_link.is_symlink() or current_link.resolve() != release_dir.resolve():
            raise RecoveryError("Atomic current publication pointer verification failed")
    except Exception:
        if previous_release is not None:
            promote_current_symlink(previous_release, current_link)
        else:
            current_link.unlink(missing_ok=True)
        if created and release_dir.exists():
            shutil.rmtree(release_dir)
        raise


def local_asset_path(root: Path, descriptor: SourceDescriptor, key: str) -> Path:
    relpath = getattr(descriptor, f"{key}_relpath")
    return contained_path(root, relpath, f"{descriptor.run['run_id']}.{key}")


def verify_asset_hashes(root: Path, descriptor: SourceDescriptor) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    for key in ("config", "monomer", "receptor", "restraint", "hotspot"):
        path = local_asset_path(root, descriptor, key)
        validate_local_hash(path, descriptor.expected_hashes[key], f"{descriptor.run['run_id']}.{key}")
        assets[key] = path
    completion = local_asset_path(root, descriptor, "completion")
    if descriptor.source_mode == REUSE_MODE:
        validate_local_hash(completion, descriptor.expected_hashes["completion"], f"{descriptor.run['run_id']}.completion")
    assets["completion"] = completion
    return assets


def validate_selected_pose_invariants(
    selected: Sequence[recovery_base.PoseRecord], run: Mapping[str, str]
) -> tuple[list[str], list[int], int, int]:
    if len(selected) != K:
        raise RecoveryError(f"Selected pose count is not fixed K={K} for {run['run_id']}")
    coordinate_hashes = [record.coordinate_sha256 for record in selected]
    selected_seeds = [record.seed for record in selected]
    if len(set(coordinate_hashes)) != K:
        raise RecoveryError(f"Top-8 decompressed coordinate hashes are not unique for {run['run_id']}")
    if len(set(selected_seeds)) != K:
        raise RecoveryError(f"Top-8 pose seeds are not unique for {run['run_id']}")
    seed_start = parse_int(run["rigidbody_seed_start"], f"{run['run_id']}.rigidbody_seed_start")
    seed_end = parse_int(run["rigidbody_seed_end"], f"{run['run_id']}.rigidbody_seed_end")
    if any(seed < seed_start or seed > seed_end for seed in selected_seeds):
        raise RecoveryError(
            f"Top-8 pose seed falls outside frozen receptor-specific range for {run['run_id']}"
        )
    return coordinate_hashes, selected_seeds, seed_start, seed_end


def build(
    run_manifest_path: Path = DEFAULT_RUN_MANIFEST,
    reuse_manifest_path: Path = DEFAULT_REUSE_MANIFEST,
    package_audit_path: Path = DEFAULT_PACKAGE_AUDIT,
    execution_release_manifest_path: Path = DEFAULT_EXECUTION_RELEASE_MANIFEST,
    outdir: Path = DEFAULT_OUTDIR,
    audit_path: Path | None = None,
    output_csv: Path | None = None,
    inventory_only: bool = False,
    ssh_executable: str = "ssh.exe",
    host: str = "node1",
    workspace_root: Path = WORKSPACE_ROOT,
    release_data_root: Path = DATA_ROOT,
    sync_runner: SyncRunner | None = None,
    pointer_promoter: PointerPromoter = promote_current_symlink,
) -> dict[str, Any]:
    release = load_execution_release(
        execution_release_manifest_path,
        release_data_root,
        FROZEN_EXECUTION_RELEASE_SHA256,
    )
    runs, reuse = load_inputs(run_manifest_path, reuse_manifest_path)
    package_audit = load_package_audit(
        package_audit_path, runs, reuse, release, release_data_root
    )
    workspace_root = workspace_root.resolve()
    old_manifest, old_manifest_binding = old_manifest_context(reuse, workspace_root)
    validate_bound_old_files(reuse, workspace_root)

    ledger_old_roots = {row["source_old_remote_root"] for row in reuse.rows}
    if len(ledger_old_roots) != 1:
        raise RecoveryError("Reuse ledger binds multiple old remote roots")
    old_remote_root = next(iter(ledger_old_roots))
    package_old_root = str(package_audit.get("old_reuse_binding", {}).get("remote_root", ""))
    new_remote_root = str(release.payload.get("remote_root", ""))
    if package_audit.get("remote_root") != new_remote_root:
        raise RecoveryError("Package and frozen execution release new remote roots differ")
    if package_old_root != old_remote_root:
        raise RecoveryError("Package and exact-reuse old remote roots differ")
    for value, label in ((old_remote_root, "old remote root"), (new_remote_root, "new remote root")):
        path = PurePosixPath(value)
        if not value or not path.is_absolute() or "\x00" in value:
            raise RecoveryError(f"{label} is not an absolute POSIX path: {value!r}")

    descriptors = source_descriptors(
        runs, reuse, old_manifest, old_remote_root, new_remote_root
    )
    validate_dual_lane_identity(descriptors)
    by_mode = {mode: [item for item in descriptors if item.source_mode == mode] for mode in SOURCE_MODES}
    requests = {
        mode: recovery_base.build_sync_request(
            [descriptor_sync_row(item) for item in by_mode[mode]],
            old_remote_root if mode == REUSE_MODE else new_remote_root,
        )
        for mode in SOURCE_MODES
    }

    outdir = outdir.resolve()
    current_link = outdir / "current"
    canonical_csv = current_link / OUTPUT_CSV_NAME
    canonical_audit = current_link / AUDIT_NAME
    requested_csv = Path(os.path.abspath(output_csv or canonical_csv))
    requested_audit = Path(os.path.abspath(audit_path or canonical_audit))
    if requested_csv != Path(os.path.abspath(canonical_csv)):
        raise RecoveryError("Selector CSV must publish inside the atomic current release")
    if requested_audit != Path(os.path.abspath(canonical_audit)):
        raise RecoveryError("Recovery audit must publish inside the atomic current release")
    runner = sync_runner or recovery_base.sync_from_remote
    script_path = Path(__file__).resolve()
    script_sha = sha256_file(script_path)
    helper_path = Path(recovery_base.__file__).resolve()
    helper_sha = sha256_file(helper_path)
    release_id = "v1_3_" + sha256_bytes(canonical_json({
        "execution_release_sha256": release.sha256,
        "run_manifest_sha256": runs.sha256,
        "reuse_manifest_sha256": reuse.sha256,
        "selector_sha256": script_sha,
        "selector_helper_sha256": helper_sha,
    }).encode("utf-8"))[:24]
    release_dir = outdir / "releases" / release_id
    outdir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{release_id}.staging.", dir=outdir))
    work_root = staging
    source_subdirs = {REUSE_MODE: "sources/reuse_old_pilot64", NEW_MODE: "sources/new_v1_3"}
    if inventory_only:
        if not current_link.is_symlink():
            shutil.rmtree(staging)
            raise RecoveryError(f"Inventory-only current release is missing: {current_link}")
        current_release = current_link.resolve()
        for subdir in source_subdirs.values():
            source = current_release / subdir
            if not source.is_dir():
                shutil.rmtree(staging)
                raise RecoveryError(f"Inventory-only source directory is missing: {source}")
            shutil.copytree(source, staging / subdir)
    source_inventories: dict[str, dict[str, Any]] = {}
    try:
        for mode in SOURCE_MODES:
            source_root = work_root / source_subdirs[mode]
            request = requests[mode]
            if not inventory_only:
                runner(
                    request,
                    source_root,
                    ssh_executable,
                    host,
                    old_remote_root if mode == REUSE_MODE else new_remote_root,
                )
            remote_inventory, local_inventory = recovery_base.load_and_verify_inventory(source_root, request)
            source_inventories[mode] = {
                "remote": remote_inventory,
                "local": local_inventory,
                "source_root": source_root,
            }

        output_rows: list[dict[str, str]] = []
        run_audits: list[dict[str, Any]] = []
        source_pose_count = 0
        for descriptor in descriptors:
            run = descriptor.run
            mode = descriptor.source_mode
            source_root = source_inventories[mode]["source_root"]
            assets = verify_asset_hashes(source_root, descriptor)
            validate_config(assets["config"], descriptor)
            monomer_coordinates = recovery_base.read_coordinate_bytes(assets["monomer"])
            receptor_coordinates = recovery_base.read_coordinate_bytes(assets["receptor"])
            monomer_inventory = recovery_base.parse_chain_inventory(
                monomer_coordinates, assets["monomer"]
            )
            receptor_inventory = recovery_base.parse_chain_inventory(
                receptor_coordinates, assets["receptor"]
            )
            recovery_base.require_chain(monomer_inventory, "A", "Frozen monomer", assets["monomer"])
            recovery_base.require_chain(receptor_inventory, "B", "Frozen receptor", assets["receptor"])
            monomer_identity = atom_heavy_identity_signature(
                monomer_coordinates, "A", assets["monomer"]
            )
            receptor_identity = atom_heavy_identity_signature(
                receptor_coordinates, "B", assets["receptor"]
            )
            io_relpath = f"{descriptor.run_dir_relpath}/4_emref/io.json"
            params_relpath = f"{descriptor.run_dir_relpath}/4_emref/params.cfg"
            selected, pose_inventory = recovery_base.load_pose_records(source_root, io_relpath)
            source_pose_count += pose_inventory["source_output_count"]
            io_path = contained_path(source_root, io_relpath, f"{run['run_id']}.io")
            params_path = contained_path(source_root, params_relpath, f"{run['run_id']}.params")
            if mode == REUSE_MODE:
                assert descriptor.reuse is not None
                if pose_inventory["source_output_count"] != parse_int(
                    descriptor.reuse["source_emref_output_count"],
                    f"{run['run_id']}.source_emref_output_count",
                ):
                    raise RecoveryError(f"Reuse io output count drift for {run['run_id']}")
                validate_local_hash(io_path, descriptor.expected_hashes["io"], f"{run['run_id']}.io")
                validate_local_hash(params_path, descriptor.expected_hashes["params"], f"{run['run_id']}.params")
            recovery_base.validate_params(params_path, run)
            completion, stage_counts = validate_completion(
                assets["completion"], descriptor, pose_inventory["source_output_count"]
            )
            coordinate_hashes, selected_seeds, seed_start, seed_end = (
                validate_selected_pose_invariants(selected, run)
            )
            source_inventory = source_inventories[mode]
            selected_indices: list[int] = []
            for rank, record in enumerate(selected, start=1):
                selected_indices.append(record.output_index)
                materialized_rel = f"materialized_coordinates/{run['run_id']}/native_rank_{rank:02d}.pdb"
                materialized = contained_path(work_root, materialized_rel, "materialized coordinate")
                coordinates = recovery_base.read_coordinate_bytes(record.local_path)
                pose_vhh_identity = atom_heavy_identity_signature(
                    coordinates, "A", record.local_path
                )
                pose_pvrig_identity = atom_heavy_identity_signature(
                    coordinates, "B", record.local_path
                )
                require_identity_match(
                    monomer_identity, pose_vhh_identity, f"{run['run_id']} rank {rank} chain A"
                )
                require_identity_match(
                    receptor_identity, pose_pvrig_identity, f"{run['run_id']} rank {rank} chain B"
                )
                atomic_write_bytes(materialized, coordinates)
                if sha256_file(materialized) != record.coordinate_sha256:
                    raise RecoveryError(f"Materialized coordinate hash mismatch for {run['run_id']} rank {rank}")
                raw_final = release_dir / record.local_path.relative_to(work_root)
                materialized_final = release_dir / materialized_rel
                vhh, pvrig = record.vhh_inventory, record.pvrig_inventory
                ledger = descriptor.reuse
                output: dict[str, Any] = {
                    "schema_version": "phase2_v3_p2_v1_3_dual47_emref_top8_selection_v1",
                    "protocol_id": PROTOCOL_ID,
                    "source_protocol_id": descriptor.source_protocol_id,
                    "source_protocol": SOURCE_PROTOCOL,
                    "source_stage": SOURCE_STAGE,
                    "source_mode": mode,
                    "run_id": run["run_id"],
                    "source_run_id": descriptor.source_run_id,
                    "case_rank": run["case_rank"],
                    "case_id": run["case_id"],
                    "candidate_id": run["candidate_id"],
                    "family": run["family"],
                    "anchor_class": run["anchor_class"],
                    "calibration_role": run["calibration_role"],
                    "sequence_sha256": run["sequence_sha256"],
                    "teacher_manifest_relpath": run["teacher_manifest_relpath"],
                    "teacher_manifest_sha256": run["teacher_manifest_sha256"],
                    "teacher_manifest_row_sha256": run["teacher_manifest_row_sha256"],
                    "generation_receptor": run["receptor_id"],
                    "receptor_id": run["receptor_id"],
                    "seed_role": run["seed_role"],
                    "topoaa_iniseed": run["topoaa_iniseed"],
                    "rigidbody_iniseed": run["rigidbody_iniseed"],
                    "rigidbody_seed_start": run["rigidbody_seed_start"],
                    "rigidbody_seed_end": run["rigidbody_seed_end"],
                    "cdr1_range": run["cdr1_range"],
                    "cdr2_range": run["cdr2_range"],
                    "cdr3_range": run["cdr3_range"],
                    "native_rank": rank,
                    "canonical_rank": rank,
                    "source_output_index": record.output_index,
                    "source_output_file": record.file_name,
                    "source_score": format(record.score, ".17g"),
                    "source_seed": record.seed,
                    "source_pose_relpath": workspace_relative(raw_final, workspace_root),
                    "remote_source_pose_relpath": record.remote_relpath,
                    "materialized_coordinate_relpath": workspace_relative(materialized_final, workspace_root),
                    "source_pose_format": "pdb.gz" if record.local_path.name.endswith(".gz") else "pdb",
                    "source_pose_sha256": record.source_sha256,
                    "source_pose_bytes": record.source_bytes,
                    "compressed_source_sha256": record.source_sha256,
                    "compressed_source_bytes": record.source_bytes,
                    "decompressed_coordinate_sha256": record.coordinate_sha256,
                    "decompressed_coordinate_bytes": record.coordinate_bytes,
                    "materialized_coordinate_sha256": record.coordinate_sha256,
                    "materialized_coordinate_bytes": record.coordinate_bytes,
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
                    "monomer_atom_identity_sha256": monomer_identity["atom_identity_sha256"],
                    "monomer_residue_identity_sha256": monomer_identity["residue_identity_sha256"],
                    "pose_vhh_atom_identity_sha256": pose_vhh_identity["atom_identity_sha256"],
                    "pose_vhh_residue_identity_sha256": pose_vhh_identity["residue_identity_sha256"],
                    "receptor_atom_identity_sha256": receptor_identity["atom_identity_sha256"],
                    "receptor_residue_identity_sha256": receptor_identity["residue_identity_sha256"],
                    "pose_pvrig_atom_identity_sha256": pose_pvrig_identity["atom_identity_sha256"],
                    "pose_pvrig_residue_identity_sha256": pose_pvrig_identity["residue_identity_sha256"],
                    "completion_status": completion["status"],
                    "completion_exit_code": completion.get("exit_code", ""),
                    "source_final_stage_ignored": "true" if mode == REUSE_MODE else "false",
                    "remote_root": descriptor.remote_root,
                    "config_relpath": workspace_relative(release_dir / source_subdirs[mode] / descriptor.config_relpath, workspace_root),
                    "remote_config_relpath": descriptor.config_relpath,
                    "completion_relpath": workspace_relative(release_dir / source_subdirs[mode] / descriptor.completion_relpath, workspace_root),
                    "remote_completion_relpath": descriptor.completion_relpath,
                    "monomer_relpath": workspace_relative(release_dir / source_subdirs[mode] / descriptor.monomer_relpath, workspace_root),
                    "remote_monomer_relpath": descriptor.monomer_relpath,
                    "receptor_relpath": workspace_relative(release_dir / source_subdirs[mode] / descriptor.receptor_relpath, workspace_root),
                    "remote_receptor_relpath": descriptor.receptor_relpath,
                    "restraint_relpath": workspace_relative(release_dir / source_subdirs[mode] / descriptor.restraint_relpath, workspace_root),
                    "remote_restraint_relpath": descriptor.restraint_relpath,
                    "hotspot_relpath": workspace_relative(release_dir / source_subdirs[mode] / descriptor.hotspot_relpath, workspace_root),
                    "remote_hotspot_relpath": descriptor.hotspot_relpath,
                    "source_params_relpath": workspace_relative(release_dir / source_subdirs[mode] / params_relpath, workspace_root),
                    "remote_source_params_relpath": params_relpath,
                    "source_io_relpath": workspace_relative(release_dir / source_subdirs[mode] / io_relpath, workspace_root),
                    "remote_source_io_relpath": io_relpath,
                    "completion_sha256": sha256_file(assets["completion"]),
                    "config_sha256": sha256_file(assets["config"]),
                    "monomer_sha256": sha256_file(assets["monomer"]),
                    "receptor_sha256": sha256_file(assets["receptor"]),
                    "restraint_sha256": sha256_file(assets["restraint"]),
                    "hotspot_sha256": sha256_file(assets["hotspot"]),
                    "source_params_sha256": sha256_file(params_path),
                    "source_io_sha256": sha256_file(io_path),
                    "run_manifest_relpath": workspace_relative(runs.path, workspace_root),
                    "run_manifest_sha256": runs.sha256,
                    "run_manifest_row_sha256": run["run_manifest_row_sha256"],
                    "exact_reuse_manifest_relpath": workspace_relative(reuse.path, workspace_root),
                    "exact_reuse_manifest_sha256": reuse.sha256,
                    "exact_reuse_manifest_row_sha256": ledger["reuse_manifest_row_sha256"] if ledger else "",
                    "source_old_run_manifest_relpath": descriptor.old_manifest_relpath,
                    "source_old_run_manifest_sha256": descriptor.old_manifest_sha256,
                    "source_old_run_manifest_row_sha256": descriptor.old_manifest_row_sha256,
                    "execution_release_manifest_relpath": workspace_relative(release.path, workspace_root),
                    "execution_release_manifest_sha256": release.sha256,
                    "publication_release_id": release_id,
                    "remote_inventory_request_sha256": requests[mode]["request_sha256"],
                    "remote_file_hash_chain": source_inventory["remote"]["file_hash_chain"],
                    "local_file_hash_chain": source_inventory["local"]["file_hash_chain"],
                    "selector_implementation_relpath": workspace_relative(script_path, workspace_root),
                    "selector_implementation_sha256": script_sha,
                    "selector_helper_relpath": workspace_relative(helper_path, workspace_root),
                    "selector_helper_sha256": helper_sha,
                    "formal_eligible": "false",
                    "training_label_release_eligible": "false",
                    "docking_gold_release_eligible": "false",
                    "claim_boundary": CLAIM_BOUNDARY,
                    "selection_row_sha256": "",
                }
                normalized = {field: str(output.get(field, "")) for field in CSV_FIELDS}
                normalized["selection_row_sha256"] = row_sha256(normalized, "selection_row_sha256")
                output_rows.append(normalized)
            run_audits.append({
                "run_id": run["run_id"],
                "source_run_id": descriptor.source_run_id,
                "source_mode": mode,
                "case_id": run["case_id"],
                "candidate_id": run["candidate_id"],
                "family": run["family"],
                "anchor_class": run["anchor_class"],
                "generation_receptor": run["receptor_id"],
                "completion_status": completion["status"],
                "source_final_stage_ignored": mode == REUSE_MODE,
                "stage_output_counts": stage_counts,
                "source_output_count": pose_inventory["source_output_count"],
                "selected_pose_count": K,
                "selected_source_output_indices": selected_indices,
                "selected_pose_seeds": selected_seeds,
                "selected_coordinate_hashes": coordinate_hashes,
                "frozen_seed_range": {"start": seed_start, "end": seed_end},
                "monomer_atom_identity": monomer_identity,
                "receptor_atom_identity": receptor_identity,
                "config_sha256": sha256_file(assets["config"]),
                "completion_sha256": sha256_file(assets["completion"]),
                "source_io_sha256": sha256_file(io_path),
                "source_params_sha256": sha256_file(params_path),
            })

        run_counts_receptor = Counter(row["generation_receptor"] for row in output_rows[::K])
        pose_counts_receptor = Counter(row["generation_receptor"] for row in output_rows)
        run_counts_mode = Counter(item.source_mode for item in descriptors)
        pose_counts_mode = Counter(row["source_mode"] for row in output_rows)
        if len(output_rows) != EXPECTED_POSES:
            raise RecoveryError(f"Fixed Top-8 cardinality mismatch: {len(output_rows)} != {EXPECTED_POSES}")
        if dict(run_counts_receptor) != EXPECTED_BY_RECEPTOR or dict(pose_counts_receptor) != EXPECTED_POSES_BY_RECEPTOR:
            raise RecoveryError("Per-receptor 47-run/376-pose closure failed")
        if dict(run_counts_mode) != EXPECTED_RUNS_BY_MODE or dict(pose_counts_mode) != EXPECTED_POSES_BY_MODE:
            raise RecoveryError("Per-source-mode run/pose closure failed")
        if len({row["candidate_id"] for row in output_rows}) != EXPECTED_CASES:
            raise RecoveryError("47-candidate selector closure failed")
        if any(
            source_inventories[mode]["remote"]["file_hash_chain"]
            != source_inventories[mode]["local"]["file_hash_chain"]
            for mode in SOURCE_MODES
        ):
            raise RecoveryError("At least one remote/local source inventory differs")
        if sha256_file(runs.path) != runs.sha256 or sha256_file(reuse.path) != reuse.sha256:
            raise RecoveryError("Input manifests changed during recovery")
        refreshed = {
            mode: recovery_base.file_inventory(
                source_inventories[mode]["source_root"],
                [item["relpath"] for item in source_inventories[mode]["local"]["files"]],
            )
            for mode in SOURCE_MODES
        }
        if any(refreshed[mode] != source_inventories[mode]["local"] for mode in SOURCE_MODES):
            raise RecoveryError("Recovered source inputs changed while selecting Top-8")

        internal_csv = work_root / OUTPUT_CSV_NAME
        write_csv_atomic(internal_csv, output_rows)
        selector_sha = sha256_file(internal_csv)

        source_audit_summary = {}
        for mode in SOURCE_MODES:
            remote, local = source_inventories[mode]["remote"], source_inventories[mode]["local"]
            source_audit_summary[mode] = {
                "remote_root": old_remote_root if mode == REUSE_MODE else new_remote_root,
                "request_sha256": requests[mode]["request_sha256"],
                "inventory_relpath": requests[mode]["inventory_relpath"],
                "remote_file_count": remote["file_count"],
                "remote_total_bytes": remote["total_bytes"],
                "remote_file_hash_chain": remote["file_hash_chain"],
                "local_file_count": local["file_count"],
                "local_total_bytes": local["total_bytes"],
                "local_file_hash_chain": local["file_hash_chain"],
                "remote_local_hash_chain_equal": remote["file_hash_chain"] == local["file_hash_chain"],
            }
        audit: dict[str, Any] = {
            "schema_version": "phase2_v3_p2_v1_3_dual47_emref_top8_recovery_audit_v1",
            "status": "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED",
            "protocol_id": PROTOCOL_ID,
            "source_protocol": SOURCE_PROTOCOL,
            "source_stage": SOURCE_STAGE,
            "host": host,
            "old_remote_root": old_remote_root,
            "new_remote_root": new_remote_root,
            "k": K,
            "selection_order": ["ascending_haddock_score", "original_io_index", "file_name"],
            "selection_backfill": False,
            "docking_launched": False,
            "scoring_performed": False,
            "formal_eligible": False,
            "training_label_release_eligible": False,
            "docking_gold_release_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
            "counts": {
                "manifest_runs": len(runs.rows),
                "reuse_runs": EXPECTED_REUSE_RUNS,
                "new_runs": EXPECTED_NEW_RUNS,
                "selected_runs": len(descriptors),
                "source_poses": source_pose_count,
                "selected_poses": len(output_rows),
                "cases": len({row["case_id"] for row in output_rows}),
            },
            "run_counts_by_receptor": dict(run_counts_receptor),
            "pose_counts_by_receptor": dict(pose_counts_receptor),
            "run_counts_by_source_mode": dict(run_counts_mode),
            "pose_counts_by_source_mode": dict(pose_counts_mode),
            "expected_run_counts_by_receptor": EXPECTED_BY_RECEPTOR,
            "expected_pose_counts_by_receptor": EXPECTED_POSES_BY_RECEPTOR,
            "inputs": {
                "execution_release_manifest": {
                    "relpath": workspace_relative(release.path, workspace_root),
                    "sha256": release.sha256,
                    "status": release.payload["status"],
                },
                "run_manifest": {"relpath": workspace_relative(runs.path, workspace_root), "sha256": runs.sha256},
                "exact_reuse_manifest": {"relpath": workspace_relative(reuse.path, workspace_root), "sha256": reuse.sha256},
                "package_audit": {"relpath": workspace_relative(package_audit_path.resolve(), workspace_root), "sha256": sha256_file(package_audit_path.resolve())},
                "old_run_manifest": old_manifest_binding,
            },
            "source_inventories": source_audit_summary,
            "remote_local_hash_chain_equal": all(
                value["remote_local_hash_chain_equal"] for value in source_audit_summary.values()
            ),
            "runs": run_audits,
            "selector": {"relpath": workspace_relative(script_path, workspace_root), "sha256": script_sha},
            "selector_helper": {"relpath": workspace_relative(helper_path, workspace_root), "sha256": helper_sha},
            "publication": {
                "release_id": release_id,
                "release_relpath": workspace_relative(release_dir, workspace_root),
                "current_pointer_relpath": workspace_relative_lexical(current_link, workspace_root),
                "atomic_unit": "versioned directory containing sources, materialized coordinates, selector CSV, and audit JSON",
                "promotion": "single atomic current symlink replacement",
                "rollback_safe": True,
            },
            "output_csv": {
                "relpath": workspace_relative(release_dir / OUTPUT_CSV_NAME, workspace_root),
                "sha256": selector_sha,
                "rows": len(output_rows),
                "selection_row_hash_chain": sha256_bytes(
                    "\n".join(row["selection_row_sha256"] for row in output_rows).encode("ascii")
                ),
            },
        }
        write_json_atomic(work_root / AUDIT_NAME, audit)
        staged_inventory = directory_inventory(work_root)
        if staged_inventory["file_count"] < EXPECTED_POSES + 2:
            raise RecoveryError("Versioned publication staging inventory is unexpectedly incomplete")
        promote_versioned_release(staging, release_dir, current_link, pointer_promoter)
        staging = None
        final_csv = current_link / OUTPUT_CSV_NAME
        final_audit = current_link / AUDIT_NAME
        if sha256_file(final_csv) != selector_sha:
            raise RecoveryError("Published selector CSV hash differs from staged selector")
        published_audit = json.loads(final_audit.read_text(encoding="utf-8"))
        if published_audit != audit:
            raise RecoveryError("Published recovery audit differs from staged audit")
        return audit
    except Exception:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_RUN_MANIFEST)
    parser.add_argument("--exact-reuse-manifest", type=Path, default=DEFAULT_REUSE_MANIFEST)
    parser.add_argument("--package-audit", type=Path, default=DEFAULT_PACKAGE_AUDIT)
    parser.add_argument(
        "--execution-release-manifest",
        type=Path,
        default=DEFAULT_EXECUTION_RELEASE_MANIFEST,
    )
    parser.add_argument("--ssh-executable", default="ssh.exe")
    parser.add_argument("--host", default="node1")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--inventory-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    audit = build(
        run_manifest_path=args.run_manifest,
        reuse_manifest_path=args.exact_reuse_manifest,
        package_audit_path=args.package_audit,
        execution_release_manifest_path=args.execution_release_manifest,
        outdir=args.outdir,
        audit_path=args.audit,
        output_csv=args.output_csv,
        inventory_only=args.inventory_only,
        ssh_executable=args.ssh_executable,
        host=args.host,
    )
    print(json.dumps({
        "status": audit["status"],
        "selected_runs": audit["counts"]["selected_runs"],
        "selected_poses": audit["counts"]["selected_poses"],
        "output_csv": audit["output_csv"]["relpath"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
