#!/usr/bin/env python3
"""Build threshold-free native Top-8 geometry metrics for V1.3 development.

Each selector row is one independently docked pose.  The pose is aligned only
to its generation receptor, raw PVRIG--VHH hotspot contacts are scored once in
that receptor's native numbering, and PVRL2 occlusion is computed only against
the matching native reference.  This processor never emits pose classes,
candidate tiers, training labels, or an R_gold score.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import process_phase2_v3_p2_v1_2_top8_calibration as core


EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
DOCKING_SCRIPTS = WORKSPACE_ROOT / "docking/scripts"

PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL_NATIVE_DEV"
SELECTOR_PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
SELECTOR_SCHEMA = "phase2_v3_p2_v1_3_dual47_emref_top8_selection_v1"
SELECTOR_AUDIT_SCHEMA = (
    "phase2_v3_p2_v1_3_dual47_emref_top8_recovery_audit_v1"
)
SELECTOR_AUDIT_STATUS = "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED"
SCORING_SEMANTICS_VERSION = "PVRIG_PVRL2_ATOM_ONLY_V1_2"
POSE_SOURCE_PROTOCOL = "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1"
REUSE_SOURCE_MODE = "REUSE_OLD_PILOT64_MAIN"
NEW_SOURCE_MODE = "NEW_DUAL_DOCKING_COMPLETION"
CLAIM_BOUNDARY = (
    "independent dual-receptor native-only computational geometry development "
    "evidence; not Docking Gold, not a training label release, and not "
    "experimental binding, affinity, Kd, or blocking truth"
)

DEFAULT_SELECTOR_CSV = (
    EXP_DIR
    / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_top8_recovery/current/"
    "pvrig_v1_3_dual47_emref_top8_selector.csv"
)
DEFAULT_SELECTOR_AUDIT = (
    EXP_DIR
    / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_top8_recovery/current/"
    "pvrig_v1_3_dual47_emref_top8_recovery_audit.json"
)
DEFAULT_SELECTOR_IMPLEMENTATION = (
    SCRIPT_DIR / "recover_phase2_v3_p2_v1_3_dual47_emref_top8.py"
)
DEFAULT_PREREGISTRATION = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_development_preregistration.json"
)
DEFAULT_RELEASE_MANIFEST = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_development_release_manifest.json"
)
DEFAULT_POSITIVE_MANIFEST = (
    WORKSPACE_ROOT / "docking/calibration/patent_success_validation/batch_manifest.csv"
)
DEFAULT_MUTANT_MANIFEST = (
    WORKSPACE_ROOT / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
)
DEFAULT_ALIGNER = DOCKING_SCRIPTS / "align_pdb_by_chain.py"
DEFAULT_POSE_SCORER = DOCKING_SCRIPTS / "score_pvrig_vhh_pose_v1_2.py"
DEFAULT_REGION_SCORER = DOCKING_SCRIPTS / "score_cdr_region_occlusion_v1_2.py"
DEFAULT_SCORING_HELPER = DOCKING_SCRIPTS / "pvrig_scoring_semantics_v1_2.py"
DEFAULT_HOTSPOTS = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
DEFAULT_RECONCILIATION = DATA_ROOT / "structures/PVRIG_numbering_reconciliation.csv"
DEFAULT_PROCESSOR_TEST = SCRIPT_DIR / "test_process_phase2_v3_p2_v1_3_native_top8.py"
DEFAULT_OUTDIR = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_native_processing"
)

RECEPTORS: Mapping[str, Mapping[str, Any]] = {
    "8X6B": {
        "reference": DATA_ROOT / "structures/8X6B.pdb",
        "reference_pvrig_chain": "B",
        "reference_pvrl2_chain": "A",
        "hotspot_ref_column": "pdb_8x6b_ref",
    },
    "9E6Y": {
        "reference": DATA_ROOT / "structures/9E6Y.pdb",
        "reference_pvrig_chain": "A",
        "reference_pvrl2_chain": "D",
        "hotspot_ref_column": "pdb_9e6y_ref",
    },
}

DEFAULT_EXPECTED_REFERENCE_INVENTORIES: Mapping[str, Mapping[str, Any]] = {
    "8X6B": dict(core.DEFAULT_EXPECTED_REFERENCE_INVENTORIES["8x6b"]),
    "9E6Y": dict(core.DEFAULT_EXPECTED_REFERENCE_INVENTORIES["9e6y"]),
}

MATERIALIZATION_MANIFEST_NAME = (
    "pvrig_v1_3_native_top8_pose_materialization_manifest.csv"
)
CONTINUOUS_METRICS_NAME = "pvrig_v1_3_native_top8_continuous_metrics.csv"
RESIDUE_CONTACTS_NAME = "pvrig_v1_3_native_top8_residue_contacts.jsonl"
AUDIT_NAME = "pvrig_v1_3_native_top8_processing_audit.json"

SELECTOR_REQUIRED_FIELDS = {
    "schema_version",
    "protocol_id",
    "source_protocol",
    "source_stage",
    "source_mode",
    "run_id",
    "source_run_id",
    "case_id",
    "candidate_id",
    "family",
    "anchor_class",
    "sequence_sha256",
    "teacher_manifest_relpath",
    "teacher_manifest_sha256",
    "teacher_manifest_row_sha256",
    "generation_receptor",
    "receptor_id",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "native_rank",
    "canonical_rank",
    "source_output_index",
    "source_output_file",
    "source_score",
    "source_seed",
    "source_pose_relpath",
    "materialized_coordinate_relpath",
    "source_pose_format",
    "source_pose_sha256",
    "source_pose_bytes",
    "compressed_source_sha256",
    "compressed_source_bytes",
    "decompressed_coordinate_sha256",
    "decompressed_coordinate_bytes",
    "materialized_coordinate_sha256",
    "materialized_coordinate_bytes",
    "vhh_chain_id",
    "vhh_atom_count",
    "vhh_residue_count",
    "vhh_chain_inventory_json",
    "pvrig_chain_id",
    "pvrig_atom_count",
    "pvrig_residue_count",
    "pvrig_chain_inventory_json",
    "monomer_atom_identity_sha256",
    "monomer_residue_identity_sha256",
    "pose_vhh_atom_identity_sha256",
    "pose_vhh_residue_identity_sha256",
    "receptor_atom_identity_sha256",
    "receptor_residue_identity_sha256",
    "pose_pvrig_atom_identity_sha256",
    "pose_pvrig_residue_identity_sha256",
    "completion_status",
    "completion_exit_code",
    "config_sha256",
    "monomer_sha256",
    "receptor_sha256",
    "restraint_sha256",
    "hotspot_sha256",
    "source_params_sha256",
    "source_io_sha256",
    "run_manifest_sha256",
    "run_manifest_row_sha256",
    "execution_release_manifest_relpath",
    "execution_release_manifest_sha256",
    "publication_release_id",
    "remote_inventory_request_sha256",
    "remote_file_hash_chain",
    "local_file_hash_chain",
    "selector_implementation_relpath",
    "selector_implementation_sha256",
    "selector_helper_relpath",
    "selector_helper_sha256",
    "formal_eligible",
    "training_label_release_eligible",
    "docking_gold_release_eligible",
    "selection_row_sha256",
}

INTERNAL_CONTACT_METRICS = core.INTERNAL_CONTACT_METRICS
INTERNAL_CONTACT_LIST_FIELDS = core.INTERNAL_CONTACT_LIST_FIELDS
REGION_TOTAL_METRICS = core.REGION_TOTAL_METRICS
REGION_ITEM_METRICS = core.REGION_ITEM_METRICS
REGIONS = core.REGIONS

MATERIALIZATION_FIELDS = (
    "schema_version",
    "protocol_id",
    "formal_eligible",
    "training_label_release_eligible",
    "docking_gold_release_eligible",
    "primary_native_metric_eligible",
    "native_only",
    "run_id",
    "source_mode",
    "candidate_id",
    "family",
    "evidence_role",
    "control_descriptor",
    "usage_boundary",
    "generation_receptor",
    "native_rank",
    "source_output_index",
    "source_score",
    "source_seed",
    "selector_row_sha256",
    "source_pose_relpath",
    "source_pose_sha256",
    "source_pose_bytes",
    "materialized_coordinate_relpath",
    "materialized_coordinate_sha256",
    "materialized_coordinate_bytes",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "alignment_map_relpath",
    "alignment_map_sha256",
    "alignment_pair_count",
    "alignment_rmsd_a",
    "aligned_pose_relpath",
    "aligned_pose_sha256",
    "aligned_pose_bytes",
    "reference_relpath",
    "reference_sha256",
    "materialization_row_sha256",
)

METRICS_FIELDS = (
    "schema_version",
    "protocol_id",
    "formal_eligible",
    "training_label_release_eligible",
    "docking_gold_release_eligible",
    "primary_native_metric_eligible",
    "native_only",
    "run_id",
    "source_mode",
    "candidate_id",
    "family",
    "evidence_role",
    "control_descriptor",
    "usage_boundary",
    "generation_receptor",
    "native_rank",
    "source_output_index",
    "source_score",
    "source_seed",
    "selector_row_sha256",
    "aligned_pose_relpath",
    "aligned_pose_sha256",
    "alignment_pair_count",
    "alignment_rmsd_a",
    "alignment_map_relpath",
    "alignment_map_sha256",
    "reference_relpath",
    "reference_sha256",
    "native_hotspot_ref_column",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "pose_score_schema_version",
    "region_score_schema_version",
    "scoring_semantics_version",
    "internal_contact_channel",
    *INTERNAL_CONTACT_METRICS,
    *REGION_TOTAL_METRICS,
    *(
        f"{region.lower()}_{metric}"
        for region in REGIONS
        for metric in REGION_ITEM_METRICS
    ),
    "cdr123_occluding_residue_pair_count",
    "cdr123_occlusion_fraction",
    "pose_pvrig_record_inventory_json",
    "pose_vhh_record_inventory_json",
    "region_pose_vhh_record_inventory_json",
    "reference_pvrl2_record_inventory_json",
    "region_reference_pvrl2_record_inventory_json",
    "raw_native_internal_score_payload_sha256",
    "region_score_payload_sha256",
    "metrics_row_sha256",
)


class ContractError(RuntimeError):
    """Raised when a native-processing trust or cardinality contract fails."""


@dataclass(frozen=True)
class DatasetContract:
    positive_cases: int = 11
    mutant_cases: int = 36
    receptors: tuple[str, ...] = ("8X6B", "9E6Y")
    poses_per_run: int = 8
    reuse_run_count: int | None = 64
    new_run_count: int | None = 30

    @property
    def case_count(self) -> int:
        return self.positive_cases + self.mutant_cases

    @property
    def run_count(self) -> int:
        return self.case_count * len(self.receptors)

    @property
    def pose_count(self) -> int:
        return self.run_count * self.poses_per_run

    def as_dict(self) -> dict[str, Any]:
        return {
            "positive_cases": self.positive_cases,
            "mutant_cases": self.mutant_cases,
            "case_count": self.case_count,
            "receptors": list(self.receptors),
            "receptor_count": len(self.receptors),
            "poses_per_run": self.poses_per_run,
            "run_count": self.run_count,
            "pose_count": self.pose_count,
            "reuse_run_count": self.reuse_run_count,
            "new_run_count": self.new_run_count,
        }


@dataclass(frozen=True)
class BuildConfig:
    selector_csv: Path = DEFAULT_SELECTOR_CSV
    selector_audit: Path | None = DEFAULT_SELECTOR_AUDIT
    selector_implementation: Path = DEFAULT_SELECTOR_IMPLEMENTATION
    preregistration: Path = DEFAULT_PREREGISTRATION
    release_manifest: Path = DEFAULT_RELEASE_MANIFEST
    positive_manifest: Path = DEFAULT_POSITIVE_MANIFEST
    mutant_manifest: Path = DEFAULT_MUTANT_MANIFEST
    aligner: Path = DEFAULT_ALIGNER
    pose_scorer: Path = DEFAULT_POSE_SCORER
    region_scorer: Path = DEFAULT_REGION_SCORER
    scoring_helper: Path = DEFAULT_SCORING_HELPER
    hotspots: Path = DEFAULT_HOTSPOTS
    reconciliation: Path = DEFAULT_RECONCILIATION
    references: Mapping[str, Path] = field(
        default_factory=lambda: {
            receptor: Path(spec["reference"])
            for receptor, spec in RECEPTORS.items()
        }
    )
    expected_reference_inventories: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: {
            receptor: dict(values)
            for receptor, values in DEFAULT_EXPECTED_REFERENCE_INVENTORIES.items()
        }
    )
    outdir: Path = DEFAULT_OUTDIR
    workspace_root: Path = WORKSPACE_ROOT
    contract: DatasetContract = DatasetContract()
    jobs: int = 1


@dataclass(frozen=True)
class NativeResult:
    receptor: str
    aligned_pose_relpath: str
    aligned_pose_sha256: str
    aligned_pose_bytes: int
    alignment_map_relpath: str
    alignment_map_sha256: str
    alignment: core.AlignmentEvidence
    raw_report: Mapping[str, Any]
    region_report: Mapping[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ContractError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: Mapping[str, Any], hash_field: str) -> str:
    return sha256_json({key: value for key, value in row.items() if key != hash_field})


def canonical_input_path(path: Path, workspace_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_workspace_path(raw: str, workspace_root: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = workspace_root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError as error:
        raise ContractError(f"Selector path escapes workspace: {raw!r}") from error
    return resolved


def output_relative(path: Path, output_root: Path) -> str:
    try:
        return path.resolve().relative_to(output_root.resolve()).as_posix()
    except ValueError as error:
        raise ContractError(f"Output path escapes package root: {path}") from error


def parse_int(value: Any, field_name: str, minimum: int | None = None) -> int:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ContractError(f"{field_name} is not numeric: {value!r}") from error
    if not math.isfinite(number) or not number.is_integer():
        raise ContractError(f"{field_name} is not a finite integer: {value!r}")
    parsed = int(number)
    if minimum is not None and parsed < minimum:
        raise ContractError(f"{field_name} must be >= {minimum}, got {parsed}")
    return parsed


def parse_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ContractError(f"{field_name} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise ContractError(f"{field_name} is not finite: {value!r}")
    return parsed


def parse_bool(value: Any, field_name: str) -> bool:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    raise ContractError(f"{field_name} is not boolean: {value!r}")


def scalar_text(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"Non-finite metric {field_name}: {value!r}")
        return format(value, ".17g")
    if isinstance(value, str):
        return value
    raise ContractError(f"Non-scalar metric {field_name}: {type(value).__name__}")


def read_csv_strict(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise ContractError(f"CSV input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ContractError(f"CSV input has no header: {path}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ContractError(f"CSV input has duplicate fields: {path}")
        rows = list(reader)
    if not rows:
        raise ContractError(f"CSV input has no rows: {path}")
    return list(reader.fieldnames), rows


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def safe_component(value: str, field_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ContractError(f"Unsafe {field_name}: {value!r}")
    return value


def assert_finite_tree(value: Any, context: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"Non-finite numeric value in {context}: {value!r}")
    if isinstance(value, dict):
        for key, nested in value.items():
            assert_finite_tree(nested, f"{context}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            assert_finite_tree(nested, f"{context}[{index}]")


def is_forbidden_output_field(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(
        token in lowered
        for token in (
            "geometry_class",
            "native_class",
            "blocker_class",
            "geometry_tier",
            "dual_tier",
            "relevance_label",
            "training_label",
            "r_gold",
        )
    ) and lowered != "training_label_release_eligible"


def assert_no_forbidden_output_fields(value: Any, context: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if is_forbidden_output_field(str(key)):
                raise ContractError(f"Forbidden output field {key!r} in {context}")
            assert_no_forbidden_output_fields(nested, context)
    elif isinstance(value, list):
        for nested in value:
            assert_no_forbidden_output_fields(nested, context)


def required_mapping(parent: Mapping[str, Any], key: str, context: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"Missing mapping {key!r} in {context}")
    return value


def parse_inventory_json(row: Mapping[str, str], field_name: str) -> Mapping[str, Any]:
    try:
        inventory = json.loads(row[field_name])
    except (KeyError, json.JSONDecodeError) as error:
        raise ContractError(f"Invalid selector inventory {field_name}") from error
    if not isinstance(inventory, dict):
        raise ContractError(f"Selector inventory {field_name} must be an object")
    assert_finite_tree(inventory, field_name)
    return inventory


def validate_preregistration(path: Path, contract: DatasetContract) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Invalid V1.3 preregistration: {path}") from error
    expected = {
        "protocol_id": PROTOCOL_ID,
        "status": "PREREGISTERED_V1_3_DEVELOPMENT_ONLY_PENDING_IMPLEMENTATION",
        "training_state": "P2_TRAINING_BLOCKED",
    }
    mismatches = {
        key: (payload.get(key), value)
        for key, value in expected.items()
        if payload.get(key) != value
    }
    primary = required_mapping(payload, "primary_processing", "preregistration")
    eligibility = required_mapping(payload, "eligibility", "preregistration")
    if primary.get("native_only") is not True:
        mismatches["primary_processing.native_only"] = (
            primary.get("native_only"),
            True,
        )
    if primary.get("expected_native_pose_count") != contract.pose_count:
        mismatches["primary_processing.expected_native_pose_count"] = (
            primary.get("expected_native_pose_count"),
            contract.pose_count,
        )
    for key in (
        "formal_eligible",
        "p2_training_ready",
        "training_label_release_eligible",
        "docking_gold_release_eligible",
    ):
        if eligibility.get(key) is not False:
            mismatches[f"eligibility.{key}"] = (eligibility.get(key), False)
    if mismatches:
        raise ContractError(f"V1.3 preregistration contract mismatch: {mismatches}")
    return payload


def load_case_metadata(config: BuildConfig) -> dict[str, core.CaseMetadata]:
    try:
        positives = core.load_case_manifest(
            config.positive_manifest.resolve(),
            dataset="known_positive_calibration",
            expected_rows=config.contract.positive_cases,
        )
        mutants = core.load_case_manifest(
            config.mutant_manifest.resolve(),
            dataset="mutant_or_perturbation_control",
            expected_rows=config.contract.mutant_cases,
        )
    except core.ContractError as error:
        raise ContractError(str(error)) from error
    overlap = sorted(set(positives) & set(mutants))
    if overlap:
        raise ContractError(f"Case manifests overlap: {overlap}")
    return {**positives, **mutants}


def verify_selector_audit(
    path: Path,
    selector_csv: Path,
    rows: Sequence[Mapping[str, str]],
    config: BuildConfig,
) -> Mapping[str, Any]:
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Invalid selector audit: {path}") from error
    expected = {
        "schema_version": SELECTOR_AUDIT_SCHEMA,
        "status": SELECTOR_AUDIT_STATUS,
        "protocol_id": SELECTOR_PROTOCOL_ID,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "remote_local_hash_chain_equal": True,
        "source_protocol": POSE_SOURCE_PROTOCOL,
        "k": config.contract.poses_per_run,
        "selection_backfill": False,
        "scoring_performed": False,
    }
    mismatches = {
        key: (audit.get(key), value)
        for key, value in expected.items()
        if audit.get(key) != value
    }
    counts = required_mapping(audit, "counts", "selector audit")
    expected_counts = {
        "manifest_runs": config.contract.run_count,
        "selected_runs": config.contract.run_count,
        "selected_poses": config.contract.pose_count,
        "cases": config.contract.case_count,
    }
    for key, value in expected_counts.items():
        if counts.get(key) != value:
            mismatches[f"counts.{key}"] = (counts.get(key), value)
    expected_by_receptor = {
        receptor: config.contract.case_count for receptor in config.contract.receptors
    }
    expected_poses_by_receptor = {
        receptor: config.contract.case_count * config.contract.poses_per_run
        for receptor in config.contract.receptors
    }
    if audit.get("run_counts_by_receptor") != expected_by_receptor:
        mismatches["run_counts_by_receptor"] = (
            audit.get("run_counts_by_receptor"),
            expected_by_receptor,
        )
    if audit.get("pose_counts_by_receptor") != expected_poses_by_receptor:
        mismatches["pose_counts_by_receptor"] = (
            audit.get("pose_counts_by_receptor"),
            expected_poses_by_receptor,
        )
    output = required_mapping(audit, "output_csv", "selector audit")
    expected_chain = sha256_bytes(
        "\n".join(row["selection_row_sha256"] for row in rows).encode("ascii")
    )
    output_expected = {
        "sha256": sha256_file(selector_csv),
        "rows": len(rows),
        "selection_row_hash_chain": expected_chain,
    }
    for key, value in output_expected.items():
        if output.get(key) != value:
            mismatches[f"output_csv.{key}"] = (output.get(key), value)
    if config.contract.reuse_run_count is not None:
        if counts.get("reuse_runs") != config.contract.reuse_run_count:
            mismatches["counts.reuse_runs"] = (
                counts.get("reuse_runs"),
                config.contract.reuse_run_count,
            )
    if config.contract.new_run_count is not None:
        if counts.get("new_runs") != config.contract.new_run_count:
            mismatches["counts.new_runs"] = (
                counts.get("new_runs"),
                config.contract.new_run_count,
            )
    if (
        config.contract.reuse_run_count is not None
        and config.contract.new_run_count is not None
    ):
        expected_runs_by_mode = {
            REUSE_SOURCE_MODE: config.contract.reuse_run_count,
            NEW_SOURCE_MODE: config.contract.new_run_count,
        }
        expected_poses_by_mode = {
            mode: count * config.contract.poses_per_run
            for mode, count in expected_runs_by_mode.items()
        }
        if audit.get("run_counts_by_source_mode") != expected_runs_by_mode:
            mismatches["run_counts_by_source_mode"] = (
                audit.get("run_counts_by_source_mode"),
                expected_runs_by_mode,
            )
        if audit.get("pose_counts_by_source_mode") != expected_poses_by_mode:
            mismatches["pose_counts_by_source_mode"] = (
                audit.get("pose_counts_by_source_mode"),
                expected_poses_by_mode,
            )
    if mismatches:
        raise ContractError(f"Selector audit contract mismatch: {mismatches}")
    publication = required_mapping(audit, "publication", "selector audit")
    release_ids = {row.get("publication_release_id", "") for row in rows}
    if len(release_ids) != 1 or "" in release_ids:
        raise ContractError("Selector rows do not bind one publication release")
    release_id = next(iter(release_ids))
    if publication.get("release_id") != release_id:
        raise ContractError("Selector audit publication release ID mismatch")
    inputs = required_mapping(audit, "inputs", "selector audit")
    audit_release = required_mapping(
        inputs, "execution_release_manifest", "selector audit inputs"
    )
    release_paths = {row.get("execution_release_manifest_relpath", "") for row in rows}
    release_hashes = {row.get("execution_release_manifest_sha256", "") for row in rows}
    if len(release_paths) != 1 or audit_release.get("relpath") not in release_paths:
        raise ContractError("Selector audit execution-release path mismatch")
    if len(release_hashes) != 1 or audit_release.get("sha256") not in release_hashes:
        raise ContractError("Selector audit execution-release hash mismatch")
    return audit


def verify_selector(
    config: BuildConfig,
    cases: Mapping[str, core.CaseMetadata],
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, Any]]:
    fields, rows = read_csv_strict(config.selector_csv.resolve())
    missing = sorted(SELECTOR_REQUIRED_FIELDS - set(fields))
    if missing:
        raise ContractError(f"Selector CSV lacks required fields: {missing}")
    if len(rows) != config.contract.pose_count:
        raise ContractError(
            f"Selector row count {len(rows)} != {config.contract.pose_count}"
        )

    selector_impl = config.selector_implementation.resolve()
    selector_impl_hash = sha256_file(selector_impl)
    file_bindings: dict[str, str] = {
        str(config.selector_csv.resolve()): sha256_file(config.selector_csv.resolve()),
        str(selector_impl): selector_impl_hash,
        str(config.positive_manifest.resolve()): sha256_file(
            config.positive_manifest.resolve()
        ),
        str(config.mutant_manifest.resolve()): sha256_file(
            config.mutant_manifest.resolve()
        ),
    }
    keys: set[tuple[str, str, int]] = set()
    run_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    selector_hashes: set[str] = set()
    selector_paths: set[str] = set()
    selector_helper_hashes: set[str] = set()
    selector_helper_paths: set[str] = set()
    publication_release_ids: set[str] = set()

    for row_number, row in enumerate(rows, start=2):
        expected_hash = row_sha256(row, "selection_row_sha256")
        if row.get("selection_row_sha256") != expected_hash:
            raise ContractError(f"Selector row hash mismatch at row {row_number}")
        if row.get("schema_version") != SELECTOR_SCHEMA:
            raise ContractError(f"Unexpected selector schema at row {row_number}")
        if row.get("protocol_id") != SELECTOR_PROTOCOL_ID:
            raise ContractError(f"Unexpected selector protocol at row {row_number}")
        if row.get("source_protocol") != POSE_SOURCE_PROTOCOL:
            raise ContractError(f"Unexpected pose source protocol at row {row_number}")
        if row.get("source_stage") != "4_emref":
            raise ContractError(f"Selector row is not from 4_emref at row {row_number}")
        for field_name in (
            "formal_eligible",
            "training_label_release_eligible",
            "docking_gold_release_eligible",
        ):
            if parse_bool(row.get(field_name), field_name):
                raise ContractError(f"Selector unexpectedly sets {field_name}=true")
        candidate_id = safe_component(row.get("candidate_id", ""), "candidate_id")
        if row.get("case_id") != candidate_id:
            raise ContractError(f"case_id/candidate_id mismatch at row {row_number}")
        case = cases.get(candidate_id)
        if case is None:
            raise ContractError(f"Unknown selector candidate: {candidate_id}")
        if row.get("family") != case.family:
            raise ContractError(f"Selector family mismatch for {candidate_id}")
        for field_name, expected_range in (
            ("cdr1_range", case.cdr1_range),
            ("cdr2_range", case.cdr2_range),
            ("cdr3_range", case.cdr3_range),
        ):
            if row.get(field_name) != expected_range:
                raise ContractError(f"Selector {field_name} mismatch for {candidate_id}")

        receptor = row.get("generation_receptor", "").upper()
        if receptor not in config.contract.receptors or receptor not in RECEPTORS:
            raise ContractError(f"Invalid generation_receptor at row {row_number}")
        if row.get("receptor_id", "").upper() != receptor:
            raise ContractError(f"receptor_id mismatch at row {row_number}")
        native_rank = parse_int(row.get("native_rank"), "native_rank", 1)
        canonical_rank = parse_int(row.get("canonical_rank"), "canonical_rank", 1)
        if native_rank != canonical_rank or native_rank > config.contract.poses_per_run:
            raise ContractError(f"Native/canonical rank mismatch at row {row_number}")
        key = (candidate_id, receptor, native_rank)
        if key in keys:
            raise ContractError(f"Duplicate selector key: {key}")
        keys.add(key)
        parse_int(row.get("source_output_index"), "source_output_index", 0)
        parse_int(row.get("source_seed"), "source_seed")
        parse_float(row.get("source_score"), "source_score")
        if row.get("vhh_chain_id") != "A" or row.get("pvrig_chain_id") != "B":
            raise ContractError(f"Pose chain contract mismatch for {key}")
        if not row.get("completion_status", "").strip() or parse_int(
            row.get("completion_exit_code"), "completion_exit_code"
        ) != 0:
            raise ContractError(f"Run completion contract failed for {key}")

        source_path = resolve_workspace_path(
            row.get("source_pose_relpath", ""), config.workspace_root
        )
        source_payload = source_path.read_bytes() if source_path.is_file() else b""
        if not source_payload:
            raise ContractError(f"Source pose is missing or empty: {source_path}")
        if sha256_bytes(source_payload) != row.get("source_pose_sha256"):
            raise ContractError(f"Source pose hash drift: {source_path}")
        if len(source_payload) != parse_int(
            row.get("source_pose_bytes"), "source_pose_bytes", 1
        ):
            raise ContractError(f"Source pose byte-count drift: {source_path}")
        if row.get("compressed_source_sha256") != row.get("source_pose_sha256"):
            raise ContractError(f"Compressed-source hash alias mismatch for {key}")
        if parse_int(row.get("compressed_source_bytes"), "compressed_source_bytes", 1) != len(
            source_payload
        ):
            raise ContractError(f"Compressed-source byte alias mismatch for {key}")
        expected_format = "pdb.gz" if source_path.name.endswith(".pdb.gz") else "pdb"
        if row.get("source_pose_format") != expected_format:
            raise ContractError(f"Source pose format mismatch for {key}")
        try:
            decompressed = (
                gzip.decompress(source_payload)
                if expected_format == "pdb.gz"
                else source_payload
            )
        except (OSError, EOFError) as error:
            raise ContractError(f"Source pose cannot be decompressed for {key}") from error

        coordinate_path = resolve_workspace_path(
            row.get("materialized_coordinate_relpath", ""), config.workspace_root
        )
        coordinate_payload = (
            coordinate_path.read_bytes() if coordinate_path.is_file() else b""
        )
        if not coordinate_payload:
            raise ContractError(f"Materialized coordinate is missing: {coordinate_path}")
        expected_coordinate_hash = row.get("decompressed_coordinate_sha256")
        if sha256_bytes(coordinate_payload) != expected_coordinate_hash:
            raise ContractError(f"Materialized coordinate hash drift: {coordinate_path}")
        if row.get("materialized_coordinate_sha256") != expected_coordinate_hash:
            raise ContractError(f"Coordinate hash alias mismatch for {key}")
        if decompressed != coordinate_payload:
            raise ContractError(f"Source/materialized coordinate bytes differ for {key}")
        coordinate_bytes = len(coordinate_payload)
        for field_name in (
            "decompressed_coordinate_bytes",
            "materialized_coordinate_bytes",
        ):
            if parse_int(row.get(field_name), field_name, 1) != coordinate_bytes:
                raise ContractError(f"Coordinate byte-count drift for {key}/{field_name}")
        try:
            coordinate_payload.decode("ascii")
        except UnicodeDecodeError as error:
            raise ContractError(f"Materialized coordinate is not ASCII PDB: {key}") from error

        for inventory_field, atom_field, residue_field, chain in (
            ("vhh_chain_inventory_json", "vhh_atom_count", "vhh_residue_count", "A"),
            ("pvrig_chain_inventory_json", "pvrig_atom_count", "pvrig_residue_count", "B"),
        ):
            inventory = parse_inventory_json(row, inventory_field)
            if inventory.get("chain") != chain:
                raise ContractError(f"Selector inventory chain mismatch in {inventory_field}")
            if inventory.get("selected_heavy_atom_count") != parse_int(
                row.get(atom_field), atom_field, 1
            ):
                raise ContractError(f"Selector inventory atom mismatch in {inventory_field}")
            if inventory.get("selected_residue_count") != parse_int(
                row.get(residue_field), residue_field, 1
            ):
                raise ContractError(
                    f"Selector inventory residue mismatch in {inventory_field}"
                )

        if row.get("selector_implementation_sha256") != selector_impl_hash:
            raise ContractError(f"Selector implementation hash mismatch at row {row_number}")
        expected_selector_path = canonical_input_path(selector_impl, config.workspace_root)
        if row.get("selector_implementation_relpath") != expected_selector_path:
            raise ContractError(f"Selector implementation path mismatch at row {row_number}")
        selector_hashes.add(row["selector_implementation_sha256"])
        selector_paths.add(row["selector_implementation_relpath"])
        selector_helper = resolve_workspace_path(
            row.get("selector_helper_relpath", ""), config.workspace_root
        )
        selector_helper_hash = sha256_file(selector_helper)
        if selector_helper_hash != row.get("selector_helper_sha256"):
            raise ContractError(f"Selector helper hash mismatch at row {row_number}")
        selector_helper_hashes.add(selector_helper_hash)
        selector_helper_paths.add(row["selector_helper_relpath"])
        publication_release_ids.add(
            safe_component(row.get("publication_release_id", ""), "publication_release_id")
        )
        execution_release = resolve_workspace_path(
            row.get("execution_release_manifest_relpath", ""), config.workspace_root
        )
        execution_release_hash = sha256_file(execution_release)
        if execution_release_hash != row.get("execution_release_manifest_sha256"):
            raise ContractError(f"Execution release manifest hash mismatch for {key}")
        teacher_manifest = resolve_workspace_path(
            row.get("teacher_manifest_relpath", ""), config.workspace_root
        )
        teacher_manifest_hash = sha256_file(teacher_manifest)
        if teacher_manifest_hash != row.get("teacher_manifest_sha256"):
            raise ContractError(f"Teacher manifest hash mismatch for {key}")
        for field_name in ("teacher_manifest_row_sha256", "run_manifest_row_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", row.get(field_name, "")):
                raise ContractError(f"Invalid {field_name} for {key}")
        if row.get("remote_file_hash_chain") != row.get("local_file_hash_chain"):
            raise ContractError(f"Remote/local hash chain mismatch for {key}")
        for path, digest in (
            (source_path, row["source_pose_sha256"]),
            (coordinate_path, row["materialized_coordinate_sha256"]),
            (selector_helper, selector_helper_hash),
            (execution_release, execution_release_hash),
            (teacher_manifest, teacher_manifest_hash),
        ):
            previous = file_bindings.setdefault(str(path), digest)
            if previous != digest:
                raise ContractError(f"Conflicting selector hash bindings for {path}")
        grouped[(candidate_id, receptor)].append(row)
        run_ids[(candidate_id, receptor)].add(row.get("source_run_id", ""))

    expected_group_keys = {
        (candidate_id, receptor)
        for candidate_id in cases
        for receptor in config.contract.receptors
    }
    if set(grouped) != expected_group_keys:
        raise ContractError(
            "Selector candidate/receptor closure mismatch: "
            f"missing={sorted(expected_group_keys - set(grouped))[:10]}; "
            f"extra={sorted(set(grouped) - expected_group_keys)[:10]}"
        )
    expected_ranks = set(range(1, config.contract.poses_per_run + 1))
    for group_key, group_rows in grouped.items():
        ranks = {int(row["native_rank"]) for row in group_rows}
        if len(group_rows) != config.contract.poses_per_run or ranks != expected_ranks:
            raise ContractError(f"Fixed native Top-8 contract failed for {group_key}")
        if len(run_ids[group_key]) != 1 or "" in run_ids[group_key]:
            raise ContractError(f"Run identity is not unique for {group_key}")
    for candidate_id in cases:
        candidate_rows = [row for row in rows if row["candidate_id"] == candidate_id]
        for field_name in (
            "sequence_sha256",
            "monomer_sha256",
            "monomer_atom_identity_sha256",
            "monomer_residue_identity_sha256",
            "pose_vhh_atom_identity_sha256",
            "pose_vhh_residue_identity_sha256",
        ):
            values = {row.get(field_name, "") for row in candidate_rows}
            if len(values) != 1 or "" in values:
                raise ContractError(
                    f"Cross-receptor frozen monomer closure failed for "
                    f"{candidate_id}/{field_name}"
                )
    if len(selector_hashes) != 1 or len(selector_paths) != 1:
        raise ContractError("Selector rows do not bind one implementation")
    if len(selector_helper_hashes) != 1 or len(selector_helper_paths) != 1:
        raise ContractError("Selector rows do not bind one helper implementation")
    if len(publication_release_ids) != 1:
        raise ContractError("Selector rows span multiple publication releases")

    ordered = sorted(
        rows,
        key=lambda row: (
            row["candidate_id"],
            row["generation_receptor"],
            int(row["native_rank"]),
        ),
    )
    audit_validated = False
    if config.selector_audit is not None:
        audit_path = config.selector_audit.resolve()
        verify_selector_audit(audit_path, config.selector_csv.resolve(), rows, config)
        file_bindings[str(audit_path)] = sha256_file(audit_path)
        audit_validated = True
    return ordered, file_bindings, {
        "selector_csv_sha256": sha256_file(config.selector_csv.resolve()),
        "selector_implementation_relpath": next(iter(selector_paths)),
        "selector_implementation_sha256": next(iter(selector_hashes)),
        "selector_helper_relpath": next(iter(selector_helper_paths)),
        "selector_helper_sha256": next(iter(selector_helper_hashes)),
        "publication_release_id": next(iter(publication_release_ids)),
        "selector_audit_validated": audit_validated,
        "selection_row_hash_chain": sha256_bytes(
            "\n".join(row["selection_row_sha256"] for row in rows).encode("ascii")
        ),
        "processing_order_row_hash_chain": sha256_bytes(
            "\n".join(row["selection_row_sha256"] for row in ordered).encode("ascii")
        ),
    }


def build_native_alignment_pair_rows(
    hotspots: Path, receptor: str
) -> list[dict[str, str]]:
    _fields, rows = read_csv_strict(hotspots)
    column = str(RECEPTORS[receptor]["hotspot_ref_column"])
    reference_chain = str(RECEPTORS[receptor]["reference_pvrig_chain"])
    output: list[dict[str, str]] = []
    for row in rows:
        if row.get("hotspot_class") not in {"core_hotspot", "secondary_hotspot"}:
            continue
        parsed = core.parse_pdb_residue_ref(row.get(column, ""))
        if parsed is None or parsed[0] != reference_chain:
            raise ContractError(
                f"Malformed native hotspot mapping {receptor}/{row.get('hotspot_id', '')}"
            )
        suffix = parsed[2]
        output.append(
            {
                "mobile_ref": f"B:{parsed[1]}{suffix}",
                "reference_ref": f"{reference_chain}:{parsed[1]}{suffix}",
            }
        )
    if len(output) != 23:
        raise ContractError(f"Expected 23 native hotspot pairs for {receptor}, got {len(output)}")
    if len({row["mobile_ref"] for row in output}) != 23:
        raise ContractError(f"Duplicate native mobile refs for {receptor}")
    if len({row["reference_ref"] for row in output}) != 23:
        raise ContractError(f"Duplicate native reference refs for {receptor}")
    return output


def validate_native_hotspot_reconciliation(hotspots: Path, reconciliation: Path) -> None:
    try:
        mapping = core.parse_reconciliation(reconciliation)
    except core.ContractError as error:
        raise ContractError(str(error)) from error
    hotspot_fields, hotspot_rows = read_csv_strict(hotspots)
    if not {"uniprot_position", "pdb_8x6b_ref", "pdb_9e6y_ref"}.issubset(
        hotspot_fields
    ):
        raise ContractError("Hotspot CSV lacks canonical reconciliation fields")
    for row in hotspot_rows:
        if row.get("hotspot_class") not in {"core_hotspot", "secondary_hotspot"}:
            continue
        uniprot = parse_int(row.get("uniprot_position"), "uniprot_position")
        for receptor in RECEPTORS:
            parsed = core.parse_pdb_residue_ref(
                row.get(RECEPTORS[receptor]["hotspot_ref_column"], "")
            )
            observed = mapping[receptor].get(uniprot)
            if parsed is None or observed is None:
                raise ContractError(f"Missing hotspot reconciliation for {receptor}/{uniprot}")
            if (parsed[0], parsed[1]) != (observed[0], observed[1]):
                raise ContractError(
                    f"Hotspot/reconciliation mismatch for {receptor}/{uniprot}: "
                    f"{parsed} vs {observed}"
                )


def materialize_native_alignment_maps(
    config: BuildConfig, staging_root: Path
) -> dict[str, dict[str, Any]]:
    maps: dict[str, dict[str, Any]] = {}
    for receptor in config.contract.receptors:
        rows = build_native_alignment_pair_rows(config.hotspots.resolve(), receptor)
        relative = Path("alignment_maps") / f"{receptor.lower()}_native_hotspot23.csv"
        path = staging_root / relative
        write_csv(path, rows, ("mobile_ref", "reference_ref"))
        maps[receptor] = {
            "path": path,
            "relpath": relative.as_posix(),
            "sha256": sha256_file(path),
            "pair_count": len(rows),
        }
    return maps


def run_command(command: Sequence[Any], *, cwd: Path, label: str) -> str:
    environment = os.environ.copy()
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    completed = subprocess.run(
        list(map(str, command)),
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ContractError(
            f"{label} failed with exit {completed.returncode}: "
            f"{completed.stdout.strip()[-3000:]}"
        )
    return completed.stdout


def run_json_tool(
    command: Sequence[Any], output: Path, *, cwd: Path, label: str
) -> dict[str, Any]:
    run_command(command, cwd=cwd, label=label)
    if not output.is_file():
        raise ContractError(f"{label} did not create JSON output: {output}")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"{label} produced invalid JSON") from error
    if not isinstance(payload, dict):
        raise ContractError(f"{label} output is not an object")
    assert_finite_tree(payload, label)
    return payload


def parse_alignment_evidence(output: str, context: str) -> core.AlignmentEvidence:
    try:
        return core.parse_alignment_evidence(output, context)
    except core.ContractError as error:
        raise ContractError(str(error)) from error


def assert_inventory_agreement(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    fields: Sequence[str],
    context: str,
) -> None:
    mismatches = {
        field_name: (left.get(field_name), right.get(field_name))
        for field_name in fields
        if left.get(field_name) != right.get(field_name)
    }
    if mismatches:
        raise ContractError(f"Inventory mismatch for {context}: {mismatches}")


def assert_expected_reference_inventory(
    inventory: Mapping[str, Any], expected: Mapping[str, Any], context: str
) -> None:
    selection_rule = str(inventory.get("selection_rule", ""))
    if "protein ATOM" not in selection_rule or "all HETATM excluded" not in selection_rule:
        raise ContractError(f"Reference inventory is not ATOM-only for {context}")
    mismatches = {
        key: (inventory.get(key), value)
        for key, value in expected.items()
        if inventory.get(key) != value
    }
    if mismatches:
        raise ContractError(f"Reference inventory mismatch for {context}: {mismatches}")


def validate_nullable_region_min_distances(
    region_report: Mapping[str, Any], context: str
) -> None:
    try:
        core.validate_nullable_region_min_distances(region_report, context)
    except core.ContractError as error:
        raise ContractError(str(error)) from error


def validate_native_reports(
    selector_row: Mapping[str, str],
    receptor: str,
    raw_report: Mapping[str, Any],
    region_report: Mapping[str, Any],
    expected_reference_inventory: Mapping[str, Any],
) -> None:
    if raw_report.get("schema_version") != "pvrig_vhh_pose_score_v1_2":
        raise ContractError(f"Unexpected raw pose scorer schema for {receptor}")
    if region_report.get("schema_version") != "cdr_region_occlusion_score_v1_2":
        raise ContractError(f"Unexpected region scorer schema for {receptor}")
    for label, report in (("raw", raw_report), ("region", region_report)):
        if report.get("scoring_semantics_version") != SCORING_SEMANTICS_VERSION:
            raise ContractError(f"Unexpected scorer semantics for {receptor}/{label}")
        policy = str(report.get("reference_pvrl2_selection", ""))
        if "ATOM" not in policy or "only" not in policy.lower():
            raise ContractError(f"{receptor}/{label} lacks ATOM-only policy")
    expected_column = RECEPTORS[receptor]["hotspot_ref_column"]
    if raw_report.get("hotspot_ref_column") != expected_column:
        raise ContractError(f"Wrong native hotspot column for {receptor}")
    if parse_int(raw_report.get("hotspot_count"), "hotspot_count") != 23:
        raise ContractError(f"Native hotspot_count != 23 for {receptor}")
    validate_nullable_region_min_distances(region_report, receptor)

    raw_inventory_root = required_mapping(raw_report, "record_inventory", "raw report")
    raw_pose = required_mapping(raw_inventory_root, "pose", "raw report inventory")
    raw_pvrig = required_mapping(raw_pose, "pvrig_chain", "raw report inventory")
    raw_vhh = required_mapping(raw_pose, "vhh_chain", "raw report inventory")
    raw_reference = required_mapping(
        raw_inventory_root, "reference_pvrl2_chain", "raw report inventory"
    )
    region_inventory_root = required_mapping(
        region_report, "record_inventory", "region report"
    )
    region_pose = required_mapping(region_inventory_root, "pose", "region inventory")
    region_vhh = required_mapping(region_pose, "vhh_chain", "region inventory")
    region_reference = required_mapping(
        region_inventory_root, "reference_pvrl2_chain", "region inventory"
    )
    assert_inventory_agreement(
        parse_inventory_json(selector_row, "pvrig_chain_inventory_json"),
        raw_pvrig,
        core.INVENTORY_AGREEMENT_FIELDS,
        f"selector/raw PVRIG {receptor}",
    )
    assert_inventory_agreement(
        parse_inventory_json(selector_row, "vhh_chain_inventory_json"),
        raw_vhh,
        core.INVENTORY_AGREEMENT_FIELDS,
        f"selector/raw VHH {receptor}",
    )
    assert_inventory_agreement(
        raw_vhh,
        region_vhh,
        core.INVENTORY_AGREEMENT_FIELDS,
        f"raw/region VHH {receptor}",
    )
    assert_inventory_agreement(
        raw_reference,
        region_reference,
        core.REFERENCE_AGREEMENT_FIELDS,
        f"raw/region reference {receptor}",
    )
    assert_expected_reference_inventory(
        raw_reference, expected_reference_inventory, f"raw {receptor}"
    )
    assert_expected_reference_inventory(
        region_reference, expected_reference_inventory, f"region {receptor}"
    )
    for field_name in (*INTERNAL_CONTACT_METRICS, *INTERNAL_CONTACT_LIST_FIELDS):
        if field_name not in raw_report:
            raise ContractError(f"Raw scorer omitted {field_name}")


def score_raw_native_internal(
    *,
    config: BuildConfig,
    selector_row: Mapping[str, str],
    case: core.CaseMetadata,
    receptor: str,
    raw_pose: Path,
    work_root: Path,
) -> Mapping[str, Any]:
    spec = RECEPTORS[receptor]
    output = work_root / "raw_native_internal_score.json"
    report = run_json_tool(
        [
            sys.executable,
            config.pose_scorer,
            "--pose-pdb",
            raw_pose,
            "--reference-pdb",
            config.references[receptor],
            "--pvrig-chain",
            "B",
            "--vhh-chain",
            "A",
            "--ref-pvrig-chain",
            spec["reference_pvrig_chain"],
            "--ref-pvrl2-chain",
            spec["reference_pvrl2_chain"],
            "--hotspots-csv",
            config.hotspots,
            "--hotspot-ref-column",
            spec["hotspot_ref_column"],
            "--cdr-ranges",
            f"CDR1:{case.cdr1_range},CDR2:{case.cdr2_range},CDR3:{case.cdr3_range}",
            "--assume-aligned",
            "--out-json",
            output,
        ],
        output,
        cwd=config.workspace_root,
        label=(
            f"raw native internal scorer {selector_row['candidate_id']}/"
            f"{receptor}/rank{selector_row['native_rank']}"
        ),
    )
    return report


def align_and_score_native(
    *,
    config: BuildConfig,
    selector_row: Mapping[str, str],
    case: core.CaseMetadata,
    receptor: str,
    raw_pose: Path,
    staging_root: Path,
    work_root: Path,
    alignment_map: Mapping[str, Any],
) -> NativeResult:
    spec = RECEPTORS[receptor]
    rank = parse_int(selector_row["native_rank"], "native_rank", 1)
    candidate_id = selector_row["candidate_id"]
    relative = (
        Path("aligned_poses")
        / candidate_id
        / receptor
        / f"native_rank_{rank:02d}.pdb"
    )
    aligned_pose = staging_root / relative
    aligned_pose.parent.mkdir(parents=True, exist_ok=True)
    stdout = run_command(
        [
            sys.executable,
            config.aligner,
            "--mobile-pdb",
            raw_pose,
            "--reference-pdb",
            config.references[receptor],
            "--mobile-chain",
            "B",
            "--reference-chain",
            spec["reference_pvrig_chain"],
            "--pair-map-csv",
            alignment_map["path"],
            "--mobile-ref-column",
            "mobile_ref",
            "--reference-ref-column",
            "reference_ref",
            "--out-pdb",
            aligned_pose,
        ],
        cwd=config.workspace_root,
        label=f"native alignment {candidate_id}/{receptor}/rank{rank}",
    )
    alignment = parse_alignment_evidence(
        stdout, f"{candidate_id}/{receptor}/rank{rank}"
    )
    if not aligned_pose.is_file() or not aligned_pose.stat().st_size:
        raise ContractError(f"Aligned pose was not materialized: {aligned_pose}")

    raw_report = score_raw_native_internal(
        config=config,
        selector_row=selector_row,
        case=case,
        receptor=receptor,
        raw_pose=raw_pose,
        work_root=work_root,
    )
    region_json = work_root / "native_region_score.json"
    region_report = run_json_tool(
        [
            sys.executable,
            config.region_scorer,
            "--pose-pdb",
            aligned_pose,
            "--reference-pdb",
            config.references[receptor],
            "--vhh-chain",
            "A",
            "--ref-pvrl2-chain",
            spec["reference_pvrl2_chain"],
            "--cdr1",
            case.cdr1_range,
            "--cdr2",
            case.cdr2_range,
            "--cdr3",
            case.cdr3_range,
            "--out-json",
            region_json,
        ],
        region_json,
        cwd=config.workspace_root,
        label=f"native region scorer {candidate_id}/{receptor}/rank{rank}",
    )
    validate_native_reports(
        selector_row,
        receptor,
        raw_report,
        region_report,
        config.expected_reference_inventories[receptor],
    )
    return NativeResult(
        receptor=receptor,
        aligned_pose_relpath=relative.as_posix(),
        aligned_pose_sha256=sha256_file(aligned_pose),
        aligned_pose_bytes=aligned_pose.stat().st_size,
        alignment_map_relpath=str(alignment_map["relpath"]),
        alignment_map_sha256=str(alignment_map["sha256"]),
        alignment=alignment,
        raw_report=raw_report,
        region_report=region_report,
    )


def normalized_raw_payload_sha256(
    report: Mapping[str, Any], selector_row: Mapping[str, str], receptor: str
) -> str:
    inventory = required_mapping(report, "record_inventory", "raw report")
    return sha256_json(
        {
            "schema_version": "pvrig_v1_3_raw_native_internal_effective_payload_v1",
            "scorer_schema_version": report.get("schema_version"),
            "scoring_semantics_version": report.get("scoring_semantics_version"),
            "generation_receptor": receptor,
            "source_coordinate_sha256": selector_row[
                "materialized_coordinate_sha256"
            ],
            "hotspot_ref_column": RECEPTORS[receptor]["hotspot_ref_column"],
            "pose_record_inventory": required_mapping(
                inventory, "pose", "raw report inventory"
            ),
            "effective_scalars": {
                field_name: report[field_name]
                for field_name in INTERNAL_CONTACT_METRICS
            },
            "effective_lists": {
                field_name: report[field_name]
                for field_name in INTERNAL_CONTACT_LIST_FIELDS
            },
        }
    )


def normalized_region_payload_sha256(
    report: Mapping[str, Any], result: NativeResult, config: BuildConfig
) -> str:
    normalized = dict(report)
    if "pose_pdb" in normalized:
        normalized["pose_pdb"] = result.aligned_pose_relpath
    if "reference_pdb" in normalized:
        normalized["reference_pdb"] = canonical_input_path(
            config.references[result.receptor], config.workspace_root
        )
    return sha256_json(normalized)


def flatten_metrics_row(
    selector_row: Mapping[str, str],
    case: core.CaseMetadata,
    result: NativeResult,
    config: BuildConfig,
) -> dict[str, str]:
    raw = result.raw_report
    region = result.region_report
    raw_inventory_root = required_mapping(raw, "record_inventory", "raw report")
    raw_pose = required_mapping(raw_inventory_root, "pose", "raw inventory")
    raw_pvrig = required_mapping(raw_pose, "pvrig_chain", "raw inventory")
    raw_vhh = required_mapping(raw_pose, "vhh_chain", "raw inventory")
    raw_reference = required_mapping(
        raw_inventory_root, "reference_pvrl2_chain", "raw inventory"
    )
    region_inventory_root = required_mapping(
        region, "record_inventory", "region report"
    )
    region_pose = required_mapping(region_inventory_root, "pose", "region inventory")
    region_vhh = required_mapping(region_pose, "vhh_chain", "region inventory")
    region_reference = required_mapping(
        region_inventory_root, "reference_pvrl2_chain", "region inventory"
    )
    regions = required_mapping(region, "regions", "region report")

    total_pairs = parse_int(
        region.get("total_occluding_residue_pair_count"),
        "total_occluding_residue_pair_count",
        0,
    )
    cdr_counts = {
        name: parse_int(
            required_mapping(regions, name, f"region {name}").get(
                "occluding_residue_pair_count"
            ),
            f"{name}.occluding_residue_pair_count",
            0,
        )
        for name in ("CDR1", "CDR2", "CDR3")
    }
    cdr_total = sum(cdr_counts.values())
    if cdr_total > total_pairs:
        raise ContractError("CDR residue-pair total exceeds native total O")
    cdr_fraction = cdr_total / total_pairs if total_pairs else 0.0

    reference = config.references[result.receptor].resolve()
    row: dict[str, Any] = {
        "schema_version": "pvrig_v1_3_native_top8_continuous_metrics_v1",
        "protocol_id": PROTOCOL_ID,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "primary_native_metric_eligible": True,
        "native_only": True,
        "run_id": selector_row["run_id"],
        "source_mode": selector_row["source_mode"],
        "candidate_id": selector_row["candidate_id"],
        "family": case.family,
        "evidence_role": case.evidence_role,
        "control_descriptor": case.control_descriptor,
        "usage_boundary": case.usage_boundary,
        "generation_receptor": result.receptor,
        "native_rank": selector_row["native_rank"],
        "source_output_index": selector_row["source_output_index"],
        "source_score": selector_row["source_score"],
        "source_seed": selector_row["source_seed"],
        "selector_row_sha256": selector_row["selection_row_sha256"],
        "aligned_pose_relpath": result.aligned_pose_relpath,
        "aligned_pose_sha256": result.aligned_pose_sha256,
        "alignment_pair_count": result.alignment.pair_count,
        "alignment_rmsd_a": result.alignment.rmsd_a,
        "alignment_map_relpath": result.alignment_map_relpath,
        "alignment_map_sha256": result.alignment_map_sha256,
        "reference_relpath": canonical_input_path(reference, config.workspace_root),
        "reference_sha256": sha256_file(reference),
        "native_hotspot_ref_column": RECEPTORS[result.receptor][
            "hotspot_ref_column"
        ],
        "cdr1_range": case.cdr1_range,
        "cdr2_range": case.cdr2_range,
        "cdr3_range": case.cdr3_range,
        "pose_score_schema_version": raw["schema_version"],
        "region_score_schema_version": region["schema_version"],
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "internal_contact_channel": (
            f"raw_4_emref_pose_{result.receptor.lower()}_native_numbering"
        ),
    }
    for field_name in INTERNAL_CONTACT_METRICS:
        row[field_name] = raw[field_name]
    for field_name in REGION_TOTAL_METRICS:
        if field_name not in region:
            raise ContractError(f"Region scorer omitted {field_name}")
        row[field_name] = region[field_name]
    for region_name in REGIONS:
        values = required_mapping(regions, region_name, f"region {region_name}")
        for field_name in REGION_ITEM_METRICS:
            if field_name not in values:
                raise ContractError(f"Region scorer omitted {region_name}.{field_name}")
            row[f"{region_name.lower()}_{field_name}"] = values[field_name]
    row.update(
        {
            "total_occluding_residue_pair_count": total_pairs,
            "cdr1_occluding_residue_pair_count": cdr_counts["CDR1"],
            "cdr2_occluding_residue_pair_count": cdr_counts["CDR2"],
            "cdr3_occluding_residue_pair_count": cdr_counts["CDR3"],
            "cdr123_occluding_residue_pair_count": cdr_total,
            "cdr123_occlusion_fraction": cdr_fraction,
            "pose_pvrig_record_inventory_json": canonical_json(raw_pvrig),
            "pose_vhh_record_inventory_json": canonical_json(raw_vhh),
            "region_pose_vhh_record_inventory_json": canonical_json(region_vhh),
            "reference_pvrl2_record_inventory_json": canonical_json(raw_reference),
            "region_reference_pvrl2_record_inventory_json": canonical_json(
                region_reference
            ),
            "raw_native_internal_score_payload_sha256": normalized_raw_payload_sha256(
                raw, selector_row, result.receptor
            ),
            "region_score_payload_sha256": normalized_region_payload_sha256(
                region, result, config
            ),
        }
    )
    normalized = {
        field_name: scalar_text(row.get(field_name), field_name)
        for field_name in METRICS_FIELDS
        if field_name != "metrics_row_sha256"
    }
    normalized["metrics_row_sha256"] = row_sha256(
        normalized, "metrics_row_sha256"
    )
    assert_no_forbidden_output_fields(normalized, "native metrics row")
    return normalized


def contact_record(
    selector_row: Mapping[str, str], result: NativeResult, config: BuildConfig
) -> dict[str, Any]:
    regions = required_mapping(result.region_report, "regions", "region report")
    record: dict[str, Any] = {
        "schema_version": "pvrig_v1_3_native_top8_residue_contacts_v1",
        "protocol_id": PROTOCOL_ID,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "primary_native_metric_eligible": True,
        "native_only": True,
        "claim_boundary": CLAIM_BOUNDARY,
        "run_id": selector_row["run_id"],
        "candidate_id": selector_row["candidate_id"],
        "generation_receptor": result.receptor,
        "native_rank": int(selector_row["native_rank"]),
        "selector_row_sha256": selector_row["selection_row_sha256"],
        "aligned_pose_sha256": result.aligned_pose_sha256,
        "native_hotspot_ref_column": RECEPTORS[result.receptor][
            "hotspot_ref_column"
        ],
        "raw_native_internal_score_payload_sha256": normalized_raw_payload_sha256(
            result.raw_report, selector_row, result.receptor
        ),
        "region_score_payload_sha256": normalized_region_payload_sha256(
            result.region_report,
            result,
            config,
        ),
        "pvrig_vhh_contacts": result.raw_report.get("pvrig_vhh_contacts", []),
        "hotspot_overlaps": result.raw_report.get("hotspot_overlaps", []),
        "region_residue_pairs": {
            region: {
                "occluding_residue_pairs": required_mapping(
                    regions, region, f"region {region}"
                ).get("occluding_residue_pairs", []),
                "clash_residue_pairs": required_mapping(
                    regions, region, f"region {region}"
                ).get("clash_residue_pairs", []),
            }
            for region in REGIONS
        },
    }
    assert_finite_tree(record, "native contact record")
    assert_no_forbidden_output_fields(record, "native contact record")
    record["contact_record_sha256"] = sha256_json(record)
    return record


def process_selector_row(
    index: int,
    selector_row: Mapping[str, str],
    *,
    config: BuildConfig,
    cases: Mapping[str, core.CaseMetadata],
    staging_root: Path,
    alignment_maps: Mapping[str, Mapping[str, Any]],
) -> tuple[int, dict[str, str], dict[str, str], dict[str, Any]]:
    candidate_id = selector_row["candidate_id"]
    receptor = selector_row["generation_receptor"]
    rank = parse_int(selector_row["native_rank"], "native_rank", 1)
    case = cases[candidate_id]
    coordinate_path = resolve_workspace_path(
        selector_row["materialized_coordinate_relpath"], config.workspace_root
    )
    coordinates = coordinate_path.read_bytes()
    if sha256_bytes(coordinates) != selector_row["materialized_coordinate_sha256"]:
        raise ContractError(f"Coordinate hash drift before processing {candidate_id}/{receptor}/{rank}")
    work_root = staging_root / ".work" / f"{index:04d}_{candidate_id}_{receptor}_{rank:02d}"
    work_root.mkdir(parents=True, exist_ok=True)
    raw_pose = work_root / "raw_native_emref_pose.pdb"
    raw_pose.write_bytes(coordinates)
    result = align_and_score_native(
        config=config,
        selector_row=selector_row,
        case=case,
        receptor=receptor,
        raw_pose=raw_pose,
        staging_root=staging_root,
        work_root=work_root,
        alignment_map=alignment_maps[receptor],
    )
    reference = config.references[receptor].resolve()
    material: dict[str, Any] = {
        "schema_version": "pvrig_v1_3_native_top8_pose_materialization_v1",
        "protocol_id": PROTOCOL_ID,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "primary_native_metric_eligible": True,
        "native_only": True,
        "run_id": selector_row["run_id"],
        "source_mode": selector_row["source_mode"],
        "candidate_id": candidate_id,
        "family": case.family,
        "evidence_role": case.evidence_role,
        "control_descriptor": case.control_descriptor,
        "usage_boundary": case.usage_boundary,
        "generation_receptor": receptor,
        "native_rank": selector_row["native_rank"],
        "source_output_index": selector_row["source_output_index"],
        "source_score": selector_row["source_score"],
        "source_seed": selector_row["source_seed"],
        "selector_row_sha256": selector_row["selection_row_sha256"],
        "source_pose_relpath": selector_row["source_pose_relpath"],
        "source_pose_sha256": selector_row["source_pose_sha256"],
        "source_pose_bytes": selector_row["source_pose_bytes"],
        "materialized_coordinate_relpath": selector_row[
            "materialized_coordinate_relpath"
        ],
        "materialized_coordinate_sha256": selector_row[
            "materialized_coordinate_sha256"
        ],
        "materialized_coordinate_bytes": selector_row[
            "materialized_coordinate_bytes"
        ],
        "cdr1_range": case.cdr1_range,
        "cdr2_range": case.cdr2_range,
        "cdr3_range": case.cdr3_range,
        "alignment_map_relpath": result.alignment_map_relpath,
        "alignment_map_sha256": result.alignment_map_sha256,
        "alignment_pair_count": result.alignment.pair_count,
        "alignment_rmsd_a": result.alignment.rmsd_a,
        "aligned_pose_relpath": result.aligned_pose_relpath,
        "aligned_pose_sha256": result.aligned_pose_sha256,
        "aligned_pose_bytes": result.aligned_pose_bytes,
        "reference_relpath": canonical_input_path(reference, config.workspace_root),
        "reference_sha256": sha256_file(reference),
    }
    normalized_material = {
        field_name: scalar_text(material.get(field_name), field_name)
        for field_name in MATERIALIZATION_FIELDS
        if field_name != "materialization_row_sha256"
    }
    normalized_material["materialization_row_sha256"] = row_sha256(
        normalized_material, "materialization_row_sha256"
    )
    metric = flatten_metrics_row(selector_row, case, result, config)
    contact = contact_record(selector_row, result, config)
    # Replace the contact's normalized region hash with the same effective hash
    # already frozen in the metric row.
    contact["region_score_payload_sha256"] = metric["region_score_payload_sha256"]
    contact["contact_record_sha256"] = sha256_json(
        {key: value for key, value in contact.items() if key != "contact_record_sha256"}
    )
    shutil.rmtree(work_root)
    return index, normalized_material, metric, contact


def validate_toolchain(config: BuildConfig) -> dict[str, dict[str, str]]:
    expected_names = {
        "aligner": "align_pdb_by_chain.py",
        "pose_scorer": "score_pvrig_vhh_pose_v1_2.py",
        "region_scorer": "score_cdr_region_occlusion_v1_2.py",
        "scoring_helper": "pvrig_scoring_semantics_v1_2.py",
    }
    paths = {
        "processor": Path(__file__).resolve(),
        "processor_test": DEFAULT_PROCESSOR_TEST.resolve(),
        "aligner": config.aligner.resolve(),
        "pose_scorer": config.pose_scorer.resolve(),
        "region_scorer": config.region_scorer.resolve(),
        "scoring_helper": config.scoring_helper.resolve(),
    }
    for name, expected_name in expected_names.items():
        if paths[name].name != expected_name:
            raise ContractError(f"Refusing non-versioned {name}: {paths[name]}")
    return {
        name: {
            "path": canonical_input_path(path, config.workspace_root),
            "sha256": sha256_file(path),
        }
        for name, path in paths.items()
    }


def current_release_component(
    config: BuildConfig, selector_evidence: Mapping[str, Any]
) -> dict[str, Any]:
    selector_helper = resolve_workspace_path(
        str(selector_evidence.get("selector_helper_relpath", "")),
        config.workspace_root,
    )
    paths = {
        "processor": Path(__file__).resolve(),
        "processor_test": DEFAULT_PROCESSOR_TEST.resolve(),
        "selector_implementation": config.selector_implementation.resolve(),
        "selector_helper": selector_helper,
        "selector_csv": config.selector_csv.resolve(),
        "selector_audit": config.selector_audit.resolve() if config.selector_audit else None,
        "preregistration": config.preregistration.resolve(),
        "positive_manifest": config.positive_manifest.resolve(),
        "mutant_manifest": config.mutant_manifest.resolve(),
        "aligner": config.aligner.resolve(),
        "pose_scorer": config.pose_scorer.resolve(),
        "region_scorer": config.region_scorer.resolve(),
        "scoring_helper": config.scoring_helper.resolve(),
        "hotspots": config.hotspots.resolve(),
        "reconciliation": config.reconciliation.resolve(),
        **{
            f"reference_{receptor.lower()}": path.resolve()
            for receptor, path in config.references.items()
        },
    }
    artifacts = {
        name: {
            "path": canonical_input_path(path, config.workspace_root),
            "sha256": sha256_file(path),
        }
        for name, path in paths.items()
        if path is not None
    }
    if artifacts["selector_implementation"]["sha256"] != selector_evidence.get(
        "selector_implementation_sha256"
    ):
        raise ContractError("Selector evidence changed before release binding")
    if artifacts["selector_helper"]["sha256"] != selector_evidence.get(
        "selector_helper_sha256"
    ):
        raise ContractError("Selector helper changed before release binding")
    return {
        "schema_version": "pvrig_v1_3_native_processor_release_component_v1",
        "protocol_id": PROTOCOL_ID,
        "artifacts": artifacts,
    }


def validate_release_manifest(
    path: Path, expected_component: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": path.resolve().as_posix(),
        "exists": path.is_file(),
        "sha256": "",
        "component_found": False,
        "component_matches": False,
        "validated": False,
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append("development_release_manifest_missing")
        return result
    result["sha256"] = sha256_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["errors"].append("development_release_manifest_invalid_json")
        return result
    component = payload.get("native_processor_release") if isinstance(payload, dict) else None
    result["component_found"] = isinstance(component, dict)
    result["component_matches"] = component == expected_component
    result["validated"] = bool(result["component_found"] and result["component_matches"])
    if not result["component_found"]:
        result["errors"].append("native_processor_release_component_missing")
    elif not result["component_matches"]:
        result["errors"].append("native_processor_release_component_mismatch")
    return result


def verify_frozen_files(bindings: Mapping[str, str]) -> None:
    drift: list[str] = []
    for raw_path, expected in sorted(bindings.items()):
        path = Path(raw_path)
        try:
            observed = sha256_file(path)
        except ContractError as error:
            drift.append(str(error))
            continue
        if observed != expected:
            drift.append(f"{path}:{observed}!={expected}")
    if drift:
        raise ContractError("Frozen input hash drift: " + "; ".join(drift))


def hash_chain(rows: Iterable[Mapping[str, str]], field_name: str) -> str:
    return sha256_bytes("\n".join(row[field_name] for row in rows).encode("ascii"))


def validate_native_key_closure(
    rows: Sequence[Mapping[str, str]], contract: DatasetContract
) -> Counter[str]:
    if len(rows) != contract.pose_count:
        raise ContractError(f"Native row count {len(rows)} != {contract.pose_count}")
    keys = Counter(
        (row["candidate_id"], row["generation_receptor"], row["native_rank"])
        for row in rows
    )
    bad_keys = [key for key, count in keys.items() if count != 1]
    if bad_keys:
        raise ContractError(f"Missing or duplicate native metric keys: {bad_keys[:10]}")
    candidates = {row["candidate_id"] for row in rows}
    if len(candidates) != contract.case_count:
        raise ContractError(
            f"Native candidate count {len(candidates)} != {contract.case_count}"
        )
    grouped: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in rows:
        receptor = row["generation_receptor"]
        if receptor not in contract.receptors:
            raise ContractError(f"Unexpected native receptor: {receptor}")
        grouped[(row["candidate_id"], receptor)].add(
            parse_int(row["native_rank"], "native_rank", 1)
        )
    expected_groups = {
        (candidate, receptor)
        for candidate in candidates
        for receptor in contract.receptors
    }
    expected_ranks = set(range(1, contract.poses_per_run + 1))
    if set(grouped) != expected_groups:
        raise ContractError("Native candidate/receptor group closure failed")
    for group_key, ranks in grouped.items():
        if ranks != expected_ranks:
            raise ContractError(f"Native rank closure failed for {group_key}: {ranks}")
    rows_by_receptor = Counter(row["generation_receptor"] for row in rows)
    expected_per_receptor = contract.case_count * contract.poses_per_run
    if rows_by_receptor != Counter(
        {receptor: expected_per_receptor for receptor in contract.receptors}
    ):
        raise ContractError(f"Per-receptor metric closure failed: {rows_by_receptor}")
    return rows_by_receptor


def package_file_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContractError(f"Generated package cannot contain symlinks: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = sha256_file(path)
    return files


def publish_stage(staging_root: Path, outdir: Path) -> None:
    if not (staging_root / AUDIT_NAME).is_file():
        raise ContractError("Staging package lacks final audit marker")
    shutil.rmtree(staging_root / ".work", ignore_errors=True)
    expected = package_file_hashes(staging_root)
    outdir.parent.mkdir(parents=True, exist_ok=True)
    if outdir.exists() and not outdir.is_dir():
        raise ContractError(f"Output path is not a directory: {outdir}")
    backup = Path(tempfile.mkdtemp(prefix=f".{outdir.name}.previous.", dir=outdir.parent))
    backup.rmdir()
    had_previous = outdir.exists()
    installed = False
    try:
        if had_previous:
            os.replace(outdir, backup)
        os.replace(staging_root, outdir)
        installed = True
        if package_file_hashes(outdir) != expected:
            raise ContractError("Post-publish package hash set differs from staging")
    except Exception:
        if installed and outdir.exists():
            shutil.rmtree(outdir)
        if had_previous and backup.exists():
            os.replace(backup, outdir)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_package(config: BuildConfig) -> dict[str, Any]:
    if config.jobs < 1:
        raise ContractError("jobs must be positive")
    if tuple(config.contract.receptors) != ("8X6B", "9E6Y"):
        raise ContractError("V1.3 requires exactly 8X6B and 9E6Y native receptors")
    if set(config.references) != set(config.contract.receptors):
        raise ContractError("Reference set does not match native receptors")
    if set(config.expected_reference_inventories) != set(config.contract.receptors):
        raise ContractError("Reference inventory expectations are incomplete")
    if len(MATERIALIZATION_FIELDS) != len(set(MATERIALIZATION_FIELDS)):
        raise ContractError("Duplicate materialization fields")
    if len(METRICS_FIELDS) != len(set(METRICS_FIELDS)):
        raise ContractError("Duplicate metrics fields")
    if any(is_forbidden_output_field(field) for field in (*MATERIALIZATION_FIELDS, *METRICS_FIELDS)):
        raise ContractError("Output schema contains a forbidden field")

    preregistration = validate_preregistration(config.preregistration.resolve(), config.contract)
    cases = load_case_metadata(config)
    toolchain = validate_toolchain(config)
    selector_rows, selector_bindings, selector_evidence = verify_selector(config, cases)
    expected_release_component = current_release_component(config, selector_evidence)
    release_check = validate_release_manifest(
        config.release_manifest.resolve(), expected_release_component
    )
    required_inputs = {
        "preregistration": config.preregistration.resolve(),
        "positive_manifest": config.positive_manifest.resolve(),
        "mutant_manifest": config.mutant_manifest.resolve(),
        "selector_implementation": config.selector_implementation.resolve(),
        "hotspots": config.hotspots.resolve(),
        "reconciliation": config.reconciliation.resolve(),
        "aligner": config.aligner.resolve(),
        "pose_scorer": config.pose_scorer.resolve(),
        "region_scorer": config.region_scorer.resolve(),
        "scoring_helper": config.scoring_helper.resolve(),
        "processor": Path(__file__).resolve(),
        "processor_test": DEFAULT_PROCESSOR_TEST.resolve(),
        **{
            f"reference_{receptor.lower()}": path.resolve()
            for receptor, path in config.references.items()
        },
    }
    if config.selector_audit is not None:
        required_inputs["selector_audit"] = config.selector_audit.resolve()
    if config.release_manifest.is_file():
        required_inputs["release_manifest"] = config.release_manifest.resolve()
    file_bindings = dict(selector_bindings)
    for path in required_inputs.values():
        file_bindings[str(path)] = sha256_file(path)

    outdir = config.outdir.resolve()
    outdir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{outdir.name}.staging.", dir=outdir.parent
    ) as temporary:
        staging_root = Path(temporary)
        validate_native_hotspot_reconciliation(
            config.hotspots.resolve(), config.reconciliation.resolve()
        )
        alignment_maps = materialize_native_alignment_maps(config, staging_root)
        results: dict[int, tuple[dict[str, str], dict[str, str], dict[str, Any]]] = {}

        def submit(index: int, row: Mapping[str, str]) -> tuple[int, dict[str, str], dict[str, str], dict[str, Any]]:
            return process_selector_row(
                index,
                row,
                config=config,
                cases=cases,
                staging_root=staging_root,
                alignment_maps=alignment_maps,
            )

        if config.jobs == 1:
            for index, row in enumerate(selector_rows):
                item = submit(index, row)
                results[item[0]] = item[1:]
        else:
            with ThreadPoolExecutor(max_workers=config.jobs) as executor:
                futures = {
                    executor.submit(submit, index, row): index
                    for index, row in enumerate(selector_rows)
                }
                try:
                    for future in as_completed(futures):
                        item = future.result()
                        results[item[0]] = item[1:]
                except Exception:
                    for future in futures:
                        future.cancel()
                    raise
        if len(results) != config.contract.pose_count:
            raise ContractError("Processed pose cardinality is incomplete")
        material_rows: list[dict[str, str]] = []
        metric_rows: list[dict[str, str]] = []
        contact_rows: list[dict[str, Any]] = []
        for index in range(len(selector_rows)):
            material, metric, contact = results[index]
            material_rows.append(material)
            metric_rows.append(metric)
            contact_rows.append(contact)
        if not (
            len(material_rows)
            == len(metric_rows)
            == len(contact_rows)
            == config.contract.pose_count
        ):
            raise ContractError("Native output row cardinality mismatch")

        # There is deliberately no operation that pairs equal ranks across receptors.
        rows_by_receptor = validate_native_key_closure(metric_rows, config.contract)

        reference_variants: dict[str, set[str]] = defaultdict(set)
        for row in metric_rows:
            reference_variants[row["generation_receptor"]].add(
                row["reference_pvrl2_record_inventory_json"]
            )
            parse_float(row["hotspot_weight_fraction"], "hotspot_weight_fraction")
            parse_int(
                row["total_occluding_residue_pair_count"],
                "total_occluding_residue_pair_count",
                0,
            )
            parse_float(row["cdr123_occlusion_fraction"], "cdr123_occlusion_fraction")
        if any(len(reference_variants[receptor]) != 1 for receptor in config.contract.receptors):
            raise ContractError("Reference inventory drifted within a native receptor")

        manifest_path = staging_root / MATERIALIZATION_MANIFEST_NAME
        metrics_path = staging_root / CONTINUOUS_METRICS_NAME
        contacts_path = staging_root / RESIDUE_CONTACTS_NAME
        audit_path = staging_root / AUDIT_NAME
        write_csv(manifest_path, material_rows, MATERIALIZATION_FIELDS)
        write_csv(metrics_path, metric_rows, METRICS_FIELDS)
        with contacts_path.open("w", encoding="utf-8") as handle:
            for record in contact_rows:
                handle.write(canonical_json(record) + "\n")

        verify_frozen_files(file_bindings)
        aligned_files = sorted(
            (staging_root / "aligned_poses").rglob("*.pdb"),
            key=lambda path: path.relative_to(staging_root).as_posix(),
        )
        if len(aligned_files) != config.contract.pose_count:
            raise ContractError(
                f"Aligned pose count {len(aligned_files)} != {config.contract.pose_count}"
            )
        aligned_manifest = [
            {
                "relpath": output_relative(path, staging_root),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in aligned_files
        ]
        output_hashes: dict[str, Any] = {
            "materialization_manifest": {
                "relpath": MATERIALIZATION_MANIFEST_NAME,
                "sha256": sha256_file(manifest_path),
                "rows": len(material_rows),
                "row_hash_chain": hash_chain(
                    material_rows, "materialization_row_sha256"
                ),
            },
            "continuous_metrics": {
                "relpath": CONTINUOUS_METRICS_NAME,
                "sha256": sha256_file(metrics_path),
                "rows": len(metric_rows),
                "row_hash_chain": hash_chain(metric_rows, "metrics_row_sha256"),
            },
            "residue_contacts": {
                "relpath": RESIDUE_CONTACTS_NAME,
                "sha256": sha256_file(contacts_path),
                "records": len(contact_rows),
                "record_hash_chain": sha256_bytes(
                    "\n".join(
                        record["contact_record_sha256"] for record in contact_rows
                    ).encode("ascii")
                ),
            },
            "aligned_poses": {
                "count": len(aligned_manifest),
                "manifest_sha256": sha256_json(aligned_manifest),
                "files": aligned_manifest,
            },
            "alignment_maps": {
                receptor: {
                    "relpath": values["relpath"],
                    "sha256": values["sha256"],
                    "pair_count": values["pair_count"],
                }
                for receptor, values in alignment_maps.items()
            },
        }
        before_audit = package_file_hashes(staging_root)
        output_hashes["full_generated_package_excluding_audit"] = {
            "file_count": len(before_audit),
            "path_sha256_manifest": sha256_json(before_audit),
        }
        audit: dict[str, Any] = {
            "schema_version": "pvrig_v1_3_native_top8_processing_audit_v1",
            "status": "PASS_V1_3_NATIVE_TOP8_CONTINUOUS_METRICS_BUILT",
            "protocol_id": PROTOCOL_ID,
            "formal_eligible": False,
            "training_label_release_eligible": False,
            "docking_gold_release_eligible": False,
            "primary_native_metric_eligible": True,
            "p2_training_ready": False,
            "native_only": True,
            "claim_boundary": CLAIM_BOUNDARY,
            "thresholds_applied": False,
            "discrete_geometry_outputs_emitted": False,
            "cross_reference_rows_emitted": False,
            "cross_receptor_rank_pairing_performed": False,
            "dual_candidate_score_outputs_emitted": False,
            "preregistration_status": preregistration["status"],
            "selector_contract": selector_evidence,
            "development_release_manifest_check": release_check,
            "expected_contract": config.contract.as_dict(),
            "observed_contract": {
                "case_count": len(cases),
                "run_count": len(
                    {
                        (row["candidate_id"], row["generation_receptor"])
                        for row in metric_rows
                    }
                ),
                "materialization_rows": len(material_rows),
                "metric_rows": len(metric_rows),
                "contact_records": len(contact_rows),
                "aligned_pose_files": len(aligned_files),
                "rows_by_generation_receptor": dict(sorted(rows_by_receptor.items())),
                "alignment_pair_count_values": sorted(
                    {int(row["alignment_pair_count"]) for row in metric_rows}
                ),
            },
            "native_processing_contract": {
                "raw_native_H_scored_once_per_pose": True,
                "native_PVRL2_reference_only": True,
                "rank_pairing_across_receptors": False,
                "9E6Y_direct_native_numbering": True,
                "canonical_hotspot_reconciliation_validated": True,
                "reference_PVRL2_protein_ATOM_only": True,
                "all_reference_HETATM_excluded": True,
                "conditional_null_min_distance_validated": True,
            },
            "reference_inventory_expected": {
                receptor: dict(values)
                for receptor, values in config.expected_reference_inventories.items()
            },
            "reference_inventory_observed": {
                receptor: json.loads(next(iter(reference_variants[receptor])))
                for receptor in config.contract.receptors
            },
            "publication_contract": {
                "atomic_full_directory_replacement": True,
                "post_publish_path_and_hash_set_verified": True,
                "stale_prior_files_preserved": False,
            },
            "input_sha256": {
                "selector_csv": sha256_file(config.selector_csv.resolve()),
                "selector_audit": (
                    sha256_file(config.selector_audit.resolve())
                    if config.selector_audit is not None
                    else ""
                ),
                "preregistration": sha256_file(config.preregistration.resolve()),
                "positive_manifest": sha256_file(config.positive_manifest.resolve()),
                "mutant_manifest": sha256_file(config.mutant_manifest.resolve()),
                "hotspots": sha256_file(config.hotspots.resolve()),
                "reconciliation": sha256_file(config.reconciliation.resolve()),
                "processor": sha256_file(Path(__file__).resolve()),
                "processor_test": sha256_file(DEFAULT_PROCESSOR_TEST.resolve()),
                "development_release_manifest": (
                    sha256_file(config.release_manifest.resolve())
                    if config.release_manifest.is_file()
                    else ""
                ),
                "frozen_file_binding_sha256": sha256_json(dict(sorted(file_bindings.items()))),
                "frozen_file_binding_count": len(file_bindings),
                **{
                    f"reference_{receptor.lower()}": sha256_file(path.resolve())
                    for receptor, path in config.references.items()
                },
            },
            "toolchain": toolchain,
            "expected_release_component": expected_release_component,
            "output_sha256": output_hashes,
        }
        # Eligibility fields above are boundaries, not emitted training labels.
        write_json(audit_path, audit)
        publish_stage(staging_root, outdir)
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector-csv", type=Path, default=DEFAULT_SELECTOR_CSV)
    parser.add_argument("--selector-audit", type=Path, default=DEFAULT_SELECTOR_AUDIT)
    parser.add_argument(
        "--selector-implementation", type=Path, default=DEFAULT_SELECTOR_IMPLEMENTATION
    )
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--positive-manifest", type=Path, default=DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--aligner", type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument("--pose-scorer", type=Path, default=DEFAULT_POSE_SCORER)
    parser.add_argument("--region-scorer", type=Path, default=DEFAULT_REGION_SCORER)
    parser.add_argument("--scoring-helper", type=Path, default=DEFAULT_SCORING_HELPER)
    parser.add_argument("--hotspots", type=Path, default=DEFAULT_HOTSPOTS)
    parser.add_argument("--reconciliation", type=Path, default=DEFAULT_RECONCILIATION)
    parser.add_argument("--reference-8x6b", type=Path, default=RECEPTORS["8X6B"]["reference"])
    parser.add_argument("--reference-9e6y", type=Path, default=RECEPTORS["9E6Y"]["reference"])
    parser.add_argument("--workspace-root", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--jobs", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = BuildConfig(
        selector_csv=args.selector_csv.resolve(),
        selector_audit=args.selector_audit.resolve(),
        selector_implementation=args.selector_implementation.resolve(),
        preregistration=args.preregistration.resolve(),
        release_manifest=args.release_manifest.resolve(),
        positive_manifest=args.positive_manifest.resolve(),
        mutant_manifest=args.mutant_manifest.resolve(),
        aligner=args.aligner.resolve(),
        pose_scorer=args.pose_scorer.resolve(),
        region_scorer=args.region_scorer.resolve(),
        scoring_helper=args.scoring_helper.resolve(),
        hotspots=args.hotspots.resolve(),
        reconciliation=args.reconciliation.resolve(),
        references={
            "8X6B": args.reference_8x6b.resolve(),
            "9E6Y": args.reference_9e6y.resolve(),
        },
        workspace_root=args.workspace_root.resolve(),
        outdir=args.outdir.resolve(),
        jobs=args.jobs,
    )
    try:
        audit = build_package(config)
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": audit["status"],
                "primary_native_metric_eligible": audit[
                    "primary_native_metric_eligible"
                ],
                "formal_eligible": audit["formal_eligible"],
                "training_label_release_eligible": audit[
                    "training_label_release_eligible"
                ],
                "docking_gold_release_eligible": audit[
                    "docking_gold_release_eligible"
                ],
                "output": config.outdir.resolve().as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
