#!/usr/bin/env python3
"""Validation and atomic-state helpers for the V4-D surrogate watcher."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "phase2_v4_d_surrogate_training_watcher_v1"
TRAIN_SPLIT = "OPEN_TRAIN"
DEVELOPMENT_SPLIT = "OPEN_DEVELOPMENT"
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
OPEN_SPLITS = frozenset((TRAIN_SPLIT, DEVELOPMENT_SPLIT))

PRODUCTION_LOCKS: dict[str, Any] = {
    "split_manifest_sha256": "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd",
    "feature_schema_sha256": "22d11cdccb0af6ecb26eb3bdcbae6c35dc5bc57543d662cf9da94155ee746cc0",
    "feature_schema_receipt_sha256": "93bd2427ae0f1205a0055d8913d8d1c0473b97c316b9120632a2d2bdebf16203",
    "contact_feature_csv_sha256": "f48de64d253a76bc9cff19ab1348c1655be7306828289b28f9a04e5b95471e7d",
    "contact_feature_audit_sha256": "eb63f16aacef2ed3d7ed0a755bfc3c49a590e09248b28643b94dc7e2c4e27e29",
    "contact_feature_receipt_sha256": "b12c0ff0ce6760db7169ec3616dddaf05786e5ca795354f639ef2bf87c370e2b",
    "embedding_manifest_sha256": "875bb5304235ff08493919e1603bf5b9a8ef04774416e47c1d851d7a2d614521",
    "embedding_summary_sha256": "0b5a5f01d82775ada2ed3bd505011a954be0c69fe73a2918a0c0c9c87b7af49c",
    "embedding_sequence_manifest_sha256": "c456ec7cb4dd36df0a9e95e103ad2f9b597eebcee43281cfd6c06dc99ea06297",
    "embedding_config_sha256": "e525cb725bc5b9ea93c2f91ba84209cc3992d1e65e0e0d78f79b7c219ba33636",
    "embedding_shards": {
        "shard_00000.pt": "731af1d81210f8443065c36fa8fe0472e62f2f5093d3404c2bdc6bbcb57a1465",
        "shard_00001.pt": "3b08d1b685904bfad485b377541b3c9477a3082e7b017a53b7b5ca2396732f1",
        "shard_00002.pt": "b1041c04293a1ea3ad7f094f6185731921f9d964123ca42f524eae126f930e10",
        "shard_00003.pt": "ba8b7305eb75b38d72ba12b5bf965128e41d7940b9f87351607b1e5e856349bf",
        "shard_00004.pt": "b63998c6c00f6a2524460143be7fc2453ff77b8fc4671d8c94d5bdaf20f2f204",
        "shard_00005.pt": "34fd3f75bd52fc274ccdb7bf2b52aba05b916d4edc9aaa13fc9d2f61e52e512a",
        "shard_00006.pt": "a3779bb01273d173e9e4424e587a999171d1960ec03bb833f75823e8f060b7e9",
    },
    "split_counts": {TRAIN_SPLIT: 226, DEVELOPMENT_SPLIT: 32, SEALED_SPLIT: 32},
    "open_teacher_count": 258,
    "contact_feature_count": 7087,
    "embedding_sequence_count": 7088,
    "raw_open_job_count": 1548,
}

MANIFEST_CLOSURE_FIELDS = (
    "candidate_id",
    "model_split",
    "parent_framework_cluster",
    "sequence_sha256",
    "sequence",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
)
FORBIDDEN_TEACHER_SPLITS = frozenset((SEALED_SPLIT, "test", "TEST"))
FORBIDDEN_PREDICTION_COLUMNS = (
    "target_",
    "label",
    "observed_",
    "true_",
    "r_dual_min",
)
BASE_OUTPUTS = (
    "frozen_open_model_config.json",
    "frozen_open_model_artifact.json",
    "open_development_predictions.tsv",
    "open_development_summary.json",
)
EMBEDDING_OUTPUTS = (
    "frozen_embedding_model_config.json",
    "frozen_embedding_model_artifact.json",
    "open_development_embedding_predictions.tsv",
    "frozen_prospective_test_predictions.tsv",
    "open_development_embedding_summary.json",
)
CONTACT_OUTPUTS = (
    "contact_fusion_open_model_config.json",
    "contact_fusion_open_model_artifact.json",
    "contact_fusion_open_development_predictions.tsv",
    "contact_fusion_open_development_summary.json",
)


class WatcherError(RuntimeError):
    pass


class WaitingInput(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WatcherError(f"invalid_json:{label}:{path}") from exc
    if not isinstance(payload, dict):
        raise WatcherError(f"json_not_object:{label}:{path}")
    return payload


def read_table(path: Path, delimiter: str) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
    except OSError as exc:
        raise WatcherError(f"cannot_read_table:{path}") from exc
    if not fields:
        raise WatcherError(f"empty_table_header:{path}")
    return rows, fields


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WatcherError(message)


def required_file(path: Path, label: str) -> None:
    require(path.is_file() and path.stat().st_size > 0, f"missing_or_empty:{label}:{path}")


def validate_locked_hash(path: Path, expected: str, label: str) -> str:
    required_file(path, label)
    observed = sha256_file(path)
    require(observed == expected, f"hash_mismatch:{label}:{observed}:{expected}")
    return observed


def load_locks(path: Path | None) -> tuple[dict[str, Any], str]:
    if path is None:
        return PRODUCTION_LOCKS, "production"
    locks = load_json(path, "test_hash_locks")
    required = set(PRODUCTION_LOCKS) - {"embedding_shards"}
    require(required <= set(locks), "test_hash_locks_missing_fields")
    require(isinstance(locks.get("embedding_shards"), dict), "test_shard_locks_invalid")
    return locks, "test_fixture"


def validate_split_manifest(
    path: Path, locks: Mapping[str, Any]
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    validate_locked_hash(path, str(locks["split_manifest_sha256"]), "split_manifest")
    rows, fields = read_table(path, "\t")
    require(set(MANIFEST_CLOSURE_FIELDS) <= set(fields), "split_manifest_fields_missing")
    label_columns = {
        "R_dual_min",
        "target_R_dual_min",
        "geometry_tier",
        "consensus_geometry_tier",
    }
    require(not (label_columns & set(fields)), "split_manifest_contains_test_labels")
    expected_counts = {str(k): int(v) for k, v in locks["split_counts"].items()}
    counts = Counter(row.get("model_split", "") for row in rows)
    require(dict(counts) == expected_counts, f"split_counts_mismatch:{dict(counts)}")
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in by_id, f"duplicate_split_id:{candidate_id}")
        sequence = row.get("sequence", "").strip().upper()
        require(sequence, f"empty_split_sequence:{candidate_id}")
        require(
            hashlib.sha256(sequence.encode("ascii")).hexdigest()
            == row.get("sequence_sha256", ""),
            f"split_sequence_hash_mismatch:{candidate_id}",
        )
        by_id[candidate_id] = row
    return rows, by_id


def validate_open_teacher(
    teacher_path: Path,
    audit_path: Path,
    receipt_path: Path,
    split_by_id: Mapping[str, Mapping[str, str]],
    locks: Mapping[str, Any],
) -> dict[str, Any]:
    teacher_rows, fields = read_table(teacher_path, "\t")
    require(set(MANIFEST_CLOSURE_FIELDS) <= set(fields), "teacher_fields_missing")
    require("R_dual_min" in fields, "teacher_primary_target_missing")
    require(len(teacher_rows) == int(locks["open_teacher_count"]), "teacher_row_count_mismatch")
    counts = Counter(row.get("model_split", "") for row in teacher_rows)
    expected_counts = {
        split: int(locks["split_counts"][split]) for split in sorted(OPEN_SPLITS)
    }
    require(dict(counts) == expected_counts, f"teacher_split_counts_mismatch:{dict(counts)}")
    require(not (set(counts) & FORBIDDEN_TEACHER_SPLITS), "teacher_contains_sealed_split")
    expected_ids = {
        candidate_id
        for candidate_id, row in split_by_id.items()
        if row["model_split"] in OPEN_SPLITS
    }
    observed_ids: set[str] = set()
    for row in teacher_rows:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id and candidate_id not in observed_ids, f"duplicate_teacher_id:{candidate_id}")
        observed_ids.add(candidate_id)
        require(candidate_id in expected_ids, f"teacher_candidate_not_open:{candidate_id}")
        source = split_by_id[candidate_id]
        for field in MANIFEST_CLOSURE_FIELDS:
            require(
                row.get(field, "").strip() == str(source.get(field, "")).strip(),
                f"teacher_manifest_closure_mismatch:{candidate_id}:{field}",
            )
        try:
            float(row["R_dual_min"])
        except (KeyError, ValueError) as exc:
            raise WatcherError(f"teacher_target_invalid:{candidate_id}") from exc
    require(observed_ids == expected_ids, "teacher_open_id_set_mismatch")

    audit = load_json(audit_path, "teacher_audit")
    require(
        audit.get("status") == "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
        "teacher_audit_status_not_pass",
    )
    require(
        audit.get("release") == "open_train_and_open_development_only",
        "teacher_audit_release_invalid",
    )
    require(int(audit.get("row_count", -1)) == len(teacher_rows), "teacher_audit_count_mismatch")
    sealed = audit.get("sealed_data_boundary") or {}
    require(sealed.get("model_split") == SEALED_SPLIT, "teacher_audit_sealed_split_invalid")
    require(int(sealed.get("raw_job_results_opened", -1)) == 0, "sealed_raw_results_opened")
    require(
        sealed.get("sealed_metrics_used_for_teacher_or_ranking") is False,
        "sealed_metrics_used",
    )
    require(
        (audit.get("inputs") or {}).get("split_manifest_sha256")
        == locks["split_manifest_sha256"],
        "teacher_audit_split_hash_mismatch",
    )
    closure = (audit.get("inputs") or {}).get("raw_aggregate_closure") or {}
    require(
        closure.get("status") == "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
        "teacher_raw_closure_status_invalid",
    )
    require(
        int(closure.get("job_count", -1)) == int(locks["raw_open_job_count"]),
        "teacher_raw_closure_job_count_invalid",
    )

    receipt = load_json(receipt_path, "postprocess_receipt")
    require(
        receipt.get("status") == "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
        "postprocess_receipt_status_invalid",
    )
    require(int(receipt.get("row_count", -1)) == len(teacher_rows), "receipt_count_mismatch")
    require(receipt.get("teacher_sha256") == sha256_file(teacher_path), "receipt_teacher_hash_mismatch")
    require(
        receipt.get("teacher_audit_sha256") == sha256_file(audit_path),
        "receipt_teacher_audit_hash_mismatch",
    )
    require(
        int(receipt.get("sealed_test_raw_job_results_opened", -1)) == 0,
        "receipt_sealed_results_opened",
    )
    require(
        receipt.get("sealed_metrics_used_for_teacher_or_ranking") is False,
        "receipt_sealed_metrics_used",
    )
    require(
        receipt.get("raw_aggregate_closure_sha256") == closure.get("closure_sha256"),
        "receipt_raw_closure_mismatch",
    )
    return {
        "row_count": len(teacher_rows),
        "split_counts": dict(counts),
        "teacher_sha256": sha256_file(teacher_path),
        "teacher_audit_sha256": sha256_file(audit_path),
        "release_receipt_sha256": sha256_file(receipt_path),
        "raw_aggregate_closure_sha256": closure.get("closure_sha256"),
    }


def validate_frozen_feature_schema(
    schema_path: Path,
    schema_receipt_path: Path,
    locks: Mapping[str, Any],
) -> dict[str, Any]:
    hashes = {
        "feature_schema": validate_locked_hash(
            schema_path, str(locks["feature_schema_sha256"]), "feature_schema"
        ),
        "feature_schema_receipt": validate_locked_hash(
            schema_receipt_path,
            str(locks["feature_schema_receipt_sha256"]),
            "feature_schema_receipt",
        ),
    }
    schema = load_json(schema_path, "feature_schema")
    require(
        schema.get("schema_version") == "phase2_v4_d_contact_feature_schema_v2"
        and schema.get("status") == "PASS_FROZEN_LABEL_FREE_CONTACT_FEATURE_SCHEMA",
        "feature_schema_status_invalid",
    )
    require(int(schema.get("selected_feature_count", -1)) == 12, "selected_feature_count_invalid")
    selected = schema.get("selected_features")
    require(isinstance(selected, list) and len(selected) == 12, "selected_features_invalid")
    schema_receipt = load_json(schema_receipt_path, "feature_schema_receipt")
    require(
        schema_receipt.get("schema_version") == "phase2_v4_d_contact_feature_schema_receipt_v2"
        and schema_receipt.get("status") == "PASS_COMPLETE_HASH_CLOSURE",
        "feature_schema_receipt_status_invalid",
    )
    require(schema_receipt.get("schema_file_sha256") == hashes["feature_schema"], "schema_receipt_hash_mismatch")
    require(schema_receipt.get("feature_csv_sha256") == locks["contact_feature_csv_sha256"], "schema_feature_hash_mismatch")
    require(schema_receipt.get("feature_audit_sha256") == locks["contact_feature_audit_sha256"], "schema_audit_hash_mismatch")
    require(
        schema_receipt.get("feature_release_receipt_sha256")
        == locks["contact_feature_receipt_sha256"],
        "schema_release_receipt_hash_mismatch",
    )
    return {"hashes": hashes, "selected_features": selected}


def validate_feature_bundle(
    schema_path: Path,
    schema_receipt_path: Path,
    feature_path: Path,
    feature_audit_path: Path,
    feature_receipt_path: Path,
    feature_verification_path: Path,
    locks: Mapping[str, Any],
) -> dict[str, Any]:
    frozen = validate_frozen_feature_schema(schema_path, schema_receipt_path, locks)
    hashes = {
        **frozen["hashes"],
        "contact_feature_csv": validate_locked_hash(
            feature_path,
            str(locks["contact_feature_csv_sha256"]),
            "contact_feature_csv",
        ),
        "contact_feature_audit": validate_locked_hash(
            feature_audit_path,
            str(locks["contact_feature_audit_sha256"]),
            "contact_feature_audit",
        ),
        "contact_feature_receipt": validate_locked_hash(
            feature_receipt_path,
            str(locks["contact_feature_receipt_sha256"]),
            "contact_feature_receipt",
        ),
    }
    required_file(feature_verification_path, "contact_feature_verification")
    selected = frozen["selected_features"]

    feature_receipt = load_json(feature_receipt_path, "contact_feature_receipt")
    require(
        feature_receipt.get("status") == "PASS"
        and feature_receipt.get("schema_version")
        == "pvrig_candidate_v2_3_label_free_residue_contact_release_receipt_v1"
        and feature_receipt.get("feature_schema_version")
        == "pvrig_candidate_v2_3_label_free_residue_contact_features_v3",
        "contact_feature_receipt_status_invalid",
    )
    require(
        int(feature_receipt.get("output_row_count", -1))
        == int(locks["contact_feature_count"]),
        "contact_feature_receipt_count_invalid",
    )
    require(feature_receipt.get("output_sha256") == hashes["contact_feature_csv"], "contact_output_hash_mismatch")
    require(feature_receipt.get("audit_sha256") == hashes["contact_feature_audit"], "contact_audit_hash_mismatch")

    verification = load_json(feature_verification_path, "contact_feature_verification")
    require(
        verification.get("status") == "PASS"
        and verification.get("schema_version")
        == "pvrig_candidate_v2_3_label_free_residue_contact_release_verification_v1",
        "contact_feature_verification_status_invalid",
    )
    require(
        verification.get("receipt_sha256") == hashes["contact_feature_receipt"],
        "contact_verification_receipt_hash_mismatch",
    )
    require(
        verification.get("output_sha256") == hashes["contact_feature_csv"]
        and verification.get("audit_sha256") == hashes["contact_feature_audit"],
        "contact_verification_output_closure_mismatch",
    )
    require(
        int(verification.get("row_count", -1)) == int(locks["contact_feature_count"]),
        "contact_verification_count_invalid",
    )
    audit = load_json(feature_audit_path, "contact_feature_audit")
    contract = audit.get("label_free_contract") or {}
    require(
        audit.get("status") == "PASS"
        and int(contract.get("docking_label_inputs_read", -1)) == 0
        and int(contract.get("v4d_raw_results_read", -1)) == 0,
        "contact_feature_label_free_boundary_invalid",
    )
    rows, fields = read_table(feature_path, ",")
    require(len(rows) == int(locks["contact_feature_count"]), "contact_feature_csv_count_invalid")
    lowered = [field.lower() for field in fields]
    require(
        not any(
            token in field
            for field in lowered
            for token in ("docking_label", "teacher_label", "r_dual_min", "geometry_tier")
        ),
        "contact_features_contain_docking_labels",
    )
    return {"hashes": hashes, "selected_features": selected, "row_count": len(rows)}


def validate_embedding_bundle(
    manifest_path: Path,
    summary_path: Path,
    sequence_manifest_path: Path,
    shard_dir: Path,
    locks: Mapping[str, Any],
) -> dict[str, Any]:
    hashes = {
        "embedding_manifest": validate_locked_hash(
            manifest_path, str(locks["embedding_manifest_sha256"]), "embedding_manifest"
        ),
        "embedding_summary": validate_locked_hash(
            summary_path, str(locks["embedding_summary_sha256"]), "embedding_summary"
        ),
        "embedding_sequence_manifest": validate_locked_hash(
            sequence_manifest_path,
            str(locks["embedding_sequence_manifest_sha256"]),
            "embedding_sequence_manifest",
        ),
    }
    summary = load_json(summary_path, "embedding_summary")
    require(summary.get("schema_version") == "phase2_v3_embedding_summary_v1", "embedding_summary_schema_invalid")
    require(summary.get("embedding_manifest_sha256") == hashes["embedding_manifest"], "embedding_summary_manifest_hash_mismatch")
    require(summary.get("sequence_manifest_sha256") == hashes["embedding_sequence_manifest"], "embedding_summary_sequence_hash_mismatch")
    require(summary.get("config_sha256") == locks["embedding_config_sha256"], "embedding_config_hash_mismatch")
    require(int(summary.get("sequence_count", -1)) == int(locks["embedding_sequence_count"]), "embedding_sequence_count_invalid")
    expected_shards = {str(k): str(v) for k, v in locks["embedding_shards"].items()}
    observed_shards = {}
    for name, expected in sorted(expected_shards.items()):
        observed_shards[name] = validate_locked_hash(shard_dir / name, expected, f"embedding_shard:{name}")
    actual_names = {path.name for path in shard_dir.glob("*.pt") if path.is_file()}
    require(actual_names == set(expected_shards), "embedding_shard_set_mismatch")
    hashes["embedding_shards"] = observed_shards
    return {"hashes": hashes, "config_sha256": summary["config_sha256"]}


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    teacher_files = {
        "teacher": args.teacher,
        "teacher_audit": args.teacher_audit,
        "release_receipt": args.release_receipt,
    }
    missing = [name for name, path in teacher_files.items() if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise WaitingInput("WAITING_OPEN_TEACHER", "missing:" + ",".join(sorted(missing)))
    locks, mode = load_locks(args.test_only_hash_locks)
    split_rows, split_by_id = validate_split_manifest(args.split_manifest, locks)
    teacher = validate_open_teacher(
        args.teacher, args.teacher_audit, args.release_receipt, split_by_id, locks
    )
    features = validate_frozen_feature_schema(
        args.feature_schema,
        args.feature_schema_receipt,
        locks,
    )
    embeddings = validate_embedding_bundle(
        args.embedding_manifest,
        args.embedding_summary,
        args.embedding_sequence_manifest,
        args.embedding_shard_dir,
        locks,
    )
    files = {
        "teacher": args.teacher,
        "teacher_audit": args.teacher_audit,
        "release_receipt": args.release_receipt,
        "split_manifest": args.split_manifest,
        "feature_schema": args.feature_schema,
        "feature_schema_receipt": args.feature_schema_receipt,
        "embedding_manifest": args.embedding_manifest,
        "embedding_summary": args.embedding_summary,
        "embedding_sequence_manifest": args.embedding_sequence_manifest,
    }
    file_hashes = {name: sha256_file(path) for name, path in sorted(files.items())}
    file_hashes["embedding_shards"] = embeddings["hashes"]["embedding_shards"]
    closure = sha256_json(file_hashes)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_SURROGATE_TRAINING_PREFLIGHT_TEST32_SEALED",
        "execution_mode": mode,
        "split_rows": len(split_rows),
        "teacher": teacher,
        "features": features,
        "embeddings": embeddings,
        "input_hashes": file_hashes,
        "input_closure_sha256": closure,
        "prospective_test": {
            "split": SEALED_SPLIT,
            "manifest_rows": int(locks["split_counts"][SEALED_SPLIT]),
            "labels_read": False,
            "label_paths_accepted": 0,
        },
    }


def verify_contact_inputs(args: argparse.Namespace) -> dict[str, Any]:
    paths = (
        args.contact_features,
        args.contact_feature_audit,
        args.contact_feature_receipt,
        args.contact_feature_verification,
    )
    if any(not path.is_file() or path.stat().st_size == 0 for path in paths):
        raise WaitingInput(
            "WAITING_CONTACT_TRAINER",
            "V3 contact release receipt/verification is not complete",
        )
    locks, mode = load_locks(args.test_only_hash_locks)
    result = validate_feature_bundle(
        args.feature_schema,
        args.feature_schema_receipt,
        args.contact_features,
        args.contact_feature_audit,
        args.contact_feature_receipt,
        args.contact_feature_verification,
        locks,
    )
    hashes = {
        "feature_schema": sha256_file(args.feature_schema),
        "feature_schema_receipt": sha256_file(args.feature_schema_receipt),
        "contact_features": sha256_file(args.contact_features),
        "contact_feature_audit": sha256_file(args.contact_feature_audit),
        "contact_feature_receipt": sha256_file(args.contact_feature_receipt),
        "contact_feature_verification": sha256_file(args.contact_feature_verification),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_CONTACT_INPUTS_VERIFIED_LABEL_FREE",
        "execution_mode": mode,
        "inputs": result,
        "input_hashes": hashes,
        "input_closure_sha256": sha256_json(hashes),
        "prospective_test_labels_read": False,
    }
def validate_output_hashes(receipt: Mapping[str, Any], out_dir: Path) -> None:
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict) and outputs, "stage_receipt_outputs_missing")
    for raw_path, expected in outputs.items():
        path = Path(str(raw_path))
        require(path.is_absolute(), f"stage_output_path_not_absolute:{path}")
        try:
            path.resolve().relative_to(out_dir.resolve())
        except ValueError as exc:
            raise WatcherError(f"stage_output_outside_directory:{path}") from exc
        required_file(path, "stage_output")
        require(sha256_file(path) == expected, f"stage_output_hash_mismatch:{path}")


def validate_prediction_only(path: Path) -> None:
    rows, fields = read_table(path, "\t")
    lower = [field.lower() for field in fields]
    require(
        not any(token in field for field in lower for token in FORBIDDEN_PREDICTION_COLUMNS),
        "prospective_predictions_contain_label_column",
    )
    require(rows and all(row.get("model_split") == SEALED_SPLIT for row in rows), "prospective_prediction_split_invalid")


def verify_stage(args: argparse.Namespace) -> dict[str, Any]:
    if args.stage == "base":
        receipt_path = args.out_dir / "frozen_open_artifact_sha256_receipt.json"
        summary_path = args.out_dir / "open_development_summary.json"
        expected_status = "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE"
        expected_outputs = BASE_OUTPUTS
    elif args.stage == "embedding":
        receipt_path = args.out_dir / "frozen_embedding_artifact_sha256_receipt.json"
        summary_path = args.out_dir / "open_development_embedding_summary.json"
        expected_status = "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE"
        expected_outputs = EMBEDDING_OUTPUTS
    else:
        receipt_path = args.out_dir / "contact_fusion_frozen_artifact_sha256_receipt.json"
        summary_path = args.out_dir / "contact_fusion_open_development_summary.json"
        expected_status = "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE"
        expected_outputs = CONTACT_OUTPUTS
    if not receipt_path.is_file():
        raise WaitingInput(f"WAITING_{args.stage.upper()}_TRAINER", f"missing:{receipt_path.name}")
    receipt = load_json(receipt_path, f"{args.stage}_receipt")
    require(receipt.get("status") == expected_status, f"{args.stage}_receipt_status_invalid")
    require(receipt.get("prospective_test_labels_read") is False, f"{args.stage}_test_labels_read")
    inputs = receipt.get("inputs")
    require(isinstance(inputs, dict), f"{args.stage}_receipt_inputs_missing")
    for path in args.expected_input:
        resolved = path.resolve()
        required_file(resolved, f"{args.stage}_expected_input")
        require(
            inputs.get(str(resolved)) == sha256_file(resolved),
            f"{args.stage}_receipt_input_hash_mismatch:{resolved}",
        )
    validate_output_hashes(receipt, args.out_dir)
    for name in expected_outputs:
        required_file(args.out_dir / name, f"{args.stage}_output:{name}")
    summary = load_json(summary_path, f"{args.stage}_summary")
    prospective = summary.get("prospective_test") or {}
    require(prospective.get("labels_read") is False, f"{args.stage}_summary_test_labels_read")
    require(int(prospective.get("label_files_opened", 0)) == 0, f"{args.stage}_summary_test_label_files_opened")
    if args.stage == "embedding":
        validate_prediction_only(args.out_dir / "frozen_prospective_test_predictions.tsv")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": f"PASS_{args.stage.upper()}_ARTIFACT_VERIFIED_TEST32_SEALED",
        "stage": args.stage,
        "scientific_gate_status": summary.get("status"),
        "receipt": str(receipt_path.resolve()),
        "receipt_sha256": sha256_file(receipt_path),
        "prospective_test_labels_read": False,
    }


def compare_preflight(args: argparse.Namespace) -> dict[str, Any]:
    left = load_json(args.before, "preflight_before")
    right = load_json(args.after, "preflight_after")
    require(left.get("status") and right.get("status") == left.get("status"), "preflight_status_invalid")
    require(
        left.get("input_closure_sha256") == right.get("input_closure_sha256"),
        "preflight_input_closure_changed",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREFLIGHT_INPUTS_UNCHANGED",
        "input_closure_sha256": left["input_closure_sha256"],
    }


def write_state(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": args.status,
        "reason": args.reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "controller_pid": args.controller_pid,
        "prospective_test_labels_read": False,
        "prospective_test_label_paths_accepted": 0,
        "claim_boundary": (
            "Fixed-PVRIG sequence-to-independent-dual-docking computational geometry "
            "surrogate training only; not binding, affinity, competition, Docking Gold, "
            "or experimental blocking truth."
        ),
    }
    for field in ("preflight", "base", "embedding", "contact"):
        path = getattr(args, field)
        if path is not None and path.is_file():
            payload[field] = load_json(path, f"state_{field}")
    atomic_write_json(args.path, payload)
    return payload


def add_preflight_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-audit", type=Path, required=True)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--feature-schema", type=Path, required=True)
    parser.add_argument("--feature-schema-receipt", type=Path, required=True)
    parser.add_argument("--contact-features", type=Path, required=True)
    parser.add_argument("--contact-feature-audit", type=Path, required=True)
    parser.add_argument("--contact-feature-receipt", type=Path, required=True)
    parser.add_argument("--contact-feature-verification", type=Path, required=True)
    parser.add_argument("--embedding-manifest", type=Path, required=True)
    parser.add_argument("--embedding-summary", type=Path, required=True)
    parser.add_argument("--embedding-sequence-manifest", type=Path, required=True)
    parser.add_argument("--embedding-shard-dir", type=Path, required=True)
    parser.add_argument("--test-only-hash-locks", type=Path)


def add_contact_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--feature-schema", type=Path, required=True)
    parser.add_argument("--feature-schema-receipt", type=Path, required=True)
    parser.add_argument("--contact-features", type=Path, required=True)
    parser.add_argument("--contact-feature-audit", type=Path, required=True)
    parser.add_argument("--contact-feature-receipt", type=Path, required=True)
    parser.add_argument("--contact-feature-verification", type=Path, required=True)
    parser.add_argument("--test-only-hash-locks", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    add_preflight_arguments(preflight_parser)
    contact_parser = subparsers.add_parser("verify-contact-inputs")
    add_contact_arguments(contact_parser)
    verify_parser = subparsers.add_parser("verify-stage")
    verify_parser.add_argument("--stage", choices=("base", "embedding", "contact"), required=True)
    verify_parser.add_argument("--out-dir", type=Path, required=True)
    verify_parser.add_argument("--expected-input", type=Path, action="append", default=[])
    compare_parser = subparsers.add_parser("compare-preflight")
    compare_parser.add_argument("--before", type=Path, required=True)
    compare_parser.add_argument("--after", type=Path, required=True)
    state_parser = subparsers.add_parser("write-state")
    state_parser.add_argument("--path", type=Path, required=True)
    state_parser.add_argument("--status", required=True)
    state_parser.add_argument("--reason", required=True)
    state_parser.add_argument("--controller-pid", type=int, required=True)
    for field in ("preflight", "base", "embedding", "contact"):
        state_parser.add_argument(f"--{field}", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args)
        elif args.command == "verify-contact-inputs":
            result = verify_contact_inputs(args)
        elif args.command == "verify-stage":
            result = verify_stage(args)
        elif args.command == "compare-preflight":
            result = compare_preflight(args)
        else:
            result = write_state(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except WaitingInput as exc:
        print(json.dumps({"status": exc.status, "reason": exc.reason}, sort_keys=True))
        return 4
    except (WatcherError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED_VALIDATION", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
