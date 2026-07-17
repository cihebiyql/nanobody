#!/usr/bin/env python3
"""Freeze the preregistered V4-G seen-parent 200-row acquisition panel (V2).

V2 supersedes the unexecuted V1 production contract.  It additionally binds the
independently verified Node1 7,087-row large-scale-fast census, excludes every
``fast_hard_fail=true`` candidate before acquisition ranking, and pre-reserves
the label-free hash control before every score-ranked bucket.  It has no CLI
argument for docking, prospective-test, V4-F, or experimental label files.
PASS and FAIL refer only to the frozen open-development model gate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
WORKSPACE_DIR = EXP_DIR.parents[1]
SCHEMA_VERSION = "phase2_v4_g_seen200_acquisition_selector_v2"
RECEIPT_VERSION = "phase2_v4_g_seen200_acquisition_receipt_v2"
IMPLEMENTATION_FREEZE_VERSION = "phase2_v4_g_seen200_selector_implementation_freeze_v2"
DEPLOYMENT_SCHEMA_VERSION = "phase2_v4_d_candidate_deployment_scoring_v1"
CENSUS_AUDIT_SCHEMA_VERSION = "candidate7087_node1_fastqc_census_audit_v1"
CENSUS_RECEIPT_SCHEMA_VERSION = "candidate7087_node1_fastqc_census_receipt_v1"
CENSUS_VERIFICATION_SCHEMA_VERSION = (
    "candidate7087_node1_large_scale_fast_census_independent_verification_v1"
)
SELECTION_SEED = "phase2_v4_g_seen200_acquisition_20260716"
MODEL_SPLIT = "V4_G_SEEN200_ACTIVE_LEARNING_ACQUISITION"
EXPECTED_POOL_ROWS = 7087
EXPECTED_V4D_ROWS = 290
EXPECTED_V4F_ROWS = 96
EXPECTED_SOURCE_PARENTS = 20
ROWS_PER_PARENT = 10
PASS_QUOTAS = (
    ("TOP_PREDICTION", 4),
    ("UNCERTAINTY", 3),
    ("MODEL_DISAGREEMENT", 2),
    ("LABEL_FREE_HASH_CONTROL", 1),
)
FAIL_QUOTAS = (
    ("LABEL_FREE_DIVERSITY_REPLACING_TOP", 4),
    ("UNCERTAINTY", 3),
    ("MODEL_DISAGREEMENT", 2),
    ("LABEL_FREE_HASH_CONTROL", 1),
)
CLAIM_BOUNDARY = (
    "Active-learning acquisition for a fixed-PVRIG sequence surrogate of independent "
    "dual-receptor docking geometry. Selection is not docking, binding, affinity, "
    "competition, Docking Gold, experimental blocking, or final-submission evidence."
)

DEFAULT_POOL = (
    EXP_DIR
    / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate/fast_gate_formal_eligible_v1.csv"
)
DEFAULT_SCORES = (
    EXP_DIR / "runs/pvrig_v4_d_deployment_scoring_v1/candidate7087_deployment_scores.tsv"
)
DEFAULT_SCORE_SUMMARY = DEFAULT_SCORES.with_name("candidate7087_deployment_summary.json")
DEFAULT_SCORE_RECEIPT = DEFAULT_SCORES.with_name("candidate7087_deployment_receipt.json")
DEFAULT_V4D = EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
DEFAULT_V4F = EXP_DIR / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv"
DEFAULT_RESERVE = EXP_DIR / "data_splits/pvrig_v4_g/untouched_reserve2_parents.tsv"
DEFAULT_CALIBRATION_EXCLUSIONS = (
    EXP_DIR / "data_splits/pvrig_v4_g/known_calibration_sequence_exclusions_v1.tsv"
)
DEFAULT_PARENT_PREREGISTRATION = (
    EXP_DIR / "data_splits/pvrig_v4_g/phase2_v4_g_active_learning_preregistration.json"
)
DEFAULT_SELECTOR_V2_PREREGISTRATION = (
    EXP_DIR / "audits/phase2_v4_g_seen200_selector_v2_preregistration.json"
)
DEFAULT_CENSUS_DIR = (
    WORKSPACE_DIR
    / "reports/pvrig_candidate7087_node1_fastqc_census_v1_20260716/runtime_evidence"
)
DEFAULT_CENSUS = DEFAULT_CENSUS_DIR / "candidate7087_node1_fastqc_census_v1.tsv"
DEFAULT_CENSUS_RECEIPT = (
    DEFAULT_CENSUS_DIR / "candidate7087_node1_fastqc_census_v1.receipt.json"
)
DEFAULT_CENSUS_AUDIT = (
    DEFAULT_CENSUS_DIR / "candidate7087_node1_fastqc_census_v1.audit.json"
)
DEFAULT_CENSUS_INDEPENDENT_VERIFICATION = (
    DEFAULT_CENSUS_DIR.parent / "INDEPENDENT_VERIFICATION.json"
)
DEFAULT_IMPLEMENTATION_FREEZE = (
    EXP_DIR / "audits/phase2_v4_g_seen200_selector_implementation_freeze_v2.json"
)
DEFAULT_OUTPUT_DIR = EXP_DIR / "data_splits/pvrig_v4_g/seen200_acquisition_v2"

EXPECTED_PRODUCTION_HASHES = {
    "candidate_pool": "a92da7c939bf008ffaf7f3a305871477f74466d64f3489e9941c34a61a620e07",
    "v4d_manifest": "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd",
    "v4f_manifest": "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334",
    "reserve2_manifest": "98c11e8f72d97d60c9e772fa2bb256622f1ed6e1e9fddd9e136a8cd42959bb75",
    "parent_preregistration": "1ba6ecb0e5541516649c9d3c8dc30c82f411f3c5296e0e04681486bd9441bf55",
    "selector_v2_preregistration": "fd16954a0bc757d805e2e9d0f67f42eb832af444d2b0d353769e126e7f697148",
    "calibration_exclusions": "cba42df8ad9fab0399eb8a7d8608397fdf85aeea6619e2993e46d12d31dbd7d4",
    "node1_fastqc_census": "33c657fa26b3348d46fb22ebea453398b81d8fd762765668a1ca6c5dd3e16855",
    "node1_fastqc_census_receipt": "95a805622e9fd19e42e9999e7a421d8f91ac3c594a06a8ab21088ce84fdd3497",
    "node1_fastqc_census_audit": "360a4a1c657839b379af1f340d25471c1c66ffc6de4d096faf0c6dc98e6cd61f",
    "node1_fastqc_census_independent_verification": "77f7c188998f3b9d68c7ac46d8e9e3c311d523c41575bcb3c5cfe3226a762e65",
}

OUTPUT_FILENAMES = (
    "seen200_acquisition_v2_manifest.tsv",
    "seen200_acquisition_v2_audit.json",
    "seen200_acquisition_v2_receipt.json",
)
MANIFEST_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
    "cdr3_length",
    "model_split",
    "model_open_gate_branch",
    "selection_bucket",
    "selection_rank_in_parent_bucket",
    "selection_metric_name",
    "selection_metric_value",
    "consensus_prediction",
    "ensemble_uncertainty",
    "model_disagreement",
    "v4d_support_domain",
    "selection_hash",
    "full_qc_and_docking_policy",
    "claim_boundary",
)

POOL_REQUIRED_FIELDS = {
    "candidate_id",
    "vhh_sequence",
    "sequence_sha256",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1_after",
    "cdr2_after",
    "cdr3_after",
    "cdr3_length",
    "fast_gate_tier",
    "hard_fail",
}
CENSUS_FIELDS = {
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "fast_hard_fail",
    "reason_summary",
    "official_validator_failed_reason",
    "census_role",
}
DEPLOYMENT_SCORE_FIELDS = {
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "v4d_support_domain",
    "v4d_support_domain_reason",
    "scoring_governance",
    "model_scoring_permitted",
    "support_release_all_gates_passed",
    "model_open_gates_passed",
    "deployment_route",
    "exploitation_eligible",
    "portfolio_diversity_required",
    "base_model",
    "base_prediction",
    "base_ensemble_uncertainty",
    "embedding_model",
    "embedding_prediction",
    "embedding_ensemble_uncertainty",
    "contact_model",
    "contact_prediction",
    "contact_ensemble_uncertainty",
    "consensus_prediction",
    "ensemble_uncertainty",
    "model_disagreement",
    "exploration_priority",
    "exploitation_rank",
    "exploration_rank",
    "claim_boundary",
}
FORBIDDEN_FIELD_TOKENS = (
    "r_dual",
    "r_8x6b",
    "r_9e6y",
    "target_r_",
    "target_geometry",
    "target_label",
    "docking_label",
    "haddock_score",
    "experimental_binding",
    "experimental_blocking",
    "assay_",
    "kd_",
    "ic50",
    "ec50",
    "v4f_label",
    "prospective_test_label",
)
SAFE_POLICY_FIELDS = {
    "new_dual_docking_label_policy",
    "full_qc_and_docking_policy",
}
NO_SCORE_GOVERNANCE = {
    "UNTOUCHED_RESERVE_NO_SCORE",
    "PROSPECTIVE_V4_F_SEPARATE_FREEZER_NO_SCORE",
    "MODEL_DEVELOPMENT_OR_CHALLENGE_EXCLUDED_NO_SCORE",
}
PREDICTION_FIELDS = (
    "base_model",
    "base_prediction",
    "base_ensemble_uncertainty",
    "embedding_model",
    "embedding_prediction",
    "embedding_ensemble_uncertainty",
    "contact_model",
    "contact_prediction",
    "contact_ensemble_uncertainty",
    "consensus_prediction",
    "ensemble_uncertainty",
    "model_disagreement",
)


class Seen200SelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    payload: bytes
    sha256: str
    size_bytes: int


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "ascii"
        )
    )


def stable_hash(*parts: str) -> str:
    return sha256_bytes("|".join(parts).encode("utf-8"))


def snapshot_file(path: Path) -> FileSnapshot:
    resolved = path.expanduser().resolve()
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise Seen200SelectionError(f"input_missing_or_unreadable:{resolved}") from exc
    return FileSnapshot(resolved, payload, sha256_bytes(payload), len(payload))


def read_table(
    snapshot: FileSnapshot, delimiter: str
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    try:
        text = snapshot.payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Seen200SelectionError(f"invalid_table_encoding:{snapshot.path}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    return list(reader), tuple(reader.fieldnames or ())


def read_json(snapshot: FileSnapshot) -> dict[str, Any]:
    try:
        payload = json.loads(snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Seen200SelectionError(f"invalid_json:{snapshot.path}") from exc
    if not isinstance(payload, dict):
        raise Seen200SelectionError(f"json_not_object:{snapshot.path}")
    return payload


def require_fields(fields: Sequence[str], required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(fields))
    if missing:
        raise Seen200SelectionError(f"missing_fields:{label}:{','.join(missing)}")


def reject_forbidden_fields(fields: Sequence[str], label: str) -> None:
    forbidden = sorted(
        field
        for field in fields
        if field not in SAFE_POLICY_FIELDS
        if any(token in field.strip().lower() for token in FORBIDDEN_FIELD_TOKENS)
    )
    if forbidden:
        raise Seen200SelectionError(
            f"forbidden_label_fields:{label}:{','.join(forbidden)}"
        )


def parse_bool(value: Any, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise Seen200SelectionError(f"invalid_boolean:{field}:{value}")


def finite_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise Seen200SelectionError(f"invalid_float:{field}:{value}") from exc
    if not math.isfinite(output):
        raise Seen200SelectionError(f"non_finite_float:{field}")
    return output


def normalize_sequence(value: str, field: str) -> str:
    sequence = str(value).strip().upper()
    if not sequence or any(residue not in "ACDEFGHIKLMNPQRSTVWY" for residue in sequence):
        raise Seen200SelectionError(f"invalid_standard_amino_acid_sequence:{field}")
    return sequence


def sequence_hash(sequence: str) -> str:
    return sha256_bytes(sequence.encode("ascii"))


def validate_pool(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[str],
    *,
    expected_rows: int,
) -> list[dict[str, str]]:
    require_fields(fields, POOL_REQUIRED_FIELDS, "candidate_pool")
    reject_forbidden_fields(fields, "candidate_pool")
    if len(rows) != expected_rows:
        raise Seen200SelectionError(f"candidate_pool_row_count:{len(rows)}")
    output: list[dict[str, str]] = []
    candidate_ids: set[str] = set()
    sequence_hashes: set[str] = set()
    for source in rows:
        candidate_id = str(source["candidate_id"]).strip()
        if not candidate_id or candidate_id in candidate_ids:
            raise Seen200SelectionError(f"duplicate_or_empty_candidate_id:{candidate_id}")
        candidate_ids.add(candidate_id)
        sequence = normalize_sequence(source["vhh_sequence"], f"sequence:{candidate_id}")
        digest = str(source["sequence_sha256"]).strip().lower()
        if digest != sequence_hash(sequence):
            raise Seen200SelectionError(f"candidate_sequence_hash_mismatch:{candidate_id}")
        if digest in sequence_hashes:
            raise Seen200SelectionError(f"duplicate_candidate_sequence:{digest}")
        sequence_hashes.add(digest)
        if str(source["fast_gate_tier"]).strip() != "FORMAL_ELIGIBLE" or parse_bool(
            source["hard_fail"], f"hard_fail:{candidate_id}"
        ):
            raise Seen200SelectionError(f"candidate_not_formal_eligible:{candidate_id}")
        cdr1 = normalize_sequence(source["cdr1_after"], f"cdr1:{candidate_id}")
        cdr2 = normalize_sequence(source["cdr2_after"], f"cdr2:{candidate_id}")
        cdr3 = normalize_sequence(source["cdr3_after"], f"cdr3:{candidate_id}")
        try:
            cdr3_length = int(source["cdr3_length"])
        except ValueError as exc:
            raise Seen200SelectionError(f"invalid_cdr3_length:{candidate_id}") from exc
        if cdr3_length != len(cdr3):
            raise Seen200SelectionError(f"cdr3_length_mismatch:{candidate_id}")
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": digest,
                "sequence": sequence,
                "parent_id": str(source["parent_id"]).strip(),
                "parent_framework_cluster": str(source["parent_framework_cluster"]).strip(),
                "design_method": str(source["design_method"]).strip(),
                "design_mode": str(source["design_mode"]).strip(),
                "target_patch_id": str(source["target_patch_id"]).strip(),
                "cdr1": cdr1,
                "cdr2": cdr2,
                "cdr3": cdr3,
                "cdr3_length": str(cdr3_length),
            }
        )
    return output


def _require_zero_label_access(payload: Mapping[str, Any], label: str) -> None:
    expected_fields = {
        "docking",
        "experimental",
        "model_score",
        "v4_d_geometry",
        "v4_f_labels",
    }
    access = payload.get("label_path_access")
    if not isinstance(access, dict) or set(access) != expected_fields:
        raise Seen200SelectionError(f"{label}_label_path_access_field_set_mismatch")
    if any(type(value) is not int or value != 0 for value in access.values()):
        raise Seen200SelectionError(f"{label}_label_path_access_nonzero")


def _named_hash(mapping: Any, filename: str, label: str) -> str:
    if not isinstance(mapping, dict):
        raise Seen200SelectionError(f"{label}_hash_mapping_missing")
    matches = [str(value) for name, value in mapping.items() if Path(str(name)).name == filename]
    if len(matches) != 1:
        raise Seen200SelectionError(f"{label}_hash_binding_count:{filename}:{len(matches)}")
    digest = matches[0].strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise Seen200SelectionError(f"{label}_invalid_sha256:{filename}")
    return digest


def validate_node1_fastqc_census(
    census_snapshot: FileSnapshot,
    receipt_snapshot: FileSnapshot,
    audit_snapshot: FileSnapshot,
    verification_snapshot: FileSnapshot,
    *,
    expected_rows: int,
) -> dict[str, dict[str, Any]]:
    """Validate the independent Node1 census and return its identity/hard-gate map."""

    rows, fields = read_table(census_snapshot, "\t")
    if set(fields) != CENSUS_FIELDS:
        raise Seen200SelectionError("node1_fastqc_census_field_set_mismatch")
    if len(rows) != expected_rows:
        raise Seen200SelectionError(f"node1_fastqc_census_row_count:{len(rows)}")

    audit = read_json(audit_snapshot)
    receipt = read_json(receipt_snapshot)
    verification = read_json(verification_snapshot)
    if audit.get("schema_version") != CENSUS_AUDIT_SCHEMA_VERSION:
        raise Seen200SelectionError("node1_fastqc_census_audit_schema_mismatch")
    if audit.get("status") != "PASS_7087_FAST_QC_CENSUS_AUDIT":
        raise Seen200SelectionError("node1_fastqc_census_audit_status_mismatch")
    if receipt.get("schema_version") != CENSUS_RECEIPT_SCHEMA_VERSION:
        raise Seen200SelectionError("node1_fastqc_census_receipt_schema_mismatch")
    if receipt.get("status") != "PASS_7087_FAST_QC_CENSUS_READY_FOR_SUPPORT_V4_A_PLANNING":
        raise Seen200SelectionError("node1_fastqc_census_receipt_status_mismatch")
    if receipt.get("receipt_publication_order") != "LAST_AFTER_ALL_CLOSURE_GATES":
        raise Seen200SelectionError("node1_fastqc_census_receipt_not_published_last")
    if verification.get("schema_version") != CENSUS_VERIFICATION_SCHEMA_VERSION:
        raise Seen200SelectionError("node1_fastqc_census_verification_schema_mismatch")
    if verification.get("status") != "PASS_INDEPENDENT_LARGE_SCALE_FAST_CENSUS_VERIFICATION":
        raise Seen200SelectionError("node1_fastqc_census_verification_status_mismatch")
    _require_zero_label_access(audit, "node1_fastqc_census_audit")
    _require_zero_label_access(receipt, "node1_fastqc_census_receipt")

    if _named_hash(
        audit.get("outputs"), census_snapshot.path.name, "node1_fastqc_census_audit"
    ) != census_snapshot.sha256:
        raise Seen200SelectionError("node1_fastqc_census_audit_table_hash_mismatch")
    if _named_hash(
        receipt.get("output_sha256"),
        census_snapshot.path.name,
        "node1_fastqc_census_receipt",
    ) != census_snapshot.sha256:
        raise Seen200SelectionError("node1_fastqc_census_receipt_table_hash_mismatch")
    if _named_hash(
        receipt.get("output_sha256"),
        audit_snapshot.path.name,
        "node1_fastqc_census_receipt",
    ) != audit_snapshot.sha256:
        raise Seen200SelectionError("node1_fastqc_census_receipt_audit_hash_mismatch")
    if str(verification.get("candidate_table_sha256", "")).lower() != census_snapshot.sha256:
        raise Seen200SelectionError("node1_fastqc_census_verification_table_hash_mismatch")
    if str(verification.get("receipt_sha256", "")).lower() != receipt_snapshot.sha256:
        raise Seen200SelectionError("node1_fastqc_census_verification_receipt_hash_mismatch")
    verification_checks = verification.get("checks")
    if (
        not isinstance(verification_checks, dict)
        or not verification_checks
        or any(value is not True for value in verification_checks.values())
    ):
        raise Seen200SelectionError("node1_fastqc_census_verification_checks_not_all_true")

    output: dict[str, dict[str, Any]] = {}
    seen_hashes: set[str] = set()
    hard_fail_count = 0
    for source in rows:
        candidate_id = str(source["candidate_id"]).strip()
        digest = str(source["sequence_sha256"]).strip().lower()
        parent = str(source["parent_framework_cluster"]).strip()
        if not candidate_id or candidate_id in output:
            raise Seen200SelectionError("node1_fastqc_census_duplicate_or_empty_candidate_id")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise Seen200SelectionError(
                f"node1_fastqc_census_invalid_sequence_sha256:{candidate_id}"
            )
        if digest in seen_hashes:
            raise Seen200SelectionError("node1_fastqc_census_duplicate_sequence_sha256")
        if not parent:
            raise Seen200SelectionError(
                f"node1_fastqc_census_empty_parent_framework_cluster:{candidate_id}"
            )
        seen_hashes.add(digest)
        hard_fail = parse_bool(
            source["fast_hard_fail"], f"node1_fastqc_census_fast_hard_fail:{candidate_id}"
        )
        hard_fail_count += int(hard_fail)
        output[candidate_id] = {
            "candidate_id": candidate_id,
            "sequence_sha256": digest,
            "parent_framework_cluster": parent,
            "fast_hard_fail": hard_fail,
            "reason_summary": str(source["reason_summary"]).strip(),
            "official_validator_failed_reason": str(
                source["official_validator_failed_reason"]
            ).strip(),
            "census_role": str(source["census_role"]).strip(),
        }

    hard_pass_count = expected_rows - hard_fail_count
    for label, payload in (("audit", audit), ("receipt", receipt)):
        if int(payload.get("candidate_count", -1)) != expected_rows:
            raise Seen200SelectionError(f"node1_fastqc_census_{label}_candidate_count_mismatch")
        if int(payload.get("fast_hard_pass_count", -1)) != hard_pass_count:
            raise Seen200SelectionError(f"node1_fastqc_census_{label}_pass_count_mismatch")
        if int(payload.get("fast_hard_fail_count", -1)) != hard_fail_count:
            raise Seen200SelectionError(f"node1_fastqc_census_{label}_fail_count_mismatch")
        if payload.get("preregistration_sha256") != audit.get("preregistration_sha256"):
            raise Seen200SelectionError(
                f"node1_fastqc_census_{label}_preregistration_binding_mismatch"
            )
        if payload.get("runtime_manifest_sha256") != audit.get("runtime_manifest_sha256"):
            raise Seen200SelectionError(
                f"node1_fastqc_census_{label}_runtime_manifest_binding_mismatch"
            )
    results = verification.get("results")
    if not isinstance(results, dict):
        raise Seen200SelectionError("node1_fastqc_census_verification_results_missing")
    if int(results.get("fast_hard_pass", -1)) != hard_pass_count or int(
        results.get("fast_hard_fail", -1)
    ) != hard_fail_count:
        raise Seen200SelectionError("node1_fastqc_census_verification_counts_mismatch")
    return output


def validate_identity_reference(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[str],
    *,
    label: str,
    expected_rows: int,
) -> list[dict[str, str]]:
    required = {"candidate_id", "sequence_sha256", "parent_framework_cluster"}
    require_fields(fields, required, label)
    reject_forbidden_fields(fields, label)
    if len(rows) != expected_rows:
        raise Seen200SelectionError(f"{label}_row_count:{len(rows)}")
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in rows:
        candidate_id = str(source["candidate_id"]).strip()
        if not candidate_id or candidate_id in seen:
            raise Seen200SelectionError(f"{label}_duplicate_or_empty_candidate_id")
        seen.add(candidate_id)
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": str(source["sequence_sha256"]).strip().lower(),
                "parent_framework_cluster": str(source["parent_framework_cluster"]).strip(),
                "model_split": str(source.get("model_split", "")).strip(),
                "cdr1": str(source.get("cdr1", "")).strip().upper(),
                "cdr2": str(source.get("cdr2", "")).strip().upper(),
                "cdr3": str(source.get("cdr3", "")).strip().upper(),
            }
        )
    return output


def validate_calibration_exclusions(
    rows: Sequence[Mapping[str, str]], fields: Sequence[str]
) -> set[str]:
    allowed = {
        "sequence_sha256",
        "sequence",
        "calibration_aliases",
        "exclusion_role",
        "claim_boundary",
    }
    if set(fields) != allowed:
        raise Seen200SelectionError("calibration_exclusion_manifest_field_set_mismatch")
    hashes: set[str] = set()
    for source in rows:
        sequence = normalize_sequence(source["sequence"], "calibration_exclusion_sequence")
        digest = str(source["sequence_sha256"]).strip().lower()
        if digest != sequence_hash(sequence):
            raise Seen200SelectionError("calibration_exclusion_sequence_hash_mismatch")
        if digest in hashes:
            raise Seen200SelectionError("calibration_exclusion_duplicate_sequence")
        hashes.add(digest)
    if not hashes:
        raise Seen200SelectionError("calibration_exclusion_manifest_empty")
    return hashes


def validate_reserve(rows: Sequence[Mapping[str, str]], fields: Sequence[str]) -> set[str]:
    require_fields(fields, {"parent_framework_cluster", "selection_role"}, "reserve2")
    reject_forbidden_fields(fields, "reserve2")
    parents = {str(row["parent_framework_cluster"]).strip() for row in rows}
    if len(rows) != 2 or len(parents) != 2:
        raise Seen200SelectionError("reserve2_parent_count_mismatch")
    if any(str(row["selection_role"]).strip() != "UNTOUCHED_V4_G_RESERVE_PARENT" for row in rows):
        raise Seen200SelectionError("reserve2_role_mismatch")
    return parents


def find_bound_output_hash(receipt: Mapping[str, Any], filename: str) -> str:
    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        raise Seen200SelectionError("deployment_receipt_outputs_missing")
    matches = [str(value) for path, value in outputs.items() if Path(str(path)).name == filename]
    if len(matches) != 1:
        raise Seen200SelectionError(f"deployment_receipt_output_binding_count:{filename}")
    return matches[0]


def validate_no_sealed_label_access(payload: Mapping[str, Any], label: str) -> None:
    required_false = (
        "prospective_test_labels_read",
        "v4f_labels_read",
        "experimental_labels_read",
    )
    for field in required_false:
        if field not in payload or payload[field] is not False:
            raise Seen200SelectionError(f"{label}_{field}_not_false")
    required_zero = (
        "prospective_test_label_paths_accepted",
        "v4f_label_paths_accepted",
        "experimental_label_paths_accepted",
    )
    for field in required_zero:
        if field not in payload or type(payload[field]) is not int or payload[field] != 0:
            raise Seen200SelectionError(f"{label}_{field}_not_explicit_zero")


def validate_deployment_release(
    score_snapshot: FileSnapshot,
    summary_snapshot: FileSnapshot,
    receipt_snapshot: FileSnapshot,
    *,
    expected_rows: int,
    node1_fastqc_hard_fail_ids: set[str],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    summary = read_json(summary_snapshot)
    receipt = read_json(receipt_snapshot)
    if summary.get("schema_version") != DEPLOYMENT_SCHEMA_VERSION:
        raise Seen200SelectionError("deployment_summary_schema_mismatch")
    if receipt.get("schema_version") != DEPLOYMENT_SCHEMA_VERSION:
        raise Seen200SelectionError("deployment_receipt_schema_mismatch")
    if summary.get("status") not in {
        "PASS_DEPLOYMENT_SCORES_ROUTED",
        "PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED",
    }:
        raise Seen200SelectionError("deployment_summary_status_not_complete")
    if receipt.get("status") != "PASS_DEPLOYMENT_SCORING_HASH_CLOSURE":
        raise Seen200SelectionError("deployment_receipt_status_not_complete")
    validate_no_sealed_label_access(summary, "deployment_summary")
    validate_no_sealed_label_access(receipt, "deployment_receipt")
    if find_bound_output_hash(receipt, score_snapshot.path.name) != score_snapshot.sha256:
        raise Seen200SelectionError("deployment_score_hash_mismatch")
    if find_bound_output_hash(receipt, summary_snapshot.path.name) != summary_snapshot.sha256:
        raise Seen200SelectionError("deployment_summary_hash_mismatch")
    rows, fields = read_table(score_snapshot, "\t")
    if set(fields) != DEPLOYMENT_SCORE_FIELDS:
        extras = sorted(set(fields) - DEPLOYMENT_SCORE_FIELDS)
        missing = sorted(DEPLOYMENT_SCORE_FIELDS - set(fields))
        raise Seen200SelectionError(
            f"deployment_score_field_set_mismatch:extra={','.join(extras)}:missing={','.join(missing)}"
        )
    if len(rows) != expected_rows or int(summary.get("candidate_count", -1)) != expected_rows:
        raise Seen200SelectionError(f"deployment_score_row_count:{len(rows)}")
    if int(receipt.get("candidate_count", -1)) != expected_rows:
        raise Seen200SelectionError("deployment_receipt_candidate_count_mismatch")
    model_gate_pass = summary.get("model_open_gates_all_passed")
    if not isinstance(model_gate_pass, bool):
        raise Seen200SelectionError("deployment_model_open_gate_missing")
    support_release = summary.get("support_release")
    if not isinstance(support_release, dict) or support_release.get("all_gates_passed") is not True:
        raise Seen200SelectionError("deployment_support_release_gate_not_pass")
    branch = "PASS" if model_gate_pass else "FAIL"
    output: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for source in rows:
        candidate_id = str(source["candidate_id"]).strip()
        digest = str(source["sequence_sha256"]).strip().lower()
        if not candidate_id or candidate_id in seen_ids:
            raise Seen200SelectionError("deployment_score_duplicate_or_empty_candidate_id")
        if digest in seen_hashes:
            raise Seen200SelectionError("deployment_score_duplicate_sequence")
        seen_ids.add(candidate_id)
        seen_hashes.add(digest)
        row_gate = parse_bool(source["model_open_gates_passed"], "model_open_gates_passed")
        if row_gate != model_gate_pass:
            raise Seen200SelectionError("deployment_score_model_gate_branch_mismatch")
        support_gate = parse_bool(
            source["support_release_all_gates_passed"], "support_release_all_gates_passed"
        )
        if not support_gate:
            raise Seen200SelectionError("deployment_score_support_gate_not_pass")
        scoring_permitted = parse_bool(source["model_scoring_permitted"], "model_scoring_permitted")
        governance = str(source["scoring_governance"]).strip()
        route = str(source["deployment_route"]).strip()
        exploitation_eligible = parse_bool(
            source["exploitation_eligible"], "exploitation_eligible"
        )
        if exploitation_eligible != (route == "EXPLOITATION"):
            raise Seen200SelectionError("deployment_exploitation_route_flag_mismatch")
        if branch == "FAIL" and exploitation_eligible:
            raise Seen200SelectionError("deployment_fail_branch_contains_exploitation")
        numeric: dict[str, float] = {}
        if scoring_permitted:
            if governance != "DEPLOYMENT_SCORING_ALLOWED":
                raise Seen200SelectionError("deployment_scoring_governance_mismatch")
            if candidate_id not in node1_fastqc_hard_fail_ids:
                for field in (
                    "consensus_prediction",
                    "ensemble_uncertainty",
                    "model_disagreement",
                ):
                    numeric[field] = finite_float(source[field], f"{field}:{candidate_id}")
        else:
            if governance not in NO_SCORE_GOVERNANCE or route != governance:
                raise Seen200SelectionError("deployment_no_score_governance_mismatch")
            if any(str(source[field]).strip() for field in PREDICTION_FIELDS):
                raise Seen200SelectionError("deployment_no_score_row_contains_prediction")
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": digest,
                "parent_framework_cluster": str(source["parent_framework_cluster"]).strip(),
                "design_method": str(source["design_method"]).strip(),
                "design_mode": str(source["design_mode"]).strip(),
                "target_patch_id": str(source["target_patch_id"]).strip(),
                "v4d_support_domain": str(source["v4d_support_domain"]).strip(),
                "scoring_governance": governance,
                "model_scoring_permitted": scoring_permitted,
                "deployment_route": route,
                "exploitation_eligible": exploitation_eligible,
                **numeric,
            }
        )
    return output, branch, summary


def validate_parent_preregistration(
    payload: Mapping[str, Any], *, expected_source_parents: int
) -> list[str]:
    if payload.get("status") != "FROZEN_LABEL_FREE_BEFORE_V4D_OPEN_TEACHER_OR_V4F_DOCKING_LABELS":
        raise Seen200SelectionError("parent_preregistration_status_mismatch")
    future = payload.get("future_seen200")
    if not isinstance(future, dict):
        raise Seen200SelectionError("parent_preregistration_seen200_missing")
    parents = [str(value) for value in future.get("source_parent_clusters", [])]
    if len(parents) != expected_source_parents or len(set(parents)) != len(parents):
        raise Seen200SelectionError("parent_preregistration_source_parent_count_mismatch")
    if int(future.get("rows", -1)) != expected_source_parents * ROWS_PER_PARENT:
        raise Seen200SelectionError("parent_preregistration_row_count_mismatch")
    if int(future.get("rows_per_parent", -1)) != ROWS_PER_PARENT:
        raise Seen200SelectionError("parent_preregistration_rows_per_parent_mismatch")
    if future.get("model_open_gate_pass_quota_per_parent") != {
        "top": 4,
        "uncertainty": 3,
        "disagreement": 2,
        "control": 1,
    }:
        raise Seen200SelectionError("parent_preregistration_pass_quota_mismatch")
    if future.get("model_open_gate_fail_quota_per_parent") != {
        "label_free_diverse_replacing_top": 4,
        "uncertainty": 3,
        "disagreement": 2,
        "control": 1,
    }:
        raise Seen200SelectionError("parent_preregistration_fail_quota_mismatch")
    label_access = payload.get("label_access")
    if not isinstance(label_access, dict) or any(int(value) != 0 for value in label_access.values()):
        raise Seen200SelectionError("parent_preregistration_label_access_not_zero")
    return parents


def validate_selector_v2_preregistration(
    payload: Mapping[str, Any], source_parents: Sequence[str]
) -> None:
    claimed_hash = payload.get("preregistration_payload_sha256")
    hash_payload = dict(payload)
    hash_payload.pop("preregistration_payload_sha256", None)
    if not isinstance(claimed_hash, str) or sha256_json(hash_payload) != claimed_hash:
        raise Seen200SelectionError("selector_v2_preregistration_payload_hash_mismatch")
    if payload.get("schema_version") != "phase2_v4_g_seen200_selector_v2_preregistration_v1":
        raise Seen200SelectionError("selector_v2_preregistration_schema_mismatch")
    if payload.get("status") != "FROZEN_V2_SUPERSEDING_V1_PREPRODUCTION_BLOCKERS_NO_SELECTION":
        raise Seen200SelectionError("selector_v2_preregistration_status_mismatch")
    if payload.get("production_selection_executed") is not False or int(
        payload.get("production_outputs_created", -1)
    ) != 0:
        raise Seen200SelectionError("selector_v2_preregistration_selection_state_mismatch")
    access = payload.get("label_access")
    if not isinstance(access, dict) or not access or any(
        type(value) is not int or value != 0 for value in access.values()
    ):
        raise Seen200SelectionError("selector_v2_preregistration_label_access_not_zero")
    intent = payload.get("frozen_selection_intent")
    if not isinstance(intent, dict):
        raise Seen200SelectionError("selector_v2_preregistration_intent_missing")
    if list(intent.get("source_parent_clusters", [])) != list(source_parents):
        raise Seen200SelectionError("selector_v2_preregistration_parent_set_mismatch")
    if int(intent.get("rows_per_parent", -1)) != ROWS_PER_PARENT or int(
        intent.get("rows_total", -1)
    ) != len(source_parents) * ROWS_PER_PARENT:
        raise Seen200SelectionError("selector_v2_preregistration_row_quota_mismatch")


def validate_implementation_freeze(
    freeze: Mapping[str, Any],
    snapshots: Mapping[str, FileSnapshot],
    *,
    enforce_production_locks: bool,
) -> None:
    claimed_payload_hash = freeze.get("freeze_payload_sha256")
    if not isinstance(claimed_payload_hash, str):
        raise Seen200SelectionError("implementation_freeze_payload_hash_missing")
    hash_payload = dict(freeze)
    hash_payload.pop("freeze_payload_sha256", None)
    if sha256_json(hash_payload) != claimed_payload_hash:
        raise Seen200SelectionError("implementation_freeze_payload_hash_mismatch")
    if freeze.get("schema_version") != IMPLEMENTATION_FREEZE_VERSION:
        raise Seen200SelectionError("implementation_freeze_schema_mismatch")
    if freeze.get("status") != "FROZEN_V2_BEFORE_V4D_OPEN_MODEL_RESULTS_NO_SEEN200_SELECTION":
        raise Seen200SelectionError("implementation_freeze_status_mismatch")
    if freeze.get("production_selection_executed") is not False:
        raise Seen200SelectionError("implementation_freeze_claims_selection_executed")
    access = freeze.get("label_access")
    if not isinstance(access, dict) or any(int(value) != 0 for value in access.values()):
        raise Seen200SelectionError("implementation_freeze_label_access_not_zero")
    artifacts = freeze.get("artifacts")
    if not isinstance(artifacts, dict):
        raise Seen200SelectionError("implementation_freeze_artifacts_missing")
    expected = {
        "selector": sha256_file(Path(__file__)),
        "parent_preregistration": snapshots["parent_preregistration"].sha256,
        "selector_v2_preregistration": snapshots["selector_v2_preregistration"].sha256,
        "calibration_exclusions": snapshots["calibration_exclusions"].sha256,
        "node1_fastqc_census": snapshots["node1_fastqc_census"].sha256,
        "node1_fastqc_census_receipt": snapshots[
            "node1_fastqc_census_receipt"
        ].sha256,
        "node1_fastqc_census_audit": snapshots["node1_fastqc_census_audit"].sha256,
        "node1_fastqc_census_independent_verification": snapshots[
            "node1_fastqc_census_independent_verification"
        ].sha256,
    }
    for name, digest in expected.items():
        record = artifacts.get(name)
        if not isinstance(record, dict) or record.get("sha256") != digest:
            raise Seen200SelectionError(f"implementation_freeze_artifact_hash_mismatch:{name}")
    policy = freeze.get("selection_policy")
    if not isinstance(policy, dict):
        raise Seen200SelectionError("implementation_freeze_selection_policy_missing")
    if policy.get("pass_quota_order") != [[name, count] for name, count in PASS_QUOTAS]:
        raise Seen200SelectionError("implementation_freeze_pass_policy_mismatch")
    if policy.get("fail_quota_order") != [[name, count] for name, count in FAIL_QUOTAS]:
        raise Seen200SelectionError("implementation_freeze_fail_policy_mismatch")
    if policy.get("control_pre_reservation") != (
        "reserve_before_all_model_ranked_and_diversity_buckets"
    ):
        raise Seen200SelectionError("implementation_freeze_control_pre_reservation_mismatch")
    if enforce_production_locks:
        for artifact_name in ("tests", "test_log"):
            record = artifacts.get(artifact_name)
            if not isinstance(record, dict):
                raise Seen200SelectionError(
                    f"implementation_freeze_{artifact_name}_missing"
                )
            artifact_path = Path(str(record.get("path", "")))
            if not artifact_path.is_file() or sha256_file(artifact_path) != record.get(
                "sha256"
            ):
                raise Seen200SelectionError(
                    f"implementation_freeze_{artifact_name}_hash_mismatch"
                )
        evidence = freeze.get("test_evidence")
        if not isinstance(evidence, dict) or evidence.get("status") != "PASS" or int(
            evidence.get("tests_run", 0)
        ) < 8:
            raise Seen200SelectionError("implementation_freeze_test_evidence_insufficient")


def levenshtein_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_value in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_value != right_value),
                )
            )
        previous = current
    return previous[-1]


def normalized_cdr_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    values: list[float] = []
    for field in ("cdr1", "cdr2", "cdr3"):
        left_value = str(left[field])
        right_value = str(right[field])
        values.append(levenshtein_distance(left_value, right_value) / max(len(left_value), len(right_value)))
    return sum(values) / len(values)


def rank_metric(
    rows: Sequence[dict[str, Any]], metric: str, *, parent: str, bucket: str
) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -float(row[metric]),
            stable_hash(SELECTION_SEED, parent, bucket, row["candidate_id"], row["sequence_sha256"]),
            row["candidate_id"],
        ),
    )


def select_label_free_diverse(
    rows: Sequence[dict[str, Any]],
    anchors: Sequence[Mapping[str, Any]],
    *,
    parent: str,
    count: int,
) -> list[tuple[dict[str, Any], float]]:
    remaining = list(rows)
    selected: list[tuple[dict[str, Any], float]] = []
    live_anchors = [row for row in anchors if all(row.get(field) for field in ("cdr1", "cdr2", "cdr3"))]
    while len(selected) < count:
        if not remaining:
            raise Seen200SelectionError(f"insufficient_label_free_diversity_rows:{parent}")
        scored: list[tuple[float, str, str, dict[str, Any]]] = []
        for row in remaining:
            comparisons = [*live_anchors, *(item[0] for item in selected)]
            distance = (
                min(normalized_cdr_distance(row, anchor) for anchor in comparisons)
                if comparisons
                else 1.0
            )
            tie_hash = stable_hash(
                SELECTION_SEED,
                parent,
                "label_free_diversity",
                row["candidate_id"],
                row["sequence_sha256"],
            )
            scored.append((-distance, tie_hash, row["candidate_id"], row))
        neg_distance, _tie, _candidate, chosen = min(scored)
        selected.append((chosen, -neg_distance))
        remaining = [row for row in remaining if row["candidate_id"] != chosen["candidate_id"]]
    return selected


def select_seen200(
    eligible_rows: Sequence[dict[str, Any]],
    source_parents: Sequence[str],
    v4d_rows: Sequence[Mapping[str, str]],
    *,
    branch: str,
) -> list[dict[str, Any]]:
    quotas = PASS_QUOTAS if branch == "PASS" else FAIL_QUOTAS if branch == "FAIL" else None
    if quotas is None:
        raise Seen200SelectionError(f"unknown_model_gate_branch:{branch}")
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        by_parent[str(row["parent_framework_cluster"])].append(row)
    anchors_by_parent: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in v4d_rows:
        anchors_by_parent[str(row["parent_framework_cluster"])].append(row)
    selected: list[dict[str, Any]] = []
    for parent in source_parents:
        available = list(by_parent.get(parent, []))
        if len(available) < ROWS_PER_PARENT:
            raise Seen200SelectionError(f"insufficient_parent_candidates:{parent}:{len(available)}")
        control_count = dict(quotas).get("LABEL_FREE_HASH_CONTROL", 0)
        if control_count != 1:
            raise Seen200SelectionError("hash_control_quota_must_equal_one")
        control_ordered = sorted(
            available,
            key=lambda row: (
                stable_hash(
                    SELECTION_SEED,
                    parent,
                    "control",
                    row["candidate_id"],
                    row["sequence_sha256"],
                ),
                row["candidate_id"],
            ),
        )
        if len(control_ordered) < control_count:
            raise Seen200SelectionError(f"selection_bucket_shortage:{parent}:LABEL_FREE_HASH_CONTROL:0")
        reserved_control = control_ordered[:control_count]
        reserved_control_ids = {row["candidate_id"] for row in reserved_control}
        available = [row for row in available if row["candidate_id"] not in reserved_control_ids]
        bucket_selections: dict[str, tuple[list[tuple[dict[str, Any], float]], str]] = {
            "LABEL_FREE_HASH_CONTROL": (
                [(row, float("nan")) for row in reserved_control],
                "sha256_control_rank_ascending_prereserved",
            )
        }

        for bucket, count in quotas:
            if bucket == "LABEL_FREE_HASH_CONTROL":
                continue
            chosen_with_metric: list[tuple[dict[str, Any], float]]
            if bucket == "TOP_PREDICTION":
                exploitation_rows = [
                    row
                    for row in available
                    if row["deployment_route"] == "EXPLOITATION"
                    and row["exploitation_eligible"]
                ]
                chosen_with_metric = [
                    (row, float(row["consensus_prediction"]))
                    for row in rank_metric(
                        exploitation_rows,
                        "consensus_prediction",
                        parent=parent,
                        bucket=bucket,
                    )[:count]
                ]
                metric_name = "consensus_prediction_desc"
            elif bucket == "UNCERTAINTY":
                chosen_with_metric = [
                    (row, float(row["ensemble_uncertainty"]))
                    for row in rank_metric(
                        available, "ensemble_uncertainty", parent=parent, bucket=bucket
                    )[:count]
                ]
                metric_name = "ensemble_uncertainty_desc"
            elif bucket == "MODEL_DISAGREEMENT":
                chosen_with_metric = [
                    (row, float(row["model_disagreement"]))
                    for row in rank_metric(
                        available, "model_disagreement", parent=parent, bucket=bucket
                    )[:count]
                ]
                metric_name = "model_disagreement_desc"
            elif bucket == "LABEL_FREE_DIVERSITY_REPLACING_TOP":
                chosen_with_metric = select_label_free_diverse(
                    available, anchors_by_parent[parent], parent=parent, count=count
                )
                metric_name = "minimum_mean_normalized_cdr_levenshtein_distance_desc"
            else:
                raise Seen200SelectionError(f"unknown_selection_bucket:{bucket}")
            if len(chosen_with_metric) != count:
                raise Seen200SelectionError(
                    f"selection_bucket_shortage:{parent}:{bucket}:{len(chosen_with_metric)}"
                )
            bucket_selections[bucket] = (chosen_with_metric, metric_name)
            chosen_ids = {row["candidate_id"] for row, _metric in chosen_with_metric}
            available = [row for row in available if row["candidate_id"] not in chosen_ids]

        parent_selected: list[dict[str, Any]] = []
        for bucket, count in quotas:
            chosen_with_metric, metric_name = bucket_selections[bucket]
            if len(chosen_with_metric) != count:
                raise Seen200SelectionError(
                    f"selection_bucket_shortage:{parent}:{bucket}:{len(chosen_with_metric)}"
                )
            for rank, (source, metric_value) in enumerate(chosen_with_metric, start=1):
                selection_hash = stable_hash(
                    SELECTION_SEED,
                    branch,
                    parent,
                    bucket,
                    str(rank),
                    source["candidate_id"],
                    source["sequence_sha256"],
                )
                output = {
                    **{field: source[field] for field in MANIFEST_FIELDS[:12]},
                    "model_split": MODEL_SPLIT,
                    "model_open_gate_branch": branch,
                    "selection_bucket": bucket,
                    "selection_rank_in_parent_bucket": str(rank),
                    "selection_metric_name": metric_name,
                    "selection_metric_value": "" if math.isnan(metric_value) else f"{metric_value:.9f}",
                    "consensus_prediction": f"{float(source['consensus_prediction']):.9f}",
                    "ensemble_uncertainty": f"{float(source['ensemble_uncertainty']):.9f}",
                    "model_disagreement": f"{float(source['model_disagreement']):.9f}",
                    "v4d_support_domain": source["v4d_support_domain"],
                    "selection_hash": selection_hash,
                    "full_qc_and_docking_policy": (
                        "run_full_qc_on_all_200;dock_every_full_qc_hard_pass;"
                        "record_attrition;no_replacement"
                    ),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
                parent_selected.append(output)
        if len(parent_selected) != ROWS_PER_PARENT:
            raise Seen200SelectionError(f"parent_selection_count_mismatch:{parent}")
        selected.extend(parent_selected)
    return selected


def validate_selected(
    rows: Sequence[Mapping[str, Any]],
    source_parents: Sequence[str],
    *,
    branch: str,
    forbidden_candidate_ids: set[str],
    forbidden_sequence_hashes: set[str],
    reserve_parents: set[str],
    node1_fastqc_hard_fail_ids: set[str],
) -> dict[str, Any]:
    expected_rows = len(source_parents) * ROWS_PER_PARENT
    if len(rows) != expected_rows:
        raise Seen200SelectionError(f"seen200_row_count:{len(rows)}")
    ids = [str(row["candidate_id"]) for row in rows]
    hashes = [str(row["sequence_sha256"]) for row in rows]
    if len(set(ids)) != expected_rows or len(set(hashes)) != expected_rows:
        raise Seen200SelectionError("seen200_duplicate_candidate_or_sequence")
    if set(ids) & forbidden_candidate_ids:
        raise Seen200SelectionError("seen200_forbidden_candidate_overlap")
    if set(hashes) & forbidden_sequence_hashes:
        raise Seen200SelectionError("seen200_forbidden_sequence_overlap")
    if set(ids) & node1_fastqc_hard_fail_ids:
        raise Seen200SelectionError("seen200_node1_fastqc_hard_fail_overlap")
    selected_parents = {str(row["parent_framework_cluster"]) for row in rows}
    if selected_parents != set(source_parents):
        raise Seen200SelectionError("seen200_source_parent_set_mismatch")
    if selected_parents & reserve_parents:
        raise Seen200SelectionError("seen200_reserve_parent_overlap")
    parent_counts = Counter(str(row["parent_framework_cluster"]) for row in rows)
    if set(parent_counts.values()) != {ROWS_PER_PARENT}:
        raise Seen200SelectionError("seen200_parent_balance_failed")
    expected_quota = dict(PASS_QUOTAS if branch == "PASS" else FAIL_QUOTAS)
    bucket_counts_by_parent: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        bucket_counts_by_parent[str(row["parent_framework_cluster"])][
            str(row["selection_bucket"])
        ] += 1
    for parent, counts in bucket_counts_by_parent.items():
        if dict(counts) != expected_quota:
            raise Seen200SelectionError(f"seen200_quota_mismatch:{parent}:{dict(counts)}")
    return {
        "row_count": len(rows),
        "candidate_ids_unique": True,
        "sequences_unique": True,
        "model_open_gate_branch": branch,
        "parent_counts": dict(sorted(parent_counts.items())),
        "quota_per_parent": expected_quota,
        "forbidden_candidate_overlap": 0,
        "forbidden_sequence_overlap": 0,
        "reserve_parent_overlap": 0,
        "node1_fastqc_hard_fail_overlap": 0,
        "prospective_test_label_files_opened": 0,
        "v4f_label_files_opened": 0,
        "experimental_label_files_opened": 0,
    }


def tsv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def build_artifacts(
    paths: Mapping[str, Path],
    *,
    enforce_production_locks: bool = True,
    expected_pool_rows: int = EXPECTED_POOL_ROWS,
    expected_v4d_rows: int = EXPECTED_V4D_ROWS,
    expected_v4f_rows: int = EXPECTED_V4F_ROWS,
    expected_source_parents: int = EXPECTED_SOURCE_PARENTS,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    snapshots = {name: snapshot_file(path) for name, path in paths.items()}
    if enforce_production_locks:
        for name, expected in EXPECTED_PRODUCTION_HASHES.items():
            if snapshots[name].sha256 != expected:
                raise Seen200SelectionError(f"production_input_hash_mismatch:{name}")
    pool_raw, pool_fields = read_table(snapshots["candidate_pool"], ",")
    pool = validate_pool(pool_raw, pool_fields, expected_rows=expected_pool_rows)
    pool_by_id = {row["candidate_id"]: row for row in pool}
    census_by_id = validate_node1_fastqc_census(
        snapshots["node1_fastqc_census"],
        snapshots["node1_fastqc_census_receipt"],
        snapshots["node1_fastqc_census_audit"],
        snapshots["node1_fastqc_census_independent_verification"],
        expected_rows=expected_pool_rows,
    )
    if set(census_by_id) != set(pool_by_id):
        raise Seen200SelectionError("node1_fastqc_census_pool_candidate_bijection_failed")
    for candidate_id, pool_row in pool_by_id.items():
        census_row = census_by_id[candidate_id]
        for field in ("sequence_sha256", "parent_framework_cluster"):
            if census_row[field] != pool_row[field]:
                raise Seen200SelectionError(
                    f"node1_fastqc_census_pool_identity_mismatch:{candidate_id}:{field}"
                )
    node1_fastqc_hard_fail_ids = {
        candidate_id
        for candidate_id, census_row in census_by_id.items()
        if census_row["fast_hard_fail"]
    }
    v4d_raw, v4d_fields = read_table(snapshots["v4d_manifest"], "\t")
    v4d = validate_identity_reference(
        v4d_raw, v4d_fields, label="v4d_manifest", expected_rows=expected_v4d_rows
    )
    v4f_raw, v4f_fields = read_table(snapshots["v4f_manifest"], "\t")
    v4f = validate_identity_reference(
        v4f_raw, v4f_fields, label="v4f_manifest", expected_rows=expected_v4f_rows
    )
    for label, references in (("v4d_manifest", v4d), ("v4f_manifest", v4f)):
        for reference in references:
            candidate_id = reference["candidate_id"]
            pool_row = pool_by_id.get(candidate_id)
            if pool_row is None:
                raise Seen200SelectionError(f"{label}_candidate_not_in_pool:{candidate_id}")
            for field in ("sequence_sha256", "parent_framework_cluster"):
                if reference[field] != pool_row[field]:
                    raise Seen200SelectionError(
                        f"{label}_pool_identity_mismatch:{candidate_id}:{field}"
                    )
    if {row["candidate_id"] for row in v4d} & {row["candidate_id"] for row in v4f}:
        raise Seen200SelectionError("v4d_v4f_candidate_overlap")
    if {row["sequence_sha256"] for row in v4d} & {
        row["sequence_sha256"] for row in v4f
    }:
        raise Seen200SelectionError("v4d_v4f_sequence_overlap")
    reserve_raw, reserve_fields = read_table(snapshots["reserve2_manifest"], "\t")
    reserve_parents = validate_reserve(reserve_raw, reserve_fields)
    calibration_raw, calibration_fields = read_table(
        snapshots["calibration_exclusions"], "\t"
    )
    calibration_hashes = validate_calibration_exclusions(
        calibration_raw, calibration_fields
    )
    parent_prereg = read_json(snapshots["parent_preregistration"])
    source_parents = validate_parent_preregistration(
        parent_prereg, expected_source_parents=expected_source_parents
    )
    selector_v2_prereg = read_json(snapshots["selector_v2_preregistration"])
    validate_selector_v2_preregistration(selector_v2_prereg, source_parents)
    implementation_freeze = read_json(snapshots["implementation_freeze"])
    validate_implementation_freeze(
        implementation_freeze,
        snapshots,
        enforce_production_locks=enforce_production_locks,
    )
    scores, branch, deployment_summary = validate_deployment_release(
        snapshots["deployment_scores"],
        snapshots["deployment_summary"],
        snapshots["deployment_receipt"],
        expected_rows=expected_pool_rows,
        node1_fastqc_hard_fail_ids=node1_fastqc_hard_fail_ids,
    )
    if len(scores) != len(pool) or {row["candidate_id"] for row in scores} != set(pool_by_id):
        raise Seen200SelectionError("deployment_score_candidate_bijection_failed")
    scores_by_id = {row["candidate_id"]: row for row in scores}
    for candidate_id, pool_row in pool_by_id.items():
        score = scores_by_id[candidate_id]
        for field in (
            "sequence_sha256",
            "parent_framework_cluster",
            "design_method",
            "design_mode",
            "target_patch_id",
        ):
            if str(score[field]) != str(pool_row[field]):
                raise Seen200SelectionError(f"deployment_pool_identity_mismatch:{candidate_id}:{field}")
    open_train_parents = {
        row["parent_framework_cluster"] for row in v4d if row["model_split"] == "OPEN_TRAIN"
    }
    if open_train_parents != set(source_parents):
        raise Seen200SelectionError("v4d_open_train_parent_set_mismatch")
    forbidden_candidate_ids = {row["candidate_id"] for row in [*v4d, *v4f]}
    forbidden_sequence_hashes = {
        *(row["sequence_sha256"] for row in [*v4d, *v4f]),
        *calibration_hashes,
    }
    eligible: list[dict[str, Any]] = []
    for candidate_id, pool_row in pool_by_id.items():
        if pool_row["parent_framework_cluster"] not in set(source_parents):
            continue
        if pool_row["parent_framework_cluster"] in reserve_parents:
            continue
        if candidate_id in forbidden_candidate_ids or pool_row["sequence_sha256"] in forbidden_sequence_hashes:
            continue
        # Frozen V2 hard gate: reject Node1 Fast-QC hard failures before
        # consulting any model prediction, uncertainty, or disagreement value.
        if census_by_id[candidate_id]["fast_hard_fail"]:
            continue
        score = scores_by_id[candidate_id]
        if not score["model_scoring_permitted"]:
            continue
        eligible.append({**pool_row, **score})
    selected = select_seen200(eligible, source_parents, v4d, branch=branch)
    checks = validate_selected(
        selected,
        source_parents,
        branch=branch,
        forbidden_candidate_ids=forbidden_candidate_ids,
        forbidden_sequence_hashes=forbidden_sequence_hashes,
        reserve_parents=reserve_parents,
        node1_fastqc_hard_fail_ids=node1_fastqc_hard_fail_ids,
    )
    input_metadata = {
        name: {
            "path": str(snapshot.path),
            "sha256": snapshot.sha256,
            "size_bytes": snapshot.size_bytes,
        }
        for name, snapshot in snapshots.items()
    }
    input_closure = sha256_json(
        {name: {"sha256": row["sha256"], "size_bytes": row["size_bytes"]} for name, row in input_metadata.items()}
    )
    manifest_payload = tsv_bytes(selected, MANIFEST_FIELDS)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_SEEN200_ACQUISITION_FROZEN"
            if enforce_production_locks
            else "TEST_ONLY_PASS_SEEN200_ACQUISITION_FROZEN"
        ),
        "execution_mode": "production" if enforce_production_locks else "test_only",
        "claim_boundary": CLAIM_BOUNDARY,
        "selection_seed": SELECTION_SEED,
        "model_open_gate_branch": branch,
        "source_parent_clusters": source_parents,
        "selection_policy": {
            "pass_quota_order": [list(value) for value in PASS_QUOTAS],
            "fail_quota_order": [list(value) for value in FAIL_QUOTAS],
            "label_free_diversity": "greedy farthest-first by minimum mean normalized Levenshtein distance over CDR1/CDR2/CDR3 against same-parent V4-D anchors and earlier diversity selections",
            "control": "pre-reserved ascending SHA256 seeded control before every other bucket; independent of model scores and labels",
        },
        "node1_fastqc_census": {
            "fast_hard_pass_count": sum(
                not row["fast_hard_fail"] for row in census_by_id.values()
            ),
            "fast_hard_fail_count": len(node1_fastqc_hard_fail_ids),
            "selected_hard_fail_overlap": 0,
            "gate_order": "fast_hard_fail_rejected_before_model_ranked_acquisition",
            "evidence_boundary": "large-scale-fast sequence/developability census; not Full-QC, official-validator, structure, docking, binding, or blocking evidence",
        },
        "inputs": input_metadata,
        "input_snapshot_content_closure_sha256": input_closure,
        "deployment_release_status": deployment_summary["status"],
        "checks": checks,
        "manifest": {
            "filename": OUTPUT_FILENAMES[0],
            "sha256": sha256_bytes(manifest_payload),
            "row_count": len(selected),
        },
        "label_access": {
            "prospective_test_label_files_opened": 0,
            "v4f_label_files_opened": 0,
            "experimental_label_files_opened": 0,
        },
    }
    audit["audit_payload_sha256"] = sha256_json(audit)
    audit_payload = json_bytes(audit)
    receipt = {
        "schema_version": RECEIPT_VERSION,
        "status": (
            "PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST"
            if enforce_production_locks
            else "TEST_ONLY_PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST"
        ),
        "execution_mode": audit["execution_mode"],
        "model_open_gate_branch": branch,
        "selector_sha256": sha256_file(Path(__file__)),
        "input_snapshot_content_closure_sha256": input_closure,
        "inputs": {name: row["sha256"] for name, row in input_metadata.items()},
        "outputs": {
            OUTPUT_FILENAMES[0]: sha256_bytes(manifest_payload),
            OUTPUT_FILENAMES[1]: sha256_bytes(audit_payload),
        },
        "row_count": len(selected),
        "receipt_publication_order": "LAST_AFTER_ALL_BOUND_OUTPUTS_VERIFIED",
        "prospective_test_label_files_opened": 0,
        "v4f_label_files_opened": 0,
        "experimental_label_files_opened": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_payload = json_bytes(receipt)
    artifacts = {
        OUTPUT_FILENAMES[0]: manifest_payload,
        OUTPUT_FILENAMES[1]: audit_payload,
        OUTPUT_FILENAMES[2]: receipt_payload,
    }
    return artifacts, audit


@contextmanager
def publication_lock(output_dir: Path):
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.seen200.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Seen200SelectionError(f"publication_lock_exists:{lock_path}") from exc
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        lock_path.unlink(missing_ok=True)


def publish_receipt_last(output_dir: Path, artifacts: Mapping[str, bytes]) -> None:
    if set(artifacts) != set(OUTPUT_FILENAMES):
        raise Seen200SelectionError("publication_artifact_set_mismatch")
    output_dir = output_dir.expanduser().resolve()
    with publication_lock(output_dir):
        staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage.", dir=output_dir.parent))
        try:
            for name, payload in artifacts.items():
                (staging / name).write_bytes(payload)
                if (staging / name).read_bytes() != payload:
                    raise Seen200SelectionError(f"staged_artifact_mismatch:{name}")
            output_dir.mkdir(parents=True, exist_ok=True)
            unexpected = sorted(
                path.name for path in output_dir.iterdir() if path.is_file() and path.name not in OUTPUT_FILENAMES
            )
            if unexpected:
                raise Seen200SelectionError(f"unexpected_existing_output_files:{','.join(unexpected)}")
            receipt_path = output_dir / OUTPUT_FILENAMES[-1]
            receipt_path.unlink(missing_ok=True)
            for name in OUTPUT_FILENAMES[:-1]:
                os.replace(staging / name, output_dir / name)
                if (output_dir / name).read_bytes() != artifacts[name]:
                    raise Seen200SelectionError(f"published_artifact_mismatch:{name}")
            os.replace(staging / OUTPUT_FILENAMES[-1], receipt_path)
            if receipt_path.read_bytes() != artifacts[OUTPUT_FILENAMES[-1]]:
                raise Seen200SelectionError("published_receipt_mismatch")
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def verify_release(output_dir: Path, expected_artifacts: Mapping[str, bytes]) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    for name in OUTPUT_FILENAMES:
        path = output_dir / name
        if not path.is_file() or path.is_symlink():
            raise Seen200SelectionError(f"published_output_missing_or_symlink:{name}")
        if path.read_bytes() != expected_artifacts[name]:
            raise Seen200SelectionError(f"published_output_replay_mismatch:{name}")
    receipt = json.loads((output_dir / OUTPUT_FILENAMES[-1]).read_text(encoding="utf-8"))
    for name in OUTPUT_FILENAMES[:-1]:
        if receipt.get("outputs", {}).get(name) != sha256_file(output_dir / name):
            raise Seen200SelectionError(f"published_receipt_hash_mismatch:{name}")
    return {
        "status": "PASS_EXACT_BYTE_REPLAY_AND_HASH_CLOSURE",
        "row_count": int(receipt["row_count"]),
        "model_open_gate_branch": receipt["model_open_gate_branch"],
    }


def run(
    paths: Mapping[str, Path],
    output_dir: Path,
    *,
    verify_only: bool = False,
    enforce_production_locks: bool = True,
    expected_pool_rows: int = EXPECTED_POOL_ROWS,
    expected_v4d_rows: int = EXPECTED_V4D_ROWS,
    expected_v4f_rows: int = EXPECTED_V4F_ROWS,
    expected_source_parents: int = EXPECTED_SOURCE_PARENTS,
) -> dict[str, Any]:
    artifacts, audit = build_artifacts(
        paths,
        enforce_production_locks=enforce_production_locks,
        expected_pool_rows=expected_pool_rows,
        expected_v4d_rows=expected_v4d_rows,
        expected_v4f_rows=expected_v4f_rows,
        expected_source_parents=expected_source_parents,
    )
    if not verify_only:
        publish_receipt_last(output_dir, artifacts)
    replay = verify_release(output_dir, artifacts)
    return {"audit": audit, "replay": replay}


def default_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "candidate_pool": args.candidate_pool,
        "deployment_scores": args.deployment_scores,
        "deployment_summary": args.deployment_summary,
        "deployment_receipt": args.deployment_receipt,
        "v4d_manifest": args.v4d_manifest,
        "v4f_manifest": args.v4f_manifest,
        "reserve2_manifest": args.reserve2_manifest,
        "calibration_exclusions": args.calibration_exclusions,
        "parent_preregistration": args.parent_preregistration,
        "implementation_freeze": args.implementation_freeze,
        "selector_v2_preregistration": args.selector_v2_preregistration,
        "node1_fastqc_census": args.node1_fastqc_census,
        "node1_fastqc_census_receipt": args.node1_fastqc_census_receipt,
        "node1_fastqc_census_audit": args.node1_fastqc_census_audit,
        "node1_fastqc_census_independent_verification": args.node1_fastqc_census_independent_verification,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--deployment-scores", type=Path, default=DEFAULT_SCORES)
    parser.add_argument("--deployment-summary", type=Path, default=DEFAULT_SCORE_SUMMARY)
    parser.add_argument("--deployment-receipt", type=Path, default=DEFAULT_SCORE_RECEIPT)
    parser.add_argument("--v4d-manifest", type=Path, default=DEFAULT_V4D)
    parser.add_argument("--v4f-manifest", type=Path, default=DEFAULT_V4F)
    parser.add_argument("--reserve2-manifest", type=Path, default=DEFAULT_RESERVE)
    parser.add_argument("--calibration-exclusions", type=Path, default=DEFAULT_CALIBRATION_EXCLUSIONS)
    parser.add_argument("--parent-preregistration", type=Path, default=DEFAULT_PARENT_PREREGISTRATION)
    parser.add_argument(
        "--selector-v2-preregistration",
        type=Path,
        default=DEFAULT_SELECTOR_V2_PREREGISTRATION,
    )
    parser.add_argument("--node1-fastqc-census", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument(
        "--node1-fastqc-census-receipt", type=Path, default=DEFAULT_CENSUS_RECEIPT
    )
    parser.add_argument(
        "--node1-fastqc-census-audit", type=Path, default=DEFAULT_CENSUS_AUDIT
    )
    parser.add_argument(
        "--node1-fastqc-census-independent-verification",
        type=Path,
        default=DEFAULT_CENSUS_INDEPENDENT_VERIFICATION,
    )
    parser.add_argument("--implementation-freeze", type=Path, default=DEFAULT_IMPLEMENTATION_FREEZE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    result = run(default_paths(args), args.output_dir, verify_only=args.verify_only)
    print(
        json.dumps(
            {
                "status": result["audit"]["status"],
                "model_open_gate_branch": result["audit"]["model_open_gate_branch"],
                "row_count": result["audit"]["checks"]["row_count"],
                "replay_status": result["replay"]["status"],
                "output_dir": str(args.output_dir.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
