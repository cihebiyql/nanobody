#!/usr/bin/env python3
"""Freeze the family-aware V1.2 pose and single-run calibration rules.

This calibration is deliberately limited to the fixed Top-8 ensemble produced by
an 8X6B docking run and scored post hoc against the 8X6B and 9E6Y baselines.  It
does not validate the later dual-receptor ``R_gold`` and it is not experimental
binding, affinity, or blocking truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_ID = "DG_A_PVRIG_V1_2_DEV"
METHOD_ID = "PVRIG_V1_2_FAMILY_AWARE_TOP8_CALIBRATION_V1"
SCHEMA_VERSION = "pvrig_v1_2_family_aware_calibration_v1"
BASELINES = ("8x6b", "9e6y")
METRICS = ("H", "O", "P")
BASELINE_METRICS = ("O", "P")
CANONICAL_H_CHANNEL = "canonical_shared"
LOWER_QUANTILE = 0.20
UPPER_QUANTILE = 0.50
SUPPORT_CUTOFF = 0.25
MIN_SUPPORTING_POSES = 2
BOOTSTRAP_SEED = 20260714
BOOTSTRAP_REPLICATES = 2000
ROBUSTNESS_LOWER_QUANTILES = (0.10, 0.20, 0.30)
ROBUSTNESS_UPPER_QUANTILES = (0.40, 0.50, 0.60)
ROBUSTNESS_SUPPORT_CUTOFFS = (0.20, 0.25, 0.33)
ROBUSTNESS_MIN_SUPPORTING_POSES = (2, 3)
CLAIM_BOUNDARY = (
    "Computational geometry teacher calibration on fixed Top-8 poses from one "
    "8X6B docking ensemble with two post-hoc scoring baselines; not binder, "
    "affinity, experimental blocking, independent dual-receptor docking, or "
    "formal-holdout truth."
)
UPSTREAM_BASELINE_SEMANTICS = (
    "posthoc_scoring_baseline_same_8x6b_docked_pose_ensemble"
)

DEFAULT_METRICS_CSV = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/runs/pvrig_v3_p2/"
    "docking_gold_v1_2_top8_calibration/pvrig_v1_2_top8_continuous_metrics.csv"
)
DEFAULT_UPSTREAM_AUDIT = DEFAULT_METRICS_CSV.with_name(
    "pvrig_v1_2_top8_calibration_audit.json"
)
DEFAULT_CONTACTS_JSONL = DEFAULT_METRICS_CSV.with_name(
    "pvrig_v1_2_top8_residue_contacts.jsonl"
)
DEFAULT_PROCESSOR_RELEASE_MANIFEST = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/audits/"
    "phase2_v3_p2_v1_2_top8_processor_release_manifest.json"
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
    "docking_gold_v1_2_family_calibration"
)
DEFAULT_REPORT = (
    WORKSPACE_ROOT
    / "experiments/phase2_5080_v1/reports/"
    "PVRIG_V3_P2_DOCKING_GOLD_V1_2_FAMILY_CALIBRATION_ZH.md"
)

RULES_NAME = "pvrig_v1_2_family_rules.json"
POSE_SCORES_NAME = "pvrig_v1_2_pose_scores.csv"
RUN_SCORES_NAME = "pvrig_v1_2_calibration_run_scores.csv"
LOFO_NAME = "pvrig_v1_2_family_lofo.csv"
BOOTSTRAP_NAME = "pvrig_v1_2_bootstrap_thresholds.csv"
BOOTSTRAP_ANCHOR_NAME = "pvrig_v1_2_bootstrap_anchor_evaluations.csv"
MUTANT_DELTAS_NAME = "pvrig_v1_2_mutant_paired_deltas.csv"
ROBUSTNESS_NAME = "pvrig_v1_2_robustness_grid.csv"
AUDIT_NAME = "pvrig_v1_2_family_calibration_audit.json"


class CalibrationError(RuntimeError):
    """Raised when a calibration contract fails closed."""


@dataclass(frozen=True)
class CalibrationContract:
    case_count: int = 47
    positive_case_count: int = 11
    positive_family_count: int = 5
    mutant_panel_case_count: int = 36
    mutant_delta_count: int = 29
    ranks_per_case: int = 8
    baseline_count: int = 2

    @property
    def metric_rows(self) -> int:
        return self.case_count * self.ranks_per_case * self.baseline_count


@dataclass(frozen=True)
class CalibrationConfig:
    metrics_csv: Path
    upstream_audit: Path | None
    contacts_jsonl: Path | None
    processor_release_manifest: Path | None
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


def canonical_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


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


def read_csv_strict(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise CalibrationError(f"CSV input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise CalibrationError(f"CSV input has no header: {path}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise CalibrationError(f"CSV input has duplicate fields: {path}")
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


def parse_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise CalibrationError(f"{field_name} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise CalibrationError(f"{field_name} is not finite: {value!r}")
    return parsed


def parse_int(value: Any, field_name: str, minimum: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise CalibrationError(f"{field_name} is not an integer: {value!r}") from error
    if parsed < minimum:
        raise CalibrationError(f"{field_name} must be >= {minimum}, got {parsed}")
    return parsed


def parse_bool(value: Any, field_name: str) -> bool:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    raise CalibrationError(f"{field_name} is not boolean: {value!r}")


def normalized_rank_weights(k: int) -> dict[int, float]:
    if k < 1:
        raise CalibrationError("Rank-weight K must be positive")
    raw = {rank: 1.0 / math.log2(rank + 1.0) for rank in range(1, k + 1)}
    total = sum(raw.values())
    return {rank: value / total for rank, value in raw.items()}


def weighted_quantile(
    values_and_weights: Iterable[tuple[float, float]], quantile: float
) -> float:
    if not 0.0 <= quantile <= 1.0:
        raise CalibrationError(f"Quantile outside [0,1]: {quantile}")
    items: list[tuple[float, float]] = []
    for value, weight in values_and_weights:
        if not math.isfinite(value) or not math.isfinite(weight):
            raise CalibrationError("Weighted quantile received a non-finite value")
        if weight < 0.0:
            raise CalibrationError("Weighted quantile received a negative weight")
        if weight > 0.0:
            items.append((value, weight))
    if not items:
        raise CalibrationError("Weighted quantile has no positive weight")
    items.sort(key=lambda item: item[0])
    total = sum(weight for _, weight in items)
    target = quantile * total
    cumulative = 0.0
    for value, weight in items:
        cumulative += weight
        if cumulative + 1e-15 >= target:
            return value
    return items[-1][0]


def ordinary_quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise CalibrationError("Ordinary quantile received no values")
    if not 0.0 <= quantile <= 1.0:
        raise CalibrationError(f"Quantile outside [0,1]: {quantile}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = quantile * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def derive_features(row: Mapping[str, str]) -> dict[str, float | int]:
    h_value = parse_float(row.get("hotspot_weight_fraction"), "hotspot_weight_fraction")
    if not 0.0 <= h_value <= 1.0 + 1e-12:
        raise CalibrationError(f"hotspot_weight_fraction outside [0,1]: {h_value}")
    total_pairs = parse_int(
        row.get("total_occluding_residue_pair_count"),
        "total_occluding_residue_pair_count",
    )
    cdr_pairs = sum(
        parse_int(row.get(f"cdr{index}_occluding_residue_pair_count"), f"cdr{index}_pairs")
        for index in (1, 2, 3)
    )
    if total_pairs == 0:
        if cdr_pairs != 0:
            raise CalibrationError("CDR residue-pair count is nonzero when total count is zero")
        p_value = 0.0
    else:
        if cdr_pairs > total_pairs:
            raise CalibrationError(
                f"CDR residue-pair count {cdr_pairs} exceeds total {total_pairs}"
            )
        p_value = cdr_pairs / total_pairs
    return {
        "H": min(h_value, 1.0),
        "O": float(total_pairs),
        "O_log1p": math.log1p(total_pairs),
        "P": p_value,
        "O_raw": total_pairs,
        "P_numerator": cdr_pairs,
    }


def load_positive_manifest(path: Path) -> dict[str, dict[str, str]]:
    fields, rows = read_csv_strict(path)
    required = {"calibration_name", "family", "validation_role"}
    missing = sorted(required - set(fields))
    if missing:
        raise CalibrationError(f"Positive manifest lacks fields: {missing}")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        case_id = row["calibration_name"].strip()
        family = row["family"].strip()
        if not case_id or not family or case_id in result:
            raise CalibrationError(f"Missing/duplicate positive case: {case_id!r}")
        result[case_id] = {
            "family": family,
            "role": row["validation_role"].strip(),
            "manifest_row_sha256": sha256_json(row),
        }
    return result


def load_mutant_manifest(
    path: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    fields, rows = read_csv_strict(path)
    required = {
        "mutant_name",
        "base_molecule",
        "family",
        "control_type",
        "mutation_class",
        "mutations_1based",
    }
    missing = sorted(required - set(fields))
    if missing:
        raise CalibrationError(f"Mutant manifest lacks fields: {missing}")
    records: dict[str, dict[str, str]] = {}
    base_by_molecule: dict[str, str] = {}
    for row in rows:
        case_id = row["mutant_name"].strip()
        base_molecule = row["base_molecule"].strip()
        if not case_id or not base_molecule or case_id in records:
            raise CalibrationError(f"Missing/duplicate mutant-panel case: {case_id!r}")
        record = {
            "family": row["family"].strip(),
            "base_molecule": base_molecule,
            "control_type": row["control_type"].strip(),
            "mutation_class": row["mutation_class"].strip(),
            "mutations_1based": row["mutations_1based"].strip(),
            "manifest_row_sha256": sha256_json(row),
        }
        records[case_id] = record
        if record["control_type"] == "base_reference":
            if base_molecule in base_by_molecule:
                raise CalibrationError(f"Duplicate declared base reference for {base_molecule}")
            base_by_molecule[base_molecule] = case_id
    for case_id, record in records.items():
        if record["control_type"] != "base_reference" and record["base_molecule"] not in base_by_molecule:
            raise CalibrationError(
                f"Mutant {case_id} has no declared base-reference row for "
                f"{record['base_molecule']}"
            )
    return records, base_by_molecule


REQUIRED_METRICS_FIELDS = {
    "protocol_id",
    "formal_eligible",
    "threshold_freeze_eligible",
    "pose_rule_threshold_freeze_eligible",
    "dual_receptor_r_gold_freeze_eligible",
    "source_docking_receptor",
    "baseline_channel_semantics",
    "candidate_id",
    "family",
    "canonical_rank",
    "baseline",
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
    "total_occluding_residue_pair_count",
    "cdr1_occluding_residue_pair_count",
    "cdr2_occluding_residue_pair_count",
    "cdr3_occluding_residue_pair_count",
    "metrics_row_sha256",
}

CANONICAL_INTERNAL_CONTACT_FIELDS = (
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
)


def validate_metrics_rows(
    fields: Sequence[str],
    rows: Sequence[dict[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    contract: CalibrationContract,
) -> dict[str, Any]:
    missing = sorted(REQUIRED_METRICS_FIELDS - set(fields))
    if missing:
        raise CalibrationError(f"Continuous metrics lack required fields: {missing}")
    if len(rows) != contract.metric_rows:
        raise CalibrationError(
            f"Expected {contract.metric_rows} continuous rows, found {len(rows)}"
        )
    if len(positive_cases) != contract.positive_case_count:
        raise CalibrationError(
            f"Expected {contract.positive_case_count} positive cases, found {len(positive_cases)}"
        )
    if len({record["family"] for record in positive_cases.values()}) != contract.positive_family_count:
        raise CalibrationError("Positive-family cardinality does not match the contract")
    if len(mutant_cases) != contract.mutant_panel_case_count:
        raise CalibrationError(
            f"Expected {contract.mutant_panel_case_count} mutant-panel cases, "
            f"found {len(mutant_cases)}"
        )
    expected_cases = set(positive_cases) | set(mutant_cases)
    if len(expected_cases) != contract.case_count:
        raise CalibrationError("Positive and mutant manifests do not form the expected case set")
    keys: set[tuple[str, int, str]] = set()
    case_rows: Counter[str] = Counter()
    family_by_case: dict[str, str] = {}
    shared_internal_by_pose: dict[tuple[str, int], tuple[str, ...]] = {}
    for row_number, row in enumerate(rows, start=2):
        observed_hash = row.get("metrics_row_sha256", "")
        expected_hash = row_sha256(row, "metrics_row_sha256")
        if observed_hash != expected_hash:
            raise CalibrationError(f"metrics_row_sha256 mismatch at CSV row {row_number}")
        if row.get("protocol_id") != PROTOCOL_ID:
            raise CalibrationError(f"Protocol mismatch at CSV row {row_number}")
        if parse_bool(row.get("formal_eligible"), "formal_eligible"):
            raise CalibrationError("Formal-eligible input is forbidden in development calibration")
        if parse_bool(row.get("threshold_freeze_eligible"), "threshold_freeze_eligible"):
            raise CalibrationError("Upstream continuous metrics unexpectedly contain frozen thresholds")
        if not parse_bool(
            row.get("pose_rule_threshold_freeze_eligible"),
            "pose_rule_threshold_freeze_eligible",
        ):
            raise CalibrationError("Upstream Top-8 closure is not pose-rule eligible")
        if parse_bool(
            row.get("dual_receptor_r_gold_freeze_eligible"),
            "dual_receptor_r_gold_freeze_eligible",
        ):
            raise CalibrationError("Dual-receptor R_gold eligibility is forbidden here")
        if row.get("source_docking_receptor", "").strip().lower() != "8x6b":
            raise CalibrationError("Calibration source must be the 8X6B docking ensemble")
        if row.get("baseline_channel_semantics", "").strip() != UPSTREAM_BASELINE_SEMANTICS:
            raise CalibrationError("Unexpected post-hoc baseline-channel semantics")
        candidate_id = row.get("candidate_id", "").strip()
        if candidate_id not in expected_cases:
            raise CalibrationError(f"Unknown candidate in metrics: {candidate_id!r}")
        rank = parse_int(row.get("canonical_rank"), "canonical_rank", 1)
        if rank > contract.ranks_per_case:
            raise CalibrationError(f"Rank {rank} exceeds fixed K={contract.ranks_per_case}")
        baseline = row.get("baseline", "").strip().lower()
        if baseline not in BASELINES:
            raise CalibrationError(f"Unknown baseline: {baseline!r}")
        key = (candidate_id, rank, baseline)
        if key in keys:
            raise CalibrationError(f"Duplicate continuous metric key: {key}")
        keys.add(key)
        shared_key = (candidate_id, rank)
        shared_values = tuple(row.get(field, "").strip() for field in CANONICAL_INTERNAL_CONTACT_FIELDS)
        previous_shared = shared_internal_by_pose.setdefault(shared_key, shared_values)
        if previous_shared != shared_values:
            differing = [
                field
                for field, previous, observed in zip(
                    CANONICAL_INTERNAL_CONTACT_FIELDS, previous_shared, shared_values
                )
                if previous != observed
            ]
            raise CalibrationError(
                f"Canonical internal-contact/H channel drift for {candidate_id}/rank{rank}: "
                f"{differing}"
            )
        case_rows[candidate_id] += 1
        expected_family = (
            positive_cases.get(candidate_id, mutant_cases.get(candidate_id, {})).get("family")
        )
        family = row.get("family", "").strip()
        if family != expected_family:
            raise CalibrationError(f"Family mismatch for {candidate_id}: {family!r}")
        if candidate_id in family_by_case and family_by_case[candidate_id] != family:
            raise CalibrationError(f"Family drift within {candidate_id}")
        family_by_case[candidate_id] = family
        derive_features(row)
    expected_per_case = contract.ranks_per_case * contract.baseline_count
    bad_cases = {
        case_id: count for case_id, count in case_rows.items() if count != expected_per_case
    }
    if set(case_rows) != expected_cases or bad_cases:
        raise CalibrationError(
            f"Missing/incomplete case closure: missing={sorted(expected_cases - set(case_rows))}, "
            f"bad={bad_cases}"
        )
    expected_keys = {
        (case_id, rank, baseline)
        for case_id in expected_cases
        for rank in range(1, contract.ranks_per_case + 1)
        for baseline in BASELINES
    }
    if keys != expected_keys:
        raise CalibrationError("Fixed Top-8 x baseline key closure failed")
    return {
        "case_count": len(case_rows),
        "metric_rows": len(rows),
        "positive_cases": len(positive_cases),
        "positive_families": len({record["family"] for record in positive_cases.values()}),
        "mutant_panel_cases": len(mutant_cases),
        "rows_by_baseline": dict(sorted(Counter(row["baseline"] for row in rows).items())),
    }


def validate_upstream_audit(path: Path | None, metrics_csv: Path) -> dict[str, Any]:
    if path is None:
        return {"required": False, "relpath": "", "sha256": ""}
    if not path.is_file():
        raise CalibrationError(f"Upstream calibration audit is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS_V1_2_TOP8_CALIBRATION_CONTINUOUS_METRICS_BUILT":
        raise CalibrationError("Upstream Top-8 calibration audit is not PASS")
    if payload.get("formal_eligible") is not False:
        raise CalibrationError("Upstream audit formal eligibility is not false")
    if payload.get("pose_rule_threshold_freeze_eligible") is not True:
        raise CalibrationError("Upstream audit is not pose-rule eligible")
    if payload.get("dual_receptor_r_gold_freeze_eligible") is not False:
        raise CalibrationError("Upstream audit incorrectly permits dual-receptor R_gold")
    output = payload.get("output_sha256", {}).get("continuous_metrics", {})
    if output.get("sha256") != sha256_file(metrics_csv):
        raise CalibrationError("Metrics CSV hash does not match the upstream audit")
    return {
        "required": True,
        "relpath": canonical_path(path),
        "sha256": sha256_file(path),
        "status": payload.get("status"),
        "metrics_row_hash_chain": output.get("row_hash_chain", ""),
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


def anchor_metric_values(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    ranks_per_case: int,
) -> dict[str, Any]:
    index = family_case_index(rows, positive_cases)
    families = sorted(index)
    if not families:
        raise CalibrationError("No positive families are available for calibration")
    q_rank = normalized_rank_weights(ranks_per_case)
    output: dict[str, Any] = {
        "H_canonical": [],
        "baseline": {
            baseline: {metric: [] for metric in BASELINE_METRICS}
            for baseline in BASELINES
        },
    }
    for family in families:
        cases = index[family]
        if not cases:
            raise CalibrationError(f"Positive family {family} has no cases")
        for case_id, case_rows in cases.items():
            by_key = {(int(row["canonical_rank"]), row["baseline"]): row for row in case_rows}
            for rank in range(1, ranks_per_case + 1):
                weight = (1.0 / len(families)) * (1.0 / len(cases)) * q_rank[rank]
                rank_rows: dict[str, Mapping[str, str]] = {}
                for baseline in BASELINES:
                    key = (rank, baseline)
                    if key not in by_key:
                        raise CalibrationError(f"Positive anchor lacks {case_id}/{rank}/{baseline}")
                    rank_rows[baseline] = by_key[key]
                    features = derive_features(rank_rows[baseline])
                    for metric in BASELINE_METRICS:
                        output["baseline"][baseline][metric].append(
                            (float(features[metric]), weight)
                        )
                shared_values = {
                    baseline: tuple(
                        rank_rows[baseline].get(field, "").strip()
                        for field in CANONICAL_INTERNAL_CONTACT_FIELDS
                    )
                    for baseline in BASELINES
                }
                if shared_values["8x6b"] != shared_values["9e6y"]:
                    raise CalibrationError(
                        f"Positive anchor canonical H/internal channel drift for "
                        f"{case_id}/rank{rank}"
                    )
                canonical_h = float(derive_features(rank_rows["8x6b"])["H"])
                output["H_canonical"].append((canonical_h, weight))
    return output


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
    if total_weight <= 0.0 or positive_weight <= 0.0:
        return {
            "L": None,
            "U": None,
            "L_raw": None,
            "U_raw": None,
            "L_transformed": None,
            "U_transformed": None,
            "raw_unit": raw_unit,
            "transform": transform,
            "lower_quantile": lower_quantile,
            "upper_quantile": upper_quantile,
            "positive_part_only": True,
            "zero_hurdle": 0.0,
            "positive_support_count": 0,
            "positive_weight": 0.0,
            "zero_weight": 1.0,
            "defined": False,
            "failure_reason": "no_positive_anchor_support",
        }
    lower = weighted_quantile(positive, lower_quantile)
    upper = weighted_quantile(positive, upper_quantile)
    lower_transformed = math.log1p(lower) if metric == "O" else lower
    upper_transformed = math.log1p(upper) if metric == "O" else upper
    failure_reason = ""
    if not math.isfinite(lower) or not math.isfinite(upper):
        failure_reason = "non_finite_cutpoint"
    elif lower <= 0.0:
        failure_reason = "non_positive_lower_cutpoint"
    elif upper <= lower:
        failure_reason = "upper_cutpoint_not_strictly_greater_than_lower"
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
        "positive_weight": positive_weight / total_weight,
        "zero_weight": 1.0 - (positive_weight / total_weight),
        "defined": not failure_reason,
        "failure_reason": failure_reason,
    }


def threshold_from_weighted_values(
    values: Sequence[tuple[float, float]],
    lower_quantile: float,
    upper_quantile: float,
    *,
    metric: str,
) -> dict[str, Any]:
    result = threshold_fit_diagnostic(
        values, lower_quantile, upper_quantile, metric=metric
    )
    if not result["defined"]:
        raise CalibrationError(
            f"Invalid {metric} threshold fit: {result['failure_reason']} "
            f"(L={result['L_raw']}, U={result['U_raw']})"
        )
    return result


def derive_rules(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    ranks_per_case: int,
    *,
    lower_quantile: float = LOWER_QUANTILE,
    upper_quantile: float = UPPER_QUANTILE,
) -> dict[str, Any]:
    if upper_quantile <= lower_quantile:
        raise CalibrationError("Upper calibration quantile must exceed lower quantile")
    values = anchor_metric_values(rows, positive_cases, ranks_per_case)
    thresholds = {
        "H_canonical": threshold_from_weighted_values(
            values["H_canonical"], lower_quantile, upper_quantile, metric="H"
        ),
        "baseline": {
            baseline: {
                metric: threshold_from_weighted_values(
                    values["baseline"][baseline][metric],
                    lower_quantile,
                    upper_quantile,
                    metric=metric,
                )
                for metric in BASELINE_METRICS
            }
            for baseline in BASELINES
        },
    }
    return {
        "thresholds": thresholds,
        "positive_family_count": len({record["family"] for record in positive_cases.values()}),
        "positive_case_count": len(positive_cases),
        "family_weighting": "equal_family_then_equal_case_within_family",
        "rank_weighting": "q_r_proportional_to_1_over_log2_rank_plus_1",
        "rank_weights": normalized_rank_weights(ranks_per_case),
        "quantile_method": "smallest_value_with_weighted_cdf_at_or_above_q",
        "hurdle_semantics": "cutpoints_use_strictly_positive_anchor_values; zero_membership_is_zero",
    }


def membership(value: float, threshold: Mapping[str, Any]) -> float:
    if not math.isfinite(value):
        raise CalibrationError("Membership received a non-finite value")
    lower_raw = float(threshold["L_raw"])
    upper_raw = float(threshold["U_raw"])
    lower = float(threshold["L_transformed"])
    upper = float(threshold["U_transformed"])
    if value <= 0.0 or value < lower_raw:
        return 0.0
    if upper <= lower or upper_raw <= lower_raw:
        raise CalibrationError("Membership threshold requires strict U > L")
    transformed = math.log1p(value) if threshold.get("transform") == "log1p" else value
    if value >= upper_raw:
        return 1.0
    return (transformed - lower) / (upper - lower)


def classify_pose(features: Mapping[str, float | int], rules: Mapping[str, Any], baseline: str) -> tuple[str, float, dict[str, float]]:
    h_threshold = rules["thresholds"]["H_canonical"]
    thresholds = rules["thresholds"]["baseline"][baseline]
    h_value = float(features["H"])
    o_value = float(features["O"])
    p_value = float(features["P"])
    memberships = {
        "H": membership(h_value, h_threshold),
        "O": membership(o_value, thresholds["O"]),
        "P": membership(p_value, thresholds["P"]),
    }
    score = math.sqrt(memberships["O"] * (memberships["H"] + memberships["P"]) / 2.0)
    if (
        o_value >= thresholds["O"]["U"]
        and h_value >= h_threshold["U"]
        and p_value >= thresholds["P"]["L"]
    ):
        pose_class = "A"
    elif (
        o_value >= thresholds["O"]["L"]
        and (
            h_value >= h_threshold["L"]
            or p_value >= thresholds["P"]["L"]
        )
    ):
        pose_class = "B"
    elif h_value >= h_threshold["L"] and o_value < thresholds["O"]["L"]:
        pose_class = "C"
    else:
        pose_class = "E"
    return pose_class, score, memberships


POSE_SCORE_FIELDS = (
    "schema_version",
    "protocol_id",
    "method_id",
    "formal_eligible",
    "dual_receptor_r_gold_freeze_eligible",
    "source_docking_receptor",
    "candidate_id",
    "family",
    "canonical_rank",
    "baseline",
    "input_metrics_row_sha256",
    "H_channel",
    "canonical_internal_channel_agreement",
    "H_hotspot_weight_fraction",
    "O_total_occluding_residue_pair_count_raw",
    "O_log1p_total_occluding_residue_pair_count",
    "P_cdr_residue_pair_fraction",
    "P_cdr_residue_pair_count",
    "mu_H",
    "mu_O",
    "mu_P",
    "S_pose_baseline",
    "pose_class",
    "claim_boundary",
    "pose_score_row_sha256",
)


def score_pose_rows(
    rows: Sequence[Mapping[str, str]], rules: Mapping[str, Any]
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    ordered = sorted(
        rows,
        key=lambda row: (
            row["candidate_id"],
            int(row["canonical_rank"]),
            BASELINES.index(row["baseline"]),
        ),
    )
    for row in ordered:
        features = derive_features(row)
        pose_class, score, memberships = classify_pose(features, rules, row["baseline"])
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "dual_receptor_r_gold_freeze_eligible": False,
            "source_docking_receptor": "8x6b",
            "candidate_id": row["candidate_id"],
            "family": row["family"],
            "canonical_rank": int(row["canonical_rank"]),
            "baseline": row["baseline"],
            "input_metrics_row_sha256": row["metrics_row_sha256"],
            "H_channel": CANONICAL_H_CHANNEL,
            "canonical_internal_channel_agreement": True,
            "H_hotspot_weight_fraction": float(features["H"]),
            "O_total_occluding_residue_pair_count_raw": int(features["O_raw"]),
            "O_log1p_total_occluding_residue_pair_count": float(features["O_log1p"]),
            "P_cdr_residue_pair_fraction": float(features["P"]),
            "P_cdr_residue_pair_count": int(features["P_numerator"]),
            "mu_H": memberships["H"],
            "mu_O": memberships["O"],
            "mu_P": memberships["P"],
            "S_pose_baseline": score,
            "pose_class": pose_class,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        normalized = {
            field: scalar_text(record.get(field), field)
            for field in POSE_SCORE_FIELDS
            if field != "pose_score_row_sha256"
        }
        normalized["pose_score_row_sha256"] = row_sha256(
            normalized, "pose_score_row_sha256"
        )
        output.append(normalized)
    return output


def pair_relevance(classes: Sequence[str]) -> tuple[int, str]:
    if len(classes) != 2 or any(value not in {"A", "B", "C", "E"} for value in classes):
        raise CalibrationError(f"Invalid baseline class pair: {classes}")
    count_a = classes.count("A")
    if count_a == 2:
        return 4, "A/A"
    if count_a == 1:
        return 3, "single_A"
    if "B" in classes:
        return 2, "B_support"
    if "C" in classes:
        return 1, "C_support"
    return 0, "E_only"


RUN_SCORE_FIELDS = (
    "schema_version",
    "protocol_id",
    "method_id",
    "formal_eligible",
    "dual_receptor_r_gold_freeze_eligible",
    "source_docking_receptor",
    "baseline_channel_semantics",
    "candidate_id",
    "family",
    "case_source",
    "R_calibration_run_8x6b_dock",
    "run_tier",
    "run_relevance",
    "qualifying_support_weight",
    "qualifying_supporting_pose_count",
    "F1",
    "F2",
    "F3",
    "F4",
    "N1",
    "N2",
    "N3",
    "N4",
    "baseline_gap_rank_weighted_mean",
    "support_weight_at_or_above_4",
    "support_count_at_or_above_4",
    "support_weight_at_or_above_3",
    "support_count_at_or_above_3",
    "support_weight_at_or_above_2",
    "support_count_at_or_above_2",
    "support_weight_at_or_above_1",
    "support_count_at_or_above_1",
    "pair_AA_count",
    "pair_single_A_count",
    "pair_B_support_count",
    "pair_C_support_count",
    "pair_E_only_count",
    "support_cutoff",
    "minimum_supporting_poses",
    "claim_boundary",
    "run_score_row_sha256",
)


def aggregate_run_scores(
    pose_rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    *,
    support_cutoff: float = SUPPORT_CUTOFF,
    min_supporting_poses: int = MIN_SUPPORTING_POSES,
) -> list[dict[str, str]]:
    if not 0.0 < support_cutoff <= 1.0:
        raise CalibrationError("Run support cutoff must be in (0,1]")
    if min_supporting_poses < 1:
        raise CalibrationError("Minimum supporting pose count must be positive")
    by_case_rank: dict[tuple[str, int], list[Mapping[str, str]]] = defaultdict(list)
    family_by_case: dict[str, str] = {}
    for row in pose_rows:
        case_id = row["candidate_id"]
        rank = int(row["canonical_rank"])
        by_case_rank[(case_id, rank)].append(row)
        family_by_case[case_id] = row["family"]
    case_ids = sorted(family_by_case)
    ranks = sorted({rank for _, rank in by_case_rank})
    q_rank = normalized_rank_weights(len(ranks))
    output: list[dict[str, str]] = []
    for case_id in case_ids:
        rank_records: list[dict[str, Any]] = []
        for rank in ranks:
            baseline_rows = by_case_rank.get((case_id, rank), [])
            if len(baseline_rows) != 2 or {row["baseline"] for row in baseline_rows} != set(BASELINES):
                raise CalibrationError(f"Run aggregation lacks two baselines for {case_id}/rank{rank}")
            classes = [row["pose_class"] for row in baseline_rows]
            relevance, pair_class = pair_relevance(classes)
            mean_score = sum(float(row["S_pose_baseline"]) for row in baseline_rows) / 2.0
            baseline_gap = abs(
                float(baseline_rows[0]["S_pose_baseline"])
                - float(baseline_rows[1]["S_pose_baseline"])
            )
            rank_records.append(
                {
                    "rank": rank,
                    "relevance": relevance,
                    "pair_class": pair_class,
                    "mean_score": mean_score,
                    "baseline_gap": baseline_gap,
                }
            )
        run_score = sum(q_rank[item["rank"]] * item["mean_score"] for item in rank_records)
        baseline_gap_mean = sum(
            q_rank[item["rank"]] * item["baseline_gap"] for item in rank_records
        )
        supports: dict[int, tuple[float, int]] = {}
        for relevance in (4, 3, 2, 1):
            supporting = [item for item in rank_records if item["relevance"] >= relevance]
            supports[relevance] = (
                sum(q_rank[item["rank"]] for item in supporting),
                len(supporting),
            )
        selected_relevance = 0
        qualifying_weight = 0.0
        qualifying_count = 0
        for relevance in (4, 3, 2, 1):
            weight, count = supports[relevance]
            if weight + 1e-15 >= support_cutoff and count >= min_supporting_poses:
                selected_relevance = relevance
                qualifying_weight = weight
                qualifying_count = count
                break
        tier = {4: "G1", 3: "G2", 2: "G3", 1: "G4", 0: "G5"}[selected_relevance]
        pair_counts = Counter(item["pair_class"] for item in rank_records)
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "dual_receptor_r_gold_freeze_eligible": False,
            "source_docking_receptor": "8x6b",
            "baseline_channel_semantics": "two_posthoc_scoring_baselines_on_same_8x6b_docked_pose_ensemble",
            "candidate_id": case_id,
            "family": family_by_case[case_id],
            "case_source": "positive_anchor" if case_id in positive_cases else "mutant_panel_control",
            "R_calibration_run_8x6b_dock": run_score,
            "run_tier": tier,
            "run_relevance": selected_relevance,
            "qualifying_support_weight": qualifying_weight,
            "qualifying_supporting_pose_count": qualifying_count,
            "F1": supports[1][0],
            "F2": supports[2][0],
            "F3": supports[3][0],
            "F4": supports[4][0],
            "N1": supports[1][1],
            "N2": supports[2][1],
            "N3": supports[3][1],
            "N4": supports[4][1],
            "baseline_gap_rank_weighted_mean": baseline_gap_mean,
            "support_weight_at_or_above_4": supports[4][0],
            "support_count_at_or_above_4": supports[4][1],
            "support_weight_at_or_above_3": supports[3][0],
            "support_count_at_or_above_3": supports[3][1],
            "support_weight_at_or_above_2": supports[2][0],
            "support_count_at_or_above_2": supports[2][1],
            "support_weight_at_or_above_1": supports[1][0],
            "support_count_at_or_above_1": supports[1][1],
            "pair_AA_count": pair_counts["A/A"],
            "pair_single_A_count": pair_counts["single_A"],
            "pair_B_support_count": pair_counts["B_support"],
            "pair_C_support_count": pair_counts["C_support"],
            "pair_E_only_count": pair_counts["E_only"],
            "support_cutoff": support_cutoff,
            "minimum_supporting_poses": min_supporting_poses,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        normalized = {
            field: scalar_text(record.get(field), field)
            for field in RUN_SCORE_FIELDS
            if field != "run_score_row_sha256"
        }
        normalized["run_score_row_sha256"] = row_sha256(
            normalized, "run_score_row_sha256"
        )
        output.append(normalized)
    return output


LOFO_FIELDS = (
    "schema_version",
    "method_id",
    "held_out_family",
    "held_out_candidate_id",
    "training_family_count",
    "training_case_count",
    "fold_defined",
    "failure_reason",
    "lofo_rules_sha256",
    "R_calibration_run_8x6b_dock",
    "all_family_tier",
    "held_out_fit_tier",
    "held_out_fit_relevance",
    "absolute_tier_shift",
    "held_out_G1_G3_retained",
    "qualifying_support_weight",
    "qualifying_supporting_pose_count",
    "formal_eligible",
    "dual_receptor_r_gold_freeze_eligible",
    "lofo_row_sha256",
)


def build_lofo_rows(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    all_family_run_rows: Sequence[Mapping[str, str]],
    ranks_per_case: int,
) -> list[dict[str, str]]:
    families = sorted({record["family"] for record in positive_cases.values()})
    all_tier = {
        row["candidate_id"]: row["run_tier"]
        for row in all_family_run_rows
        if row["candidate_id"] in positive_cases
    }
    if set(all_tier) != set(positive_cases):
        raise CalibrationError("All-family anchor tier closure failed before LOFO")
    tier_strength = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}
    output: list[dict[str, str]] = []
    for held_out in families:
        train_cases = {
            case_id: record
            for case_id, record in positive_cases.items()
            if record["family"] != held_out
        }
        held_out_cases = {
            case_id: record
            for case_id, record in positive_cases.items()
            if record["family"] == held_out
        }
        fold_defined = True
        failure_reason = ""
        lofo_rule_hash = ""
        run_by_case: dict[str, Mapping[str, str]] = {}
        try:
            lofo_rules = derive_rules(rows, train_cases, ranks_per_case)
            lofo_rule_hash = sha256_json(lofo_rules)
            held_out_rows = [
                row for row in rows if row["candidate_id"] in held_out_cases
            ]
            pose_scores = score_pose_rows(held_out_rows, lofo_rules)
            run_by_case = {
                row["candidate_id"]: row
                for row in aggregate_run_scores(pose_scores, held_out_cases)
            }
        except CalibrationError as error:
            fold_defined = False
            failure_reason = str(error)
        for candidate_id in sorted(held_out_cases):
            run = run_by_case.get(candidate_id)
            candidate_defined = fold_defined and run is not None
            held_tier = run["run_tier"] if candidate_defined else ""
            shift = (
                abs(tier_strength[held_tier] - tier_strength[all_tier[candidate_id]])
                if candidate_defined
                else None
            )
            record: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "method_id": METHOD_ID,
                "held_out_family": held_out,
                "held_out_candidate_id": candidate_id,
                "training_family_count": len(families) - 1,
                "training_case_count": len(train_cases),
                "fold_defined": candidate_defined,
                "failure_reason": "" if candidate_defined else failure_reason,
                "lofo_rules_sha256": lofo_rule_hash,
                "R_calibration_run_8x6b_dock": (
                    run["R_calibration_run_8x6b_dock"] if candidate_defined else ""
                ),
                "all_family_tier": all_tier[candidate_id],
                "held_out_fit_tier": held_tier,
                "held_out_fit_relevance": run["run_relevance"] if candidate_defined else "",
                "absolute_tier_shift": shift,
                "held_out_G1_G3_retained": held_tier in {"G1", "G2", "G3"},
                "qualifying_support_weight": (
                    run["qualifying_support_weight"] if candidate_defined else ""
                ),
                "qualifying_supporting_pose_count": (
                    run["qualifying_supporting_pose_count"] if candidate_defined else ""
                ),
                "formal_eligible": False,
                "dual_receptor_r_gold_freeze_eligible": False,
            }
            normalized = {
                field: scalar_text(record.get(field), field)
                for field in LOFO_FIELDS
                if field != "lofo_row_sha256"
            }
            normalized["lofo_row_sha256"] = row_sha256(
                normalized, "lofo_row_sha256"
            )
            output.append(normalized)
    return sorted(
        output, key=lambda row: (row["held_out_family"], row["held_out_candidate_id"])
    )


def summarize_lofo(
    rows: Sequence[Mapping[str, str]], positive_cases: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    by_family: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        by_family[row["held_out_family"]].append(row)
    expected_families = {record["family"] for record in positive_cases.values()}
    fold_definition_gate = (
        set(by_family) == expected_families
        and all(row["fold_defined"] == "true" for row in rows)
    )
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
    macro_recall = sum(recalls) / len(recalls) if recalls else 0.0
    defined_shifts = [
        int(row["absolute_tier_shift"])
        for row in rows
        if row["fold_defined"] == "true"
    ]
    shift_le_one_count = sum(shift <= 1 for shift in defined_shifts)
    max_shift = max(defined_shifts) if defined_shifts else None
    family_gate = all(item["at_least_one_G1_G3"] for item in family_summary.values())
    macro_gate = macro_recall >= 0.80
    shift_count_gate = len(defined_shifts) == 11 and shift_le_one_count >= 9
    max_shift_gate = max_shift is not None and max_shift <= 2
    return {
        "fold_definition_gate_passed": fold_definition_gate,
        "families": family_summary,
        "each_family_at_least_one_G1_G3_gate_passed": family_gate,
        "macro_family_G1_G3_recall": macro_recall,
        "macro_family_recall_gate_passed": macro_gate,
        "tier_shift_le_one_count": shift_le_one_count,
        "tier_shift_le_one_required": 9,
        "tier_shift_count_gate_passed": shift_count_gate,
        "maximum_absolute_tier_shift": max_shift,
        "maximum_shift_gate_passed": max_shift_gate,
        "passed": all(
            (fold_definition_gate, family_gate, macro_gate, shift_count_gate, max_shift_gate)
        ),
    }


BOOTSTRAP_FIELDS = (
    "schema_version",
    "method_id",
    "bootstrap_seed",
    "bootstrap_replicate",
    "replicate_defined",
    "baseline",
    "metric",
    "cutpoint",
    "metric_defined",
    "value_raw",
    "value_transformed",
    "raw_unit",
    "transform",
    "failure_reason",
    "formal_eligible",
    "bootstrap_row_sha256",
)

BOOTSTRAP_ANCHOR_FIELDS = (
    "schema_version",
    "method_id",
    "bootstrap_seed",
    "bootstrap_replicate",
    "evaluation_defined",
    "failure_reason",
    "candidate_id",
    "family",
    "R_calibration_run_8x6b_dock",
    "run_tier",
    "run_relevance",
    "F1",
    "F2",
    "F3",
    "F4",
    "N1",
    "N2",
    "N3",
    "N4",
    "qualifying_support_weight",
    "qualifying_supporting_pose_count",
    "baseline_gap_rank_weighted_mean",
    "formal_eligible",
    "bootstrap_anchor_row_sha256",
)


def hierarchical_bootstrap_rows(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    ranks_per_case: int,
    *,
    seed: int,
    replicates: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if replicates < 1:
        raise CalibrationError("Bootstrap replicate count must be positive")
    index = family_case_index(rows, positive_cases)
    families = sorted(index)
    q_rank = normalized_rank_weights(ranks_per_case)
    rng = random.Random(seed)
    threshold_output: list[dict[str, str]] = []
    anchor_output: list[dict[str, str]] = []
    original_anchor_rows = [row for row in rows if row["candidate_id"] in positive_cases]
    ordered_anchor_ids = sorted(positive_cases)

    for replicate in range(1, replicates + 1):
        sampled_values: dict[str, Any] = {
            "H_canonical": [],
            "baseline": {
                baseline: {metric: [] for metric in BASELINE_METRICS}
                for baseline in BASELINES
            },
        }
        family_draws = [rng.choice(families) for _ in families]
        for family in family_draws:
            case_ids = sorted(index[family])
            case_draws = [rng.choice(case_ids) for _ in case_ids]
            for case_id in case_draws:
                by_key = {
                    (int(row["canonical_rank"]), row["baseline"]): row
                    for row in index[family][case_id]
                }
                for rank in range(1, ranks_per_case + 1):
                    weight = (1.0 / len(families)) * (1.0 / len(case_ids)) * q_rank[rank]
                    rank_rows = {
                        baseline: by_key[(rank, baseline)] for baseline in BASELINES
                    }
                    shared_values = {
                        baseline: tuple(
                            rank_rows[baseline].get(field, "").strip()
                            for field in CANONICAL_INTERNAL_CONTACT_FIELDS
                        )
                        for baseline in BASELINES
                    }
                    if shared_values["8x6b"] != shared_values["9e6y"]:
                        raise CalibrationError(
                            f"Bootstrap canonical H/internal channel drift for "
                            f"{case_id}/rank{rank}"
                        )
                    sampled_values["H_canonical"].append(
                        (float(derive_features(rank_rows["8x6b"])["H"]), weight)
                    )
                    for baseline in BASELINES:
                        features = derive_features(rank_rows[baseline])
                        for metric in BASELINE_METRICS:
                            sampled_values["baseline"][baseline][metric].append(
                                (float(features[metric]), weight)
                            )

        channels = [(CANONICAL_H_CHANNEL, "H", sampled_values["H_canonical"])]
        channels.extend(
            (baseline, metric, sampled_values["baseline"][baseline][metric])
            for baseline in BASELINES
            for metric in BASELINE_METRICS
        )
        fits: dict[tuple[str, str], dict[str, Any]] = {}
        for baseline, metric, metric_values in channels:
            fits[(baseline, metric)] = threshold_fit_diagnostic(
                metric_values, LOWER_QUANTILE, UPPER_QUANTILE, metric=metric
            )
        replicate_defined = all(fit["defined"] for fit in fits.values())
        replicate_failures = sorted(
            f"{baseline}/{metric}:{fit['failure_reason']}"
            for (baseline, metric), fit in fits.items()
            if not fit["defined"]
        )
        replicate_failure = ";".join(replicate_failures)

        for baseline, metric, _metric_values in channels:
            fit = fits[(baseline, metric)]
            for cutpoint in ("L", "U"):
                record: dict[str, Any] = {
                    "schema_version": SCHEMA_VERSION,
                    "method_id": METHOD_ID,
                    "bootstrap_seed": seed,
                    "bootstrap_replicate": replicate,
                    "replicate_defined": replicate_defined,
                    "baseline": baseline,
                    "metric": metric,
                    "cutpoint": cutpoint,
                    "metric_defined": fit["defined"],
                    "value_raw": fit[f"{cutpoint}_raw"],
                    "value_transformed": fit[f"{cutpoint}_transformed"],
                    "raw_unit": fit["raw_unit"],
                    "transform": fit["transform"],
                    "failure_reason": fit["failure_reason"],
                    "formal_eligible": False,
                }
                normalized = {
                    field: scalar_text(record.get(field), field)
                    for field in BOOTSTRAP_FIELDS
                    if field != "bootstrap_row_sha256"
                }
                normalized["bootstrap_row_sha256"] = row_sha256(
                    normalized, "bootstrap_row_sha256"
                )
                threshold_output.append(normalized)

        runs_by_case: dict[str, Mapping[str, str]] = {}
        if replicate_defined:
            bootstrap_rules = {
                "thresholds": {
                    "H_canonical": fits[(CANONICAL_H_CHANNEL, "H")],
                    "baseline": {
                        baseline: {
                            metric: fits[(baseline, metric)]
                            for metric in BASELINE_METRICS
                        }
                        for baseline in BASELINES
                    },
                }
            }
            bootstrap_poses = score_pose_rows(original_anchor_rows, bootstrap_rules)
            runs_by_case = {
                row["candidate_id"]: row
                for row in aggregate_run_scores(bootstrap_poses, positive_cases)
            }
        for candidate_id in ordered_anchor_ids:
            run = runs_by_case.get(candidate_id)
            record = {
                "schema_version": SCHEMA_VERSION,
                "method_id": METHOD_ID,
                "bootstrap_seed": seed,
                "bootstrap_replicate": replicate,
                "evaluation_defined": run is not None,
                "failure_reason": "" if run is not None else replicate_failure,
                "candidate_id": candidate_id,
                "family": positive_cases[candidate_id]["family"],
                "R_calibration_run_8x6b_dock": (
                    run["R_calibration_run_8x6b_dock"] if run is not None else ""
                ),
                "run_tier": run["run_tier"] if run is not None else "",
                "run_relevance": run["run_relevance"] if run is not None else "",
                **{
                    field: run[field] if run is not None else ""
                    for field in (
                        "F1", "F2", "F3", "F4", "N1", "N2", "N3", "N4",
                        "qualifying_support_weight",
                        "qualifying_supporting_pose_count",
                        "baseline_gap_rank_weighted_mean",
                    )
                },
                "formal_eligible": False,
            }
            normalized = {
                field: scalar_text(record.get(field), field)
                for field in BOOTSTRAP_ANCHOR_FIELDS
                if field != "bootstrap_anchor_row_sha256"
            }
            normalized["bootstrap_anchor_row_sha256"] = row_sha256(
                normalized, "bootstrap_anchor_row_sha256"
            )
            anchor_output.append(normalized)
    return threshold_output, anchor_output

def summarize_bootstrap(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    grouped_raw: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    grouped_transformed: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    replicate_ids: set[int] = set()
    undefined_replicates: set[int] = set()
    undefined_by_channel: Counter[str] = Counter()
    for row in rows:
        replicate = int(row["bootstrap_replicate"])
        replicate_ids.add(replicate)
        if row["replicate_defined"] != "true":
            undefined_replicates.add(replicate)
        key = (row["baseline"], row["metric"], row["cutpoint"])
        if row["metric_defined"] == "true":
            grouped_raw[key].append(float(row["value_raw"]))
            grouped_transformed[key].append(float(row["value_transformed"]))
        elif row["cutpoint"] == "L":
            undefined_by_channel[f"{row['baseline']}/{row['metric']}"] += 1
    channels = {
        CANONICAL_H_CHANNEL: ("H",),
        **{baseline: BASELINE_METRICS for baseline in BASELINES},
    }
    thresholds: dict[str, Any] = {}
    for baseline, metrics in channels.items():
        thresholds[baseline] = {}
        for metric in metrics:
            thresholds[baseline][metric] = {}
            for cutpoint in ("L", "U"):
                key = (baseline, metric, cutpoint)
                raw_values = grouped_raw[key]
                transformed_values = grouped_transformed[key]
                thresholds[baseline][metric][cutpoint] = {
                    "defined_replicates": len(raw_values),
                    "undefined_replicates": len(replicate_ids) - len(raw_values),
                    "raw_q025": ordinary_quantile(raw_values, 0.025) if raw_values else None,
                    "raw_median": ordinary_quantile(raw_values, 0.50) if raw_values else None,
                    "raw_q975": ordinary_quantile(raw_values, 0.975) if raw_values else None,
                    "transformed_q025": ordinary_quantile(transformed_values, 0.025) if transformed_values else None,
                    "transformed_median": ordinary_quantile(transformed_values, 0.50) if transformed_values else None,
                    "transformed_q975": ordinary_quantile(transformed_values, 0.975) if transformed_values else None,
                }
    return {
        "replicate_count": len(replicate_ids),
        "undefined_replicate_count": len(undefined_replicates),
        "undefined_replicate_fraction": (
            len(undefined_replicates) / len(replicate_ids) if replicate_ids else 1.0
        ),
        "undefined_by_channel": dict(sorted(undefined_by_channel.items())),
        "thresholds": thresholds,
    }


def summarize_bootstrap_anchors(
    rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    replicates: int,
) -> dict[str, Any]:
    by_case: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        by_case[row["candidate_id"]].append(row)
    if set(by_case) != set(positive_cases):
        raise CalibrationError("Bootstrap anchor-evaluation candidate closure failed")
    anchor_summary: dict[str, Any] = {}
    modal_pass_count = 0
    family_retention: dict[str, list[float]] = defaultdict(list)
    for candidate_id in sorted(positive_cases):
        candidate_rows = by_case[candidate_id]
        if len(candidate_rows) != replicates:
            raise CalibrationError(
                f"Bootstrap anchor rows for {candidate_id}: {len(candidate_rows)} != {replicates}"
            )
        defined = [row for row in candidate_rows if row["evaluation_defined"] == "true"]
        tiers = Counter(row["run_tier"] for row in defined)
        modal_tier = max(
            ("G1", "G2", "G3", "G4", "G5"),
            key=lambda tier: (tiers[tier], -int(tier[1:])),
        )
        modal_probability = tiers[modal_tier] / replicates
        retention_probability = sum(
            tiers[tier] for tier in ("G1", "G2", "G3")
        ) / replicates
        modal_pass = modal_probability >= 0.70
        modal_pass_count += int(modal_pass)
        family = positive_cases[candidate_id]["family"]
        family_retention[family].append(retention_probability)
        scores = [float(row["R_calibration_run_8x6b_dock"]) for row in defined]
        gaps = [float(row["baseline_gap_rank_weighted_mean"]) for row in defined]
        supports = [float(row["qualifying_support_weight"]) for row in defined]
        anchor_summary[candidate_id] = {
            "family": family,
            "defined_replicates": len(defined),
            "undefined_replicates": replicates - len(defined),
            "tier_counts": {tier: tiers[tier] for tier in ("G1", "G2", "G3", "G4", "G5")},
            "tier_probabilities": {
                tier: tiers[tier] / replicates for tier in ("G1", "G2", "G3", "G4", "G5")
            },
            "modal_tier": modal_tier,
            "modal_tier_probability": modal_probability,
            "modal_probability_gate_passed": modal_pass,
            "g1_g3_retention_probability": retention_probability,
            "R_q025": ordinary_quantile(scores, 0.025) if scores else None,
            "R_median": ordinary_quantile(scores, 0.50) if scores else None,
            "R_q975": ordinary_quantile(scores, 0.975) if scores else None,
            "baseline_gap_median": ordinary_quantile(gaps, 0.50) if gaps else None,
            "qualifying_support_median": ordinary_quantile(supports, 0.50) if supports else None,
        }
    family_summary = {
        family: {
            "best_anchor_retention_probability": max(values),
            "at_least_one_anchor_retention_ge_0_70": max(values) >= 0.70,
        }
        for family, values in sorted(family_retention.items())
    }
    modal_gate = modal_pass_count >= 9
    family_gate = all(
        item["at_least_one_anchor_retention_ge_0_70"]
        for item in family_summary.values()
    )
    return {
        "replicates": replicates,
        "anchors": anchor_summary,
        "families": family_summary,
        "anchors_modal_probability_ge_0_70_count": modal_pass_count,
        "anchors_modal_probability_gate_required": 9,
        "modal_probability_gate_passed": modal_gate,
        "family_retention_gate_passed": family_gate,
        "passed": modal_gate and family_gate,
    }


MUTANT_DELTA_FIELDS = (
    "schema_version",
    "method_id",
    "candidate_id",
    "declared_base_molecule",
    "declared_base_candidate_id",
    "family",
    "mutation_class",
    "mutations_1based",
    "candidate_R_calibration_run_8x6b_dock",
    "base_R_calibration_run_8x6b_dock",
    "paired_delta_candidate_minus_base",
    "candidate_run_tier",
    "base_run_tier",
    "comparison_semantics",
    "binary_negative_label_assigned",
    "formal_eligible",
    "mutant_delta_row_sha256",
)


def build_mutant_delta_rows(
    run_rows: Sequence[Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    base_by_molecule: Mapping[str, str],
) -> list[dict[str, str]]:
    run_by_case = {row["candidate_id"]: row for row in run_rows}
    output: list[dict[str, str]] = []
    for case_id in sorted(mutant_cases):
        metadata = mutant_cases[case_id]
        if metadata["control_type"] == "base_reference":
            continue
        base_id = base_by_molecule[metadata["base_molecule"]]
        if case_id not in run_by_case or base_id not in run_by_case:
            raise CalibrationError(f"Missing paired run score for {case_id} -> {base_id}")
        candidate_score = float(run_by_case[case_id]["R_calibration_run_8x6b_dock"])
        base_score = float(run_by_case[base_id]["R_calibration_run_8x6b_dock"])
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "method_id": METHOD_ID,
            "candidate_id": case_id,
            "declared_base_molecule": metadata["base_molecule"],
            "declared_base_candidate_id": base_id,
            "family": metadata["family"],
            "mutation_class": metadata["mutation_class"],
            "mutations_1based": metadata["mutations_1based"],
            "candidate_R_calibration_run_8x6b_dock": candidate_score,
            "base_R_calibration_run_8x6b_dock": base_score,
            "paired_delta_candidate_minus_base": candidate_score - base_score,
            "candidate_run_tier": run_by_case[case_id]["run_tier"],
            "base_run_tier": run_by_case[base_id]["run_tier"],
            "comparison_semantics": "paired_geometry_delta_to_declared_base_only_not_binary_truth",
            "binary_negative_label_assigned": False,
            "formal_eligible": False,
        }
        normalized = {
            field: scalar_text(record.get(field), field)
            for field in MUTANT_DELTA_FIELDS
            if field != "mutant_delta_row_sha256"
        }
        normalized["mutant_delta_row_sha256"] = row_sha256(
            normalized, "mutant_delta_row_sha256"
        )
        output.append(normalized)
    return output


ROBUSTNESS_FIELDS = (
    "schema_version",
    "method_id",
    "grid_id",
    "lower_quantile",
    "upper_quantile",
    "support_cutoff",
    "primary_preregistered_row",
    "best_row_selected",
    "selection_semantics",
    "positive_G1_count",
    "positive_G2_count",
    "positive_G3_count",
    "positive_G4_count",
    "positive_G5_count",
    "all_G1_count",
    "all_G2_count",
    "all_G3_count",
    "all_G4_count",
    "all_G5_count",
    "positive_run_score_median",
    "mutant_paired_delta_median",
    "rules_sha256",
    "formal_eligible",
    "robustness_row_sha256",
)


def build_robustness_rows(
    metrics_rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    mutant_cases: Mapping[str, Mapping[str, str]],
    base_by_molecule: Mapping[str, str],
    ranks_per_case: int,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    grid_index = 0
    for lower in ROBUSTNESS_LOWER_QUANTILES:
        for upper in ROBUSTNESS_UPPER_QUANTILES:
            for support in ROBUSTNESS_SUPPORT_CUTOFFS:
                grid_index += 1
                rules = derive_rules(
                    metrics_rows,
                    positive_cases,
                    ranks_per_case,
                    lower_quantile=lower,
                    upper_quantile=upper,
                )
                poses = score_pose_rows(metrics_rows, rules)
                runs = aggregate_run_scores(
                    poses, positive_cases, support_cutoff=support
                )
                deltas = build_mutant_delta_rows(runs, mutant_cases, base_by_molecule)
                positive_tiers = Counter(
                    row["run_tier"] for row in runs if row["candidate_id"] in positive_cases
                )
                all_tiers = Counter(row["run_tier"] for row in runs)
                positive_scores = [
                    float(row["R_calibration_run_8x6b_dock"])
                    for row in runs
                    if row["candidate_id"] in positive_cases
                ]
                delta_values = [float(row["paired_delta_candidate_minus_base"]) for row in deltas]
                record: dict[str, Any] = {
                    "schema_version": SCHEMA_VERSION,
                    "method_id": METHOD_ID,
                    "grid_id": f"GRID_{grid_index:02d}",
                    "lower_quantile": lower,
                    "upper_quantile": upper,
                    "support_cutoff": support,
                    "primary_preregistered_row": (
                        lower == LOWER_QUANTILE
                        and upper == UPPER_QUANTILE
                        and support == SUPPORT_CUTOFF
                    ),
                    "best_row_selected": False,
                    "selection_semantics": "fixed_grid_robustness_only_no_best_row_selection",
                    **{f"positive_{tier}_count": positive_tiers[tier] for tier in ("G1", "G2", "G3", "G4", "G5")},
                    **{f"all_{tier}_count": all_tiers[tier] for tier in ("G1", "G2", "G3", "G4", "G5")},
                    "positive_run_score_median": median(positive_scores),
                    "mutant_paired_delta_median": median(delta_values),
                    "rules_sha256": sha256_json(rules),
                    "formal_eligible": False,
                }
                normalized = {
                    field: scalar_text(record.get(field), field)
                    for field in ROBUSTNESS_FIELDS
                    if field != "robustness_row_sha256"
                }
                normalized["robustness_row_sha256"] = row_sha256(
                    normalized, "robustness_row_sha256"
                )
                output.append(normalized)
    return output


def rules_document(
    rules: Mapping[str, Any],
    config: CalibrationConfig,
    input_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    freeze_eligible = (
        config.bootstrap_seed == BOOTSTRAP_SEED
        and config.bootstrap_replicates == BOOTSTRAP_REPLICATES
        and config.contract == CalibrationContract()
        and input_bindings.get("upstream_audit", {}).get("required") is True
    )
    status = (
        "PASS_V1_2_FAMILY_AWARE_POSE_AND_SINGLE_RUN_RULES_FROZEN"
        if freeze_eligible
        else "PASS_V1_2_FAMILY_AWARE_DRY_RUN_BUILT_NOT_FROZEN"
    )
    core = {
        "method_id": METHOD_ID,
        "feature_definitions": {
            "H": "one canonical shared hotspot_weight_fraction per source pose",
            "O": "log1p(total_occluding_residue_pair_count)",
            "P": "(cdr1+cdr2+cdr3 occluding residue-pair count)/total occluding residue-pair count",
        },
        "calibration": rules,
        "canonical_shared_channel_gate": list(CANONICAL_INTERNAL_CONTACT_FIELDS),
        "H_cutpoint_semantics": "one family-balanced H_canonical L/U shared by both post-hoc baselines",
        "pose_score": "sqrt(mu_O * (mu_H + mu_P) / 2)",
        "pose_classes": {
            "A": "O>=U_O and H>=U_H and P>=L_P",
            "B": "not A and O>=L_O and (H>=L_H or P>=L_P)",
            "C": "H>=L_H and O<L_O",
            "E": "otherwise",
        },
        "pair_relevance": {
            "4": "A/A",
            "3": "exactly one baseline A",
            "2": "no A and at least one B",
            "1": "no A/B and at least one C",
            "0": "E/E",
        },
        "run_score": "rank-weighted mean of the two post-hoc baseline S_pose values",
        "run_score_name": "R_calibration_run_8x6b_dock",
        "run_tier": {
            "support_semantics": "highest cumulative relevance threshold satisfying both gates",
            "normalized_rank_weight_support_cutoff": SUPPORT_CUTOFF,
            "minimum_supporting_pose_count": MIN_SUPPORTING_POSES,
            "mapping": {"4": "G1", "3": "G2", "2": "G3", "1": "G4", "0": "G5"},
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "protocol_id": PROTOCOL_ID,
        "formal_eligible": False,
        "threshold_freeze_eligible": False,
        "pose_rule_threshold_freeze_eligible": freeze_eligible,
        "single_8x6b_dock_run_method_freeze_eligible": freeze_eligible,
        "dual_receptor_r_gold_freeze_eligible": False,
        "training_label_release_eligible": False,
        "computational_geometry_teacher_only": True,
        "source_docking_receptor": "8x6b",
        "baseline_channel_semantics": "two_posthoc_scoring_baselines_on_same_8x6b_docked_pose_ensemble",
        "canonical_shared_h_and_internal_contact_gate": {
            "passed": True,
            "fields": list(CANONICAL_INTERNAL_CONTACT_FIELDS),
            "H_cutpoint_count": 1,
            "shared_between_baselines": True,
        },
        "claim_boundary": CLAIM_BOUNDARY,
        "rules_core": core,
        "rules_core_sha256": sha256_json(core),
        "input_bindings": dict(input_bindings),
        "toolchain": {
            "calibration_script_relpath": canonical_path(Path(__file__)),
            "calibration_script_sha256": sha256_file(Path(__file__)),
            "bootstrap_seed": config.bootstrap_seed,
            "bootstrap_replicates": config.bootstrap_replicates,
        },
    }


def summarize_tiers(rows: Sequence[Mapping[str, str]]) -> dict[str, int]:
    counts = Counter(row["run_tier"] for row in rows)
    return {tier: counts[tier] for tier in ("G1", "G2", "G3", "G4", "G5")}


def render_report(
    *,
    rules: Mapping[str, Any],
    run_rows: Sequence[Mapping[str, str]],
    positive_cases: Mapping[str, Mapping[str, str]],
    lofo_rows: Sequence[Mapping[str, str]],
    bootstrap_summary: Mapping[str, Any],
    mutant_delta_rows: Sequence[Mapping[str, str]],
    robustness_rows: Sequence[Mapping[str, str]],
    artifact_hashes: Mapping[str, Mapping[str, Any]],
    status: str,
    freeze_eligible: bool,
    bootstrap_seed: int,
    bootstrap_replicates: int,
) -> str:
    positive_runs = [row for row in run_rows if row["candidate_id"] in positive_cases]
    positive_tiers = summarize_tiers(positive_runs)
    all_tiers = summarize_tiers(run_rows)
    lofo_tiers = summarize_tiers(lofo_rows)
    delta_values = [float(row["paired_delta_candidate_minus_base"]) for row in mutant_delta_rows]
    primary_grid = [row for row in robustness_rows if row["primary_preregistered_row"] == "true"]
    if len(primary_grid) != 1:
        raise CalibrationError("Robustness grid must contain one preregistered primary row")
    lines = [
        "# PVRIG V3 P2 Docking Gold V1.2 family-aware 校准结果",
        "",
        "## 结论",
        "",
        "```text",
        status,
        f"pose_rule_threshold_freeze_eligible={str(freeze_eligible).lower()}",
        "formal_eligible=false",
        "dual_receptor_r_gold_freeze_eligible=false",
        "training_label_release_eligible=false",
        "```",
        "",
        "本次产物只涉及 **8X6B docking 单一 pose ensemble** 上的 pose-level A/B/C/E 规则和 "
        "`R_calibration_run_8x6b_dock`。8X6B/9E6Y 是对同一批 pose 的两个 post-hoc scoring channel，"
        "不是两次独立 receptor docking，因此仍不能冻结或宣称 `R_gold`。",
        "",
        "## 数据与权重",
        "",
        f"- 已知成功 anchor：{len(positive_cases)} 个 case，{len(set(v['family'] for v in positive_cases.values()))} 个 family。",
        f"- 全部计分 case：{len(run_rows)}；每个 case 固定 Top-8，每个 pose 对 8X6B/9E6Y 各计分一次。",
        "- family 等权，family 内 case 等权，case 内 rank 使用 `1/log2(rank+1)` 归一化权重。",
        "- mutant 不被当作负样本；只计算它与 manifest 声明的 base reference 之间的成对几何差值。",
        "",
        "## 主规则阈值",
        "",
        "| baseline | metric | L=q20 positive-part | U=q50 positive-part | zero weight |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    thresholds = rules["thresholds"]
    threshold_channels = [(CANONICAL_H_CHANNEL, "H", thresholds["H_canonical"])]
    threshold_channels.extend(
        (baseline, metric, thresholds["baseline"][baseline][metric])
        for baseline in BASELINES
        for metric in BASELINE_METRICS
    )
    for baseline, metric, item in threshold_channels:
        lines.append(
            f"| {baseline} | {metric} | {item['L']:.6g} | {item['U']:.6g} | {item['zero_weight']:.4f} |"
        )
    lines.extend(
        [
            "",
            "`H` 每个 source pose 只有一个 canonical shared channel，两个 baseline 共用同一组 H L/U 和 `mu_H`。"
            "`O` 在阈值学习和规则应用中都使用 `log1p(total_occluding_residue_pair_count)`；"
            "`P` 为 CDR1+CDR2+CDR3 的 residue-pair count 占 total pair count 的比例。"
            "零值不参与 positive-part q20/q50，且 membership 为 0。",
            "",
            "## 主要输出",
            "",
            f"- 11 个 success anchor 的 tier：`{positive_tiers}`。",
            f"- 47 个全部 case 的 tier：`{all_tiers}`。",
            f"- leave-one-family-out 的 11 个留出 case tier：`{lofo_tiers}`。",
            f"- mutant paired deltas：{len(mutant_delta_rows)} 对；median(candidate-base)="
            f"`{median(delta_values):.6g}`。该值只是计算几何差值，不是活性方向真值。",
            f"- robustness grid：{len(robustness_rows)} 个预先固定组合；`best_row_selected=false` "
            "对所有行成立，没有按结果选最好的一行。",
            "",
            "## Hierarchical family bootstrap",
            "",
            "| baseline | metric/cutpoint | 2.5% | median | 97.5% |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    bootstrap_channels = {
        CANONICAL_H_CHANNEL: ("H",),
        **{baseline: BASELINE_METRICS for baseline in BASELINES},
    }
    for baseline, metrics in bootstrap_channels.items():
        for metric in metrics:
            for cutpoint in ("L", "U"):
                item = bootstrap_summary[baseline][metric][cutpoint]
                lines.append(
                    f"| {baseline} | {metric}/{cutpoint} | {item['q025']:.6g} | "
                    f"{item['median']:.6g} | {item['q975']:.6g} |"
                )
    lines.extend(
        [
            "",
            "Bootstrap 先对 family 有放回抽样，再在被抽中的 family 内对 case 有放回抽样；"
            f"seed={bootstrap_seed}，B={bootstrap_replicates}。Top-8 rank 是预先固定的计算单元，"
            "不再对 rank 独立重抽样。",
            "",
            "## 证据边界与下一关",
            "",
            "1. 这些规则可用于 V1.2 pose-level 和单个 8X6B-dock run 的可重复计分。",
            "2. 它们不能单独解除 `P2_TRAINING_BLOCKED`，也不能把 mutant 变成 non-binder 负样本。",
            "3. 必须继续完成 8-run smoke、52-run failure regression，并在 rebuilt Pilot64 中验证独立 "
            "8X6B-dock/9E6Y-dock aggregation，才能进入全新 formal holdout。",
            "",
            "## Artifact hashes",
            "",
            "| artifact | rows | SHA256 |",
            "| --- | ---: | --- |",
        ]
    )
    for name, evidence in artifact_hashes.items():
        lines.append(f"| `{name}` | {evidence.get('rows', '')} | `{evidence['sha256']}` |")
    lines.extend(["", f"> Claim boundary: {CLAIM_BOUNDARY}", ""])
    return "\n".join(lines)


def publish_directory(staging: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except Exception:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_calibration(config: CalibrationConfig) -> dict[str, Any]:
    metrics_fields, metrics_rows = read_csv_strict(config.metrics_csv)
    positive_cases = load_positive_manifest(config.positive_manifest)
    mutant_cases, base_by_molecule = load_mutant_manifest(config.mutant_manifest)
    observed_contract = validate_metrics_rows(
        metrics_fields, metrics_rows, positive_cases, mutant_cases, config.contract
    )
    upstream = validate_upstream_audit(config.upstream_audit, config.metrics_csv)
    input_bindings = {
        "continuous_metrics": {
            "relpath": canonical_path(config.metrics_csv),
            "sha256": sha256_file(config.metrics_csv),
            "rows": len(metrics_rows),
            "row_hash_chain": row_hash_chain(metrics_rows, "metrics_row_sha256"),
        },
        "upstream_audit": upstream,
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
    rules = derive_rules(metrics_rows, positive_cases, config.contract.ranks_per_case)
    rules_payload = rules_document(rules, config, input_bindings)
    freeze_eligible = bool(rules_payload["pose_rule_threshold_freeze_eligible"])
    status = str(rules_payload["status"])
    pose_rows = score_pose_rows(metrics_rows, rules)
    run_rows = aggregate_run_scores(pose_rows, positive_cases)
    lofo_rows = build_lofo_rows(
        metrics_rows, positive_cases, config.contract.ranks_per_case
    )
    bootstrap_rows = hierarchical_bootstrap_rows(
        metrics_rows,
        positive_cases,
        config.contract.ranks_per_case,
        seed=config.bootstrap_seed,
        replicates=config.bootstrap_replicates,
    )
    bootstrap_summary = summarize_bootstrap(bootstrap_rows)
    mutant_delta_rows = build_mutant_delta_rows(
        run_rows, mutant_cases, base_by_molecule
    )
    if len(mutant_delta_rows) != config.contract.mutant_delta_count:
        raise CalibrationError(
            f"Expected {config.contract.mutant_delta_count} mutant deltas, "
            f"found {len(mutant_delta_rows)}"
        )
    robustness_rows = build_robustness_rows(
        metrics_rows,
        positive_cases,
        mutant_cases,
        base_by_molecule,
        config.contract.ranks_per_case,
    )

    config.outdir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{config.outdir.name}.staging-", dir=config.outdir.parent)
    )
    try:
        rules_path = staging / RULES_NAME
        pose_path = staging / POSE_SCORES_NAME
        run_path = staging / RUN_SCORES_NAME
        lofo_path = staging / LOFO_NAME
        bootstrap_path = staging / BOOTSTRAP_NAME
        mutant_path = staging / MUTANT_DELTAS_NAME
        robustness_path = staging / ROBUSTNESS_NAME
        write_json(rules_path, rules_payload)
        write_csv(pose_path, pose_rows, POSE_SCORE_FIELDS)
        write_csv(run_path, run_rows, RUN_SCORE_FIELDS)
        write_csv(lofo_path, lofo_rows, LOFO_FIELDS)
        write_csv(bootstrap_path, bootstrap_rows, BOOTSTRAP_FIELDS)
        write_csv(mutant_path, mutant_delta_rows, MUTANT_DELTA_FIELDS)
        write_csv(robustness_path, robustness_rows, ROBUSTNESS_FIELDS)
        artifact_paths: dict[str, tuple[Path, int | None, str | None]] = {
            RULES_NAME: (rules_path, None, None),
            POSE_SCORES_NAME: (pose_path, len(pose_rows), "pose_score_row_sha256"),
            RUN_SCORES_NAME: (run_path, len(run_rows), "run_score_row_sha256"),
            LOFO_NAME: (lofo_path, len(lofo_rows), "lofo_row_sha256"),
            BOOTSTRAP_NAME: (
                bootstrap_path,
                len(bootstrap_rows),
                "bootstrap_row_sha256",
            ),
            MUTANT_DELTAS_NAME: (
                mutant_path,
                len(mutant_delta_rows),
                "mutant_delta_row_sha256",
            ),
            ROBUSTNESS_NAME: (
                robustness_path,
                len(robustness_rows),
                "robustness_row_sha256",
            ),
        }
        artifact_hashes: dict[str, dict[str, Any]] = {}
        row_lookup = {
            POSE_SCORES_NAME: pose_rows,
            RUN_SCORES_NAME: run_rows,
            LOFO_NAME: lofo_rows,
            BOOTSTRAP_NAME: bootstrap_rows,
            MUTANT_DELTAS_NAME: mutant_delta_rows,
            ROBUSTNESS_NAME: robustness_rows,
        }
        for name, (path, row_count, hash_field) in artifact_paths.items():
            evidence: dict[str, Any] = {"sha256": sha256_file(path)}
            if row_count is not None:
                evidence["rows"] = row_count
            if hash_field is not None:
                evidence["row_hash_chain"] = row_hash_chain(row_lookup[name], hash_field)
            artifact_hashes[name] = evidence

        report_text = render_report(
            rules=rules,
            run_rows=run_rows,
            positive_cases=positive_cases,
            lofo_rows=lofo_rows,
            bootstrap_summary=bootstrap_summary,
            mutant_delta_rows=mutant_delta_rows,
            robustness_rows=robustness_rows,
            artifact_hashes=artifact_hashes,
            status=status,
            freeze_eligible=freeze_eligible,
            bootstrap_seed=config.bootstrap_seed,
            bootstrap_replicates=config.bootstrap_replicates,
        )
        report_staging = staging / config.report.name
        report_staging.write_text(report_text, encoding="utf-8")
        report_evidence = {
            "relpath": canonical_path(config.report),
            "sha256": sha256_file(report_staging),
        }
        audit = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "protocol_id": PROTOCOL_ID,
            "method_id": METHOD_ID,
            "formal_eligible": False,
            "threshold_freeze_eligible": False,
            "pose_rule_threshold_freeze_eligible": freeze_eligible,
            "single_8x6b_dock_run_method_freeze_eligible": freeze_eligible,
            "dual_receptor_r_gold_freeze_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_blocked": True,
            "computational_geometry_teacher_only": True,
            "source_docking_receptor": "8x6b",
            "baseline_channel_semantics": "two_posthoc_scoring_baselines_on_same_8x6b_docked_pose_ensemble",
            "canonical_shared_h_and_internal_contact_gate": {
                "passed": True,
                "fields": list(CANONICAL_INTERNAL_CONTACT_FIELDS),
                "H_cutpoint_count": 1,
                "shared_between_baselines": True,
            },
            "claim_boundary": CLAIM_BOUNDARY,
            "observed_contract": observed_contract,
            "positive_tiers": summarize_tiers(
                [row for row in run_rows if row["candidate_id"] in positive_cases]
            ),
            "all_case_tiers": summarize_tiers(run_rows),
            "lofo_tiers": summarize_tiers(lofo_rows),
            "bootstrap": {
                "seed": config.bootstrap_seed,
                "replicates": config.bootstrap_replicates,
                "hierarchy": "family_with_replacement_then_case_within_family_with_replacement",
                "summary": bootstrap_summary,
            },
            "mutant_comparison": {
                "paired_delta_count": len(mutant_delta_rows),
                "binary_negative_labels_assigned": False,
                "semantics": "declared-base paired computational geometry deltas only",
            },
            "robustness_grid": {
                "rows": len(robustness_rows),
                "fixed_before_result_review": True,
                "best_row_selected": False,
                "lower_quantiles": list(ROBUSTNESS_LOWER_QUANTILES),
                "upper_quantiles": list(ROBUSTNESS_UPPER_QUANTILES),
                "support_cutoffs": list(ROBUSTNESS_SUPPORT_CUTOFFS),
            },
            "input_bindings": input_bindings,
            "toolchain": rules_payload["toolchain"],
            "output_sha256": artifact_hashes,
            "report": report_evidence,
        }
        write_json(staging / AUDIT_NAME, audit)
        publish_directory(staging, config.outdir)
        config.report.parent.mkdir(parents=True, exist_ok=True)
        report_source = config.outdir / config.report.name
        report_tmp = config.report.with_name(config.report.name + ".tmp")
        shutil.copyfile(report_source, report_tmp)
        os.replace(report_tmp, config.report)
        report_source.unlink()
        return audit
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-csv", type=Path, default=DEFAULT_METRICS_CSV)
    parser.add_argument("--upstream-audit", type=Path, default=DEFAULT_UPSTREAM_AUDIT)
    parser.add_argument("--positive-manifest", type=Path, default=DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = CalibrationConfig(
        metrics_csv=args.metrics_csv.resolve(),
        upstream_audit=args.upstream_audit.resolve(),
        positive_manifest=args.positive_manifest.resolve(),
        mutant_manifest=args.mutant_manifest.resolve(),
        outdir=args.outdir.resolve(),
        report=args.report.resolve(),
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_replicates=args.bootstrap_replicates,
    )
    try:
        audit = build_calibration(config)
    except (CalibrationError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL_V1_2_FAMILY_AWARE_CALIBRATION: {error}")
        return 2
    print(canonical_json(audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
