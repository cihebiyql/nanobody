#!/usr/bin/env python3
"""Materialize and score the fixed-emref-Top-8 V1.2 calibration cohort.

The processor is deliberately threshold-free.  It verifies the selector trust
chain, aligns every raw 8X6B-numbered pose independently to both structural
baselines, remaps the 9E6Y scoring channel, and invokes only the versioned V1.2
ATOM-only scorers.  Outputs are development/calibration evidence, never formal
validation or experimental binding/blocking truth.
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
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
DOCKING_SCRIPTS = WORKSPACE_ROOT / "docking/scripts"

PROTOCOL_ID = "DG_A_PVRIG_V1_2_DEV"
SCORING_SEMANTICS_VERSION = "PVRIG_PVRL2_ATOM_ONLY_V1_2"
POSE_SOURCE_PROTOCOL = "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1"
CLAIM_BOUNDARY = (
    "fixed-emref-Top-8 ATOM-only computational calibration evidence; "
    "development only, not formal validation and not experimental binding, "
    "affinity, or blocking truth"
)

DEFAULT_SELECTOR_CSV = (
    EXP_DIR / "data_splits/pvrig_v3_p2/v1_2_calibration_emref_top8_manifest.csv"
)
DEFAULT_SELECTOR_AUDIT = (
    EXP_DIR
    / "audits/phase2_v3_p2_v1_2_calibration_emref_top8_selection_audit.json"
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
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_2_top8_calibration"

BASELINES: Mapping[str, Mapping[str, Any]] = {
    "8x6b": {
        "reference": DATA_ROOT / "structures/8X6B.pdb",
        "pdb_id": "8X6B",
        "ref_pvrig_chain": "B",
        "ref_pvrl2_chain": "A",
        "hotspot_ref_column": "pdb_8x6b_ref",
    },
    "9e6y": {
        "reference": DATA_ROOT / "structures/9E6Y.pdb",
        "pdb_id": "9E6Y",
        "ref_pvrig_chain": "A",
        "ref_pvrl2_chain": "D",
        "hotspot_ref_column": "pdb_9e6y_ref",
    },
}

DEFAULT_EXPECTED_REFERENCE_INVENTORIES: Mapping[str, Mapping[str, Any]] = {
    "8x6b": {
        "chain": "A",
        "parsed_atom_and_hetatm_count": 1021,
        "protein_atom_heavy_atom_count": 963,
        "protein_atom_residue_count": 126,
        "selected_protein_heavy_atom_count": 963,
        "selected_protein_residue_count": 126,
        "excluded_hetatm_heavy_atom_count": 58,
        "excluded_hetatm_residue_count": 58,
        "excluded_hoh_heavy_atom_count": 58,
        "excluded_hoh_residue_count": 58,
        "excluded_edo_heavy_atom_count": 0,
        "excluded_edo_residue_count": 0,
        "excluded_other_hetatm_heavy_atom_count": 0,
        "excluded_other_hetatm_residue_count": 0,
        "atom_altloc_heavy_atom_count": 0,
        "atom_altloc_labels": [],
    },
    "9e6y": {
        "chain": "D",
        "parsed_atom_and_hetatm_count": 1086,
        "protein_atom_heavy_atom_count": 1002,
        "protein_atom_residue_count": 130,
        "selected_protein_heavy_atom_count": 1002,
        "selected_protein_residue_count": 130,
        "excluded_hetatm_heavy_atom_count": 84,
        "excluded_hetatm_residue_count": 66,
        "excluded_hoh_heavy_atom_count": 60,
        "excluded_hoh_residue_count": 60,
        "excluded_edo_heavy_atom_count": 24,
        "excluded_edo_residue_count": 6,
        "excluded_other_hetatm_heavy_atom_count": 0,
        "excluded_other_hetatm_residue_count": 0,
        "atom_altloc_heavy_atom_count": 12,
        "atom_altloc_labels": ["A", "B"],
    },
}

MATERIALIZATION_MANIFEST_NAME = "pvrig_v1_2_top8_pose_materialization_manifest.csv"
CONTINUOUS_METRICS_NAME = "pvrig_v1_2_top8_continuous_metrics.csv"
RESIDUE_CONTACTS_NAME = "pvrig_v1_2_top8_residue_contacts.jsonl"
AUDIT_NAME = "pvrig_v1_2_top8_calibration_audit.json"

SELECTOR_REQUIRED_FIELDS = {
    "schema_version",
    "protocol_id",
    "source_protocol",
    "source_stage",
    "run_id",
    "case_id",
    "candidate_id",
    "family",
    "role",
    "canonical_rank",
    "source_output_index",
    "source_output_file",
    "source_score",
    "source_seed",
    "source_pose_relpath",
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
    "vhh_chain_inventory_json",
    "pvrig_chain_id",
    "pvrig_atom_count",
    "pvrig_residue_count",
    "pvrig_chain_inventory_json",
    "source_io_relpath",
    "source_io_sha256",
    "source_manifest_relpath",
    "source_manifest_sha256",
    "source_manifest_row_sha256",
    "selector_implementation_relpath",
    "selector_implementation_sha256",
    "reuse_role",
    "formal_eligible",
    "selection_row_sha256",
}

MATERIALIZATION_FIELDS = (
    "schema_version",
    "protocol_id",
    "formal_eligible",
    "threshold_freeze_eligible",
    "pose_rule_threshold_freeze_eligible",
    "dual_receptor_r_gold_freeze_eligible",
    "source_docking_receptor",
    "baseline_channel_semantics",
    "run_id",
    "candidate_id",
    "family",
    "evidence_role",
    "control_descriptor",
    "usage_boundary",
    "canonical_rank",
    "source_output_index",
    "source_score",
    "source_seed",
    "selector_row_sha256",
    "source_pose_relpath",
    "source_pose_sha256",
    "decompressed_coordinate_sha256",
    "decompressed_coordinate_bytes",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "alignment_map_8x6b_relpath",
    "alignment_map_8x6b_sha256",
    "alignment_pair_count_8x6b",
    "alignment_rmsd_a_8x6b",
    "aligned_pose_8x6b_relpath",
    "aligned_pose_8x6b_sha256",
    "aligned_pose_8x6b_bytes",
    "alignment_map_9e6y_relpath",
    "alignment_map_9e6y_sha256",
    "alignment_pair_count_9e6y",
    "alignment_rmsd_a_9e6y",
    "aligned_pose_9e6y_relpath",
    "aligned_pose_9e6y_sha256",
    "aligned_pose_9e6y_bytes",
    "remap_observed_receptor_residues_9e6y",
    "remap_remapped_receptor_residues_9e6y",
    "remap_unmapped_receptor_residues_9e6y",
    "materialization_row_sha256",
)

POSE_METRICS = (
    "contact_cutoff_a",
    "clash_cutoff_a",
    "pvrig_vhh_contact_pair_count",
    "pvrig_contact_residue_count",
    "vhh_contact_residue_count",
    "cdr_contact_residue_count",
    "hotspot_count",
    "hotspot_overlap_count",
    "hotspot_overlap_fraction",
    "hotspot_weight_total",
    "hotspot_weight_overlap",
    "hotspot_weight_fraction",
    "pvrl2_vhh_occluding_contact_count",
    "pvrl2_occluded_residue_count",
    "vhh_occluding_residue_count",
    "pvrl2_vhh_clash_count",
    "pvrl2_clash_residue_count",
    "vhh_clash_residue_count",
)
REGION_TOTAL_METRICS = (
    "total_occluding_atom_contact_count",
    "total_clash_atom_contact_count",
    "total_occluding_residue_pair_count",
    "total_clash_residue_pair_count",
)
REGION_ITEM_METRICS = (
    "occluding_atom_contact_count",
    "occlusion_fraction_of_total",
    "occluding_residue_pair_count",
    "occluding_residue_pair_fraction_of_total",
    "clash_atom_contact_count",
    "clash_fraction_of_total",
    "clash_residue_pair_count",
    "clash_residue_pair_fraction_of_total",
    "vhh_residue_count",
    "pvrl2_residue_count",
    "min_distance_a",
)
REGIONS = ("CDR1", "CDR2", "CDR3", "framework")

METRICS_FIELDS = (
    "schema_version",
    "protocol_id",
    "formal_eligible",
    "threshold_freeze_eligible",
    "pose_rule_threshold_freeze_eligible",
    "dual_receptor_r_gold_freeze_eligible",
    "source_docking_receptor",
    "baseline_channel_semantics",
    "run_id",
    "candidate_id",
    "family",
    "evidence_role",
    "control_descriptor",
    "usage_boundary",
    "canonical_rank",
    "source_output_index",
    "source_score",
    "source_seed",
    "selector_row_sha256",
    "baseline",
    "aligned_pose_relpath",
    "aligned_pose_sha256",
    "alignment_pair_count",
    "alignment_rmsd_a",
    "alignment_map_relpath",
    "alignment_map_sha256",
    "remap_applied",
    "remap_observed_receptor_residues",
    "remap_remapped_receptor_residues",
    "remap_unmapped_receptor_residues",
    "reference_relpath",
    "reference_sha256",
    "hotspot_ref_column",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "pose_score_schema_version",
    "region_score_schema_version",
    "scoring_semantics_version",
    *POSE_METRICS,
    *REGION_TOTAL_METRICS,
    *(
        f"{region.lower()}_{metric}"
        for region in REGIONS
        for metric in REGION_ITEM_METRICS
    ),
    "pose_pvrig_record_inventory_json",
    "pose_vhh_record_inventory_json",
    "region_pose_vhh_record_inventory_json",
    "reference_pvrl2_record_inventory_json",
    "region_reference_pvrl2_record_inventory_json",
    "pose_score_payload_sha256",
    "region_score_payload_sha256",
    "metrics_row_sha256",
)

FORBIDDEN_EXACT_FIELDS = {
    "classification",
    "blocker_class",
    "consensus_class",
    "geometry_class",
    "geometry_tier",
    "tier",
    "label",
    "relevance",
}
INVENTORY_AGREEMENT_FIELDS = (
    "chain",
    "parsed_atom_and_hetatm_count",
    "selected_heavy_atom_count",
    "selected_residue_count",
    "atom_heavy_atom_count",
    "atom_residue_count",
    "hetatm_heavy_atom_count",
    "hetatm_residue_count",
    "altloc_heavy_atom_count",
    "altloc_labels",
)
REFERENCE_AGREEMENT_FIELDS = (
    "chain",
    "parsed_atom_and_hetatm_count",
    "protein_atom_heavy_atom_count",
    "protein_atom_residue_count",
    "selected_protein_heavy_atom_count",
    "selected_protein_residue_count",
    "excluded_hetatm_heavy_atom_count",
    "excluded_hetatm_residue_count",
    "excluded_hoh_heavy_atom_count",
    "excluded_hoh_residue_count",
    "excluded_edo_heavy_atom_count",
    "excluded_edo_residue_count",
    "excluded_other_hetatm_heavy_atom_count",
    "excluded_other_hetatm_residue_count",
    "atom_altloc_heavy_atom_count",
    "atom_altloc_labels",
)


class ContractError(RuntimeError):
    """Raised when any calibration trust-chain contract cannot be proven."""


@dataclass(frozen=True)
class DatasetContract:
    positive_cases: int = 11
    mutant_cases: int = 36
    poses_per_case: int = 8

    @property
    def case_count(self) -> int:
        return self.positive_cases + self.mutant_cases

    @property
    def materialization_rows(self) -> int:
        return self.case_count * self.poses_per_case

    @property
    def metric_rows(self) -> int:
        return self.materialization_rows * len(BASELINES)

    def as_dict(self) -> dict[str, int]:
        return {
            "positive_cases": self.positive_cases,
            "mutant_cases": self.mutant_cases,
            "case_count": self.case_count,
            "poses_per_case": self.poses_per_case,
            "materialization_rows": self.materialization_rows,
            "metric_rows": self.metric_rows,
        }


@dataclass(frozen=True)
class BuildConfig:
    selector_csv: Path = DEFAULT_SELECTOR_CSV
    selector_audit: Path | None = DEFAULT_SELECTOR_AUDIT
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
            baseline: Path(spec["reference"]) for baseline, spec in BASELINES.items()
        }
    )
    expected_reference_inventories: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: {
            baseline: dict(inventory)
            for baseline, inventory in DEFAULT_EXPECTED_REFERENCE_INVENTORIES.items()
        }
    )
    outdir: Path = DEFAULT_OUTDIR
    workspace_root: Path = WORKSPACE_ROOT
    contract: DatasetContract = DatasetContract()
    jobs: int = 1
    emit_contact_jsonl: bool = True


@dataclass(frozen=True)
class CaseMetadata:
    candidate_id: str
    family: str
    evidence_role: str
    control_descriptor: str
    usage_boundary: str
    cdr1_range: str
    cdr2_range: str
    cdr3_range: str
    source_manifest: Path
    source_manifest_sha256: str
    source_manifest_row_sha256: str


@dataclass(frozen=True)
class AlignmentEvidence:
    pair_count: int
    skipped_pair_count: int
    fit_atom_count: int
    rmsd_a: float


@dataclass(frozen=True)
class BaselineResult:
    baseline: str
    aligned_pose_relpath: str
    aligned_pose_sha256: str
    aligned_pose_bytes: int
    alignment_map_relpath: str
    alignment_map_sha256: str
    alignment: AlignmentEvidence
    remap: Mapping[str, int]
    pose_report: Mapping[str, Any]
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


def resolve_selector_path(raw: str, workspace_root: Path) -> Path:
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
        numeric = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ContractError(f"{field_name} is not numeric: {value!r}") from error
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ContractError(f"{field_name} is not a finite integer: {value!r}")
    parsed = int(numeric)
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
    raise ContractError(
        f"Metric {field_name} must be scalar, got {type(value).__name__}"
    )


def read_csv_strict(path: Path, *, allow_empty: bool = False) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise ContractError(f"CSV input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ContractError(f"CSV input has no header: {path}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ContractError(f"CSV input has duplicate fields: {path}")
        rows = list(reader)
    if not rows and not allow_empty:
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


def validate_cdr_range(value: str, field_name: str, candidate_id: str) -> str:
    match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", value.strip())
    if not match:
        raise ContractError(f"Invalid {field_name} for {candidate_id}: {value!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        raise ContractError(f"Descending {field_name} for {candidate_id}: {value!r}")
    return f"{start}-{end}"


def safe_component(value: str, field_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ContractError(f"Unsafe {field_name} for output path: {value!r}")
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
    return (
        lowered in FORBIDDEN_EXACT_FIELDS
        or lowered.endswith("_classification")
        or lowered.endswith("_blocker_class")
        or lowered.endswith("_geometry_class")
        or lowered.endswith("_geometry_tier")
        or lowered.endswith("_relevance_label")
    )


def assert_no_classification_fields(value: Any, context: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if is_forbidden_output_field(str(key)):
                raise ContractError(
                    f"Classification/tier field {key!r} appeared in {context}"
                )
            assert_no_classification_fields(nested, context)
    elif isinstance(value, list):
        for nested in value:
            assert_no_classification_fields(nested, context)


def required_mapping(parent: Mapping[str, Any], key: str, context: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"Missing mapping {key!r} in {context}")
    return value


def load_case_manifest(
    path: Path,
    *,
    dataset: str,
    expected_rows: int,
) -> dict[str, CaseMetadata]:
    fields, rows = read_csv_strict(path, allow_empty=expected_rows == 0)
    if len(rows) != expected_rows:
        raise ContractError(
            f"Expected {expected_rows} {dataset} rows in {path}, found {len(rows)}"
        )
    if dataset == "known_positive_calibration":
        id_field = "calibration_name"
        role_field = "validation_role"
        descriptor_field = "sequence_type"
        usage_field = "usage_boundary"
    elif dataset == "mutant_or_perturbation_control":
        id_field = "mutant_name"
        role_field = "intended_role"
        descriptor_field = "control_type"
        usage_field = ""
    else:
        raise ContractError(f"Unknown calibration dataset: {dataset}")
    required = {
        id_field,
        "family",
        role_field,
        descriptor_field,
        "cdr1_range",
        "cdr2_range",
        "cdr3_range",
    }
    missing = sorted(required - set(fields))
    if missing:
        raise ContractError(f"{path} lacks required fields: {missing}")
    manifest_sha256 = sha256_file(path)
    output: dict[str, CaseMetadata] = {}
    for row_number, row in enumerate(rows, start=2):
        candidate_id = row.get(id_field, "").strip()
        if not candidate_id or candidate_id in output:
            raise ContractError(
                f"Missing or duplicate {dataset} candidate at {path}:{row_number}: "
                f"{candidate_id!r}"
            )
        safe_component(candidate_id, "candidate_id")
        output[candidate_id] = CaseMetadata(
            candidate_id=candidate_id,
            family=row.get("family", "").strip(),
            evidence_role=row.get(role_field, "").strip(),
            control_descriptor=row.get(descriptor_field, "").strip(),
            usage_boundary=(
                row.get(usage_field, "").strip()
                if usage_field
                else "development_calibration_control_only_not_assumed_negative"
            ),
            cdr1_range=validate_cdr_range(
                row.get("cdr1_range", ""), "cdr1_range", candidate_id
            ),
            cdr2_range=validate_cdr_range(
                row.get("cdr2_range", ""), "cdr2_range", candidate_id
            ),
            cdr3_range=validate_cdr_range(
                row.get("cdr3_range", ""), "cdr3_range", candidate_id
            ),
            source_manifest=path.resolve(),
            source_manifest_sha256=manifest_sha256,
            source_manifest_row_sha256=sha256_json(row),
        )
    return output


def load_case_metadata(config: BuildConfig) -> dict[str, CaseMetadata]:
    positive = load_case_manifest(
        config.positive_manifest.resolve(),
        dataset="known_positive_calibration",
        expected_rows=config.contract.positive_cases,
    )
    mutant = load_case_manifest(
        config.mutant_manifest.resolve(),
        dataset="mutant_or_perturbation_control",
        expected_rows=config.contract.mutant_cases,
    )
    overlap = sorted(set(positive) & set(mutant))
    if overlap:
        raise ContractError(f"Candidate IDs overlap across calibration manifests: {overlap}")
    return {**positive, **mutant}


def read_coordinate_bytes(path: Path) -> bytes:
    payload = path.read_bytes()
    if not payload:
        raise ContractError(f"Selected source pose is empty: {path}")
    if path.name.endswith(".gz"):
        try:
            coordinates = gzip.decompress(payload)
        except (OSError, EOFError) as error:
            raise ContractError(f"Selected source pose cannot be decompressed: {path}") from error
    else:
        coordinates = payload
    if not coordinates:
        raise ContractError(f"Selected source pose has empty coordinates: {path}")
    try:
        coordinates.decode("ascii")
    except UnicodeDecodeError as error:
        raise ContractError(f"Selected source pose is not ASCII PDB text: {path}") from error
    return coordinates


def parse_inventory_json(row: Mapping[str, str], field_name: str) -> Mapping[str, Any]:
    try:
        inventory = json.loads(row[field_name])
    except (KeyError, json.JSONDecodeError) as error:
        raise ContractError(f"Invalid selector inventory {field_name}") from error
    if not isinstance(inventory, dict):
        raise ContractError(f"Selector inventory {field_name} must be an object")
    assert_finite_tree(inventory, field_name)
    return inventory


def verify_selector_audit(
    path: Path,
    selector_csv: Path,
    selector_rows: Sequence[Mapping[str, str]],
    selector_impl_sha256: str,
    contract: DatasetContract,
) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"Selector audit is missing: {path}")
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Selector audit is invalid JSON: {path}") from error
    if not isinstance(audit, dict):
        raise ContractError(f"Selector audit must be a JSON object: {path}")
    expected_values = {
        "status": "PASS",
        "protocol_id": PROTOCOL_ID,
        "k": contract.poses_per_case,
        "case_count": contract.case_count,
        "selected_pose_count": contract.materialization_rows,
        "formal_eligible": False,
    }
    mismatches = {
        key: (audit.get(key), expected)
        for key, expected in expected_values.items()
        if audit.get(key) != expected
    }
    if mismatches:
        raise ContractError(f"Selector audit contract mismatch: {mismatches}")
    output = required_mapping(audit, "output_csv", "selector audit")
    expected_chain = sha256_bytes(
        "\n".join(row["selection_row_sha256"] for row in selector_rows).encode("ascii")
    )
    output_expectations = {
        "sha256": sha256_file(selector_csv),
        "rows": len(selector_rows),
        "selection_row_hash_chain": expected_chain,
    }
    output_mismatches = {
        key: (output.get(key), expected)
        for key, expected in output_expectations.items()
        if output.get(key) != expected
    }
    if output_mismatches:
        raise ContractError(f"Selector audit output closure mismatch: {output_mismatches}")
    selector = required_mapping(audit, "selector", "selector audit")
    if selector.get("sha256") != selector_impl_sha256:
        raise ContractError(
            "Selector implementation hash differs between selector rows and selector audit"
        )
    return audit


def verify_selector(
    config: BuildConfig,
    cases: Mapping[str, CaseMetadata],
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, Any]]:
    selector_csv = config.selector_csv.resolve()
    fields, rows = read_csv_strict(selector_csv)
    missing = sorted(SELECTOR_REQUIRED_FIELDS - set(fields))
    if missing:
        raise ContractError(f"Selector CSV lacks required fields: {missing}")
    if len(rows) != config.contract.materialization_rows:
        raise ContractError(
            f"Selector row count {len(rows)} != expected "
            f"{config.contract.materialization_rows}"
        )

    file_bindings: dict[str, str] = {
        str(selector_csv): sha256_file(selector_csv),
        str(config.positive_manifest.resolve()): sha256_file(
            config.positive_manifest.resolve()
        ),
        str(config.mutant_manifest.resolve()): sha256_file(
            config.mutant_manifest.resolve()
        ),
    }
    seen_keys: set[tuple[str, int]] = set()
    seen_selection_hashes: set[str] = set()
    candidate_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    selector_impl_paths: set[Path] = set()
    selector_impl_hashes: set[str] = set()

    for row_number, row in enumerate(rows, start=2):
        expected_row_hash = row_sha256(row, "selection_row_sha256")
        if row.get("selection_row_sha256") != expected_row_hash:
            raise ContractError(f"Selector row hash mismatch at row {row_number}")
        if expected_row_hash in seen_selection_hashes:
            raise ContractError(f"Duplicate selector row hash at row {row_number}")
        seen_selection_hashes.add(expected_row_hash)
        if row.get("protocol_id") != PROTOCOL_ID:
            raise ContractError(f"Unexpected selector protocol at row {row_number}")
        if row.get("source_protocol") != POSE_SOURCE_PROTOCOL:
            raise ContractError(f"Unexpected pose source protocol at row {row_number}")
        if row.get("source_stage") != "4_emref":
            raise ContractError(f"Selector row is not from 4_emref at row {row_number}")
        if parse_bool(row.get("formal_eligible"), "selector formal_eligible"):
            raise ContractError("Selector unexpectedly claims formal eligibility")
        if row.get("reuse_role") != "development_only":
            raise ContractError(f"Selector row is not development_only at row {row_number}")
        if row.get("case_id") != row.get("candidate_id"):
            raise ContractError(f"case_id/candidate_id mismatch at row {row_number}")
        candidate_id = safe_component(row.get("candidate_id", ""), "candidate_id")
        case = cases.get(candidate_id)
        if case is None:
            raise ContractError(f"Selector candidate is absent from calibration manifests: {candidate_id}")
        rank = parse_int(row.get("canonical_rank"), "canonical_rank", 1)
        key = (candidate_id, rank)
        if key in seen_keys:
            raise ContractError(f"Duplicate selector candidate/rank: {key}")
        seen_keys.add(key)
        parse_int(row.get("source_output_index"), "source_output_index", 0)
        parse_int(row.get("source_seed"), "source_seed")
        parse_float(row.get("source_score"), "source_score")
        if row.get("vhh_chain_id") != "A" or row.get("pvrig_chain_id") != "B":
            raise ContractError(f"Selector chain contract mismatch for {candidate_id}/rank{rank}")
        if row.get("family") != case.family:
            raise ContractError(f"Selector/manifest family mismatch for {candidate_id}")

        selector_manifest = resolve_selector_path(
            row.get("source_manifest_relpath", ""), config.workspace_root
        )
        if selector_manifest != case.source_manifest:
            raise ContractError(f"Selector source manifest mismatch for {candidate_id}")
        if row.get("source_manifest_sha256") != case.source_manifest_sha256:
            raise ContractError(f"Selector source manifest hash mismatch for {candidate_id}")
        if row.get("source_manifest_row_sha256") != case.source_manifest_row_sha256:
            raise ContractError(f"Selector source manifest row hash mismatch for {candidate_id}")

        source_path = resolve_selector_path(
            row.get("source_pose_relpath", ""), config.workspace_root
        )
        source_payload = source_path.read_bytes() if source_path.is_file() else b""
        if not source_payload:
            raise ContractError(f"Selected source pose is missing or empty: {source_path}")
        source_hash = sha256_bytes(source_payload)
        source_bytes = len(source_payload)
        if source_hash != row.get("source_pose_sha256"):
            raise ContractError(f"Selected source pose hash drift: {source_path}")
        if source_hash != row.get("compressed_source_sha256"):
            raise ContractError(f"Compressed source hash alias mismatch: {source_path}")
        if source_bytes != parse_int(row.get("source_pose_bytes"), "source_pose_bytes", 1):
            raise ContractError(f"Selected source pose byte-count drift: {source_path}")
        if source_bytes != parse_int(
            row.get("compressed_source_bytes"), "compressed_source_bytes", 1
        ):
            raise ContractError(f"Compressed source byte-count alias mismatch: {source_path}")
        expected_format = "pdb.gz" if source_path.name.endswith(".pdb.gz") else "pdb"
        if row.get("source_pose_format") != expected_format:
            raise ContractError(f"Selector pose format mismatch: {source_path}")
        coordinates = read_coordinate_bytes(source_path)
        if sha256_bytes(coordinates) != row.get("decompressed_coordinate_sha256"):
            raise ContractError(f"Decompressed coordinate hash drift: {source_path}")
        if len(coordinates) != parse_int(
            row.get("decompressed_coordinate_bytes"),
            "decompressed_coordinate_bytes",
            1,
        ):
            raise ContractError(f"Decompressed coordinate byte-count drift: {source_path}")

        for inventory_field, atom_field, residue_field, chain in (
            ("vhh_chain_inventory_json", "vhh_atom_count", "vhh_residue_count", "A"),
            (
                "pvrig_chain_inventory_json",
                "pvrig_atom_count",
                "pvrig_residue_count",
                "B",
            ),
        ):
            inventory = parse_inventory_json(row, inventory_field)
            if inventory.get("chain") != chain:
                raise ContractError(f"Selector inventory chain mismatch in {inventory_field}")
            if inventory.get("selected_heavy_atom_count") != parse_int(
                row.get(atom_field), atom_field, 1
            ):
                raise ContractError(f"Selector inventory atom count mismatch in {inventory_field}")
            if inventory.get("selected_residue_count") != parse_int(
                row.get(residue_field), residue_field, 1
            ):
                raise ContractError(
                    f"Selector inventory residue count mismatch in {inventory_field}"
                )

        source_io = resolve_selector_path(row.get("source_io_relpath", ""), config.workspace_root)
        if sha256_file(source_io) != row.get("source_io_sha256"):
            raise ContractError(f"Selector source io.json hash drift: {source_io}")
        selector_impl = resolve_selector_path(
            row.get("selector_implementation_relpath", ""), config.workspace_root
        )
        selector_impl_hash = sha256_file(selector_impl)
        if selector_impl_hash != row.get("selector_implementation_sha256"):
            raise ContractError(f"Selector implementation hash drift: {selector_impl}")
        selector_impl_paths.add(selector_impl)
        selector_impl_hashes.add(selector_impl_hash)
        for path, digest in (
            (source_path, source_hash),
            (source_io, row["source_io_sha256"]),
            (selector_manifest, row["source_manifest_sha256"]),
            (selector_impl, selector_impl_hash),
        ):
            previous = file_bindings.setdefault(str(path), digest)
            if previous != digest:
                raise ContractError(f"Conflicting selector hash bindings for {path}")
        candidate_rows[candidate_id].append(row)

    if set(candidate_rows) != set(cases):
        raise ContractError(
            "Selector/calibration candidate set mismatch: "
            f"missing={sorted(set(cases) - set(candidate_rows))}; "
            f"extra={sorted(set(candidate_rows) - set(cases))}"
        )
    expected_ranks = set(range(1, config.contract.poses_per_case + 1))
    for candidate_id, grouped in candidate_rows.items():
        ranks = {parse_int(row["canonical_rank"], "canonical_rank") for row in grouped}
        if len(grouped) != config.contract.poses_per_case or ranks != expected_ranks:
            raise ContractError(
                f"Fixed Top-{config.contract.poses_per_case} contract failed for "
                f"{candidate_id}: rows={len(grouped)}, ranks={sorted(ranks)}"
            )
        if len({row["run_id"] for row in grouped}) != 1:
            raise ContractError(f"Multiple run IDs found for calibration case {candidate_id}")
    if len(selector_impl_paths) != 1 or len(selector_impl_hashes) != 1:
        raise ContractError("Selector rows do not bind one frozen selector implementation")

    ordered = sorted(
        rows, key=lambda row: (row["candidate_id"], int(row["canonical_rank"]))
    )
    selector_impl_sha256 = next(iter(selector_impl_hashes))
    selector_audit_payload: dict[str, Any] = {}
    if config.selector_audit is not None:
        selector_audit_path = config.selector_audit.resolve()
        selector_audit_payload = verify_selector_audit(
            selector_audit_path,
            selector_csv,
            ordered,
            selector_impl_sha256,
            config.contract,
        )
        file_bindings[str(selector_audit_path)] = sha256_file(selector_audit_path)
    return ordered, file_bindings, {
        "selector_csv_sha256": sha256_file(selector_csv),
        "selector_implementation_path": canonical_input_path(
            next(iter(selector_impl_paths)), config.workspace_root
        ),
        "selector_implementation_sha256": selector_impl_sha256,
        "selector_audit_validated": bool(selector_audit_payload),
        "selection_row_hash_chain": sha256_bytes(
            "\n".join(row["selection_row_sha256"] for row in ordered).encode("ascii")
        ),
    }


def parse_pdb_residue_ref(value: str) -> tuple[str, int, str] | None:
    match = re.fullmatch(r"([^:\s]+):(-?\d+)([A-Za-z]{0,3})", value.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2)), match.group(3).upper()


def build_alignment_pair_rows(
    hotspots: Path,
    baseline: str,
) -> list[dict[str, str]]:
    _fields, rows = read_csv_strict(hotspots)
    target_spec = BASELINES[baseline]
    target_column = str(target_spec["hotspot_ref_column"])
    output: list[dict[str, str]] = []
    for row in rows:
        if row.get("hotspot_class") not in {"core_hotspot", "secondary_hotspot"}:
            continue
        mobile = parse_pdb_residue_ref(row.get("pdb_8x6b_ref", ""))
        reference = parse_pdb_residue_ref(row.get(target_column, ""))
        if mobile is None or reference is None:
            raise ContractError(
                f"Malformed 23-point hotspot mapping for {baseline}: "
                f"{row.get('hotspot_id', '')}"
            )
        if mobile[0] != "B" or reference[0] != target_spec["ref_pvrig_chain"]:
            raise ContractError(
                f"Hotspot chain mismatch for {baseline}: mobile={mobile}, reference={reference}"
            )
        output.append(
            {
                "mobile_ref": f"B:{mobile[1]}{mobile[2]}",
                "reference_ref": f"{reference[0]}:{reference[1]}{reference[2]}",
            }
        )
    if len(output) != 23:
        raise ContractError(
            f"Expected exactly 23 alignment pairs for {baseline}, found {len(output)}"
        )
    if len({row["mobile_ref"] for row in output}) != 23:
        raise ContractError(f"Duplicate mobile residues in {baseline} alignment map")
    if len({row["reference_ref"] for row in output}) != 23:
        raise ContractError(f"Duplicate reference residues in {baseline} alignment map")
    return output


def materialize_alignment_maps(
    config: BuildConfig,
    staging_root: Path,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for baseline in BASELINES:
        rows = build_alignment_pair_rows(config.hotspots.resolve(), baseline)
        relative = Path("alignment_maps") / f"8x6b_to_{baseline}_hotspot23.csv"
        path = staging_root / relative
        write_csv(path, rows, ("mobile_ref", "reference_ref"))
        output[baseline] = {
            "path": path,
            "relpath": relative.as_posix(),
            "sha256": sha256_file(path),
            "pair_count": len(rows),
        }
    return output


def parse_reconciliation(
    path: Path,
) -> dict[str, dict[int, tuple[str, int, str]]]:
    fields, rows = read_csv_strict(path)
    required = {
        "pdb_id",
        "pvrig_chain",
        "pdb_resseq",
        "pdb_icode",
        "uniprot_position",
    }
    missing = sorted(required - set(fields))
    if missing:
        raise ContractError(f"Reconciliation CSV lacks required fields: {missing}")
    by_pdb: dict[str, dict[int, tuple[str, int, str]]] = {
        "8X6B": {},
        "9E6Y": {},
    }
    for row in rows:
        pdb_id = row.get("pdb_id", "").upper()
        raw_uniprot = row.get("uniprot_position", "").strip()
        if pdb_id not in by_pdb or not raw_uniprot:
            continue
        uniprot = parse_int(raw_uniprot, "uniprot_position")
        value = (
            row.get("pvrig_chain", "").strip(),
            parse_int(row.get("pdb_resseq"), "pdb_resseq"),
            row.get("pdb_icode", "").strip(),
        )
        previous = by_pdb[pdb_id].get(uniprot)
        if previous is not None and previous != value:
            raise ContractError(
                f"Ambiguous reconciliation for {pdb_id} UniProt {uniprot}: "
                f"{previous} vs {value}"
            )
        by_pdb[pdb_id][uniprot] = value
    if not by_pdb["8X6B"] or not by_pdb["9E6Y"]:
        raise ContractError("Reconciliation lacks 8X6B or 9E6Y PVRIG mappings")
    return by_pdb


def residue_number_map(
    reconciliation: Mapping[str, Mapping[int, tuple[str, int, str]]],
    source_pdb_id: str = "8X6B",
    target_pdb_id: str = "9E6Y",
) -> dict[tuple[int, str], tuple[int, str]]:
    source = reconciliation[source_pdb_id]
    target = reconciliation[target_pdb_id]
    output: dict[tuple[int, str], tuple[int, str]] = {}
    for uniprot in sorted(set(source) & set(target)):
        source_chain, source_resseq, source_icode = source[uniprot]
        target_chain, target_resseq, target_icode = target[uniprot]
        if source_chain != "B" or target_chain != "A":
            raise ContractError(
                f"Unexpected PVRIG reconciliation chains at UniProt {uniprot}: "
                f"{source_chain}->{target_chain}"
            )
        source_key = (source_resseq, source_icode)
        target_value = (target_resseq, target_icode)
        previous = output.get(source_key)
        if previous is not None and previous != target_value:
            raise ContractError(
                f"Ambiguous 8X6B->9E6Y residue mapping for {source_key}: "
                f"{previous} vs {target_value}"
            )
        output[source_key] = target_value
    if len(output) < 23:
        raise ContractError(f"Reconciliation produced only {len(output)} shared residues")
    return output


def validate_hotspot_reconciliation(
    pair_rows: Sequence[Mapping[str, str]],
    mapping: Mapping[tuple[int, str], tuple[int, str]],
) -> None:
    for row in pair_rows:
        mobile = parse_pdb_residue_ref(row["mobile_ref"])
        target = parse_pdb_residue_ref(row["reference_ref"])
        if mobile is None or target is None:
            raise ContractError("Malformed hotspot row during reconciliation validation")
        observed = mapping.get((mobile[1], ""))
        if observed != (target[1], ""):
            raise ContractError(
                f"Hotspot/reconciliation disagreement: {mobile} -> {observed}, "
                f"expected {target}"
            )


def remap_pose_receptor_numbering(
    source: Path,
    destination: Path,
    mapping: Mapping[tuple[int, str], tuple[int, str]],
    pose_chain: str = "B",
) -> dict[str, int]:
    """Apply the frozen V1.1 reconciliation policy to the 9E6Y score channel."""
    output: list[str] = []
    unmapped_ids: dict[tuple[int, str], int] = {}
    observed_residues: set[tuple[int, str]] = set()
    remapped_residues: set[tuple[int, str]] = set()
    next_unmapped = -900
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 27 and line[21] == pose_chain:
            try:
                original = (int(line[22:26]), line[26].strip())
            except ValueError as error:
                raise ContractError(f"Unparseable pose residue identifier in {source}") from error
            observed_residues.add(original)
            target = mapping.get(original)
            if target is None:
                if original not in unmapped_ids:
                    unmapped_ids[original] = next_unmapped
                    next_unmapped += 1
                target = (unmapped_ids[original], "")
            else:
                remapped_residues.add(original)
            line = f"{line[:22]}{target[0]:4d}{(target[1] or ' ')[:1]}{line[27:]}"
        output.append(line)
    if not observed_residues:
        raise ContractError(f"No PVRIG chain {pose_chain} residues found to remap: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")
    return {
        "observed_receptor_residues": len(observed_residues),
        "remapped_receptor_residues": len(remapped_residues),
        "unmapped_receptor_residues": len(unmapped_ids),
    }


def run_command(command: Sequence[str], *, cwd: Path, label: str) -> str:
    environment = os.environ.copy()
    environment.setdefault("OPENBLAS_NUM_THREADS", "1")
    environment.setdefault("OMP_NUM_THREADS", "1")
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


def parse_alignment_evidence(output: str, context: str) -> AlignmentEvidence:
    pair_match = re.search(r"pairs=(\d+)\s+skipped=(\d+)", output)
    fit_match = re.search(r"fit_atoms=(\d+).*?rmsd=([-+0-9.eE]+)\s+A", output)
    if pair_match is None or fit_match is None:
        raise ContractError(f"Cannot parse alignment evidence for {context}: {output!r}")
    evidence = AlignmentEvidence(
        pair_count=int(pair_match.group(1)),
        skipped_pair_count=int(pair_match.group(2)),
        fit_atom_count=int(fit_match.group(1)),
        rmsd_a=parse_float(fit_match.group(2), f"{context} alignment RMSD"),
    )
    if (
        evidence.pair_count != 23
        or evidence.skipped_pair_count != 0
        or evidence.fit_atom_count != 23
    ):
        raise ContractError(
            f"Alignment pair contract failed for {context}: {evidence}"
        )
    return evidence


def run_json_tool(command: Sequence[str], output: Path, *, cwd: Path, label: str) -> dict[str, Any]:
    run_command(command, cwd=cwd, label=label)
    if not output.is_file():
        raise ContractError(f"{label} did not create JSON output: {output}")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"{label} produced invalid JSON: {output}") from error
    if not isinstance(payload, dict):
        raise ContractError(f"{label} JSON output is not an object: {output}")
    assert_finite_tree(payload, label)
    assert_no_classification_fields(payload, label)
    return payload
