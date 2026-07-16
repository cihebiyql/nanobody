#!/usr/bin/env python3
"""Freeze label-free V4-F predictions from completed V4-D surrogate artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v4_d_contact_feature_surrogate as contact  # noqa: E402
import train_phase2_v4_d_frozen_embedding_surrogate as embedding  # noqa: E402
import train_phase2_v4_d_surrogate as base  # noqa: E402


SCHEMA_VERSION = "phase2_v4_f_frozen_surrogate_predictions_v1"
MODEL_SPLIT = "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT"
EXPECTED_MANIFEST_SHA256 = "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334"
EXPECTED_AUDIT_SHA256 = "fc24cc2bd203100e29be897e87850a67ddc362b1fa1635d4172ec4335f5083a1"
EXPECTED_MANIFEST_RECEIPT_SHA256 = (
    "3adc1e3194bdc5846f35b99020c3c996859caf3e3abc2b8e02df6ac75296512f"
)
EXPECTED_ROW_COUNT = 96
OUTPUT_FILENAMES = (
    "v4_f_96_frozen_surrogate_predictions.tsv",
    "v4_f_96_frozen_surrogate_predictions.audit.json",
    "v4_f_96_frozen_surrogate_predictions.receipt.json",
)
FORBIDDEN_MANIFEST_FIELDS = {
    "R_dual_min",
    "target_R_dual_min",
    "geometry_tier",
    "consensus_geometry_tier",
    "docking_label",
    "experimental_blocking",
}
FORBIDDEN_OUTPUT_FIELDS = {
    "R_dual_min",
    "target_R_dual_min",
    "geometry_tier",
    "consensus_geometry_tier",
    "docking_label",
    "experimental_blocking",
}
IDENTITY_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "model_split",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr3_length",
)
CLAIM_BOUNDARY = (
    "Frozen label-free predictions of fixed dual-Docking computational geometry for the "
    "prospective V4-F panel; not binding, affinity, competition, Docking Gold, or "
    "experimental blocking truth."
)


class PredictionFreezeError(RuntimeError):
    pass


class WaitingForSurrogates(PredictionFreezeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PredictionFreezeError(f"invalid_json:{label}:{path}") from exc
    if not isinstance(payload, dict):
        raise PredictionFreezeError(f"json_not_object:{label}:{path}")
    return payload


def read_table(path: Path, delimiter: str) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
    except OSError as exc:
        raise PredictionFreezeError(f"cannot_read_table:{path}") from exc
    if not fields:
        raise PredictionFreezeError(f"table_header_missing:{path}")
    return rows, fields


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PredictionFreezeError(message)


def required_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise PredictionFreezeError(f"missing_or_empty:{label}:{path}")


def required_surrogate_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise WaitingForSurrogates(f"missing_or_empty:{label}:{path}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PredictionFreezeError("cannot_write_empty_predictions")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


@contextmanager
def publication_lock(out_dir: Path):
    import fcntl

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir.parent / f".{out_dir.name}.prediction-freeze.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PredictionFreezeError("prediction_freezer_already_running") from exc
        yield


def validate_holdout(
    manifest_path: Path,
    audit_path: Path,
    receipt_path: Path,
    *,
    enforce_production_hashes: bool,
    expected_count: int,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    for path, label in (
        (manifest_path, "v4f_manifest"),
        (audit_path, "v4f_audit"),
        (receipt_path, "v4f_manifest_receipt"),
    ):
        required_file(path, label)
    hashes = {
        "manifest": sha256_file(manifest_path),
        "audit": sha256_file(audit_path),
        "manifest_receipt": sha256_file(receipt_path),
    }
    if enforce_production_hashes:
        require(hashes["manifest"] == EXPECTED_MANIFEST_SHA256, "v4f_manifest_hash_mismatch")
        require(hashes["audit"] == EXPECTED_AUDIT_SHA256, "v4f_audit_hash_mismatch")
        require(
            hashes["manifest_receipt"] == EXPECTED_MANIFEST_RECEIPT_SHA256,
            "v4f_manifest_receipt_hash_mismatch",
        )
    rows, fields = read_table(manifest_path, "\t")
    required = {
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
    }
    require(required <= set(fields), "v4f_manifest_fields_missing")
    require(not (FORBIDDEN_MANIFEST_FIELDS & set(fields)), "v4f_manifest_contains_labels")
    require(len(rows) == expected_count, f"v4f_manifest_row_count:{len(rows)}")
    ids: set[str] = set()
    sequence_hashes: set[str] = set()
    for row in rows:
        candidate_id = row["candidate_id"].strip()
        sequence = row["sequence"].strip().upper()
        digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        require(candidate_id and candidate_id not in ids, f"v4f_duplicate_id:{candidate_id}")
        require(digest == row["sequence_sha256"], f"v4f_sequence_hash_mismatch:{candidate_id}")
        require(digest not in sequence_hashes, f"v4f_duplicate_sequence:{candidate_id}")
        require(row["model_split"] == MODEL_SPLIT, f"v4f_split_mismatch:{candidate_id}")
        ids.add(candidate_id)
        sequence_hashes.add(digest)
    audit = load_json(audit_path, "v4f_audit")
    require(audit.get("status") == "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN", "v4f_audit_status_invalid")
    require((audit.get("output") or {}).get("sha256") == hashes["manifest"], "v4f_audit_manifest_hash_mismatch")
    require(int((audit.get("checks") or {}).get("row_count", -1)) == expected_count, "v4f_audit_count_mismatch")
    policy = audit.get("future_release_policy") or {}
    require(
        policy.get("labels")
        == "do not compute or open before model/config/test predictions are frozen",
        "v4f_audit_label_policy_invalid",
    )
    receipt = load_json(receipt_path, "v4f_manifest_receipt")
    require(receipt.get("status") == "PASS_COMPLETE_HASH_CLOSURE", "v4f_manifest_receipt_status_invalid")
    require(receipt.get("manifest_sha256") == hashes["manifest"], "v4f_receipt_manifest_hash_mismatch")
    require(receipt.get("audit_file_sha256") == hashes["audit"], "v4f_receipt_audit_hash_mismatch")
    return rows, hashes


STAGE_CONTRACTS = {
    "base": {
        "config": "frozen_open_model_config.json",
        "artifact": "frozen_open_model_artifact.json",
        "development_predictions": "open_development_predictions.tsv",
        "summary": "open_development_summary.json",
        "receipt": "frozen_open_artifact_sha256_receipt.json",
        "receipt_status": "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE",
    },
    "embedding": {
        "config": "frozen_embedding_model_config.json",
        "artifact": "frozen_embedding_model_artifact.json",
        "development_predictions": "open_development_embedding_predictions.tsv",
        "prospective_predictions": "frozen_prospective_test_predictions.tsv",
        "summary": "open_development_embedding_summary.json",
        "receipt": "frozen_embedding_artifact_sha256_receipt.json",
        "receipt_status": "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE",
    },
    "contact": {
        "config": "contact_fusion_open_model_config.json",
        "artifact": "contact_fusion_open_model_artifact.json",
        "development_predictions": "contact_fusion_open_development_predictions.tsv",
        "summary": "contact_fusion_open_development_summary.json",
        "receipt": "contact_fusion_frozen_artifact_sha256_receipt.json",
        "receipt_status": "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE",
    },
}


def validate_stage(out_dir: Path, stage: str) -> dict[str, Any]:
    contract = STAGE_CONTRACTS[stage]
    paths = {
        name: out_dir / filename
        for name, filename in contract.items()
        if name not in {"receipt_status"}
    }
    for name, path in paths.items():
        required_surrogate_file(path, f"{stage}_{name}")
    receipt = load_json(paths["receipt"], f"{stage}_receipt")
    require(receipt.get("status") == contract["receipt_status"], f"{stage}_receipt_status_invalid")
    require(receipt.get("prospective_test_labels_read") is False, f"{stage}_receipt_test_labels_read")
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict), f"{stage}_receipt_outputs_missing")
    expected_output_paths = {
        str(path.resolve()) for name, path in paths.items() if name != "receipt"
    }
    require(set(outputs) == expected_output_paths, f"{stage}_receipt_output_set_mismatch")
    for name, path in paths.items():
        if name == "receipt":
            continue
        path = paths[name].resolve()
        require(outputs.get(str(path)) == sha256_file(path), f"{stage}_{name}_receipt_hash_mismatch")
    summary = load_json(paths["summary"], f"{stage}_summary")
    prospective = summary.get("prospective_test") or {}
    require(prospective.get("labels_read") is False, f"{stage}_summary_test_labels_read")
    require(int(prospective.get("label_files_opened", 0)) == 0, f"{stage}_summary_test_files_opened")
    return {
        "paths": paths,
        "hashes": {name: sha256_file(path) for name, path in paths.items()},
        "scientific_gate_status": summary.get("status"),
    }


def validate_contact_artifact(path: Path, config_hash: str) -> dict[str, Any]:
    artifact = load_json(path, "contact_artifact")
    require(
        artifact.get("schema_version") == contact.SCHEMA_VERSION
        and artifact.get("status") == "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
        "contact_artifact_status_invalid",
    )
    require(artifact.get("config_sha256") == config_hash, "contact_artifact_config_hash_mismatch")
    require(artifact.get("prospective_test_labels_read") is False, "contact_artifact_test_labels_read")
    require(set(artifact.get("models", {})) == set(contact.MODEL_NAMES), "contact_artifact_model_set_invalid")
    selected = artifact.get("selected_candidate_model")
    require(selected in contact.CANDIDATE_MODELS, "contact_artifact_selected_model_invalid")
    return artifact


def finite_predictions(values: np.ndarray, uncertainty: np.ndarray, label: str) -> None:
    require(values.ndim == uncertainty.ndim == 1, f"{label}_prediction_dimension_invalid")
    require(len(values) == len(uncertainty), f"{label}_prediction_length_mismatch")
    require(np.all(np.isfinite(values)) and np.all(np.isfinite(uncertainty)), f"{label}_prediction_nonfinite")
    require(np.all(uncertainty >= 0), f"{label}_uncertainty_negative")


def build_predictions(
    rows: list[dict[str, str]],
    base_stage: Mapping[str, Any],
    embedding_stage: Mapping[str, Any],
    contact_stage: Mapping[str, Any],
    embedding_manifest: Path,
    embedding_summary: Path,
    embedding_sequence_manifest: Path,
    contact_receipt: Path,
    contact_schema: Path,
    *,
    enforce_production_hashes: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_config_hash = base_stage["hashes"]["config"]
    base_artifact = base.load_model_artifact(
        base_stage["paths"]["artifact"], expected_config_sha256=base_config_hash
    )
    base_model = str(base_artifact.get("selected_candidate_model"))
    require(base_model in base.CANDIDATE_MODELS, "base_selected_model_invalid")
    base_prediction, base_uncertainty = base.predict_serialized_model(
        base_artifact, base_model, rows
    )

    bank = embedding.load_embedding_bank(
        embedding_manifest,
        embedding_summary,
        embedding_sequence_manifest,
        enforce_production_hashes=enforce_production_hashes,
    )
    embedding_config_hash = embedding_stage["hashes"]["config"]
    embedding_artifact = embedding.load_model_artifact(
        embedding_stage["paths"]["artifact"],
        expected_config_sha256=embedding_config_hash,
    )
    embedding_model = str(embedding_artifact["selected_model"])
    sequence_hashes = [row["sequence_sha256"] for row in rows]
    embedding_prediction, embedding_uncertainty = embedding.predict_artifact_model(
        embedding_artifact, embedding_model, bank, sequence_hashes
    )

    ids = {row["candidate_id"] for row in rows}
    contacts, stable_columns, contact_metadata = contact.load_verified_contact_release(
        contact_receipt,
        contact_schema,
        ids,
        enforce_production_hash=enforce_production_hashes,
    )
    esm2 = bank.matrix(sequence_hashes, "esm2_ridge")
    contact_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        feature = contacts[row["candidate_id"]]
        require(
            feature["sequence_sha256"] == row["sequence_sha256"],
            f"contact_sequence_hash_mismatch:{row['candidate_id']}",
        )
        contact_rows.append(
            {**row, "_contact": {column: feature[column] for column in stable_columns}, "_embedding": esm2[index]}
        )
    contact_config_hash = contact_stage["hashes"]["config"]
    contact_artifact = validate_contact_artifact(
        contact_stage["paths"]["artifact"], contact_config_hash
    )
    contact_model = str(contact_artifact["selected_candidate_model"])
    contact_prediction, contact_uncertainty = contact.predict_serialized_model(
        contact_artifact, contact_model, contact_rows
    )

    for label, prediction, uncertainty in (
        ("base", base_prediction, base_uncertainty),
        ("embedding", embedding_prediction, embedding_uncertainty),
        ("contact", contact_prediction, contact_uncertainty),
    ):
        finite_predictions(prediction, uncertainty, label)
        require(len(prediction) == len(rows), f"{label}_prediction_row_count_mismatch")

    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        result = {field: row[field] for field in IDENTITY_FIELDS}
        result.update(
            {
                "base_selected_model": base_model,
                "base_predicted_geometry_score": format(float(base_prediction[index]), ".9g"),
                "base_prediction_uncertainty": format(float(base_uncertainty[index]), ".9g"),
                "embedding_selected_model": embedding_model,
                "embedding_predicted_geometry_score": format(float(embedding_prediction[index]), ".9g"),
                "embedding_prediction_uncertainty": format(float(embedding_uncertainty[index]), ".9g"),
                "contact_selected_model": contact_model,
                "contact_predicted_geometry_score": format(float(contact_prediction[index]), ".9g"),
                "contact_prediction_uncertainty": format(float(contact_uncertainty[index]), ".9g"),
            }
        )
        output.append(result)
    provenance = {
        "base_selected_model": base_model,
        "embedding_selected_model": embedding_model,
        "contact_selected_model": contact_model,
        "embedding_bank": bank.provenance,
        "contact_release": contact_metadata,
    }
    return output, provenance


def verify_input_hashes(input_hashes: Mapping[str, str]) -> None:
    for raw_path, expected in input_hashes.items():
        path = Path(raw_path)
        required_file(path, "frozen_prediction_input")
        require(sha256_file(path) == expected, f"frozen_prediction_input_changed:{path}")


def validate_prediction_rows(
    prediction_path: Path, manifest_rows: list[dict[str, str]], expected_count: int
) -> list[dict[str, str]]:
    rows, fields = read_table(prediction_path, "\t")
    require(len(rows) == expected_count, "prediction_row_count_mismatch")
    require(not (FORBIDDEN_OUTPUT_FIELDS & set(fields)), "prediction_output_contains_label_field")
    require(
        not any(
            token in field.lower()
            for field in fields
            for token in ("ground_truth", "observed_geometry", "experimental_label")
        ),
        "prediction_output_contains_label_alias",
    )
    expected_ids = [row["candidate_id"] for row in manifest_rows]
    require([row.get("candidate_id") for row in rows] == expected_ids, "prediction_candidate_order_mismatch")
    for prediction, manifest in zip(rows, manifest_rows):
        require(prediction.get("sequence_sha256") == manifest["sequence_sha256"], "prediction_sequence_hash_mismatch")
        require(prediction.get("model_split") == MODEL_SPLIT, "prediction_model_split_invalid")
    return rows


def verify_receipt(
    receipt_path: Path,
    manifest_path: Path,
    audit_path: Path,
    manifest_receipt_path: Path,
    *,
    enforce_production_hashes: bool,
    expected_count: int,
) -> dict[str, Any]:
    manifest_rows, manifest_hashes = validate_holdout(
        manifest_path,
        audit_path,
        manifest_receipt_path,
        enforce_production_hashes=enforce_production_hashes,
        expected_count=expected_count,
    )
    if not receipt_path.is_file() or receipt_path.stat().st_size == 0:
        raise WaitingForSurrogates(f"missing_or_empty:prediction_receipt:{receipt_path}")
    receipt = load_json(receipt_path, "prediction_receipt")
    require(receipt.get("schema_version") == SCHEMA_VERSION, "prediction_receipt_schema_invalid")
    require(
        receipt.get("status") == "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN",
        "prediction_receipt_status_invalid",
    )
    require(int(receipt.get("row_count", -1)) == expected_count, "prediction_receipt_count_invalid")
    require(receipt.get("v4_f_labels_read") is False, "prediction_receipt_labels_read")
    require(receipt.get("v4_f_label_paths_accepted") == 0, "prediction_receipt_label_paths_accepted")
    require((receipt.get("holdout") or {}).get("manifest_sha256") == manifest_hashes["manifest"], "prediction_receipt_manifest_hash_mismatch")
    outputs = receipt.get("outputs") or {}
    prediction_path = Path(str((outputs.get("predictions") or {}).get("path", "")))
    freeze_audit_path = Path(str((outputs.get("audit") or {}).get("path", "")))
    expected_root = receipt_path.resolve().parent
    require(
        prediction_path.resolve() == expected_root / OUTPUT_FILENAMES[0]
        and freeze_audit_path.resolve() == expected_root / OUTPUT_FILENAMES[1],
        "prediction_receipt_output_paths_invalid",
    )
    required_file(prediction_path, "frozen_predictions")
    required_file(freeze_audit_path, "frozen_prediction_audit")
    require(sha256_file(prediction_path) == (outputs["predictions"] or {}).get("sha256"), "prediction_receipt_output_hash_mismatch")
    require(sha256_file(freeze_audit_path) == (outputs["audit"] or {}).get("sha256"), "prediction_receipt_audit_hash_mismatch")
    prediction_rows = validate_prediction_rows(prediction_path, manifest_rows, expected_count)
    freeze_audit = load_json(freeze_audit_path, "prediction_audit")
    require(freeze_audit.get("status") == "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN", "prediction_audit_status_invalid")
    require(freeze_audit.get("v4_f_labels_read") is False, "prediction_audit_labels_read")
    input_hashes = receipt.get("input_hashes")
    require(isinstance(input_hashes, dict), "prediction_receipt_input_hashes_missing")
    verify_input_hashes(input_hashes)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V4_F_PREDICTION_RECEIPT_VERIFIED_DOCKING_MAY_START",
        "row_count": len(prediction_rows),
        "receipt_sha256": sha256_file(receipt_path),
        "predictions_sha256": sha256_file(prediction_path),
        "v4_f_labels_read": False,
    }


def run_freeze(args: argparse.Namespace) -> dict[str, Any]:
    rows, holdout_hashes = validate_holdout(
        args.manifest,
        args.manifest_audit,
        args.manifest_receipt,
        enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
        expected_count=args.expected_count,
    )
    stages = {
        "base": validate_stage(args.base_out, "base"),
        "embedding": validate_stage(args.embedding_out, "embedding"),
        "contact": validate_stage(args.contact_out, "contact"),
    }
    prediction_rows, provenance = build_predictions(
        rows,
        stages["base"],
        stages["embedding"],
        stages["contact"],
        args.embedding_manifest,
        args.embedding_summary,
        args.embedding_sequence_manifest,
        args.contact_receipt,
        args.contact_schema,
        enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
    )
    input_paths = {
        "holdout_manifest": args.manifest,
        "holdout_audit": args.manifest_audit,
        "holdout_manifest_receipt": args.manifest_receipt,
        "embedding_manifest": args.embedding_manifest,
        "embedding_summary": args.embedding_summary,
        "embedding_sequence_manifest": args.embedding_sequence_manifest,
        "contact_receipt": args.contact_receipt,
        "contact_schema": args.contact_schema,
        "contact_schema_receipt": args.contact_schema.with_suffix(".receipt.json"),
    }
    for stage, payload in stages.items():
        for name, path in payload["paths"].items():
            input_paths[f"{stage}_{name}"] = path
    for path in provenance["embedding_bank"]["shards"].values():
        input_paths[f"embedding_shard:{Path(path['path']).name}"] = Path(path["path"])
    contact_release = provenance["contact_release"]
    input_paths["contact_feature_audit"] = Path(contact_release["audit_path"])
    input_paths["contact_feature_csv"] = Path(contact_release["feature_path"])
    input_hashes = {str(path.resolve()): sha256_file(path.resolve()) for path in input_paths.values()}

    args.out_dir = args.out_dir.resolve()
    final_paths = {name: args.out_dir / name for name in OUTPUT_FILENAMES}
    with publication_lock(args.out_dir):
        if final_paths[OUTPUT_FILENAMES[-1]].is_file():
            return verify_receipt(
                final_paths[OUTPUT_FILENAMES[-1]],
                args.manifest,
                args.manifest_audit,
                args.manifest_receipt,
                enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
                expected_count=args.expected_count,
            )
        if args.out_dir.exists():
            unexpected = sorted(
                path.name for path in args.out_dir.iterdir() if path.name not in OUTPUT_FILENAMES
            )
            require(not unexpected, "prediction_output_directory_contains_unexpected_files")
        args.out_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{args.out_dir.name}.stage.", dir=args.out_dir.parent)
        )
        try:
            prediction_path = staging / OUTPUT_FILENAMES[0]
            audit_path = staging / OUTPUT_FILENAMES[1]
            receipt_path = staging / OUTPUT_FILENAMES[2]
            write_tsv(prediction_path, prediction_rows)
            audit = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN",
                "execution_mode": (
                    "test_fixture" if args.test_only_allow_unfrozen_inputs else "production"
                ),
                "row_count": len(prediction_rows),
                "holdout_hashes": holdout_hashes,
                "model_scientific_gate_status": {
                    stage: payload["scientific_gate_status"] for stage, payload in stages.items()
                },
                "prediction_models": {
                    "base": provenance["base_selected_model"],
                    "embedding": provenance["embedding_selected_model"],
                    "contact": provenance["contact_selected_model"],
                },
                "prediction_sha256": sha256_file(prediction_path),
                "input_hashes": input_hashes,
                "v4_f_labels_read": False,
                "v4_f_label_files_opened": 0,
                "v4_f_label_paths_accepted": 0,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(audit_path, audit)
            verify_input_hashes(input_hashes)
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN",
                "row_count": len(prediction_rows),
                "holdout": {
                    "manifest_sha256": holdout_hashes["manifest"],
                    "audit_sha256": holdout_hashes["audit"],
                    "manifest_receipt_sha256": holdout_hashes["manifest_receipt"],
                },
                "input_hashes": input_hashes,
                "outputs": {
                    "predictions": {
                        "path": str(final_paths[OUTPUT_FILENAMES[0]]),
                        "sha256": sha256_file(prediction_path),
                    },
                    "audit": {
                        "path": str(final_paths[OUTPUT_FILENAMES[1]]),
                        "sha256": sha256_file(audit_path),
                    },
                },
                "publication": {
                    "policy": "stage_then_atomic_replace_receipt_last",
                    "receipt_published_last": True,
                },
                "v4_f_labels_read": False,
                "v4_f_label_paths_accepted": 0,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(receipt_path, receipt)
            args.out_dir.mkdir(parents=True, exist_ok=True)
            final_paths[OUTPUT_FILENAMES[-1]].unlink(missing_ok=True)
            os.replace(prediction_path, final_paths[OUTPUT_FILENAMES[0]])
            os.replace(audit_path, final_paths[OUTPUT_FILENAMES[1]])
            os.replace(receipt_path, final_paths[OUTPUT_FILENAMES[2]])
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return verify_receipt(
        final_paths[OUTPUT_FILENAMES[-1]],
        args.manifest,
        args.manifest_audit,
        args.manifest_receipt,
        enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
        expected_count=args.expected_count,
    )


def build_parser() -> argparse.ArgumentParser:
    root = SCRIPT_DIR.parent
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    verify = subparsers.add_parser("verify-receipt")
    for subparser in (freeze, verify):
        subparser.add_argument(
            "--manifest",
            type=Path,
            default=root / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv",
        )
        subparser.add_argument(
            "--manifest-audit",
            type=Path,
            default=root / "data_splits/pvrig_v4_f/prospective_holdout96_audit.json",
        )
        subparser.add_argument(
            "--manifest-receipt",
            type=Path,
            default=root / "data_splits/pvrig_v4_f/prospective_holdout96_receipt.json",
        )
        subparser.add_argument("--expected-count", type=int, default=EXPECTED_ROW_COUNT)
        subparser.add_argument("--test-only-allow-unfrozen-inputs", action="store_true")
    freeze.add_argument(
        "--base-out", type=Path, default=root / "runs/pvrig_v4_d_sequence_surrogate_v1"
    )
    freeze.add_argument(
        "--embedding-out",
        type=Path,
        default=root / "runs/pvrig_v4_d_frozen_embedding_surrogate_v1",
    )
    freeze.add_argument(
        "--contact-out",
        type=Path,
        default=root / "runs/pvrig_v4_d_contact_fusion_surrogate_v1",
    )
    embedding_root = root / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
    freeze.add_argument(
        "--embedding-manifest",
        type=Path,
        default=embedding_root / "meanpool_embeddings/embedding_manifest_v3.csv",
    )
    freeze.add_argument(
        "--embedding-summary",
        type=Path,
        default=embedding_root / "meanpool_embeddings/embedding_summary_v3.json",
    )
    freeze.add_argument(
        "--embedding-sequence-manifest",
        type=Path,
        default=embedding_root / "sequence_manifest_v3.csv",
    )
    freeze.add_argument(
        "--contact-receipt",
        type=Path,
        default=root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json",
    )
    freeze.add_argument(
        "--contact-schema",
        type=Path,
        default=root / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json",
    )
    freeze.add_argument(
        "--out-dir", type=Path, default=root / "predictions/pvrig_v4_f_surrogate_predictions_v1"
    )
    verify.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            result = run_freeze(args)
        else:
            result = verify_receipt(
                args.receipt,
                args.manifest,
                args.manifest_audit,
                args.manifest_receipt,
                enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
                expected_count=args.expected_count,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except WaitingForSurrogates as exc:
        print(json.dumps({"status": "WAITING_V4_D_SURROGATES", "reason": str(exc)}, sort_keys=True))
        return 4
    except (PredictionFreezeError, base.SurrogateError, embedding.FrozenEmbeddingError, contact.ContactFusionError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED_V4_F_PREDICTION_FREEZE", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
