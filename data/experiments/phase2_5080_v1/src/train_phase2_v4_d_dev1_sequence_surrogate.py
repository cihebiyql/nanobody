#!/usr/bin/env python3
"""Train the post-hoc V4-D-DEV1 development-only sequence surrogate.

This package deliberately does not continue the failed formal V4-D chain.  It
accepts only the 226 OPEN_TRAIN and 32 OPEN_DEVELOPMENT rows released by the
independent DEV1 teacher builder after the V4-D evaluator failed.  V4-D's 32
prospective-test labels remain sealed.  OPEN_DEVELOPMENT is selection-only.

The result is computational dual-docking geometry development evidence.  It
cannot create a formal completion/unlock receipt and cannot unlock V4-F.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
import train_phase2_v4_d_surrogate as base  # noqa: E402


SCHEMA_VERSION = "phase2_v4_d_dev1_sequence_surrogate_v1"
VERSION = "V4-D-DEV1"
PRIMARY_TARGET = base.PRIMARY_TARGET
TRAIN_SPLIT = base.TRAIN_SPLIT
DEVELOPMENT_SPLIT = base.DEVELOPMENT_SPLIT
FORBIDDEN_SPLIT = base.SEALED_SPLIT
EXPECTED_TEACHER_COUNTS = {TRAIN_SPLIT: 226, DEVELOPMENT_SPLIT: 32}
EXPECTED_TEACHER_ROWS = 258
EXPECTED_SPLIT_MANIFEST_SHA256 = base.EXPECTED_SPLIT_MANIFEST_SHA256
EXPECTED_SOURCE_EVALUATOR_SHA256 = (
    "289542c58cfe72c380143a910b3adb75ba4e12f65899f71907a044314bedb674"
)
EXPECTED_PREREGISTRATION_SHA256 = (
    "10395d03f0f8d9eae7db2fa94fc3b4cccc1570369ee8b09a6650bff062f35113"
)
EXPECTED_BASE_MODULE_SHA256 = (
    "bbdf2d1d22ef1e375b65d1d680c25fffe6a4d09d170184528dc2c3f0292fa95e"
)
EXPECTED_TEACHER_STATUS = (
    "RELEASED_DEV_ONLY_FROM_FAILED_V4D_EVALUATOR_TEST32_SEALED"
)
EXPECTED_TEACHER_RELEASE = "OPEN_TRAIN_226_PLUS_OPEN_DEVELOPMENT_32_DEV_ONLY"
EXPECTED_FAILED_GATE = "candidate_threshold_sensitivity"
FIXED_ALPHAS = base.DEFAULT_ALPHAS
FIXED_GROUP_BOOTSTRAP_SEEDS = (
    2026071701,
    2026071702,
    2026071703,
    2026071704,
    2026071705,
)
FIXED_FEATURE_WIDTH = base.FROZEN_FEATURE_WIDTH
REQUIRED_BASELINES = base.REQUIRED_BASELINES
CANDIDATE_MODELS = base.CANDIDATE_MODELS
MODEL_NAMES = base.MODEL_NAMES
TEACHER_FIELDS = base.TEACHER_FIELDS
MANIFEST_FIELDS = base.MANIFEST_FIELDS
CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence-to-independent-dual-docking computational geometry "
    "development surrogate only; not binding, affinity, competition, "
    "experimental blocking, Docking Gold, a formal V4-D pass, or final "
    "submission authority."
)
OUTPUT_FILENAMES = (
    "dev1_frozen_model_config.json",
    "dev1_frozen_model_artifact.json",
    "dev1_open_development_predictions.tsv",
    "dev1_open_development_summary.json",
    "dev1_artifact_sha256_receipt.json",
)
CONFIG_STATUS = "DEV_ONLY_FROZEN_CONFIGURATION_H96_PREDICTION_NOT_FROZEN"
ARTIFACT_STATUS = "DEV_ONLY_FROZEN_MODEL_ARTIFACT_H96_NOT_EVALUATED"
SUMMARY_PASS_STATUS = (
    "DEV_ONLY_PASS_OPEN_DEVELOPMENT_GATES_H96_PREDICTION_NOT_FROZEN"
)
SUMMARY_FAIL_STATUS = (
    "DEV_ONLY_FAIL_OPEN_DEVELOPMENT_GATES_H96_PREDICTION_NOT_FROZEN"
)
RECEIPT_STATUS = "DEV_ONLY_PASS_ARTIFACT_HASH_CLOSURE"
FORBIDDEN_STATUS_TOKENS = ("FORMAL", "UNLOCK", "COMPLETION", "V4_F")
FORBIDDEN_PATH_TOKENS = ("formal", "unlock", "completion", "v4_f")


class Dev1SurrogateError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return base.sha256_file(path)


def sha256_strings(values: Iterable[str]) -> str:
    return base.sha256_strings(values)


def read_tsv(path: Path) -> list[dict[str, str]]:
    return base.read_tsv(path)


def tsv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            return next(reader)
        except StopIteration as exc:
            raise Dev1SurrogateError("empty_teacher_tsv") from exc


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    base.write_json(path, payload)


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    base.write_tsv(path, rows)


def validate_dev_only_status(status: str) -> str:
    value = str(status).strip()
    if not value.startswith("DEV_ONLY_"):
        raise Dev1SurrogateError(f"status_not_dev_only:{value}")
    upper = value.upper()
    for token in FORBIDDEN_STATUS_TOKENS:
        if token in upper:
            raise Dev1SurrogateError(f"dev_only_status_impersonates_authority:{token}")
    return value


def validate_dev_only_output_path(out_dir: Path) -> Path:
    lexical = out_dir.absolute()
    # Reject both an output symlink and an existing symlink ancestor before
    # resolving.  A lexical "dev1" component must not be able to redirect a
    # publication into an authoritative/formal root.
    for candidate in (lexical, *lexical.parents):
        if candidate.is_symlink():
            raise Dev1SurrogateError(
                f"dev1_output_path_symlink_forbidden:{candidate}"
            )
    resolved = lexical.resolve()
    lowered_parts = [part.lower() for part in resolved.parts]
    if not any("dev1" in part for part in lowered_parts):
        raise Dev1SurrogateError(f"output_path_missing_dev1_namespace:{resolved}")
    for part in lowered_parts:
        for token in FORBIDDEN_PATH_TOKENS:
            if token in part:
                raise Dev1SurrogateError(
                    f"dev1_output_path_impersonates_authority:{token}:{resolved}"
                )
    return resolved


def load_preregistration(path: Path, *, enforce_hash: bool = True) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Dev1SurrogateError(f"invalid_dev1_preregistration:{path}") from exc
    if enforce_hash and sha256_file(path) != EXPECTED_PREREGISTRATION_SHA256:
        raise Dev1SurrogateError("dev1_preregistration_sha256_mismatch")
    if payload.get("version") != VERSION:
        raise Dev1SurrogateError("dev1_preregistration_version_mismatch")
    disclosure = payload.get("post_hoc_disclosure", {})
    if disclosure.get("defined_after_v4_d_evaluator_result_was_known") is not True:
        raise Dev1SurrogateError("dev1_post_hoc_disclosure_missing")
    if disclosure.get("source_evaluator_status") != "FAIL":
        raise Dev1SurrogateError("dev1_source_evaluator_status_not_fail")
    if disclosure.get("source_evaluator_unlockable") is not False:
        raise Dev1SurrogateError("dev1_source_evaluator_must_remain_locked")
    if disclosure.get("source_evaluator_sha256") != EXPECTED_SOURCE_EVALUATOR_SHA256:
        raise Dev1SurrogateError("dev1_source_evaluator_sha256_mismatch")
    teacher = payload.get("teacher_contract", {})
    if teacher.get("release_status") != EXPECTED_TEACHER_STATUS:
        raise Dev1SurrogateError("dev1_prereg_teacher_status_mismatch")
    if teacher.get("split_counts") != EXPECTED_TEACHER_COUNTS:
        raise Dev1SurrogateError("dev1_prereg_teacher_counts_mismatch")
    protocol = payload.get("training_protocol", {})
    if tuple(protocol.get("fixed_group_bootstrap_seeds", [])) != FIXED_GROUP_BOOTSTRAP_SEEDS:
        raise Dev1SurrogateError("dev1_prereg_seed_mismatch")
    if tuple(protocol.get("model_set", [])) != MODEL_NAMES:
        raise Dev1SurrogateError("dev1_prereg_model_set_mismatch")
    future = payload.get("future_evaluation", {})
    if future.get("v4_d_test32_remains_sealed") is not True:
        raise Dev1SurrogateError("dev1_prereg_test32_not_sealed")
    if future.get("panel") != "V4-H_QC96":
        raise Dev1SurrogateError("dev1_prereg_future_panel_mismatch")
    non_authority = payload.get("non_authority", {})
    if any(
        non_authority.get(key) is not False
        for key in (
            "may_create_formal_v4_d_or_v4_f_completion_receipt",
            "may_unlock_v4_f",
            "may_modify_existing_v4_d_or_v4_f_watchers",
            "may_publish_to_existing_formal_roots",
            "deployment_eligible_from_open_development_results_alone",
        )
    ):
        raise Dev1SurrogateError("dev1_prereg_non_authority_contract_mismatch")
    return payload


def validate_teacher_audit(
    teacher_path: Path,
    audit_path: Path,
    split_manifest_path: Path,
) -> dict[str, Any]:
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Dev1SurrogateError(f"invalid_dev1_teacher_audit:{audit_path}") from exc
    if audit.get("status") != EXPECTED_TEACHER_STATUS:
        raise Dev1SurrogateError("dev1_teacher_audit_status_mismatch")
    if audit.get("release") != EXPECTED_TEACHER_RELEASE:
        raise Dev1SurrogateError("dev1_teacher_audit_release_mismatch")
    source = audit.get("source_evaluator", {})
    if source.get("status") != "FAIL":
        raise Dev1SurrogateError("dev1_teacher_source_evaluator_status_not_fail")
    if source.get("unlockable") is not False:
        raise Dev1SurrogateError("dev1_teacher_source_evaluator_unlockable_not_false")
    if source.get("sha256") != EXPECTED_SOURCE_EVALUATOR_SHA256:
        raise Dev1SurrogateError("dev1_teacher_source_evaluator_sha256_mismatch")
    if source.get("failed_gates") != [EXPECTED_FAILED_GATE]:
        raise Dev1SurrogateError("dev1_teacher_source_failed_gate_mismatch")
    if audit.get("formal_v4_f_unlock_eligible") is not False:
        raise Dev1SurrogateError("dev1_teacher_formal_v4_f_unlock_eligible_not_false")
    claim_boundary = str(audit.get("claim_boundary", ""))
    for required_phrase in (
        "development",
        "not binding",
        "Docking Gold",
    ):
        if required_phrase not in claim_boundary:
            raise Dev1SurrogateError(
                "dev1_teacher_claim_boundary_missing:" + required_phrase.replace(" ", "_")
            )
    non_authority = audit.get("non_authority", {})
    if non_authority.get("formal_completion_or_unlock_receipt_created") is not False:
        raise Dev1SurrogateError("dev1_teacher_non_authority_receipt_flag_mismatch")
    if non_authority.get("formal_v4_f_unlock_eligible") is not False:
        raise Dev1SurrogateError("dev1_teacher_non_authority_unlock_flag_mismatch")
    boundary = audit.get("sealed_data_boundary", {})
    for field in (
        "raw_test32_job_files_opened",
        "test32_metric_values_read",
        "test32_label_rows_emitted",
    ):
        if boundary.get(field) != 0:
            raise Dev1SurrogateError(f"dev1_teacher_nonzero_sealed_counter:{field}")
    inputs = audit.get("inputs", {})
    if inputs.get("split_manifest_sha256") != sha256_file(split_manifest_path):
        raise Dev1SurrogateError("dev1_teacher_split_manifest_hash_mismatch")
    output = audit.get("output", {})
    if output.get("sha256") != sha256_file(teacher_path):
        raise Dev1SurrogateError("dev1_teacher_output_hash_mismatch")
    if output.get("row_count") != EXPECTED_TEACHER_ROWS:
        raise Dev1SurrogateError("dev1_teacher_audit_row_count_mismatch")
    if output.get("split_counts") != EXPECTED_TEACHER_COUNTS:
        raise Dev1SurrogateError("dev1_teacher_audit_split_counts_mismatch")
    if output.get("exact_header") != tsv_header(teacher_path):
        raise Dev1SurrogateError("dev1_teacher_exact_header_mismatch")
    return audit


def validate_split_manifest(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    try:
        return base.validate_split_manifest(rows)
    except base.SurrogateError as exc:
        raise Dev1SurrogateError(str(exc)) from exc


def validate_teacher_rows(
    rows: list[Mapping[str, Any]],
    split_by_id: Mapping[str, Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if len(rows) != EXPECTED_TEACHER_ROWS:
        raise Dev1SurrogateError(f"dev1_teacher_row_count_mismatch:{len(rows)}")
    identity_counts: Counter[str] = Counter()
    for row in rows:
        # The split check occurs before any target or feature read.
        split = str(row.get("model_split", ""))
        if split == FORBIDDEN_SPLIT:
            raise Dev1SurrogateError("dev1_teacher_contains_prospective_computational_test")
        if split not in EXPECTED_TEACHER_COUNTS:
            raise Dev1SurrogateError(f"dev1_teacher_unknown_split:{split}")
        identity_counts[split] += 1
    if dict(identity_counts) != EXPECTED_TEACHER_COUNTS:
        raise Dev1SurrogateError(
            "dev1_teacher_split_count_mismatch:"
            + json.dumps(dict(sorted(identity_counts.items())), sort_keys=True)
        )
    try:
        train_rows, development_rows = base.validate_teacher_rows(
            rows,
            split_by_id,
            target=PRIMARY_TARGET,
        )
    except base.SurrogateError as exc:
        raise Dev1SurrogateError(str(exc)) from exc
    train_clusters = sorted(
        {str(row["parent_framework_cluster"]) for row in train_rows}
    )
    development_clusters = sorted(
        {str(row["parent_framework_cluster"]) for row in development_rows}
    )
    overlap = sorted(set(train_clusters) & set(development_clusters))
    audit = {
        "status": "PASS_DEV_ONLY_PARENT_CLUSTER_ISOLATION",
        "group_unit": "parent_framework_cluster",
        "fit_split": TRAIN_SPLIT,
        "selection_split": DEVELOPMENT_SPLIT,
        "fit_row_count": len(train_rows),
        "selection_row_count": len(development_rows),
        "fit_parent_cluster_count": len(train_clusters),
        "selection_parent_cluster_count": len(development_clusters),
        "fit_parent_clusters_sha256": sha256_strings(train_clusters),
        "selection_parent_clusters_sha256": sha256_strings(development_clusters),
        "overlap_count": len(overlap),
        "overlap": overlap,
        "selection_rows_used_as_fit_rows": 0,
    }
    if overlap:
        raise Dev1SurrogateError("dev1_teacher_parent_cluster_leakage")
    return train_rows, development_rows, audit


def train_surrogates(
    train_rows: list[dict[str, Any]], development_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    try:
        return base.train_surrogates(
            train_rows,
            development_rows,
            target=PRIMARY_TARGET,
            alphas=FIXED_ALPHAS,
            ensemble_seeds=FIXED_GROUP_BOOTSTRAP_SEEDS,
            frozen_feature_width=FIXED_FEATURE_WIDTH,
        )
    except base.SurrogateError as exc:
        raise Dev1SurrogateError(str(exc)) from exc


def load_model_artifact(
    path: Path, *, expected_config_sha256: str | None = None
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Dev1SurrogateError(f"invalid_dev1_model_artifact:{path}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise Dev1SurrogateError("dev1_model_artifact_schema_mismatch")
    validate_dev_only_status(str(payload.get("status", "")))
    if payload.get("status") != ARTIFACT_STATUS:
        raise Dev1SurrogateError("dev1_model_artifact_status_mismatch")
    if expected_config_sha256 is not None and payload.get("config_sha256") != expected_config_sha256:
        raise Dev1SurrogateError("dev1_model_artifact_config_hash_mismatch")
    if set(payload.get("models", {})) != set(MODEL_NAMES):
        raise Dev1SurrogateError("dev1_model_artifact_model_set_mismatch")
    if payload.get("formal_completion_or_unlock_receipt") is not False:
        raise Dev1SurrogateError("dev1_model_artifact_authority_flag_mismatch")
    return payload


def predict_serialized_model(
    artifact: Mapping[str, Any], model_name: str, rows: list[dict[str, Any]]
) -> tuple[np.ndarray, np.ndarray]:
    try:
        return base.predict_serialized_model(artifact, model_name, rows)
    except base.SurrogateError as exc:
        raise Dev1SurrogateError(str(exc)) from exc


def verify_artifact_roundtrip(
    artifact_path: Path,
    config_path: Path,
    development_rows: list[dict[str, Any]],
    trained: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = load_model_artifact(
        artifact_path, expected_config_sha256=sha256_file(config_path)
    )
    per_model: dict[str, Any] = {}
    for model_name in MODEL_NAMES:
        prediction, uncertainty = predict_serialized_model(
            artifact, model_name, development_rows
        )
        expected_prediction = np.asarray(
            trained["models"][model_name]["ensemble_prediction"], dtype=np.float64
        )
        expected_uncertainty = np.asarray(
            trained["models"][model_name]["ensemble_uncertainty"], dtype=np.float64
        )
        prediction_error = float(np.max(np.abs(prediction - expected_prediction)))
        uncertainty_error = float(np.max(np.abs(uncertainty - expected_uncertainty)))
        if prediction_error > 1e-12 or uncertainty_error > 1e-12:
            raise Dev1SurrogateError(
                f"dev1_artifact_prediction_roundtrip_mismatch:{model_name}"
            )
        per_model[model_name] = {
            "row_count": len(development_rows),
            "maximum_absolute_prediction_error": prediction_error,
            "maximum_absolute_uncertainty_error": uncertainty_error,
        }
    return {
        "status": "PASS_DEV_ONLY_SERIALIZED_ARTIFACT_PREDICTION_ROUNDTRIP",
        "model_count": len(MODEL_NAMES),
        "per_model": per_model,
    }


def validate_existing_output_directory(out_dir: Path) -> None:
    validate_dev_only_output_path(out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise Dev1SurrogateError(f"dev1_output_path_is_not_directory:{out_dir}")
    if not out_dir.exists():
        return
    unexpected = sorted(
        path.name for path in out_dir.iterdir() if path.name not in set(OUTPUT_FILENAMES)
    )
    if unexpected:
        raise Dev1SurrogateError(
            "unexpected_existing_dev1_output_files:" + ",".join(unexpected)
        )


@contextmanager
def output_publication_lock(out_dir: Path) -> Iterable[None]:
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir.parent / f".{out_dir.name}.dev1_publication.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Dev1SurrogateError(f"dev1_publication_lock_exists:{lock_path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def publish_staged_outputs(staging_dir: Path, out_dir: Path) -> dict[str, Any]:
    validate_existing_output_directory(out_dir)
    for name in OUTPUT_FILENAMES:
        if not (staging_dir / name).is_file():
            raise Dev1SurrogateError(f"staged_dev1_output_missing:{name}")
    receipt_name = OUTPUT_FILENAMES[-1]
    try:
        receipt = json.loads((staging_dir / receipt_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Dev1SurrogateError("invalid_staged_dev1_receipt") from exc
    validate_dev_only_status(str(receipt.get("status", "")))
    if receipt.get("status") != RECEIPT_STATUS:
        raise Dev1SurrogateError("staged_dev1_receipt_status_mismatch")
    expected_outputs = receipt.get("outputs", {})
    expected_paths = {
        str((out_dir / name).resolve()) for name in OUTPUT_FILENAMES[:-1]
    }
    if set(expected_outputs) != expected_paths:
        raise Dev1SurrogateError("staged_dev1_receipt_output_set_mismatch")
    out_dir.mkdir(parents=True, exist_ok=True)
    final_receipt = out_dir / receipt_name
    stale_receipt_removed = final_receipt.exists()
    final_receipt.unlink(missing_ok=True)
    for name in OUTPUT_FILENAMES[:-1]:
        destination = out_dir / name
        os.replace(staging_dir / name, destination)
        if sha256_file(destination) != expected_outputs[str(destination.resolve())]:
            raise Dev1SurrogateError(f"published_dev1_output_hash_mismatch:{name}")
    os.replace(staging_dir / receipt_name, final_receipt)
    descriptor = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "policy": "stage_all_dev1_outputs_then_atomic_replace_receipt_last",
        "stale_receipt_removed_before_replacement": stale_receipt_removed,
        "receipt_published_last": True,
    }


def run_pipeline(
    teacher_path: Path,
    teacher_audit_path: Path,
    split_manifest_path: Path,
    preregistration_path: Path,
    out_dir: Path,
    *,
    enforce_production_hashes: bool = True,
) -> dict[str, Any]:
    out_dir = validate_dev_only_output_path(out_dir)
    preregistration = load_preregistration(
        preregistration_path, enforce_hash=enforce_production_hashes
    )
    if enforce_production_hashes:
        if sha256_file(split_manifest_path) != EXPECTED_SPLIT_MANIFEST_SHA256:
            raise Dev1SurrogateError("dev1_split_manifest_sha256_mismatch")
        if sha256_file(Path(base.__file__).resolve()) != EXPECTED_BASE_MODULE_SHA256:
            raise Dev1SurrogateError("dev1_reused_base_module_sha256_mismatch")
    audit = validate_teacher_audit(
        teacher_path, teacher_audit_path, split_manifest_path
    )
    split_rows = read_tsv(split_manifest_path)
    split_by_id = validate_split_manifest(split_rows)
    teacher_rows = read_tsv(teacher_path)
    train_rows, development_rows, isolation_audit = validate_teacher_rows(
        teacher_rows, split_by_id
    )
    trained = train_surrogates(train_rows, development_rows)

    final_paths = {name: out_dir / name for name in OUTPUT_FILENAMES}
    sealed_manifest_ids = sorted(
        row["candidate_id"]
        for row in split_rows
        if row["model_split"] == FORBIDDEN_SPLIT
    )
    if len(sealed_manifest_ids) != 32:
        raise Dev1SurrogateError("dev1_label_free_test32_manifest_count_mismatch")

    with output_publication_lock(out_dir):
        validate_existing_output_directory(out_dir)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".{out_dir.name}.dev1-stage.", dir=out_dir.parent)
        )
        try:
            config_path = staging_dir / OUTPUT_FILENAMES[0]
            model_path = staging_dir / OUTPUT_FILENAMES[1]
            predictions_path = staging_dir / OUTPUT_FILENAMES[2]
            summary_path = staging_dir / OUTPUT_FILENAMES[3]
            receipt_path = staging_dir / OUTPUT_FILENAMES[4]

            config = {
                "schema_version": SCHEMA_VERSION,
                "status": CONFIG_STATUS,
                "version": VERSION,
                "post_hoc_after_failed_v4_d_evaluator": True,
                "source_evaluator": {
                    "status": "FAIL",
                    "unlockable": False,
                    "failed_gates": [EXPECTED_FAILED_GATE],
                    "sha256": EXPECTED_SOURCE_EVALUATOR_SHA256,
                },
                "primary_target": PRIMARY_TARGET,
                "fit_split": TRAIN_SPLIT,
                "selection_split": DEVELOPMENT_SPLIT,
                "fit_rows": len(train_rows),
                "selection_rows": len(development_rows),
                "selection_rows_used_as_fit_rows": 0,
                "parent_cluster_isolation_audit": isolation_audit,
                "required_baselines": list(REQUIRED_BASELINES),
                "candidate_models": list(CANDIDATE_MODELS),
                "ridge_alphas": list(FIXED_ALPHAS),
                "fixed_group_bootstrap_seeds": list(FIXED_GROUP_BOOTSTRAP_SEEDS),
                "seed_count": len(FIXED_GROUP_BOOTSTRAP_SEEDS),
                "frozen_feature_width": FIXED_FEATURE_WIDTH,
                "test32": {
                    "manifest_rows": len(sealed_manifest_ids),
                    "candidate_ids_sha256": sha256_strings(sealed_manifest_ids),
                    "raw_label_files_opened": 0,
                    "labels_read": 0,
                    "metric_values_read": 0,
                    "label_rows_used": 0,
                },
                "future_one_shot_evaluation": {
                    "panel": "V4-H_QC96",
                    "predictions_must_be_frozen_before_dual_docking_label_access": True,
                    "evaluated_now": False,
                },
                "inputs": {
                    "teacher_sha256": sha256_file(teacher_path),
                    "teacher_audit_sha256": sha256_file(teacher_audit_path),
                    "split_manifest_sha256": sha256_file(split_manifest_path),
                    "preregistration_sha256": sha256_file(preregistration_path),
                    "reused_base_module_sha256": sha256_file(Path(base.__file__).resolve()),
                },
                "runtime_provenance": {
                    "python_version": sys.version,
                    "numpy_version": np.__version__,
                    "platform": platform.platform(),
                },
                "deployment_eligible": False,
                "formal_completion_or_unlock_receipt": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            validate_dev_only_status(config["status"])
            write_json(config_path, config)

            artifact = {
                "schema_version": SCHEMA_VERSION,
                "status": ARTIFACT_STATUS,
                "version": VERSION,
                "config_sha256": sha256_file(config_path),
                "selected_candidate_model": trained["selected_candidate"],
                "strongest_shortcut_baseline": trained["strongest_shortcut"],
                "models": {
                    name: base.json_model_result(trained["models"][name])
                    for name in MODEL_NAMES
                },
                "fit_row_count": len(train_rows),
                "development_row_count_used_for_selection_only": len(development_rows),
                "test32_raw_label_files_opened": 0,
                "test32_labels_read": 0,
                "test32_metric_values_read": 0,
                "test32_label_rows_used": 0,
                "h96_evaluated": False,
                "deployment_eligible": False,
                "formal_completion_or_unlock_receipt": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            validate_dev_only_status(artifact["status"])
            write_json(model_path, artifact)
            roundtrip = verify_artifact_roundtrip(
                model_path, config_path, development_rows, trained
            )
            reloaded = load_model_artifact(
                model_path, expected_config_sha256=sha256_file(config_path)
            )
            serialized = {
                name: predict_serialized_model(reloaded, name, development_rows)
                for name in MODEL_NAMES
            }

            prediction_rows: list[dict[str, Any]] = []
            for index, row in enumerate(development_rows):
                output: dict[str, Any] = {
                    "candidate_id": row["candidate_id"],
                    "model_split": row["model_split"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                    "target_R_dual_min": round(float(row[PRIMARY_TARGET]), 9),
                }
                for name in MODEL_NAMES:
                    prediction, uncertainty = serialized[name]
                    output[f"prediction_{name}"] = round(float(prediction[index]), 9)
                    output[f"uncertainty_{name}"] = round(float(uncertainty[index]), 9)
                selected = trained["selected_candidate"]
                output["selected_model"] = selected
                output["selected_prediction"] = output[f"prediction_{selected}"]
                output["selected_uncertainty"] = output[f"uncertainty_{selected}"]
                prediction_rows.append(output)
            write_tsv(predictions_path, prediction_rows)

            open_gates_pass = (
                trained["open_performance_gates"]["all_passed"]
                and trained["uncertainty_gate_pass"]
            )
            summary_status = (
                SUMMARY_PASS_STATUS if open_gates_pass else SUMMARY_FAIL_STATUS
            )
            validate_dev_only_status(summary_status)
            summary = {
                "schema_version": SCHEMA_VERSION,
                "status": summary_status,
                "version": VERSION,
                "post_hoc_after_failed_v4_d_evaluator": True,
                "teacher_release_status": audit["status"],
                "primary_target": PRIMARY_TARGET,
                "fit": {
                    "split": TRAIN_SPLIT,
                    "rows": len(train_rows),
                    "parent_clusters": isolation_audit["fit_parent_cluster_count"],
                },
                "selection": {
                    "split": DEVELOPMENT_SPLIT,
                    "rows": len(development_rows),
                    "parent_clusters": isolation_audit[
                        "selection_parent_cluster_count"
                    ],
                    "rows_used_as_fit_rows": 0,
                },
                "parent_cluster_isolation_audit": isolation_audit,
                "test32": {
                    "manifest_rows": len(sealed_manifest_ids),
                    "raw_label_files_opened": 0,
                    "labels_read": 0,
                    "metric_values_read": 0,
                    "label_rows_used": 0,
                    "remains_sealed": True,
                },
                "future_evaluation": {
                    "panel": "V4-H_QC96",
                    "predictions_frozen": False,
                    "dual_docking_labels_read": False,
                    "one_shot_evaluation_not_run": True,
                },
                "models": {
                    name: base.summary_model_result(trained["models"][name])
                    for name in MODEL_NAMES
                },
                "strongest_shortcut_baseline": trained["strongest_shortcut"],
                "selected_candidate_model": trained["selected_candidate"],
                "open_performance_gates": trained["open_performance_gates"],
                "uncertainty_gate_pass": trained["uncertainty_gate_pass"],
                "serialized_artifact_prediction_roundtrip": roundtrip,
                "deployment_eligible": False,
                "formal_completion_or_unlock_receipt": False,
                "artifacts": {
                    "config": {
                        "path": str(final_paths[OUTPUT_FILENAMES[0]]),
                        "sha256": sha256_file(config_path),
                    },
                    "model": {
                        "path": str(final_paths[OUTPUT_FILENAMES[1]]),
                        "sha256": sha256_file(model_path),
                    },
                    "predictions": {
                        "path": str(final_paths[OUTPUT_FILENAMES[2]]),
                        "sha256": sha256_file(predictions_path),
                    },
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(summary_path, summary)

            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": RECEIPT_STATUS,
                "version": VERSION,
                "test32_raw_label_files_opened": 0,
                "test32_labels_read": 0,
                "test32_metric_values_read": 0,
                "test32_label_rows_used": 0,
                "h96_dual_docking_labels_read": False,
                "deployment_eligible": False,
                "formal_completion_or_unlock_receipt": False,
                "inputs": {
                    str(teacher_path.resolve()): sha256_file(teacher_path),
                    str(teacher_audit_path.resolve()): sha256_file(teacher_audit_path),
                    str(split_manifest_path.resolve()): sha256_file(split_manifest_path),
                    str(preregistration_path.resolve()): sha256_file(preregistration_path),
                    str(Path(base.__file__).resolve()): sha256_file(
                        Path(base.__file__).resolve()
                    ),
                    str(Path(__file__).resolve()): sha256_file(Path(__file__).resolve()),
                },
                "outputs": {
                    str(final_paths[name]): sha256_file(staging_dir / name)
                    for name in OUTPUT_FILENAMES[:-1]
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            validate_dev_only_status(receipt["status"])
            write_json(receipt_path, receipt)
            publication = publish_staged_outputs(staging_dir, out_dir)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    return {
        "status": summary["status"],
        "summary": str(final_paths[OUTPUT_FILENAMES[3]]),
        "receipt": str(final_paths[OUTPUT_FILENAMES[4]]),
        "selected_candidate_model": trained["selected_candidate"],
        "strongest_shortcut_baseline": trained["strongest_shortcut"],
        "test32_raw_label_files_opened": 0,
        "test32_labels_read": 0,
        "test32_metric_values_read": 0,
        "formal_completion_or_unlock_receipt": False,
        "publication": publication,
        "preregistration_status": preregistration["status"],
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-audit", type=Path, required=True)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=root
        / "audits/phase2_v4_d_dev1_sequence_surrogate_v1_preregistration.json",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_pipeline(
        args.teacher,
        args.teacher_audit,
        args.split_manifest,
        args.preregistration,
        args.out_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
