#!/usr/bin/env python3
"""Replay frozen V4-D artifacts over the 7,087-candidate deployment pool.

This scorer accepts label-free candidate, embedding, contact-feature, and
sequence-support releases only. It has no interface for prospective-test,
sealed, V4-F, or experimental labels.
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
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_phase2_v4_d_sequence_support as support  # noqa: E402
import phase2_v4_d_surrogate_watcher_helper as watcher  # noqa: E402
import train_phase2_v4_d_contact_feature_surrogate as contact  # noqa: E402
import train_phase2_v4_d_frozen_embedding_surrogate as embedding  # noqa: E402
import train_phase2_v4_d_surrogate as base  # noqa: E402


EXP_DIR = SCRIPT_DIR.parent
SCHEMA_VERSION = "phase2_v4_d_candidate_deployment_scoring_v1"
EXPECTED_CANDIDATE_COUNT = 7087
DEFAULT_POOL = (
    EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv"
)
DEFAULT_SUPPORT_CSV = EXP_DIR / "prepared/pvrig_v4_d/candidate7087_sequence_support.csv"
DEFAULT_SUPPORT_AUDIT = DEFAULT_SUPPORT_CSV.with_suffix(".csv.audit.json")
DEFAULT_SUPPORT_RECEIPT = DEFAULT_SUPPORT_CSV.with_suffix(".csv.receipt.json")
DEFAULT_V4D_MANIFEST = EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
DEFAULT_V4D_AUDIT = DEFAULT_V4D_MANIFEST.with_name("fullqc290_split_audit.json")
DEFAULT_V4F_MANIFEST = EXP_DIR / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv"
DEFAULT_V4F_AUDIT = DEFAULT_V4F_MANIFEST.with_name("prospective_holdout96_audit.json")
DEFAULT_V4F_RECEIPT = DEFAULT_V4F_MANIFEST.with_name("prospective_holdout96_receipt.json")
DEFAULT_V4G_RESERVE = EXP_DIR / "data_splits/pvrig_v4_g/untouched_reserve2_parents.tsv"
DEFAULT_V4G_PREREGISTRATION = DEFAULT_V4G_RESERVE.with_name(
    "phase2_v4_g_active_learning_preregistration.json"
)
DEFAULT_V4G_RECEIPT = DEFAULT_V4G_RESERVE.with_name(
    "v4_g_active_learning_freeze_receipt.json"
)
EXPECTED_V4D_MANIFEST_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_V4D_AUDIT_SHA256 = "e0fa1b2558e8dd1f6c934f709822706beb26ae69e4859fad3bdc4d5abaa3df37"
EXPECTED_V4F_MANIFEST_SHA256 = "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334"
EXPECTED_V4F_AUDIT_SHA256 = "fc24cc2bd203100e29be897e87850a67ddc362b1fa1635d4172ec4335f5083a1"
EXPECTED_V4F_RECEIPT_SHA256 = "3adc1e3194bdc5846f35b99020c3c996859caf3e3abc2b8e02df6ac75296512f"
EXPECTED_V4G_RESERVE_SHA256 = "98c11e8f72d97d60c9e772fa2bb256622f1ed6e1e9fddd9e136a8cd42959bb75"
EXPECTED_V4G_PREREGISTRATION_SHA256 = "1ba6ecb0e5541516649c9d3c8dc30c82f411f3c5296e0e04681486bd9441bf55"
EXPECTED_V4G_RECEIPT_SHA256 = "bb1e68b826987a146d7eeaa6f2a2262336b3bb82898b3a9147dbad4abb022b24"
DEFAULT_EMBEDDING_ROOT = (
    EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
)
DEFAULT_EMBEDDING_MANIFEST = (
    DEFAULT_EMBEDDING_ROOT / "meanpool_embeddings/embedding_manifest_v3.csv"
)
DEFAULT_EMBEDDING_SUMMARY = DEFAULT_EMBEDDING_MANIFEST.with_name(
    "embedding_summary_v3.json"
)
DEFAULT_SEQUENCE_MANIFEST = DEFAULT_EMBEDDING_ROOT / "sequence_manifest_v3.csv"
DEFAULT_BASE_DIR = EXP_DIR / "runs/pvrig_v4_d_sequence_surrogate_v1"
DEFAULT_EMBEDDING_DIR = EXP_DIR / "runs/pvrig_v4_d_frozen_embedding_surrogate_v1"
DEFAULT_CONTACT_DIR = EXP_DIR / "runs/pvrig_v4_d_contact_fusion_surrogate_v1"
DEFAULT_OUT_DIR = EXP_DIR / "runs/pvrig_v4_d_deployment_scoring_v1"
SCORE_FILENAME = "candidate7087_deployment_scores.tsv"
SUMMARY_FILENAME = "candidate7087_deployment_summary.json"
RECEIPT_FILENAME = "candidate7087_deployment_receipt.json"
OUTPUT_FILENAMES = (SCORE_FILENAME, SUMMARY_FILENAME, RECEIPT_FILENAME)
STAGE_RECEIPTS = {
    "base": "frozen_open_artifact_sha256_receipt.json",
    "embedding": "frozen_embedding_artifact_sha256_receipt.json",
    "contact": "contact_fusion_frozen_artifact_sha256_receipt.json",
}
STAGE_CONFIGS = {
    "base": "frozen_open_model_config.json",
    "embedding": "frozen_embedding_model_config.json",
    "contact": "contact_fusion_open_model_config.json",
}
STAGE_ARTIFACTS = {
    "base": "frozen_open_model_artifact.json",
    "embedding": "frozen_embedding_model_artifact.json",
    "contact": "contact_fusion_open_model_artifact.json",
}
STAGE_SUMMARIES = {
    "base": "open_development_summary.json",
    "embedding": "open_development_embedding_summary.json",
    "contact": "contact_fusion_open_development_summary.json",
}
CLAIM_BOUNDARY = (
    "Frozen V4-D sequence/embedding/contact surrogate replay for prioritizing "
    "independent dual-receptor docking only. Scores are computational geometry "
    "priors, not binding, affinity, competition, Docking Gold, experimental "
    "blocking, or final submission evidence. Only support-gated IN_DOMAIN rows "
    "may enter exploitation; all other rows require direct docking evidence."
)
POOL_FIELDS = (
    "candidate_id",
    "vhh_sequence",
    "sequence_sha256",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1_after",
    "cdr2_after",
    "cdr3_after",
    "generic_binding_prior",
)
SUPPORT_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "v4d_in_sequence_support",
    "v4d_support_domain",
    "v4d_support_domain_reason",
)
ALLOWED_SUPPORT_DOMAINS = frozenset(
    {"IN_DOMAIN", "NEAR_DOMAIN", "OOD", "TRAIN_REFERENCE"}
)
RESERVE_NO_SCORE = "UNTOUCHED_RESERVE_NO_SCORE"
V4F_NO_SCORE = "PROSPECTIVE_V4_F_SEPARATE_FREEZER_NO_SCORE"
V4D_NO_SCORE = "MODEL_DEVELOPMENT_OR_CHALLENGE_EXCLUDED_NO_SCORE"
SCORE_ALLOWED = "DEPLOYMENT_SCORING_ALLOWED"
NO_SCORE_CLASSES = frozenset({RESERVE_NO_SCORE, V4F_NO_SCORE, V4D_NO_SCORE})


class DeploymentScoringError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class StageBundle:
    stage: str
    directory: Path
    verification: dict[str, Any]
    config: dict[str, Any]
    artifact: dict[str, Any]
    summary: dict[str, Any]
    open_gates_pass: bool


def snapshot_file(path: Path) -> FileSnapshot:
    resolved = path.resolve()
    try:
        with resolved.open("rb") as handle:
            payload = handle.read()
    except OSError as exc:
        raise DeploymentScoringError(f"input_missing_or_unreadable:{resolved}") from exc
    return FileSnapshot(resolved, payload, hashlib.sha256(payload).hexdigest())


def sha256_file(path: Path) -> str:
    return snapshot_file(path).sha256


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def load_json_snapshot(snapshot: FileSnapshot) -> dict[str, Any]:
    try:
        payload = json.loads(snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentScoringError(f"invalid_json:{snapshot.path}") from exc
    if not isinstance(payload, dict):
        raise DeploymentScoringError(f"json_not_object:{snapshot.path}")
    return payload


def read_table_snapshot(
    snapshot: FileSnapshot, *, delimiter: str
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    try:
        text = snapshot.payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DeploymentScoringError(f"invalid_table_encoding:{snapshot.path}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    return list(reader), tuple(reader.fieldnames or ())


def require_fields(
    fields: Sequence[str], required: Sequence[str], label: str
) -> None:
    missing = sorted(set(required) - set(fields))
    if missing:
        raise DeploymentScoringError(
            f"missing_fields:{label}:{','.join(missing)}"
        )


def parse_bool(value: Any, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise DeploymentScoringError(f"invalid_boolean:{field}:{value}")


def finite_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise DeploymentScoringError(f"invalid_float:{field}:{value}") from exc
    if not math.isfinite(output):
        raise DeploymentScoringError(f"non_finite_float:{field}")
    return output


def adapt_candidate_rows(
    rows: Sequence[Mapping[str, str]], fields: Sequence[str], expected_count: int
) -> list[dict[str, Any]]:
    require_fields(fields, POOL_FIELDS, "candidate_pool")
    if len(rows) != expected_count:
        raise DeploymentScoringError(
            f"candidate_count_mismatch:{len(rows)}:{expected_count}"
        )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in rows:
        candidate_id = str(source["candidate_id"]).strip()
        if not candidate_id or candidate_id in seen:
            raise DeploymentScoringError(f"duplicate_or_empty_candidate_id:{candidate_id}")
        seen.add(candidate_id)
        sequence = base.validate_sequence(str(source["vhh_sequence"]), "vhh_sequence")
        digest = str(source["sequence_sha256"]).strip().lower()
        if base.sequence_sha256(sequence) != digest:
            raise DeploymentScoringError(f"candidate_sequence_hash_mismatch:{candidate_id}")
        cdrs = {
            name: base.validate_sequence(str(source[f"{name}_after"]), name)
            for name in ("cdr1", "cdr2", "cdr3")
        }
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": digest,
                "sequence": sequence,
                "parent_framework_cluster": str(
                    source["parent_framework_cluster"]
                ).strip(),
                "design_method": str(source["design_method"]).strip(),
                "design_mode": str(source["design_mode"]).strip(),
                "target_patch_id": str(source["target_patch_id"]).strip(),
                "generic_binding_prior": finite_float(
                    source["generic_binding_prior"], "generic_binding_prior"
                ),
                **cdrs,
            }
        )
    return output


def validate_support_rows(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[str],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    require_fields(fields, SUPPORT_FIELDS, "sequence_support")
    if len(rows) != len(candidates):
        raise DeploymentScoringError("support_candidate_row_count_mismatch")
    candidate_by_id = {str(row["candidate_id"]): row for row in candidates}
    support_by_id: dict[str, dict[str, Any]] = {}
    for source in rows:
        candidate_id = str(source["candidate_id"]).strip()
        candidate = candidate_by_id.get(candidate_id)
        if candidate is None or candidate_id in support_by_id:
            raise DeploymentScoringError(
                f"support_unknown_or_duplicate_candidate:{candidate_id}"
            )
        if (
            str(source["sequence_sha256"]).strip().lower()
            != candidate["sequence_sha256"]
            or str(source["parent_framework_cluster"]).strip()
            != candidate["parent_framework_cluster"]
        ):
            raise DeploymentScoringError(f"support_candidate_identity_mismatch:{candidate_id}")
        domain = str(source["v4d_support_domain"]).strip()
        if domain not in ALLOWED_SUPPORT_DOMAINS:
            raise DeploymentScoringError(f"unknown_support_domain:{candidate_id}:{domain}")
        in_support = parse_bool(
            source["v4d_in_sequence_support"], "v4d_in_sequence_support"
        )
        if in_support != (domain == "IN_DOMAIN"):
            raise DeploymentScoringError(f"support_domain_boolean_mismatch:{candidate_id}")
        support_by_id[candidate_id] = {
            "v4d_support_domain": domain,
            "v4d_in_sequence_support": in_support,
            "v4d_support_domain_reason": str(
                source["v4d_support_domain_reason"]
            ).strip(),
        }
    if set(support_by_id) != set(candidate_by_id):
        raise DeploymentScoringError("support_candidate_set_mismatch")
    return support_by_id


def verify_support_release(
    candidate_pool_path: Path,
    support_csv_path: Path,
    support_audit_path: Path,
    support_receipt_path: Path,
    *,
    expected_count: int,
    enforce_production_locks: bool,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    pool_snapshot = snapshot_file(candidate_pool_path)
    support_snapshot = snapshot_file(support_csv_path)
    audit_snapshot = snapshot_file(support_audit_path)
    receipt_snapshot = snapshot_file(support_receipt_path)
    try:
        closure = support.verify_artifact_closure(
            support_audit_path, support_receipt_path
        )
    except (OSError, KeyError, ValueError, support.SupportError) as exc:
        raise DeploymentScoringError("sequence_support_receipt_verification_failed") from exc
    audit = load_json_snapshot(audit_snapshot)
    receipt = load_json_snapshot(receipt_snapshot)
    audit_without_hash = dict(audit)
    claimed_audit_hash = audit_without_hash.pop("audit_payload_sha256", None)
    if claimed_audit_hash != support.sha256_json(audit_without_hash):
        raise DeploymentScoringError("support_audit_snapshot_payload_hash_mismatch")
    if audit.get("schema_version") != support.SCHEMA_VERSION:
        raise DeploymentScoringError("support_schema_version_mismatch")
    if audit.get("status") not in {
        "PASS_LABEL_FREE_SEQUENCE_SUPPORT_GATES",
        "FAIL_LABEL_FREE_SEQUENCE_SUPPORT_GATES",
    }:
        raise DeploymentScoringError("support_audit_status_invalid")
    output_record = (audit.get("outputs") or {}).get("sequence_support_csv")
    pool_record = (audit.get("inputs") or {}).get("candidate_pool")
    if not isinstance(output_record, dict) or not isinstance(pool_record, dict):
        raise DeploymentScoringError("support_audit_input_output_binding_missing")
    if (
        Path(str(output_record.get("path", ""))).resolve() != support_snapshot.path
        or output_record.get("sha256") != support_snapshot.sha256
        or int(output_record.get("row_count", -1)) != expected_count
        or Path(str(pool_record.get("path", ""))).resolve() != pool_snapshot.path
        or pool_record.get("sha256") != pool_snapshot.sha256
        or int(pool_record.get("row_count", -1)) != expected_count
    ):
        raise DeploymentScoringError("support_snapshot_binding_mismatch")
    if (
        Path(str((receipt.get("audit") or {}).get("path", ""))).resolve()
        != audit_snapshot.path
        or (receipt.get("audit") or {}).get("sha256") != audit_snapshot.sha256
    ):
        raise DeploymentScoringError("support_receipt_audit_snapshot_mismatch")
    if enforce_production_locks:
        if pool_snapshot.sha256 != support.EXPECTED_POOL_SHA256:
            raise DeploymentScoringError("candidate_pool_production_hash_mismatch")
        if audit.get("production_lock_id") != support.PRODUCTION_LOCK_ID:
            raise DeploymentScoringError("support_production_lock_id_mismatch")
        if audit.get("execution_mode") != "PRODUCTION_LOCKED_CONFIGURATION":
            raise DeploymentScoringError("support_execution_mode_not_production")
        if expected_count != EXPECTED_CANDIDATE_COUNT:
            raise DeploymentScoringError("production_candidate_count_override_forbidden")
    pool_rows, pool_fields = read_table_snapshot(pool_snapshot, delimiter=",")
    support_rows, support_fields = read_table_snapshot(support_snapshot, delimiter=",")
    candidates = adapt_candidate_rows(pool_rows, pool_fields, expected_count)
    support_by_id = validate_support_rows(
        support_rows, support_fields, candidates
    )
    all_gates_passed = audit.get("all_gates_passed") is True
    if all_gates_passed != all(
        bool(payload.get("passed"))
        for payload in (audit.get("gates") or {}).values()
    ):
        raise DeploymentScoringError("support_all_gates_boolean_mismatch")
    return candidates, support_by_id, {
        "closure": closure,
        "status": audit["status"],
        "all_gates_passed": all_gates_passed,
        "coverage": audit.get("coverage"),
        "gates": audit.get("gates"),
        "claim_boundary": audit.get("claim_boundary"),
        "candidate_pool": {
            "path": str(pool_snapshot.path),
            "sha256": pool_snapshot.sha256,
            "row_count": len(candidates),
        },
        "support_csv": {
            "path": str(support_snapshot.path),
            "sha256": support_snapshot.sha256,
            "row_count": len(support_by_id),
        },
        "support_audit": {
            "path": str(audit_snapshot.path),
            "sha256": audit_snapshot.sha256,
        },
        "support_receipt": {
            "path": str(receipt_snapshot.path),
            "sha256": receipt_snapshot.sha256,
        },
    }


def validate_frozen_identity_rows(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[str],
    candidates_by_id: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> set[str]:
    require_fields(
        fields,
        ("candidate_id", "sequence_sha256", "parent_framework_cluster"),
        label,
    )
    selected: set[str] = set()
    for row in rows:
        candidate_id = str(row["candidate_id"]).strip()
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None or candidate_id in selected:
            raise DeploymentScoringError(
                f"{label}_unknown_or_duplicate_candidate:{candidate_id}"
            )
        if (
            str(row["sequence_sha256"]).strip().lower()
            != candidate["sequence_sha256"]
            or str(row["parent_framework_cluster"]).strip()
            != candidate["parent_framework_cluster"]
        ):
            raise DeploymentScoringError(
                f"{label}_candidate_identity_mismatch:{candidate_id}"
            )
        selected.add(candidate_id)
    return selected


def load_scoring_governance(
    candidates: Sequence[Mapping[str, Any]],
    v4d_manifest_path: Path,
    v4d_audit_path: Path,
    v4f_manifest_path: Path,
    v4f_audit_path: Path,
    v4f_receipt_path: Path,
    v4g_reserve_path: Path,
    v4g_preregistration_path: Path,
    v4g_receipt_path: Path,
    *,
    enforce_production_locks: bool,
    expected_v4d_count: int = 290,
    expected_v4f_count: int = 96,
    expected_reserve_parent_count: int = 2,
) -> tuple[dict[str, str], dict[str, Any]]:
    snapshots = {
        "v4d_manifest": snapshot_file(v4d_manifest_path),
        "v4d_audit": snapshot_file(v4d_audit_path),
        "v4f_manifest": snapshot_file(v4f_manifest_path),
        "v4f_audit": snapshot_file(v4f_audit_path),
        "v4f_receipt": snapshot_file(v4f_receipt_path),
        "v4g_reserve": snapshot_file(v4g_reserve_path),
        "v4g_preregistration": snapshot_file(v4g_preregistration_path),
        "v4g_receipt": snapshot_file(v4g_receipt_path),
    }
    if enforce_production_locks:
        expected_hashes = {
            "v4d_manifest": EXPECTED_V4D_MANIFEST_SHA256,
            "v4d_audit": EXPECTED_V4D_AUDIT_SHA256,
            "v4f_manifest": EXPECTED_V4F_MANIFEST_SHA256,
            "v4f_audit": EXPECTED_V4F_AUDIT_SHA256,
            "v4f_receipt": EXPECTED_V4F_RECEIPT_SHA256,
            "v4g_reserve": EXPECTED_V4G_RESERVE_SHA256,
            "v4g_preregistration": EXPECTED_V4G_PREREGISTRATION_SHA256,
            "v4g_receipt": EXPECTED_V4G_RECEIPT_SHA256,
        }
        for label, expected in expected_hashes.items():
            if snapshots[label].sha256 != expected:
                raise DeploymentScoringError(
                    f"governance_production_hash_mismatch:{label}"
                )
    candidates_by_id = {str(row["candidate_id"]): row for row in candidates}

    v4d_rows, v4d_fields = read_table_snapshot(
        snapshots["v4d_manifest"], delimiter="\t"
    )
    if len(v4d_rows) != expected_v4d_count:
        raise DeploymentScoringError("v4d_governance_row_count_mismatch")
    v4d_ids = validate_frozen_identity_rows(
        v4d_rows, v4d_fields, candidates_by_id, label="v4d_governance"
    )
    v4d_audit = load_json_snapshot(snapshots["v4d_audit"])
    if (
        v4d_audit.get("status") != "PASS_PROSPECTIVE_COMPUTATIONAL_SPLIT"
        or (v4d_audit.get("manifest") or {}).get("sha256")
        != snapshots["v4d_manifest"].sha256
    ):
        raise DeploymentScoringError("v4d_governance_audit_closure_invalid")

    v4f_rows, v4f_fields = read_table_snapshot(
        snapshots["v4f_manifest"], delimiter="\t"
    )
    if len(v4f_rows) != expected_v4f_count:
        raise DeploymentScoringError("v4f_governance_row_count_mismatch")
    v4f_ids = validate_frozen_identity_rows(
        v4f_rows, v4f_fields, candidates_by_id, label="v4f_governance"
    )
    v4f_audit = load_json_snapshot(snapshots["v4f_audit"])
    v4f_receipt = load_json_snapshot(snapshots["v4f_receipt"])
    if (
        v4f_audit.get("status") != "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN"
        or (v4f_audit.get("output") or {}).get("sha256")
        != snapshots["v4f_manifest"].sha256
        or v4f_receipt.get("status") != "PASS_COMPLETE_HASH_CLOSURE"
        or v4f_receipt.get("manifest_sha256")
        != snapshots["v4f_manifest"].sha256
        or v4f_receipt.get("audit_file_sha256") != snapshots["v4f_audit"].sha256
    ):
        raise DeploymentScoringError("v4f_governance_receipt_closure_invalid")

    reserve_rows, reserve_fields = read_table_snapshot(
        snapshots["v4g_reserve"], delimiter="\t"
    )
    require_fields(
        reserve_fields,
        (
            "parent_framework_cluster",
            "selection_role",
            "untouched_policy",
        ),
        "v4g_reserve",
    )
    reserve_parents = {
        str(row["parent_framework_cluster"]).strip() for row in reserve_rows
    }
    if (
        len(reserve_rows) != expected_reserve_parent_count
        or len(reserve_parents) != expected_reserve_parent_count
        or any(
            row["selection_role"] != "UNTOUCHED_V4_G_RESERVE_PARENT"
            or "no_model_scoring" not in row["untouched_policy"]
            for row in reserve_rows
        )
    ):
        raise DeploymentScoringError("v4g_reserve_policy_invalid")
    preregistration = load_json_snapshot(snapshots["v4g_preregistration"])
    v4g_receipt = load_json_snapshot(snapshots["v4g_receipt"])
    prereg_reserve = preregistration.get("untouched_reserve2") or {}
    if (
        preregistration.get("status")
        != "FROZEN_LABEL_FREE_BEFORE_V4D_OPEN_TEACHER_OR_V4F_DOCKING_LABELS"
        or set(prereg_reserve.get("parent_clusters") or []) != reserve_parents
        or prereg_reserve.get("parent_manifest_sha256")
        != snapshots["v4g_reserve"].sha256
        or "no model scoring" not in str(prereg_reserve.get("policy", ""))
        or v4g_receipt.get("status")
        != "PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST"
        or (v4g_receipt.get("outputs") or {}).get(
            snapshots["v4g_reserve"].path.name
        )
        != snapshots["v4g_reserve"].sha256
        or (v4g_receipt.get("outputs") or {}).get(
            snapshots["v4g_preregistration"].path.name
        )
        != snapshots["v4g_preregistration"].sha256
    ):
        raise DeploymentScoringError("v4g_reserve_receipt_closure_invalid")

    governance = {candidate_id: SCORE_ALLOWED for candidate_id in candidates_by_id}
    for candidate_id in v4d_ids:
        governance[candidate_id] = V4D_NO_SCORE
    for candidate_id in v4f_ids:
        governance[candidate_id] = V4F_NO_SCORE
    reserve_ids = {
        candidate_id
        for candidate_id, row in candidates_by_id.items()
        if row["parent_framework_cluster"] in reserve_parents
    }
    for candidate_id in reserve_ids:
        governance[candidate_id] = RESERVE_NO_SCORE
    counts: dict[str, int] = {}
    for value in governance.values():
        counts[value] = counts.get(value, 0) + 1
    metadata = {
        "priority": [RESERVE_NO_SCORE, V4F_NO_SCORE, V4D_NO_SCORE, SCORE_ALLOWED],
        "counts": dict(sorted(counts.items())),
        "v4d_candidate_count": len(v4d_ids),
        "v4f_candidate_count": len(v4f_ids),
        "reserve_parent_count": len(reserve_parents),
        "reserve_parent_clusters": sorted(reserve_parents),
        "reserve_candidate_count": len(reserve_ids),
        "scored_candidate_count": counts.get(SCORE_ALLOWED, 0),
        "inputs": {
            label: {"path": str(snapshot.path), "sha256": snapshot.sha256}
            for label, snapshot in snapshots.items()
        },
        "model_feature_matrix_contract": (
            "Only DEPLOYMENT_SCORING_ALLOWED candidates may enter any base, embedding, "
            "or contact feature matrix. All frozen V4-D, V4-F, and V4-G reserve rows "
            "remain identity-only with empty predictions and uncertainties."
        ),
    }
    return governance, metadata


def stage_missing(stage: str, directory: Path) -> list[str]:
    required = (
        STAGE_RECEIPTS[stage],
        STAGE_CONFIGS[stage],
        STAGE_ARTIFACTS[stage],
        STAGE_SUMMARIES[stage],
    )
    return [str((directory / name).resolve()) for name in required if not (directory / name).is_file()]


def verify_stage_bundle(stage: str, directory: Path) -> StageBundle:
    directory = directory.resolve()
    try:
        verification = watcher.verify_stage(
            SimpleNamespace(stage=stage, out_dir=directory, expected_input=[])
        )
    except Exception as exc:
        raise DeploymentScoringError(f"frozen_stage_verification_failed:{stage}") from exc
    receipt_path = directory / STAGE_RECEIPTS[stage]
    config_path = directory / STAGE_CONFIGS[stage]
    artifact_path = directory / STAGE_ARTIFACTS[stage]
    summary_path = directory / STAGE_SUMMARIES[stage]
    receipt_snapshot = snapshot_file(receipt_path)
    config_snapshot = snapshot_file(config_path)
    artifact_snapshot = snapshot_file(artifact_path)
    summary_snapshot = snapshot_file(summary_path)
    receipt = load_json_snapshot(receipt_snapshot)
    output_hashes = receipt.get("outputs")
    if not isinstance(output_hashes, dict):
        raise DeploymentScoringError(f"stage_receipt_outputs_missing:{stage}")
    replay_snapshots = {
        "receipt": receipt_snapshot,
        "config": config_snapshot,
        "artifact": artifact_snapshot,
        "summary": summary_snapshot,
    }
    for label, snapshot in replay_snapshots.items():
        if label == "receipt":
            continue
        if output_hashes.get(str(snapshot.path)) != snapshot.sha256:
            raise DeploymentScoringError(
                f"stage_replay_snapshot_hash_mismatch:{stage}:{label}"
            )
    verification = dict(verification)
    verification["replay_inputs"] = {
        label: {"path": str(snapshot.path), "sha256": snapshot.sha256}
        for label, snapshot in replay_snapshots.items()
    }
    config = load_json_snapshot(config_snapshot)
    summary = load_json_snapshot(summary_snapshot)
    config_hash = config_snapshot.sha256
    if stage == "base":
        artifact = base.load_model_artifact(
            artifact_path, expected_config_sha256=config_hash
        )
        selected = artifact.get("selected_candidate_model")
        if selected not in base.CANDIDATE_MODELS:
            raise DeploymentScoringError("base_selected_model_not_candidate_model")
        open_gates_pass = str(summary.get("status", "")).startswith(
            "PASS_OPEN_DEVELOPMENT_GATES_"
        )
    elif stage == "embedding":
        artifact = embedding.load_model_artifact(
            artifact_path, expected_config_sha256=config_hash
        )
        open_gates_pass = (
            str(summary.get("status", "")).startswith("PASS_OPEN_GATES_")
            and summary.get("open_gates_pass") is True
        )
    else:
        artifact = load_json_snapshot(artifact_snapshot)
        if (
            artifact.get("schema_version") != contact.SCHEMA_VERSION
            or artifact.get("status")
            != "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED"
            or artifact.get("config_sha256") != config_hash
            or artifact.get("prospective_test_labels_read") is not False
            or set(artifact.get("models", {})) != set(contact.MODEL_NAMES)
            or artifact.get("selected_candidate_model") not in contact.CANDIDATE_MODELS
        ):
            raise DeploymentScoringError("contact_artifact_contract_invalid")
        identity_fields = (
            "embedding_bank_identity_sha256",
            "contact_release_receipt_sha256",
            "contact_schema_sha256",
            "stable_contact_columns_sha256",
            "stage_inputs_closure_sha256",
        )
        config_identity = config.get("artifact_identity_contract") or {}
        if any(
            artifact.get(field) != receipt.get(field)
            or (
                field != "stage_inputs_closure_sha256"
                and artifact.get(field) != config_identity.get(field)
            )
            for field in identity_fields
        ):
            raise DeploymentScoringError("contact_artifact_identity_contract_mismatch")
        if receipt.get("stage_inputs_closure_sha256") != contact.sha256_json(
            receipt.get("inputs") or {}
        ):
            raise DeploymentScoringError("contact_stage_inputs_closure_mismatch")
        if receipt.get("stable_contact_columns_sha256") != base.sha256_strings(
            receipt.get("stable_contact_columns") or []
        ):
            raise DeploymentScoringError("contact_stable_columns_hash_mismatch")
        performance = summary.get("open_performance_gates_vs_cdr_length_only") or {}
        uncertainty = summary.get("selected_model_uncertainty_contract") or {}
        open_gates_pass = (
            performance.get("all_passed") is True
            and uncertainty.get("gate_pass") is True
        )
    if (
        config.get("prospective_test", {}).get("labels_read") is not False
        and config.get("prospective_test_labels_read") is not False
    ):
        raise DeploymentScoringError(f"stage_config_test_label_boundary_invalid:{stage}")
    if artifact.get("prospective_test_labels_read") is not False:
        raise DeploymentScoringError(f"stage_artifact_test_label_boundary_invalid:{stage}")
    if sha256_file(artifact_path) != artifact_snapshot.sha256:
        raise DeploymentScoringError(f"stage_artifact_changed_during_replay:{stage}")
    return StageBundle(
        stage,
        directory,
        verification,
        config,
        artifact,
        summary,
        open_gates_pass,
    )


def validate_contact_replay_identity(
    contact_stage: StageBundle,
    bank: embedding.EmbeddingBank,
    contact_metadata: Mapping[str, Any],
    stable_columns: Sequence[str],
) -> None:
    artifact = contact_stage.artifact
    expected = {
        "embedding_bank_identity_sha256": bank.provenance["identity_sha256"],
        "contact_release_receipt_sha256": contact_metadata["receipt_sha256"],
        "contact_schema_sha256": contact_metadata["frozen_schema"]["schema_sha256"],
        "stable_contact_columns_sha256": base.sha256_strings(stable_columns),
    }
    for field, value in expected.items():
        if artifact.get(field) != value:
            raise DeploymentScoringError(
                f"contact_replay_identity_mismatch:{field}"
            )


def attach_contact_and_embedding_features(
    candidates: Sequence[dict[str, Any]],
    contact_by_id: Mapping[str, Mapping[str, Any]],
    stable_columns: Sequence[str],
    bank: embedding.EmbeddingBank,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in candidates:
        candidate_id = str(source["candidate_id"])
        digest = str(source["sequence_sha256"])
        contact_row = contact_by_id[candidate_id]
        if contact_row["sequence_sha256"] != digest:
            raise DeploymentScoringError(
                f"contact_candidate_sequence_hash_mismatch:{candidate_id}"
            )
        index = bank.index_by_sha256.get(digest)
        if index is None:
            raise DeploymentScoringError(f"candidate_embedding_missing:{candidate_id}")
        esm2 = np.asarray(bank.esm2[index], dtype=np.float64).copy()
        if esm2.shape != (bank.esm2.shape[1],) or not np.all(np.isfinite(esm2)):
            raise DeploymentScoringError(f"candidate_esm2_invalid:{candidate_id}")
        row = dict(source)
        row["_contact"] = {
            column: finite_float(contact_row[column], column)
            for column in stable_columns
        }
        row["_embedding"] = esm2
        output.append(row)
    return output


def replay_predictions(
    candidates: list[dict[str, Any]],
    contact_by_id: Mapping[str, Mapping[str, Any]],
    stable_columns: Sequence[str],
    bank: embedding.EmbeddingBank,
    stages: Mapping[str, StageBundle],
) -> dict[str, Any]:
    sequence_hashes = [str(row["sequence_sha256"]) for row in candidates]
    base_name = str(stages["base"].artifact["selected_candidate_model"])
    embedding_name = str(stages["embedding"].artifact["selected_model"])
    contact_name = str(stages["contact"].artifact["selected_candidate_model"])
    base_prediction, base_uncertainty = base.predict_serialized_model(
        stages["base"].artifact, base_name, candidates
    )
    embedding_prediction, embedding_uncertainty = embedding.predict_artifact_model(
        stages["embedding"].artifact,
        embedding_name,
        bank,
        sequence_hashes,
    )
    contact_rows = attach_contact_and_embedding_features(
        candidates, contact_by_id, stable_columns, bank
    )
    contact_prediction, contact_uncertainty = contact.predict_serialized_model(
        stages["contact"].artifact, contact_name, contact_rows
    )
    predictions = np.vstack(
        [base_prediction, embedding_prediction, contact_prediction]
    )
    uncertainties = np.vstack(
        [base_uncertainty, embedding_uncertainty, contact_uncertainty]
    )
    if (
        predictions.shape != (3, len(candidates))
        or uncertainties.shape != (3, len(candidates))
        or not np.all(np.isfinite(predictions))
        or not np.all(np.isfinite(uncertainties))
        or np.any(uncertainties < 0.0)
    ):
        raise DeploymentScoringError("replayed_prediction_shape_or_finiteness_invalid")
    return {
        "model_names": {
            "base": base_name,
            "embedding": embedding_name,
            "contact": contact_name,
        },
        "base_prediction": base_prediction,
        "base_uncertainty": base_uncertainty,
        "embedding_prediction": embedding_prediction,
        "embedding_uncertainty": embedding_uncertainty,
        "contact_prediction": contact_prediction,
        "contact_uncertainty": contact_uncertainty,
        "consensus_prediction": predictions.mean(axis=0),
        "ensemble_uncertainty": np.sqrt(np.mean(np.square(uncertainties), axis=0)),
        "model_disagreement": predictions.std(axis=0),
    }


def index_replayed_predictions(
    candidates: Sequence[Mapping[str, Any]], replay: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate["candidate_id"])
        output[candidate_id] = {
            "base_model": replay["model_names"]["base"],
            "base_prediction": round(float(replay["base_prediction"][index]), 9),
            "base_ensemble_uncertainty": round(
                float(replay["base_uncertainty"][index]), 9
            ),
            "embedding_model": replay["model_names"]["embedding"],
            "embedding_prediction": round(
                float(replay["embedding_prediction"][index]), 9
            ),
            "embedding_ensemble_uncertainty": round(
                float(replay["embedding_uncertainty"][index]), 9
            ),
            "contact_model": replay["model_names"]["contact"],
            "contact_prediction": round(
                float(replay["contact_prediction"][index]), 9
            ),
            "contact_ensemble_uncertainty": round(
                float(replay["contact_uncertainty"][index]), 9
            ),
            "consensus_prediction": round(
                float(replay["consensus_prediction"][index]), 9
            ),
            "ensemble_uncertainty": round(
                float(replay["ensemble_uncertainty"][index]), 9
            ),
            "model_disagreement": round(
                float(replay["model_disagreement"][index]), 9
            ),
        }
    return output


def deployment_route(
    domain: str, *, support_gates_pass: bool, model_gates_pass: bool
) -> str:
    if domain == "TRAIN_REFERENCE":
        return "TRAIN_REFERENCE_EXCLUDED"
    if domain == "NEAR_DOMAIN":
        return "UNCERTAINTY_DIVERSITY_DIRECT_DOCKING"
    if domain == "OOD":
        return "DIRECT_DOCKING_ONLY_OOD"
    if domain != "IN_DOMAIN":
        raise DeploymentScoringError(f"unknown_support_domain:{domain}")
    if not support_gates_pass:
        return "EXPLOITATION_BLOCKED_SUPPORT_GATE"
    if not model_gates_pass:
        return "EXPLOITATION_BLOCKED_MODEL_GATE"
    return "EXPLOITATION"


def rank_indices(indices: Sequence[int], keys: Mapping[int, tuple[Any, ...]]) -> dict[int, int]:
    ordered = sorted(indices, key=lambda index: keys[index])
    return {index: rank for rank, index in enumerate(ordered, start=1)}


def build_output_rows(
    candidates: Sequence[Mapping[str, Any]],
    support_by_id: Mapping[str, Mapping[str, Any]],
    governance_by_id: Mapping[str, str],
    prediction_by_id: Mapping[str, Mapping[str, Any]],
    *,
    support_gates_pass: bool,
    model_gates_pass: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate["candidate_id"])
        support_row = support_by_id[candidate_id]
        domain = str(support_row["v4d_support_domain"])
        governance = governance_by_id[candidate_id]
        prediction = prediction_by_id.get(candidate_id)
        scoring_permitted = governance == SCORE_ALLOWED
        if scoring_permitted:
            if prediction is None:
                raise DeploymentScoringError(
                    f"scorable_candidate_prediction_missing:{candidate_id}"
                )
            route = deployment_route(
                domain,
                support_gates_pass=support_gates_pass,
                model_gates_pass=model_gates_pass,
            )
            ensemble_uncertainty = float(prediction["ensemble_uncertainty"])
            disagreement = float(prediction["model_disagreement"])
        else:
            if governance not in NO_SCORE_CLASSES or prediction is not None:
                raise DeploymentScoringError(
                    f"no_score_candidate_prediction_or_policy_invalid:{candidate_id}"
                )
            route = governance
            ensemble_uncertainty = math.nan
            disagreement = math.nan
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": candidate["sequence_sha256"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "design_method": candidate["design_method"],
                "design_mode": candidate["design_mode"],
                "target_patch_id": candidate["target_patch_id"],
                "v4d_support_domain": domain,
                "v4d_support_domain_reason": support_row[
                    "v4d_support_domain_reason"
                ],
                "scoring_governance": governance,
                "model_scoring_permitted": scoring_permitted,
                "support_release_all_gates_passed": support_gates_pass,
                "model_open_gates_passed": model_gates_pass,
                "deployment_route": route,
                "exploitation_eligible": route == "EXPLOITATION",
                "portfolio_diversity_required": route
                == "UNCERTAINTY_DIVERSITY_DIRECT_DOCKING",
                "base_model": prediction["base_model"] if prediction else "",
                "base_prediction": prediction["base_prediction"] if prediction else "",
                "base_ensemble_uncertainty": (
                    prediction["base_ensemble_uncertainty"] if prediction else ""
                ),
                "embedding_model": prediction["embedding_model"] if prediction else "",
                "embedding_prediction": (
                    prediction["embedding_prediction"] if prediction else ""
                ),
                "embedding_ensemble_uncertainty": (
                    prediction["embedding_ensemble_uncertainty"] if prediction else ""
                ),
                "contact_model": prediction["contact_model"] if prediction else "",
                "contact_prediction": prediction["contact_prediction"] if prediction else "",
                "contact_ensemble_uncertainty": (
                    prediction["contact_ensemble_uncertainty"] if prediction else ""
                ),
                "consensus_prediction": (
                    prediction["consensus_prediction"] if prediction else ""
                ),
                "ensemble_uncertainty": (
                    round(ensemble_uncertainty, 9) if prediction else ""
                ),
                "model_disagreement": round(disagreement, 9) if prediction else "",
                "exploration_priority": (
                    round(ensemble_uncertainty + disagreement, 9) if prediction else ""
                ),
                "exploitation_rank": "",
                "exploration_rank": "",
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    exploitation_indices = [
        index for index, row in enumerate(output) if row["exploitation_eligible"]
    ]
    exploitation_ranks = rank_indices(
        exploitation_indices,
        {
            index: (
                -float(output[index]["consensus_prediction"]),
                float(output[index]["ensemble_uncertainty"]),
                float(output[index]["model_disagreement"]),
                str(output[index]["candidate_id"]),
            )
            for index in exploitation_indices
        },
    )
    exploration_indices = [
        index
        for index, row in enumerate(output)
        if row["deployment_route"] == "UNCERTAINTY_DIVERSITY_DIRECT_DOCKING"
    ]
    exploration_ranks = rank_indices(
        exploration_indices,
        {
            index: (
                -float(output[index]["exploration_priority"]),
                -float(output[index]["consensus_prediction"]),
                str(output[index]["candidate_id"]),
            )
            for index in exploration_indices
        },
    )
    for index, rank in exploitation_ranks.items():
        output[index]["exploitation_rank"] = rank
    for index, rank in exploration_ranks.items():
        output[index]["exploration_rank"] = rank
    route_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    for row in output:
        route_counts[str(row["deployment_route"])] = (
            route_counts.get(str(row["deployment_route"]), 0) + 1
        )
        domain_counts[str(row["v4d_support_domain"])] = (
            domain_counts.get(str(row["v4d_support_domain"]), 0) + 1
        )
    return output, {
        "row_count": len(output),
        "domain_counts": dict(sorted(domain_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "exploitation_count": len(exploitation_indices),
        "uncertainty_diversity_direct_docking_count": len(exploration_indices),
        "scored_prediction_count": len(prediction_by_id),
        "no_score_identity_only_count": len(output) - len(prediction_by_id),
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise DeploymentScoringError("refusing_to_write_empty_deployment_scores")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def publish(
    staging: Path,
    out_dir: Path,
    names: Sequence[str],
    *,
    waiting: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    allowed = set(OUTPUT_FILENAMES)
    unexpected = sorted(path.name for path in out_dir.iterdir() if path.name not in allowed)
    if unexpected:
        raise DeploymentScoringError(
            "unexpected_deployment_output_files:" + ",".join(unexpected)
        )
    if waiting and (out_dir / SCORE_FILENAME).exists():
        raise DeploymentScoringError("refusing_to_replace_scored_release_with_waiting")
    receipt_path = out_dir / RECEIPT_FILENAME
    receipt_path.unlink(missing_ok=True)
    for name in names:
        if name == RECEIPT_FILENAME:
            continue
        os.replace(staging / name, out_dir / name)
    os.replace(staging / RECEIPT_FILENAME, receipt_path)
    descriptor = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "policy": "stage_all_outputs_then_atomic_file_replace_with_receipt_last",
        "receipt_published_last": True,
        "waiting_release": waiting,
    }


def input_hashes(
    support_metadata: Mapping[str, Any],
    contact_metadata: Mapping[str, Any],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    records = (
        support_metadata["candidate_pool"],
        support_metadata["support_csv"],
        support_metadata["support_audit"],
        support_metadata["support_receipt"],
    )
    output = {str(record["path"]): str(record["sha256"]) for record in records}
    for path_key, hash_key in (
        ("receipt_path", "receipt_sha256"),
        ("audit_path", "audit_sha256"),
        ("feature_path", "feature_sha256"),
    ):
        output[str(contact_metadata[path_key])] = str(contact_metadata[hash_key])
    schema = contact_metadata["frozen_schema"]
    output[str(schema["schema_path"])] = str(schema["schema_sha256"])
    output[str(schema["schema_receipt_path"])] = str(schema["schema_receipt_sha256"])
    if extra:
        output.update(extra)
    return dict(sorted(output.items()))


def verify_published_release(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.resolve()
    receipt_path = out_dir / RECEIPT_FILENAME
    summary_path = out_dir / SUMMARY_FILENAME
    receipt = load_json_snapshot(snapshot_file(receipt_path))
    summary = load_json_snapshot(snapshot_file(summary_path))
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or summary.get("schema_version") != SCHEMA_VERSION
        or receipt.get("prospective_test_labels_read") is not False
        or receipt.get("v4f_labels_read") is not False
        or summary.get("prospective_test_labels_read") is not False
        or summary.get("v4f_labels_read") is not False
    ):
        raise DeploymentScoringError("published_release_label_boundary_invalid")
    inputs = receipt.get("inputs")
    outputs = receipt.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        raise DeploymentScoringError("published_release_hash_bindings_missing")
    for label, records in (("input", inputs), ("output", outputs)):
        for raw_path, expected_hash in records.items():
            path = Path(str(raw_path))
            if not path.is_absolute() or sha256_file(path) != expected_hash:
                raise DeploymentScoringError(
                    f"published_release_{label}_hash_mismatch:{path}"
                )
    if outputs.get(str(summary_path)) != sha256_file(summary_path):
        raise DeploymentScoringError("published_release_summary_not_bound")
    score_path = out_dir / SCORE_FILENAME
    waiting = receipt.get("status") == "WAITING_NO_DEPLOYMENT_SCORES_PUBLISHED"
    complete = receipt.get("status") == "PASS_DEPLOYMENT_SCORING_HASH_CLOSURE"
    if waiting == complete:
        raise DeploymentScoringError("published_release_status_invalid")
    if waiting:
        if summary.get("status") != "WAITING_FROZEN_MODEL_ARTIFACTS" or score_path.exists():
            raise DeploymentScoringError("waiting_release_published_scores_or_wrong_summary")
        row_count = 0
    else:
        if summary.get("status") not in {
            "PASS_DEPLOYMENT_SCORES_ROUTED",
            "PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED",
        }:
            raise DeploymentScoringError("complete_release_summary_status_invalid")
        if outputs.get(str(score_path)) != sha256_file(score_path):
            raise DeploymentScoringError("complete_release_score_not_bound")
        score_snapshot = snapshot_file(score_path)
        score_rows, fields = read_table_snapshot(score_snapshot, delimiter="\t")
        require_fields(
            fields,
            (
                "candidate_id",
                "sequence_sha256",
                "scoring_governance",
                "model_scoring_permitted",
                "deployment_route",
                "ensemble_uncertainty",
                "model_disagreement",
                "claim_boundary",
            ),
            "published_deployment_scores",
        )
        row_count = len(score_rows)
        if row_count != int(receipt.get("candidate_count", -1)):
            raise DeploymentScoringError("published_release_score_row_count_mismatch")
        prediction_fields = (
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
        scored_count = 0
        for row in score_rows:
            governance = row["scoring_governance"]
            if governance in NO_SCORE_CLASSES:
                if row["deployment_route"] != governance or any(
                    row.get(field, "") != "" for field in prediction_fields
                ):
                    raise DeploymentScoringError(
                        "published_no_score_row_contains_model_output"
                    )
            elif governance == SCORE_ALLOWED:
                scored_count += 1
                if row["model_scoring_permitted"].lower() != "true" or any(
                    row.get(field, "") == "" for field in prediction_fields
                ):
                    raise DeploymentScoringError(
                        "published_scored_row_missing_model_output"
                    )
            else:
                raise DeploymentScoringError("published_scoring_governance_unknown")
        if scored_count != int(receipt.get("model_scored_candidate_count", -1)):
            raise DeploymentScoringError("published_scored_candidate_count_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_WAITING_RELEASE_HASH_CLOSURE"
            if waiting
            else "PASS_DEPLOYMENT_RELEASE_HASH_CLOSURE"
        ),
        "release_status": receipt["status"],
        "row_count": row_count,
        "receipt": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "prospective_test_labels_read": False,
        "v4f_labels_read": False,
    }


def run_pipeline(
    candidate_pool_path: Path,
    support_csv_path: Path,
    support_audit_path: Path,
    support_receipt_path: Path,
    v4d_manifest_path: Path,
    v4d_audit_path: Path,
    v4f_manifest_path: Path,
    v4f_audit_path: Path,
    v4f_receipt_path: Path,
    v4g_reserve_path: Path,
    v4g_preregistration_path: Path,
    v4g_receipt_path: Path,
    contact_receipt_path: Path,
    contact_schema_path: Path,
    embedding_manifest_path: Path,
    embedding_summary_path: Path,
    sequence_manifest_path: Path,
    base_dir: Path,
    embedding_dir: Path,
    contact_dir: Path,
    out_dir: Path,
    *,
    expected_count: int = EXPECTED_CANDIDATE_COUNT,
    expected_v4d_count: int = 290,
    expected_v4f_count: int = 96,
    expected_reserve_parent_count: int = 2,
    enforce_production_locks: bool = True,
) -> dict[str, Any]:
    candidates, support_by_id, support_metadata = verify_support_release(
        candidate_pool_path,
        support_csv_path,
        support_audit_path,
        support_receipt_path,
        expected_count=expected_count,
        enforce_production_locks=enforce_production_locks,
    )
    governance_by_id, governance_metadata = load_scoring_governance(
        candidates,
        v4d_manifest_path,
        v4d_audit_path,
        v4f_manifest_path,
        v4f_audit_path,
        v4f_receipt_path,
        v4g_reserve_path,
        v4g_preregistration_path,
        v4g_receipt_path,
        enforce_production_locks=enforce_production_locks,
        expected_v4d_count=expected_v4d_count,
        expected_v4f_count=expected_v4f_count,
        expected_reserve_parent_count=expected_reserve_parent_count,
    )
    scorable_candidates = [
        row
        for row in candidates
        if governance_by_id[str(row["candidate_id"])] == SCORE_ALLOWED
    ]
    scorable_ids = {str(row["candidate_id"]) for row in scorable_candidates}
    all_contact_rows, stable_columns, contact_metadata = contact.load_verified_contact_release(
        contact_receipt_path,
        contact_schema_path,
        scorable_ids,
        enforce_production_hash=enforce_production_locks,
    )
    contact_by_id = {candidate_id: all_contact_rows[candidate_id] for candidate_id in scorable_ids}
    governance_input_hashes = {
        str(record["path"]): str(record["sha256"])
        for record in governance_metadata["inputs"].values()
    }
    directories = {
        "base": base_dir.resolve(),
        "embedding": embedding_dir.resolve(),
        "contact": contact_dir.resolve(),
    }
    missing = {
        stage: stage_missing(stage, directory)
        for stage, directory in directories.items()
    }
    missing = {stage: paths for stage, paths in missing.items() if paths}
    out_dir = out_dir.resolve()
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.stage.", dir=out_dir.parent))
    try:
        if missing:
            summary = {
                "schema_version": SCHEMA_VERSION,
                "status": "WAITING_FROZEN_MODEL_ARTIFACTS",
                "candidate_count": len(candidates),
                "model_scored_candidate_count": len(scorable_candidates),
                "missing_model_artifacts": missing,
                "support_release": support_metadata,
                "scoring_governance": governance_metadata,
                "contact_feature_release": contact_metadata,
                "scores_published": False,
                "prospective_test_labels_read": False,
                "prospective_test_label_paths_accepted": 0,
                "v4f_labels_read": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            summary_path = staging / SUMMARY_FILENAME
            write_json(summary_path, summary)
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "WAITING_NO_DEPLOYMENT_SCORES_PUBLISHED",
                "inputs": input_hashes(
                    support_metadata,
                    contact_metadata,
                    {
                        **governance_input_hashes,
                        str(Path(__file__).resolve()): sha256_file(Path(__file__)),
                    },
                ),
                "outputs": {
                    str((out_dir / SUMMARY_FILENAME).resolve()): sha256_file(summary_path)
                },
                "prospective_test_labels_read": False,
                "v4f_labels_read": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(staging / RECEIPT_FILENAME, receipt)
            publication = publish(
                staging,
                out_dir,
                (SUMMARY_FILENAME, RECEIPT_FILENAME),
                waiting=True,
            )
            return {
                "status": summary["status"],
                "summary": str((out_dir / SUMMARY_FILENAME).resolve()),
                "receipt": str((out_dir / RECEIPT_FILENAME).resolve()),
                "missing_model_artifacts": missing,
                "publication": publication,
            }

        stages = {
            stage: verify_stage_bundle(stage, directory)
            for stage, directory in directories.items()
        }
        bank = embedding.load_embedding_bank(
            embedding_manifest_path,
            embedding_summary_path,
            sequence_manifest_path,
            enforce_production_hashes=enforce_production_locks,
        )
        validate_contact_replay_identity(
            stages["contact"], bank, contact_metadata, stable_columns
        )
        replay = replay_predictions(
            scorable_candidates, contact_by_id, stable_columns, bank, stages
        )
        prediction_by_id = index_replayed_predictions(scorable_candidates, replay)
        model_gates_pass = all(bundle.open_gates_pass for bundle in stages.values())
        rows, routing = build_output_rows(
            candidates,
            support_by_id,
            governance_by_id,
            prediction_by_id,
            support_gates_pass=bool(support_metadata["all_gates_passed"]),
            model_gates_pass=model_gates_pass,
        )
        score_path = staging / SCORE_FILENAME
        summary_path = staging / SUMMARY_FILENAME
        write_tsv(score_path, rows)
        stage_provenance = {
            stage: {
                "directory": str(bundle.directory),
                "receipt": bundle.verification,
                "selected_model": replay["model_names"][stage],
                "open_gates_pass": bundle.open_gates_pass,
            }
            for stage, bundle in stages.items()
        }
        summary = {
            "schema_version": SCHEMA_VERSION,
            "status": (
                "PASS_DEPLOYMENT_SCORES_ROUTED"
                if routing["exploitation_count"] > 0
                else "PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED"
            ),
            "candidate_count": len(rows),
            "model_scored_candidate_count": len(scorable_candidates),
            "routing": routing,
            "support_release": support_metadata,
            "scoring_governance": governance_metadata,
            "model_stages": stage_provenance,
            "model_open_gates_all_passed": model_gates_pass,
            "prediction_aggregation": {
                "consensus_prediction": "arithmetic_mean_of_selected_base_embedding_contact_predictions",
                "ensemble_uncertainty": "root_mean_square_of_three_selected_model_bootstrap_standard_deviations",
                "model_disagreement": "population_standard_deviation_of_three_selected_model_predictions",
                "exploration_priority": "ensemble_uncertainty_plus_model_disagreement",
                "diversity": "required_downstream_constraint_not_collapsed_into_scalar_score",
            },
            "embedding_release": bank.provenance,
            "contact_feature_release": contact_metadata,
            "prospective_test_labels_read": False,
            "prospective_test_label_paths_accepted": 0,
            "v4f_labels_read": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        write_json(summary_path, summary)
        extra_inputs = {
            str((bundle.directory / STAGE_RECEIPTS[stage]).resolve()): sha256_file(
                bundle.directory / STAGE_RECEIPTS[stage]
            )
            for stage, bundle in stages.items()
        }
        extra_inputs.update(governance_input_hashes)
        extra_inputs[str(Path(__file__).resolve())] = sha256_file(Path(__file__))
        for bundle in stages.values():
            for record in bundle.verification["replay_inputs"].values():
                extra_inputs[str(record["path"])] = str(record["sha256"])
        for record in (
            bank.provenance["embedding_manifest"],
            bank.provenance["embedding_summary"],
            bank.provenance["sequence_manifest"],
            *bank.provenance["shards"].values(),
        ):
            extra_inputs[str(record["path"])] = str(record["sha256"])
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_DEPLOYMENT_SCORING_HASH_CLOSURE",
            "inputs": input_hashes(
                support_metadata, contact_metadata, extra_inputs
            ),
            "outputs": {
                str((out_dir / SCORE_FILENAME).resolve()): sha256_file(score_path),
                str((out_dir / SUMMARY_FILENAME).resolve()): sha256_file(summary_path),
            },
            "candidate_count": len(rows),
            "model_scored_candidate_count": len(scorable_candidates),
            "no_score_identity_only_count": len(rows) - len(scorable_candidates),
            "exploitation_count": routing["exploitation_count"],
            "prospective_test_labels_read": False,
            "prospective_test_label_paths_accepted": 0,
            "v4f_labels_read": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        write_json(staging / RECEIPT_FILENAME, receipt)
        publication = publish(
            staging,
            out_dir,
            OUTPUT_FILENAMES,
            waiting=False,
        )
        return {
            "status": summary["status"],
            "scores": str((out_dir / SCORE_FILENAME).resolve()),
            "summary": str((out_dir / SUMMARY_FILENAME).resolve()),
            "receipt": str((out_dir / RECEIPT_FILENAME).resolve()),
            "routing": routing,
            "publication": publication,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--support-csv", type=Path, default=DEFAULT_SUPPORT_CSV)
    parser.add_argument("--support-audit", type=Path, default=DEFAULT_SUPPORT_AUDIT)
    parser.add_argument("--support-receipt", type=Path, default=DEFAULT_SUPPORT_RECEIPT)
    parser.add_argument("--v4d-manifest", type=Path, default=DEFAULT_V4D_MANIFEST)
    parser.add_argument("--v4d-audit", type=Path, default=DEFAULT_V4D_AUDIT)
    parser.add_argument("--v4f-manifest", type=Path, default=DEFAULT_V4F_MANIFEST)
    parser.add_argument("--v4f-audit", type=Path, default=DEFAULT_V4F_AUDIT)
    parser.add_argument("--v4f-receipt", type=Path, default=DEFAULT_V4F_RECEIPT)
    parser.add_argument("--v4g-reserve", type=Path, default=DEFAULT_V4G_RESERVE)
    parser.add_argument(
        "--v4g-preregistration", type=Path, default=DEFAULT_V4G_PREREGISTRATION
    )
    parser.add_argument("--v4g-receipt", type=Path, default=DEFAULT_V4G_RECEIPT)
    parser.add_argument("--contact-receipt", type=Path, default=contact.DEFAULT_CONTACT_RECEIPT)
    parser.add_argument("--contact-schema", type=Path, default=contact.DEFAULT_CONTACT_SCHEMA)
    parser.add_argument("--embedding-manifest", type=Path, default=DEFAULT_EMBEDDING_MANIFEST)
    parser.add_argument("--embedding-summary", type=Path, default=DEFAULT_EMBEDDING_SUMMARY)
    parser.add_argument("--sequence-manifest", type=Path, default=DEFAULT_SEQUENCE_MANIFEST)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--embedding-dir", type=Path, default=DEFAULT_EMBEDDING_DIR)
    parser.add_argument("--contact-dir", type=Path, default=DEFAULT_CONTACT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only:
        print(
            json.dumps(
                verify_published_release(args.out_dir),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    result = run_pipeline(
        args.candidate_pool,
        args.support_csv,
        args.support_audit,
        args.support_receipt,
        args.v4d_manifest,
        args.v4d_audit,
        args.v4f_manifest,
        args.v4f_audit,
        args.v4f_receipt,
        args.v4g_reserve,
        args.v4g_preregistration,
        args.v4g_receipt,
        args.contact_receipt,
        args.contact_schema,
        args.embedding_manifest,
        args.embedding_summary,
        args.sequence_manifest,
        args.base_dir,
        args.embedding_dir,
        args.contact_dir,
        args.out_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
