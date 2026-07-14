#!/usr/bin/env python3
"""Build the V1.2 ATOM-only development-sensitivity rescore package.

The legacy aligned pose directories contain variable-size final
``6_seletopclusts`` ensembles.  They may validate scorer sensitivity, record
inventory, and numeric closure only.  They must not inform threshold fitting,
are not a fixed-K calibration Gold set, and are never formal-eligible here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

PROTOCOL_ID = "DG_A_PVRIG_V1_2_DEV"
SENSITIVITY_DATASET_ID = "V1_2_ATOM_ONLY_SCORER_SENSITIVITY_FINAL_POSES"
DATASET_PURPOSE = "development_sensitivity_inventory_numeric_closure_only"
POSE_SOURCE_PROTOCOL = "legacy_6_seletopclusts_variable_final_pose_set"
CLAIM_BOUNDARY = (
    "ATOM-only computational scorer sensitivity, record inventory, and numeric closure "
    "on legacy variable-size final poses; prohibited for threshold fitting; not fixed-K "
    "calibration Gold, not formal validation, and not experimental binding or blocking truth"
)
SCORING_SEMANTICS_VERSION = "PVRIG_PVRL2_ATOM_ONLY_V1_2"

DEFAULT_POSITIVE_MANIFEST = (
    WORKSPACE_ROOT / "docking/calibration/patent_success_validation/batch_manifest.csv"
)
DEFAULT_MUTANT_MANIFEST = (
    WORKSPACE_ROOT / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
)
DEFAULT_POSE_SCORER = WORKSPACE_ROOT / "docking/scripts/score_pvrig_vhh_pose_v1_2.py"
DEFAULT_REGION_SCORER = (
    WORKSPACE_ROOT / "docking/scripts/score_cdr_region_occlusion_v1_2.py"
)
DEFAULT_SCORING_HELPER = WORKSPACE_ROOT / "docking/scripts/pvrig_scoring_semantics_v1_2.py"
DEFAULT_HOTSPOTS = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_2_calibration_sensitivity"

BASELINES: Mapping[str, Mapping[str, Any]] = {
    "8x6b": {
        "reference": DATA_ROOT / "structures/8X6B.pdb",
        "ref_pvrig_chain": "B",
        "ref_pvrl2_chain": "A",
        "hotspot_ref_column": "pdb_8x6b_ref",
    },
    "9e6y": {
        "reference": DATA_ROOT / "structures/9E6Y.pdb",
        "ref_pvrig_chain": "A",
        "ref_pvrl2_chain": "D",
        "hotspot_ref_column": "pdb_9e6y_ref",
    },
}

POSE_MANIFEST_NAME = "pvrig_v1_2_sensitivity_pose_manifest.csv"
METRICS_NAME = "pvrig_v1_2_sensitivity_continuous_metrics.csv"
AUDIT_NAME = "pvrig_v1_2_sensitivity_audit.json"


@dataclass(frozen=True)
class DatasetContract:
    positive_cases: int = 11
    mutant_cases: int = 36
    positive_poses_per_baseline: int = 109
    mutant_poses_per_baseline: int = 357

    @property
    def total_rows(self) -> int:
        return 2 * (self.positive_poses_per_baseline + self.mutant_poses_per_baseline)

    def as_dict(self) -> dict[str, int]:
        return {
            "positive_cases": self.positive_cases,
            "mutant_cases": self.mutant_cases,
            "positive_poses_per_baseline": self.positive_poses_per_baseline,
            "mutant_poses_per_baseline": self.mutant_poses_per_baseline,
            "total_rows": self.total_rows,
        }


DEFAULT_CONTRACT = DatasetContract()


@dataclass(frozen=True)
class BuildConfig:
    positive_manifest: Path
    mutant_manifest: Path
    pose_scorer: Path
    region_scorer: Path
    scoring_helper: Path
    hotspots: Path
    references: Mapping[str, Path]
    outdir: Path
    workspace_root: Path = WORKSPACE_ROOT
    pose_dir_template: str = "haddock3/top_models_aligned_to_{baseline}"
    pose_suffix_template: str = "_aligned_to_{baseline}.pdb"
    pose_source_protocol: str = POSE_SOURCE_PROTOCOL
    contract: DatasetContract = DEFAULT_CONTRACT


class ContractError(RuntimeError):
    """Raised whenever the sensitivity package cannot be built fail-closed."""


MANIFEST_FIELDS = [
    "schema_version",
    "protocol_id",
    "sensitivity_dataset_id",
    "dataset_purpose",
    "formal_eligible",
    "threshold_freeze_eligible",
    "pose_source_protocol",
    "source_dataset",
    "source_order",
    "sample_id",
    "family",
    "evidence_role",
    "control_descriptor",
    "usage_boundary",
    "model",
    "cluster_index",
    "model_index",
    "baseline",
    "source_pose_relpath",
    "source_pose_sha256",
    "source_manifest_relpath",
    "source_manifest_sha256",
    "source_manifest_row_sha256",
    "reference_relpath",
    "reference_sha256",
    "hotspots_relpath",
    "hotspots_sha256",
    "pose_scorer_relpath",
    "pose_scorer_sha256",
    "region_scorer_relpath",
    "region_scorer_sha256",
    "scoring_helper_relpath",
    "scoring_helper_sha256",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "pose_pvrig_chain",
    "pose_vhh_chain",
    "ref_pvrig_chain",
    "ref_pvrl2_chain",
    "hotspot_ref_column",
    "manifest_row_sha256",
]

POSE_METRICS = [
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
]
REGION_TOTAL_METRICS = [
    "total_occluding_atom_contact_count",
    "total_clash_atom_contact_count",
    "total_occluding_residue_pair_count",
    "total_clash_residue_pair_count",
]
REGION_ITEM_METRICS = [
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
]
REGIONS = ("CDR1", "CDR2", "CDR3", "framework")
METRICS_FIELDS = [
    *MANIFEST_FIELDS,
    "pose_score_schema_version",
    "region_score_schema_version",
    "scoring_semantics_version",
    *POSE_METRICS,
    *REGION_TOTAL_METRICS,
    *[
        f"{region.lower()}_{metric}"
        for region in REGIONS
        for metric in REGION_ITEM_METRICS
    ],
    "pose_pvrig_record_inventory_json",
    "pose_vhh_record_inventory_json",
    "region_pose_vhh_record_inventory_json",
    "reference_pvrl2_record_inventory_json",
    "reference_pvrl2_record_inventory_sha256",
    "region_reference_pvrl2_record_inventory_json",
    "region_reference_pvrl2_record_inventory_sha256",
    "pose_score_payload_sha256",
    "region_score_payload_sha256",
    "metrics_row_sha256",
]

MODEL_RE = re.compile(r"^cluster_(\d+)_model_(\d+)$")
FORBIDDEN_RAW_KEYS = {
    "classification",
    "blocker_class",
    "consensus_class",
    "geometry_class",
    "geometry_tier",
    "tier",
    "label",
    "relevance",
}


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ContractError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def row_hash(row: Mapping[str, Any], hash_field: str) -> str:
    return sha256_json({key: row[key] for key in row if key != hash_field})


def canonical_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_path(raw: str, manifest: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = manifest.parent / path
    return path.resolve()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ContractError(f"Input manifest is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ContractError(f"Input manifest has no rows: {path}")
    return rows


def natural_model_key(model: str) -> tuple[int, int]:
    match = MODEL_RE.fullmatch(model)
    if not match:
        raise ContractError(f"Invalid HADDOCK model identifier: {model!r}")
    return int(match.group(1)), int(match.group(2))


def validate_cdr_range(value: str, field: str, sample_id: str) -> str:
    text = value.strip()
    match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", text)
    if not match or int(match.group(1)) > int(match.group(2)):
        raise ContractError(f"Invalid {field} for {sample_id}: {value!r}")
    return f"{int(match.group(1))}-{int(match.group(2))}"


def discover_models(
    workdir: Path,
    baseline: str,
    pose_dir_template: str,
    suffix_template: str,
) -> tuple[Path, dict[str, Path]]:
    try:
        relative_dir = pose_dir_template.format(baseline=baseline)
        suffix = suffix_template.format(baseline=baseline)
    except KeyError as error:
        raise ContractError(f"Unsupported pose template placeholder: {error}") from error
    directory = workdir / relative_dir
    if not directory.is_dir():
        raise ContractError(f"Aligned pose directory is missing: {directory}")
    files = sorted(directory.glob("*.pdb"), key=lambda item: item.name)
    if not files:
        raise ContractError(f"No aligned PDB poses found: {directory}")
    models: dict[str, Path] = {}
    for path in files:
        if not path.name.endswith(suffix):
            raise ContractError(
                f"Unexpected PDB in aligned pose directory {directory}: {path.name}"
            )
        model = path.name[: -len(suffix)]
        natural_model_key(model)
        if model in models:
            raise ContractError(f"Duplicate model {model!r} in {directory}")
        models[model] = path.resolve()
    return directory.resolve(), models


def source_case_rows(
    source_dataset: str,
    manifest: Path,
    rows: Sequence[dict[str, str]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if source_dataset == "known_positive_calibration":
        mapping = {
            "order": "recommended_order",
            "id": "calibration_name",
            "role": "validation_role",
            "descriptor": "sequence_type",
            "usage": "usage_boundary",
        }
    else:
        mapping = {
            "order": "panel_order",
            "id": "mutant_name",
            "role": "intended_role",
            "descriptor": "control_type",
            "usage": "",
        }
    required = {
        mapping["order"],
        mapping["id"],
        "family",
        "workdir",
        "cdr1_range",
        "cdr2_range",
        "cdr3_range",
        mapping["role"],
        mapping["descriptor"],
    }
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ContractError(f"{manifest} lacks required fields: {missing}")
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for raw in rows:
        sample_id = raw[mapping["id"]].strip()
        if not sample_id or sample_id in seen_ids:
            raise ContractError(f"Missing or duplicate sample id in {manifest}: {sample_id!r}")
        try:
            source_order = int(raw[mapping["order"]])
        except ValueError as error:
            raise ContractError(f"Invalid source order for {sample_id}") from error
        if source_order in seen_orders:
            raise ContractError(f"Duplicate source order {source_order} in {manifest}")
        seen_ids.add(sample_id)
        seen_orders.add(source_order)
        usage_boundary = (
            raw.get(mapping["usage"], "").strip()
            if mapping["usage"]
            else "development_calibration_control_only_not_assumed_negative"
        )
        result.append(
            {
                "source_dataset": source_dataset,
                "source_order": source_order,
                "sample_id": sample_id,
                "family": raw["family"].strip(),
                "evidence_role": raw[mapping["role"]].strip(),
                "control_descriptor": raw[mapping["descriptor"]].strip(),
                "usage_boundary": usage_boundary,
                "workdir": resolve_path(raw["workdir"], manifest),
                "cdr1_range": validate_cdr_range(raw["cdr1_range"], "cdr1_range", sample_id),
                "cdr2_range": validate_cdr_range(raw["cdr2_range"], "cdr2_range", sample_id),
                "cdr3_range": validate_cdr_range(raw["cdr3_range"], "cdr3_range", sample_id),
                "source_manifest": manifest.resolve(),
                "source_manifest_row_sha256": sha256_json(raw),
            }
        )
    return sorted(result, key=lambda row: (row["source_order"], row["sample_id"]))


def optional_tool_snapshot(path: Path, required: bool) -> dict[str, str]:
    resolved = path.resolve()
    if not resolved.is_file():
        if required:
            raise ContractError(f"Required V1.2 scoring tool is missing: {resolved}")
        return {"path": canonical_path(resolved, WORKSPACE_ROOT), "sha256": ""}
    return {"path": canonical_path(resolved, WORKSPACE_ROOT), "sha256": sha256_file(resolved)}


def build_pose_manifest(
    config: BuildConfig,
    *,
    require_tools: bool,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, str]]:
    positive_rows = read_csv(config.positive_manifest)
    mutant_rows = read_csv(config.mutant_manifest)
    if len(positive_rows) != config.contract.positive_cases:
        raise ContractError(
            f"Expected {config.contract.positive_cases} positive cases, found {len(positive_rows)}"
        )
    if len(mutant_rows) != config.contract.mutant_cases:
        raise ContractError(
            f"Expected {config.contract.mutant_cases} mutant cases, found {len(mutant_rows)}"
        )

    required_inputs = {
        "positive_manifest": config.positive_manifest.resolve(),
        "mutant_manifest": config.mutant_manifest.resolve(),
        "hotspots": config.hotspots.resolve(),
        **{
            f"reference_{baseline}": path.resolve()
            for baseline, path in config.references.items()
        },
    }
    input_hashes = {name: sha256_file(path) for name, path in required_inputs.items()}
    tools = {
        "pose_scorer": optional_tool_snapshot(config.pose_scorer, require_tools),
        "region_scorer": optional_tool_snapshot(config.region_scorer, require_tools),
        "scoring_helper": optional_tool_snapshot(config.scoring_helper, require_tools),
    }
    source_manifest_hash = {
        "known_positive_calibration": input_hashes["positive_manifest"],
        "mutant_or_reference_control": input_hashes["mutant_manifest"],
    }
    source_manifest_path = {
        "known_positive_calibration": config.positive_manifest.resolve(),
        "mutant_or_reference_control": config.mutant_manifest.resolve(),
    }
    cases = [
        *source_case_rows(
            "known_positive_calibration", config.positive_manifest, positive_rows
        ),
        *source_case_rows(
            "mutant_or_reference_control", config.mutant_manifest, mutant_rows
        ),
    ]

    rows: list[dict[str, str]] = []
    case_inventories: list[dict[str, Any]] = []
    pose_counts: Counter[tuple[str, str]] = Counter()
    pose_files: set[Path] = set()
    for case in cases:
        discovered: dict[str, dict[str, Path]] = {}
        directories: dict[str, Path] = {}
        for baseline in BASELINES:
            directory, model_paths = discover_models(
                case["workdir"],
                baseline,
                config.pose_dir_template,
                config.pose_suffix_template,
            )
            directories[baseline] = directory
            discovered[baseline] = model_paths
        model_sets = {baseline: set(models) for baseline, models in discovered.items()}
        if model_sets["8x6b"] != model_sets["9e6y"]:
            missing_8 = sorted(model_sets["9e6y"] - model_sets["8x6b"], key=natural_model_key)
            missing_9 = sorted(model_sets["8x6b"] - model_sets["9e6y"], key=natural_model_key)
            raise ContractError(
                f"Mismatched aligned models for {case['sample_id']}: "
                f"missing_8x6b={missing_8}, missing_9e6y={missing_9}"
            )
        models = sorted(model_sets["8x6b"], key=natural_model_key)
        case_inventories.append(
            {
                "source_dataset": case["source_dataset"],
                "source_order": case["source_order"],
                "sample_id": case["sample_id"],
                "pose_count_per_baseline": len(models),
                "models": models,
                "pose_directories": {
                    baseline: canonical_path(path, config.workspace_root)
                    for baseline, path in directories.items()
                },
            }
        )
        for model in models:
            cluster_index, model_index = natural_model_key(model)
            for baseline, baseline_spec in BASELINES.items():
                pose_path = discovered[baseline][model]
                pose_files.add(pose_path)
                reference = config.references[baseline].resolve()
                source = case["source_dataset"]
                row: dict[str, Any] = {
                    "schema_version": "pvrig_v1_2_sensitivity_pose_manifest_v1",
                    "protocol_id": PROTOCOL_ID,
                    "sensitivity_dataset_id": SENSITIVITY_DATASET_ID,
                    "dataset_purpose": DATASET_PURPOSE,
                    "formal_eligible": "false",
                    "threshold_freeze_eligible": "false",
                    "pose_source_protocol": config.pose_source_protocol,
                    "source_dataset": source,
                    "source_order": str(case["source_order"]),
                    "sample_id": case["sample_id"],
                    "family": case["family"],
                    "evidence_role": case["evidence_role"],
                    "control_descriptor": case["control_descriptor"],
                    "usage_boundary": case["usage_boundary"],
                    "model": model,
                    "cluster_index": str(cluster_index),
                    "model_index": str(model_index),
                    "baseline": baseline,
                    "source_pose_relpath": canonical_path(pose_path, config.workspace_root),
                    "source_pose_sha256": sha256_file(pose_path),
                    "source_manifest_relpath": canonical_path(
                        source_manifest_path[source], config.workspace_root
                    ),
                    "source_manifest_sha256": source_manifest_hash[source],
                    "source_manifest_row_sha256": case["source_manifest_row_sha256"],
                    "reference_relpath": canonical_path(reference, config.workspace_root),
                    "reference_sha256": input_hashes[f"reference_{baseline}"],
                    "hotspots_relpath": canonical_path(config.hotspots, config.workspace_root),
                    "hotspots_sha256": input_hashes["hotspots"],
                    "pose_scorer_relpath": tools["pose_scorer"]["path"],
                    "pose_scorer_sha256": tools["pose_scorer"]["sha256"],
                    "region_scorer_relpath": tools["region_scorer"]["path"],
                    "region_scorer_sha256": tools["region_scorer"]["sha256"],
                    "scoring_helper_relpath": tools["scoring_helper"]["path"],
                    "scoring_helper_sha256": tools["scoring_helper"]["sha256"],
                    "cdr1_range": case["cdr1_range"],
                    "cdr2_range": case["cdr2_range"],
                    "cdr3_range": case["cdr3_range"],
                    "pose_pvrig_chain": "B",
                    "pose_vhh_chain": "A",
                    "ref_pvrig_chain": str(baseline_spec["ref_pvrig_chain"]),
                    "ref_pvrl2_chain": str(baseline_spec["ref_pvrl2_chain"]),
                    "hotspot_ref_column": str(baseline_spec["hotspot_ref_column"]),
                }
                row = {key: str(row.get(key, "")) for key in MANIFEST_FIELDS if key != "manifest_row_sha256"}
                row["manifest_row_sha256"] = row_hash(row, "manifest_row_sha256")
                rows.append(row)
                pose_counts[(source, baseline)] += 1

    expected_counts = {
        ("known_positive_calibration", baseline): config.contract.positive_poses_per_baseline
        for baseline in BASELINES
    }
    expected_counts.update(
        {
            ("mutant_or_reference_control", baseline): config.contract.mutant_poses_per_baseline
            for baseline in BASELINES
        }
    )
    if pose_counts != Counter(expected_counts):
        raise ContractError(
            f"Pose-count contract mismatch: observed={dict(pose_counts)}, "
            f"expected={expected_counts}"
        )
    if len(rows) != config.contract.total_rows:
        raise ContractError(
            f"Expected {config.contract.total_rows} manifest rows, found {len(rows)}"
        )

    inventory = {
        "case_inventories": case_inventories,
        "case_inventory_sha256": sha256_json(case_inventories),
        "observed": {
            "positive_cases": len(positive_rows),
            "mutant_cases": len(mutant_rows),
            "positive_poses_per_baseline": pose_counts[
                ("known_positive_calibration", "8x6b")
            ],
            "mutant_poses_per_baseline": pose_counts[
                ("mutant_or_reference_control", "8x6b")
            ],
            "rows_by_baseline": dict(sorted(Counter(row["baseline"] for row in rows).items())),
            "total_rows": len(rows),
        },
    }
    frozen_hashes = {
        str(path.resolve()): sha256_file(path)
        for path in {*required_inputs.values(), *pose_files}
    }
    for tool in (config.pose_scorer, config.region_scorer, config.scoring_helper):
        if tool.is_file():
            frozen_hashes[str(tool.resolve())] = sha256_file(tool.resolve())
    return rows, {"inputs": input_hashes, "tools": tools, **inventory}, frozen_hashes


def assert_no_classification_keys(value: Any, context: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = key.lower()
            if (
                lowered in FORBIDDEN_RAW_KEYS
                or lowered.endswith("_classification")
                or lowered.endswith("_blocker_class")
                or lowered.endswith("_geometry_class")
                or lowered.endswith("_geometry_tier")
                or lowered.endswith("_relevance_label")
            ):
                raise ContractError(f"Classification field {key!r} appeared in {context}")
            assert_no_classification_keys(nested, context)
    elif isinstance(value, list):
        for nested in value:
            assert_no_classification_keys(nested, context)


def run_scorer(command: Sequence[str], output: Path, label: str) -> dict[str, Any]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise ContractError(
            f"{label} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[-2000:]}"
        )
    if not output.is_file():
        raise ContractError(f"{label} did not create {output}")
    try:
        report = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"Invalid JSON from {label}: {output}") from error
    assert_no_classification_keys(report, label)
    return report


def scalar_text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"Non-finite metric {field}: {value}")
        return format(value, ".17g")
    if isinstance(value, str):
        return value
    raise ContractError(f"Expected scalar metric {field}, got {type(value).__name__}")


def required_mapping(parent: Mapping[str, Any], key: str, context: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"Missing mapping {key!r} in {context}")
    return value


def assert_inventory_agreement(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    fields: Sequence[str],
    context: str,
) -> None:
    disagreements = {
        field: (left.get(field), right.get(field))
        for field in fields
        if left.get(field) != right.get(field)
    }
    if disagreements:
        raise ContractError(f"Scorer record inventories disagree for {context}: {disagreements}")


def assert_atom_only_reference_policy(
    report: Mapping[str, Any],
    inventory: Mapping[str, Any],
    context: str,
) -> None:
    policy = str(report.get("reference_pvrl2_selection", ""))
    selection_rule = str(inventory.get("selection_rule", ""))
    if "ATOM" not in policy or "only" not in policy.lower():
        raise ContractError(f"{context} did not declare an ATOM-only reference policy: {policy!r}")
    if "all HETATM excluded" not in selection_rule:
        raise ContractError(
            f"{context} reference inventory did not exclude all HETATM: {selection_rule!r}"
        )


def flatten_metric_row(
    manifest_row: Mapping[str, str],
    pose_report: Mapping[str, Any],
    region_report: Mapping[str, Any],
) -> dict[str, str]:
    for name, report in (("pose scorer", pose_report), ("region scorer", region_report)):
        if report.get("scoring_semantics_version") != SCORING_SEMANTICS_VERSION:
            raise ContractError(
                f"Unexpected scoring semantics from {name}: "
                f"{report.get('scoring_semantics_version')!r}"
            )
    pose_inventory = required_mapping(pose_report, "record_inventory", "pose scorer")
    pose_chains = required_mapping(pose_inventory, "pose", "pose scorer inventory")
    region_inventory = required_mapping(region_report, "record_inventory", "region scorer")
    region_pose = required_mapping(region_inventory, "pose", "region scorer inventory")
    pvrig_inventory = required_mapping(pose_chains, "pvrig_chain", "pose scorer inventory")
    vhh_inventory = required_mapping(pose_chains, "vhh_chain", "pose scorer inventory")
    region_vhh_inventory = required_mapping(region_pose, "vhh_chain", "region scorer inventory")
    reference_inventory = required_mapping(
        pose_inventory, "reference_pvrl2_chain", "pose scorer inventory"
    )
    region_reference_inventory = required_mapping(
        region_inventory, "reference_pvrl2_chain", "region scorer inventory"
    )
    assert_atom_only_reference_policy(pose_report, reference_inventory, "pose scorer")
    assert_atom_only_reference_policy(region_report, region_reference_inventory, "region scorer")
    assert_inventory_agreement(
        vhh_inventory,
        region_vhh_inventory,
        (
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
        ),
        "pose VHH chain",
    )
    assert_inventory_agreement(
        reference_inventory,
        region_reference_inventory,
        (
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
        ),
        "reference PVRL2 chain",
    )

    row = dict(manifest_row)
    row.update(
        {
            "pose_score_schema_version": scalar_text(
                pose_report.get("schema_version"), "pose_score_schema_version"
            ),
            "region_score_schema_version": scalar_text(
                region_report.get("schema_version"), "region_score_schema_version"
            ),
            "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        }
    )
    for metric in POSE_METRICS:
        if metric not in pose_report:
            raise ContractError(f"Pose scorer omitted metric {metric}")
        row[metric] = scalar_text(pose_report[metric], metric)
    for metric in REGION_TOTAL_METRICS:
        if metric not in region_report:
            raise ContractError(f"Region scorer omitted metric {metric}")
        row[metric] = scalar_text(region_report[metric], metric)
    regions = required_mapping(region_report, "regions", "region scorer")
    for region in REGIONS:
        values = required_mapping(regions, region, f"region scorer {region}")
        for metric in REGION_ITEM_METRICS:
            if metric not in values:
                raise ContractError(f"Region scorer omitted {region}.{metric}")
            row[f"{region.lower()}_{metric}"] = scalar_text(
                values[metric], f"{region}.{metric}"
            )
    row.update(
        {
            "pose_pvrig_record_inventory_json": canonical_json(pvrig_inventory),
            "pose_vhh_record_inventory_json": canonical_json(vhh_inventory),
            "region_pose_vhh_record_inventory_json": canonical_json(
                region_vhh_inventory
            ),
            "reference_pvrl2_record_inventory_json": canonical_json(reference_inventory),
            "reference_pvrl2_record_inventory_sha256": sha256_json(reference_inventory),
            "region_reference_pvrl2_record_inventory_json": canonical_json(
                region_reference_inventory
            ),
            "region_reference_pvrl2_record_inventory_sha256": sha256_json(
                region_reference_inventory
            ),
            "pose_score_payload_sha256": sha256_json(pose_report),
            "region_score_payload_sha256": sha256_json(region_report),
        }
    )
    normalized = {
        key: str(row.get(key, "")) for key in METRICS_FIELDS if key != "metrics_row_sha256"
    }
    normalized["metrics_row_sha256"] = row_hash(normalized, "metrics_row_sha256")
    return normalized


def rescore_rows(config: BuildConfig, manifest_rows: Sequence[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    metrics: list[dict[str, str]] = []
    reference_inventories: dict[str, set[str]] = defaultdict(set)
    aggregate_pose_inventory: dict[str, Counter[str]] = {
        "pvrig": Counter(),
        "vhh": Counter(),
    }
    with tempfile.TemporaryDirectory(prefix="pvrig-v1-2-rescore-") as tmp:
        temp_root = Path(tmp)
        for index, row in enumerate(manifest_rows):
            pose_path = config.workspace_root / row["source_pose_relpath"]
            if not pose_path.is_file():
                pose_path = Path(row["source_pose_relpath"])
            reference = config.references[row["baseline"]].resolve()
            pose_json = temp_root / f"{index:04d}_pose.json"
            region_json = temp_root / f"{index:04d}_region.json"
            pose_report = run_scorer(
                [
                    sys.executable,
                    str(config.pose_scorer),
                    "--pose-pdb",
                    str(pose_path),
                    "--reference-pdb",
                    str(reference),
                    "--pvrig-chain",
                    row["pose_pvrig_chain"],
                    "--vhh-chain",
                    row["pose_vhh_chain"],
                    "--ref-pvrig-chain",
                    row["ref_pvrig_chain"],
                    "--ref-pvrl2-chain",
                    row["ref_pvrl2_chain"],
                    "--hotspots-csv",
                    str(config.hotspots),
                    "--hotspot-ref-column",
                    row["hotspot_ref_column"],
                    "--cdr-ranges",
                    (
                        f"CDR1:{row['cdr1_range']},CDR2:{row['cdr2_range']},"
                        f"CDR3:{row['cdr3_range']}"
                    ),
                    "--assume-aligned",
                    "--out-json",
                    str(pose_json),
                ],
                pose_json,
                f"pose scorer for {row['sample_id']}/{row['model']}/{row['baseline']}",
            )
            region_report = run_scorer(
                [
                    sys.executable,
                    str(config.region_scorer),
                    "--pose-pdb",
                    str(pose_path),
                    "--reference-pdb",
                    str(reference),
                    "--vhh-chain",
                    row["pose_vhh_chain"],
                    "--ref-pvrl2-chain",
                    row["ref_pvrl2_chain"],
                    "--cdr1",
                    row["cdr1_range"],
                    "--cdr2",
                    row["cdr2_range"],
                    "--cdr3",
                    row["cdr3_range"],
                    "--out-json",
                    str(region_json),
                ],
                region_json,
                f"region scorer for {row['sample_id']}/{row['model']}/{row['baseline']}",
            )
            metric_row = flatten_metric_row(row, pose_report, region_report)
            metrics.append(metric_row)
            reference_inventories[row["baseline"]].add(
                metric_row["reference_pvrl2_record_inventory_json"]
            )
            for label, field in (
                ("pvrig", "pose_pvrig_record_inventory_json"),
                ("vhh", "pose_vhh_record_inventory_json"),
            ):
                inventory = json.loads(metric_row[field])
                for key, value in inventory.items():
                    if isinstance(value, int):
                        aggregate_pose_inventory[label][key] += value

    for baseline, inventories in reference_inventories.items():
        if len(inventories) != 1:
            raise ContractError(
                f"Reference record inventory changed across {baseline} rows: {len(inventories)} variants"
            )
    record_inventory = {
        "metric_rows": len(metrics),
        "reference_pvrl2_by_baseline": {
            baseline: json.loads(next(iter(inventories)))
            for baseline, inventories in sorted(reference_inventories.items())
        },
        "pose_inventory_numeric_totals": {
            label: dict(sorted(counter.items()))
            for label, counter in aggregate_pose_inventory.items()
        },
    }
    return metrics, record_inventory


def write_csv_atomic(path: Path, rows: Sequence[Mapping[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def verify_frozen_files(frozen_hashes: Mapping[str, str]) -> None:
    mismatches = []
    for raw_path, expected in sorted(frozen_hashes.items()):
        path = Path(raw_path)
        observed = sha256_file(path)
        if observed != expected:
            mismatches.append(f"{path}:{observed}!={expected}")
    if mismatches:
        raise ContractError("Inputs changed while building package: " + "; ".join(mismatches))


def hash_chain(rows: Iterable[Mapping[str, str]], field: str) -> str:
    values = [row[field] for row in rows]
    return hashlib.sha256(("\n".join(values) + "\n").encode("ascii")).hexdigest()


def build_package(config: BuildConfig, *, manifest_only: bool) -> dict[str, Any]:
    rows, evidence, frozen_hashes = build_pose_manifest(
        config, require_tools=not manifest_only
    )
    metrics: list[dict[str, str]] = []
    score_inventory: dict[str, Any] = {}
    if not manifest_only:
        metrics, score_inventory = rescore_rows(config, rows)
        if len(metrics) != len(rows):
            raise ContractError(f"Expected {len(rows)} metric rows, found {len(metrics)}")
    verify_frozen_files(frozen_hashes)

    manifest_path = config.outdir / POSE_MANIFEST_NAME
    metrics_path = config.outdir / METRICS_NAME
    audit_path = config.outdir / AUDIT_NAME
    write_csv_atomic(manifest_path, rows, MANIFEST_FIELDS)
    if metrics:
        write_csv_atomic(metrics_path, metrics, METRICS_FIELDS)
    elif metrics_path.exists():
        metrics_path.unlink()

    output_hashes = {
        "pose_manifest": sha256_file(manifest_path),
        "pose_manifest_row_hash_chain": hash_chain(rows, "manifest_row_sha256"),
    }
    if metrics:
        output_hashes.update(
            {
                "continuous_metrics": sha256_file(metrics_path),
                "continuous_metrics_row_hash_chain": hash_chain(
                    metrics, "metrics_row_sha256"
                ),
            }
        )
    audit = {
        "schema_version": "pvrig_v1_2_sensitivity_package_audit_v1",
        "status": (
            "PASS_V1_2_DEVELOPMENT_SENSITIVITY_RESCORE_BUILT"
            if metrics
            else "PASS_V1_2_DEVELOPMENT_SENSITIVITY_MANIFEST_BUILT"
        ),
        "mode": "full_rescore" if metrics else "manifest_only",
        "protocol_id": PROTOCOL_ID,
        "sensitivity_dataset_id": SENSITIVITY_DATASET_ID,
        "dataset_purpose": DATASET_PURPOSE,
        "formal_eligible": False,
        "threshold_freeze_eligible": False,
        "pose_source_protocol": config.pose_source_protocol,
        "claim_boundary": CLAIM_BOUNDARY,
        "thresholds_or_classes_applied": False,
        "fixed_k_pose_ensemble": False,
        "expected_contract": config.contract.as_dict(),
        "observed_inventory": evidence["observed"],
        "case_inventory_sha256": evidence["case_inventory_sha256"],
        "case_inventories": evidence["case_inventories"],
        "score_record_inventory": score_inventory,
        "input_sha256": evidence["inputs"],
        "toolchain": evidence["tools"],
        "toolchain_complete": all(
            item["sha256"] for item in evidence["tools"].values()
        ),
        "output_sha256": output_hashes,
    }
    write_json_atomic(audit_path, audit)
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-manifest", type=Path, default=DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--pose-scorer", type=Path, default=DEFAULT_POSE_SCORER)
    parser.add_argument("--region-scorer", type=Path, default=DEFAULT_REGION_SCORER)
    parser.add_argument("--scoring-helper", type=Path, default=DEFAULT_SCORING_HELPER)
    parser.add_argument("--hotspots", type=Path, default=DEFAULT_HOTSPOTS)
    parser.add_argument("--reference-8x6b", type=Path, default=BASELINES["8x6b"]["reference"])
    parser.add_argument("--reference-9e6y", type=Path, default=BASELINES["9e6y"]["reference"])
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--pose-dir-template", default="haddock3/top_models_aligned_to_{baseline}")
    parser.add_argument("--pose-suffix-template", default="_aligned_to_{baseline}.pdb")
    parser.add_argument("--pose-source-protocol", default=POSE_SOURCE_PROTOCOL)
    parser.add_argument("--expected-positive-cases", type=int, default=11)
    parser.add_argument("--expected-mutant-cases", type=int, default=36)
    parser.add_argument("--expected-positive-poses-per-baseline", type=int, default=109)
    parser.add_argument("--expected-mutant-poses-per-baseline", type=int, default=357)
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Freeze pose/reference hashes without importing or executing scorer files.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = BuildConfig(
        positive_manifest=args.positive_manifest.resolve(),
        mutant_manifest=args.mutant_manifest.resolve(),
        pose_scorer=args.pose_scorer.resolve(),
        region_scorer=args.region_scorer.resolve(),
        scoring_helper=args.scoring_helper.resolve(),
        hotspots=args.hotspots.resolve(),
        references={
            "8x6b": args.reference_8x6b.resolve(),
            "9e6y": args.reference_9e6y.resolve(),
        },
        outdir=args.outdir.resolve(),
        pose_dir_template=args.pose_dir_template,
        pose_suffix_template=args.pose_suffix_template,
        pose_source_protocol=args.pose_source_protocol,
        contract=DatasetContract(
            positive_cases=args.expected_positive_cases,
            mutant_cases=args.expected_mutant_cases,
            positive_poses_per_baseline=args.expected_positive_poses_per_baseline,
            mutant_poses_per_baseline=args.expected_mutant_poses_per_baseline,
        ),
    )
    if min(config.contract.as_dict().values()) <= 0:
        print("ERROR: expected dataset-contract counts must be positive", file=sys.stderr)
        return 2
    try:
        audit = build_package(config, manifest_only=args.manifest_only)
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": audit["status"],
        "formal_eligible": audit["formal_eligible"],
        "total_rows": audit["observed_inventory"]["total_rows"],
        "outdir": str(config.outdir),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
