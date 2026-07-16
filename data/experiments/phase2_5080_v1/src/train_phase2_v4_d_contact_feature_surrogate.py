#!/usr/bin/env python3
"""Train open-split V4-D contact/embedding fusion surrogates.

The trainer accepts only the OPEN_TRAIN and OPEN_DEVELOPMENT teacher release.
Contact inputs are admitted exclusively through a verified V3 residue-feature
receipt and its stable allowlist.  Prospective-test labels are not an input.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch

import extract_pvrig_v2_3_residue_contact_features as contact_v3
import train_phase2_v4_d_surrogate as base


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
SCHEMA_VERSION = "phase2_v4_d_contact_embedding_fusion_surrogate_v1"
PRIMARY_TARGET = base.PRIMARY_TARGET
TRAIN_SPLIT = base.TRAIN_SPLIT
DEVELOPMENT_SPLIT = base.DEVELOPMENT_SPLIT
SEALED_SPLIT = base.SEALED_SPLIT
DEFAULT_ALPHAS = base.DEFAULT_ALPHAS
DEFAULT_ENSEMBLE_SEEDS = base.DEFAULT_ENSEMBLE_SEEDS
DEFAULT_CONTACT_RECEIPT = (
    EXP_DIR / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json"
)
DEFAULT_CONTACT_SCHEMA = (
    EXP_DIR / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json"
)
EXPECTED_CONTACT_SCHEMA_SHA256 = (
    "22d11cdccb0af6ecb26eb3bdcbae6c35dc5bc57543d662cf9da94155ee746cc0"
)
EXPECTED_CONTACT_SCHEMA_RECEIPT_SHA256 = (
    "93bd2427ae0f1205a0055d8913d8d1c0473b97c316b9120632a2d2bdebf16203"
)
CONTACT_SCHEMA_VERSION = "phase2_v4_d_contact_feature_schema_v2"
CONTACT_SCHEMA_RECEIPT_VERSION = "phase2_v4_d_contact_feature_schema_receipt_v2"
DEFAULT_EMBEDDING_MANIFEST = (
    EXP_DIR
    / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_manifest_v3.csv"
)
DEFAULT_EMBEDDING_SUMMARY = DEFAULT_EMBEDDING_MANIFEST.with_name("embedding_summary_v3.json")
EXPECTED_EMBEDDING_MANIFEST_SHA256 = (
    "875bb5304235ff08493919e1603bf5b9a8ef04774416e47c1d851d7a2d614521"
)
MODEL_NAMES = (
    "cdr_length_only",
    "stable_contact_mean",
    "stable_contact_mean_std",
    "embedding_only",
    "embedding_contact_fusion",
)
CANDIDATE_MODELS = MODEL_NAMES[1:]
OUTPUT_FILENAMES = (
    "contact_fusion_open_model_config.json",
    "contact_fusion_open_model_artifact.json",
    "contact_fusion_open_development_predictions.tsv",
    "contact_fusion_open_development_summary.json",
    "contact_fusion_frozen_artifact_sha256_receipt.json",
)
FORBIDDEN_STABLE_TOKENS = (
    "diagnostic",
    "length_confounded",
    "r_dual",
    "r_8x6b",
    "r_9e6y",
    "docking",
    "haddock",
    "geometry",
    "occlusion",
    "pose",
    "teacher",
    "label",
)
CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence/contact-to-independent-dual-docking computational geometry "
    "surrogate only; not binding, affinity, competition, experimental blocking, "
    "Docking Gold, or final submission authority."
)


class ContactFusionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return base.sha256_file(path)


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise ContactFusionError(f"missing_csv:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContactFusionError(f"invalid_json:{path}") from exc
    if not isinstance(payload, dict):
        raise ContactFusionError(f"json_not_object:{path}")
    return payload


def validate_stable_allowlist(
    columns: Sequence[str], *, require_mean_std_pairs: bool = True
) -> tuple[str, ...]:
    values = tuple(str(column) for column in columns)
    if not values or len(values) != len(set(values)):
        raise ContactFusionError("stable_allowlist_empty_or_duplicate")
    allowed_bases = set(contact_v3.STABLE_FEATURE_NAMES)
    for column in values:
        lowered = column.lower()
        if any(token in lowered for token in FORBIDDEN_STABLE_TOKENS):
            raise ContactFusionError(f"forbidden_stable_feature_alias:{column}")
        if column.endswith("_seed_mean"):
            feature = column[: -len("_seed_mean")]
        elif column.endswith("_seed_std"):
            feature = column[: -len("_seed_std")]
        else:
            raise ContactFusionError(f"stable_feature_not_mean_or_std:{column}")
        if feature not in allowed_bases:
            raise ContactFusionError(f"stable_feature_not_in_v3_allowlist:{column}")
        if feature in contact_v3.DIAGNOSTIC_ONLY_FEATURES:
            raise ContactFusionError(f"diagnostic_feature_in_stable_allowlist:{column}")
    means = {column[: -len("_seed_mean")] for column in values if column.endswith("_seed_mean")}
    standard_deviations = {
        column[: -len("_seed_std")] for column in values if column.endswith("_seed_std")
    }
    if require_mean_std_pairs and means != standard_deviations:
        raise ContactFusionError("stable_mean_std_feature_sets_do_not_match")
    return values


def verify_frozen_contact_schema(
    schema_path: Path,
    contact_receipt_path: Path,
    *,
    enforce_production_hash: bool,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    schema_path = schema_path.resolve()
    schema_receipt_path = schema_path.with_suffix(".receipt.json")
    schema = load_json(schema_path)
    schema_receipt = load_json(schema_receipt_path)
    schema_hash = sha256_file(schema_path)
    schema_receipt_hash = sha256_file(schema_receipt_path)
    if enforce_production_hash and schema_hash != EXPECTED_CONTACT_SCHEMA_SHA256:
        raise ContactFusionError("contact_schema_production_hash_mismatch")
    if (
        enforce_production_hash
        and schema_receipt_hash != EXPECTED_CONTACT_SCHEMA_RECEIPT_SHA256
    ):
        raise ContactFusionError("contact_schema_receipt_production_hash_mismatch")

    expected_status = (
        "PASS_FROZEN_LABEL_FREE_CONTACT_FEATURE_SCHEMA"
        if enforce_production_hash
        else "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA"
    )
    expected_receipt_status = (
        "PASS_COMPLETE_HASH_CLOSURE"
        if enforce_production_hash
        else "TEST_ONLY_PASS_HASH_CLOSURE"
    )
    expected_mode = "production" if enforce_production_hash else "test_only"
    if (
        schema.get("schema_version") != CONTACT_SCHEMA_VERSION
        or schema.get("status") != expected_status
        or schema.get("execution_mode") != expected_mode
    ):
        raise ContactFusionError("contact_schema_version_status_or_mode_mismatch")
    if (
        schema_receipt.get("schema_version") != CONTACT_SCHEMA_RECEIPT_VERSION
        or schema_receipt.get("status") != expected_receipt_status
        or schema_receipt.get("schema_file_sha256") != schema_hash
    ):
        raise ContactFusionError("contact_schema_receipt_closure_mismatch")

    configuration = schema.get("configuration")
    if not isinstance(configuration, dict):
        raise ContactFusionError("contact_schema_configuration_missing")
    if (
        schema.get("configuration_sha256") != sha256_json(configuration)
        or schema_receipt.get("configuration_sha256") != schema.get("configuration_sha256")
        or configuration.get("schema_version") != CONTACT_SCHEMA_VERSION
        or configuration.get("selection_uses_docking_labels") is not False
    ):
        raise ContactFusionError("contact_schema_configuration_closure_mismatch")
    payload_without_hash = dict(schema)
    payload_hash = payload_without_hash.pop("payload_sha256", None)
    if (
        not isinstance(payload_hash, str)
        or payload_hash != sha256_json(payload_without_hash)
        or schema_receipt.get("schema_payload_sha256") != payload_hash
    ):
        raise ContactFusionError("contact_schema_payload_hash_mismatch")

    selected_features = tuple(str(value) for value in schema.get("selected_features") or [])
    if (
        not selected_features
        or len(selected_features) != len(set(selected_features))
        or schema.get("selected_feature_count") != len(selected_features)
        or schema.get("required_shortcut_baseline") != "cdr_length_only"
    ):
        raise ContactFusionError("contact_schema_selected_features_invalid")
    stability = schema.get("feature_stability")
    if not isinstance(stability, list):
        raise ContactFusionError("contact_schema_stability_missing")
    selected_from_stability: list[str] = []
    for row in stability:
        if not isinstance(row, dict) or not isinstance(row.get("feature"), str):
            raise ContactFusionError("contact_schema_stability_row_invalid")
        if row.get("selected"):
            if row.get("cross_seed_stable") is not True or row.get("length_confounded") is not False:
                raise ContactFusionError("contact_schema_selected_feature_not_stable")
            selected_from_stability.append(str(row["feature"]))
    if tuple(selected_from_stability) != selected_features:
        raise ContactFusionError("contact_schema_selected_feature_stability_mismatch")
    if any(feature not in contact_v3.STABLE_FEATURE_NAMES for feature in selected_features):
        raise ContactFusionError("contact_schema_feature_not_in_v3_allowlist")
    if set(selected_features) & set(schema.get("diagnostic_only_length_confounded_features") or []):
        raise ContactFusionError("contact_schema_selected_diagnostic_feature")

    expected_means = tuple(f"{feature}_seed_mean" for feature in selected_features)
    expected_mean_std = tuple(
        column
        for feature in selected_features
        for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
    )
    feature_sets = schema.get("training_feature_sets")
    if not isinstance(feature_sets, dict):
        raise ContactFusionError("contact_schema_training_feature_sets_missing")
    if (
        tuple(feature_sets.get("stable_seed_mean") or []) != expected_means
        or tuple(feature_sets.get("stable_seed_mean_and_std") or []) != expected_mean_std
    ):
        raise ContactFusionError("contact_schema_training_feature_sets_mismatch")
    stable_columns = validate_stable_allowlist(expected_mean_std)

    contact_receipt_hash = sha256_file(contact_receipt_path)
    schema_input = (schema.get("inputs") or {}).get("feature_release_receipt")
    if not isinstance(schema_input, dict):
        raise ContactFusionError("contact_schema_feature_receipt_input_missing")
    try:
        schema_input_path = Path(str(schema_input["path"])).resolve()
    except KeyError as exc:
        raise ContactFusionError("contact_schema_feature_receipt_input_missing") from exc
    if (
        schema_input_path != contact_receipt_path.resolve()
        or schema_input.get("sha256") != contact_receipt_hash
        or schema_receipt.get("feature_release_receipt_sha256") != contact_receipt_hash
    ):
        raise ContactFusionError("contact_schema_feature_receipt_hash_or_path_mismatch")
    return stable_columns, {
        "schema_path": str(schema_path),
        "schema_sha256": schema_hash,
        "schema_receipt_path": str(schema_receipt_path),
        "schema_receipt_sha256": schema_receipt_hash,
        "selected_features": list(selected_features),
        "selected_feature_count": len(selected_features),
        "stable_columns": list(stable_columns),
        "selection_uses_docking_labels": False,
    }


def load_verified_contact_release(
    receipt_path: Path,
    schema_path: Path,
    required_ids: set[str],
    *,
    enforce_production_hash: bool,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...], dict[str, Any]]:
    verification = contact_v3.verify_release_receipt(receipt_path)
    stable_columns, schema_metadata = verify_frozen_contact_schema(
        schema_path,
        receipt_path,
        enforce_production_hash=enforce_production_hash,
    )
    receipt = load_json(receipt_path)
    audit_path = Path(str(receipt["audit"]))
    audit = load_json(audit_path)
    if audit.get("feature_schema_version") != contact_v3.SCHEMA_VERSION:
        raise ContactFusionError("contact_feature_schema_is_not_v3")
    policy = audit.get("feature_policy")
    if not isinstance(policy, dict):
        raise ContactFusionError("contact_audit_lacks_feature_policy")
    v3_stable_columns = set(
        validate_stable_allowlist(policy.get("stable_default_trainer_columns") or [])
    )
    if not set(stable_columns) <= v3_stable_columns:
        raise ContactFusionError("contact_schema_columns_not_in_v3_audit_allowlist")
    prohibited = set(policy.get("default_trainer_must_exclude_columns") or [])
    if prohibited & set(stable_columns):
        raise ContactFusionError("contact_stable_and_prohibited_columns_overlap")
    feature_path = Path(str(receipt["output"]))
    rows, fieldnames = read_csv(feature_path)
    required_fields = {"candidate_id", "sequence_sha256", *stable_columns}
    missing = required_fields - set(fieldnames)
    if missing:
        raise ContactFusionError(f"contact_feature_columns_missing:{','.join(sorted(missing))}")
    by_id: dict[str, dict[str, Any]] = {}
    for source in rows:
        candidate_id = source["candidate_id"].strip()
        if candidate_id in by_id:
            raise ContactFusionError(f"duplicate_contact_candidate:{candidate_id}")
        row: dict[str, Any] = {
            "candidate_id": candidate_id,
            "sequence_sha256": source["sequence_sha256"].strip().lower(),
        }
        for column in stable_columns:
            row[column] = base.finite_float(source[column], f"contact:{column}")
        by_id[candidate_id] = row
    missing_ids = sorted(required_ids - set(by_id))
    if missing_ids:
        raise ContactFusionError(
            "contact_features_missing_open_candidates:" + ",".join(missing_ids[:5])
        )
    metadata = {
        "verification": verification,
        "receipt_path": str(receipt_path.resolve()),
        "receipt_sha256": sha256_file(receipt_path),
        "audit_path": str(audit_path.resolve()),
        "audit_sha256": sha256_file(audit_path),
        "feature_path": str(feature_path.resolve()),
        "feature_sha256": sha256_file(feature_path),
        "stable_columns": list(stable_columns),
        "stable_columns_sha256": base.sha256_strings(stable_columns),
        "frozen_schema": schema_metadata,
        "diagnostic_columns_used": [],
        "docking_label_alias_columns_used": [],
    }
    return by_id, stable_columns, metadata


class MeanEmbeddingStore:
    def __init__(
        self,
        manifest_path: Path,
        summary_path: Path,
        required_hashes: set[str],
        *,
        enforce_production_hash: bool,
    ):
        summary = load_json(summary_path)
        if summary.get("schema_version") != "phase2_v3_embedding_summary_v1":
            raise ContactFusionError("embedding_summary_schema_mismatch")
        manifest_hash = sha256_file(manifest_path)
        if summary.get("embedding_manifest_sha256") != manifest_hash:
            raise ContactFusionError("embedding_summary_manifest_hash_mismatch")
        if enforce_production_hash and manifest_hash != EXPECTED_EMBEDDING_MANIFEST_SHA256:
            raise ContactFusionError("embedding_manifest_production_hash_mismatch")
        rows, fieldnames = read_csv(manifest_path)
        required_fields = {
            "sequence_sha256", "sequence_length", "shard_path", "shard_index",
            "esm2_dim", "config_sha256",
        }
        missing = required_fields - set(fieldnames)
        if missing:
            raise ContactFusionError(
                "embedding_manifest_fields_missing:" + ",".join(sorted(missing))
            )
        self.rows: dict[str, dict[str, str]] = {}
        for row in rows:
            digest = row["sequence_sha256"].strip().lower()
            if digest in self.rows:
                raise ContactFusionError(f"duplicate_embedding_sequence:{digest}")
            self.rows[digest] = row
        missing_hashes = sorted(required_hashes - set(self.rows))
        if missing_hashes:
            raise ContactFusionError(
                "embedding_sequences_missing:" + ",".join(missing_hashes[:5])
            )
        dimensions = {int(self.rows[digest]["esm2_dim"]) for digest in required_hashes}
        if len(dimensions) != 1:
            raise ContactFusionError("embedding_dimension_not_constant")
        self.dimension = dimensions.pop()
        self.manifest_path = manifest_path
        self.summary_path = summary_path
        self.config_sha256 = str(summary.get("config_sha256") or "")
        self._shards: dict[Path, dict[str, Any]] = {}
        self.referenced_shards = sorted(
            {self._resolve_shard(self.rows[digest]) for digest in required_hashes},
            key=str,
        )
        if any(not path.is_file() for path in self.referenced_shards):
            raise ContactFusionError("embedding_referenced_shard_missing")

    def _resolve_shard(self, row: Mapping[str, str]) -> Path:
        path = Path(row["shard_path"])
        return path.resolve() if path.is_absolute() else (self.manifest_path.parent / path).resolve()

    def _load_shard(self, path: Path) -> dict[str, Any]:
        if path not in self._shards:
            payload = torch.load(path, map_location="cpu", weights_only=False)
            if not isinstance(payload, dict):
                raise ContactFusionError(f"embedding_shard_not_mapping:{path}")
            if payload.get("config_sha256") != self.config_sha256:
                raise ContactFusionError(f"embedding_shard_config_hash_mismatch:{path}")
            sequence_hashes = payload.get("sequence_sha256")
            embeddings = payload.get("esm2")
            if not isinstance(sequence_hashes, list) or not isinstance(embeddings, torch.Tensor):
                raise ContactFusionError(f"embedding_shard_payload_invalid:{path}")
            if embeddings.ndim != 2 or embeddings.shape[0] != len(sequence_hashes):
                raise ContactFusionError(f"embedding_shard_shape_mismatch:{path}")
            self._shards[path] = payload
        return self._shards[path]

    def get(self, digest: str) -> np.ndarray:
        row = self.rows[digest]
        path = self._resolve_shard(row)
        payload = self._load_shard(path)
        index = int(row["shard_index"])
        sequence_hashes = payload["sequence_sha256"]
        if not 0 <= index < len(sequence_hashes) or sequence_hashes[index] != digest:
            raise ContactFusionError(f"embedding_shard_index_identity_mismatch:{digest}")
        tensor = payload["esm2"][index].detach().float().cpu()
        if tensor.ndim != 1 or len(tensor) != self.dimension:
            raise ContactFusionError(f"embedding_vector_shape_mismatch:{digest}")
        values = tensor.numpy().astype(np.float64, copy=True)
        if not np.all(np.isfinite(values)):
            raise ContactFusionError(f"embedding_non_finite:{digest}")
        return values

    def audit(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path.resolve()),
            "manifest_sha256": sha256_file(self.manifest_path),
            "summary_path": str(self.summary_path.resolve()),
            "summary_sha256": sha256_file(self.summary_path),
            "embedding_dimension": self.dimension,
            "referenced_shard_sha256": {
                str(path): sha256_file(path) for path in self.referenced_shards
            },
        }


def attach_label_free_features(
    rows: Sequence[dict[str, Any]],
    contact_by_id: Mapping[str, Mapping[str, Any]],
    stable_columns: Sequence[str],
    embeddings: MeanEmbeddingStore,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in rows:
        candidate_id = str(source["candidate_id"])
        digest = str(source["sequence_sha256"]).lower()
        contact = contact_by_id[candidate_id]
        if contact["sequence_sha256"] != digest:
            raise ContactFusionError(f"contact_teacher_sequence_hash_mismatch:{candidate_id}")
        row = dict(source)
        row["_contact"] = {
            column: base.finite_float(contact[column], column) for column in stable_columns
        }
        row["_embedding"] = embeddings.get(digest)
        output.append(row)
    return output


@dataclass(frozen=True)
class FeatureSpec:
    model_name: str
    feature_names: tuple[str, ...]
    contact_columns: tuple[str, ...]
    embedding_dimension: int

    def to_json(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "feature_names": list(self.feature_names),
            "contact_columns": list(self.contact_columns),
            "embedding_dimension": self.embedding_dimension,
        }

    @classmethod
    def from_json(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_stable_columns: Sequence[str] | None = None,
    ) -> "FeatureSpec":
        try:
            spec = cls(
                str(payload["model_name"]),
                tuple(str(value) for value in payload["feature_names"]),
                tuple(str(value) for value in payload["contact_columns"]),
                int(payload["embedding_dimension"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContactFusionError("invalid_serialized_feature_spec") from exc
        if spec.model_name not in MODEL_NAMES or spec.embedding_dimension < 1:
            raise ContactFusionError("invalid_serialized_feature_spec")
        if expected_stable_columns is not None:
            stable = validate_stable_allowlist(expected_stable_columns)
            means = tuple(column for column in stable if column.endswith("_seed_mean"))
            expected_contact_columns = {
                "cdr_length_only": (),
                "stable_contact_mean": means,
                "stable_contact_mean_std": stable,
                "embedding_only": (),
                "embedding_contact_fusion": stable,
            }[spec.model_name]
            if spec.contact_columns != expected_contact_columns:
                raise ContactFusionError(
                    f"serialized_contact_feature_set_mismatch:{spec.model_name}"
                )
        elif spec.contact_columns:
            validate_stable_allowlist(
                spec.contact_columns,
                require_mean_std_pairs=spec.model_name != "stable_contact_mean",
            )
        return spec


def build_feature_spec(
    model_name: str,
    stable_columns: Sequence[str],
    embedding_dimension: int,
) -> FeatureSpec:
    stable = validate_stable_allowlist(stable_columns)
    means = tuple(column for column in stable if column.endswith("_seed_mean"))
    if model_name == "cdr_length_only":
        names = ("sequence_length", "cdr1_length", "cdr2_length", "cdr3_length")
        contact_columns: tuple[str, ...] = ()
    elif model_name == "stable_contact_mean":
        names = means
        contact_columns = means
    elif model_name == "stable_contact_mean_std":
        names = stable
        contact_columns = stable
    elif model_name == "embedding_only":
        names = tuple(f"esm2_mean_{index}" for index in range(embedding_dimension))
        contact_columns = ()
    elif model_name == "embedding_contact_fusion":
        names = tuple(f"esm2_mean_{index}" for index in range(embedding_dimension)) + stable
        contact_columns = stable
    else:
        raise ContactFusionError(f"unknown_model:{model_name}")
    return FeatureSpec(model_name, names, contact_columns, embedding_dimension)


def encode_features(row: Mapping[str, Any], spec: FeatureSpec) -> list[float]:
    if spec.model_name == "cdr_length_only":
        return [
            len(base.validate_sequence(str(row["sequence"]))) / 150.0,
            len(base.validate_sequence(str(row["cdr1"]))) / 15.0,
            len(base.validate_sequence(str(row["cdr2"]))) / 15.0,
            len(base.validate_sequence(str(row["cdr3"]))) / 30.0,
        ]
    contact_values = [base.finite_float(row["_contact"][column], column) for column in spec.contact_columns]
    if spec.model_name in {"stable_contact_mean", "stable_contact_mean_std"}:
        return contact_values
    embedding = np.asarray(row["_embedding"], dtype=np.float64)
    if embedding.shape != (spec.embedding_dimension,) or not np.all(np.isfinite(embedding)):
        raise ContactFusionError("embedding_feature_shape_or_finiteness_mismatch")
    if spec.model_name == "embedding_only":
        return embedding.tolist()
    if spec.model_name == "embedding_contact_fusion":
        return embedding.tolist() + contact_values
    raise ContactFusionError(f"unknown_model:{spec.model_name}")


def feature_matrix(rows: Sequence[dict[str, Any]], spec: FeatureSpec) -> np.ndarray:
    matrix = np.asarray([encode_features(row, spec) for row in rows], dtype=np.float64)
    if matrix.shape != (len(rows), len(spec.feature_names)) or not np.all(np.isfinite(matrix)):
        raise ContactFusionError(f"feature_matrix_invalid:{spec.model_name}:{matrix.shape}")
    return matrix


def train_one_model(
    model_name: str,
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    stable_columns: Sequence[str],
    embedding_dimension: int,
    alphas: Sequence[float],
    ensemble_seeds: Sequence[int],
) -> dict[str, Any]:
    spec = build_feature_spec(model_name, stable_columns, embedding_dimension)
    x_train = feature_matrix(train_rows, spec)
    x_development = feature_matrix(development_rows, spec)
    y_train = np.asarray([base.finite_float(row[PRIMARY_TARGET], PRIMARY_TARGET) for row in train_rows])
    y_development = np.asarray(
        [base.finite_float(row[PRIMARY_TARGET], PRIMARY_TARGET) for row in development_rows]
    )
    candidates: list[tuple[tuple[float, ...], float, base.RidgeFit, np.ndarray, dict[str, float]]] = []
    for alpha in alphas:
        fit = base.fit_ridge(x_train, y_train, float(alpha))
        prediction = base.predict_ridge(x_development, fit)
        metric = base.regression_metrics(y_development, prediction)
        candidates.append((base.selection_key(metric, float(alpha)), float(alpha), fit, prediction, metric))
    _key, selected_alpha, direct_fit, direct_prediction, direct_metrics = max(
        candidates, key=lambda item: item[0]
    )
    seed_predictions: list[np.ndarray] = []
    seed_fits: list[dict[str, Any]] = []
    for seed in ensemble_seeds:
        indices = base.group_bootstrap_indices(train_rows, int(seed))
        fit = base.fit_ridge(x_train[indices], y_train[indices], selected_alpha)
        seed_predictions.append(base.predict_ridge(x_development, fit))
        seed_fits.append(
            {
                "seed": int(seed),
                "sampled_train_row_count": len(indices),
                "sampled_train_candidate_ids_sha256": base.sha256_strings(
                    str(train_rows[index]["candidate_id"]) for index in indices
                ),
                "fit": fit.to_json(),
            }
        )
    matrix = np.asarray(seed_predictions, dtype=np.float64)
    ensemble_prediction = matrix.mean(axis=0)
    uncertainty = matrix.std(axis=0)
    parents = [str(row["parent_framework_cluster"]) for row in development_rows]
    return {
        "model_name": model_name,
        "feature_spec": spec,
        "selected_alpha": selected_alpha,
        "direct_fit": direct_fit,
        "direct_prediction": direct_prediction,
        "direct_metrics": direct_metrics,
        "ensemble_prediction": ensemble_prediction,
        "ensemble_uncertainty": uncertainty,
        "ensemble_metrics": base.regression_metrics(y_development, ensemble_prediction),
        "parent_macro_ensemble_metrics": base.parent_macro_regression_metrics(
            y_development, ensemble_prediction, parents
        ),
        "ensemble_metric_distribution": base.metric_distribution(y_development, matrix),
        "selective_risk": base.selective_risk(
            y_development, ensemble_prediction, uncertainty, parents
        ),
        "seed_fits": seed_fits,
        "alpha_development_metrics": {
            str(alpha): metric for _sort, alpha, _fit, _prediction, metric in candidates
        },
    }


def train_models(
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    stable_columns: Sequence[str],
    embedding_dimension: int,
    alphas: Sequence[float],
    ensemble_seeds: Sequence[int],
) -> dict[str, Any]:
    if len(set(ensemble_seeds)) < 3:
        raise ContactFusionError("at_least_three_unique_ensemble_seeds_required")
    if not alphas or any(float(alpha) <= 0 for alpha in alphas):
        raise ContactFusionError("ridge_alphas_must_be_positive")
    models = {
        name: train_one_model(
            name,
            train_rows,
            development_rows,
            stable_columns,
            embedding_dimension,
            alphas,
            ensemble_seeds,
        )
        for name in MODEL_NAMES
    }
    selected = max(
        CANDIDATE_MODELS,
        key=lambda name: (
            models[name]["ensemble_metrics"]["spearman"],
            models[name]["ensemble_metrics"]["ndcg"],
            models[name]["ensemble_metrics"]["top_quartile_recall_at_25pct_budget"],
            -models[name]["ensemble_metrics"]["mae"],
            name,
        ),
    )
    strongest_nonfusion = max(
        ("cdr_length_only", "stable_contact_mean", "stable_contact_mean_std", "embedding_only"),
        key=lambda name: (
            models[name]["ensemble_metrics"]["spearman"],
            models[name]["ensemble_metrics"]["ndcg"],
            -models[name]["ensemble_metrics"]["mae"],
            name,
        ),
    )
    gates = base.evaluate_open_performance_gates(
        models[selected], models["cdr_length_only"]
    )
    return {
        "models": models,
        "selected_candidate": selected,
        "strongest_nonfusion_or_length_baseline": strongest_nonfusion,
        "fusion_spearman_delta_over_embedding_only": round(
            models["embedding_contact_fusion"]["ensemble_metrics"]["spearman"]
            - models["embedding_only"]["ensemble_metrics"]["spearman"],
            9,
        ),
        "fusion_spearman_delta_over_contact_mean_std": round(
            models["embedding_contact_fusion"]["ensemble_metrics"]["spearman"]
            - models["stable_contact_mean_std"]["ensemble_metrics"]["spearman"],
            9,
        ),
        "open_performance_gates_vs_cdr_length_only": gates,
    }


def serialized_model(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "feature_spec": result["feature_spec"].to_json(),
        "selected_alpha": result["selected_alpha"],
        "bootstrap_ensemble_fits": result["seed_fits"],
        "fit_split": TRAIN_SPLIT,
        "fit_labels": PRIMARY_TARGET,
        "development_rows_used_as_fit_rows": 0,
        "prospective_test_rows_used_as_fit_rows": 0,
    }


def predict_serialized_model(
    artifact: Mapping[str, Any], model_name: str, rows: Sequence[dict[str, Any]]
) -> tuple[np.ndarray, np.ndarray]:
    model = artifact.get("models", {}).get(model_name)
    if not isinstance(model, dict):
        raise ContactFusionError(f"serialized_model_missing:{model_name}")
    if not rows or not isinstance(rows[0].get("_contact"), dict):
        raise ContactFusionError("prediction_rows_lack_verified_contact_features")
    expected_stable_columns = tuple(str(column) for column in rows[0]["_contact"])
    spec = FeatureSpec.from_json(
        model["feature_spec"], expected_stable_columns=expected_stable_columns
    )
    if spec.model_name != model_name:
        raise ContactFusionError(f"serialized_model_spec_mismatch:{model_name}")
    x = feature_matrix(rows, spec)
    predictions: list[np.ndarray] = []
    seeds: set[int] = set()
    for row in model.get("bootstrap_ensemble_fits") or []:
        seed = int(row["seed"])
        if seed in seeds:
            raise ContactFusionError(f"duplicate_serialized_seed:{model_name}:{seed}")
        seeds.add(seed)
        fit = base.RidgeFit.from_json(row["fit"])
        if len(fit.coefficient) != x.shape[1]:
            raise ContactFusionError(f"serialized_fit_width_mismatch:{model_name}")
        predictions.append(base.predict_ridge(x, fit))
    if len(predictions) < 3:
        raise ContactFusionError(f"serialized_ensemble_too_small:{model_name}")
    matrix = np.asarray(predictions, dtype=np.float64)
    return matrix.mean(axis=0), matrix.std(axis=0)


def validate_output_directory(out_dir: Path) -> None:
    if out_dir.exists() and not out_dir.is_dir():
        raise ContactFusionError(f"output_path_is_not_directory:{out_dir}")
    if out_dir.exists():
        unexpected = sorted(
            path.name for path in out_dir.iterdir() if path.name not in set(OUTPUT_FILENAMES)
        )
        if unexpected:
            raise ContactFusionError("unexpected_existing_output_files:" + ",".join(unexpected))


def publish_staged(staging: Path, out_dir: Path, stale_receipt_expected: bool) -> dict[str, Any]:
    validate_output_directory(out_dir)
    if any(not (staging / name).is_file() for name in OUTPUT_FILENAMES):
        raise ContactFusionError("staged_output_set_incomplete")
    receipt = load_json(staging / OUTPUT_FILENAMES[-1])
    expected_paths = {str((out_dir / name).resolve()) for name in OUTPUT_FILENAMES[:-1]}
    if set(receipt.get("outputs", {})) != expected_paths:
        raise ContactFusionError("staged_receipt_output_set_mismatch")
    out_dir.mkdir(parents=True, exist_ok=True)
    final_receipt = out_dir / OUTPUT_FILENAMES[-1]
    if final_receipt.exists() != stale_receipt_expected:
        raise ContactFusionError("publication_stale_receipt_state_changed")
    final_receipt.unlink(missing_ok=True)
    for name in OUTPUT_FILENAMES[:-1]:
        os.replace(staging / name, out_dir / name)
        final = (out_dir / name).resolve()
        if sha256_file(final) != receipt["outputs"][str(final)]:
            raise ContactFusionError(f"published_output_hash_mismatch:{name}")
    os.replace(staging / OUTPUT_FILENAMES[-1], final_receipt)
    descriptor = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "policy": "stage_all_outputs_then_atomic_file_replace_with_receipt_last",
        "stale_receipt_removed_before_replacement": stale_receipt_expected,
        "receipt_published_last": True,
    }


def summary_model(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected_alpha": result["selected_alpha"],
        "feature_count": len(result["feature_spec"].feature_names),
        "feature_names": list(result["feature_spec"].feature_names),
        "ensemble_development_metrics": result["ensemble_metrics"],
        "parent_macro_ensemble_development_metrics": result[
            "parent_macro_ensemble_metrics"
        ],
        "bootstrap_seed_metric_distribution": result["ensemble_metric_distribution"],
        "selective_risk": result["selective_risk"],
        "alpha_development_metrics": result["alpha_development_metrics"],
    }


def run_pipeline(
    teacher_path: Path,
    teacher_audit_path: Path,
    split_manifest_path: Path,
    contact_receipt_path: Path,
    contact_schema_path: Path,
    embedding_manifest_path: Path,
    embedding_summary_path: Path,
    out_dir: Path,
    *,
    alphas: Sequence[float] = DEFAULT_ALPHAS,
    ensemble_seeds: Sequence[int] = DEFAULT_ENSEMBLE_SEEDS,
    expected_counts: Mapping[str, int] = base.EXPECTED_SPLIT_COUNTS,
    expected_cluster_counts: Mapping[str, int] = base.EXPECTED_CLUSTER_COUNTS,
    enforce_production_locks: bool = True,
) -> dict[str, Any]:
    if enforce_production_locks and sha256_file(split_manifest_path) != base.EXPECTED_SPLIT_MANIFEST_SHA256:
        raise ContactFusionError("split_manifest_production_hash_mismatch")
    teacher_audit = base.validate_teacher_audit(
        teacher_path, teacher_audit_path, split_manifest_path
    )
    split_rows = base.read_tsv(split_manifest_path)
    split_by_id = base.validate_split_manifest(
        split_rows, expected_counts=expected_counts, expected_cluster_counts=expected_cluster_counts
    )
    teacher_rows = base.read_tsv(teacher_path)
    train_rows, development_rows = base.validate_teacher_rows(
        teacher_rows, split_by_id, PRIMARY_TARGET, expected_counts=expected_counts
    )
    open_ids = {str(row["candidate_id"]) for row in train_rows + development_rows}
    contact_by_id, stable_columns, contact_metadata = load_verified_contact_release(
        contact_receipt_path,
        contact_schema_path,
        open_ids,
        enforce_production_hash=enforce_production_locks,
    )
    required_hashes = {str(row["sequence_sha256"]).lower() for row in train_rows + development_rows}
    embedding_store = MeanEmbeddingStore(
        embedding_manifest_path,
        embedding_summary_path,
        required_hashes,
        enforce_production_hash=enforce_production_locks,
    )
    train_rows = attach_label_free_features(
        train_rows, contact_by_id, stable_columns, embedding_store
    )
    development_rows = attach_label_free_features(
        development_rows, contact_by_id, stable_columns, embedding_store
    )
    trained = train_models(
        train_rows,
        development_rows,
        stable_columns,
        embedding_store.dimension,
        alphas,
        ensemble_seeds,
    )
    test_ids = sorted(
        str(row["candidate_id"]) for row in split_rows if row["model_split"] == SEALED_SPLIT
    )

    out_dir = out_dir.resolve()
    final_paths = {name: out_dir / name for name in OUTPUT_FILENAMES}
    with base.output_publication_lock(out_dir):
        validate_output_directory(out_dir)
        stale_receipt = final_paths[OUTPUT_FILENAMES[-1]].exists()
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.stage.", dir=out_dir.parent))
        try:
            config_path = staging / OUTPUT_FILENAMES[0]
            model_path = staging / OUTPUT_FILENAMES[1]
            predictions_path = staging / OUTPUT_FILENAMES[2]
            summary_path = staging / OUTPUT_FILENAMES[3]
            receipt_path = staging / OUTPUT_FILENAMES[4]
            embedding_audit = embedding_store.audit()
            config = {
                "schema_version": SCHEMA_VERSION,
                "status": "FROZEN_OPEN_CONFIGURATION_BEFORE_PROSPECTIVE_TEST_UNSEAL",
                "primary_target": PRIMARY_TARGET,
                "fit_split": TRAIN_SPLIT,
                "selection_split": DEVELOPMENT_SPLIT,
                "group_unit": "parent_framework_cluster",
                "models": list(MODEL_NAMES),
                "required_shortcut_baseline": "cdr_length_only",
                "alphas": list(alphas),
                "group_bootstrap_ensemble_seeds": list(ensemble_seeds),
                "contact_feature_policy": {
                    "source": "verified_v3_receipt_plus_frozen_v2_schema_selected_features_only",
                    "stable_columns": list(stable_columns),
                    "selected_features": contact_metadata["frozen_schema"]["selected_features"],
                    "diagnostic_or_length_confounded_columns_used": [],
                    "docking_label_alias_columns_used": [],
                },
                "embedding_policy": {
                    "field": "esm2",
                    "dimension": embedding_store.dimension,
                    "frozen": True,
                    "label_fitted": False,
                },
                "prospective_test": {
                    "manifest_rows": len(test_ids),
                    "labels_read": False,
                    "label_files_opened": 0,
                    "used_for_training_or_selection": False,
                },
                "inputs": {
                    "teacher_sha256": sha256_file(teacher_path),
                    "teacher_audit_sha256": sha256_file(teacher_audit_path),
                    "split_manifest_sha256": sha256_file(split_manifest_path),
                    "contact_release": contact_metadata,
                    "embedding_release": embedding_audit,
                },
                "runtime_provenance": {
                    "python_version": sys.version,
                    "numpy_version": np.__version__,
                    "torch_version": torch.__version__,
                    "platform": platform.platform(),
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            base.write_json(config_path, config)
            artifact = {
                "schema_version": SCHEMA_VERSION,
                "status": "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
                "config_sha256": sha256_file(config_path),
                "selected_candidate_model": trained["selected_candidate"],
                "strongest_nonfusion_or_length_baseline": trained[
                    "strongest_nonfusion_or_length_baseline"
                ],
                "models": {
                    name: serialized_model(trained["models"][name]) for name in MODEL_NAMES
                },
                "fit_row_count": len(train_rows),
                "development_row_count_used_for_selection_only": len(development_rows),
                "prospective_test_labels_read": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            base.write_json(model_path, artifact)
            reloaded = load_json(model_path)
            predictions = {
                name: predict_serialized_model(reloaded, name, development_rows)
                for name in MODEL_NAMES
            }
            for name in MODEL_NAMES:
                expected_prediction = trained["models"][name]["ensemble_prediction"]
                expected_uncertainty = trained["models"][name]["ensemble_uncertainty"]
                if not np.array_equal(
                    np.round(predictions[name][0], 9), np.round(expected_prediction, 9)
                ) or not np.array_equal(
                    np.round(predictions[name][1], 9), np.round(expected_uncertainty, 9)
                ):
                    raise ContactFusionError(f"serialized_prediction_roundtrip_mismatch:{name}")
            y_development = np.asarray(
                [base.finite_float(row[PRIMARY_TARGET], PRIMARY_TARGET) for row in development_rows]
            )
            prediction_rows: list[dict[str, Any]] = []
            selected = trained["selected_candidate"]
            for index, row in enumerate(development_rows):
                output: dict[str, Any] = {
                    "candidate_id": row["candidate_id"],
                    "model_split": row["model_split"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                    "target_R_dual_min": round(float(y_development[index]), 9),
                    "selected_model": selected,
                }
                for name in MODEL_NAMES:
                    prediction, uncertainty = predictions[name]
                    output[f"prediction_{name}"] = round(float(prediction[index]), 9)
                    output[f"uncertainty_{name}"] = round(float(uncertainty[index]), 9)
                output["selected_prediction"] = output[f"prediction_{selected}"]
                output["selected_uncertainty"] = output[f"uncertainty_{selected}"]
                prediction_rows.append(output)
            base.write_tsv(predictions_path, prediction_rows)
            selected_risk = trained["models"][selected]["selective_risk"]
            summary = {
                "schema_version": SCHEMA_VERSION,
                "status": "OPEN_DEVELOPMENT_EVALUATED_PROSPECTIVE_TEST_STILL_SEALED",
                "teacher_release_status": teacher_audit["status"],
                "fit": {
                    "split": TRAIN_SPLIT,
                    "rows": len(train_rows),
                    "parent_clusters": len({row["parent_framework_cluster"] for row in train_rows}),
                },
                "selection": {
                    "split": DEVELOPMENT_SPLIT,
                    "rows": len(development_rows),
                    "parent_clusters": len(
                        {row["parent_framework_cluster"] for row in development_rows}
                    ),
                },
                "prospective_test": {
                    "split": SEALED_SPLIT,
                    "manifest_rows": len(test_ids),
                    "labels_read": False,
                    "label_files_opened": 0,
                    "used_for_training_or_selection": False,
                },
                "models": {
                    name: summary_model(trained["models"][name]) for name in MODEL_NAMES
                },
                "selected_candidate_model": selected,
                "strongest_nonfusion_or_length_baseline": trained[
                    "strongest_nonfusion_or_length_baseline"
                ],
                "fusion_spearman_delta_over_embedding_only": trained[
                    "fusion_spearman_delta_over_embedding_only"
                ],
                "fusion_spearman_delta_over_contact_mean_std": trained[
                    "fusion_spearman_delta_over_contact_mean_std"
                ],
                "open_performance_gates_vs_cdr_length_only": trained[
                    "open_performance_gates_vs_cdr_length_only"
                ],
                "selected_model_uncertainty_contract": selected_risk,
                "parent_macro_contract": trained["models"][selected][
                    "parent_macro_ensemble_metrics"
                ],
                "deployment_eligible": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            base.write_json(summary_path, summary)
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE",
                "prospective_test_labels_read": False,
                "stable_contact_columns": list(stable_columns),
                "diagnostic_or_docking_alias_columns_used": [],
                "publication": {
                    "policy": "stage_all_outputs_then_atomic_file_replace_with_receipt_last",
                    "stale_receipt_removed_before_replacement": stale_receipt,
                    "receipt_published_last": True,
                },
                "inputs": {
                    str(teacher_path.resolve()): sha256_file(teacher_path),
                    str(teacher_audit_path.resolve()): sha256_file(teacher_audit_path),
                    str(split_manifest_path.resolve()): sha256_file(split_manifest_path),
                    str(contact_receipt_path.resolve()): sha256_file(contact_receipt_path),
                    str(contact_schema_path.resolve()): sha256_file(contact_schema_path),
                    str(contact_schema_path.resolve().with_suffix(".receipt.json")): sha256_file(
                        contact_schema_path.resolve().with_suffix(".receipt.json")
                    ),
                    str(embedding_manifest_path.resolve()): sha256_file(embedding_manifest_path),
                    str(embedding_summary_path.resolve()): sha256_file(embedding_summary_path),
                    str(Path(__file__).resolve()): sha256_file(Path(__file__)),
                    str(Path(base.__file__).resolve()): sha256_file(Path(base.__file__)),
                    **embedding_audit["referenced_shard_sha256"],
                },
                "outputs": {
                    str(final_paths[OUTPUT_FILENAMES[0]]): sha256_file(config_path),
                    str(final_paths[OUTPUT_FILENAMES[1]]): sha256_file(model_path),
                    str(final_paths[OUTPUT_FILENAMES[2]]): sha256_file(predictions_path),
                    str(final_paths[OUTPUT_FILENAMES[3]]): sha256_file(summary_path),
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            base.write_json(receipt_path, receipt)
            publication = publish_staged(staging, out_dir, stale_receipt)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return {
        "status": summary["status"],
        "summary": str(final_paths[OUTPUT_FILENAMES[3]]),
        "receipt": str(final_paths[OUTPUT_FILENAMES[4]]),
        "selected_candidate_model": trained["selected_candidate"],
        "prospective_test_labels_read": False,
        "publication": publication,
    }


def parse_numbers(value: str, cast: type) -> tuple[Any, ...]:
    try:
        values = tuple(cast(token.strip()) for token in value.split(",") if token.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid_number_list:{value}") from exc
    if not values:
        raise argparse.ArgumentTypeError("empty_number_list")
    return values


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-audit", type=Path)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument("--contact-receipt", type=Path, default=DEFAULT_CONTACT_RECEIPT)
    parser.add_argument("--contact-schema", type=Path, default=DEFAULT_CONTACT_SCHEMA)
    parser.add_argument("--embedding-manifest", type=Path, default=DEFAULT_EMBEDDING_MANIFEST)
    parser.add_argument("--embedding-summary", type=Path, default=DEFAULT_EMBEDDING_SUMMARY)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--alphas", default=",".join(str(value) for value in DEFAULT_ALPHAS))
    parser.add_argument(
        "--ensemble-seeds", default=",".join(str(value) for value in DEFAULT_ENSEMBLE_SEEDS)
    )
    args = parser.parse_args(argv)
    teacher_audit = args.teacher_audit or args.teacher.with_suffix(args.teacher.suffix + ".audit.json")
    result = run_pipeline(
        args.teacher,
        teacher_audit,
        args.split_manifest,
        args.contact_receipt,
        args.contact_schema,
        args.embedding_manifest,
        args.embedding_summary,
        args.out_dir,
        alphas=parse_numbers(args.alphas, float),
        ensemble_seeds=parse_numbers(args.ensemble_seeds, int),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
