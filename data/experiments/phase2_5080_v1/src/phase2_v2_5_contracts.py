#!/usr/bin/env python3
"""Phase 2 V2.5 evidence-registry contracts and validators."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

SCHEMA_VERSION = "phase2_v2_5_evidence_registry_v1"
EXTERNAL_MANIFEST_VERSION = "phase2_v2_5_external_dataset_manifest_v1"
PVRIG_TARGET_ID = "PVRIG_HUMAN_Q6DKI7"

CANONICAL_FIELDS = [
    "schema_version",
    "sample_id",
    "vhh_sequence",
    "sequence_sha256",
    "target_id",
    "target_sequence_sha256",
    "target_construct",
    "label_axis",
    "evidence_level",
    "ground_truth_kind",
    "label_value",
    "label_unit",
    "label_direction",
    "assay_type",
    "assay_batch",
    "replicate_count",
    "source_id",
    "source_path_or_locator",
    "allowed_use",
    "forbidden_use",
    "family_id",
    "leakage_group_id",
    "split_group_id",
    "sealed_status",
    "dataset_version",
    "mutation",
    "reference_sample_id",
    "pose_id",
    "pose_qc_status",
    "missing_reason",
    "ordinary_train_allowed",
    "ordinary_test_allowed",
    "candidate_ranking_allowed",
    "ordinary_bce_eligible",
    "lane",
    "notes",
]

REQUIRED_NON_NULL_FIELDS = [
    "sample_id",
    "vhh_sequence",
    "sequence_sha256",
    "target_id",
    "target_sequence_sha256",
    "target_construct",
    "label_axis",
    "evidence_level",
    "ground_truth_kind",
    "source_id",
    "source_path_or_locator",
    "allowed_use",
    "forbidden_use",
    "family_id",
    "leakage_group_id",
    "split_group_id",
    "sealed_status",
    "dataset_version",
]

EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3", "E4", "E5", "E6"}
LABEL_AXES = {"contact", "binding", "blocking", "mutation_effect", "proxy", "control"}
SEALED_STATUSES = {"OPEN_DEVELOPMENT", "SEALED_BLINDED", "SEALED_LABELS", "NOT_FORMAL"}
ALLOWED_USE_VALUES = {
    "CALIBRATION_LEAKAGE_CONTROL_ONLY",
    "MUTATION_CONTROL_ONLY",
    "PROXY_STRESS_ONLY",
    "POSE_PROXY_TRIAGE_ONLY",
    "CONTACT_SITE_GUARDRAIL_ONLY",
    "EXPERIMENTAL_RANKING_ONLY",
    "REVIEWED_LOCAL_USE",
}
EXTERNAL_USAGE_ALLOWED = {"ALLOWED", "REVIEWED_LOCAL_USE"}

EXTERNAL_MANIFEST_FIELDS = [
    "manifest_version",
    "source_id",
    "source_family",
    "source_version",
    "source_path_or_locator",
    "license_or_usage_status",
    "redistribution_allowed",
    "allowed_use",
    "forbidden_use",
    "accession_mapping_status",
    "sequence_mapping_status",
    "unit_normalization_status",
    "duplicate_policy",
    "excluded_row_count",
    "enters_training_or_evaluation",
    "notes",
]


class ContractError(ValueError):
    """Raised when a V2.5 contract hard gate fails."""


@dataclass(frozen=True)
class ValidationResult:
    status: str
    row_count: int
    evidence_level_counts: dict[str, int]
    data_readiness_status: str
    errors: list[str]


def normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def empty_to_na(value: object) -> object:
    if value is None:
        return pd.NA
    if isinstance(value, str) and value.strip() == "":
        return pd.NA
    return value


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def sequence_sha256(sequence: str) -> str:
    clean = "".join(str(sequence).split()).upper()
    return sha256_text(clean)


def ensure_canonical_columns(df: pd.DataFrame) -> pd.DataFrame:
    extra = sorted(set(df.columns) - set(CANONICAL_FIELDS))
    missing = [field for field in CANONICAL_FIELDS if field not in df.columns]
    if extra:
        raise ContractError(f"Non-canonical evidence registry fields: {extra}")
    if missing:
        raise ContractError(f"Missing canonical evidence registry fields: {missing}")
    return df[CANONICAL_FIELDS].copy()


def _is_missing(series: pd.Series) -> pd.Series:
    return series.map(empty_to_na).isna()


def _collect_missing_required(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_NON_NULL_FIELDS:
        bad = _is_missing(df[field])
        if bad.any():
            sample_ids = df.loc[bad, "sample_id"].head(5).astype(str).tolist()
            errors.append(f"{field} is required but missing for {sample_ids}")
    return errors


def _rows_without_missing_reason(df: pd.DataFrame, mask: pd.Series, reason: str) -> list[str]:
    if not mask.any():
        return []
    missing_reason = _is_missing(df.loc[mask, "missing_reason"])
    if not missing_reason.any():
        return []
    sample_ids = df.loc[mask].loc[missing_reason, "sample_id"].head(5).astype(str).tolist()
    return [f"{reason}; missing_reason absent for {sample_ids}"]


def validate_evidence_registry(df: pd.DataFrame, *, raise_on_error: bool = True) -> ValidationResult:
    df = ensure_canonical_columns(df)
    errors: list[str] = []
    errors.extend(_collect_missing_required(df))

    invalid_levels = sorted(set(df["evidence_level"].dropna().astype(str)) - EVIDENCE_LEVELS)
    if invalid_levels:
        errors.append(f"Invalid evidence_level values: {invalid_levels}")
    invalid_axes = sorted(set(df["label_axis"].dropna().astype(str)) - LABEL_AXES)
    if invalid_axes:
        errors.append(f"Invalid label_axis values: {invalid_axes}")
    invalid_seal = sorted(set(df["sealed_status"].dropna().astype(str)) - SEALED_STATUSES)
    if invalid_seal:
        errors.append(f"Invalid sealed_status values: {invalid_seal}")
    invalid_allowed = sorted(set(df["allowed_use"].dropna().astype(str)) - ALLOWED_USE_VALUES)
    if invalid_allowed:
        errors.append(f"Invalid allowed_use values: {invalid_allowed}")

    seq_mismatch = df["vhh_sequence"].astype(str).str.replace(r"\s+", "", regex=True).str.upper().map(sequence_sha256) != df["sequence_sha256"].astype(str)
    if seq_mismatch.any():
        errors.append(f"sequence_sha256 mismatch for {df.loc[seq_mismatch, 'sample_id'].head(5).astype(str).tolist()}")

    e4_e6 = df["evidence_level"].isin(["E4", "E5", "E6"])
    for field in ["label_value", "label_unit", "label_direction", "assay_type", "assay_batch"]:
        mask = e4_e6 & _is_missing(df[field])
        errors.extend(_rows_without_missing_reason(df, mask, f"{field} required for E4-E6 rows"))
    replicate_missing = e4_e6 & _is_missing(df["replicate_count"])
    errors.extend(_rows_without_missing_reason(df, replicate_missing, "replicate_count conditionally required for E4-E6 rows"))

    conditional_fields = [
        "label_value",
        "label_unit",
        "label_direction",
        "assay_type",
        "assay_batch",
        "replicate_count",
        "mutation",
        "reference_sample_id",
        "pose_id",
        "pose_qc_status",
    ]
    conditional_missing = pd.Series(False, index=df.index)
    for field in conditional_fields:
        conditional_missing = conditional_missing | _is_missing(df[field])
    missing_reason_absent = conditional_missing & _is_missing(df["missing_reason"])
    if missing_reason_absent.any():
        errors.append(
            "Any missing conditional field requires missing_reason; affected "
            f"{df.loc[missing_reason_absent, 'sample_id'].head(5).astype(str).tolist()}"
        )

    mutation_rows = df["label_axis"].eq("mutation_effect") | df["ground_truth_kind"].astype(str).str.contains("mutation", case=False, na=False)
    mutation_primary = mutation_rows & df["allowed_use"].eq("EXPERIMENTAL_RANKING_ONLY")
    mutation_missing = mutation_primary & (_is_missing(df["mutation"]) | _is_missing(df["reference_sample_id"]) | _is_missing(df["label_value"]))
    if mutation_missing.any():
        errors.append(f"mutation-effect primary row lacks mutation/reference/effect size: {df.loc[mutation_missing, 'sample_id'].head(5).astype(str).tolist()}")

    pose_rows = df["evidence_level"].eq("E3") | df["ground_truth_kind"].eq("pose_proxy")
    pose_missing = pose_rows & (_is_missing(df["pose_id"]) | _is_missing(df["pose_qc_status"]))
    if pose_missing.any():
        errors.append(f"E3 pose row lacks pose_id/pose_qc_status: {df.loc[pose_missing, 'sample_id'].head(5).astype(str).tolist()}")

    constructed_or_pose = df["ground_truth_kind"].isin(["constructed_proxy", "pose_proxy"])
    contaminated_truth = constructed_or_pose & df["ground_truth_kind"].isin(["verified_nonbinder", "blocker_positive"])
    if contaminated_truth.any():
        errors.append("constructed_proxy or pose_proxy appears in verified truth")
    e2_bce = df["evidence_level"].eq("E2") & df["ordinary_bce_eligible"].map(normalize_bool)
    if e2_bce.any():
        errors.append(f"E2 rows cannot be ordinary_bce_eligible: {df.loc[e2_bce, 'sample_id'].head(5).astype(str).tolist()}")
    proxy_truth_terms = df["ground_truth_kind"].astype(str).str.contains("verified_nonbinder|blocker_positive", case=False, na=False)
    proxy_truth_contam = df["evidence_level"].isin(["E2", "E3"]) & proxy_truth_terms
    if proxy_truth_contam.any():
        errors.append(f"E2/E3 proxy rows cannot carry verified truth: {df.loc[proxy_truth_contam, 'sample_id'].head(5).astype(str).tolist()}")

    ordinary_eligibility = (
        df["ordinary_train_allowed"].map(normalize_bool)
        | df["ordinary_test_allowed"].map(normalize_bool)
        | df["candidate_ranking_allowed"].map(normalize_bool)
    )
    bad_e2_lane = df["evidence_level"].eq("E2") & (
        df["allowed_use"].ne("PROXY_STRESS_ONLY") | ordinary_eligibility
    )
    if bad_e2_lane.any():
        errors.append(f"E2 constructed rows must remain proxy-only: {df.loc[bad_e2_lane, 'sample_id'].head(5).astype(str).tolist()}")
    bad_e3_lane = df["evidence_level"].eq("E3") & (
        df["allowed_use"].ne("POSE_PROXY_TRIAGE_ONLY") | ordinary_eligibility
    )
    if bad_e3_lane.any():
        errors.append(f"E3 pose rows must remain triage-only: {df.loc[bad_e3_lane, 'sample_id'].head(5).astype(str).tolist()}")

    e1_rows = df["evidence_level"].eq("E1")
    bad_e1_lane = e1_rows & (
        df["label_axis"].ne("contact")
        | df["allowed_use"].ne("CONTACT_SITE_GUARDRAIL_ONLY")
        | df["ordinary_bce_eligible"].map(normalize_bool)
        | df["candidate_ranking_allowed"].map(normalize_bool)
    )
    if bad_e1_lane.any():
        errors.append(f"E1 rows must remain contact/site guardrails: {df.loc[bad_e1_lane, 'sample_id'].head(5).astype(str).tolist()}")

    generic_e4 = df["evidence_level"].eq("E4") & df["target_id"].ne(PVRIG_TARGET_ID)
    generic_blocker_claim = generic_e4 & (
        df["label_axis"].eq("blocking")
        | df["ground_truth_kind"].astype(str).str.contains("blocker|blocking", case=False, na=False)
        | ~df["forbidden_use"].astype(str).str.contains("BLOCKER", case=False, na=False)
        | df["ordinary_bce_eligible"].map(normalize_bool)
    )
    if generic_blocker_claim.any():
        errors.append(f"Generic E4 binding rows cannot carry blocker or BCE claims: {df.loc[generic_blocker_claim, 'sample_id'].head(5).astype(str).tolist()}")

    known_or_control = df["ground_truth_kind"].astype(str).str.contains("known_positive|calibration|control|leakage", case=False, na=False)
    ordinary_lane = known_or_control & (
        df["ordinary_train_allowed"].map(normalize_bool)
        | df["ordinary_test_allowed"].map(normalize_bool)
        | df["candidate_ranking_allowed"].map(normalize_bool)
        | df["lane"].astype(str).str.contains("ordinary", case=False, na=False)
    )
    if ordinary_lane.any():
        errors.append(f"Known positive/control rows entered ordinary lane: {df.loc[ordinary_lane, 'sample_id'].head(5).astype(str).tolist()}")

    verified_negative = df["ground_truth_kind"].eq("verified_nonbinder")
    if (verified_negative & _is_missing(df["source_path_or_locator"])).any():
        errors.append("verified negative lacks assay/source locator")

    e4_e6_units = e4_e6 & (_is_missing(df["label_unit"]) | _is_missing(df["label_direction"]))
    if e4_e6_units.any():
        errors.append(f"Assay-backed row has ambiguous unit/direction: {df.loc[e4_e6_units, 'sample_id'].head(5).astype(str).tolist()}")

    counts = {str(k): int(v) for k, v in df["evidence_level"].value_counts(dropna=False).sort_index().items()}
    readiness = compute_target_readiness(df)
    if errors and raise_on_error:
        raise ContractError("; ".join(errors))
    return ValidationResult("FAIL" if errors else "PASS", int(len(df)), counts, readiness, errors)


def compute_target_readiness(df: pd.DataFrame, *, target_id: str = PVRIG_TARGET_ID) -> str:
    assay = df[
        df["target_id"].eq(target_id)
        & df["evidence_level"].isin(["E4", "E5", "E6"])
    ].copy()
    ordinary_assay = assay[assay["allowed_use"].eq("EXPERIMENTAL_RANKING_ONLY")]
    independent_blocks = ordinary_assay[["family_id", "assay_type", "source_id"]].drop_duplicates().shape[0]
    assay_labeled_pairs = ordinary_assay[~_is_missing(ordinary_assay["label_value"])].shape[0]
    group_sizes = ordinary_assay.groupby("split_group_id")["sample_id"].nunique() if not ordinary_assay.empty else pd.Series(dtype=int)
    ranking_groups = int((group_sizes >= 3).sum())
    has_positive = ordinary_assay["ground_truth_kind"].astype(str).str.contains("positive|binder|blocking", case=False, na=False).any()
    has_negative = ordinary_assay["ground_truth_kind"].astype(str).str.contains("negative|nonbinder|nonblocker|weaker", case=False, na=False).any()
    if assay_labeled_pairs >= 20 and has_positive and has_negative and independent_blocks >= 5:
        return "TARGET_PILOT_READY"
    if ranking_groups >= 8 and independent_blocks >= 5:
        return "TARGET_PILOT_READY"
    return "DATA_NOT_READY"


def validate_external_manifest(df: pd.DataFrame, *, raise_on_error: bool = True) -> list[str]:
    extra = sorted(set(df.columns) - set(EXTERNAL_MANIFEST_FIELDS))
    missing = [field for field in EXTERNAL_MANIFEST_FIELDS if field not in df.columns]
    errors: list[str] = []
    if extra:
        errors.append(f"Non-canonical external manifest fields: {extra}")
    if missing:
        errors.append(f"Missing external manifest fields: {missing}")
    if errors:
        if raise_on_error:
            raise ContractError("; ".join(errors))
        return errors
    for field in [
        "source_id",
        "source_version",
        "source_path_or_locator",
        "license_or_usage_status",
        "accession_mapping_status",
        "sequence_mapping_status",
        "unit_normalization_status",
        "duplicate_policy",
        "excluded_row_count",
    ]:
        bad = _is_missing(df[field])
        if bad.any():
            errors.append(f"External dataset missing {field}: {df.loc[bad, 'source_id'].head(5).astype(str).tolist()}")
    training = df["enters_training_or_evaluation"].map(normalize_bool)
    bad_usage = training & ~df["license_or_usage_status"].isin(EXTERNAL_USAGE_ALLOWED)
    if bad_usage.any():
        errors.append(f"External dataset enters training/eval without allowed usage: {df.loc[bad_usage, 'source_id'].head(5).astype(str).tolist()}")
    redistribution = df["redistribution_allowed"].map(normalize_bool)
    reviewed_local = df["license_or_usage_status"].eq("REVIEWED_LOCAL_USE")
    bad_reviewed_redistribution = reviewed_local & redistribution
    if bad_reviewed_redistribution.any():
        errors.append(
            "REVIEWED_LOCAL_USE datasets cannot allow redistribution: "
            f"{df.loc[bad_reviewed_redistribution, 'source_id'].head(5).astype(str).tolist()}"
        )
    excluded_counts = pd.to_numeric(df["excluded_row_count"], errors="coerce")
    bad_excluded_count = excluded_counts.isna() | (excluded_counts < 0) | (excluded_counts % 1 != 0)
    if bad_excluded_count.any():
        errors.append(f"External excluded_row_count must be a non-negative integer: {df.loc[bad_excluded_count, 'source_id'].head(5).astype(str).tolist()}")
    nanobind = df["source_family"].astype(str).str.lower().eq("nanobind")
    bad_nanobind = nanobind & (df["license_or_usage_status"].ne("REVIEWED_LOCAL_USE") | redistribution | ~df["forbidden_use"].astype(str).str.contains("REDISTRIBUTION", na=False))
    if bad_nanobind.any():
        errors.append("NanoBind local checkout must be REVIEWED_LOCAL_USE and prohibit redistribution")
    if errors and raise_on_error:
        raise ContractError("; ".join(errors))
    return errors


def require_no_alias_columns(columns: Iterable[str]) -> None:
    aliases = {"unit", "direction"} & set(columns)
    if aliases:
        raise ContractError(f"Use canonical label_unit/label_direction, not aliases: {sorted(aliases)}")
