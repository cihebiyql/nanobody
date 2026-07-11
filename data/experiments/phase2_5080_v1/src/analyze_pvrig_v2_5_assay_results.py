#!/usr/bin/env python3
"""Validate and summarize prospective PVRIG assay results without inventing labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_PACKAGE_DIR = EXP_DIR / "assays/pvrig_v2_5_prospective_v1"

PACKAGE_VERSION = "pvrig_v2_5_prospective_assay_execution_v1"
PENDING_VALUES = {"", "PENDING", "NOT_RUN"}
QC_CALLS = {"PASS", "FAIL", "INCONCLUSIVE", "PENDING"}
IDENTITY_CALLS = {"PASS", "FAIL", "INCONCLUSIVE", "PENDING"}
BINDING_CALLS = {"BINDER", "NONBINDER", "INCONCLUSIVE", "NOT_RUN", "PENDING"}
BLOCKING_CALLS = {"BLOCKER", "NONBLOCKER", "INCONCLUSIVE", "NOT_RUN", "PENDING"}
FUNCTIONAL_CALLS = {"POSITIVE", "NEGATIVE", "INCONCLUSIVE", "NOT_RUN", "PENDING"}
FIT_CALLS = {"PASS", "FAIL", "INCONCLUSIVE", "PENDING"}
CONCENTRATION_CALLS = {"PRESENT", "ABSENT", "INCONCLUSIVE", "PENDING"}

QC_REQUIRED_COLUMNS = {
    "package_version",
    "assay_sample_id",
    "sequence_sha256_expected",
    "sequence_sha256_observed",
    "expression_yield_mg_per_l",
    "purity_fraction",
    "sec_monomer_fraction",
    "aggregation_fraction",
    "identity_call",
    "scientist_qc_call",
    "raw_data_path",
    "raw_data_sha256",
    "exclusion_reason",
}

RUN_IDENTITY_COLUMNS = {
    "package_version",
    "run_id",
    "day_block",
    "randomized_order",
    "sample_plate_well",
    "assay_sample_id",
    "target_id",
    "target_construct",
    "target_sequence_sha256",
}


class AssayContractError(ValueError):
    """Raised when result files violate a hard assay evidence contract."""


def clean(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def upper(value: object) -> str:
    return clean(value).upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise AssayContractError(f"Missing required assay file: {path}")
    return pd.read_csv(path, keep_default_na=False, dtype=str)


def require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise AssayContractError(f"{label} is missing required columns: {missing}")


def require_allowed(frame: pd.DataFrame, column: str, allowed: set[str], label: str) -> None:
    observed = {upper(value) for value in frame[column]}
    invalid = sorted(observed - allowed)
    if invalid:
        raise AssayContractError(f"{label}.{column} contains invalid values: {invalid}")


def numeric(value: object, *, field: str, allow_blank: bool = True) -> float | None:
    text = clean(value)
    if not text and allow_blank:
        return None
    try:
        result = float(text)
    except ValueError as exc:
        raise AssayContractError(f"{field} must be numeric, observed {text!r}") from exc
    if not math.isfinite(result):
        raise AssayContractError(f"{field} must be finite, observed {text!r}")
    return result


def validate_package_manifest(package_dir: Path) -> dict[str, object]:
    manifest_path = package_dir / "package_manifest.json"
    if not manifest_path.is_file():
        raise AssayContractError(f"Missing package manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package_version") != PACKAGE_VERSION:
        raise AssayContractError("Assay package version mismatch")
    frozen = manifest.get("frozen_artifacts")
    if not isinstance(frozen, dict) or not frozen:
        raise AssayContractError("Package manifest does not identify frozen artifacts")
    for filename, expected in frozen.items():
        path = package_dir / str(filename)
        if not path.is_file() or sha256_file(path) != str(expected):
            raise AssayContractError(f"Frozen package artifact changed: {filename}")
    return manifest


def validate_identity_and_schedule(package_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = read_csv(package_dir / "blinding_key.csv")
    schedule = read_csv(package_dir / "assay_run_schedule_blinded.csv")
    require_columns(
        key,
        {
            "package_version",
            "assay_sample_id",
            "candidate_id",
            "prospective_group_id",
            "group_type",
            "candidate_role",
            "family_id",
            "vhh_sequence",
            "sequence_sha256",
            "target_id",
            "target_construct",
            "target_sequence_sha256",
        },
        "blinding_key",
    )
    require_columns(schedule, RUN_IDENTITY_COLUMNS, "assay_run_schedule_blinded")
    if len(key) != 24 or key["assay_sample_id"].nunique() != 24 or key["sequence_sha256"].nunique() != 24:
        raise AssayContractError("Blinding key must contain 24 unique assay samples and sequence hashes")
    if len(schedule) != 72 or schedule["run_id"].nunique() != 3 or schedule["day_block"].nunique() < 2:
        raise AssayContractError("Run schedule must contain 72 sample-runs across three runs and at least two days")
    if {"candidate_id", "candidate_role", "current_truth_status"} & set(schedule.columns):
        raise AssayContractError("Blinded run schedule exposes candidate identity or truth role")
    expected_ids = set(key["assay_sample_id"])
    if set(schedule["assay_sample_id"]) != expected_ids:
        raise AssayContractError("Run schedule sample IDs do not match the blinding key")
    if not schedule.groupby("run_id")["assay_sample_id"].nunique().eq(24).all():
        raise AssayContractError("Each run must contain every assay sample exactly once")
    identity = key.set_index("assay_sample_id")
    for row in schedule.to_dict(orient="records"):
        expected = identity.loc[row["assay_sample_id"]]
        for column in ("target_id", "target_construct", "target_sequence_sha256"):
            if clean(row[column]) != clean(expected[column]):
                raise AssayContractError(f"Schedule identity mismatch for {row['assay_sample_id']} in {column}")
    return key, schedule


def validate_result_identity(frame: pd.DataFrame, schedule: pd.DataFrame, label: str) -> None:
    require_columns(frame, RUN_IDENTITY_COLUMNS, label)
    expected = schedule[list(RUN_IDENTITY_COLUMNS)].copy()
    observed = frame[list(RUN_IDENTITY_COLUMNS)].copy()
    key_columns = ["run_id", "assay_sample_id"]
    if observed.duplicated(key_columns).any():
        raise AssayContractError(f"{label} contains duplicate run/sample rows")
    merged = expected.merge(observed, on=key_columns, how="outer", suffixes=("_expected", "_observed"), indicator=True)
    if len(merged) != len(expected) or not merged["_merge"].eq("both").all():
        raise AssayContractError(f"{label} rows do not exactly match the blinded run schedule")
    for column in RUN_IDENTITY_COLUMNS - set(key_columns):
        if not merged[f"{column}_expected"].astype(str).eq(merged[f"{column}_observed"].astype(str)).all():
            raise AssayContractError(f"{label} changed frozen run identity field {column}")


def validate_raw_evidence(package_dir: Path, frame: pd.DataFrame, call_column: str, label: str) -> None:
    for row in frame.to_dict(orient="records"):
        call = upper(row[call_column])
        if call in PENDING_VALUES:
            continue
        raw_path_text = clean(row["raw_data_path"])
        raw_hash = clean(row["raw_data_sha256"]).lower()
        if not raw_path_text or len(raw_hash) != 64 or any(char not in "0123456789abcdef" for char in raw_hash):
            raise AssayContractError(f"{label} completed call lacks raw_data_path/raw_data_sha256")
        raw_path = Path(raw_path_text)
        if not raw_path.is_absolute():
            raw_path = package_dir / raw_path
        if not raw_path.is_file() or sha256_file(raw_path) != raw_hash:
            raise AssayContractError(f"{label} raw evidence is missing or hash-mismatched: {raw_path_text}")


def load_preregistration(package_dir: Path) -> tuple[dict[str, object], bool]:
    path = package_dir / "assay_preregistration.json"
    prereg = json.loads(path.read_text(encoding="utf-8"))
    parameters = prereg.get("lab_parameters_to_freeze_before_first_measurement")
    if not isinstance(parameters, dict):
        raise AssayContractError("Preregistration lacks lab parameter contract")
    complete = all(value is not None and clean(value) for value in parameters.values())
    return prereg, complete


def any_completed_calls(frames_and_columns: Iterable[tuple[pd.DataFrame, str]]) -> bool:
    return any(
        upper(value) not in PENDING_VALUES
        for frame, column in frames_and_columns
        for value in frame[column]
    )


def validate_result_tables(
    package_dir: Path, key: pd.DataFrame, schedule: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object], bool]:
    qc = read_csv(package_dir / "expression_qc_results.csv")
    binding = read_csv(package_dir / "binding_results.csv")
    competition = read_csv(package_dir / "competition_results.csv")
    functional = read_csv(package_dir / "functional_results.csv")

    require_columns(qc, QC_REQUIRED_COLUMNS, "expression_qc_results")
    if len(qc) != 24 or qc["assay_sample_id"].nunique() != 24:
        raise AssayContractError("Expression QC results must contain one row per assay sample")
    if set(qc["assay_sample_id"]) != set(key["assay_sample_id"]):
        raise AssayContractError("Expression QC sample IDs do not match the blinding key")
    expected_hash = key.set_index("assay_sample_id")["sequence_sha256"].to_dict()
    for row in qc.to_dict(orient="records"):
        if clean(row["sequence_sha256_expected"]) != clean(expected_hash[row["assay_sample_id"]]):
            raise AssayContractError(f"Expression QC expected sequence hash changed for {row['assay_sample_id']}")

    binding_required = RUN_IDENTITY_COLUMNS | {
        "assay_method",
        "analyte_max_concentration_nM",
        "kd_value_M",
        "kd_qualifier",
        "fit_qc_call",
        "concentration_dependent_binding_call",
        "scientist_binding_call",
        "raw_data_path",
        "raw_data_sha256",
    }
    competition_required = RUN_IDENTITY_COLUMNS | {
        "verified_binder_eligibility",
        "assay_method",
        "analyte_max_concentration_nM",
        "ic50_value_nM",
        "ic50_qualifier",
        "fit_qc_call",
        "scientist_blocking_call",
        "raw_data_path",
        "raw_data_sha256",
    }
    functional_required = RUN_IDENTITY_COLUMNS | {
        "verified_blocker_eligibility",
        "assay_method",
        "analyte_max_concentration_nM",
        "ec50_value_nM",
        "ec50_qualifier",
        "viability_fraction",
        "fit_qc_call",
        "scientist_functional_call",
        "raw_data_path",
        "raw_data_sha256",
    }
    require_columns(binding, binding_required, "binding_results")
    require_columns(competition, competition_required, "competition_results")
    require_columns(functional, functional_required, "functional_results")
    validate_result_identity(binding, schedule, "binding_results")
    validate_result_identity(competition, schedule, "competition_results")
    validate_result_identity(functional, schedule, "functional_results")

    require_allowed(qc, "scientist_qc_call", QC_CALLS, "expression_qc_results")
    require_allowed(qc, "identity_call", IDENTITY_CALLS, "expression_qc_results")
    require_allowed(binding, "scientist_binding_call", BINDING_CALLS, "binding_results")
    require_allowed(binding, "fit_qc_call", FIT_CALLS, "binding_results")
    require_allowed(binding, "concentration_dependent_binding_call", CONCENTRATION_CALLS, "binding_results")
    require_allowed(competition, "scientist_blocking_call", BLOCKING_CALLS, "competition_results")
    require_allowed(competition, "fit_qc_call", FIT_CALLS, "competition_results")
    require_allowed(functional, "scientist_functional_call", FUNCTIONAL_CALLS, "functional_results")
    require_allowed(functional, "fit_qc_call", FIT_CALLS, "functional_results")

    validate_raw_evidence(package_dir, qc, "scientist_qc_call", "expression_qc_results")
    validate_raw_evidence(package_dir, binding, "scientist_binding_call", "binding_results")
    validate_raw_evidence(package_dir, competition, "scientist_blocking_call", "competition_results")
    validate_raw_evidence(package_dir, functional, "scientist_functional_call", "functional_results")

    prereg, prereg_complete = load_preregistration(package_dir)
    if any_completed_calls(
        [
            (qc, "scientist_qc_call"),
            (binding, "scientist_binding_call"),
            (competition, "scientist_blocking_call"),
            (functional, "scientist_functional_call"),
        ]
    ) and not prereg_complete:
        raise AssayContractError("Measurements were entered before all lab-specific parameters were frozen")
    return qc, binding, competition, functional, prereg, prereg_complete


def threshold(prereg: dict[str, object], name: str) -> float:
    values = prereg["lab_parameters_to_freeze_before_first_measurement"]
    assert isinstance(values, dict)
    value = numeric(values[name], field=f"preregistration.{name}", allow_blank=False)
    assert value is not None
    return value


def qc_status(row: pd.Series, prereg: dict[str, object], prereg_complete: bool) -> tuple[str, list[str]]:
    call = upper(row["scientist_qc_call"])
    if call == "PENDING":
        return "PENDING_EXPRESSION_QC", ["expression_qc_pending"]
    if call == "INCONCLUSIVE":
        return "INCONCLUSIVE_REMEASURE", ["expression_qc_inconclusive"]
    if call == "FAIL":
        reason = clean(row["exclusion_reason"]) or "expression_or_qc_failure"
        return "EXCLUDED_EXPRESSION_OR_QC_FAILURE", [reason]
    if call != "PASS":
        raise AssayContractError(f"Unexpected QC call {call}")
    if not prereg_complete:
        raise AssayContractError("QC PASS cannot be interpreted before preregistration is complete")
    if upper(row["identity_call"]) != "PASS":
        raise AssayContractError("QC PASS requires identity_call=PASS")
    if clean(row["sequence_sha256_observed"]) != clean(row["sequence_sha256_expected"]):
        raise AssayContractError("QC PASS requires the observed sequence hash to match the expected hash")
    yield_value = numeric(row["expression_yield_mg_per_l"], field="expression_yield_mg_per_l", allow_blank=False)
    purity = numeric(row["purity_fraction"], field="purity_fraction", allow_blank=False)
    monomer = numeric(row["sec_monomer_fraction"], field="sec_monomer_fraction", allow_blank=False)
    aggregation = numeric(row["aggregation_fraction"], field="aggregation_fraction", allow_blank=False)
    assert yield_value is not None and purity is not None and monomer is not None and aggregation is not None
    violations = []
    if yield_value < threshold(prereg, "minimum_expression_yield_mg_per_l"):
        violations.append("yield_below_preregistered_minimum")
    if purity < threshold(prereg, "minimum_purity_fraction"):
        violations.append("purity_below_preregistered_minimum")
    if monomer < threshold(prereg, "minimum_sec_monomer_fraction"):
        violations.append("sec_monomer_below_preregistered_minimum")
    if aggregation > threshold(prereg, "maximum_aggregation_fraction"):
        violations.append("aggregation_above_preregistered_maximum")
    if violations:
        raise AssayContractError(f"QC PASS conflicts with preregistered thresholds: {violations}")
    return "QC_PASS", []


def stage_rows(frame: pd.DataFrame, sample_id: str) -> pd.DataFrame:
    return frame[frame["assay_sample_id"] == sample_id].copy()


def consensus_status(
    rows: pd.DataFrame,
    *,
    call_column: str,
    positive_call: str,
    negative_call: str,
    positive_status: str,
    negative_status: str,
    pending_status: str,
    inconclusive_status: str,
) -> str:
    normalized_calls = rows[call_column].map(upper)
    calls = normalized_calls.tolist()
    if all(call in PENDING_VALUES for call in calls):
        return pending_status
    entered_rows = rows[~normalized_calls.isin(PENDING_VALUES)]
    if entered_rows["raw_data_sha256"].astype(str).nunique() < entered_rows["run_id"].nunique():
        raise AssayContractError("Independent runs must reference distinct raw-data files")
    if any(call in {"PENDING", "NOT_RUN", "INCONCLUSIVE"} for call in calls):
        return inconclusive_status
    if rows["run_id"].nunique() < 3 or rows["day_block"].nunique() < 2:
        return inconclusive_status
    if not rows["fit_qc_call"].map(upper).eq("PASS").all():
        return inconclusive_status
    if set(calls) == {positive_call}:
        return positive_status
    if set(calls) == {negative_call}:
        return negative_status
    return inconclusive_status


def validate_binding_call_rows(rows: pd.DataFrame, prereg: dict[str, object]) -> None:
    for row in rows.to_dict(orient="records"):
        call = upper(row["scientist_binding_call"])
        if call in PENDING_VALUES or call == "INCONCLUSIVE":
            continue
        if upper(row["fit_qc_call"]) != "PASS" or not clean(row["assay_method"]):
            raise AssayContractError("Completed binding calls require assay_method and fit_qc_call=PASS")
        max_concentration = numeric(
            row["analyte_max_concentration_nM"], field="binding.analyte_max_concentration_nM", allow_blank=False
        )
        if max_concentration is None or max_concentration <= 0:
            raise AssayContractError("Completed binding calls require a positive maximum analyte concentration")
        concentration_call = upper(row["concentration_dependent_binding_call"])
        if call == "BINDER" and concentration_call != "PRESENT":
            raise AssayContractError("BINDER requires concentration_dependent_binding_call=PRESENT")
        if call == "NONBINDER" and concentration_call != "ABSENT":
            raise AssayContractError("NONBINDER requires concentration_dependent_binding_call=ABSENT")
        if call == "NONBINDER" and max_concentration < threshold(prereg, "binding_max_analyte_concentration_nM"):
            raise AssayContractError("NONBINDER did not reach the preregistered maximum analyte concentration")
        kd = numeric(row["kd_value_M"], field="binding.kd_value_M")
        if call == "BINDER" and (kd is None or kd <= 0) and not clean(row["kd_qualifier"]):
            raise AssayContractError("BINDER requires a positive Kd or an explicit censoring qualifier")


def validate_competition_call_rows(rows: pd.DataFrame, prereg: dict[str, object]) -> None:
    for row in rows.to_dict(orient="records"):
        call = upper(row["scientist_blocking_call"])
        if call in PENDING_VALUES or call == "INCONCLUSIVE":
            continue
        if upper(row["fit_qc_call"]) != "PASS" or not clean(row["assay_method"]):
            raise AssayContractError("Completed competition calls require assay_method and fit_qc_call=PASS")
        max_concentration = numeric(
            row["analyte_max_concentration_nM"], field="competition.analyte_max_concentration_nM", allow_blank=False
        )
        if max_concentration is None or max_concentration <= 0:
            raise AssayContractError("Completed competition calls require a positive maximum analyte concentration")
        if call == "NONBLOCKER" and max_concentration < threshold(prereg, "competition_max_analyte_concentration_nM"):
            raise AssayContractError("NONBLOCKER did not reach the preregistered maximum analyte concentration")
        ic50 = numeric(row["ic50_value_nM"], field="competition.ic50_value_nM")
        if call == "BLOCKER" and (ic50 is None or ic50 <= 0) and not clean(row["ic50_qualifier"]):
            raise AssayContractError("BLOCKER requires a positive IC50 or an explicit censoring qualifier")


def validate_functional_call_rows(rows: pd.DataFrame, prereg: dict[str, object]) -> None:
    for row in rows.to_dict(orient="records"):
        call = upper(row["scientist_functional_call"])
        if call in PENDING_VALUES:
            continue
        if upper(row["fit_qc_call"]) != "PASS" or not clean(row["assay_method"]):
            raise AssayContractError("Completed functional calls require assay_method and fit_qc_call=PASS")
        max_concentration = numeric(
            row["analyte_max_concentration_nM"], field="functional.analyte_max_concentration_nM", allow_blank=False
        )
        if max_concentration is None or max_concentration <= 0:
            raise AssayContractError("Completed functional calls require a positive maximum analyte concentration")
        if call == "NEGATIVE" and max_concentration < threshold(prereg, "functional_max_analyte_concentration_nM"):
            raise AssayContractError("Functional NEGATIVE did not reach the preregistered maximum analyte concentration")
        viability = numeric(row["viability_fraction"], field="functional.viability_fraction", allow_blank=False)
        if viability is None or not 0 <= viability <= 1:
            raise AssayContractError("Completed functional calls require viability_fraction in [0, 1]")
        if viability < threshold(prereg, "minimum_functional_viability_fraction"):
            raise AssayContractError("Completed functional call failed the preregistered viability gate")
        ec50 = numeric(row["ec50_value_nM"], field="functional.ec50_value_nM")
        if call == "POSITIVE" and (ec50 is None or ec50 <= 0) and not clean(row["ec50_qualifier"]):
            raise AssayContractError("Functional POSITIVE requires a positive EC50 or censoring qualifier")


def has_completed_call(rows: pd.DataFrame, column: str) -> bool:
    return any(upper(value) not in PENDING_VALUES for value in rows[column])


def median_value(rows: pd.DataFrame, column: str) -> float | str:
    values = [numeric(value, field=column) for value in rows[column]]
    present = sorted(value for value in values if value is not None)
    if not present:
        return ""
    middle = len(present) // 2
    return present[middle] if len(present) % 2 else (present[middle - 1] + present[middle]) / 2.0


def evidence_row(
    identity: pd.Series,
    rows: pd.DataFrame,
    *,
    axis: str,
    consensus_call: str,
    binary_label: int,
    value_column: str,
    value_unit: str,
) -> dict[str, object]:
    source_paths = sorted({clean(value) for value in rows["raw_data_path"] if clean(value)})
    raw_hashes = sorted({clean(value).lower() for value in rows["raw_data_sha256"] if clean(value)})
    identity_material = "|".join(
        [
            clean(identity["assay_sample_id"]),
            clean(identity["sequence_sha256"]),
            clean(identity["target_sequence_sha256"]),
            axis,
            PACKAGE_VERSION,
        ]
    )
    return {
        "schema_version": "pvrig_v2_6_e6_label_candidate_v1",
        "package_version": PACKAGE_VERSION,
        "row_identity_sha256": sha256_text(identity_material),
        "assay_sample_id": identity["assay_sample_id"],
        "candidate_id": identity["candidate_id"],
        "prospective_group_id": identity["prospective_group_id"],
        "group_type": identity["group_type"],
        "family_id": identity["family_id"],
        "sequence_sha256": identity["sequence_sha256"],
        "target_id": identity["target_id"],
        "target_construct": identity["target_construct"],
        "target_sequence_sha256": identity["target_sequence_sha256"],
        "label_axis": axis,
        "consensus_call": consensus_call,
        "binary_label": binary_label,
        "median_label_value": median_value(rows, value_column),
        "label_unit": value_unit,
        "replicate_count": int(rows["run_id"].nunique()),
        "day_block_count": int(rows["day_block"].nunique()),
        "raw_data_paths": ";".join(source_paths),
        "raw_data_sha256_set": ";".join(raw_hashes),
        "evidence_level": "E6_CANDIDATE_PENDING_REVIEW",
        "allowed_use": "PROSPECTIVE_E6_REVIEW_ONLY",
        "ordinary_train_allowed": "false",
        "formal_use": "NEW_VERSION_SPLIT_AND_SEAL_REQUIRED",
        "claim_boundary": "derived_from_explicit_scientist_calls_not_automatic_curve_interpretation",
    }


def analyze_candidates(
    key: pd.DataFrame,
    qc: pd.DataFrame,
    binding: pd.DataFrame,
    competition: pd.DataFrame,
    functional: pd.DataFrame,
    prereg: dict[str, object],
    prereg_complete: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    qc_by_id = qc.set_index("assay_sample_id")
    status_rows: list[dict[str, object]] = []
    evidence_rows: list[dict[str, object]] = []

    for identity_dict in key.to_dict(orient="records"):
        identity = pd.Series(identity_dict)
        sample_id = clean(identity["assay_sample_id"])
        qc_state, missing = qc_status(qc_by_id.loc[sample_id], prereg, prereg_complete)
        binding_rows = stage_rows(binding, sample_id)
        competition_rows = stage_rows(competition, sample_id)
        functional_rows = stage_rows(functional, sample_id)
        validate_binding_call_rows(binding_rows, prereg)
        validate_competition_call_rows(competition_rows, prereg)
        validate_functional_call_rows(functional_rows, prereg)

        if qc_state != "QC_PASS":
            binding_state = "NOT_INTERPRETABLE_WITHOUT_QC_PASS"
            blocking_state = "NOT_ELIGIBLE_WITHOUT_VERIFIED_BINDING"
            functional_state = "NOT_ELIGIBLE_WITHOUT_VERIFIED_BLOCKING"
            truth_status = qc_state
        else:
            binding_state = consensus_status(
                binding_rows,
                call_column="scientist_binding_call",
                positive_call="BINDER",
                negative_call="NONBINDER",
                positive_status="VERIFIED_BINDER",
                negative_status="VERIFIED_NONBINDER",
                pending_status="PENDING_BINDING",
                inconclusive_status="BINDING_INCONCLUSIVE",
            )
            if binding_state == "VERIFIED_BINDER":
                evidence_rows.append(
                    evidence_row(
                        identity,
                        binding_rows,
                        axis="binding",
                        consensus_call="VERIFIED_BINDER",
                        binary_label=1,
                        value_column="kd_value_M",
                        value_unit="M",
                    )
                )
                if has_completed_call(competition_rows, "scientist_blocking_call") and not competition_rows[
                    "verified_binder_eligibility"
                ].map(upper).eq("YES").all():
                    raise AssayContractError("Completed competition calls require verified_binder_eligibility=YES")
                blocking_state = consensus_status(
                    competition_rows,
                    call_column="scientist_blocking_call",
                    positive_call="BLOCKER",
                    negative_call="NONBLOCKER",
                    positive_status="BIOCHEMICAL_BLOCKER",
                    negative_status="VERIFIED_BINDER_NONBLOCKER",
                    pending_status="PENDING_COMPETITION",
                    inconclusive_status="COMPETITION_INCONCLUSIVE",
                )
            elif binding_state == "VERIFIED_NONBINDER":
                if has_completed_call(competition_rows, "scientist_blocking_call"):
                    raise AssayContractError("Competition results cannot be interpreted for a verified nonbinder")
                evidence_rows.append(
                    evidence_row(
                        identity,
                        binding_rows,
                        axis="binding",
                        consensus_call="VERIFIED_NONBINDER",
                        binary_label=0,
                        value_column="kd_value_M",
                        value_unit="M",
                    )
                )
                blocking_state = "NOT_ELIGIBLE_NONBINDER"
            else:
                if has_completed_call(competition_rows, "scientist_blocking_call"):
                    raise AssayContractError("Competition calls require a verified binding consensus first")
                blocking_state = "NOT_ELIGIBLE_WITHOUT_VERIFIED_BINDING"

            if blocking_state == "BIOCHEMICAL_BLOCKER":
                evidence_rows.append(
                    evidence_row(
                        identity,
                        competition_rows,
                        axis="blocking",
                        consensus_call="BIOCHEMICAL_BLOCKER",
                        binary_label=1,
                        value_column="ic50_value_nM",
                        value_unit="nM",
                    )
                )
                if has_completed_call(functional_rows, "scientist_functional_call") and not functional_rows[
                    "verified_blocker_eligibility"
                ].map(upper).eq("YES").all():
                    raise AssayContractError("Completed functional calls require verified_blocker_eligibility=YES")
                functional_state = consensus_status(
                    functional_rows,
                    call_column="scientist_functional_call",
                    positive_call="POSITIVE",
                    negative_call="NEGATIVE",
                    positive_status="FUNCTIONAL_POSITIVE",
                    negative_status="FUNCTIONAL_NEGATIVE",
                    pending_status="PENDING_FUNCTIONAL",
                    inconclusive_status="FUNCTIONAL_INCONCLUSIVE",
                )
            elif blocking_state == "VERIFIED_BINDER_NONBLOCKER":
                if has_completed_call(functional_rows, "scientist_functional_call"):
                    raise AssayContractError("Functional blocker calls cannot be interpreted for a nonblocker")
                evidence_rows.append(
                    evidence_row(
                        identity,
                        competition_rows,
                        axis="blocking",
                        consensus_call="VERIFIED_BINDER_NONBLOCKER",
                        binary_label=0,
                        value_column="ic50_value_nM",
                        value_unit="nM",
                    )
                )
                functional_state = "NOT_ELIGIBLE_NONBLOCKER"
            else:
                if has_completed_call(functional_rows, "scientist_functional_call"):
                    raise AssayContractError("Functional calls require a biochemical blocker consensus first")
                functional_state = "NOT_ELIGIBLE_WITHOUT_VERIFIED_BLOCKING"

            if functional_state in {"FUNCTIONAL_POSITIVE", "FUNCTIONAL_NEGATIVE"}:
                evidence_rows.append(
                    evidence_row(
                        identity,
                        functional_rows,
                        axis="functional",
                        consensus_call=functional_state,
                        binary_label=1 if functional_state == "FUNCTIONAL_POSITIVE" else 0,
                        value_column="ec50_value_nM",
                        value_unit="nM",
                    )
                )

            if binding_state == "VERIFIED_NONBINDER":
                truth_status = "VERIFIED_NONBINDER"
            elif binding_state == "PENDING_BINDING":
                truth_status = "PENDING_BINDING"
            elif binding_state == "BINDING_INCONCLUSIVE":
                truth_status = "BINDING_INCONCLUSIVE_REMEASURE"
            elif blocking_state == "VERIFIED_BINDER_NONBLOCKER":
                truth_status = "VERIFIED_BINDER_NONBLOCKER"
            elif blocking_state == "PENDING_COMPETITION":
                truth_status = "VERIFIED_BINDER_COMPETITION_PENDING"
            elif blocking_state == "COMPETITION_INCONCLUSIVE":
                truth_status = "COMPETITION_INCONCLUSIVE_REMEASURE"
            elif functional_state == "FUNCTIONAL_POSITIVE":
                truth_status = "FUNCTIONAL_BLOCKER_VALIDATED"
            elif functional_state == "FUNCTIONAL_NEGATIVE":
                truth_status = "BIOCHEMICAL_BLOCKER_FUNCTIONAL_NEGATIVE"
            elif functional_state == "PENDING_FUNCTIONAL":
                truth_status = "BIOCHEMICAL_BLOCKER_FUNCTIONAL_PENDING"
            else:
                truth_status = "ASSAY_REVIEW_REQUIRED"

        status_rows.append(
            {
                "package_version": PACKAGE_VERSION,
                "assay_sample_id": sample_id,
                "candidate_id": identity["candidate_id"],
                "prospective_group_id": identity["prospective_group_id"],
                "group_type": identity["group_type"],
                "candidate_role": identity["candidate_role"],
                "sequence_sha256": identity["sequence_sha256"],
                "target_sequence_sha256": identity["target_sequence_sha256"],
                "qc_status": qc_state,
                "binding_status": binding_state,
                "blocking_status": blocking_state,
                "functional_status": functional_state,
                "truth_status": truth_status,
                "eligible_e6_candidate_axes": sum(
                    1 for row in evidence_rows if row["assay_sample_id"] == sample_id
                ),
                "missing_or_exclusion_reasons": ";".join(missing),
                "model_use_status": "REVIEW_AND_NEW_VERSION_SPLIT_REQUIRED",
            }
        )
    return pd.DataFrame(status_rows), pd.DataFrame(evidence_rows)


def overall_status(candidate_status: pd.DataFrame, prereg_complete: bool) -> str:
    truth = candidate_status["truth_status"].astype(str)
    if truth.eq("PENDING_EXPRESSION_QC").all():
        return "READY_FOR_LAB_PREREGISTRATION" if not prereg_complete else "READY_FOR_MEASUREMENT"
    terminal = {
        "VERIFIED_NONBINDER",
        "VERIFIED_BINDER_NONBLOCKER",
        "FUNCTIONAL_BLOCKER_VALIDATED",
        "BIOCHEMICAL_BLOCKER_FUNCTIONAL_NEGATIVE",
        "EXCLUDED_EXPRESSION_OR_QC_FAILURE",
    }
    if truth.isin(terminal).all():
        return "MEASUREMENTS_COMPLETE_REVIEW_REQUIRED"
    return "MEASUREMENTS_IN_PROGRESS"


def write_outputs(
    package_dir: Path,
    candidate_status: pd.DataFrame,
    evidence: pd.DataFrame,
    prereg_complete: bool,
    manifest: dict[str, object],
) -> dict[str, object]:
    status_path = package_dir / "candidate_assay_status.csv"
    evidence_path = package_dir / "e6_label_candidates_review.csv"
    candidate_status.to_csv(status_path, index=False, lineterminator="\n")
    if evidence.empty:
        evidence = pd.DataFrame(
            columns=[
                "schema_version",
                "package_version",
                "row_identity_sha256",
                "assay_sample_id",
                "candidate_id",
                "prospective_group_id",
                "group_type",
                "family_id",
                "sequence_sha256",
                "target_id",
                "target_construct",
                "target_sequence_sha256",
                "label_axis",
                "consensus_call",
                "binary_label",
                "median_label_value",
                "label_unit",
                "replicate_count",
                "day_block_count",
                "raw_data_paths",
                "raw_data_sha256_set",
                "evidence_level",
                "allowed_use",
                "ordinary_train_allowed",
                "formal_use",
                "claim_boundary",
            ]
        )
    evidence.to_csv(evidence_path, index=False, lineterminator="\n")

    status = overall_status(candidate_status, prereg_complete)
    summary = {
        "schema_version": "pvrig_v2_5_assay_analysis_summary_v1",
        "package_version": PACKAGE_VERSION,
        "package_status": manifest.get("status"),
        "preregistration_complete": prereg_complete,
        "measurement_status": status,
        "candidate_count": len(candidate_status),
        "truth_status_counts": candidate_status["truth_status"].value_counts().sort_index().to_dict(),
        "e6_candidate_row_count": len(evidence),
        "e6_candidate_axis_counts": evidence["label_axis"].value_counts().sort_index().to_dict() if len(evidence) else {},
        "model_readiness_decision": "NOT_EVALUATED_BY_ASSAY_INTAKE",
        "required_next_gate": "MANUAL_SCIENTIFIC_REVIEW_THEN_V2_6_SPLIT_SEAL_AND_READINESS",
        "claim_boundary": "no_pending_template_or_derived_row_is_automatic_binding_blocking_or_model_truth",
        "output_sha256": {
            "candidate_assay_status.csv": sha256_file(status_path),
            "e6_label_candidates_review.csv": sha256_file(evidence_path),
        },
    }
    summary_path = package_dir / "assay_analysis_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")

    report_lines = [
        "# PVRIG V2.5 Prospective Assay Execution Status",
        "",
        f"- Measurement status: **{status}**",
        f"- Preregistration complete: `{str(prereg_complete).lower()}`",
        f"- Candidate count: `{len(candidate_status)}`",
        f"- E6 review-candidate rows: `{len(evidence)}`",
        "- Model readiness: **NOT_EVALUATED_BY_ASSAY_INTAKE**",
        "",
        "## Truth Status Counts",
        "",
    ]
    for name, count in summary["truth_status_counts"].items():
        report_lines.append(f"- `{name}`: {count}")
    report_lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Expression or assay failure is excluded and is never relabeled as nonbinding.",
            "Binding does not imply blocking. Derived E6 rows remain review-only until a",
            "new V2.6 split, seal, readiness evaluation, and one-shot formal protocol exist.",
            "",
        ]
    )
    (package_dir / "ASSAY_EXECUTION_STATUS.md").write_text("\n".join(report_lines), encoding="ascii")
    return summary


def analyze(package_dir: Path) -> dict[str, object]:
    manifest = validate_package_manifest(package_dir)
    key, schedule = validate_identity_and_schedule(package_dir)
    qc, binding, competition, functional, prereg, prereg_complete = validate_result_tables(
        package_dir, key, schedule
    )
    measurements_entered = any_completed_calls(
        [
            (qc, "scientist_qc_call"),
            (binding, "scientist_binding_call"),
            (competition, "scientist_blocking_call"),
            (functional, "scientist_functional_call"),
        ]
    )
    if measurements_entered and (
        manifest.get("preregistration_frozen") is not True or manifest.get("status") != "READY_FOR_MEASUREMENT"
    ):
        raise AssayContractError("Completed measurements require the preregistration freeze command")
    candidate_status, evidence = analyze_candidates(
        key, qc, binding, competition, functional, prereg, prereg_complete
    )
    return write_outputs(package_dir, candidate_status, evidence, prereg_complete, manifest)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = analyze(args.package_dir)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
