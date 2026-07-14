#!/usr/bin/env python3
"""Summarize legacy-inclusive versus V1.2 ATOM-only scorer sensitivity.

This script compares the same legacy variable-size final poses.  Any class
transition is produced by replaying the frozen OLD V1.1 rule implementation
as a diagnostic only.  It is not a V1.2 label and is ineligible for threshold
fitting or formal Docking Gold claims.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
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
ANALYSIS_ID = "V1_2_ATOM_ONLY_FINAL_POSE_SENSITIVITY_DELTA_V1"
CLAIM_BOUNDARY = (
    "Development sensitivity diagnostic on legacy variable-size final poses only; "
    "OLD V1.1 rule transitions are not V1.2 labels, not threshold-fitting evidence, "
    "not formal Docking Gold, and not experimental binding or blocking truth."
)

DEFAULT_RUN_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_2_calibration_sensitivity"
)
DEFAULT_METRICS = DEFAULT_RUN_ROOT / "pvrig_v1_2_sensitivity_continuous_metrics.csv"
DEFAULT_RESCORE_AUDIT = DEFAULT_RUN_ROOT / "pvrig_v1_2_sensitivity_audit.json"
DEFAULT_POSITIVE_MANIFEST = (
    WORKSPACE_ROOT / "docking/calibration/patent_success_validation/batch_manifest.csv"
)
DEFAULT_MUTANT_MANIFEST = (
    WORKSPACE_ROOT / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
)
DEFAULT_OLD_RULES = (
    WORKSPACE_ROOT / "docking/success_case_validation/blocker_judgment_rules_v2.json"
)
DEFAULT_OLD_CLASSIFIER = (
    WORKSPACE_ROOT / "docking/success_case_validation/apply_blocker_judgment.py"
)
DEFAULT_DELTA_CSV = (
    EXP_DIR / "audits/phase2_v3_p2_v1_2_final_pose_sensitivity_deltas.csv"
)
DEFAULT_AUDIT_JSON = (
    EXP_DIR / "audits/phase2_v3_p2_v1_2_final_pose_sensitivity_audit.json"
)
DEFAULT_REPORT_MD = (
    EXP_DIR / "reports/PVRIG_V3_P2_V1_2_FINAL_POSE_SENSITIVITY_ZH.md"
)

EXPECTED_METRICS_SHA256 = "ace4ef1559923a4c39739ca84d38012b09da277ec94976959bb2c52f2ac16f0e"
EXPECTED_RESCORE_AUDIT_SHA256 = "25a4a9c937c34ec4579b026c7c8a5c8fff4c1123647327721d1bd92a2b47a565"
EXPECTED_OLD_RULES_SHA256 = "60424c514d0e1c4f32bfec28631b969ed511c89babb4a73dcecf504e1e6a16a5"
EXPECTED_OLD_CLASSIFIER_SHA256 = "c5f6f96d4821863dd14dc201807d8c863226876507df36a9e78b7a47e7df2654"

EXPECTED_ROWS = 932
EXPECTED_SAMPLES = 47
BASELINES = ("8x6b", "9e6y")
MODEL_RE = re.compile(r"^cluster_(\d+)_model_(\d+)$")

METRIC_SPECS: Mapping[str, tuple[str, str]] = {
    "total_atom_contacts": (
        "total_vhh_pvrl2_atom_occlusion",
        "total_occluding_atom_contact_count",
    ),
    "total_residue_pairs": (
        "total_vhh_pvrl2_residue_pair_occlusion",
        "total_occluding_residue_pair_count",
    ),
    "cdr3_atom_contacts": (
        "cdr3_atom_occlusion",
        "cdr3_occluding_atom_contact_count",
    ),
    "cdr3_residue_pairs": (
        "cdr3_residue_pair_occlusion",
        "cdr3_occluding_residue_pair_count",
    ),
    "cdr3_atom_fraction": (
        "cdr3_atom_occlusion_fraction",
        "cdr3_occlusion_fraction_of_total",
    ),
    "cdr3_residue_pair_fraction": (
        "cdr3_residue_pair_occlusion_fraction",
        "cdr3_occluding_residue_pair_fraction_of_total",
    ),
}

DELTA_FIELDS = [
    "schema_version",
    "protocol_id",
    "analysis_id",
    "claim_boundary",
    "diagnostic_only",
    "v1_2_label",
    "formal_eligible",
    "threshold_freeze_eligible",
    "source_dataset",
    "source_order",
    "sample_id",
    "family",
    "mutation_class",
    "control_type",
    "source_descriptor",
    "model",
    "baseline",
    "source_pose_sha256",
    "v1_2_metrics_row_sha256",
    "legacy_occlusion_relpath",
    "legacy_occlusion_sha256",
    "legacy_classification_relpath",
    "legacy_classification_sha256",
    "legacy_hotspot_overlap_count",
    "v1_2_hotspot_overlap_count",
    "hotspot_overlap_delta",
]
for _metric_name in METRIC_SPECS:
    DELTA_FIELDS.extend(
        [
            f"legacy_inclusive_{_metric_name}",
            f"v1_2_atom_only_{_metric_name}",
            f"delta_{_metric_name}",
            f"ratio_new_over_old_{_metric_name}",
            f"percent_change_{_metric_name}",
        ]
    )
DELTA_FIELDS.extend(
    [
        "reference_protein_atom_heavy_atom_count",
        "reference_excluded_hetatm_heavy_atom_count",
        "reference_excluded_hoh_heavy_atom_count",
        "reference_excluded_edo_heavy_atom_count",
        "legacy_v1_1_class",
        "v1_2_metrics_old_rule_diagnostic_class",
        "old_rule_diagnostic_transition",
        "old_rule_class_changed",
        "delta_row_sha256",
    ]
)


@dataclass(frozen=True)
class SummaryConfig:
    metrics: Path
    rescore_audit: Path
    positive_manifest: Path
    mutant_manifest: Path
    old_rules: Path
    old_classifier: Path
    delta_csv: Path
    audit_json: Path
    report_md: Path
    expected_metrics_sha256: str = EXPECTED_METRICS_SHA256
    expected_rescore_audit_sha256: str = EXPECTED_RESCORE_AUDIT_SHA256
    expected_old_rules_sha256: str = EXPECTED_OLD_RULES_SHA256
    expected_old_classifier_sha256: str = EXPECTED_OLD_CLASSIFIER_SHA256
    expected_rows: int = EXPECTED_ROWS
    expected_samples: int = EXPECTED_SAMPLES
    workspace_root: Path = WORKSPACE_ROOT


class ClosureError(RuntimeError):
    """Raised when row, numeric, or hash closure is not exact."""


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ClosureError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def row_hash(row: Mapping[str, Any], field: str) -> str:
    return sha256_json({key: row[key] for key in row if key != field})


def canonical_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ClosureError(f"CSV is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise ClosureError(f"CSV has no rows: {path}")
    return rows


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClosureError(f"Invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ClosureError(f"JSON root must be an object: {path}")
    return value


def finite_float(value: Any, field: str, context: str) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ClosureError(f"Invalid numeric {field} in {context}: {value!r}") from error
    if not math.isfinite(number):
        raise ClosureError(f"Non-finite numeric {field} in {context}: {value!r}")
    return number


def number_text(value: float) -> str:
    if not math.isfinite(value):
        raise ClosureError(f"Refusing to serialize non-finite value: {value}")
    return format(value, ".17g")


def natural_key(model: str) -> tuple[int, int]:
    match = MODEL_RE.fullmatch(model)
    if not match:
        raise ClosureError(f"Invalid model identifier: {model!r}")
    return int(match.group(1)), int(match.group(2))


def verify_hash(path: Path, expected: str, label: str) -> str:
    observed = sha256_file(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ClosureError(f"Missing valid expected SHA256 for {label}")
    if observed != expected:
        raise ClosureError(f"{label} SHA256 mismatch: {observed}!={expected}")
    return observed


def load_old_classifier(path: Path):
    module_name = f"old_v1_1_blocker_classifier_{sha256_file(path)[:12]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ClosureError(f"Cannot load OLD V1.1 classifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    for required in ("load_rules", "classify"):
        if not hasattr(module, required):
            raise ClosureError(f"OLD V1.1 classifier lacks {required}")
    return module


def manifest_row_digest(row: Mapping[str, str]) -> str:
    return sha256_json(dict(row))


def resolve_workdir(value: str, manifest: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = manifest.parent / path
    return path.resolve()


def load_case_metadata(config: SummaryConfig) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    manifests = {
        "known_positive_calibration": config.positive_manifest.resolve(),
        "mutant_or_reference_control": config.mutant_manifest.resolve(),
    }
    hashes = {source: sha256_file(path) for source, path in manifests.items()}
    result: dict[str, dict[str, Any]] = {}
    for source, manifest in manifests.items():
        rows = read_csv(manifest)
        for raw in rows:
            if source == "known_positive_calibration":
                sample_id = raw.get("calibration_name", "").strip()
                source_order = raw.get("recommended_order", "").strip()
                mutation_class = "known_positive_calibration"
                control_type = "known_positive_calibration"
                source_descriptor = raw.get("sequence_type", "").strip()
            else:
                sample_id = raw.get("mutant_name", "").strip()
                source_order = raw.get("panel_order", "").strip()
                mutation_class = raw.get("mutation_class", "").strip()
                control_type = raw.get("control_type", "").strip()
                source_descriptor = mutation_class
            if not sample_id or sample_id in result:
                raise ClosureError(f"Missing or duplicate sample id: {sample_id!r}")
            try:
                order_int = int(source_order)
            except ValueError as error:
                raise ClosureError(f"Invalid source order for {sample_id}: {source_order!r}") from error
            result[sample_id] = {
                "source_dataset": source,
                "source_order": order_int,
                "family": raw.get("family", "").strip(),
                "mutation_class": mutation_class,
                "control_type": control_type,
                "source_descriptor": source_descriptor,
                "workdir": resolve_workdir(raw.get("workdir", ""), manifest),
                "source_manifest": manifest,
                "source_manifest_sha256": hashes[source],
                "source_manifest_row_sha256": manifest_row_digest(raw),
            }
    if len(result) != config.expected_samples:
        raise ClosureError(
            f"Expected {config.expected_samples} source samples, found {len(result)}"
        )
    return result, hashes


def unique_rows(
    rows: Sequence[dict[str, str]],
    key_fields: Sequence[str],
    context: str,
) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row.get(field, "").strip() for field in key_fields)
        if any(not value for value in key):
            raise ClosureError(f"Blank key {key_fields} in {context}: {key}")
        if key in result:
            raise ClosureError(f"Duplicate key {key} in {context}")
        result[key] = row
    return result


def load_legacy_rows(
    config: SummaryConfig,
    cases: Mapping[str, Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
    dict[str, str],
]:
    occlusion: dict[tuple[str, str, str], dict[str, Any]] = {}
    classification: dict[tuple[str, str, str], dict[str, Any]] = {}
    file_hashes: dict[str, str] = {}
    ordered_cases = sorted(cases.items(), key=lambda item: (item[1]["source_dataset"], item[1]["source_order"], item[0]))
    for sample_id, metadata in ordered_cases:
        reports = Path(metadata["workdir"]) / "reports"
        for baseline in BASELINES:
            occ_path = reports / f"{baseline}_baseline/cdr3_occlusion_summary_{baseline}.csv"
            cls_path = reports / f"{sample_id}_{baseline}_blocker_classification.csv"
            occ_rows = unique_rows(read_csv(occ_path), ("model",), str(occ_path))
            cls_rows = unique_rows(read_csv(cls_path), ("model",), str(cls_path))
            if set(occ_rows) != set(cls_rows):
                raise ClosureError(
                    f"Legacy occlusion/classification model mismatch for {sample_id}/{baseline}"
                )
            occ_hash = sha256_file(occ_path)
            cls_hash = sha256_file(cls_path)
            file_hashes[canonical_path(occ_path, config.workspace_root)] = occ_hash
            file_hashes[canonical_path(cls_path, config.workspace_root)] = cls_hash
            for (model,), row in occ_rows.items():
                natural_key(model)
                if row.get("baseline", "").strip().lower() != baseline:
                    raise ClosureError(
                        f"Legacy baseline mismatch for {sample_id}/{model}/{baseline}"
                    )
                key = (sample_id, model, baseline)
                if key in occlusion:
                    raise ClosureError(f"Duplicate legacy occlusion key: {key}")
                occlusion[key] = {
                    "row": row,
                    "path": occ_path,
                    "sha256": occ_hash,
                }
                classification[key] = {
                    "row": cls_rows[(model,)],
                    "path": cls_path,
                    "sha256": cls_hash,
                }
    return occlusion, classification, dict(sorted(file_hashes.items()))


def validate_rescore_inputs(
    config: SummaryConfig,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, str]]:
    hashes = {
        "metrics": verify_hash(
            config.metrics, config.expected_metrics_sha256, "V1.2 sensitivity metrics"
        ),
        "rescore_audit": verify_hash(
            config.rescore_audit,
            config.expected_rescore_audit_sha256,
            "V1.2 sensitivity audit",
        ),
        "old_rules": verify_hash(
            config.old_rules, config.expected_old_rules_sha256, "OLD V1.1 rules"
        ),
        "old_classifier": verify_hash(
            config.old_classifier,
            config.expected_old_classifier_sha256,
            "OLD V1.1 classifier",
        ),
    }
    audit = read_json(config.rescore_audit)
    if audit.get("status") != "PASS_V1_2_DEVELOPMENT_SENSITIVITY_RESCORE_BUILT":
        raise ClosureError(f"V1.2 rescore audit is not PASS: {audit.get('status')!r}")
    if audit.get("formal_eligible") is not False or audit.get("threshold_freeze_eligible") is not False:
        raise ClosureError("V1.2 rescore audit violated development-only eligibility boundary")
    if audit.get("output_sha256", {}).get("continuous_metrics") != hashes["metrics"]:
        raise ClosureError("V1.2 rescore audit does not bind the metrics SHA256")
    if audit.get("observed_inventory", {}).get("total_rows") != config.expected_rows:
        raise ClosureError("V1.2 rescore audit row count does not match expected closure")
    rows = read_csv(config.metrics)
    if len(rows) != config.expected_rows:
        raise ClosureError(f"Expected {config.expected_rows} metric rows, found {len(rows)}")
    indexed = unique_rows(rows, ("sample_id", "model", "baseline"), str(config.metrics))
    if len(indexed) != len(rows):
        raise ClosureError("V1.2 metrics keys are not unique")
    for key, row in indexed.items():
        if row.get("metrics_row_sha256") != row_hash(row, "metrics_row_sha256"):
            raise ClosureError(f"V1.2 metrics row hash mismatch: {key}")
        if row.get("formal_eligible") != "false" or row.get("threshold_freeze_eligible") != "false":
            raise ClosureError(f"V1.2 metrics row crossed eligibility boundary: {key}")
    return rows, audit, hashes


def old_rule_input(
    model: str,
    hotspot: float,
    total_pairs: float,
    cdr3_pairs: float,
    cdr3_fraction: float,
    framework_pairs: float,
) -> dict[str, str]:
    return {
        "model": model,
        "hotspot_overlap_count": number_text(hotspot),
        "total_vhh_pvrl2_residue_pair_occlusion": number_text(total_pairs),
        "cdr3_pvrl2_residue_pair_occlusion": number_text(cdr3_pairs),
        "cdr3_occlusion_fraction": number_text(cdr3_fraction),
        "framework_residue_pair_occlusion": number_text(framework_pairs),
    }


def apply_old_rule(module: Any, rules: Mapping[str, Any], values: Mapping[str, str]) -> str:
    result = module.classify(dict(values), dict(rules), "naked_vhh", "diagnostic_replay")
    label = str(result.get("blocker_class", ""))
    if not label:
        raise ClosureError("OLD V1.1 classifier returned a blank class")
    return label


def inventory_for_row(row: Mapping[str, str], key: tuple[str, str, str]) -> dict[str, Any]:
    try:
        inventory = json.loads(row["reference_pvrl2_record_inventory_json"])
    except (KeyError, json.JSONDecodeError) as error:
        raise ClosureError(f"Invalid reference inventory for {key}") from error
    if not isinstance(inventory, dict):
        raise ClosureError(f"Reference inventory is not an object for {key}")
    if sha256_json(inventory) != row.get("reference_pvrl2_record_inventory_sha256"):
        raise ClosureError(f"Reference inventory hash mismatch for {key}")
    return inventory


def build_delta_rows(
    config: SummaryConfig,
    metrics_rows: Sequence[dict[str, str]],
    cases: Mapping[str, Mapping[str, Any]],
    legacy_occ: Mapping[tuple[str, str, str], Mapping[str, Any]],
    legacy_cls: Mapping[tuple[str, str, str], Mapping[str, Any]],
    classifier: Any,
    rules: Mapping[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    new_index = unique_rows(
        metrics_rows, ("sample_id", "model", "baseline"), "V1.2 metrics"
    )
    new_keys = set(new_index)
    if new_keys != set(legacy_occ) or new_keys != set(legacy_cls):
        raise ClosureError(
            "Exact 932-row closure failed: "
            f"new_only_occ={len(new_keys-set(legacy_occ))}, "
            f"old_occ_only={len(set(legacy_occ)-new_keys)}, "
            f"new_only_cls={len(new_keys-set(legacy_cls))}, "
            f"old_cls_only={len(set(legacy_cls)-new_keys)}"
        )
    reference_inventories: dict[str, set[str]] = defaultdict(set)
    output: list[dict[str, str]] = []
    sorted_keys = sorted(
        new_keys,
        key=lambda key: (
            0 if new_index[key]["source_dataset"] == "known_positive_calibration" else 1,
            int(new_index[key]["source_order"]),
            natural_key(key[1]),
            BASELINES.index(key[2]),
        ),
    )
    for key in sorted_keys:
        sample_id, model, baseline = key
        new = new_index[key]
        old = legacy_occ[key]["row"]
        old_class_row = legacy_cls[key]["row"]
        metadata = cases.get(sample_id)
        if not metadata:
            raise ClosureError(f"No source-manifest metadata for {sample_id}")
        if new.get("source_dataset") != metadata["source_dataset"]:
            raise ClosureError(f"Source dataset mismatch for {key}")
        if int(new.get("source_order", "-1")) != metadata["source_order"]:
            raise ClosureError(f"Source order mismatch for {key}")
        if new.get("family") != metadata["family"]:
            raise ClosureError(f"Family mismatch for {key}")
        if new.get("source_manifest_sha256") != metadata["source_manifest_sha256"]:
            raise ClosureError(f"Source manifest hash mismatch for {key}")
        if new.get("source_manifest_row_sha256") != metadata["source_manifest_row_sha256"]:
            raise ClosureError(f"Source manifest row hash mismatch for {key}")

        context = "/".join(key)
        old_hotspot = finite_float(old.get("hotspot_overlap_count"), "old hotspot", context)
        new_hotspot = finite_float(new.get("hotspot_overlap_count"), "new hotspot", context)
        if old_hotspot != new_hotspot:
            raise ClosureError(f"Non-occlusion hotspot metric changed for {context}")
        old_total_pairs = finite_float(
            old.get("total_vhh_pvrl2_residue_pair_occlusion"), "old total pairs", context
        )
        old_cdr3_pairs = finite_float(
            old.get("cdr3_residue_pair_occlusion"), "old CDR3 pairs", context
        )
        old_cdr3_fraction = finite_float(
            old.get("cdr3_residue_pair_occlusion_fraction"), "old CDR3 fraction", context
        )
        old_framework = finite_float(
            old.get("framework_residue_pair_occlusion"), "old framework pairs", context
        )
        replayed_old_class = apply_old_rule(
            classifier,
            rules,
            old_rule_input(
                model,
                old_hotspot,
                old_total_pairs,
                old_cdr3_pairs,
                old_cdr3_fraction,
                old_framework,
            ),
        )
        legacy_class = old_class_row.get("blocker_class", "").strip()
        if replayed_old_class != legacy_class:
            raise ClosureError(
                f"OLD V1.1 classifier replay mismatch for {context}: "
                f"{replayed_old_class}!={legacy_class}"
            )
        new_total_pairs = finite_float(
            new.get("total_occluding_residue_pair_count"), "new total pairs", context
        )
        new_cdr3_pairs = finite_float(
            new.get("cdr3_occluding_residue_pair_count"), "new CDR3 pairs", context
        )
        new_cdr3_fraction = finite_float(
            new.get("cdr3_occluding_residue_pair_fraction_of_total"),
            "new CDR3 fraction",
            context,
        )
        new_framework = finite_float(
            new.get("framework_occluding_residue_pair_count"),
            "new framework pairs",
            context,
        )
        diagnostic_class = apply_old_rule(
            classifier,
            rules,
            old_rule_input(
                model,
                new_hotspot,
                new_total_pairs,
                new_cdr3_pairs,
                new_cdr3_fraction,
                new_framework,
            ),
        )
        inventory = inventory_for_row(new, key)
        reference_inventories[baseline].add(canonical_json(inventory))
        row: dict[str, str] = {
            "schema_version": "pvrig_v1_2_final_pose_sensitivity_delta_v1",
            "protocol_id": PROTOCOL_ID,
            "analysis_id": ANALYSIS_ID,
            "claim_boundary": CLAIM_BOUNDARY,
            "diagnostic_only": "true",
            "v1_2_label": "false",
            "formal_eligible": "false",
            "threshold_freeze_eligible": "false",
            "source_dataset": new["source_dataset"],
            "source_order": new["source_order"],
            "sample_id": sample_id,
            "family": new["family"],
            "mutation_class": str(metadata["mutation_class"]),
            "control_type": str(metadata["control_type"]),
            "source_descriptor": str(metadata["source_descriptor"]),
            "model": model,
            "baseline": baseline,
            "source_pose_sha256": new["source_pose_sha256"],
            "v1_2_metrics_row_sha256": new["metrics_row_sha256"],
            "legacy_occlusion_relpath": canonical_path(
                Path(legacy_occ[key]["path"]), config.workspace_root
            ),
            "legacy_occlusion_sha256": str(legacy_occ[key]["sha256"]),
            "legacy_classification_relpath": canonical_path(
                Path(legacy_cls[key]["path"]), config.workspace_root
            ),
            "legacy_classification_sha256": str(legacy_cls[key]["sha256"]),
            "legacy_hotspot_overlap_count": number_text(old_hotspot),
            "v1_2_hotspot_overlap_count": number_text(new_hotspot),
            "hotspot_overlap_delta": number_text(new_hotspot - old_hotspot),
            "reference_protein_atom_heavy_atom_count": str(
                inventory["protein_atom_heavy_atom_count"]
            ),
            "reference_excluded_hetatm_heavy_atom_count": str(
                inventory["excluded_hetatm_heavy_atom_count"]
            ),
            "reference_excluded_hoh_heavy_atom_count": str(
                inventory["excluded_hoh_heavy_atom_count"]
            ),
            "reference_excluded_edo_heavy_atom_count": str(
                inventory["excluded_edo_heavy_atom_count"]
            ),
            "legacy_v1_1_class": legacy_class,
            "v1_2_metrics_old_rule_diagnostic_class": diagnostic_class,
            "old_rule_diagnostic_transition": f"{legacy_class}->{diagnostic_class}",
            "old_rule_class_changed": "true" if legacy_class != diagnostic_class else "false",
        }
        for metric_name, (old_field, new_field) in METRIC_SPECS.items():
            old_value = finite_float(old.get(old_field), old_field, context)
            new_value = finite_float(new.get(new_field), new_field, context)
            delta = new_value - old_value
            row[f"legacy_inclusive_{metric_name}"] = number_text(old_value)
            row[f"v1_2_atom_only_{metric_name}"] = number_text(new_value)
            row[f"delta_{metric_name}"] = number_text(delta)
            if old_value == 0.0:
                row[f"ratio_new_over_old_{metric_name}"] = ""
                row[f"percent_change_{metric_name}"] = ""
            else:
                ratio = new_value / old_value
                row[f"ratio_new_over_old_{metric_name}"] = number_text(ratio)
                row[f"percent_change_{metric_name}"] = number_text((ratio - 1.0) * 100.0)
        normalized = {
            field: str(row.get(field, ""))
            for field in DELTA_FIELDS
            if field != "delta_row_sha256"
        }
        normalized["delta_row_sha256"] = row_hash(normalized, "delta_row_sha256")
        output.append(normalized)

    if len(output) != config.expected_rows:
        raise ClosureError(f"Expected {config.expected_rows} delta rows, found {len(output)}")
    reference_summary: dict[str, Any] = {}
    for baseline in BASELINES:
        inventories = reference_inventories.get(baseline, set())
        if len(inventories) != 1:
            raise ClosureError(
                f"Expected one exact reference inventory for {baseline}, found {len(inventories)}"
            )
        inventory = json.loads(next(iter(inventories)))
        reference_summary[baseline] = {
            **inventory,
            "legacy_inclusive_selected_heavy_atom_count": (
                int(inventory["protein_atom_heavy_atom_count"])
                + int(inventory["excluded_hetatm_heavy_atom_count"])
            ),
            "v1_2_selected_protein_heavy_atom_count": int(
                inventory["selected_protein_heavy_atom_count"]
            ),
        }
    return output, reference_summary


def metric_stats(rows: Sequence[Mapping[str, str]], metric_name: str) -> dict[str, Any]:
    old_values = [float(row[f"legacy_inclusive_{metric_name}"]) for row in rows]
    new_values = [float(row[f"v1_2_atom_only_{metric_name}"]) for row in rows]
    deltas = [float(row[f"delta_{metric_name}"]) for row in rows]
    ratios = [
        float(row[f"ratio_new_over_old_{metric_name}"])
        for row in rows
        if row[f"ratio_new_over_old_{metric_name}"] != ""
    ]
    return {
        "old_sum": sum(old_values),
        "new_sum": sum(new_values),
        "old_mean": statistics.fmean(old_values),
        "new_mean": statistics.fmean(new_values),
        "delta_mean": statistics.fmean(deltas),
        "delta_median": statistics.median(deltas),
        "delta_min": min(deltas),
        "delta_max": max(deltas),
        "ratio_defined_rows": len(ratios),
        "ratio_mean": statistics.fmean(ratios) if ratios else None,
        "ratio_median": statistics.median(ratios) if ratios else None,
        "decreased_rows": sum(value < 0 for value in deltas),
        "unchanged_rows": sum(value == 0 for value in deltas),
        "increased_rows": sum(value > 0 for value in deltas),
    }


def summarize_subset(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "sample_count": len({row["sample_id"] for row in rows}),
        "legacy_class_counts": dict(sorted(Counter(row["legacy_v1_1_class"] for row in rows).items())),
        "old_rule_diagnostic_class_counts": dict(
            sorted(Counter(row["v1_2_metrics_old_rule_diagnostic_class"] for row in rows).items())
        ),
        "old_rule_transition_counts": dict(
            sorted(Counter(row["old_rule_diagnostic_transition"] for row in rows).items())
        ),
        "changed_class_rows": sum(row["old_rule_class_changed"] == "true" for row in rows),
        "metrics": {
            metric_name: metric_stats(rows, metric_name) for metric_name in METRIC_SPECS
        },
    }


def stratify(rows: Sequence[Mapping[str, str]], field: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row[field]].append(row)
    return {value: summarize_subset(groups[value]) for value in sorted(groups)}


def write_csv_atomic(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=DELTA_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def compact_counts(values: Mapping[str, int]) -> str:
    return "; ".join(f"{key}={value}" for key, value in sorted(values.items())) or "none"


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def report_table(lines: list[str], title: str, groups: Mapping[str, Any]) -> None:
    lines.extend(
        [
            f"## {title}",
            "",
            "| 分层 | rows | samples | total-pair median delta | CDR3-pair median delta | class changed | diagnostic transitions |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for name, summary in groups.items():
        total_delta = summary["metrics"]["total_residue_pairs"]["delta_median"]
        cdr3_delta = summary["metrics"]["cdr3_residue_pairs"]["delta_median"]
        transitions = compact_counts(summary["old_rule_transition_counts"]).replace("|", "/")
        lines.append(
            f"| {name} | {summary['row_count']} | {summary['sample_count']} | "
            f"{fmt(total_delta, 2)} | {fmt(cdr3_delta, 2)} | "
            f"{summary['changed_class_rows']} | {transitions} |"
        )
    lines.append("")


def build_chinese_report(
    summary: Mapping[str, Any],
    reference_inventory: Mapping[str, Any],
    input_hashes: Mapping[str, str],
    delta_hash: str,
) -> str:
    overall = summary["overall"]
    total_stats = overall["metrics"]["total_residue_pairs"]
    cdr3_stats = overall["metrics"]["cdr3_residue_pairs"]
    fraction_stats = overall["metrics"]["cdr3_residue_pair_fraction"]
    lines = [
        "# PVRIG V1.2 ATOM-only final-pose sensitivity 报告",
        "",
        "## 结论边界",
        "",
        f"- 协议：`{PROTOCOL_ID}`",
        f"- 数据集：`{ANALYSIS_ID}`",
        "- 本分析只比较同一批 legacy variable-size final poses 在旧 HETATM-inclusive 与 V1.2 protein-ATOM-only 语义下的数值敏感性。",
        "- 文中的 class transition 只是将 **OLD V1.1 rules** 重放到 V1.2 连续指标上的诊断；它们不是 V1.2 标签。",
        "- `threshold_freeze_eligible=false`，不得用本结果拟合或冻结新阈值，不得将任一行称为 Docking Gold。",
        "",
        "## 932 行闭包",
        "",
        f"- 行数：{overall['row_count']}；样本数：{overall['sample_count']}。",
        f"- 旧规则 class 计数：{compact_counts(overall['legacy_class_counts'])}。",
        f"- V1.2 metrics 上的旧规则诊断计数：{compact_counts(overall['old_rule_diagnostic_class_counts'])}。",
        f"- 发生诊断 class 变化的 pose：{overall['changed_class_rows']}/{overall['row_count']}。",
        "",
        "## 主要数值敏感性",
        "",
        "| 指标 | old mean | V1.2 mean | mean delta | median delta | median new/old ratio | decreased rows |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| total residue pairs | {fmt(total_stats['old_mean'])} | {fmt(total_stats['new_mean'])} | {fmt(total_stats['delta_mean'])} | {fmt(total_stats['delta_median'])} | {fmt(total_stats['ratio_median'])} | {total_stats['decreased_rows']} |",
        f"| CDR3 residue pairs | {fmt(cdr3_stats['old_mean'])} | {fmt(cdr3_stats['new_mean'])} | {fmt(cdr3_stats['delta_mean'])} | {fmt(cdr3_stats['delta_median'])} | {fmt(cdr3_stats['ratio_median'])} | {cdr3_stats['decreased_rows']} |",
        f"| CDR3 residue-pair fraction | {fmt(fraction_stats['old_mean'])} | {fmt(fraction_stats['new_mean'])} | {fmt(fraction_stats['delta_mean'])} | {fmt(fraction_stats['delta_median'])} | {fmt(fraction_stats['ratio_median'])} | {fraction_stats['decreased_rows']} |",
        "",
        "## Reference record inventory",
        "",
        "| baseline | chain | protein ATOM heavy | legacy inclusive heavy | V1.2 selected | excluded HETATM | HOH | EDO |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for baseline in BASELINES:
        inv = reference_inventory[baseline]
        lines.append(
            f"| {baseline} | {inv['chain']} | {inv['protein_atom_heavy_atom_count']} | "
            f"{inv['legacy_inclusive_selected_heavy_atom_count']} | "
            f"{inv['v1_2_selected_protein_heavy_atom_count']} | "
            f"{inv['excluded_hetatm_heavy_atom_count']} | "
            f"{inv['excluded_hoh_heavy_atom_count']} | {inv['excluded_edo_heavy_atom_count']} |"
        )
    lines.append("")
    report_table(lines, "按 positive / mutant 分层", summary["by_source_dataset"])
    report_table(lines, "按 baseline 分层", summary["by_baseline"])
    report_table(lines, "按 family 分层", summary["by_family"])
    report_table(lines, "按 mutation class 分层", summary["by_mutation_class"])
    report_table(lines, "按 control type 分层", summary["by_control_type"])
    lines.extend(
        [
            "## 可复现性",
            "",
            f"- V1.2 metrics SHA256: `{input_hashes['metrics']}`",
            f"- V1.2 rescore audit SHA256: `{input_hashes['rescore_audit']}`",
            f"- OLD V1.1 rules SHA256: `{input_hashes['old_rules']}`",
            f"- OLD V1.1 classifier SHA256: `{input_hashes['old_classifier']}`",
            f"- row-level delta CSV SHA256: `{delta_hash}`",
            "",
            "## 解读限制",
            "",
            "- 当前 pose 来自 legacy `6_seletopclusts` variable-size final ensembles，不是预注册 fixed-K `4_emref` Top-8。",
            "- 旧分类阈值本身是 V1.1 产物；它们在这里只用来量化 scorer semantics 改变的诊断影响。",
            "- 需要使用全新 fixed-K development set 完成独立阈值开发，再对 untouched formal holdout 做最终验证。",
            "",
        ]
    )
    return "\n".join(lines)


def verify_frozen_hashes(files: Mapping[Path, str]) -> None:
    mismatches = []
    for path, expected in sorted(files.items(), key=lambda item: str(item[0])):
        observed = sha256_file(path)
        if observed != expected:
            mismatches.append(f"{path}:{observed}!={expected}")
    if mismatches:
        raise ClosureError("Inputs changed during summary build: " + "; ".join(mismatches))


def run_summary(config: SummaryConfig) -> dict[str, Any]:
    metrics_rows, _rescore_audit, core_hashes = validate_rescore_inputs(config)
    cases, manifest_hashes = load_case_metadata(config)
    legacy_occ, legacy_cls, legacy_hashes = load_legacy_rows(config, cases)
    classifier = load_old_classifier(config.old_classifier)
    rules = classifier.load_rules(config.old_rules)
    delta_rows, reference_inventory = build_delta_rows(
        config,
        metrics_rows,
        cases,
        legacy_occ,
        legacy_cls,
        classifier,
        rules,
    )
    summary = {
        "overall": summarize_subset(delta_rows),
        "by_source_dataset": stratify(delta_rows, "source_dataset"),
        "by_baseline": stratify(delta_rows, "baseline"),
        "by_family": stratify(delta_rows, "family"),
        "by_mutation_class": stratify(delta_rows, "mutation_class"),
        "by_control_type": stratify(delta_rows, "control_type"),
    }
    frozen = {
        config.metrics.resolve(): core_hashes["metrics"],
        config.rescore_audit.resolve(): core_hashes["rescore_audit"],
        config.old_rules.resolve(): core_hashes["old_rules"],
        config.old_classifier.resolve(): core_hashes["old_classifier"],
        config.positive_manifest.resolve(): manifest_hashes["known_positive_calibration"],
        config.mutant_manifest.resolve(): manifest_hashes["mutant_or_reference_control"],
    }
    for item in legacy_occ.values():
        frozen[Path(item["path"]).resolve()] = str(item["sha256"])
    for item in legacy_cls.values():
        frozen[Path(item["path"]).resolve()] = str(item["sha256"])
    verify_frozen_hashes(frozen)

    write_csv_atomic(config.delta_csv, delta_rows)
    delta_hash = sha256_file(config.delta_csv)
    report = build_chinese_report(summary, reference_inventory, core_hashes, delta_hash)
    write_text_atomic(config.report_md, report)
    report_hash = sha256_file(config.report_md)
    audit = {
        "schema_version": "pvrig_v1_2_final_pose_sensitivity_audit_v1",
        "status": "PASS_V1_2_FINAL_POSE_SENSITIVITY_DIAGNOSTIC",
        "protocol_id": PROTOCOL_ID,
        "analysis_id": ANALYSIS_ID,
        "claim_boundary": CLAIM_BOUNDARY,
        "diagnostic_only": True,
        "v1_2_labels_emitted": False,
        "formal_eligible": False,
        "threshold_freeze_eligible": False,
        "fixed_k_pose_ensemble": False,
        "row_closure": {
            "expected": config.expected_rows,
            "v1_2_metrics": len(metrics_rows),
            "legacy_occlusion": len(legacy_occ),
            "legacy_classification": len(legacy_cls),
            "delta_rows": len(delta_rows),
            "unique_samples": len({row["sample_id"] for row in delta_rows}),
        },
        "old_rule_replay": {
            "rules_sha256": core_hashes["old_rules"],
            "classifier_sha256": core_hashes["old_classifier"],
            "legacy_rows_reproduced": len(delta_rows),
            "mismatches": 0,
            "interpretation": "sensitivity diagnostic only; not V1.2 labels",
        },
        "reference_record_inventory": reference_inventory,
        "summary": summary,
        "input_sha256": {
            **core_hashes,
            "positive_manifest": manifest_hashes["known_positive_calibration"],
            "mutant_manifest": manifest_hashes["mutant_or_reference_control"],
            "legacy_files": legacy_hashes,
            "summarizer": sha256_file(Path(__file__).resolve()),
        },
        "output_sha256": {
            "row_level_delta_csv": delta_hash,
            "row_hash_chain": hashlib.sha256(
                ("\n".join(row["delta_row_sha256"] for row in delta_rows) + "\n").encode("ascii")
            ).hexdigest(),
            "chinese_report": report_hash,
        },
    }
    write_json_atomic(config.audit_json, audit)
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--rescore-audit", type=Path, default=DEFAULT_RESCORE_AUDIT)
    parser.add_argument("--positive-manifest", type=Path, default=DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--old-rules", type=Path, default=DEFAULT_OLD_RULES)
    parser.add_argument("--old-classifier", type=Path, default=DEFAULT_OLD_CLASSIFIER)
    parser.add_argument("--delta-csv", type=Path, default=DEFAULT_DELTA_CSV)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--expected-metrics-sha256", default=EXPECTED_METRICS_SHA256)
    parser.add_argument(
        "--expected-rescore-audit-sha256", default=EXPECTED_RESCORE_AUDIT_SHA256
    )
    parser.add_argument("--expected-old-rules-sha256", default=EXPECTED_OLD_RULES_SHA256)
    parser.add_argument(
        "--expected-old-classifier-sha256", default=EXPECTED_OLD_CLASSIFIER_SHA256
    )
    parser.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS)
    parser.add_argument("--expected-samples", type=int, default=EXPECTED_SAMPLES)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = SummaryConfig(
        metrics=args.metrics.resolve(),
        rescore_audit=args.rescore_audit.resolve(),
        positive_manifest=args.positive_manifest.resolve(),
        mutant_manifest=args.mutant_manifest.resolve(),
        old_rules=args.old_rules.resolve(),
        old_classifier=args.old_classifier.resolve(),
        delta_csv=args.delta_csv.resolve(),
        audit_json=args.audit_json.resolve(),
        report_md=args.report_md.resolve(),
        expected_metrics_sha256=args.expected_metrics_sha256,
        expected_rescore_audit_sha256=args.expected_rescore_audit_sha256,
        expected_old_rules_sha256=args.expected_old_rules_sha256,
        expected_old_classifier_sha256=args.expected_old_classifier_sha256,
        expected_rows=args.expected_rows,
        expected_samples=args.expected_samples,
    )
    try:
        audit = run_summary(config)
    except ClosureError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": audit["status"],
                "rows": audit["row_closure"]["delta_rows"],
                "changed_class_rows": audit["summary"]["overall"]["changed_class_rows"],
                "threshold_freeze_eligible": audit["threshold_freeze_eligible"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
