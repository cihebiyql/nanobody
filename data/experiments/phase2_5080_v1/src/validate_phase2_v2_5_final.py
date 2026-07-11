#!/usr/bin/env python3
"""Phase 2 V2.5 final-audit validator.

This script encodes the V2.5 PRD/test-spec hard boundaries: experimental
ranking is separate from proxy evidence, calibration is unavailable without real
positive and real negative labels, pose fusion is gated by exact-QC coverage, and
formal target success cannot be inferred from generic-transfer success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]

EXPERIMENTAL_LEVELS = {"E4", "E5", "E6"}
PROXY_LEVELS = {"E2", "E3"}
PVRIG_TARGET_MARKERS = ("PVRIG", "Q6DKI7")
VERIFIED_NEGATIVE_KINDS = {"verified_negative", "verified_nonbinder", "binder_nonblocker", "assay_backed_nonbinder"}
POSITIVE_KINDS = {"verified_positive", "blocker_positive", "binding_positive", "assay_backed_positive"}
KNOWN_CONTROL_USES = {"known_positive_calibration", "known_positive_control", "mutation_control", "leakage_control", "control_only"}
FORBIDDEN_CLAIMS = (
    "validated blocker",
    "biologically validated",
    "calibrated blocker probability",
    "calibrated binding probability",
    "verified non-binder from proxy",
    "pvrig target success from generic transfer",
)
CLAIM_BOUNDARY = "ranking_evidence_not_experimental_blocker_validation"

REQUIRED_SCHEMA_FIELDS = {
    "sample_id", "vhh_sequence", "sequence_sha256", "target_id", "target_sequence_sha256", "target_construct",
    "label_axis", "evidence_level", "ground_truth_kind", "source_id", "source_path_or_locator",
    "allowed_use", "forbidden_use", "family_id", "leakage_group_id", "split_group_id",
    "sealed_status", "dataset_version",
}
CONDITIONAL_FIELDS = {
    "label_value", "label_unit", "label_direction", "assay_type", "assay_batch", "replicate_count",
    "mutation", "reference_sample_id", "pose_id", "pose_qc_status",
}
EXTERNAL_REQUIRED_FIELDS = {
    "source_id", "license_or_usage_status", "redistribution_allowed", "forbidden_use",
    "enters_training_or_evaluation", "accession_mapping_status", "sequence_mapping_status",
    "unit_normalization_status", "duplicate_policy", "excluded_row_count",
}
EXTERNAL_VERSION_FIELDS = ("source_version", "dataset_version")


@dataclass
class Check:
    name: str
    status: str
    evidence: Any
    severity: str = "REQUIRED"


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "null", "."} else text


def truthy(value: Any) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y", "allowed"}


def boolean_value(value: Any) -> bool | None:
    text = clean(value).lower()
    if text in {"1", "true", "yes", "y", "allowed"}:
        return True
    if text in {"0", "false", "no", "n", "disallowed"}:
        return False
    return None


def is_pvrig_target(value: Any) -> bool:
    target_id = clean(value).upper()
    return any(marker in target_id for marker in PVRIG_TARGET_MARKERS)


def pvrig_target_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "target_id" not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame[_series(frame, "target_id").map(is_pvrig_target)].copy()


def target_model_eligible_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    allowed = _series(frame, "allowed_use").astype(str).str.strip().str.upper()
    return frame[allowed.eq("EXPERIMENTAL_RANKING_ONLY")].copy()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def read_csv(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def add_check(checks: list[Check], name: str, condition: bool, evidence: Any, severity: str = "REQUIRED") -> None:
    checks.append(Check(name=name, status="PASS" if condition else ("WARN" if severity == "WARN" else "FAIL"), evidence=evidence, severity=severity))


def rel_or_abs(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(DATA_ROOT.resolve()))
    except ValueError:
        return str(path)


def _series(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    return frame[column] if column in frame.columns else pd.Series([default] * len(frame), index=frame.index)


def _contains_token(series: pd.Series, tokens: Iterable[str]) -> pd.Series:
    token_set = {token.lower() for token in tokens}
    return series.astype(str).str.lower().apply(lambda text: any(token in {part.strip() for part in text.replace(";", ",").replace("|", ",").split(",")} for token in token_set))


def validate_schema(checks: list[Check], registry: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_SCHEMA_FIELDS - set(registry.columns))
    add_check(checks, "canonical_required_schema_fields_present", not missing, missing)
    if registry.empty or missing:
        return
    non_null_missing = {col: int(_series(registry, col).map(clean).eq("").sum()) for col in REQUIRED_SCHEMA_FIELDS if col in registry.columns}
    add_check(checks, "canonical_required_schema_fields_non_null", all(count == 0 for count in non_null_missing.values()), non_null_missing)

    missing_reason = _series(registry, "missing_reason").map(clean)
    conditional_present = [col for col in CONDITIONAL_FIELDS if col in registry.columns]
    conditional_blanks = pd.Series(False, index=registry.index)
    for col in conditional_present:
        conditional_blanks = conditional_blanks | _series(registry, col).map(clean).eq("")
    add_check(
        checks,
        "conditional_nulls_have_missing_reason",
        not bool((conditional_blanks & missing_reason.eq("")).any()),
        {"rows_without_missing_reason": registry.loc[conditional_blanks & missing_reason.eq(""), "sample_id"].astype(str).head(10).tolist()},
    )


def audit_contamination(checks: list[Check], registry: pd.DataFrame) -> dict[str, int]:
    if registry.empty:
        add_check(checks, "evidence_registry_present", False, "missing or empty evidence registry")
        return {"verified_binary_positive": 0, "verified_binary_negative": 0}
    level = _series(registry, "evidence_level").astype(str).str.upper()
    kind = _series(registry, "ground_truth_kind").astype(str).str.lower()
    allowed_use = _series(registry, "allowed_use").astype(str).str.lower()
    forbidden_use = _series(registry, "forbidden_use").astype(str).str.lower()

    proxy_as_truth = registry[level.isin(PROXY_LEVELS) & kind.isin({"verified_nonbinder", "verified_negative", "blocker_positive"})]
    add_check(checks, "proxy_evidence_not_used_as_verified_truth", proxy_as_truth.empty, proxy_as_truth.get("sample_id", pd.Series(dtype=str)).astype(str).head(10).tolist())

    ordinary_bce = _series(registry, "ordinary_bce_eligible").map(truthy)
    e2_bce = registry[(level == "E2") & ordinary_bce]
    add_check(checks, "constructed_proxy_not_ordinary_bce_eligible", e2_bce.empty, e2_bce.get("sample_id", pd.Series(dtype=str)).astype(str).head(10).tolist())

    control_mask = _contains_token(allowed_use, KNOWN_CONTROL_USES) | _contains_token(forbidden_use, {"ordinary_train", "ordinary_test", "ordinary_candidate"})
    ordinary_lane = _contains_token(allowed_use, {"ordinary_train", "ordinary_test", "ordinary_candidate", "candidate_ranking"})
    bad_controls = registry[control_mask & ordinary_lane]
    add_check(checks, "known_positive_and_controls_not_in_ordinary_lanes", bad_controls.empty, bad_controls.get("sample_id", pd.Series(dtype=str)).astype(str).head(10).tolist())

    verified_negative = kind.isin(VERIFIED_NEGATIVE_KINDS)
    source_missing = _series(registry, "source_path_or_locator").map(clean).eq("") | _series(registry, "source_id").map(clean).eq("")
    add_check(checks, "verified_negative_has_assay_source_locator", not bool((verified_negative & source_missing).any()), registry.loc[verified_negative & source_missing, "sample_id"].astype(str).head(10).tolist())

    assay_rows = level.isin(EXPERIMENTAL_LEVELS) | registry["label_value"].notna() if "label_value" in registry.columns else level.isin(EXPERIMENTAL_LEVELS)
    unit_direction_missing = _series(registry, "label_unit").map(clean).eq("") | _series(registry, "label_direction").map(clean).eq("")
    add_check(checks, "assay_metric_units_and_directions_present", not bool((assay_rows & unit_direction_missing).any()), registry.loc[assay_rows & unit_direction_missing, "sample_id"].astype(str).head(10).tolist())

    mutation_primary = kind.str.contains("mutation", na=False) & _contains_token(allowed_use, {"primary", "experimental_ranking", "target_primary"})
    missing_mut_ref = _series(registry, "reference_sample_id").map(clean).eq("") | _series(registry, "label_value").map(clean).eq("")
    add_check(checks, "mutation_primary_has_reference_and_measured_effect", not bool((mutation_primary & missing_mut_ref).any()), registry.loc[mutation_primary & missing_mut_ref, "sample_id"].astype(str).head(10).tolist())

    target = _series(registry, "target_id").map(is_pvrig_target)
    target_eligible = allowed_use.str.upper().eq("EXPERIMENTAL_RANKING_ONLY")
    pos_count = int((target & level.isin(EXPERIMENTAL_LEVELS) & kind.isin(POSITIVE_KINDS) & target_eligible).sum())
    neg_count = int((target & level.isin(EXPERIMENTAL_LEVELS) & kind.isin(VERIFIED_NEGATIVE_KINDS) & target_eligible).sum())
    return {"verified_binary_positive": pos_count, "verified_binary_negative": neg_count}


def audit_formal_manifest(checks: list[Check], blinded: pd.DataFrame) -> None:
    if blinded.empty:
        add_check(checks, "formal_blinded_manifest_present", False, "missing or empty formal blinded manifest")
        return
    forbidden_columns = {"label_value", "label", "truth", "ground_truth", "kd", "ic50", "ec50", "blocker_label"}
    exposed = sorted(forbidden_columns & {col.lower() for col in blinded.columns})
    add_check(checks, "formal_blinded_manifest_does_not_expose_labels", not exposed, exposed)


def audit_external_manifest(checks: list[Check], external: pd.DataFrame) -> None:
    if external.empty:
        add_check(checks, "external_dataset_manifest_present_when_used", False, "missing or empty external dataset usage manifest")
        return
    missing = sorted(EXTERNAL_REQUIRED_FIELDS - set(external.columns))
    version_columns = [column for column in EXTERNAL_VERSION_FIELDS if column in external.columns]
    add_check(
        checks,
        "external_dataset_metadata_fields_present",
        not missing and bool(version_columns),
        {"missing": missing, "accepted_version_fields_present": version_columns},
    )
    if missing or not version_columns:
        return
    blank_counts = {col: int(_series(external, col).map(clean).eq("").sum()) for col in EXTERNAL_REQUIRED_FIELDS}
    version_missing = pd.Series(True, index=external.index)
    for column in version_columns:
        version_missing &= _series(external, column).map(clean).eq("")
    blank_counts["source_or_dataset_version"] = int(version_missing.sum())
    add_check(checks, "external_dataset_metadata_complete", all(count == 0 for count in blank_counts.values()), blank_counts)

    training = _series(external, "enters_training_or_evaluation").map(boolean_value)
    redistribution = _series(external, "redistribution_allowed").map(boolean_value)
    invalid_boolean = training.isna() | redistribution.isna()
    add_check(
        checks,
        "external_dataset_boolean_fields_valid",
        not bool(invalid_boolean.any()),
        external.loc[invalid_boolean, "source_id"].astype(str).tolist(),
    )

    usage_status = _series(external, "license_or_usage_status").map(clean).str.upper()
    enters_training = training.eq(True)
    approved = usage_status.isin({"ALLOWED", "REVIEWED_LOCAL_USE"})
    unapproved_usage = enters_training & ~approved
    add_check(
        checks,
        "external_dataset_usage_approved_when_entering_training_or_evaluation",
        not bool(unapproved_usage.any()),
        external.loc[unapproved_usage, "source_id"].astype(str).tolist(),
    )

    reviewed_training = enters_training & usage_status.eq("REVIEWED_LOCAL_USE")
    redistribution_forbidden = _contains_token(_series(external, "forbidden_use"), {"REDISTRIBUTION"})
    bad_reviewed_use = reviewed_training & (redistribution.ne(False) | ~redistribution_forbidden)
    add_check(
        checks,
        "reviewed_local_use_training_requires_redistribution_prohibition",
        not bool(bad_reviewed_use.any()),
        external.loc[bad_reviewed_use, "source_id"].astype(str).tolist(),
    )


def audit_calibration(checks: list[Check], metrics: dict[str, Any], binary_counts: dict[str, int]) -> dict[str, Any]:
    calibration = metrics.get("calibration", {}) if isinstance(metrics.get("calibration", {}), dict) else {}
    applicable = binary_counts["verified_binary_positive"] > 0 and binary_counts["verified_binary_negative"] > 0
    probability_fields = ["brier", "brier_score", "ece", "expected_calibration_error", "calibrated_probability"]
    present_probability = {field: metrics.get(field, calibration.get(field)) for field in probability_fields if metrics.get(field, calibration.get(field)) not in (None, "", "NOT_APPLICABLE")}
    if applicable:
        add_check(checks, "calibration_applicable_only_with_verified_binary_labels", calibration.get("status") == "APPLICABLE", {"counts": binary_counts, "calibration": calibration})
        status = "APPLICABLE" if calibration.get("status") == "APPLICABLE" else "INVALID"
    else:
        add_check(checks, "calibration_not_applicable_without_verified_pos_and_neg", calibration.get("status") == "NOT_APPLICABLE" and not present_probability, {"counts": binary_counts, "calibration": calibration, "probability_fields": present_probability})
        status = "NOT_APPLICABLE"
    return {"status": status, "fit_split": calibration.get("fit_split", "dev_only"), "reason": calibration.get("reason")}


def audit_pose_gate(checks: list[Check], metrics: dict[str, Any], pose_frame: pd.DataFrame) -> dict[str, Any]:
    pose = metrics.get("pose", {}) if isinstance(metrics.get("pose", {}), dict) else {}
    if pose_frame.empty:
        coverage = pose.get("exact_qc_passed_coverage")
    elif {"pose_qc_status", "pose_id"} <= set(pose_frame.columns):
        exact = pose_frame["pose_qc_status"].astype(str).str.lower().isin({"exact_qc_pass", "exact_qc_passed", "pass", "passed"})
        coverage = float(exact.mean()) if len(pose_frame) else None
    else:
        coverage = pose.get("exact_qc_passed_coverage")
    try:
        coverage_float = float(coverage) if coverage is not None else None
    except (TypeError, ValueError):
        coverage_float = None
    global_fusion = bool(pose.get("global_fusion_applied", False))
    missingness_pass = pose.get("missingness_audit_pass")
    gate_ok = (not global_fusion) or (coverage_float is not None and coverage_float >= 0.80 and missingness_pass is True)
    add_check(checks, "pose_global_fusion_requires_80pct_exact_qc_coverage", gate_ok, {"coverage": coverage_float, "global_fusion_applied": global_fusion, "missingness_audit_pass": missingness_pass})
    return {"exact_qc_passed_coverage": coverage_float, "global_fusion_min_coverage": 0.8, "global_fusion_applied": global_fusion, "missingness_audit_pass": missingness_pass}


def audit_sha(checks: list[Check], metrics: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    expected = metrics.get("input_sha256", {}) if isinstance(metrics.get("input_sha256", {}), dict) else {}
    path_map = {
        "evidence_registry": args.evidence_registry,
        "formal_manifest_blinded": args.formal_manifest_blinded,
        "formal_labels_sealed": args.formal_labels_sealed,
        "preregistration_json": args.preregistration_json,
    }
    observed: dict[str, str | None] = {}
    mismatches: dict[str, dict[str, str | None]] = {}
    for key, path in path_map.items():
        if path and path.exists() and path.is_file():
            observed[key] = file_sha256(path)
            if expected.get(key) and expected.get(key) != observed[key]:
                mismatches[key] = {"expected": expected.get(key), "observed": observed[key], "path": rel_or_abs(path)}
        else:
            observed[key] = None
            mismatches[key] = {"expected": expected.get(key), "observed": None, "path": rel_or_abs(path) if path else None}
    add_check(checks, "registered_input_sha256_values_match", not mismatches, mismatches)
    return observed


def claim_text_is_safe(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower()
    text = text.replace("not calibrated binding probability", "").replace("not a calibrated binding probability", "")
    text = text.replace("not biologically validated", "").replace("not a validated blocker", "")
    return not any(term in text for term in FORBIDDEN_CLAIMS)


def data_readiness_from_registry(
    registry: pd.DataFrame,
    metrics: dict[str, Any],
    binary_counts: dict[str, int],
    formal_manifest_blinded: pd.DataFrame | None = None,
) -> dict[str, Any]:
    explicit = metrics.get("data_readiness", {}) if isinstance(metrics.get("data_readiness", {}), dict) else {}
    target_registry = pvrig_target_rows(registry)
    if target_registry.empty:
        status = "DATA_NOT_READY"
        rank_groups = 0
        blocks = 0
        exp = target_registry.copy()
        eligible_exp = exp.copy()
        control_only_count = 0
    else:
        level = _series(target_registry, "evidence_level").astype(str).str.upper()
        exp = target_registry[level.isin(EXPERIMENTAL_LEVELS)].copy()
        eligible_exp = target_model_eligible_rows(exp)
        exp_allowed = _series(exp, "allowed_use").astype(str).str.lower()
        control_only_count = int(exp_allowed.str.contains("calibration|leakage|control_only", regex=True).sum())
        group_columns = [
            column for column in ("target_id", "assay_type", "assay_batch", "source_id", "label_axis", "split_group_id")
            if column in eligible_exp.columns
        ]
        if not eligible_exp.empty and group_columns:
            group_sizes = eligible_exp.groupby(group_columns, dropna=False).size()
            rank_groups = int(group_sizes.ge(3).sum())
        else:
            rank_groups = 0
        block_columns = [column for column in ("family_id", "assay_type", "assay_batch", "source_id") if column in eligible_exp.columns]
        blocks = int(eligible_exp[block_columns].drop_duplicates().shape[0]) if not eligible_exp.empty and block_columns else 0
        pilot_shape = (len(eligible_exp) >= 20 and binary_counts["verified_binary_positive"] > 0 and binary_counts["verified_binary_negative"] > 0 and blocks >= 5) or rank_groups >= 8
        status = "TARGET_PILOT_READY" if pilot_shape else "DATA_NOT_READY"

    default_power = {
        "primary_metric": "macro_group_pairwise_preference_accuracy",
        "mde_absolute": 0.10,
        "alpha_two_sided": 0.05,
        "estimated_power": None,
        "minimum_power": 0.80,
        "expected_ci_half_width": None,
        "maximum_ci_half_width": 0.10,
        "formal_split_group_count": 0,
        "formal_assay_or_source_block_count": 0,
        "formal_labels_read": False,
        "simulation_seed": None,
    }
    explicit_power = explicit.get("power_simulation", {}) if isinstance(explicit.get("power_simulation", {}), dict) else {}
    power = {**default_power, **explicit_power}
    if formal_manifest_blinded is not None:
        target_formal = pvrig_target_rows(formal_manifest_blinded)
        if not target_formal.empty and "evidence_level" in target_formal.columns:
            formal_level = _series(target_formal, "evidence_level").astype(str).str.upper()
            target_formal = target_formal[formal_level.isin(EXPERIMENTAL_LEVELS)].copy()
        formal_split_groups = _series(target_formal, "split_group_id").map(clean) if not target_formal.empty else pd.Series(dtype=str)
        power["formal_split_group_count"] = int(formal_split_groups[formal_split_groups.ne("")].nunique())
        formal_block_columns = [column for column in ("assay_batch", "source_id") if column in target_formal.columns]
        if target_formal.empty or not formal_block_columns:
            power["formal_assay_or_source_block_count"] = 0
        else:
            formal_blocks = target_formal[formal_block_columns].copy()
            for column in formal_block_columns:
                formal_blocks[column] = formal_blocks[column].map(clean)
            formal_blocks = formal_blocks[formal_blocks.ne("").any(axis=1)]
            power["formal_assay_or_source_block_count"] = int(formal_blocks.drop_duplicates().shape[0])

    pilot_shape = status == "TARGET_PILOT_READY"
    formal_ready = (
        pilot_shape
        and float(power.get("estimated_power", -1) or -1) >= 0.80
        and float(power.get("expected_ci_half_width", 999) or 999) <= 0.10
        and int(power.get("formal_split_group_count", 0) or 0) >= 5
        and int(power.get("formal_assay_or_source_block_count", 0) or 0) >= 2
        and power.get("formal_labels_read") is False
    )
    if formal_ready:
        status = "TARGET_FORMAL_READY"
    elif pilot_shape and explicit.get("status") == "NOT_POWERED_FOR_TARGET_FORMAL":
        status = "NOT_POWERED_FOR_TARGET_FORMAL"
    return {
        "status": status,
        "evidence_level_counts": _series(target_registry, "evidence_level").astype(str).value_counts().to_dict() if not target_registry.empty else {},
        "assay_backed_rank_groups": rank_groups,
        "target_model_eligible_assay_rows": int(len(eligible_exp)),
        "target_non_model_eligible_assay_rows": int(len(exp) - len(eligible_exp)),
        "target_control_only_assay_rows": control_only_count,
        "verified_binary_positive": binary_counts["verified_binary_positive"],
        "verified_binary_negative": binary_counts["verified_binary_negative"],
        "independent_family_assay_blocks": blocks,
        "power_simulation": power,
    }


def decide_formal_status(metrics: dict[str, Any], readiness: dict[str, Any], failed_checks: list[str]) -> dict[str, Any]:
    decision = metrics.get("formal_decision", {}) if isinstance(metrics.get("formal_decision", {}), dict) else {}
    target_ready = readiness.get("status") == "TARGET_FORMAL_READY"
    generic_pass = bool(decision.get("generic_transfer_formal_pass", metrics.get("generic_transfer_formal_pass", False)))
    primary_ci = decision.get("primary_delta_vs_strong_baseline_ci_low_gt_zero") is True
    permutation = decision.get("permutation_pass") is True
    seeds = decision.get("seed_consistency_pass") is True
    contact = decision.get("contact_guardrail_pass") is not False
    paratope = decision.get("paratope_guardrail_pass") is not False
    invalid = bool(failed_checks)
    if invalid:
        status = "INVALID_RUN"
    elif target_ready and primary_ci and permutation and seeds and contact and paratope:
        status = "PASS_TARGET_RANKING"
    elif generic_pass and not target_ready:
        status = "PASS_GENERIC_TRANSFER_ONLY"
    elif readiness.get("status") in {"DATA_NOT_READY", "TARGET_PILOT_READY"}:
        status = "DATA_NOT_READY_FOR_TARGET_MODEL"
    elif readiness.get("status") == "NOT_POWERED_FOR_TARGET_FORMAL":
        status = "PASS_LIMITED_RANKING_ONLY"
    elif target_ready:
        status = "FAIL_PREREGISTERED_TARGET_TEST"
    else:
        status = "PASS_LIMITED_RANKING_ONLY"
    return {
        "status": status,
        "primary_delta_vs_strong_baseline_ci_low_gt_zero": decision.get("primary_delta_vs_strong_baseline_ci_low_gt_zero"),
        "permutation_pass": decision.get("permutation_pass"),
        "seed_consistency_pass": decision.get("seed_consistency_pass"),
        "contact_guardrail_pass": decision.get("contact_guardrail_pass"),
        "paratope_guardrail_pass": decision.get("paratope_guardrail_pass"),
        "claim_boundary": decision.get("claim_boundary") or CLAIM_BOUNDARY,
    }


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[Check] = []
    required_artifacts = {
        "evidence_registry_artifact_present": args.evidence_registry,
        "formal_blinded_artifact_present": args.formal_manifest_blinded,
        "formal_labels_artifact_present": args.formal_labels_sealed,
        "external_dataset_usage_artifact_present": args.external_dataset_manifest,
        "pose_summary_artifact_present": args.pose_summary_csv,
        "metrics_artifact_present": args.metrics_json,
        "preregistration_artifact_present": args.preregistration_json,
    }
    for name, path in required_artifacts.items():
        present = bool(path and path.is_file() and path.stat().st_size > 0)
        add_check(checks, name, present, {"path": rel_or_abs(path) if path else None, "present": present})
    registry = read_csv(args.evidence_registry)
    blinded = read_csv(args.formal_manifest_blinded)
    external = read_csv(args.external_dataset_manifest)
    pose_frame = read_csv(args.pose_summary_csv)
    metrics = load_json(args.metrics_json) if args.metrics_json and args.metrics_json.exists() else {}

    validate_schema(checks, registry)
    binary_counts = audit_contamination(checks, registry)
    audit_formal_manifest(checks, blinded)
    audit_external_manifest(checks, external)
    calibration = audit_calibration(checks, metrics, binary_counts)
    pose = audit_pose_gate(checks, metrics, pose_frame)
    input_sha = audit_sha(checks, metrics, args)
    add_check(checks, "claim_boundary_excludes_forbidden_biological_claims", claim_text_is_safe(metrics), "forbidden claim scan passed")

    readiness = data_readiness_from_registry(registry, metrics, binary_counts, blinded)
    failed = [check.name for check in checks if check.status == "FAIL"]
    formal_decision = decide_formal_status(metrics, readiness, failed)
    if formal_decision["status"] == "PASS_TARGET_RANKING" and metrics.get("generic_transfer_formal_pass") is True and readiness.get("status") != "TARGET_FORMAL_READY":
        add_check(checks, "generic_transfer_success_cannot_be_pvrig_target_success", False, {"readiness": readiness.get("status")})
    else:
        add_check(checks, "generic_transfer_success_cannot_be_pvrig_target_success", formal_decision["status"] != "PASS_TARGET_RANKING" or readiness.get("status") == "TARGET_FORMAL_READY", {"decision": formal_decision["status"], "readiness": readiness.get("status")})

    failed = [check.name for check in checks if check.status == "FAIL"]
    warnings = [check.name for check in checks if check.status == "WARN"]
    if failed:
        status = "FAIL"
        formal_decision["status"] = "INVALID_RUN"
    elif warnings:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"
    return {
        "status": status,
        "schema_version": "phase2_v2_5_final_audit_v1",
        "input_sha256": input_sha,
        "data_readiness": readiness,
        "lane_policy": {
            "known_positive_ordinary_train_allowed": False,
            "constructed_proxy_as_verified_nonbinder_allowed": False,
            "pose_proxy_as_experimental_label_allowed": False,
        },
        "calibration": calibration,
        "pose": pose,
        "formal_decision": formal_decision,
        "failed_checks": failed,
        "warnings": warnings,
        "check_count": len(checks),
        "checks": [check.__dict__ for check in checks],
    }


def write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 2 V2.5 Final Audit V1",
        "",
        f"- Status: **{result['status']}**",
        f"- Formal decision: **{result['formal_decision']['status']}**",
        f"- Data readiness: **{result['data_readiness']['status']}**",
        f"- Checks: {result['check_count'] - len(result['failed_checks'])}/{result['check_count']} pass-or-warn",
        f"- Claim boundary: `{result['formal_decision']['claim_boundary']}`",
        "",
        "## Checks",
        "",
    ]
    for item in result["checks"]:
        lines.append(f"- [{item['status']}] `{item['name']}` ({item['severity']}) - {item['evidence']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-dir", type=Path, default=EXP_DIR)
    parser.add_argument("--evidence-registry", type=Path)
    parser.add_argument("--formal-manifest-blinded", type=Path)
    parser.add_argument("--formal-labels-sealed", type=Path)
    parser.add_argument("--external-dataset-manifest", type=Path)
    parser.add_argument("--pose-summary-csv", type=Path)
    parser.add_argument("--metrics-json", type=Path)
    parser.add_argument("--preregistration-json", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    defaults = {
        "evidence_registry": "data_splits/evidence_registry_v2_5.csv",
        "formal_manifest_blinded": "prepared/phase2_v2_5_generic/nanobind_affinity_formal_blinded_v2_5.csv",
        "formal_labels_sealed": "prepared/phase2_v2_5_generic/nanobind_affinity_formal_labels_sealed_v2_5.csv",
        "external_dataset_manifest": "data_splits/external_dataset_usage_manifest_v2_5.csv",
        "pose_summary_csv": "prepared/pvrig_pose_proxy_summary_v2_5.csv",
        "metrics_json": "reports/phase2_v2_5_metrics_v1.json",
        "preregistration_json": "audits/phase2_v2_5_preregistration_v1.json",
        "json_out": "audits/phase2_v2_5_final_audit_v1.json",
        "markdown_out": "audits/PHASE2_V2_5_FINAL_AUDIT_V1.md",
    }
    for name, relative_path in defaults.items():
        if getattr(args, name) is None:
            setattr(args, name, args.exp_dir / relative_path)
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = build_audit(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.no_write:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_markdown(result, args.markdown_out)
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
