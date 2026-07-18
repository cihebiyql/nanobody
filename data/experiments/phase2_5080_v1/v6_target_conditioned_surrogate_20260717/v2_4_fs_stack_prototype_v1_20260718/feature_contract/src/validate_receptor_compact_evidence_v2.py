#!/usr/bin/env python3
"""Validate V2.4 role-separated receptor compact feature/meta evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


PROVENANCE_SCHEMA_VERSION = "pvrig_v2_4_component_provenance_v2"
BASE_ROW_SCHEMA_VERSION = "pvrig_v2_4_receptor_base_feature_row_v2"
META_ROW_SCHEMA_VERSION = "pvrig_v2_4_outer_meta_prediction_row_v2"
CONTACT_FORMULA_VERSION = "pvrig_v2_4_contact_composite_v1_equal_weight_preregistered"
STACK_SCALING_CONTRACT = "weighted_shared_receptor_zscore_meta_train_only_v1"
STACK_RIDGE_ALPHA = 1.0e-3
STACK_CONDITION_NUMBER_CEILING = 1.0e6
CANONICAL_V2_4_LABEL_TABLE_SHA256 = "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
CANONICAL_OUTER_SPLIT_SHA256 = "ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55"
CANONICAL_INNER_SPLIT_SHA256 = "b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073"
CANONICAL_SPLIT_BUILDER = "pvrig_v2_4_whole_parent_nested_split_builder_v3_parent_balanced"
CANONICAL_OUTER_SPLIT_SCHEMA = "pvrig_v2_4_whole_parent_outer_split_manifest_v3"
CANONICAL_INNER_SPLIT_SCHEMA = "pvrig_v2_4_whole_parent_inner_split_manifest_v3"

INNER_OOF_BASE_FEATURE = "INNER_OOF_BASE_FEATURE"
OUTER_TEST_BASE_FEATURE = "OUTER_TEST_BASE_FEATURE"
OUTER_TEST_META_PREDICTION = "OUTER_TEST_META_PREDICTION"
BASE_ROLES = {INNER_OOF_BASE_FEATURE, OUTER_TEST_BASE_FEATURE}

COMPACT_FEATURE_COLUMNS = (
    "M2_R8",
    "neural_R8",
    "contact_score_R8",
    "M2_R9",
    "neural_R9",
    "contact_score_R9",
)

BASE_COLUMNS = (
    "schema_version",
    "evidence_role",
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "inner_fold",
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    *COMPACT_FEATURE_COLUMNS,
    "split_manifest_path",
    "split_manifest_sha256",
    "split_train_parent_set_sha256",
    "split_score_parent_set_sha256",
    "M2_training_parent_set_sha256",
    "M2_component_receipt_sha256",
    "M2_artifact_path",
    "neural_training_parent_set_sha256",
    "neural_component_receipt_sha256",
    "neural_checkpoint_path",
    "contact_training_parent_set_sha256",
    "contact_component_receipt_sha256",
    "contact_checkpoint_path",
    "contact_formula_receipt_sha256",
    "contact_formula_artifact_path",
)

META_COLUMNS = (
    "schema_version",
    "evidence_role",
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    "prediction_R8",
    "prediction_R9",
    "prediction_R_dual_min",
    "split_manifest_path",
    "split_manifest_sha256",
    "split_train_parent_set_sha256",
    "split_score_parent_set_sha256",
    "outer_base_feature_evidence_path",
    "outer_base_feature_evidence_sha256",
    "fit_inner_oof_evidence_path",
    "fit_inner_oof_evidence_sha256",
    "fit_inner_oof_parent_set_sha256",
    "scaling_fit_parent_set_sha256",
    "meta_training_parent_set_sha256",
    "meta_model_receipt_sha256",
    "meta_model_artifact_path",
)

_V4F_TOKEN = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])", re.IGNORECASE)


class EvidenceContractError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_parent_set_sha256(parents: Iterable[str]) -> str:
    payload = "".join(f"{parent}\n" for parent in sorted(set(parents))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _check_path(path: str, context: str) -> None:
    if _V4F_TOKEN.search(path):
        raise EvidenceContractError(f"forbidden_v4f_path:{context}:{path}")
    if not Path(path).is_absolute():
        raise EvidenceContractError(f"path_not_absolute:{context}:{path}")


def _exact_min(left: str, right: str, observed: str, context: str) -> None:
    a = np.float64(left)
    b = np.float64(right)
    value = np.float64(observed)
    expected = np.minimum(a, b)
    if value.tobytes() != expected.tobytes():
        raise EvidenceContractError(
            f"not_exact_min:{context}:observed={value!r}:expected={expected!r}"
        )


def read_evidence(path: Path) -> tuple[list[dict[str, str]], str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        fieldnames = tuple(reader.fieldnames or ())
    if not rows:
        raise EvidenceContractError("empty_evidence")
    roles = {row.get("evidence_role", "") for row in rows}
    if len(roles) != 1:
        raise EvidenceContractError("mixed_or_missing_evidence_roles")
    role = next(iter(roles))
    expected = BASE_COLUMNS if role in BASE_ROLES else META_COLUMNS if role == OUTER_TEST_META_PREDICTION else ()
    if fieldnames != expected:
        raise EvidenceContractError(f"exact_header_mismatch:role={role}")
    validate_row_values(rows, role)
    return rows, role


def validate_row_values(rows: Sequence[Mapping[str, str]], role: str) -> None:
    columns = BASE_COLUMNS if role in BASE_ROLES else META_COLUMNS
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        for column in columns:
            if str(row.get(column, "")).strip() == "":
                raise EvidenceContractError(f"blank_value:row={row_number}:column={column}")
        expected_schema = BASE_ROW_SCHEMA_VERSION if role in BASE_ROLES else META_ROW_SCHEMA_VERSION
        if row["schema_version"] != expected_schema or row["evidence_role"] != role:
            raise EvidenceContractError(f"row_role_or_schema_mismatch:row={row_number}")
        if row["candidate_id"] in seen:
            raise EvidenceContractError(f"duplicate_candidate_id:{row['candidate_id']}")
        seen.add(row["candidate_id"])
        if re.sub(r"[^a-z0-9]", "", row["teacher_source"].lower()) == "v4f":
            raise EvidenceContractError(f"forbidden_v4f_source:{row['candidate_id']}")
        if role == OUTER_TEST_BASE_FEATURE and row["inner_fold"] != "NONE":
            raise EvidenceContractError(f"outer_base_inner_fold_not_NONE:{row['candidate_id']}")
        if role == INNER_OOF_BASE_FEATURE and row["inner_fold"] == "NONE":
            raise EvidenceContractError(f"inner_base_missing_inner_fold:{row['candidate_id']}")

        numeric = ["R_8X6B", "R_9E6Y", "R_dual_min"]
        numeric += list(COMPACT_FEATURE_COLUMNS) if role in BASE_ROLES else [
            "prediction_R8", "prediction_R9", "prediction_R_dual_min"
        ]
        for column in numeric:
            try:
                value = float(row[column])
            except ValueError as exc:
                raise EvidenceContractError(f"non_numeric:row={row_number}:column={column}") from exc
            if not math.isfinite(value):
                raise EvidenceContractError(f"non_finite:row={row_number}:column={column}")
        _exact_min(row["R_8X6B"], row["R_9E6Y"], row["R_dual_min"], f"truth:{row['candidate_id']}")
        if role == OUTER_TEST_META_PREDICTION:
            _exact_min(
                row["prediction_R8"], row["prediction_R9"], row["prediction_R_dual_min"],
                f"prediction:{row['candidate_id']}",
            )
        for column, value in row.items():
            if column.endswith("sha256") and not _is_sha256(value):
                raise EvidenceContractError(f"invalid_sha256:row={row_number}:column={column}")
            if column.endswith("_path"):
                _check_path(value, f"row={row_number}:column={column}")


def read_split_manifest(path: Path) -> tuple[list[dict[str, str]], str]:
    _check_path(str(path.resolve()), "split_manifest")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    if not rows:
        raise EvidenceContractError("empty_split_manifest")
    levels = {row.get("split_level", "") for row in rows}
    if len(levels) != 1 or next(iter(levels)) not in {"outer", "inner"}:
        raise EvidenceContractError("invalid_split_manifest_level")
    level = next(iter(levels))
    expected_schema = (
        CANONICAL_INNER_SPLIT_SCHEMA if level == "inner" else CANONICAL_OUTER_SPLIT_SCHEMA
    )
    for row in rows:
        if row.get("schema_version") != expected_schema:
            raise EvidenceContractError("noncanonical_split_schema")
        if row.get("builder_version") != CANONICAL_SPLIT_BUILDER:
            raise EvidenceContractError("noncanonical_split_builder")
        if row.get("input_table_sha256") != CANONICAL_V2_4_LABEL_TABLE_SHA256:
            raise EvidenceContractError("split_not_based_on_current_v2_4_labels")
    observed_sha = sha256_file(path)
    expected_sha = CANONICAL_INNER_SPLIT_SHA256 if level == "inner" else CANONICAL_OUTER_SPLIT_SHA256
    if observed_sha != expected_sha:
        raise EvidenceContractError(f"noncanonical_split_manifest_sha:{level}:{observed_sha}")
    return rows, level


def load_provenance(path: Path) -> dict[str, Any]:
    _check_path(str(path.resolve()), "component_provenance")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        raise EvidenceContractError("provenance_schema_mismatch")
    for section in ("m2_components", "neural_components", "contact_components", "meta_models"):
        if not isinstance(data.get(section), dict):
            raise EvidenceContractError(f"missing_provenance_section:{section}")
    return data


def validate_contact_formula(path: Path, expected_sha: str) -> None:
    _check_path(str(path.resolve()), "contact_formula")
    if sha256_file(path) != expected_sha:
        raise EvidenceContractError("contact_formula_receipt_mismatch")
    formula = json.loads(path.read_text(encoding="utf-8"))
    if formula.get("formula_version") != CONTACT_FORMULA_VERSION:
        raise EvidenceContractError("contact_formula_version_mismatch")
    if formula.get("weights") != {"hotspot_contact_mass": 0.5, "interface_specificity": 0.5}:
        raise EvidenceContractError("contact_formula_weights_mismatch")
    if formula.get("outer_result_tuning") is not False or formula.get("label_access") is not False:
        raise EvidenceContractError("contact_formula_label_access")


def _parent_set_from_receipt(
    section: Mapping[str, Any], receipt_sha: str, context: str
) -> tuple[set[str], Mapping[str, Any]]:
    block = section.get(receipt_sha)
    if not isinstance(block, dict):
        raise EvidenceContractError(f"unknown_component_receipt:{context}:{receipt_sha}")
    parents_raw = block.get("training_parent_framework_clusters")
    if not isinstance(parents_raw, list) or not parents_raw:
        raise EvidenceContractError(f"missing_component_training_parents:{context}")
    parents = {str(value) for value in parents_raw}
    if len(parents) != len(parents_raw):
        raise EvidenceContractError(f"duplicate_component_training_parent:{context}")
    digest = canonical_parent_set_sha256(parents)
    if block.get("training_parent_set_sha256") != digest:
        raise EvidenceContractError(f"component_parent_digest_mismatch:{context}")
    _check_path(str(block.get("artifact_path", "")), f"component:{context}")
    return parents, block


def _split_index(
    split_rows: Sequence[Mapping[str, str]], split_level: str
) -> dict[tuple[str, ...], Mapping[str, str]]:
    index: dict[tuple[str, ...], Mapping[str, str]] = {}
    for row in split_rows:
        key = (
            (row["outer_fold"], row["inner_fold"], row["candidate_id"])
            if split_level == "inner"
            else (row["outer_fold"], row["candidate_id"])
        )
        if key in index:
            raise EvidenceContractError(f"duplicate_split_key:{key}")
        index[key] = row
    return index


def _validate_meta_fit_evidence(
    block: Mapping[str, Any], row: Mapping[str, str], split_train_digest: str
) -> set[str]:
    fit_path = Path(str(block.get("fit_inner_oof_evidence_path", "")))
    _check_path(str(fit_path), f"meta_fit_inner_oof:{row['candidate_id']}")
    if not fit_path.is_file():
        raise EvidenceContractError(f"meta_fit_inner_oof_missing:{row['candidate_id']}")
    observed_sha = sha256_file(fit_path)
    expected_sha = str(block.get("fit_inner_oof_evidence_sha256", ""))
    if observed_sha != expected_sha:
        raise EvidenceContractError(f"meta_fit_inner_oof_hash_mismatch:{row['candidate_id']}")
    if row["fit_inner_oof_evidence_path"] != str(fit_path) or row["fit_inner_oof_evidence_sha256"] != observed_sha:
        raise EvidenceContractError(f"meta_row_fit_inner_oof_binding_mismatch:{row['candidate_id']}")

    parents_raw = block.get("fit_inner_oof_parent_framework_clusters")
    if not isinstance(parents_raw, list) or not parents_raw:
        raise EvidenceContractError(f"meta_fit_inner_oof_parent_list_missing:{row['candidate_id']}")
    declared_parents = {str(value) for value in parents_raw}
    declared_digest = canonical_parent_set_sha256(declared_parents)
    if (
        block.get("fit_inner_oof_parent_set_sha256") != declared_digest
        or row["fit_inner_oof_parent_set_sha256"] != declared_digest
        or declared_digest != split_train_digest
    ):
        raise EvidenceContractError(f"meta_fit_inner_oof_parent_closure_mismatch:{row['candidate_id']}")

    with fit_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fit_rows = list(reader)
        if tuple(reader.fieldnames or ()) != BASE_COLUMNS:
            raise EvidenceContractError(f"meta_fit_inner_oof_schema_mismatch:{row['candidate_id']}")
    if not fit_rows:
        raise EvidenceContractError(f"meta_fit_inner_oof_empty:{row['candidate_id']}")
    observed_parents: set[str] = set()
    seen_candidates: set[str] = set()
    for fit_row in fit_rows:
        if fit_row.get("evidence_role") != INNER_OOF_BASE_FEATURE:
            raise EvidenceContractError(f"meta_fit_uses_non_inner_oof_evidence:{row['candidate_id']}")
        if fit_row.get("outer_fold") != row["outer_fold"]:
            raise EvidenceContractError(f"meta_fit_inner_oof_outer_fold_mismatch:{row['candidate_id']}")
        parent = str(fit_row.get("parent_framework_cluster", ""))
        candidate = str(fit_row.get("candidate_id", ""))
        if not parent or not candidate or candidate in seen_candidates:
            raise EvidenceContractError(f"meta_fit_inner_oof_identity_failure:{row['candidate_id']}")
        observed_parents.add(parent)
        seen_candidates.add(candidate)
    if observed_parents != declared_parents:
        raise EvidenceContractError(f"meta_fit_inner_oof_observed_parent_closure_mismatch:{row['candidate_id']}")
    return declared_parents


def _validate_outer_base_feature_evidence(row: Mapping[str, str]) -> None:
    outer_base_path = Path(row["outer_base_feature_evidence_path"])
    if not outer_base_path.is_file():
        raise EvidenceContractError(
            f"outer_base_feature_evidence_missing:{row['candidate_id']}"
        )
    if sha256_file(outer_base_path) != row["outer_base_feature_evidence_sha256"]:
        raise EvidenceContractError(
            f"outer_base_feature_evidence_hash_mismatch:{row['candidate_id']}"
        )
    with outer_base_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        base_rows = list(reader)
        if tuple(reader.fieldnames or ()) != BASE_COLUMNS:
            raise EvidenceContractError(
                f"outer_base_feature_evidence_schema_mismatch:{row['candidate_id']}"
            )
    matches = [base for base in base_rows if base.get("candidate_id") == row["candidate_id"]]
    if len(matches) != 1:
        raise EvidenceContractError(
            f"outer_base_feature_candidate_closure_failure:{row['candidate_id']}"
        )
    base = matches[0]
    if base.get("evidence_role") != OUTER_TEST_BASE_FEATURE:
        raise EvidenceContractError(
            f"outer_base_feature_role_mismatch:{row['candidate_id']}"
        )
    for column in (
        "teacher_source",
        "parent_framework_cluster",
        "outer_fold",
        "split_train_parent_set_sha256",
        "split_score_parent_set_sha256",
    ):
        if base.get(column) != row[column]:
            raise EvidenceContractError(
                f"outer_base_feature_identity_mismatch:{row['candidate_id']}:{column}"
            )


def validate_against_split_and_provenance(
    rows: Sequence[Mapping[str, str]],
    role: str,
    split_rows: Sequence[Mapping[str, str]],
    split_level: str,
    split_manifest_path: Path,
    provenance: Mapping[str, Any],
    contact_formula_path: Path,
    enforce_canonical_split_sha: bool = True,
) -> dict[str, Any]:
    expected_level = "inner" if role == INNER_OOF_BASE_FEATURE else "outer"
    if split_level != expected_level:
        raise EvidenceContractError(f"split_level_role_mismatch:{role}:{split_level}")
    split_sha = sha256_file(split_manifest_path)
    expected_split_sha = (
        CANONICAL_INNER_SPLIT_SHA256 if split_level == "inner" else CANONICAL_OUTER_SPLIT_SHA256
    )
    if enforce_canonical_split_sha and split_sha != expected_split_sha:
        raise EvidenceContractError(
            f"noncanonical_split_manifest_sha:{split_level}:{split_sha}"
        )
    split_path = str(split_manifest_path.resolve())
    formula_sha = sha256_file(contact_formula_path)
    validate_contact_formula(contact_formula_path, formula_sha)
    index = _split_index(split_rows, split_level)

    for row in rows:
        key = (
            (row["outer_fold"], row["inner_fold"], row["candidate_id"])
            if split_level == "inner"
            else (row["outer_fold"], row["candidate_id"])
        )
        split = index.get(key)
        if split is None:
            raise EvidenceContractError(f"candidate_missing_from_split:{key}")
        if split.get("candidate_role") != "score":
            raise EvidenceContractError(f"evidence_candidate_not_split_score:{key}")
        for column in ("teacher_source", "parent_framework_cluster"):
            if split.get(column) != row[column]:
                raise EvidenceContractError(f"split_identity_mismatch:{key}:{column}")
        if row["split_manifest_path"] != split_path or row["split_manifest_sha256"] != split_sha:
            raise EvidenceContractError(f"split_artifact_binding_mismatch:{key}")
        for digest_column in ("train_parent_set_sha256", "score_parent_set_sha256"):
            row_column = f"split_{digest_column}"
            if row[row_column] != split[digest_column]:
                raise EvidenceContractError(f"split_parent_digest_binding_mismatch:{key}:{digest_column}")
        split_train_digest = split["train_parent_set_sha256"]

        if role in BASE_ROLES:
            component_contracts = (
                ("M2", "m2_components", "M2_component_receipt_sha256", "M2_training_parent_set_sha256", "M2_artifact_path"),
                ("neural", "neural_components", "neural_component_receipt_sha256", "neural_training_parent_set_sha256", "neural_checkpoint_path"),
                ("contact", "contact_components", "contact_component_receipt_sha256", "contact_training_parent_set_sha256", "contact_checkpoint_path"),
            )
            component_blocks: dict[str, Mapping[str, Any]] = {}
            for name, section_name, receipt_column, digest_column, path_column in component_contracts:
                parents, block = _parent_set_from_receipt(
                    provenance[section_name], row[receipt_column], f"{name}:{row['candidate_id']}"
                )
                component_blocks[name] = block
                if row[digest_column] != split_train_digest or block["training_parent_set_sha256"] != split_train_digest:
                    raise EvidenceContractError(
                        f"component_training_parents_not_split_train:{name}:{row['candidate_id']}"
                    )
                if row["parent_framework_cluster"] in parents:
                    raise EvidenceContractError(f"in_sample_component_parent:{name}:{row['candidate_id']}")
                if row[path_column] != block["artifact_path"]:
                    raise EvidenceContractError(f"component_path_mismatch:{name}:{row['candidate_id']}")
                if str(block.get("outer_fold")) != row["outer_fold"] or str(block.get("inner_fold")) != row["inner_fold"]:
                    raise EvidenceContractError(f"component_fold_mismatch:{name}:{row['candidate_id']}")
            if row["neural_component_receipt_sha256"] == row["contact_component_receipt_sha256"]:
                if (
                    component_blocks["neural"]["artifact_path"] != component_blocks["contact"]["artifact_path"]
                    or component_blocks["neural"]["training_parent_set_sha256"]
                    != component_blocks["contact"]["training_parent_set_sha256"]
                ):
                    raise EvidenceContractError(f"shared_neural_contact_checkpoint_mismatch:{row['candidate_id']}")
            if row["contact_formula_receipt_sha256"] != formula_sha:
                raise EvidenceContractError(f"contact_formula_row_receipt_mismatch:{row['candidate_id']}")
            if row["contact_formula_artifact_path"] != str(contact_formula_path.resolve()):
                raise EvidenceContractError(f"contact_formula_path_mismatch:{row['candidate_id']}")
        else:
            _validate_outer_base_feature_evidence(row)
            parents, block = _parent_set_from_receipt(
                provenance["meta_models"], row["meta_model_receipt_sha256"],
                f"meta:{row['candidate_id']}",
            )
            if row["meta_training_parent_set_sha256"] != split_train_digest or block["training_parent_set_sha256"] != split_train_digest:
                raise EvidenceContractError(f"meta_training_parents_not_split_train:{row['candidate_id']}")
            fit_oof_parents = _validate_meta_fit_evidence(block, row, split_train_digest)
            scaling_parents_raw = block.get("scaling_fit_parent_framework_clusters")
            if not isinstance(scaling_parents_raw, list) or not scaling_parents_raw:
                raise EvidenceContractError(f"scaling_fit_parent_list_missing:{row['candidate_id']}")
            scaling_parents = {str(value) for value in scaling_parents_raw}
            scaling_digest = canonical_parent_set_sha256(scaling_parents)
            if (
                block.get("scaling_fit_parent_set_sha256") != scaling_digest
                or row["scaling_fit_parent_set_sha256"] != scaling_digest
                or scaling_digest != split_train_digest
                or scaling_parents != fit_oof_parents
            ):
                raise EvidenceContractError(f"scaling_fit_parents_not_split_train:{row['candidate_id']}")
            if (
                block.get("scaling_contract") != STACK_SCALING_CONTRACT
                or block.get("fixed_ridge_alpha") != STACK_RIDGE_ALPHA
                or block.get("fixed_condition_number_ceiling") != STACK_CONDITION_NUMBER_CEILING
                or block.get("parameter_count") != 5
                or block.get("shared_nonnegative_slopes") is not True
            ):
                raise EvidenceContractError(f"meta_numeric_contract_mismatch:{row['candidate_id']}")
            if row["parent_framework_cluster"] in parents:
                raise EvidenceContractError(f"in_sample_meta_parent:{row['candidate_id']}")
            if row["meta_model_artifact_path"] != block["artifact_path"]:
                raise EvidenceContractError(f"meta_model_path_mismatch:{row['candidate_id']}")
            if str(block.get("outer_fold")) != row["outer_fold"]:
                raise EvidenceContractError(f"meta_outer_fold_mismatch:{row['candidate_id']}")

    return {
        "status": "PASS_ROLE_SEPARATED_COMPONENT_CONTRACT",
        "evidence_role": role,
        "candidate_count": len(rows),
        "split_level": split_level,
        "split_manifest_sha256": split_sha,
        "contact_formula_receipt_sha256": formula_sha,
        "compact_feature_count": 6 if role in BASE_ROLES else 0,
        "meta_receipt_required": role == OUTER_TEST_META_PREDICTION,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    evidence_path = Path(args.evidence_tsv).resolve()
    split_path = Path(args.split_manifest_tsv).resolve()
    provenance_path = Path(args.provenance_json).resolve()
    formula_path = Path(args.contact_formula_json).resolve()
    report_path = Path(args.report_json).resolve()
    if report_path.exists():
        raise EvidenceContractError(f"report_already_exists:{report_path}")
    rows, role = read_evidence(evidence_path)
    split_rows, split_level = read_split_manifest(split_path)
    provenance = load_provenance(provenance_path)
    report = validate_against_split_and_provenance(
        rows, role, split_rows, split_level, split_path, provenance, formula_path
    )
    report.update({
        "evidence_tsv_sha256": sha256_file(evidence_path),
        "provenance_json_sha256": sha256_file(provenance_path),
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-tsv", required=True)
    parser.add_argument("--split-manifest-tsv", required=True)
    parser.add_argument("--provenance-json", required=True)
    parser.add_argument("--contact-formula-json", required=True)
    parser.add_argument("--report-json", required=True)
    return parser


def main() -> int:
    print(json.dumps(run(build_parser().parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
