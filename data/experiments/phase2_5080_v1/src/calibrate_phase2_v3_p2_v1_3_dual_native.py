#!/usr/bin/env python3
"""Calibrate the preregistered V1.3 native dual-receptor development method.

The implementation is deliberately development-only.  It consumes the fixed
native Top-8 processor output, fits five anchor-derived channels, aggregates
each receptor independently, and only then joins the two run summaries at the
candidate level.  It never emits Docking Gold, training, binder, affinity, Kd,
or experimental-blocking labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL_NATIVE_DEV"
METHOD_ID = "PVRIG_V1_3_NATIVE_DUAL_RECEPTOR_CALIBRATION_V1"
SCHEMA_VERSION = "pvrig_v1_3_native_dual_receptor_calibration_v1"
METRICS_SCHEMA_VERSION = "pvrig_v1_3_native_top8_continuous_metrics_v1"
PROCESSOR_AUDIT_SCHEMA_VERSION = "pvrig_v1_3_native_top8_processing_audit_v1"
PROCESSOR_PENDING_STATUS = "BUILT_PENDING_DEVELOPMENT_RELEASE"
PROCESSOR_QUALIFICATION_SCHEMA = "pvrig_v1_3_native_processor_qualification_v1"
PROCESSOR_QUALIFICATION_STATUS = "QUALIFIED_NATIVE_PROCESSOR_INPUT"
PREREG_SCHEMA_VERSION = (
    "phase2_v3_p2_docking_gold_v1_3_development_preregistration_v1"
)
PREREGISTRATION_ID = "PVRIG_V3_P2_DOCKING_GOLD_V1_3_DEV_20260714"
PREREGISTRATION_SHA256 = (
    "930c40cd09423a786bb10319f986ec03d890b086e378bfc7198440a8fd92fdff"
)
EXECUTION_RELEASE_SHA256 = (
    "4a0f1a63ef3dc16220beb9d821db71e500d4e512195e7f19a3e112d1d7a2db21"
)
POSITIVE_MANIFEST_SHA256 = (
    "ad1930b5c9938d0969c6645b4be05b9a3b9e49d48b4fb95b8a904a64f31bdef8"
)
MUTANT_MANIFEST_SHA256 = (
    "81f42361be2e31dd8a083eb5cf28b35e1d09292635801a9a021fbe29b1d19248"
)
CASE_MANIFEST_SHA256 = (
    "63e08d11d548afd98cca93d66d54395b0084d7398f4c8e94f288aa64cc326e81"
)
RUN_MANIFEST_SHA256 = (
    "7db0b4865169020381d3df22bd7dd39113c33d679d24960f73aedf75cdb8175f"
)
PROTOCOL_MANIFEST_SHA256 = (
    "79308811f52715308bb9d52aaee6d361b1e4f62dec5beec94b6d5a3054dc5709"
)
REFERENCE_SHA256 = {
    "8X6B": "b9a930e44f61ee2ba35b4f8f739bc9431eb1944dad2e2344bd9c9a7ad13bb868",
    "9E6Y": "fb05ec77e439b8e1f43bfa12d7eb60f05f2c53e2099f06442f6c9ced32d98316",
}
NATIVE_HOTSPOT_COLUMN = {"8X6B": "pdb_8x6b_ref", "9E6Y": "pdb_9e6y_ref"}
RECEPTORS = ("8X6B", "9E6Y")
POSE_CLASSES = ("A", "B", "C", "E")
CLASS_RELEVANCE = {"A": 4, "B": 2, "C": 1, "E": 0}
CLASS_ORDINAL = {"A": 3, "B": 2, "C": 1, "E": 0}
DUAL_TIER_STRENGTH = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}
LOWER_QUANTILE = 0.20
UPPER_QUANTILE = 0.50
SUPPORT_FRACTION = 0.25
MIN_SUPPORTING_POSES = 2
BOOTSTRAP_SEED = 20260714
BOOTSTRAP_REPLICATES = 2000
ROBUSTNESS_LOWER_QUANTILES = (0.10, 0.20, 0.30)
ROBUSTNESS_UPPER_QUANTILES = (0.40, 0.50, 0.60)
ROBUSTNESS_SUPPORT_FRACTIONS = (0.20, 0.25, 0.33)
ROBUSTNESS_MIN_SUPPORTING_POSES = (2, 3)
CLAIM_BOUNDARY = (
    "Independent native 8X6B/9E6Y computational geometry development only; "
    "not Docking Gold, a training label, binder truth, affinity/Kd truth, or "
    "experimental blocking truth."
)

DEFAULT_PROCESSING_DIR = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/runs/pvrig_v3_p2/"
    "docking_gold_v1_3_native_processing"
)
DEFAULT_PROCESSING_CURRENT = DEFAULT_PROCESSING_DIR / "current"
DEFAULT_METRICS_CSV = (
    DEFAULT_PROCESSING_CURRENT / "pvrig_v1_3_native_top8_continuous_metrics.csv"
)
DEFAULT_PROCESSOR_AUDIT = (
    DEFAULT_PROCESSING_CURRENT / "pvrig_v1_3_native_top8_processing_audit.json"
)
DEFAULT_PROCESSOR_QUALIFICATION_ROOT = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/runs/pvrig_v3_p2/"
    "docking_gold_v1_3_native_processor_qualification"
)
DEFAULT_PROCESSOR_QUALIFICATION = (
    DEFAULT_PROCESSOR_QUALIFICATION_ROOT
    / "current/pvrig_v1_3_native_processor_qualification.json"
)
DEFAULT_SELECTOR_ROOT = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/runs/pvrig_v3_p2/"
    "docking_gold_v1_3_dual47_top8_recovery"
)
DEFAULT_SELECTOR_DIR = DEFAULT_SELECTOR_ROOT / "current"
DEFAULT_SELECTOR_CSV = DEFAULT_SELECTOR_DIR / "pvrig_v1_3_dual47_emref_top8_selector.csv"
DEFAULT_SELECTOR_AUDIT = DEFAULT_SELECTOR_DIR / "pvrig_v1_3_dual47_emref_top8_recovery_audit.json"
DEFAULT_EXECUTION_RELEASE = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/audits/"
    "phase2_v3_p2_v1_3_docking_execution_release_manifest.json"
)
DEFAULT_PACKAGE_DIR = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/runs/pvrig_v3_p2/"
    "docking_gold_v1_3_dual47_completion15_package"
)
DEFAULT_CASE_MANIFEST = DEFAULT_PACKAGE_DIR / "manifests/case_manifest.csv"
DEFAULT_RUN_MANIFEST = DEFAULT_PACKAGE_DIR / "manifests/run_manifest.csv"
DEFAULT_PROTOCOL_MANIFEST = DEFAULT_PACKAGE_DIR / "manifests/protocol_manifest.csv"
DEFAULT_REFERENCES = {
    "8X6B": WORKSPACE_ROOT / "structures/8X6B.pdb",
    "9E6Y": WORKSPACE_ROOT / "structures/9E6Y.pdb",
}
DEFAULT_CALIBRATOR_TEST = (
    Path(__file__).resolve().with_name(
        "test_calibrate_phase2_v3_p2_v1_3_dual_native.py"
    )
)
DEFAULT_PROCESSOR_IMPLEMENTATION = (
    Path(__file__).resolve().with_name("process_phase2_v3_p2_v1_3_native_top8.py")
)
DEFAULT_PROCESSOR_TEST = (
    Path(__file__).resolve().with_name(
        "test_process_phase2_v3_p2_v1_3_native_top8.py"
    )
)
DEFAULT_PROCESSOR_QUALIFICATION_VALIDATOR = (
    Path(__file__).resolve().with_name(
        "validate_phase2_v3_p2_v1_3_native_processor_release.py"
    )
)
DEFAULT_PROCESSOR_QUALIFICATION_TEST = (
    Path(__file__).resolve().with_name(
        "test_validate_phase2_v3_p2_v1_3_native_processor_release.py"
    )
)
DEFAULT_PREREGISTRATION = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/audits/"
    "phase2_v3_p2_v1_3_development_preregistration.json"
)
DEFAULT_POSITIVE_MANIFEST = (
    WORKSPACE_ROOT.parent
    / "docking/calibration/patent_success_validation/batch_manifest.csv"
)
DEFAULT_MUTANT_MANIFEST = (
    WORKSPACE_ROOT.parent
    / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
)
DEFAULT_OUTDIR = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/runs/pvrig_v3_p2/"
    "docking_gold_v1_3_native_dual_calibration"
)
DEFAULT_REPORT = (
    DEFAULT_OUTDIR
    / "current/PVRIG_V3_P2_DOCKING_GOLD_V1_3_NATIVE_DUAL_CALIBRATION_ZH.md"
)

RULES_NAME = "pvrig_v1_3_native_dual_rules.json"
POSE_SCORES_NAME = "pvrig_v1_3_native_pose_scores.csv"
RUN_SCORES_NAME = "pvrig_v1_3_native_run_scores.csv"
DUAL_SCORES_NAME = "pvrig_v1_3_dual_candidate_scores.csv"
LOFO_NAME = "pvrig_v1_3_family_lofo.csv"
BOOTSTRAP_THRESHOLDS_NAME = "pvrig_v1_3_bootstrap_thresholds.csv"
BOOTSTRAP_RECEPTOR_NAME = "pvrig_v1_3_bootstrap_receptor_anchor_evaluations.csv"
BOOTSTRAP_DUAL_NAME = "pvrig_v1_3_bootstrap_dual_anchor_evaluations.csv"
MUTANT_DELTAS_NAME = "pvrig_v1_3_mutant_paired_deltas.csv"
ROBUSTNESS_NAME = "pvrig_v1_3_robustness_grid.csv"
AUDIT_NAME = "pvrig_v1_3_native_dual_calibration_audit.json"
RELEASE_INPUT_NAME = "pvrig_v1_3_calibration_release_input.json"
REPORT_NAME = "PVRIG_V3_P2_DOCKING_GOLD_V1_3_NATIVE_DUAL_CALIBRATION_ZH.md"
CALCULATED_STATUS = "CALCULATED_PENDING_RELEASE_VALIDATION"
RELEASE_INPUT_STATUS = "PENDING_EXTERNAL_RELEASE_VALIDATION"
PointerPromoter = Callable[[Path, Path], None]


class CalibrationError(RuntimeError):
    """Raised when a frozen calibration contract fails closed."""


@dataclass(frozen=True)
class CalibrationContract:
    case_count: int = 47
    positive_case_count: int = 11
    positive_family_count: int = 5
    control_case_count: int = 36
    mutant_delta_count: int = 29
    receptors_per_case: int = 2
    ranks_per_run: int = 8

    @property
    def run_count(self) -> int:
        return self.case_count * self.receptors_per_case

    @property
    def metric_rows(self) -> int:
        return self.run_count * self.ranks_per_run


@dataclass(frozen=True)
class CalibrationConfig:
    metrics_csv: Path
    processor_audit: Path
    processor_qualification: Path
    selector_csv: Path
    selector_audit: Path
    execution_release: Path
    case_manifest: Path
    run_manifest: Path
    protocol_manifest: Path
    references: Mapping[str, Path]
    preregistration: Path
    positive_manifest: Path
    mutant_manifest: Path
    outdir: Path
    report: Path
    bootstrap_seed: int = BOOTSTRAP_SEED
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES
    contract: CalibrationContract = CalibrationContract()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise CalibrationError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: Mapping[str, Any], hash_field: str) -> str:
    return sha256_json({key: value for key, value in row.items() if key != hash_field})


def row_hash_chain(rows: Sequence[Mapping[str, Any]], hash_field: str) -> str:
    return sha256_json([str(row[hash_field]) for row in rows])


def newline_hash_chain(rows: Sequence[Mapping[str, Any]], hash_field: str) -> str:
    return sha256_bytes(
        "\n".join(str(row[hash_field]) for row in rows).encode("ascii")
    )


def canonical_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def canonical_path_lexical(path: Path) -> str:
    absolute = Path(os.path.abspath(path))
    try:
        return absolute.relative_to(Path(os.path.abspath(WORKSPACE_ROOT))).as_posix()
    except ValueError:
        return absolute.as_posix()


def scalar_text(value: Any, field_name: str = "value") -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CalibrationError(f"Non-finite {field_name}: {value!r}")
        return format(value, ".17g")
    if isinstance(value, str):
        return value
    raise CalibrationError(f"{field_name} must be scalar, got {type(value).__name__}")


def normalize_record(
    record: Mapping[str, Any], fields: Sequence[str], hash_field: str
) -> dict[str, str]:
    normalized = {
        field: scalar_text(record.get(field), field)
        for field in fields
        if field != hash_field
    }
    normalized[hash_field] = row_sha256(normalized, hash_field)
    return normalized


def read_csv_strict(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise CalibrationError(f"CSV input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise CalibrationError(f"CSV header is missing or duplicated: {path}")
        rows = list(reader)
    if not rows:
        raise CalibrationError(f"CSV input has no rows: {path}")
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


def parse_int(value: Any, field: str, minimum: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise CalibrationError(f"{field} is not an integer: {value!r}") from error
    if parsed < minimum:
        raise CalibrationError(f"{field} must be >= {minimum}, got {parsed}")
    return parsed


def parse_float(value: Any, field: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise CalibrationError(f"{field} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise CalibrationError(f"{field} is not finite: {value!r}")
    return parsed


def parse_bool(value: Any, field: str) -> bool:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    raise CalibrationError(f"{field} is not boolean: {value!r}")


def normalized_rank_weights(k: int) -> dict[int, float]:
    if k < 1:
        raise CalibrationError("Rank count must be positive")
    raw = {rank: 1.0 / math.log2(rank + 1.0) for rank in range(1, k + 1)}
    total = sum(raw.values())
    return {rank: value / total for rank, value in raw.items()}


def weighted_quantile(
    values_and_weights: Iterable[tuple[float, float]], quantile: float
) -> float:
    if not 0.0 <= quantile <= 1.0:
        raise CalibrationError(f"Quantile outside [0,1]: {quantile}")
    supplied = list(values_and_weights)
    if any(
        not math.isfinite(value) or not math.isfinite(weight) or weight < 0.0
        for value, weight in supplied
    ):
        raise CalibrationError("Weighted quantile has invalid input")
    values = sorted((value, weight) for value, weight in supplied if weight > 0.0)
    if not values:
        raise CalibrationError("Weighted quantile has invalid or empty input")
    target = quantile * sum(weight for _, weight in values)
    cumulative = 0.0
    for value, weight in values:
        cumulative += weight
        if cumulative + 1e-15 >= target:
            return value
    return values[-1][0]


def ordinary_quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise CalibrationError("Ordinary quantile has no values")
    ordered = sorted(values)
    position = quantile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def validate_atom_only_inventory(raw: str) -> str:
    try:
        inventory = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CalibrationError("reference_pvrl2_record_inventory_json is invalid") from error
    if not isinstance(inventory, dict):
        raise CalibrationError("PVRL2 inventory must be an object")
    rule = str(inventory.get("selection_rule", ""))
    selected_atoms = parse_int(
        inventory.get("selected_protein_heavy_atom_count"), "selected atoms", 1
    )
    protein_atoms = parse_int(
        inventory.get("protein_atom_heavy_atom_count"), "protein atoms", 1
    )
    selected_residues = parse_int(
        inventory.get("selected_protein_residue_count"), "selected residues", 1
    )
    protein_residues = parse_int(
        inventory.get("protein_atom_residue_count"), "protein residues", 1
    )
    if (
        "protein ATOM" not in rule
        or "all HETATM excluded" not in rule
        or selected_atoms != protein_atoms
        or selected_residues != protein_residues
    ):
        raise CalibrationError("PVRL2 inventory is not protein-ATOM-only")
    return canonical_json(inventory)


def load_positive_manifest(path: Path) -> dict[str, dict[str, str]]:
    fields, rows = read_csv_strict(path)
    required = {"calibration_name", "family", "validation_role"}
    if not required <= set(fields):
        raise CalibrationError("Positive manifest schema mismatch")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        case_id = row["calibration_name"].strip()
        if not case_id or case_id in result or not row["family"].strip():
            raise CalibrationError(f"Missing or duplicate positive case: {case_id!r}")
        result[case_id] = {
            "family": row["family"].strip(),
            "role": row["validation_role"].strip(),
            "manifest_row_sha256": sha256_json(row),
        }
    return result


def load_mutant_manifest(
    path: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    fields, rows = read_csv_strict(path)
    required = {
        "mutant_name", "base_molecule", "family", "control_type",
        "mutation_class", "mutations_1based",
    }
    if not required <= set(fields):
        raise CalibrationError("Mutant manifest schema mismatch")
    records: dict[str, dict[str, str]] = {}
    base_by_molecule: dict[str, str] = {}
    for row in rows:
        case_id = row["mutant_name"].strip()
        molecule = row["base_molecule"].strip()
        if not case_id or not molecule or case_id in records:
            raise CalibrationError(f"Missing or duplicate control case: {case_id!r}")
        record = {
            "family": row["family"].strip(),
            "base_molecule": molecule,
            "control_type": row["control_type"].strip(),
            "mutation_class": row["mutation_class"].strip(),
            "mutations_1based": row["mutations_1based"].strip(),
            "manifest_row_sha256": sha256_json(row),
        }
        records[case_id] = record
        if record["control_type"] == "base_reference":
            if molecule in base_by_molecule:
                raise CalibrationError(f"Duplicate exact base for {molecule}")
            base_by_molecule[molecule] = case_id
    for case_id, record in records.items():
        if (
            record["control_type"] != "base_reference"
            and record["base_molecule"] not in base_by_molecule
        ):
            raise CalibrationError(f"No exact base for {case_id}")
    return records, base_by_molecule


def apply_declared_mutations(base_sequence: str, mutation_text: str) -> str:
    sequence = list(base_sequence)
    mutations = mutation_text.split(";") if mutation_text != "none" else []
    if not mutations:
        return base_sequence
    seen_positions: set[int] = set()
    for mutation in mutations:
        match = re.fullmatch(r"([A-Z])(\d+)([A-Z])", mutation)
        if not match:
            raise CalibrationError(f"Invalid mutation declaration: {mutation!r}")
        source, raw_position, target = match.groups()
        position = int(raw_position)
        if position < 1 or position > len(sequence) or position in seen_positions:
            raise CalibrationError(f"Invalid/repeated mutation position: {mutation}")
        seen_positions.add(position)
        if base_sequence[position - 1] != source:
            raise CalibrationError(
                f"Mutation source mismatch at {mutation}: "
                f"base has {base_sequence[position - 1]}"
            )
        sequence[position - 1] = target
    return "".join(sequence)


def validate_fixed_case_semantics(
    config: CalibrationConfig,
    frozen_cases: Mapping[str, Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    base_by_molecule: Mapping[str, str],
) -> dict[str, Any]:
    positive_evidence = require_canonical_frozen_file(
        config.positive_manifest,
        DEFAULT_POSITIVE_MANIFEST,
        POSITIVE_MANIFEST_SHA256,
        "positive manifest",
    )
    mutant_evidence = require_canonical_frozen_file(
        config.mutant_manifest,
        DEFAULT_MUTANT_MANIFEST,
        MUTANT_MANIFEST_SHA256,
        "mutant manifest",
    )
    expected_cases = set(positive_cases) | set(mutant_cases)
    if set(frozen_cases) != expected_cases:
        raise CalibrationError("Frozen case manifest and positive/control manifests differ")
    for case_id, record in positive_cases.items():
        frozen = frozen_cases[case_id]
        if frozen["family"] != record["family"]:
            raise CalibrationError(f"Positive family mismatch in frozen case ledger: {case_id}")
    validated_mutations = 0
    validated_bases = 0
    for case_id, record in mutant_cases.items():
        frozen = frozen_cases[case_id]
        if frozen["family"] != record["family"]:
            raise CalibrationError(f"Control family mismatch in frozen case ledger: {case_id}")
        base_id = base_by_molecule[record["base_molecule"]]
        base_sequence = frozen_cases[base_id]["sequence"]
        expected_sequence = apply_declared_mutations(
            base_sequence, record["mutations_1based"]
        )
        if record["control_type"] == "base_reference":
            validated_bases += 1
            if record["mutations_1based"] != "none" or frozen["sequence"] != base_sequence:
                raise CalibrationError(f"Base-reference semantics mismatch: {case_id}")
        else:
            validated_mutations += 1
            if expected_sequence != frozen["sequence"]:
                raise CalibrationError(f"Declared mutations do not reproduce sequence: {case_id}")
        if sha256_bytes(frozen["sequence"].encode("ascii")) != frozen["sequence_sha256"]:
            raise CalibrationError(f"Frozen sequence SHA256 mismatch: {case_id}")
    if validated_bases != 7 or validated_mutations != 29:
        raise CalibrationError("Expected 7 exact bases and 29 declared mutation sequences")
    return {
        "positive_manifest": positive_evidence,
        "mutant_manifest": mutant_evidence,
        "positive_case_count": len(positive_cases),
        "control_case_count": len(mutant_cases),
        "exact_base_count": validated_bases,
        "declared_mutation_count": validated_mutations,
        "sequence_hashes_validated": True,
        "mutation_semantics_validated": True,
    }


SELECTOR_REQUIRED_FIELDS = {
    "schema_version", "protocol_id", "source_protocol", "source_stage", "run_id",
    "case_id", "candidate_id", "family", "sequence_sha256",
    "generation_receptor", "receptor_id", "native_rank", "canonical_rank",
    "receptor_sha256", "run_manifest_sha256", "run_manifest_row_sha256",
    "execution_release_manifest_sha256", "publication_release_id",
    "formal_eligible", "training_label_release_eligible",
    "docking_gold_release_eligible", "selection_row_sha256",
}


def validate_selector_publication(
    selector_csv: Path,
    selector_audit: Path,
    frozen_cases: Mapping[str, Mapping[str, str]],
    frozen_runs: Mapping[tuple[str, str], Mapping[str, str]],
    protocols: Mapping[str, Mapping[str, str]],
) -> tuple[dict[tuple[str, str, int], dict[str, str]], dict[str, Any]]:
    fields, rows = read_csv_strict(selector_csv)
    missing = sorted(SELECTOR_REQUIRED_FIELDS - set(fields))
    if missing or len(rows) != 752:
        raise CalibrationError(
            f"Selector publication schema/cardinality mismatch: missing={missing}, rows={len(rows)}"
        )
    selector_by_key: dict[tuple[str, str, int], dict[str, str]] = {}
    selector_hashes: set[str] = set()
    release_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        if row["selection_row_sha256"] != row_sha256(row, "selection_row_sha256"):
            raise CalibrationError(f"Selector row SHA256 mismatch at row {row_number}")
        case_id = row["candidate_id"]
        receptor = row["generation_receptor"].upper()
        rank = parse_int(row["native_rank"], "native_rank", 1)
        key = (case_id, receptor, rank)
        frozen_case = frozen_cases.get(case_id)
        frozen_run = frozen_runs.get((case_id, receptor))
        if (
            row["schema_version"] != "phase2_v3_p2_v1_3_dual47_emref_top8_selection_v3"
            or row["protocol_id"] != "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
            or row["source_protocol"] != "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1"
            or row["source_stage"] != "4_emref"
            or receptor not in RECEPTORS
            or row["receptor_id"].upper() != receptor
            or rank > 8
            or parse_int(row["canonical_rank"], "canonical_rank", 1) != rank
            or key in selector_by_key
            or frozen_case is None
            or frozen_run is None
            or row["case_id"] != case_id
            or row["family"] != frozen_case["family"]
            or row["sequence_sha256"] != frozen_case["sequence_sha256"]
            or row["run_id"] != frozen_run["run_id"]
            or row["run_manifest_sha256"] != RUN_MANIFEST_SHA256
            or row["run_manifest_row_sha256"] != frozen_run["run_manifest_row_sha256"]
            or row["receptor_sha256"] != protocols[receptor]["receptor_sha256"]
            or row["execution_release_manifest_sha256"] != EXECUTION_RELEASE_SHA256
            or any(
                parse_bool(row[field], field)
                for field in (
                    "formal_eligible", "training_label_release_eligible",
                    "docking_gold_release_eligible", "p2_training_ready",
                )
            )
        ):
            raise CalibrationError(f"Selector native identity mismatch at row {row_number}")
        selector_by_key[key] = row
        selector_hashes.add(row["selection_row_sha256"])
        release_ids.add(row["publication_release_id"])
    expected_keys = {
        (case_id, receptor, rank)
        for case_id in frozen_cases
        for receptor in RECEPTORS
        for rank in range(1, 9)
    }
    if set(selector_by_key) != expected_keys or len(selector_hashes) != 752:
        raise CalibrationError("Selector 94-run/752-pose identity/hash closure failed")
    if len(release_ids) != 1 or "" in release_ids:
        raise CalibrationError("Selector rows do not bind one immutable publication release")
    audit = json.loads(selector_audit.read_text(encoding="utf-8"))
    expected_audit = {
        "schema_version": "phase2_v3_p2_v1_3_dual47_emref_top8_recovery_audit_v3",
        "status": "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED",
        "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
        "source_protocol": "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1",
        "k": 8,
        "selection_backfill": False,
        "scoring_performed": False,
        "remote_local_hash_chain_equal": True,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "p2_training_ready": False,
    }
    for field, value in expected_audit.items():
        if audit.get(field) != value:
            raise CalibrationError(f"Selector audit {field} mismatch")
    counts = audit.get("counts", {})
    if not isinstance(counts, dict) or any(
        counts.get(field) != value
        for field, value in {
            "manifest_runs": 94, "selected_runs": 94, "selected_poses": 752,
            "cases": 47, "reuse_runs": 64, "new_runs": 30,
        }.items()
    ):
        raise CalibrationError("Selector audit 94-run/752-pose count closure failed")
    output = audit.get("output_csv", {})
    selector_chain = sha256_bytes(
        "\n".join(row["selection_row_sha256"] for row in rows).encode("ascii")
    )
    if not isinstance(output, dict) or any(
        output.get(field) != value
        for field, value in {
            "sha256": sha256_file(selector_csv),
            "rows": 752,
            "selection_row_hash_chain": selector_chain,
        }.items()
    ):
        raise CalibrationError("Selector audit output hash closure failed")
    publication = audit.get("publication", {})
    release_id = next(iter(release_ids))
    if (
        not isinstance(publication, dict)
        or publication.get("release_id") != release_id
        or publication.get("promotion") != "single atomic current symlink replacement"
        or publication.get("rollback_safe") is not True
    ):
        raise CalibrationError("Selector immutable publication contract mismatch")
    inputs = audit.get("inputs", {})
    release_input = inputs.get("execution_release_manifest", {}) if isinstance(inputs, dict) else {}
    if not isinstance(release_input, dict) or release_input.get("sha256") != EXECUTION_RELEASE_SHA256:
        raise CalibrationError("Selector audit does not bind frozen execution release")
    return selector_by_key, {
        "selector_csv": {
            "relpath": canonical_path(selector_csv),
            "sha256": sha256_file(selector_csv),
            "rows": len(rows),
            "row_hash_chain": selector_chain,
        },
        "selector_audit": {
            "relpath": canonical_path(selector_audit),
            "sha256": sha256_file(selector_audit),
            "status": audit["status"],
        },
        "publication_release_id": release_id,
        "immutable_publication_validated": True,
        "run_count": 94,
        "pose_count": 752,
    }


def validate_preregistration(path: Path) -> dict[str, Any]:
    observed_hash = sha256_file(path)
    if observed_hash != PREREGISTRATION_SHA256:
        raise CalibrationError(
            f"Frozen preregistration SHA256 mismatch: {observed_hash}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": PREREG_SCHEMA_VERSION,
        "preregistration_id": PREREGISTRATION_ID,
        "protocol_id": PROTOCOL_ID,
        "status": "PREREGISTERED_V1_3_DEVELOPMENT_ONLY_PENDING_IMPLEMENTATION",
        "training_state": "P2_TRAINING_BLOCKED",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise CalibrationError(f"Frozen preregistration {field} mismatch")
    checks = (
        payload.get("threshold_contract", {}).get("primary_channel_count") == 5,
        payload.get("cohort", {}).get("case_count") == 47,
        payload.get("cohort", {}).get("total_native_main_run_count") == 94,
        payload.get("primary_processing", {}).get("expected_primary_metric_rows") == 752,
        payload.get("bootstrap", {}).get("replicates") == 2000,
        payload.get("bootstrap", {}).get("seed") == 20260714,
        payload.get("anchor_readiness", {}).get("unconditional_formal_veto") is True,
        payload.get("eligibility", {}).get("development_method_evaluation_eligible") is True,
        payload.get("eligibility", {}).get("formal_eligible") is False,
        payload.get("eligibility", {}).get("docking_gold_release_eligible") is False,
        payload.get("eligibility", {}).get("training_label_release_eligible") is False,
        payload.get("eligibility", {}).get("p2_training_ready") is False,
    )
    if not all(checks):
        raise CalibrationError("Frozen preregistration semantic closure failed")
    bindings = payload.get("evidence_bindings")
    if not isinstance(bindings, list) or len(bindings) != 17:
        raise CalibrationError("Frozen preregistration evidence ledger is incomplete")
    validated_bindings: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            raise CalibrationError(f"Preregistration evidence[{index}] is not an object")
        raw_path = str(binding.get("path", ""))
        if not raw_path or raw_path in seen_paths:
            raise CalibrationError(f"Duplicate/empty preregistration evidence path: {raw_path!r}")
        seen_paths.add(raw_path)
        evidence_path = (WORKSPACE_ROOT / raw_path).resolve()
        expected_hash = str(binding.get("sha256", ""))
        expected_bytes = parse_int(binding.get("bytes"), f"evidence[{index}].bytes", 1)
        if (
            not evidence_path.is_file()
            or evidence_path.stat().st_size != expected_bytes
            or sha256_file(evidence_path) != expected_hash
        ):
            raise CalibrationError(f"Preregistration evidence binding drift: {raw_path}")
        validated_bindings.append(
            {
                "path": raw_path,
                "sha256": expected_hash,
                "bytes": expected_bytes,
                "role": str(binding.get("role", "")),
            }
        )
    return {
        "relpath": canonical_path(path),
        "sha256": observed_hash,
        "schema_version": payload["schema_version"],
        "preregistration_id": payload["preregistration_id"],
        "evidence_binding_count": len(validated_bindings),
        "evidence_binding_sha256": sha256_json(validated_bindings),
        "validated": True,
    }


def require_canonical_frozen_file(
    path: Path, canonical: Path, expected_hash: str, label: str
) -> dict[str, Any]:
    if path.resolve() != canonical.resolve():
        raise CalibrationError(f"{label} must use canonical path: {canonical}")
    observed_hash = sha256_file(path)
    if observed_hash != expected_hash:
        raise CalibrationError(f"Frozen {label} SHA256 mismatch: {observed_hash}")
    return {
        "relpath": canonical_path(path),
        "sha256": observed_hash,
        "bytes": path.stat().st_size,
        "validated": True,
    }


def validate_execution_release(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    evidence = require_canonical_frozen_file(
        path, DEFAULT_EXECUTION_RELEASE, EXECUTION_RELEASE_SHA256, "execution release"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": "phase2_v3_p2_v1_3_docking_execution_release_v1",
        "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
        "status": "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE",
        "remote_launch_eligible": True,
        "remote_launch_run_count": 30,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise CalibrationError(f"Execution release {field} mismatch")
    closure = payload.get("execution_closure", {})
    if not isinstance(closure, dict) or closure != {
        "candidate_count": 47,
        "new_completion15_run_count": 30,
        "reused_pilot64_main_run_count": 64,
        "run_count_per_receptor": 47,
        "total_main_run_count": 94,
    }:
        raise CalibrationError("Execution release 94-run closure mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) < 30:
        raise CalibrationError("Execution release artifact ledger is incomplete")
    ledger: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            raise CalibrationError(f"Execution release artifact[{index}] is invalid")
        relpath = str(item.get("path", ""))
        if not relpath or relpath in ledger:
            raise CalibrationError(f"Duplicate/empty execution artifact path: {relpath!r}")
        artifact_path = (WORKSPACE_ROOT / relpath).resolve()
        expected_bytes = parse_int(item.get("bytes"), f"execution artifact {relpath} bytes", 1)
        expected_hash = str(item.get("sha256", ""))
        if (
            not artifact_path.is_file()
            or artifact_path.stat().st_size != expected_bytes
            or sha256_file(artifact_path) != expected_hash
        ):
            raise CalibrationError(f"Execution release artifact drift: {relpath}")
        ledger[relpath] = {
            "path": relpath,
            "sha256": expected_hash,
            "bytes": expected_bytes,
        }
    evidence.update(
        {
            "status": payload["status"],
            "artifact_count": len(ledger),
            "artifact_ledger_sha256": sha256_json(list(ledger.values())),
        }
    )
    return evidence, ledger


def require_execution_binding(
    path: Path,
    expected_hash: str,
    ledger: Mapping[str, Mapping[str, Any]],
    label: str,
) -> dict[str, Any]:
    relpath = canonical_path(path)
    item = ledger.get(relpath)
    observed = sha256_file(path)
    if not isinstance(item, Mapping) or item.get("sha256") != observed or observed != expected_hash:
        raise CalibrationError(f"{label} is not closed by the frozen execution release")
    return {
        "relpath": relpath,
        "sha256": observed,
        "bytes": path.stat().st_size,
        "validated": True,
    }


def validate_frozen_manifests(
    config: CalibrationConfig,
    execution_ledger: Mapping[str, Mapping[str, Any]],
) -> tuple[
    dict[str, dict[str, str]],
    dict[tuple[str, str], dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, Any],
]:
    fixed_paths = (
        (config.case_manifest, DEFAULT_CASE_MANIFEST, CASE_MANIFEST_SHA256, "case manifest"),
        (config.run_manifest, DEFAULT_RUN_MANIFEST, RUN_MANIFEST_SHA256, "run manifest"),
        (
            config.protocol_manifest,
            DEFAULT_PROTOCOL_MANIFEST,
            PROTOCOL_MANIFEST_SHA256,
            "protocol manifest",
        ),
    )
    evidence: dict[str, Any] = {}
    for path, canonical, digest, label in fixed_paths:
        if path.resolve() != canonical.resolve():
            raise CalibrationError(f"{label} must use canonical path")
        evidence[label.replace(" ", "_")] = require_execution_binding(
            path, digest, execution_ledger, label
        )
    case_fields, case_rows = read_csv_strict(config.case_manifest)
    required_case = {
        "schema_version", "case_id", "candidate_id", "family", "sequence",
        "sequence_sha256", "formal_eligible", "training_label_release_eligible",
        "docking_gold_release_eligible", "case_manifest_row_sha256",
    }
    if not required_case <= set(case_fields) or len(case_rows) != 47:
        raise CalibrationError("Frozen case manifest schema/cardinality mismatch")
    cases: dict[str, dict[str, str]] = {}
    for row in case_rows:
        case_id = row["case_id"]
        if (
            row["schema_version"] != "phase2_v3_p2_v1_3_dual47_case_manifest_v1"
            or row["candidate_id"] != case_id
            or case_id in cases
            or row["case_manifest_row_sha256"] != row_sha256(row, "case_manifest_row_sha256")
            or sha256_bytes(row["sequence"].encode("ascii")) != row["sequence_sha256"]
            or any(
                parse_bool(row[field], field)
                for field in (
                    "formal_eligible", "training_label_release_eligible",
                    "docking_gold_release_eligible",
                )
            )
        ):
            raise CalibrationError(f"Frozen case manifest row invalid: {case_id}")
        cases[case_id] = row

    run_fields, run_rows = read_csv_strict(config.run_manifest)
    required_run = {
        "schema_version", "protocol_id", "run_id", "case_id", "candidate_id",
        "family", "sequence_sha256", "receptor_id", "seed_role", "topoaa_iniseed",
        "rigidbody_iniseed", "rigidbody_seed_start", "rigidbody_seed_end",
        "rigidbody_sampling", "rigidbody_tolerance", "seletop_select",
        "flexref_tolerance", "emref_tolerance", "ncores", "fixed_top8_policy",
        "formal_eligible", "training_label_release_eligible",
        "docking_gold_release_eligible", "run_manifest_row_sha256",
    }
    if not required_run <= set(run_fields) or len(run_rows) != 94:
        raise CalibrationError("Frozen run manifest schema/cardinality mismatch")
    runs: dict[tuple[str, str], dict[str, str]] = {}
    for row in run_rows:
        case_id = row["case_id"]
        receptor = row["receptor_id"].upper()
        key = (case_id, receptor)
        case = cases.get(case_id)
        expected_seed = "917" if receptor == "8X6B" else "20917"
        if (
            row["schema_version"] != "phase2_v3_p2_v1_3_dual47_run_manifest_v1"
            or row["protocol_id"] != "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
            or receptor not in RECEPTORS
            or key in runs
            or case is None
            or row["candidate_id"] != case_id
            or row["family"] != case["family"]
            or row["sequence_sha256"] != case["sequence_sha256"]
            or row["seed_role"] != "main"
            or row["topoaa_iniseed"] != "917"
            or row["rigidbody_iniseed"] != expected_seed
            or row["rigidbody_sampling"] != "40"
            or row["rigidbody_tolerance"] != "5"
            or row["seletop_select"] != "10"
            or row["flexref_tolerance"] != "20"
            or row["emref_tolerance"] != "20"
            or row["ncores"] != "4"
            or row["fixed_top8_policy"] != "deferred_4_emref_score_order_no_backfill"
            or row["run_manifest_row_sha256"] != row_sha256(row, "run_manifest_row_sha256")
            or any(
                parse_bool(row[field], field)
                for field in (
                    "formal_eligible", "training_label_release_eligible",
                    "docking_gold_release_eligible",
                )
            )
        ):
            raise CalibrationError(f"Frozen run manifest row invalid: {key}")
        runs[key] = row
    if set(runs) != {(case_id, receptor) for case_id in cases for receptor in RECEPTORS}:
        raise CalibrationError("Frozen 94-run candidate/receptor closure failed")

    protocol_fields, protocol_rows = read_csv_strict(config.protocol_manifest)
    if len(protocol_rows) != 2 or "receptor_sha256" not in protocol_fields:
        raise CalibrationError("Frozen protocol manifest schema/cardinality mismatch")
    protocols: dict[str, dict[str, str]] = {}
    for row in protocol_rows:
        receptor = row["receptor_id"].upper()
        expected_seed = "917" if receptor == "8X6B" else "20917"
        if (
            receptor not in RECEPTORS
            or receptor in protocols
            or row["protocol_id"] != "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
            or row["rigidbody_iniseed"] != expected_seed
            or row["last_module"] != "4_emref"
            or row["haddock3_version_contract"] != "2025.11.0"
            or row["hotspot_count"] != "23"
        ):
            raise CalibrationError(f"Frozen protocol manifest row invalid: {receptor}")
        protocols[receptor] = row
    if set(protocols) != set(RECEPTORS):
        raise CalibrationError("Frozen two-receptor protocol closure failed")
    evidence["case_row_hash_chain"] = row_hash_chain(case_rows, "case_manifest_row_sha256")
    evidence["run_row_hash_chain"] = row_hash_chain(run_rows, "run_manifest_row_sha256")
    evidence["case_count"] = len(cases)
    evidence["run_count"] = len(runs)
    evidence["protocol_count"] = len(protocols)
    return cases, runs, protocols, evidence


REQUIRED_METRICS_FIELDS = {
    "schema_version", "protocol_id", "formal_eligible",
    "training_label_release_eligible", "docking_gold_release_eligible",
    "primary_native_metric_eligible", "native_only", "candidate_id", "family", "run_id",
    "generation_receptor", "native_rank", "selector_row_sha256",
    "aligned_pose_sha256", "reference_relpath", "reference_sha256",
    "native_hotspot_ref_column", "internal_contact_channel", "hotspot_weight_fraction",
    "total_occluding_residue_pair_count",
    "cdr1_occluding_residue_pair_count", "cdr2_occluding_residue_pair_count",
    "cdr3_occluding_residue_pair_count",
    "reference_pvrl2_record_inventory_json", "metrics_row_sha256",
}


def derive_features(row: Mapping[str, str]) -> dict[str, float | int]:
    h_value = parse_float(row.get("hotspot_weight_fraction"), "hotspot_weight_fraction")
    if not 0.0 <= h_value <= 1.0 + 1e-12:
        raise CalibrationError(f"H outside [0,1]: {h_value}")
    total = parse_int(
        row.get("total_occluding_residue_pair_count"),
        "total_occluding_residue_pair_count",
    )
    cdr = sum(
        parse_int(
            row.get(f"cdr{index}_occluding_residue_pair_count"),
            f"cdr{index}_occluding_residue_pair_count",
        )
        for index in (1, 2, 3)
    )
    if total == 0 and cdr != 0:
        raise CalibrationError("CDR occlusion is nonzero while total occlusion is zero")
    if cdr > total:
        raise CalibrationError("CDR occlusion exceeds total occlusion")
    return {
        "H": min(h_value, 1.0),
        "O": float(total),
        "O_raw": total,
        "O_log1p": math.log1p(total),
        "P": cdr / total if total else 0.0,
        "P_numerator": cdr,
    }


def validate_metrics_rows(
    fields: Sequence[str],
    rows: Sequence[dict[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    contract: CalibrationContract,
    selector_by_key: Mapping[tuple[str, str, int], Mapping[str, str]] | None = None,
    references: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    missing = sorted(REQUIRED_METRICS_FIELDS - set(fields))
    if missing:
        raise CalibrationError(f"Native metrics lack required fields: {missing}")
    if len(rows) != contract.metric_rows:
        raise CalibrationError(f"Expected {contract.metric_rows} metric rows, got {len(rows)}")
    if len(positive_cases) != contract.positive_case_count:
        raise CalibrationError("Positive anchor count mismatch")
    if len({item["family"] for item in positive_cases.values()}) != contract.positive_family_count:
        raise CalibrationError("Positive family count mismatch")
    if len(mutant_cases) != contract.control_case_count:
        raise CalibrationError("Control case count mismatch")
    expected_cases = set(positive_cases) | set(mutant_cases)
    if len(expected_cases) != contract.case_count:
        raise CalibrationError("Positive/control manifests do not close 47 cases")
    keys: set[tuple[str, str, int]] = set()
    run_ids: dict[tuple[str, str], str] = {}
    inventories: dict[str, set[str]] = defaultdict(set)
    rows_by_receptor: Counter[str] = Counter()
    reference_evidence: dict[str, dict[str, Any]] = {}
    strict_identity = selector_by_key is not None and references is not None
    if strict_identity:
        if set(references) != set(RECEPTORS):
            raise CalibrationError("Exactly two canonical native references are required")
        for receptor in RECEPTORS:
            canonical_reference = DEFAULT_REFERENCES[receptor].resolve()
            reference = references[receptor].resolve()
            if reference != canonical_reference or sha256_file(reference) != REFERENCE_SHA256[receptor]:
                raise CalibrationError(f"Frozen native reference drift: {receptor}")
            reference_evidence[receptor] = {
                "relpath": reference.relative_to(WORKSPACE_ROOT.parent).as_posix(),
                "sha256": REFERENCE_SHA256[receptor],
            }
    for row_number, row in enumerate(rows, start=2):
        if row.get("schema_version") != METRICS_SCHEMA_VERSION:
            raise CalibrationError(f"Metrics schema mismatch at row {row_number}")
        if row.get("protocol_id") != PROTOCOL_ID:
            raise CalibrationError(f"Protocol mismatch at row {row_number}")
        if any(
            parse_bool(row.get(field), field)
            for field in (
                "formal_eligible", "training_label_release_eligible",
                "docking_gold_release_eligible",
            )
        ):
            raise CalibrationError("Release-eligible processor input is forbidden")
        if parse_bool(row.get("primary_native_metric_eligible"), "primary_native_metric_eligible"):
            raise CalibrationError(
                "Pending processor rows must not self-authorize primary calibration input"
            )
        if not parse_bool(row.get("native_only"), "native_only"):
            raise CalibrationError("Processor metric row is not native_only=true")
        if row.get("metrics_row_sha256") != row_sha256(row, "metrics_row_sha256"):
            raise CalibrationError(f"metrics_row_sha256 mismatch at row {row_number}")
        case_id = row.get("candidate_id", "").strip()
        if case_id not in expected_cases:
            raise CalibrationError(f"Unknown candidate: {case_id!r}")
        expected_family = (
            positive_cases.get(case_id, mutant_cases.get(case_id, {})).get("family")
        )
        if row.get("family", "").strip() != expected_family:
            raise CalibrationError(f"Family mismatch for {case_id}")
        receptor = row.get("generation_receptor", "").strip().upper()
        if receptor not in RECEPTORS:
            raise CalibrationError(f"Unknown generation receptor: {receptor!r}")
        rank = parse_int(row.get("native_rank"), "native_rank", 1)
        if rank > contract.ranks_per_run:
            raise CalibrationError(f"Native rank exceeds K=8: {rank}")
        key = (case_id, receptor, rank)
        if key in keys:
            raise CalibrationError(f"Duplicate native metric key: {key}")
        keys.add(key)
        selector = selector_by_key.get(key) if selector_by_key is not None else None
        if strict_identity and selector is None:
            raise CalibrationError(f"Native metric row has no selector identity: {key}")
        run_id = row.get("run_id", "").strip()
        if not run_id:
            raise CalibrationError("Empty run_id")
        previous_run = run_ids.setdefault((case_id, receptor), run_id)
        if previous_run != run_id:
            raise CalibrationError(f"Run drift within {case_id}/{receptor}")
        if strict_identity and (
            run_id != selector["run_id"]
            or row["selector_row_sha256"] != selector["selection_row_sha256"]
            or row["family"] != selector["family"]
        ):
            raise CalibrationError(f"Metric/selector native identity mismatch: {key}")
        expected_reference = reference_evidence.get(receptor)
        if (
            (strict_identity and row["reference_relpath"] != expected_reference["relpath"])
            or (strict_identity and row["reference_sha256"] != expected_reference["sha256"])
            or not re.fullmatch(r"[0-9a-f]{64}", row["reference_sha256"])
            or not row["reference_relpath"].strip()
            or row["native_hotspot_ref_column"] != NATIVE_HOTSPOT_COLUMN[receptor]
            or row["internal_contact_channel"]
            != f"raw_4_emref_pose_{receptor.lower()}_native_numbering"
        ):
            raise CalibrationError(f"Generation/native reference identity mismatch: {key}")
        for hash_field in (
            "selector_row_sha256", "aligned_pose_sha256", "reference_sha256",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", row.get(hash_field, "")):
                raise CalibrationError(f"Invalid {hash_field} at row {row_number}")
        inventories[receptor].add(
            validate_atom_only_inventory(row["reference_pvrl2_record_inventory_json"])
        )
        derive_features(row)
        rows_by_receptor[receptor] += 1
    expected_keys = {
        (case_id, receptor, rank)
        for case_id in expected_cases
        for receptor in RECEPTORS
        for rank in range(1, contract.ranks_per_run + 1)
    }
    if keys != expected_keys:
        raise CalibrationError("47 x 2 x Top-8 native metric key closure failed")
    if len(run_ids) != contract.run_count or len(set(run_ids.values())) != contract.run_count:
        raise CalibrationError("94 unique native run IDs did not close")
    if any(len(inventories[receptor]) != 1 for receptor in RECEPTORS):
        raise CalibrationError("Native PVRL2 inventory drift within a receptor")
    return {
        "case_count": len(expected_cases),
        "run_count": len(run_ids),
        "metric_rows": len(rows),
        "rows_by_generation_receptor": dict(sorted(rows_by_receptor.items())),
        "positive_anchor_count": len(positive_cases),
        "positive_family_count": len({x["family"] for x in positive_cases.values()}),
        "control_case_count": len(mutant_cases),
        "native_rank_pairing_across_receptors": False,
        "native_only_validated": True,
        "generation_native_receptor_identity_validated": strict_identity,
        "metric_selector_identity_count": len(keys) if strict_identity else 0,
        "selector_identity_validation_mode": "strict_frozen" if strict_identity else "processor_compatibility_only",
        "atom_only_reference_inventory_gate_passed": True,
        "reference_inventory_sha256_by_receptor": {
            receptor: sha256_bytes(next(iter(inventories[receptor])).encode())
            for receptor in RECEPTORS
        },
        "reference_evidence": reference_evidence,
    }


def validate_processor_audit(
    path: Path,
    metrics_csv: Path,
    rows: Sequence[Mapping[str, str]],
    config: CalibrationConfig,
    selector_evidence: Mapping[str, Any],
    preregistration: Mapping[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        raise CalibrationError(f"Processor audit is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": PROCESSOR_AUDIT_SCHEMA_VERSION,
        "status": PROCESSOR_PENDING_STATUS,
        "protocol_id": PROTOCOL_ID,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "primary_native_metric_eligible": False,
        "native_only": True,
        "thresholds_applied": False,
        "discrete_geometry_outputs_emitted": False,
        "cross_reference_rows_emitted": False,
        "cross_receptor_rank_pairing_performed": False,
        "dual_candidate_score_outputs_emitted": False,
        "p2_training_ready": False,
    }
    failures = [field for field, value in expected.items() if payload.get(field) != value]
    observed = payload.get("observed_contract", {})
    for field, value in {
        "case_count": 47,
        "run_count": 94,
        "materialization_rows": 752,
        "metric_rows": 752,
        "contact_records": 752,
        "aligned_pose_files": 752,
        "rows_by_generation_receptor": {"8X6B": 376, "9E6Y": 376},
    }.items():
        if not isinstance(observed, dict) or observed.get(field) != value:
            failures.append(f"observed_contract.{field}")
    output = payload.get("output_sha256", {})
    metric_binding = output.get("continuous_metrics", {}) if isinstance(output, dict) else {}
    expected_metric = {
        "sha256": sha256_file(metrics_csv),
        "rows": len(rows),
        "row_hash_chain": newline_hash_chain(rows, "metrics_row_sha256"),
    }
    for field, value in expected_metric.items():
        if not isinstance(metric_binding, dict) or metric_binding.get(field) != value:
            failures.append(f"continuous_metrics.{field}")
    selector = payload.get("selector_contract", {})
    selector_expected = {
        "selector_csv_sha256": selector_evidence["selector_csv"]["sha256"],
        "publication_release_id": selector_evidence["publication_release_id"],
        "selector_audit_validated": True,
        "selection_row_hash_chain": selector_evidence["selector_csv"]["row_hash_chain"],
    }
    for field, value in selector_expected.items():
        if not isinstance(selector, dict) or selector.get(field) != value:
            failures.append(f"selector_contract.{field}")
    native_contract = payload.get("native_processing_contract", {})
    for field in (
        "raw_native_H_scored_once_per_pose", "native_PVRL2_reference_only",
        "9E6Y_direct_native_numbering", "canonical_hotspot_reconciliation_validated",
        "reference_PVRL2_protein_ATOM_only", "all_reference_HETATM_excluded",
    ):
        if not isinstance(native_contract, dict) or native_contract.get(field) is not True:
            failures.append(f"native_processing_contract.{field}")
    if not isinstance(native_contract, dict) or native_contract.get(
        "rank_pairing_across_receptors"
    ) is not False:
        failures.append("native_processing_contract.rank_pairing_across_receptors")
    input_hashes = payload.get("input_sha256", {})
    expected_inputs = {
        "selector_csv": selector_evidence["selector_csv"]["sha256"],
        "selector_audit": selector_evidence["selector_audit"]["sha256"],
        "selector_publication_release_id": selector_evidence["publication_release_id"],
        "execution_release_manifest": EXECUTION_RELEASE_SHA256,
        "run_manifest": RUN_MANIFEST_SHA256,
        "preregistration": preregistration["sha256"],
        "positive_manifest": POSITIVE_MANIFEST_SHA256,
        "mutant_manifest": MUTANT_MANIFEST_SHA256,
        "reference_8x6b": REFERENCE_SHA256["8X6B"],
        "reference_9e6y": REFERENCE_SHA256["9E6Y"],
    }
    for field, value in expected_inputs.items():
        if not isinstance(input_hashes, dict) or input_hashes.get(field) != value:
            failures.append(f"input_sha256.{field}")
    publication_contract = payload.get("publication_contract", {})
    if (
        not isinstance(publication_contract, dict)
        or publication_contract.get("immutable_versioned_release") is not True
        or publication_contract.get("atomic_current_symlink_replacement") is not True
        or publication_contract.get("rollback_safe") is not True
        or not str(publication_contract.get("release_id", "")).startswith("native-")
        or publication_contract.get("release_relpath")
        != f"releases/{publication_contract.get('release_id', '')}"
        or publication_contract.get("current_pointer_relpath") != "current"
    ):
        failures.append("publication_contract")
    expected_contract = payload.get("expected_contract", {})
    if not isinstance(expected_contract, dict) or any(
        expected_contract.get(field) != value
        for field, value in {
            "positive_cases": 11, "mutant_cases": 36, "case_count": 47,
            "run_count": 94, "pose_count": 752, "poses_per_run": 8,
        }.items()
    ):
        failures.append("expected_contract")
    release_state = payload.get("development_release_state", {})
    if (
        not isinstance(release_state, dict)
        or release_state.get("status") != "NOT_EVALUATED_BY_PROCESSOR_BUILDER"
        or release_state.get("independent_qualification_required") is not True
        or release_state.get("validated") is not False
    ):
        failures.append("development_release_state")
    if failures:
        raise CalibrationError(f"Processor audit closure failed: {sorted(failures)}")
    return {
        "relpath": canonical_path(path),
        "sha256": sha256_file(path),
        "schema_version": payload["schema_version"],
        "status": payload["status"],
        "native_only": True,
        "selector_publication_release_id": selector_evidence["publication_release_id"],
        "processor_release_id": publication_contract.get("release_id", ""),
        "metric_row_hash_chain": expected_metric["row_hash_chain"],
        "validated": True,
    }


def validate_processor_qualification(
    path: Path,
    config: CalibrationConfig,
    processor_audit: Mapping[str, Any],
    metric_rows: Sequence[Mapping[str, str]],
    selector_evidence: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    execution_release: Mapping[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        raise CalibrationError(f"Independent processor qualification is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_scalars = {
        "schema_version": PROCESSOR_QUALIFICATION_SCHEMA,
        "status": PROCESSOR_QUALIFICATION_STATUS,
        "protocol_id": PROTOCOL_ID,
        "calibration_input_eligible": True,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
        "native_only": True,
    }
    failures = [
        field for field, expected in expected_scalars.items()
        if payload.get(field) != expected
    ]
    qualified = payload.get("qualified_input", {})
    expected_qualified = {
        "processor_audit_sha256": processor_audit["sha256"],
        "continuous_metrics_sha256": sha256_file(config.metrics_csv),
        "continuous_metrics_row_hash_chain": newline_hash_chain(
            metric_rows, "metrics_row_sha256"
        ),
        "selector_csv_sha256": selector_evidence["selector_csv"]["sha256"],
        "selector_audit_sha256": selector_evidence["selector_audit"]["sha256"],
        "selector_publication_release_id": selector_evidence["publication_release_id"],
        "preregistration_sha256": preregistration["sha256"],
        "execution_release_sha256": execution_release["sha256"],
        "positive_manifest_sha256": POSITIVE_MANIFEST_SHA256,
        "mutant_manifest_sha256": MUTANT_MANIFEST_SHA256,
        "case_manifest_sha256": CASE_MANIFEST_SHA256,
        "run_manifest_sha256": RUN_MANIFEST_SHA256,
        "protocol_manifest_sha256": PROTOCOL_MANIFEST_SHA256,
        "reference_sha256": dict(REFERENCE_SHA256),
        "processor_sha256": sha256_file(DEFAULT_PROCESSOR_IMPLEMENTATION),
        "processor_test_sha256": sha256_file(DEFAULT_PROCESSOR_TEST),
        "validator_sha256": sha256_file(DEFAULT_PROCESSOR_QUALIFICATION_VALIDATOR),
        "validator_test_sha256": sha256_file(DEFAULT_PROCESSOR_QUALIFICATION_TEST),
    }
    for field, expected in expected_qualified.items():
        if not isinstance(qualified, dict) or qualified.get(field) != expected:
            failures.append(f"qualified_input.{field}")
    determinism = payload.get("determinism", {})
    expected_determinism = {
        "independent_publication_count": 2,
        "full_inventory_equal": True,
        "core_output_hashes_equal": True,
        "content_addressed_release_id_equal": True,
    }
    for field, expected in expected_determinism.items():
        if not isinstance(determinism, dict) or determinism.get(field) != expected:
            failures.append(f"determinism.{field}")
    if not isinstance(determinism, dict) or any(
        not re.fullmatch(r"[0-9a-f]{64}", str(determinism.get(field, "")))
        for field in (
            "primary_inventory_sha256", "rebuild_inventory_sha256",
            "primary_processor_audit_sha256", "rebuild_processor_audit_sha256",
        )
    ) or not str(determinism.get("release_id", "")).startswith("native-"):
        failures.append("determinism.hash_or_release_identity")
    publication = payload.get("publication", {})
    source_releases = payload.get("source_pending_releases", {})
    primary_source = source_releases.get("primary", {}) if isinstance(source_releases, dict) else {}
    rebuild_source = source_releases.get("rebuild", {}) if isinstance(source_releases, dict) else {}
    if (
        not isinstance(primary_source, dict)
        or not isinstance(rebuild_source, dict)
        or not primary_source.get("audit_path")
        or not rebuild_source.get("audit_path")
        or primary_source.get("audit_path") == rebuild_source.get("audit_path")
        or primary_source.get("audit_sha256")
        != determinism.get("primary_processor_audit_sha256")
        or rebuild_source.get("audit_sha256")
        != determinism.get("rebuild_processor_audit_sha256")
        or primary_source.get("release_id") != rebuild_source.get("release_id")
        or primary_source.get("release_id") != determinism.get("release_id")
    ):
        failures.append("source_pending_releases")
    if (
        not isinstance(publication, dict)
        or not str(publication.get("release_id", "")).strip()
        or publication.get("immutable_versioned_release") is not True
        or publication.get("atomic_current_symlink_replacement") is not True
        or publication.get("current_pointer_relpath") != "current"
        or publication.get("release_relpath")
        != f"releases/{publication.get('release_id', '')}"
    ):
        failures.append("publication")
    if failures:
        raise CalibrationError(
            f"Independent processor qualification closure failed: {sorted(failures)}"
        )
    return {
        "relpath": canonical_path(path),
        "sha256": sha256_file(path),
        "schema_version": payload["schema_version"],
        "status": payload["status"],
        "calibration_input_eligible": True,
        "deterministic_publication_count": 2,
        "publication_release_id": publication["release_id"],
        "validated": True,
    }


def family_case_index(
    rows: Sequence[Mapping[str, str]], positive_cases: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, list[Mapping[str, str]]]]:
    index: dict[str, dict[str, list[Mapping[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        case_id = row["candidate_id"]
        if case_id in positive_cases:
            index[positive_cases[case_id]["family"]][case_id].append(row)
    return {family: dict(cases) for family, cases in index.items()}


def threshold_fit_diagnostic(
    values: Sequence[tuple[float, float]],
    lower_quantile: float,
    upper_quantile: float,
    *,
    metric: str,
) -> dict[str, Any]:
    total_weight = sum(weight for _, weight in values)
    positive = [(value, weight) for value, weight in values if value > 0.0 and weight > 0.0]
    positive_weight = sum(weight for _, weight in positive)
    transform = "log1p" if metric == "O" else "identity"
    raw_unit = "residue_pair_count" if metric == "O" else "unitless_fraction"
    lower = weighted_quantile(positive, lower_quantile) if positive else None
    upper = weighted_quantile(positive, upper_quantile) if positive else None
    failure_reason = ""
    if total_weight <= 0.0 or positive_weight <= 0.0:
        failure_reason = "no_positive_anchor_support"
    elif lower is None or upper is None or not math.isfinite(lower) or not math.isfinite(upper):
        failure_reason = "non_finite_cutpoint"
    elif lower <= 0.0:
        failure_reason = "non_positive_lower_cutpoint"
    elif upper <= lower:
        failure_reason = "upper_cutpoint_not_strictly_greater_than_lower"
    lower_transformed = (
        math.log1p(lower) if lower is not None and metric == "O" else lower
    )
    upper_transformed = (
        math.log1p(upper) if upper is not None and metric == "O" else upper
    )
    return {
        "L": lower,
        "U": upper,
        "L_raw": lower,
        "U_raw": upper,
        "L_transformed": lower_transformed,
        "U_transformed": upper_transformed,
        "raw_unit": raw_unit,
        "transform": transform,
        "lower_quantile": lower_quantile,
        "upper_quantile": upper_quantile,
        "positive_part_only": True,
        "zero_hurdle": 0.0,
        "positive_support_count": len(positive),
        "positive_weight": positive_weight / total_weight if total_weight > 0.0 else 0.0,
        "zero_weight": 1.0 - positive_weight / total_weight if total_weight > 0.0 else 1.0,
        "defined": not failure_reason,
        "failure_reason": failure_reason,
    }


def anchor_metric_values(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    ranks_per_run: int,
) -> dict[str, Any]:
    index = family_case_index(rows, positive_cases)
    families = sorted(index)
    if not families:
        raise CalibrationError("Threshold fit has no positive families")
    q_rank = normalized_rank_weights(ranks_per_run)
    values: dict[str, Any] = {
        "pooled_H": [],
        "receptor": {
            receptor: {"O": [], "P": []} for receptor in RECEPTORS
        },
    }
    for family in families:
        cases = index[family]
        if not cases:
            raise CalibrationError(f"Positive family {family} has no anchor")
        for case_id, case_rows in sorted(cases.items()):
            by_key = {
                (row["generation_receptor"].upper(), int(row["native_rank"])): row
                for row in case_rows
            }
            for receptor in RECEPTORS:
                for rank in range(1, ranks_per_run + 1):
                    key = (receptor, rank)
                    if key not in by_key:
                        raise CalibrationError(f"Anchor lacks {case_id}/{receptor}/rank{rank}")
                    features = derive_features(by_key[key])
                    receptor_weight = (1.0 / len(families)) * (1.0 / len(cases)) * q_rank[rank]
                    values["receptor"][receptor]["O"].append(
                        (float(features["O"]), receptor_weight)
                    )
                    values["receptor"][receptor]["P"].append(
                        (float(features["P"]), receptor_weight)
                    )
                    values["pooled_H"].append(
                        (float(features["H"]), 0.5 * receptor_weight)
                    )
    return values


def derive_rules(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    ranks_per_run: int,
    *,
    lower_quantile: float = LOWER_QUANTILE,
    upper_quantile: float = UPPER_QUANTILE,
) -> dict[str, Any]:
    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise CalibrationError("Threshold quantiles must satisfy 0<=qL<qU<=1")
    values = anchor_metric_values(rows, positive_cases, ranks_per_run)
    fits = {
        "pooled_H": threshold_fit_diagnostic(
            values["pooled_H"], lower_quantile, upper_quantile, metric="H"
        ),
        "receptor": {
            receptor: {
                metric: threshold_fit_diagnostic(
                    values["receptor"][receptor][metric],
                    lower_quantile,
                    upper_quantile,
                    metric=metric,
                )
                for metric in ("O", "P")
            }
            for receptor in RECEPTORS
        },
    }
    channels = [fits["pooled_H"]]
    channels.extend(
        fits["receptor"][receptor][metric]
        for receptor in RECEPTORS
        for metric in ("O", "P")
    )
    invalid = [item["failure_reason"] for item in channels if not item["defined"]]
    if invalid:
        raise CalibrationError(f"Five-channel threshold fit is undefined: {invalid}")
    return {
        "thresholds": fits,
        "primary_channel_count": 5,
        "channel_order": [
            "canonical_pooled_H", "8X6B_native_O", "8X6B_native_P",
            "9E6Y_native_O", "9E6Y_native_P",
        ],
        "positive_family_count": len({x["family"] for x in positive_cases.values()}),
        "positive_case_count": len(positive_cases),
        "family_weighting": "equal_family_then_equal_case_within_family",
        "pooled_H_receptor_weighting": "one_half_per_receptor",
        "rank_weights": normalized_rank_weights(ranks_per_run),
        "cross_reference_threshold_fit": False,
        "receptor_specific_H_thresholds": False,
        "rank_pairing_across_receptors": False,
    }


def membership(value: float, threshold: Mapping[str, Any]) -> float:
    if not math.isfinite(value):
        raise CalibrationError("Membership received non-finite value")
    lower_raw = float(threshold["L_raw"])
    upper_raw = float(threshold["U_raw"])
    lower = float(threshold["L_transformed"])
    upper = float(threshold["U_transformed"])
    if value <= 0.0 or value < lower_raw:
        return 0.0
    if upper <= lower or upper_raw <= lower_raw:
        raise CalibrationError("Membership requires strict U>L")
    transformed = math.log1p(value) if threshold["transform"] == "log1p" else value
    if value >= upper_raw:
        return 1.0
    return max(0.0, min(1.0, (transformed - lower) / (upper - lower)))


def classify_pose(
    features: Mapping[str, float | int], rules: Mapping[str, Any], receptor: str
) -> tuple[str, float, dict[str, float]]:
    if receptor not in RECEPTORS:
        raise CalibrationError(f"Unknown receptor for classification: {receptor}")
    h_threshold = rules["thresholds"]["pooled_H"]
    receptor_thresholds = rules["thresholds"]["receptor"][receptor]
    h_value = float(features["H"])
    o_value = float(features["O"])
    p_value = float(features["P"])
    memberships = {
        "H": membership(h_value, h_threshold),
        "O": membership(o_value, receptor_thresholds["O"]),
        "P": membership(p_value, receptor_thresholds["P"]),
    }
    score = math.sqrt(memberships["O"] * (memberships["H"] + memberships["P"]) / 2.0)
    if (
        o_value >= receptor_thresholds["O"]["U_raw"]
        and h_value >= h_threshold["U_raw"]
        and p_value >= receptor_thresholds["P"]["L_raw"]
    ):
        pose_class = "A"
    elif (
        o_value >= receptor_thresholds["O"]["L_raw"]
        and (
            h_value >= h_threshold["L_raw"]
            or p_value >= receptor_thresholds["P"]["L_raw"]
        )
    ):
        pose_class = "B"
    elif h_value >= h_threshold["L_raw"] and o_value < receptor_thresholds["O"]["L_raw"]:
        pose_class = "C"
    else:
        pose_class = "E"
    return pose_class, score, memberships


POSE_SCORE_FIELDS = (
    "schema_version", "protocol_id", "method_id", "formal_eligible",
    "docking_gold_release_eligible", "training_label_release_eligible",
    "candidate_id", "family", "run_id", "generation_receptor", "native_rank",
    "input_metrics_row_sha256", "H_hotspot_weight_fraction",
    "O_total_occluding_residue_pair_count_raw", "O_log1p_once",
    "P_cdr_residue_pair_fraction", "P_cdr_residue_pair_count",
    "mu_H", "mu_O", "mu_P", "S_native_pose", "native_pose_class",
    "native_pose_relevance_strength", "input_native_only",
    "native_reference_sha256", "claim_boundary",
    "pose_score_row_sha256",
)


def score_pose_rows(
    rows: Sequence[Mapping[str, str]], rules: Mapping[str, Any]
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            item["candidate_id"], RECEPTORS.index(item["generation_receptor"].upper()),
            int(item["native_rank"]),
        ),
    ):
        receptor = row["generation_receptor"].upper()
        features = derive_features(row)
        pose_class, score, memberships = classify_pose(features, rules, receptor)
        record = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "candidate_id": row["candidate_id"],
            "family": row["family"],
            "run_id": row["run_id"],
            "generation_receptor": receptor,
            "native_rank": int(row["native_rank"]),
            "input_metrics_row_sha256": row["metrics_row_sha256"],
            "H_hotspot_weight_fraction": float(features["H"]),
            "O_total_occluding_residue_pair_count_raw": int(features["O_raw"]),
            "O_log1p_once": float(features["O_log1p"]),
            "P_cdr_residue_pair_fraction": float(features["P"]),
            "P_cdr_residue_pair_count": int(features["P_numerator"]),
            "mu_H": memberships["H"],
            "mu_O": memberships["O"],
            "mu_P": memberships["P"],
            "S_native_pose": score,
            "native_pose_class": pose_class,
            "native_pose_relevance_strength": CLASS_RELEVANCE[pose_class],
            "input_native_only": row["native_only"],
            "native_reference_sha256": row["reference_sha256"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        output.append(normalize_record(record, POSE_SCORE_FIELDS, "pose_score_row_sha256"))
    return output


RUN_SCORE_FIELDS = (
    "schema_version", "protocol_id", "method_id", "formal_eligible",
    "docking_gold_release_eligible", "training_label_release_eligible",
    "candidate_id", "family", "case_source", "run_id", "generation_receptor",
    "R_native", "native_run_class", "native_run_relevance_strength",
    "assigned_support_fraction", "assigned_supporting_pose_count",
    "F_A", "N_A", "F_B", "N_B", "F_C", "N_C",
    "support_fraction_threshold", "minimum_supporting_poses",
    "native_rank_count", "cross_receptor_rank_pairing", "claim_boundary",
    "run_score_row_sha256",
)


def aggregate_native_runs(
    pose_rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    *,
    support_fraction: float = SUPPORT_FRACTION,
    min_supporting_poses: int = MIN_SUPPORTING_POSES,
) -> list[dict[str, str]]:
    if not 0.0 < support_fraction <= 1.0:
        raise CalibrationError("Support fraction must be in (0,1]")
    if min_supporting_poses < 1:
        raise CalibrationError("Minimum supporting poses must be positive")
    by_run: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in pose_rows:
        by_run[(row["candidate_id"], row["generation_receptor"])].append(row)
    q_rank = normalized_rank_weights(8)
    output: list[dict[str, str]] = []
    for (case_id, receptor), run_poses in sorted(
        by_run.items(), key=lambda item: (item[0][0], RECEPTORS.index(item[0][1]))
    ):
        if receptor not in RECEPTORS:
            raise CalibrationError(f"Unknown run receptor: {receptor}")
        ranks = [int(row["native_rank"]) for row in run_poses]
        if sorted(ranks) != list(range(1, 9)) or len({row["run_id"] for row in run_poses}) != 1:
            raise CalibrationError(f"Native Top-8 run closure failed for {case_id}/{receptor}")
        by_rank = {int(row["native_rank"]): row for row in run_poses}
        run_score = sum(
            q_rank[rank] * float(by_rank[rank]["S_native_pose"])
            for rank in range(1, 9)
        )
        supports: dict[str, tuple[float, int]] = {}
        allowed = {
            "A": {"A"},
            "B": {"A", "B"},
            "C": {"A", "B", "C"},
        }
        for level, classes in allowed.items():
            supporting = [
                rank
                for rank in range(1, 9)
                if by_rank[rank]["native_pose_class"] in classes
            ]
            supports[level] = (sum(q_rank[rank] for rank in supporting), len(supporting))
        run_class = "E"
        for level in ("A", "B", "C"):
            weight, count = supports[level]
            if weight + 1e-15 >= support_fraction and count >= min_supporting_poses:
                run_class = level
                break
        assigned_weight, assigned_count = supports.get(run_class, (0.0, 0))
        first = run_poses[0]
        record = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "candidate_id": case_id,
            "family": first["family"],
            "case_source": "positive_anchor" if case_id in positive_cases else "control_or_perturbation",
            "run_id": first["run_id"],
            "generation_receptor": receptor,
            "R_native": run_score,
            "native_run_class": run_class,
            "native_run_relevance_strength": CLASS_RELEVANCE[run_class],
            "assigned_support_fraction": assigned_weight,
            "assigned_supporting_pose_count": assigned_count,
            "F_A": supports["A"][0],
            "N_A": supports["A"][1],
            "F_B": supports["B"][0],
            "N_B": supports["B"][1],
            "F_C": supports["C"][0],
            "N_C": supports["C"][1],
            "support_fraction_threshold": support_fraction,
            "minimum_supporting_poses": min_supporting_poses,
            "native_rank_count": 8,
            "cross_receptor_rank_pairing": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        output.append(normalize_record(record, RUN_SCORE_FIELDS, "run_score_row_sha256"))
    return output


def dual_tier(class_8x6b: str, class_9e6y: str) -> str:
    if class_8x6b not in POSE_CLASSES or class_9e6y not in POSE_CLASSES:
        raise CalibrationError(f"Invalid native class pair: {class_8x6b}/{class_9e6y}")
    if "E" in {class_8x6b, class_9e6y}:
        return "G5"
    if class_8x6b == class_9e6y == "A":
        return "G1"
    if {class_8x6b, class_9e6y} == {"A", "B"}:
        return "G2"
    if class_8x6b == class_9e6y == "B":
        return "G3"
    if "C" in {class_8x6b, class_9e6y}:
        return "G4"
    raise CalibrationError(f"Unmapped dual class pair: {class_8x6b}/{class_9e6y}")


DUAL_SCORE_FIELDS = (
    "schema_version", "protocol_id", "method_id", "formal_eligible",
    "docking_gold_release_eligible", "training_label_release_eligible",
    "candidate_id", "family", "case_source", "run_id_8X6B", "run_id_9E6Y",
    "R_8X6B", "R_9E6Y", "R_dual_dev", "R_dual_min", "R_dual_max", "R_dual_gap",
    "native_class_8X6B", "native_class_9E6Y", "dual_tier",
    "F_dual_A", "N_dual_A", "F_dual_B", "N_dual_B", "F_dual_C", "N_dual_C",
    "assigned_tier_support_fraction", "assigned_tier_supporting_pose_count",
    "support_fraction_threshold", "minimum_supporting_poses",
    "candidate_level_join_only", "cross_receptor_rank_pairing", "R_gold_name_used",
    "claim_boundary", "dual_score_row_sha256",
)


def aggregate_dual_candidates(
    run_rows: Sequence[Mapping[str, str]],
    *,
    support_fraction: float = SUPPORT_FRACTION,
    min_supporting_poses: int = MIN_SUPPORTING_POSES,
) -> list[dict[str, str]]:
    by_case: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in run_rows:
        by_case[row["candidate_id"]].append(row)
    output: list[dict[str, str]] = []
    for case_id, case_runs in sorted(by_case.items()):
        by_receptor = {row["generation_receptor"]: row for row in case_runs}
        if len(case_runs) != 2 or set(by_receptor) != set(RECEPTORS):
            raise CalibrationError(f"Candidate-level dual join lacks two native runs: {case_id}")
        left, right = by_receptor["8X6B"], by_receptor["9E6Y"]
        if left["family"] != right["family"]:
            raise CalibrationError(f"Family drift across receptors for {case_id}")
        class_left = left["native_run_class"]
        class_right = right["native_run_class"]
        tier = dual_tier(class_left, class_right)
        score_left = float(left["R_native"])
        score_right = float(right["R_native"])
        common_support = {
            level: (
                min(float(left[f"F_{level}"]), float(right[f"F_{level}"])),
                min(int(left[f"N_{level}"]), int(right[f"N_{level}"])),
            )
            for level in ("A", "B", "C")
        }
        if tier == "G5":
            assigned_weight, assigned_count = 0.0, 0
        else:
            left_weight = float(left[f"F_{class_left}"])
            right_weight = float(right[f"F_{class_right}"])
            left_count = int(left[f"N_{class_left}"])
            right_count = int(right[f"N_{class_right}"])
            assigned_weight = min(left_weight, right_weight)
            assigned_count = min(left_count, right_count)
            if (
                assigned_weight + 1e-15 < support_fraction
                or assigned_count < min_supporting_poses
            ):
                raise CalibrationError(
                    f"Assigned support is invalid for non-E dual tier {case_id}/{tier}"
                )
        record = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "candidate_id": case_id,
            "family": left["family"],
            "case_source": left["case_source"],
            "run_id_8X6B": left["run_id"],
            "run_id_9E6Y": right["run_id"],
            "R_8X6B": score_left,
            "R_9E6Y": score_right,
            "R_dual_dev": (score_left + score_right) / 2.0,
            "R_dual_min": min(score_left, score_right),
            "R_dual_max": max(score_left, score_right),
            "R_dual_gap": abs(score_left - score_right),
            "native_class_8X6B": class_left,
            "native_class_9E6Y": class_right,
            "dual_tier": tier,
            "F_dual_A": common_support["A"][0],
            "N_dual_A": common_support["A"][1],
            "F_dual_B": common_support["B"][0],
            "N_dual_B": common_support["B"][1],
            "F_dual_C": common_support["C"][0],
            "N_dual_C": common_support["C"][1],
            "assigned_tier_support_fraction": assigned_weight,
            "assigned_tier_supporting_pose_count": assigned_count,
            "support_fraction_threshold": support_fraction,
            "minimum_supporting_poses": min_supporting_poses,
            "candidate_level_join_only": True,
            "cross_receptor_rank_pairing": False,
            "R_gold_name_used": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        output.append(normalize_record(record, DUAL_SCORE_FIELDS, "dual_score_row_sha256"))
    return output


LOFO_FIELDS = (
    "schema_version", "protocol_id", "method_id", "held_out_family",
    "held_out_candidate_id", "training_family_count", "training_case_count",
    "fold_defined", "failure_reason", "lofo_rules_sha256", "R_8X6B", "R_9E6Y",
    "R_dual_dev", "all_family_dual_tier", "held_out_dual_tier",
    "absolute_dual_tier_shift", "held_out_G1_G3_retained",
    "native_class_8X6B", "native_class_9E6Y", "formal_eligible",
    "docking_gold_release_eligible", "training_label_release_eligible",
    "lofo_row_sha256",
)


def build_lofo_rows(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    all_family_dual_rows: Sequence[Mapping[str, str]],
    ranks_per_run: int,
) -> list[dict[str, str]]:
    families = sorted({record["family"] for record in positive_cases.values()})
    all_tier = {
        row["candidate_id"]: row["dual_tier"]
        for row in all_family_dual_rows
        if row["candidate_id"] in positive_cases
    }
    if set(all_tier) != set(positive_cases):
        raise CalibrationError("Central anchor dual-tier closure failed before LOFO")
    output: list[dict[str, str]] = []
    for held_out in families:
        train_cases = {
            case_id: record
            for case_id, record in positive_cases.items()
            if record["family"] != held_out
        }
        test_cases = {
            case_id: record
            for case_id, record in positive_cases.items()
            if record["family"] == held_out
        }
        failure_reason = ""
        rules_hash = ""
        dual_by_case: dict[str, Mapping[str, str]] = {}
        try:
            rules = derive_rules(rows, train_cases, ranks_per_run)
            rules_hash = sha256_json(rules)
            held_rows = [row for row in rows if row["candidate_id"] in test_cases]
            held_pose = score_pose_rows(held_rows, rules)
            held_runs = aggregate_native_runs(held_pose, test_cases)
            dual_by_case = {
                row["candidate_id"]: row for row in aggregate_dual_candidates(held_runs)
            }
        except CalibrationError as error:
            failure_reason = str(error)
        for case_id in sorted(test_cases):
            dual = dual_by_case.get(case_id)
            defined = dual is not None
            held_tier = dual["dual_tier"] if dual else ""
            shift = (
                abs(DUAL_TIER_STRENGTH[held_tier] - DUAL_TIER_STRENGTH[all_tier[case_id]])
                if dual else None
            )
            record = {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "method_id": METHOD_ID,
                "held_out_family": held_out,
                "held_out_candidate_id": case_id,
                "training_family_count": len(families) - 1,
                "training_case_count": len(train_cases),
                "fold_defined": defined,
                "failure_reason": "" if defined else failure_reason,
                "lofo_rules_sha256": rules_hash,
                "R_8X6B": dual["R_8X6B"] if dual else "",
                "R_9E6Y": dual["R_9E6Y"] if dual else "",
                "R_dual_dev": dual["R_dual_dev"] if dual else "",
                "all_family_dual_tier": all_tier[case_id],
                "held_out_dual_tier": held_tier,
                "absolute_dual_tier_shift": shift,
                "held_out_G1_G3_retained": held_tier in {"G1", "G2", "G3"},
                "native_class_8X6B": dual["native_class_8X6B"] if dual else "",
                "native_class_9E6Y": dual["native_class_9E6Y"] if dual else "",
                "formal_eligible": False,
                "docking_gold_release_eligible": False,
                "training_label_release_eligible": False,
            }
            output.append(normalize_record(record, LOFO_FIELDS, "lofo_row_sha256"))
    if len(output) != 11:
        raise CalibrationError(f"Expected 11 LOFO anchor rows, found {len(output)}")
    return sorted(output, key=lambda row: (row["held_out_family"], row["held_out_candidate_id"]))


def summarize_lofo(
    rows: Sequence[Mapping[str, str]], positive_cases: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    by_family: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        by_family[row["held_out_family"]].append(row)
    expected_families = {item["family"] for item in positive_cases.values()}
    family_summary: dict[str, Any] = {}
    recalls: list[float] = []
    for family in sorted(expected_families):
        family_rows = by_family.get(family, [])
        retained = sum(row["held_out_G1_G3_retained"] == "true" for row in family_rows)
        recall = retained / len(family_rows) if family_rows else 0.0
        recalls.append(recall)
        family_summary[family] = {
            "anchor_count": len(family_rows),
            "G1_G3_retained_count": retained,
            "G1_G3_recall": recall,
            "at_least_one_G1_G3": retained >= 1,
            "fold_defined": bool(family_rows) and all(
                row["fold_defined"] == "true" for row in family_rows
            ),
        }
    shifts = [
        int(row["absolute_dual_tier_shift"])
        for row in rows
        if row["fold_defined"] == "true"
    ]
    macro_recall = sum(recalls) / len(recalls) if recalls else 0.0
    summary = {
        "fold_count": len(by_family),
        "anchor_row_count": len(rows),
        "families": family_summary,
        "all_folds_defined": set(by_family) == expected_families and len(shifts) == 11,
        "each_family_at_least_one_G1_G3": all(
            item["at_least_one_G1_G3"] for item in family_summary.values()
        ),
        "macro_family_G1_G3_recall": macro_recall,
        "macro_recall_gate_passed": macro_recall >= 0.80,
        "tier_shift_le_one_count": sum(shift <= 1 for shift in shifts),
        "tier_shift_le_one_gate_passed": len(shifts) == 11 and sum(shift <= 1 for shift in shifts) >= 9,
        "maximum_absolute_tier_shift": max(shifts) if shifts else None,
        "maximum_shift_gate_passed": bool(shifts) and max(shifts) <= 2,
    }
    summary["passed"] = all(
        summary[field]
        for field in (
            "all_folds_defined", "each_family_at_least_one_G1_G3",
            "macro_recall_gate_passed", "tier_shift_le_one_gate_passed",
            "maximum_shift_gate_passed",
        )
    )
    return summary


BOOTSTRAP_THRESHOLD_FIELDS = (
    "schema_version", "protocol_id", "method_id", "bootstrap_seed",
    "bootstrap_replicate", "replicate_defined", "channel", "receptor", "metric",
    "cutpoint", "metric_defined", "value_raw", "value_transformed", "raw_unit",
    "transform", "failure_reason", "formal_eligible",
    "docking_gold_release_eligible", "training_label_release_eligible",
    "bootstrap_threshold_row_sha256",
)

BOOTSTRAP_RECEPTOR_FIELDS = (
    "schema_version", "protocol_id", "method_id", "bootstrap_seed",
    "bootstrap_replicate", "evaluation_defined", "failure_reason", "candidate_id",
    "family", "generation_receptor", "R_native", "native_run_class",
    "native_run_relevance_strength", "assigned_support_fraction",
    "assigned_supporting_pose_count", "F_A", "N_A", "F_B", "N_B", "F_C", "N_C",
    "formal_eligible", "docking_gold_release_eligible",
    "training_label_release_eligible", "bootstrap_receptor_row_sha256",
)

BOOTSTRAP_DUAL_FIELDS = (
    "schema_version", "protocol_id", "method_id", "bootstrap_seed",
    "bootstrap_replicate", "evaluation_defined", "failure_reason", "candidate_id",
    "family", "R_8X6B", "R_9E6Y", "R_dual_dev", "R_dual_gap",
    "native_class_8X6B", "native_class_9E6Y", "dual_tier",
    "assigned_tier_support_fraction", "assigned_tier_supporting_pose_count",
    "class_ordinal_gap", "both_native_non_E", "cross_receptor_rank_pairing",
    "formal_eligible", "docking_gold_release_eligible",
    "training_label_release_eligible", "bootstrap_dual_row_sha256",
)


def sampled_anchor_values(
    index: Mapping[str, Mapping[str, Sequence[Mapping[str, str]]]],
    ranks_per_run: int,
    rng: random.Random,
) -> dict[str, Any]:
    families = sorted(index)
    q_rank = normalized_rank_weights(ranks_per_run)
    values: dict[str, Any] = {
        "pooled_H": [],
        "receptor": {receptor: {"O": [], "P": []} for receptor in RECEPTORS},
    }
    for family in [rng.choice(families) for _ in families]:
        family_cases = sorted(index[family])
        for case_id in [rng.choice(family_cases) for _ in family_cases]:
            by_key = {
                (row["generation_receptor"].upper(), int(row["native_rank"])): row
                for row in index[family][case_id]
            }
            for receptor in RECEPTORS:
                for rank in range(1, ranks_per_run + 1):
                    features = derive_features(by_key[(receptor, rank)])
                    receptor_weight = (
                        (1.0 / len(families))
                        * (1.0 / len(family_cases))
                        * q_rank[rank]
                    )
                    for metric in ("O", "P"):
                        values["receptor"][receptor][metric].append(
                            (float(features[metric]), receptor_weight)
                        )
                    values["pooled_H"].append(
                        (float(features["H"]), 0.5 * receptor_weight)
                    )
    return values


def diagnostic_rules_from_values(
    values: Mapping[str, Any], lower_quantile: float, upper_quantile: float
) -> tuple[dict[str, Any], list[tuple[str, str, str, dict[str, Any]]]]:
    pooled_h = threshold_fit_diagnostic(
        values["pooled_H"], lower_quantile, upper_quantile, metric="H"
    )
    receptor_fits = {
        receptor: {
            metric: threshold_fit_diagnostic(
                values["receptor"][receptor][metric],
                lower_quantile,
                upper_quantile,
                metric=metric,
            )
            for metric in ("O", "P")
        }
        for receptor in RECEPTORS
    }
    channels = [("canonical_pooled_H", "", "H", pooled_h)]
    channels.extend(
        (f"{receptor}_native_{metric}", receptor, metric, receptor_fits[receptor][metric])
        for receptor in RECEPTORS
        for metric in ("O", "P")
    )
    rules = {
        "thresholds": {"pooled_H": pooled_h, "receptor": receptor_fits},
        "primary_channel_count": 5,
        "rank_pairing_across_receptors": False,
    }
    return rules, channels


def hierarchical_bootstrap_rows(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    ranks_per_run: int,
    *,
    seed: int,
    replicates: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    if replicates < 1:
        raise CalibrationError("Bootstrap replicate count must be positive")
    index = family_case_index(rows, positive_cases)
    rng = random.Random(seed)
    anchor_rows = [row for row in rows if row["candidate_id"] in positive_cases]
    threshold_output: list[dict[str, str]] = []
    receptor_output: list[dict[str, str]] = []
    dual_output: list[dict[str, str]] = []
    anchor_ids = sorted(positive_cases)
    for replicate in range(1, replicates + 1):
        values = sampled_anchor_values(index, ranks_per_run, rng)
        rules, channels = diagnostic_rules_from_values(
            values, LOWER_QUANTILE, UPPER_QUANTILE
        )
        replicate_defined = all(item[3]["defined"] for item in channels)
        failures = ";".join(
            f"{channel}:{fit['failure_reason']}"
            for channel, _receptor, _metric, fit in channels
            if not fit["defined"]
        )
        for channel, receptor, metric, fit in channels:
            for cutpoint in ("L", "U"):
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "method_id": METHOD_ID,
                    "bootstrap_seed": seed,
                    "bootstrap_replicate": replicate,
                    "replicate_defined": replicate_defined,
                    "channel": channel,
                    "receptor": receptor,
                    "metric": metric,
                    "cutpoint": cutpoint,
                    "metric_defined": fit["defined"],
                    "value_raw": fit[f"{cutpoint}_raw"],
                    "value_transformed": fit[f"{cutpoint}_transformed"],
                    "raw_unit": fit["raw_unit"],
                    "transform": fit["transform"],
                    "failure_reason": fit["failure_reason"],
                    "formal_eligible": False,
                    "docking_gold_release_eligible": False,
                    "training_label_release_eligible": False,
                }
                threshold_output.append(
                    normalize_record(
                        record, BOOTSTRAP_THRESHOLD_FIELDS,
                        "bootstrap_threshold_row_sha256",
                    )
                )
        run_by_key: dict[tuple[str, str], Mapping[str, str]] = {}
        dual_by_case: dict[str, Mapping[str, str]] = {}
        if replicate_defined:
            pose_scores = score_pose_rows(anchor_rows, rules)
            run_scores = aggregate_native_runs(pose_scores, positive_cases)
            run_by_key = {
                (row["candidate_id"], row["generation_receptor"]): row
                for row in run_scores
            }
            dual_by_case = {
                row["candidate_id"]: row
                for row in aggregate_dual_candidates(run_scores)
            }
        for case_id in anchor_ids:
            family = positive_cases[case_id]["family"]
            for receptor in RECEPTORS:
                run = run_by_key.get((case_id, receptor))
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "method_id": METHOD_ID,
                    "bootstrap_seed": seed,
                    "bootstrap_replicate": replicate,
                    "evaluation_defined": run is not None,
                    "failure_reason": "" if run is not None else failures,
                    "candidate_id": case_id,
                    "family": family,
                    "generation_receptor": receptor,
                    "R_native": run["R_native"] if run else "",
                    "native_run_class": run["native_run_class"] if run else "",
                    "native_run_relevance_strength": run["native_run_relevance_strength"] if run else "",
                    "assigned_support_fraction": run["assigned_support_fraction"] if run else "",
                    "assigned_supporting_pose_count": run["assigned_supporting_pose_count"] if run else "",
                    **{
                        field: run[field] if run else ""
                        for field in ("F_A", "N_A", "F_B", "N_B", "F_C", "N_C")
                    },
                    "formal_eligible": False,
                    "docking_gold_release_eligible": False,
                    "training_label_release_eligible": False,
                }
                receptor_output.append(
                    normalize_record(
                        record, BOOTSTRAP_RECEPTOR_FIELDS,
                        "bootstrap_receptor_row_sha256",
                    )
                )
            dual = dual_by_case.get(case_id)
            ordinal_gap = (
                abs(
                    CLASS_ORDINAL[dual["native_class_8X6B"]]
                    - CLASS_ORDINAL[dual["native_class_9E6Y"]]
                )
                if dual else None
            )
            dual_record = {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "method_id": METHOD_ID,
                "bootstrap_seed": seed,
                "bootstrap_replicate": replicate,
                "evaluation_defined": dual is not None,
                "failure_reason": "" if dual is not None else failures,
                "candidate_id": case_id,
                "family": family,
                "R_8X6B": dual["R_8X6B"] if dual else "",
                "R_9E6Y": dual["R_9E6Y"] if dual else "",
                "R_dual_dev": dual["R_dual_dev"] if dual else "",
                "R_dual_gap": dual["R_dual_gap"] if dual else "",
                "native_class_8X6B": dual["native_class_8X6B"] if dual else "",
                "native_class_9E6Y": dual["native_class_9E6Y"] if dual else "",
                "dual_tier": dual["dual_tier"] if dual else "",
                "assigned_tier_support_fraction": dual["assigned_tier_support_fraction"] if dual else "",
                "assigned_tier_supporting_pose_count": dual["assigned_tier_supporting_pose_count"] if dual else "",
                "class_ordinal_gap": ordinal_gap,
                "both_native_non_E": (
                    dual is not None
                    and dual["native_class_8X6B"] != "E"
                    and dual["native_class_9E6Y"] != "E"
                ),
                "cross_receptor_rank_pairing": False,
                "formal_eligible": False,
                "docking_gold_release_eligible": False,
                "training_label_release_eligible": False,
            }
            dual_output.append(
                normalize_record(
                    dual_record, BOOTSTRAP_DUAL_FIELDS, "bootstrap_dual_row_sha256"
                )
            )
    expected_thresholds = replicates * 10
    expected_receptor = replicates * len(positive_cases) * 2
    expected_dual = replicates * len(positive_cases)
    if (
        len(threshold_output) != expected_thresholds
        or len(receptor_output) != expected_receptor
        or len(dual_output) != expected_dual
    ):
        raise CalibrationError("Bootstrap output cardinality mismatch")
    return threshold_output, receptor_output, dual_output


def summarize_bootstrap(
    threshold_rows: Sequence[Mapping[str, str]],
    receptor_rows: Sequence[Mapping[str, str]],
    dual_rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    replicates: int,
) -> dict[str, Any]:
    replicate_ids = {int(row["bootstrap_replicate"]) for row in threshold_rows}
    undefined = {
        int(row["bootstrap_replicate"])
        for row in threshold_rows
        if row["replicate_defined"] != "true"
    }
    dual_by_case: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    receptor_by_case: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in dual_rows:
        dual_by_case[row["candidate_id"]].append(row)
    for row in receptor_rows:
        receptor_by_case[(row["candidate_id"], row["generation_receptor"])].append(row)
    if set(dual_by_case) != set(positive_cases):
        raise CalibrationError("Bootstrap dual anchor closure failed")
    anchor_summary: dict[str, Any] = {}
    family_retention: dict[str, list[float]] = defaultdict(list)
    family_both_non_e: dict[str, list[float]] = defaultdict(list)
    modal_pass_count = 0
    consistency_pass_count = 0
    for case_id in sorted(positive_cases):
        rows = dual_by_case[case_id]
        if len(rows) != replicates:
            raise CalibrationError(f"Bootstrap dual rows do not close for {case_id}")
        defined = [row for row in rows if row["evaluation_defined"] == "true"]
        tiers = Counter(row["dual_tier"] for row in defined)
        modal = max(
            ("G1", "G2", "G3", "G4", "G5"),
            key=lambda tier: (tiers[tier], DUAL_TIER_STRENGTH[tier]),
        )
        modal_probability = tiers[modal] / replicates
        retention_probability = sum(tiers[tier] for tier in ("G1", "G2", "G3")) / replicates
        consistency_probability = sum(
            int(row["class_ordinal_gap"]) <= 1 for row in defined
        ) / replicates
        both_non_e_probability = sum(
            row["both_native_non_E"] == "true" for row in defined
        ) / replicates
        modal_pass_count += int(modal_probability >= 0.70)
        consistency_pass_count += int(consistency_probability >= 0.70)
        family = positive_cases[case_id]["family"]
        family_retention[family].append(retention_probability)
        family_both_non_e[family].append(both_non_e_probability)
        receptor_class_counts = {
            receptor: Counter(
                row["native_run_class"]
                for row in receptor_by_case[(case_id, receptor)]
                if row["evaluation_defined"] == "true"
            )
            for receptor in RECEPTORS
        }
        anchor_summary[case_id] = {
            "family": family,
            "defined_replicates": len(defined),
            "undefined_replicates": replicates - len(defined),
            "dual_tier_counts": {tier: tiers[tier] for tier in DUAL_TIER_STRENGTH},
            "dual_tier_probabilities": {
                tier: tiers[tier] / replicates for tier in DUAL_TIER_STRENGTH
            },
            "modal_dual_tier": modal,
            "modal_dual_tier_probability": modal_probability,
            "modal_probability_gate_passed": modal_probability >= 0.70,
            "G1_G3_retention_probability": retention_probability,
            "receptor_consistency_probability": consistency_probability,
            "receptor_consistency_gate_passed": consistency_probability >= 0.70,
            "both_native_non_E_probability": both_non_e_probability,
            "native_class_counts": {
                receptor: {name: receptor_class_counts[receptor][name] for name in POSE_CLASSES}
                for receptor in RECEPTORS
            },
        }
    family_summary = {
        family: {
            "best_G1_G3_retention_probability": max(family_retention[family]),
            "retention_gate_passed": max(family_retention[family]) >= 0.70,
            "best_both_native_non_E_probability": max(family_both_non_e[family]),
            "both_native_non_E_gate_passed": max(family_both_non_e[family]) >= 0.70,
        }
        for family in sorted(family_retention)
    }
    modal_gate = modal_pass_count >= 9
    retention_gate = all(x["retention_gate_passed"] for x in family_summary.values())
    consistency_gate = consistency_pass_count >= 9
    both_non_e_gate = all(
        x["both_native_non_E_gate_passed"] for x in family_summary.values()
    )
    return {
        "replicate_count": len(replicate_ids),
        "undefined_replicate_count": len(undefined),
        "undefined_replicates_remain_in_denominator": True,
        "threshold_row_count": len(threshold_rows),
        "receptor_anchor_evaluation_row_count": len(receptor_rows),
        "dual_anchor_evaluation_row_count": len(dual_rows),
        "anchors": anchor_summary,
        "families": family_summary,
        "modal_probability_ge_0_70_count": modal_pass_count,
        "modal_probability_gate_passed": modal_gate,
        "family_G1_G3_retention_gate_passed": retention_gate,
        "receptor_consistency_ge_0_70_count": consistency_pass_count,
        "receptor_consistency_gate_passed": consistency_gate,
        "family_both_native_non_E_gate_passed": both_non_e_gate,
        "passed": modal_gate and retention_gate and consistency_gate and both_non_e_gate,
    }


MUTANT_DELTA_FIELDS = (
    "schema_version", "protocol_id", "method_id", "candidate_id", "family",
    "base_molecule", "exact_base_candidate_id", "control_type", "mutation_class",
    "mutations_1based", "candidate_sequence_sha256", "base_sequence_sha256",
    "mutation_semantics_validated", "delta_R8", "delta_R9", "delta_R_dual_dev",
    "delta_native_class_8", "delta_native_class_9", "delta_dual_tier",
    "candidate_native_class_8", "base_native_class_8",
    "candidate_native_class_9", "base_native_class_9",
    "candidate_dual_tier", "base_dual_tier", "binary_negative_label_assigned",
    "direction_preserved", "formal_eligible", "docking_gold_release_eligible",
    "training_label_release_eligible", "claim_boundary", "mutant_delta_row_sha256",
)


def build_mutant_delta_rows(
    dual_rows: Sequence[Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    base_by_molecule: Mapping[str, str],
    frozen_cases: Mapping[str, Mapping[str, str]],
) -> list[dict[str, str]]:
    by_case = {row["candidate_id"]: row for row in dual_rows}
    if not set(mutant_cases) <= set(by_case):
        raise CalibrationError("Dual candidate output lacks control cases")
    output: list[dict[str, str]] = []
    for case_id, item in sorted(mutant_cases.items()):
        if item["control_type"] == "base_reference":
            continue
        base_id = base_by_molecule.get(item["base_molecule"])
        if not base_id or base_id not in by_case:
            raise CalibrationError(f"Exact base is missing for {case_id}")
        candidate = by_case[case_id]
        base = by_case[base_id]
        if candidate["family"] != base["family"]:
            raise CalibrationError(f"Exact-base family mismatch for {case_id}")
        candidate_case = frozen_cases.get(case_id)
        base_case = frozen_cases.get(base_id)
        if candidate_case is None or base_case is None:
            raise CalibrationError(f"Frozen sequence evidence missing for {case_id}")
        expected_sequence = apply_declared_mutations(
            base_case["sequence"], item["mutations_1based"]
        )
        if (
            expected_sequence != candidate_case["sequence"]
            or sha256_bytes(candidate_case["sequence"].encode("ascii"))
            != candidate_case["sequence_sha256"]
            or sha256_bytes(base_case["sequence"].encode("ascii"))
            != base_case["sequence_sha256"]
        ):
            raise CalibrationError(f"Exact-base mutation sequence closure failed: {case_id}")
        record = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "candidate_id": case_id,
            "family": item["family"],
            "base_molecule": item["base_molecule"],
            "exact_base_candidate_id": base_id,
            "control_type": item["control_type"],
            "mutation_class": item["mutation_class"],
            "mutations_1based": item["mutations_1based"],
            "candidate_sequence_sha256": candidate_case["sequence_sha256"],
            "base_sequence_sha256": base_case["sequence_sha256"],
            "mutation_semantics_validated": True,
            "delta_R8": float(candidate["R_8X6B"]) - float(base["R_8X6B"]),
            "delta_R9": float(candidate["R_9E6Y"]) - float(base["R_9E6Y"]),
            "delta_R_dual_dev": float(candidate["R_dual_dev"]) - float(base["R_dual_dev"]),
            "delta_native_class_8": (
                CLASS_ORDINAL[candidate["native_class_8X6B"]]
                - CLASS_ORDINAL[base["native_class_8X6B"]]
            ),
            "delta_native_class_9": (
                CLASS_ORDINAL[candidate["native_class_9E6Y"]]
                - CLASS_ORDINAL[base["native_class_9E6Y"]]
            ),
            "delta_dual_tier": (
                DUAL_TIER_STRENGTH[candidate["dual_tier"]]
                - DUAL_TIER_STRENGTH[base["dual_tier"]]
            ),
            "candidate_native_class_8": candidate["native_class_8X6B"],
            "base_native_class_8": base["native_class_8X6B"],
            "candidate_native_class_9": candidate["native_class_9E6Y"],
            "base_native_class_9": base["native_class_9E6Y"],
            "candidate_dual_tier": candidate["dual_tier"],
            "base_dual_tier": base["dual_tier"],
            "binary_negative_label_assigned": False,
            "direction_preserved": True,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        output.append(
            normalize_record(record, MUTANT_DELTA_FIELDS, "mutant_delta_row_sha256")
        )
    if len(output) != 29:
        raise CalibrationError(f"Expected 29 exact-base mutant deltas, found {len(output)}")
    return output


ROBUSTNESS_FIELDS = (
    "schema_version", "protocol_id", "method_id", "grid_id", "lower_quantile",
    "upper_quantile", "support_fraction", "minimum_supporting_poses",
    "grid_defined", "failure_reason", "primary_preregistered_row",
    "best_row_selected", "selection_semantics", "positive_G1_count",
    "positive_G2_count", "positive_G3_count", "positive_G4_count",
    "positive_G5_count", "all_G1_count", "all_G2_count", "all_G3_count",
    "all_G4_count", "all_G5_count", "positive_R_dual_median",
    "mutant_delta_R_dual_median", "rules_sha256", "formal_eligible",
    "docking_gold_release_eligible", "training_label_release_eligible",
    "robustness_row_sha256",
)


def build_robustness_rows(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    base_by_molecule: Mapping[str, str],
    frozen_cases: Mapping[str, Mapping[str, str]],
    ranks_per_run: int,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    grid_index = 0
    for lower in ROBUSTNESS_LOWER_QUANTILES:
        for upper in ROBUSTNESS_UPPER_QUANTILES:
            for support in ROBUSTNESS_SUPPORT_FRACTIONS:
                for minimum_poses in ROBUSTNESS_MIN_SUPPORTING_POSES:
                    grid_index += 1
                    defined = True
                    failure_reason = ""
                    rules_hash = ""
                    positive_tiers: Counter[str] = Counter()
                    all_tiers: Counter[str] = Counter()
                    positive_median: float | str = ""
                    delta_median: float | str = ""
                    try:
                        rules = derive_rules(
                            rows,
                            positive_cases,
                            ranks_per_run,
                            lower_quantile=lower,
                            upper_quantile=upper,
                        )
                        rules_hash = sha256_json(rules)
                        pose = score_pose_rows(rows, rules)
                        runs = aggregate_native_runs(
                            pose,
                            positive_cases,
                            support_fraction=support,
                            min_supporting_poses=minimum_poses,
                        )
                        dual = aggregate_dual_candidates(
                            runs,
                            support_fraction=support,
                            min_supporting_poses=minimum_poses,
                        )
                        deltas = build_mutant_delta_rows(
                            dual, mutant_cases, base_by_molecule, frozen_cases
                        )
                        positive_tiers = Counter(
                            row["dual_tier"]
                            for row in dual
                            if row["candidate_id"] in positive_cases
                        )
                        all_tiers = Counter(row["dual_tier"] for row in dual)
                        positive_median = median(
                            float(row["R_dual_dev"])
                            for row in dual
                            if row["candidate_id"] in positive_cases
                        )
                        delta_median = median(
                            float(row["delta_R_dual_dev"]) for row in deltas
                        )
                    except CalibrationError as error:
                        defined = False
                        failure_reason = str(error)
                    record = {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "method_id": METHOD_ID,
                        "grid_id": f"GRID_{grid_index:02d}",
                        "lower_quantile": lower,
                        "upper_quantile": upper,
                        "support_fraction": support,
                        "minimum_supporting_poses": minimum_poses,
                        "grid_defined": defined,
                        "failure_reason": failure_reason,
                        "primary_preregistered_row": (
                            lower == LOWER_QUANTILE
                            and upper == UPPER_QUANTILE
                            and support == SUPPORT_FRACTION
                            and minimum_poses == MIN_SUPPORTING_POSES
                        ),
                        "best_row_selected": False,
                        "selection_semantics": "fixed_54_grid_no_best_row_selection",
                        **{
                            f"positive_{tier}_count": positive_tiers[tier] if defined else ""
                            for tier in DUAL_TIER_STRENGTH
                        },
                        **{
                            f"all_{tier}_count": all_tiers[tier] if defined else ""
                            for tier in DUAL_TIER_STRENGTH
                        },
                        "positive_R_dual_median": positive_median,
                        "mutant_delta_R_dual_median": delta_median,
                        "rules_sha256": rules_hash,
                        "formal_eligible": False,
                        "docking_gold_release_eligible": False,
                        "training_label_release_eligible": False,
                    }
                    output.append(
                        normalize_record(record, ROBUSTNESS_FIELDS, "robustness_row_sha256")
                    )
    if len(output) != 54 or sum(row["primary_preregistered_row"] == "true" for row in output) != 1:
        raise CalibrationError("Fixed 54-row robustness grid closure failed")
    return output


def spearman(values_x: Sequence[float], values_y: Sequence[float]) -> float | None:
    if len(values_x) != len(values_y) or len(values_x) < 2:
        return None

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        result = [0.0] * len(values)
        position = 0
        while position < len(order):
            end = position + 1
            while end < len(order) and values[order[end]] == values[order[position]]:
                end += 1
            average = (position + 1 + end) / 2.0
            for cursor in range(position, end):
                result[order[cursor]] = average
            position = end
        return result

    rank_x, rank_y = ranks(values_x), ranks(values_y)
    mean_x = sum(rank_x) / len(rank_x)
    mean_y = sum(rank_y) / len(rank_y)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(rank_x, rank_y))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in rank_x)
        * sum((y - mean_y) ** 2 for y in rank_y)
    )
    return numerator / denominator if denominator else None


def build_acceptance_summary(
    *,
    config: CalibrationConfig,
    observed_contract: Mapping[str, Any],
    input_bindings: Mapping[str, Any],
    rules: Mapping[str, Any],
    pose_rows: Sequence[Mapping[str, str]],
    run_rows: Sequence[Mapping[str, str]],
    dual_rows: Sequence[Mapping[str, str]],
    lofo_summary: Mapping[str, Any],
    bootstrap_summary: Mapping[str, Any],
    mutant_rows: Sequence[Mapping[str, str]],
    robustness_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    threshold_channels = [rules["thresholds"]["pooled_H"]]
    threshold_channels.extend(
        rules["thresholds"]["receptor"][receptor][metric]
        for receptor in RECEPTORS
        for metric in ("O", "P")
    )
    threshold_valid = len(threshold_channels) == 5 and all(
        item["defined"]
        and float(item["L_raw"]) > 0.0
        and float(item["U_raw"]) > float(item["L_raw"])
        for item in threshold_channels
    )
    primary_grid = [
        row for row in robustness_rows if row["primary_preregistered_row"] == "true"
    ]
    gates: dict[str, dict[str, Any]] = {
        "frozen_upstream": {
            "passed": (
                input_bindings["preregistration"].get("validated") is True
                and input_bindings["execution_release"].get("validated") is True
                and input_bindings["selector_publication"].get(
                    "immutable_publication_validated"
                ) is True
                and input_bindings["processor_audit"].get("validated") is True
                and input_bindings["processor_qualification"].get(
                    "calibration_input_eligible"
                ) is True
                and input_bindings["fixed_case_semantics"].get(
                    "mutation_semantics_validated"
                ) is True
            )
        },
        "cohort_closure": {
            "passed": observed_contract.get("case_count") == 47
            and observed_contract.get("positive_anchor_count") == 11
            and observed_contract.get("positive_family_count") == 5
            and observed_contract.get("control_case_count") == 36,
        },
        "run_closure": {"passed": len(run_rows) == 94},
        "pose_closure": {"passed": len(pose_rows) == 752},
        "metric_closure": {
            "passed": observed_contract.get("metric_rows") == 752
            and observed_contract.get("rows_by_generation_receptor")
            == {"8X6B": 376, "9E6Y": 376},
        },
        "protocol_hash_closure": {
            "passed": bool(input_bindings["continuous_metrics"].get("sha256"))
            and bool(input_bindings["processor_audit"].get("sha256"))
            and input_bindings["frozen_manifests"].get("run_count") == 94
            and input_bindings["frozen_manifests"].get("protocol_count") == 2
            and input_bindings["execution_release"].get("artifact_count", 0) >= 30,
        },
        "ATOM_only": {
            "passed": observed_contract.get("atom_only_reference_inventory_gate_passed") is True
        },
        "five_channel_threshold_validity": {
            "passed": threshold_valid and rules.get("primary_channel_count") == 5
        },
        "family_and_receptor_balance": {
            "passed": rules.get("positive_family_count") == 5
            and rules.get("pooled_H_receptor_weighting") == "one_half_per_receptor",
        },
        "central_and_54_grid": {
            "passed": len(robustness_rows) == 54
            and len(primary_grid) == 1
            and all(row["grid_defined"] == "true" for row in robustness_rows)
            and all(row["best_row_selected"] == "false" for row in robustness_rows),
        },
        "LOFO": {"passed": lofo_summary.get("passed") is True},
        "bootstrap": {
            "passed": bootstrap_summary.get("passed") is True
            and config.bootstrap_seed == BOOTSTRAP_SEED
            and config.bootstrap_replicates == BOOTSTRAP_REPLICATES
            and bootstrap_summary.get("threshold_row_count") == 20000
            and bootstrap_summary.get("receptor_anchor_evaluation_row_count") == 44000
            and bootstrap_summary.get("dual_anchor_evaluation_row_count") == 22000,
        },
        "receptor_consistency": {
            "passed": bootstrap_summary.get("receptor_consistency_gate_passed") is True
            and bootstrap_summary.get("family_both_native_non_E_gate_passed") is True
        },
        "mutant_sensitivity": {
            "passed": len(mutant_rows) == 29
            and all(row["binary_negative_label_assigned"] == "false" for row in mutant_rows)
            and all(row["direction_preserved"] == "true" for row in mutant_rows)
            and all(row["mutation_semantics_validated"] == "true" for row in mutant_rows),
            "sequence_hashes_and_mutation_semantics": all(
                row["mutation_semantics_validated"] == "true"
                and re.fullmatch(r"[0-9a-f]{64}", row["candidate_sequence_sha256"])
                and re.fullmatch(r"[0-9a-f]{64}", row["base_sequence_sha256"])
                for row in mutant_rows
            ),
        },
        "diagnostic_isolation": {
            "passed": observed_contract.get("native_rank_pairing_across_receptors") is False
            and observed_contract.get("native_only_validated") is True
            and observed_contract.get(
                "generation_native_receptor_identity_validated"
            ) is True
            and all(row["cross_receptor_rank_pairing"] == "false" for row in run_rows)
            and all(row["cross_receptor_rank_pairing"] == "false" for row in dual_rows),
        },
        "claim_boundary": {
            "passed": all(row["claim_boundary"] == CLAIM_BOUNDARY for row in dual_rows)
        },
        "formal_veto": {
            "passed": True,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            "unconditional": True,
        },
    }
    required = (
        "frozen_upstream", "cohort_closure", "run_closure", "pose_closure",
        "metric_closure", "protocol_hash_closure", "ATOM_only",
        "five_channel_threshold_validity", "family_and_receptor_balance",
        "central_and_54_grid", "LOFO", "bootstrap", "receptor_consistency",
        "mutant_sensitivity", "diagnostic_isolation", "claim_boundary", "formal_veto",
    )
    passed = all(gates[name]["passed"] for name in required)
    return {
        "all_gates_required": True,
        "required_gate_order": list(required),
        "gates": gates,
        "development_method_passed": passed,
        "computed_gate_outcome": "COMPUTED_GATES_SATISFIED" if passed else "COMPUTED_GATES_NOT_SATISFIED",
        "status": CALCULATED_STATUS,
        "external_release_validation_required": True,
        "development_smoke_eligible": False,
        "pass_does_not_override_formal_veto": True,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
        "training_state": "P2_TRAINING_BLOCKED",
    }


def tier_counts(rows: Sequence[Mapping[str, str]]) -> dict[str, int]:
    counts = Counter(row["dual_tier"] for row in rows)
    return {tier: counts[tier] for tier in DUAL_TIER_STRENGTH}


def render_report(
    *,
    status: str,
    rules: Mapping[str, Any],
    dual_rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    lofo_summary: Mapping[str, Any],
    bootstrap_summary: Mapping[str, Any],
    mutant_rows: Sequence[Mapping[str, str]],
    robustness_rows: Sequence[Mapping[str, str]],
    acceptance: Mapping[str, Any],
    artifact_hashes: Mapping[str, Mapping[str, Any]],
    config: CalibrationConfig,
) -> str:
    positive_dual = [row for row in dual_rows if row["candidate_id"] in positive_cases]
    anchor_r8 = [float(row["R_8X6B"]) for row in positive_dual]
    anchor_r9 = [float(row["R_9E6Y"]) for row in positive_dual]
    lines = [
        "# PVRIG V3-P2 Docking Gold V1.3 native dual-receptor development calibration",
        "",
        f"- Status: `{status}`",
        "- External release validation is required; this calculation never unlocks smoke execution.",
        "- Development smoke eligible: `false`.",
        "- Primary data: 47 cases x 2 independent native receptor runs x Top-8 = 752 poses.",
        "- Five channels: pooled canonical H plus receptor-native O/P for 8X6B and 9E6Y.",
        "- Ranks are never paired across receptors; dual joining occurs only after 94 run summaries.",
        "- Formal, Docking Gold, training-label, and P2-training eligibility remain false unconditionally.",
        "",
        "## Central thresholds",
        "",
        "| channel | L raw | U raw | transform |",
        "| --- | ---: | ---: | --- |",
    ]
    threshold_rows = [("canonical pooled H", rules["thresholds"]["pooled_H"])]
    threshold_rows.extend(
        (f"{receptor} native {metric}", rules["thresholds"]["receptor"][receptor][metric])
        for receptor in RECEPTORS
        for metric in ("O", "P")
    )
    for name, fit in threshold_rows:
        lines.append(
            f"| {name} | {fit['L_raw']:.8g} | {fit['U_raw']:.8g} | {fit['transform']} |"
        )
    lines.extend(
        [
            "",
            "## Development diagnostics",
            "",
            f"- Positive dual tiers: `{tier_counts(positive_dual)}`.",
            f"- All-case dual tiers: `{tier_counts(dual_rows)}`.",
            f"- LOFO passed: `{lofo_summary['passed']}`.",
            f"- Bootstrap seed/B: `{config.bootstrap_seed}/{config.bootstrap_replicates}`.",
            f"- Bootstrap rows: thresholds={bootstrap_summary['threshold_row_count']}, receptor-anchor={bootstrap_summary['receptor_anchor_evaluation_row_count']}, dual-anchor={bootstrap_summary['dual_anchor_evaluation_row_count']}.",
            f"- Native receptor score Spearman on 11 anchors (diagnostic only): `{spearman(anchor_r8, anchor_r9)}`.",
            f"- Exact-base mutant deltas: `{len(mutant_rows)}`; binary negative labels assigned: `false`.",
            f"- Fixed sensitivity grid rows: `{len(robustness_rows)}`; best row selected: `false`.",
            "",
            "## Acceptance gates",
            "",
            "| gate | passed |",
            "| --- | --- |",
        ]
    )
    for name, gate in acceptance["gates"].items():
        lines.append(f"| {name} | `{gate['passed']}` |")
    lines.extend(["", "## Artifact hashes", "", "| artifact | rows | SHA256 |", "| --- | ---: | --- |"])
    for name, evidence in artifact_hashes.items():
        lines.append(f"| `{name}` | {evidence.get('rows', '')} | `{evidence['sha256']}` |")
    lines.extend(["", f"> Claim boundary: {CLAIM_BOUNDARY}", ""])
    return "\n".join(lines)


def directory_inventory(root: Path) -> dict[str, Any]:
    files = [
        {
            "relpath": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]
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
        raise CalibrationError(f"Current publication pointer is not a symlink: {current_link}")
    temporary = current_link.with_name(f".{current_link.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    os.symlink(os.path.relpath(release_dir, current_link.parent), temporary, target_is_directory=True)
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
        raise CalibrationError(f"Current publication pointer is not a symlink: {current_link}")
    previous_release = current_link.resolve() if current_link.is_symlink() else None
    created = False
    if release_dir.exists():
        if directory_inventory(staging) != directory_inventory(release_dir):
            raise CalibrationError(f"Immutable calibration release collision: {release_dir.name}")
        shutil.rmtree(staging)
    else:
        os.replace(staging, release_dir)
        created = True
    try:
        pointer_promoter(release_dir, current_link)
        if not current_link.is_symlink() or current_link.resolve() != release_dir.resolve():
            raise CalibrationError("Atomic calibration current-pointer verification failed")
    except Exception:
        if previous_release is not None:
            promote_current_symlink(previous_release, current_link)
        else:
            current_link.unlink(missing_ok=True)
        if created and release_dir.exists():
            shutil.rmtree(release_dir)
        raise


def build_calibration(
    config: CalibrationConfig,
    *,
    pointer_promoter: PointerPromoter = promote_current_symlink,
) -> dict[str, Any]:
    preregistration = validate_preregistration(config.preregistration)
    execution_release, execution_ledger = validate_execution_release(
        config.execution_release
    )
    frozen_cases, frozen_runs, protocols, frozen_manifest_evidence = (
        validate_frozen_manifests(config, execution_ledger)
    )
    positive_cases = load_positive_manifest(config.positive_manifest)
    mutant_cases, base_by_molecule = load_mutant_manifest(config.mutant_manifest)
    case_semantics = validate_fixed_case_semantics(
        config,
        frozen_cases,
        positive_cases,
        mutant_cases,
        base_by_molecule,
    )
    selector_by_key, selector_evidence = validate_selector_publication(
        config.selector_csv,
        config.selector_audit,
        frozen_cases,
        frozen_runs,
        protocols,
    )
    metric_fields, metric_rows = read_csv_strict(config.metrics_csv)
    observed_contract = validate_metrics_rows(
        metric_fields,
        metric_rows,
        positive_cases,
        mutant_cases,
        config.contract,
        selector_by_key,
        config.references,
    )
    processor_audit = validate_processor_audit(
        config.processor_audit,
        config.metrics_csv,
        metric_rows,
        config,
        selector_evidence,
        preregistration,
    )
    processor_qualification = validate_processor_qualification(
        config.processor_qualification,
        config,
        processor_audit,
        metric_rows,
        selector_evidence,
        preregistration,
        execution_release,
    )
    input_bindings = {
        "preregistration": preregistration,
        "execution_release": execution_release,
        "frozen_manifests": frozen_manifest_evidence,
        "fixed_case_semantics": case_semantics,
        "selector_publication": selector_evidence,
        "processor_audit": processor_audit,
        "processor_qualification": processor_qualification,
        "continuous_metrics": {
            "relpath": canonical_path(config.metrics_csv),
            "sha256": sha256_file(config.metrics_csv),
            "rows": len(metric_rows),
            "row_hash_chain": newline_hash_chain(metric_rows, "metrics_row_sha256"),
        },
        "positive_manifest": {
            "relpath": canonical_path(config.positive_manifest),
            "sha256": sha256_file(config.positive_manifest),
            "rows": len(positive_cases),
        },
        "mutant_manifest": {
            "relpath": canonical_path(config.mutant_manifest),
            "sha256": sha256_file(config.mutant_manifest),
            "rows": len(mutant_cases),
        },
    }
    rules = derive_rules(metric_rows, positive_cases, config.contract.ranks_per_run)
    pose_rows = score_pose_rows(metric_rows, rules)
    run_rows = aggregate_native_runs(pose_rows, positive_cases)
    dual_rows = aggregate_dual_candidates(run_rows)
    if len(pose_rows) != 752 or len(run_rows) != 94 or len(dual_rows) != 47:
        raise CalibrationError("Central pose/run/dual output closure failed")
    lofo_rows = build_lofo_rows(
        metric_rows, positive_cases, dual_rows, config.contract.ranks_per_run
    )
    lofo_summary = summarize_lofo(lofo_rows, positive_cases)
    bootstrap_threshold_rows, bootstrap_receptor_rows, bootstrap_dual_rows = (
        hierarchical_bootstrap_rows(
            metric_rows,
            positive_cases,
            config.contract.ranks_per_run,
            seed=config.bootstrap_seed,
            replicates=config.bootstrap_replicates,
        )
    )
    bootstrap_summary = summarize_bootstrap(
        bootstrap_threshold_rows,
        bootstrap_receptor_rows,
        bootstrap_dual_rows,
        positive_cases,
        config.bootstrap_replicates,
    )
    mutant_rows = build_mutant_delta_rows(
        dual_rows, mutant_cases, base_by_molecule, frozen_cases
    )
    robustness_rows = build_robustness_rows(
        metric_rows,
        positive_cases,
        mutant_cases,
        base_by_molecule,
        frozen_cases,
        config.contract.ranks_per_run,
    )
    acceptance = build_acceptance_summary(
        config=config,
        observed_contract=observed_contract,
        input_bindings=input_bindings,
        rules=rules,
        pose_rows=pose_rows,
        run_rows=run_rows,
        dual_rows=dual_rows,
        lofo_summary=lofo_summary,
        bootstrap_summary=bootstrap_summary,
        mutant_rows=mutant_rows,
        robustness_rows=robustness_rows,
    )
    status = acceptance["status"]
    rules_document = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "protocol_id": PROTOCOL_ID,
        "method_id": METHOD_ID,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
        "training_state": "P2_TRAINING_BLOCKED",
        "development_method_evaluation_eligible": True,
        "development_method_passed": acceptance["development_method_passed"],
        "computed_gate_outcome": acceptance["computed_gate_outcome"],
        "external_release_validation_required": True,
        "development_smoke_eligible": False,
        "claim_boundary": CLAIM_BOUNDARY,
        "rules": rules,
        "aggregation": {
            "per_receptor_first": True,
            "candidate_level_dual_join_second": True,
            "cross_receptor_rank_pairing": False,
            "native_class_relevance_strength": CLASS_RELEVANCE,
            "native_class_ordinal": CLASS_ORDINAL,
            "dual_tier_map": {
                "A/A": "G1", "A/B_or_B/A": "G2", "B/B": "G3",
                "both_non_E_and_at_least_one_C": "G4", "any_E": "G5",
            },
            "R_gold_name_forbidden": True,
        },
        "input_bindings": input_bindings,
        "implementation": {
            "relpath": canonical_path(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
            "test_relpath": canonical_path(DEFAULT_CALIBRATOR_TEST),
            "test_sha256": sha256_file(DEFAULT_CALIBRATOR_TEST),
        },
    }
    release_identity = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "method_id": METHOD_ID,
        "input_sha256": {
            name: evidence.get("sha256", "")
            for name, evidence in {
                "preregistration": preregistration,
                "execution_release": execution_release,
                "selector_csv": selector_evidence["selector_csv"],
                "selector_audit": selector_evidence["selector_audit"],
                "processor_audit": processor_audit,
                "processor_qualification": processor_qualification,
                "continuous_metrics": input_bindings["continuous_metrics"],
                "positive_manifest": input_bindings["positive_manifest"],
                "mutant_manifest": input_bindings["mutant_manifest"],
            }.items()
        },
        "implementation_sha256": rules_document["implementation"]["sha256"],
        "implementation_test_sha256": rules_document["implementation"]["test_sha256"],
        "bootstrap_seed": config.bootstrap_seed,
        "bootstrap_replicates": config.bootstrap_replicates,
    }
    release_id = f"calc-{sha256_json(release_identity)[:24]}"
    publication_root = config.outdir.resolve()
    releases_root = publication_root / "releases"
    release_dir = releases_root / release_id
    current_link = publication_root / "current"
    expected_report = current_link / REPORT_NAME
    if Path(os.path.abspath(config.report)) != Path(os.path.abspath(expected_report)):
        raise CalibrationError(
            f"Report path must be the versioned current view: {expected_report}"
        )
    publication_root.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{release_id}.staging-", dir=publication_root)
    )
    try:
        payloads: dict[str, tuple[Sequence[Mapping[str, str]], Sequence[str], str]] = {
            POSE_SCORES_NAME: (pose_rows, POSE_SCORE_FIELDS, "pose_score_row_sha256"),
            RUN_SCORES_NAME: (run_rows, RUN_SCORE_FIELDS, "run_score_row_sha256"),
            DUAL_SCORES_NAME: (dual_rows, DUAL_SCORE_FIELDS, "dual_score_row_sha256"),
            LOFO_NAME: (lofo_rows, LOFO_FIELDS, "lofo_row_sha256"),
            BOOTSTRAP_THRESHOLDS_NAME: (
                bootstrap_threshold_rows,
                BOOTSTRAP_THRESHOLD_FIELDS,
                "bootstrap_threshold_row_sha256",
            ),
            BOOTSTRAP_RECEPTOR_NAME: (
                bootstrap_receptor_rows,
                BOOTSTRAP_RECEPTOR_FIELDS,
                "bootstrap_receptor_row_sha256",
            ),
            BOOTSTRAP_DUAL_NAME: (
                bootstrap_dual_rows,
                BOOTSTRAP_DUAL_FIELDS,
                "bootstrap_dual_row_sha256",
            ),
            MUTANT_DELTAS_NAME: (
                mutant_rows, MUTANT_DELTA_FIELDS, "mutant_delta_row_sha256"
            ),
            ROBUSTNESS_NAME: (
                robustness_rows, ROBUSTNESS_FIELDS, "robustness_row_sha256"
            ),
        }
        rules_path = staging / RULES_NAME
        write_json(rules_path, rules_document)
        for name, (rows, fields, _hash_field) in payloads.items():
            write_csv(staging / name, rows, fields)
        artifact_hashes: dict[str, dict[str, Any]] = {
            RULES_NAME: {"sha256": sha256_file(rules_path)}
        }
        for name, (rows, _fields, hash_field) in payloads.items():
            artifact_hashes[name] = {
                "sha256": sha256_file(staging / name),
                "rows": len(rows),
                "row_hash_chain": row_hash_chain(rows, hash_field),
            }
        report_text = render_report(
            status=status,
            rules=rules,
            dual_rows=dual_rows,
            positive_cases=positive_cases,
            lofo_summary=lofo_summary,
            bootstrap_summary=bootstrap_summary,
            mutant_rows=mutant_rows,
            robustness_rows=robustness_rows,
            acceptance=acceptance,
            artifact_hashes=artifact_hashes,
            config=config,
        )
        report_path = staging / REPORT_NAME
        report_path.write_text(report_text, encoding="utf-8")
        audit = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            "training_state": "P2_TRAINING_BLOCKED",
            "development_method_evaluation_eligible": True,
            "computational_geometry_teacher_only": True,
            "development_method_passed": acceptance["development_method_passed"],
            "computed_gate_outcome": acceptance["computed_gate_outcome"],
            "external_release_validation_required": True,
            "development_smoke_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
            "observed_contract": observed_contract,
            "input_bindings": input_bindings,
            "central_rules": rules,
            "central_outputs": {
                "pose_rows": len(pose_rows),
                "native_run_rows": len(run_rows),
                "dual_candidate_rows": len(dual_rows),
                "positive_dual_tiers": tier_counts(
                    [row for row in dual_rows if row["candidate_id"] in positive_cases]
                ),
                "all_dual_tiers": tier_counts(dual_rows),
                "cross_receptor_rank_pairing": False,
            },
            "lofo": lofo_summary,
            "bootstrap": {
                "seed": config.bootstrap_seed,
                "replicates": config.bootstrap_replicates,
                "hierarchy": "family_with_replacement_then_case_within_family_with_replacement",
                "atomic_unit": "both_native_receptor_top8_runs_for_one_case",
                "summary": bootstrap_summary,
            },
            "mutant_sensitivity": {
                "paired_delta_count": len(mutant_rows),
                "exact_base_only": True,
                "sequence_hashes_validated": True,
                "mutation_semantics_validated": True,
                "binary_negative_labels_assigned": False,
                "directions_preserved": True,
            },
            "robustness_grid": {
                "rows": len(robustness_rows),
                "best_row_selected": False,
                "all_rows_emitted_once": True,
            },
            "acceptance_summary": acceptance,
            "implementation": rules_document["implementation"],
            "output_sha256": artifact_hashes,
            "report": {
                "relpath": REPORT_NAME,
                "sha256": sha256_file(report_path),
            },
            "publication": {
                "release_id": release_id,
                "release_relpath": f"releases/{release_id}",
                "current_pointer_relpath": "current",
                "immutable_versioned_release": True,
                "promotion": "single atomic current symlink replacement",
                "rollback_safe": True,
            },
        }
        audit_path = staging / AUDIT_NAME
        write_json(audit_path, audit)
        release_input = {
            "schema_version": "pvrig_v1_3_calibration_release_input_v1",
            "status": RELEASE_INPUT_STATUS,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "release_id": release_id,
            "calculation_status": CALCULATED_STATUS,
            "computed_gate_outcome": acceptance["computed_gate_outcome"],
            "external_validator_required": True,
            "development_smoke_eligible": False,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            "calibration_audit": {
                "relpath": AUDIT_NAME,
                "sha256": sha256_file(audit_path),
            },
            "calibrator": rules_document["implementation"],
            "upstream_sha256": release_identity["input_sha256"],
            "output_sha256": artifact_hashes,
            "required_external_checks": [
                "canonical_upstream_paths_and_frozen_hashes",
                "immutable_release_inventory",
                "current_pointer_identity",
                "computed_gate_outcome",
                "B2000_output_cardinality",
                "formal_and_training_vetoes",
            ],
        }
        write_json(staging / RELEASE_INPUT_NAME, release_input)
        staged_inventory = directory_inventory(staging)
        if staged_inventory["file_count"] != len(payloads) + 4:
            raise CalibrationError("Calibration immutable release inventory is incomplete")
        promote_versioned_release(
            staging, release_dir, current_link, pointer_promoter
        )
        if sha256_file(current_link / AUDIT_NAME) != sha256_file(release_dir / AUDIT_NAME):
            raise CalibrationError("Published calibration audit hash mismatch")
        if sha256_file(current_link / RELEASE_INPUT_NAME) != sha256_file(
            release_dir / RELEASE_INPUT_NAME
        ):
            raise CalibrationError("Published release-input contract hash mismatch")
        return audit
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def validate_publication_input_wiring(
    *,
    metrics_csv: Path,
    processor_audit: Path,
    processor_qualification: Path,
    selector_csv: Path,
    selector_audit: Path,
) -> dict[str, str]:
    entries = {
        "continuous_metrics": (
            metrics_csv,
            DEFAULT_PROCESSING_DIR,
            DEFAULT_METRICS_CSV.name,
            DEFAULT_METRICS_CSV,
        ),
        "processor_audit": (
            processor_audit,
            DEFAULT_PROCESSING_DIR,
            DEFAULT_PROCESSOR_AUDIT.name,
            DEFAULT_PROCESSOR_AUDIT,
        ),
        "processor_qualification": (
            processor_qualification,
            DEFAULT_PROCESSOR_QUALIFICATION_ROOT,
            DEFAULT_PROCESSOR_QUALIFICATION.name,
            DEFAULT_PROCESSOR_QUALIFICATION,
        ),
        "selector_csv": (
            selector_csv,
            DEFAULT_SELECTOR_ROOT,
            DEFAULT_SELECTOR_CSV.name,
            DEFAULT_SELECTOR_CSV,
        ),
        "selector_audit": (
            selector_audit,
            DEFAULT_SELECTOR_ROOT,
            DEFAULT_SELECTOR_AUDIT.name,
            DEFAULT_SELECTOR_AUDIT,
        ),
    }
    validated: dict[str, str] = {}
    for label, (selected, publication_root, filename, canonical_default) in entries.items():
        default_lexical = Path(os.path.abspath(canonical_default))
        expected_default = Path(os.path.abspath(publication_root / "current" / filename))
        if default_lexical != expected_default:
            raise CalibrationError(f"Internal {label} default is not wired through current")
        selected_lexical = Path(os.path.abspath(selected))
        stale_root_level = Path(os.path.abspath(publication_root / filename))
        if selected_lexical == stale_root_level:
            raise CalibrationError(
                f"Stale root-level {label} is forbidden; use publication current: "
                f"{canonical_default}"
            )
        validated[label] = selected_lexical.as_posix()
    return validated


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-csv", type=Path, default=DEFAULT_METRICS_CSV)
    parser.add_argument("--processor-audit", type=Path, default=DEFAULT_PROCESSOR_AUDIT)
    parser.add_argument(
        "--processor-qualification",
        type=Path,
        default=DEFAULT_PROCESSOR_QUALIFICATION,
    )
    parser.add_argument("--selector-csv", type=Path, default=DEFAULT_SELECTOR_CSV)
    parser.add_argument("--selector-audit", type=Path, default=DEFAULT_SELECTOR_AUDIT)
    parser.add_argument("--execution-release", type=Path, default=DEFAULT_EXECUTION_RELEASE)
    parser.add_argument("--case-manifest", type=Path, default=DEFAULT_CASE_MANIFEST)
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_RUN_MANIFEST)
    parser.add_argument("--protocol-manifest", type=Path, default=DEFAULT_PROTOCOL_MANIFEST)
    parser.add_argument("--reference-8x6b", type=Path, default=DEFAULT_REFERENCES["8X6B"])
    parser.add_argument("--reference-9e6y", type=Path, default=DEFAULT_REFERENCES["9E6Y"])
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--positive-manifest", type=Path, default=DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_publication_input_wiring(
            metrics_csv=args.metrics_csv,
            processor_audit=args.processor_audit,
            processor_qualification=args.processor_qualification,
            selector_csv=args.selector_csv,
            selector_audit=args.selector_audit,
        )
    except CalibrationError as error:
        print(f"FAIL_V1_3_NATIVE_DUAL_CALIBRATION_PREFLIGHT: {error}")
        return 2
    config = CalibrationConfig(
        metrics_csv=args.metrics_csv.resolve(),
        processor_audit=args.processor_audit.resolve(),
        processor_qualification=args.processor_qualification.resolve(),
        selector_csv=args.selector_csv.resolve(),
        selector_audit=args.selector_audit.resolve(),
        execution_release=args.execution_release.resolve(),
        case_manifest=args.case_manifest.resolve(),
        run_manifest=args.run_manifest.resolve(),
        protocol_manifest=args.protocol_manifest.resolve(),
        references={
            "8X6B": args.reference_8x6b.resolve(),
            "9E6Y": args.reference_9e6y.resolve(),
        },
        preregistration=args.preregistration.resolve(),
        positive_manifest=args.positive_manifest.resolve(),
        mutant_manifest=args.mutant_manifest.resolve(),
        outdir=args.outdir.resolve(),
        report=(
            args.report.resolve()
            if args.report is not None
            else (args.outdir.resolve() / "current" / REPORT_NAME)
        ),
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_replicates=args.bootstrap_replicates,
    )
    try:
        audit = build_calibration(config)
    except (CalibrationError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL_V1_3_NATIVE_DUAL_CALIBRATION: {error}")
        return 2
    print(canonical_json(audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
