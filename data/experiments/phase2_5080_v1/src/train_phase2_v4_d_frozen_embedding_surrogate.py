#!/usr/bin/env python3
"""Train hash-closed V4-D frozen-embedding dual-ridge surrogates.

The open teacher contains only OPEN_TRAIN and OPEN_DEVELOPMENT labels. The
prospective split is joined to frozen embeddings by sequence hash and receives
predictions only; this program has no argument for a prospective label source.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v4_d_surrogate as base  # noqa: E402


SCHEMA_VERSION = "phase2_v4_d_frozen_embedding_surrogate_v1"
EXPECTED_EMBEDDING_MANIFEST_SHA256 = (
    "875bb5304235ff08493919e1603bf5b9a8ef04774416e47c1d851d7a2d614521"
)
EXPECTED_EMBEDDING_SUMMARY_SHA256 = (
    "0b5a5f01d82775ada2ed3bd505011a954be0c69fe73a2918a0c0c9c87b7af49c"
)
EXPECTED_SEQUENCE_MANIFEST_SHA256 = (
    "c456ec7cb4dd36df0a9e95e103ad2f9b597eebcee43281cfd6c06dc99ea06297"
)
EXPECTED_EMBEDDING_CONFIG_SHA256 = (
    "e525cb725bc5b9ea93c2f91ba84209cc3992d1e65e0e0d78f79b7c219ba33636"
)
EXPECTED_SHARD_SHA256 = {
    "shard_00000.pt": "731af1d81210f8443065c36fa8fe0472e62f2f5093d3404c2bdc6bbcb57a1465",
    "shard_00001.pt": "3b08d1b685904bfad4855b377541b3c9477a3082e7b017a53b7b5ca2396732f1",
    "shard_00002.pt": "b1041c04293a1ea3ad7f094f6185731921f9d964123ca42f524eae126f930e10",
    "shard_00003.pt": "ba8b7305eb75b38d72ba12b5bf965128e41d7940b9f87351607b1e5e856349bf",
    "shard_00004.pt": "b63998c6c00f6a2524460143be7fc2453ff77b8fc4671d8c94d5bdaf20f2f204",
    "shard_00005.pt": "34fd3f75bd52fc274ccdb7bf2b52aba05b916d4edc9aaa13fc9d2f61e52e512a",
    "shard_00006.pt": "a3779bb01273d173e9e4424e587a999171d1960ec03bb833f75823e8f060b7e9",
}
EXPECTED_SEQUENCE_COUNT = 7088
EXPECTED_VHH_COUNT = 7087
EXPECTED_DIMS = {"esm2": 320, "vhhbert": 768, "physchem": 27}
EMBEDDING_MODELS = ("esm2_ridge", "vhhbert_ridge", "joint_ridge")
LOCAL_SHORTCUT_MODELS = ("cdr_length_only",)
MODEL_CHANNELS = {
    "esm2_ridge": ("esm2",),
    "vhhbert_ridge": ("vhhbert",),
    "joint_ridge": ("vhhbert", "esm2", "physchem"),
}
OUTPUT_FILENAMES = (
    "frozen_embedding_model_config.json",
    "frozen_embedding_model_artifact.json",
    "open_development_embedding_predictions.tsv",
    "frozen_prospective_test_predictions.tsv",
    "open_development_embedding_summary.json",
    "frozen_embedding_artifact_sha256_receipt.json",
)
CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence-to-independent-dual-docking frozen-embedding surrogate; "
    "computational geometry only, not binding, affinity, competition, Docking Gold, "
    "experimental blocking, or final submission authority."
)


class FrozenEmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    payload: bytes
    sha256: str


def snapshot_file(path: Path) -> FileSnapshot:
    resolved = path.resolve()
    with resolved.open("rb") as handle:
        payload = handle.read()
    return FileSnapshot(resolved, payload, hashlib.sha256(payload).hexdigest())


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    return read_csv_snapshot(snapshot_file(path))


def read_csv_snapshot(snapshot: FileSnapshot) -> list[dict[str, str]]:
    text = snapshot.payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def read_tsv_snapshot(snapshot: FileSnapshot) -> list[dict[str, str]]:
    text = snapshot.payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter="\t"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise FrozenEmbeddingError("refusing_to_write_empty_predictions")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def require_columns(rows: list[dict[str, str]], columns: Sequence[str], label: str) -> None:
    if not rows:
        raise FrozenEmbeddingError(f"empty_table:{label}")
    missing = [column for column in columns if column not in rows[0]]
    if missing:
        raise FrozenEmbeddingError(f"missing_columns:{label}:{','.join(missing)}")


@dataclass(frozen=True)
class EmbeddingBank:
    index_by_sha256: dict[str, int]
    sequence_sha256: tuple[str, ...]
    roles: tuple[str, ...]
    esm2: np.ndarray
    vhhbert: np.ndarray
    physchem: np.ndarray
    config_sha256: str
    provenance: dict[str, Any]

    def matrix(self, sequence_hashes: Sequence[str], model_name: str) -> np.ndarray:
        if model_name not in MODEL_CHANNELS:
            raise FrozenEmbeddingError(f"unknown_embedding_model:{model_name}")
        missing = [value for value in sequence_hashes if value not in self.index_by_sha256]
        if missing:
            raise FrozenEmbeddingError(
                "embedding_hashes_missing:" + ",".join(sorted(set(missing))[:5])
            )
        indices = np.asarray([self.index_by_sha256[value] for value in sequence_hashes])
        parts = [np.asarray(getattr(self, channel)[indices], dtype=np.float64) for channel in MODEL_CHANNELS[model_name]]
        matrix = np.concatenate(parts, axis=1) if len(parts) > 1 else parts[0]
        if not np.all(np.isfinite(matrix)):
            raise FrozenEmbeddingError(f"non_finite_embedding_matrix:{model_name}")
        return matrix


def _expected_shard_hashes(
    summary: Mapping[str, Any], enforce_production_hashes: bool
) -> dict[str, str]:
    if enforce_production_hashes:
        return dict(EXPECTED_SHARD_SHA256)
    raw = summary.get("shard_sha256")
    if not isinstance(raw, Mapping) or not raw:
        raise FrozenEmbeddingError("embedding_summary_shard_hashes_missing")
    output = {str(key): str(value) for key, value in raw.items()}
    if any(len(value) != 64 for value in output.values()):
        raise FrozenEmbeddingError("embedding_summary_shard_hash_invalid")
    return output


def load_embedding_bank(
    embedding_manifest_path: Path,
    embedding_summary_path: Path,
    sequence_manifest_path: Path,
    *,
    enforce_production_hashes: bool = True,
    embedding_manifest_snapshot: FileSnapshot | None = None,
    embedding_summary_snapshot: FileSnapshot | None = None,
    sequence_manifest_snapshot: FileSnapshot | None = None,
) -> EmbeddingBank:
    manifest_snapshot = embedding_manifest_snapshot or snapshot_file(
        embedding_manifest_path
    )
    summary_snapshot = embedding_summary_snapshot or snapshot_file(
        embedding_summary_path
    )
    sequence_snapshot = sequence_manifest_snapshot or snapshot_file(
        sequence_manifest_path
    )
    manifest_hash = manifest_snapshot.sha256
    summary_hash = summary_snapshot.sha256
    sequence_manifest_hash = sequence_snapshot.sha256
    if enforce_production_hashes:
        expected = (
            (manifest_hash, EXPECTED_EMBEDDING_MANIFEST_SHA256, "embedding_manifest"),
            (summary_hash, EXPECTED_EMBEDDING_SUMMARY_SHA256, "embedding_summary"),
            (sequence_manifest_hash, EXPECTED_SEQUENCE_MANIFEST_SHA256, "sequence_manifest"),
        )
        for observed, frozen, label in expected:
            if observed != frozen:
                raise FrozenEmbeddingError(f"production_{label}_sha256_mismatch")

    try:
        summary = json.loads(summary_snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenEmbeddingError("invalid_embedding_summary") from exc
    if summary.get("schema_version") != "phase2_v3_embedding_summary_v1":
        raise FrozenEmbeddingError("embedding_summary_schema_mismatch")
    if summary.get("embedding_manifest_sha256") != manifest_hash:
        raise FrozenEmbeddingError("summary_embedding_manifest_hash_mismatch")
    if summary.get("sequence_manifest_sha256") != sequence_manifest_hash:
        raise FrozenEmbeddingError("summary_sequence_manifest_hash_mismatch")
    config = summary.get("config")
    if not isinstance(config, Mapping):
        raise FrozenEmbeddingError("embedding_summary_config_missing")
    config_sha256 = sha256_json(config)
    if summary.get("config_sha256") != config_sha256:
        raise FrozenEmbeddingError("embedding_summary_config_hash_mismatch")
    if enforce_production_hashes and config_sha256 != EXPECTED_EMBEDDING_CONFIG_SHA256:
        raise FrozenEmbeddingError("production_embedding_config_hash_mismatch")
    if enforce_production_hashes and config.get("backend") != "real":
        raise FrozenEmbeddingError("production_embedding_backend_not_real")

    manifest_rows = read_csv_snapshot(manifest_snapshot)
    sequence_rows = read_csv_snapshot(sequence_snapshot)
    require_columns(
        manifest_rows,
        (
            "sequence_sha256",
            "sequence_length",
            "roles",
            "shard_path",
            "shard_index",
            "esm2_dim",
            "vhhbert_dim",
            "physchem_dim",
            "config_sha256",
        ),
        "embedding_manifest",
    )
    require_columns(
        sequence_rows,
        ("sequence_sha256", "sequence", "sequence_length", "roles"),
        "sequence_manifest",
    )
    if len({row["sequence_sha256"] for row in manifest_rows}) != len(manifest_rows):
        raise FrozenEmbeddingError("duplicate_embedding_sequence_sha256")
    if len({row["sequence_sha256"] for row in sequence_rows}) != len(sequence_rows):
        raise FrozenEmbeddingError("duplicate_sequence_manifest_sha256")
    manifest_hashes = [row["sequence_sha256"] for row in manifest_rows]
    sequence_hashes = [row["sequence_sha256"] for row in sequence_rows]
    if manifest_hashes != sequence_hashes:
        raise FrozenEmbeddingError("embedding_sequence_manifest_order_mismatch")
    for row in sequence_rows:
        sequence = base.validate_sequence(row["sequence"], "embedding_sequence_manifest")
        if base.sequence_sha256(sequence) != row["sequence_sha256"]:
            raise FrozenEmbeddingError(
                f"embedding_sequence_sha256_mismatch:{row['sequence_sha256']}"
            )
        if int(row["sequence_length"]) != len(sequence):
            raise FrozenEmbeddingError(
                f"embedding_sequence_length_mismatch:{row['sequence_sha256']}"
            )
    for manifest, sequence in zip(manifest_rows, sequence_rows):
        if manifest["sequence_length"] != sequence["sequence_length"]:
            raise FrozenEmbeddingError("embedding_manifest_sequence_length_mismatch")
        if manifest["roles"] != sequence["roles"]:
            raise FrozenEmbeddingError("embedding_manifest_roles_mismatch")
        if manifest["config_sha256"] != config_sha256:
            raise FrozenEmbeddingError("embedding_manifest_config_hash_mismatch")

    expected_count = EXPECTED_SEQUENCE_COUNT if enforce_production_hashes else len(sequence_rows)
    if len(manifest_rows) != expected_count:
        raise FrozenEmbeddingError(
            f"embedding_sequence_count_mismatch:{len(manifest_rows)}:{expected_count}"
        )
    vhh_count = sum("vhh" in row["roles"].split(";") for row in sequence_rows)
    if enforce_production_hashes and vhh_count != EXPECTED_VHH_COUNT:
        raise FrozenEmbeddingError(f"embedding_vhh_count_mismatch:{vhh_count}")
    if int(summary.get("sequence_count", -1)) != len(sequence_rows):
        raise FrozenEmbeddingError("embedding_summary_sequence_count_mismatch")
    if int(summary.get("vhh_sequence_count", -1)) != vhh_count:
        raise FrozenEmbeddingError("embedding_summary_vhh_count_mismatch")

    dimensions = {
        "esm2": int(manifest_rows[0]["esm2_dim"]),
        "vhhbert": int(manifest_rows[0]["vhhbert_dim"]),
        "physchem": int(manifest_rows[0]["physchem_dim"]),
    }
    if any(
        int(row[f"{channel}_dim"]) != dimension
        for row in manifest_rows
        for channel, dimension in dimensions.items()
    ):
        raise FrozenEmbeddingError("embedding_manifest_mixed_dimensions")
    if any(int(config[f"{channel}_dim"]) != value for channel, value in dimensions.items()):
        raise FrozenEmbeddingError("embedding_config_dimension_mismatch")
    if enforce_production_hashes and dimensions != EXPECTED_DIMS:
        raise FrozenEmbeddingError(f"production_embedding_dimensions_mismatch:{dimensions}")

    rows_by_shard: dict[Path, list[dict[str, str]]] = {}
    shard_order: list[Path] = []
    for row in manifest_rows:
        path = Path(row["shard_path"]).resolve()
        if not path.is_file():
            relocated = (
                embedding_manifest_path.resolve().parent / "shards" / path.name
            )
            if relocated.is_file():
                path = relocated
        if path not in rows_by_shard:
            rows_by_shard[path] = []
            shard_order.append(path)
        rows_by_shard[path].append(row)
    expected_shard_hashes = _expected_shard_hashes(summary, enforce_production_hashes)
    if {path.name for path in shard_order} != set(expected_shard_hashes):
        raise FrozenEmbeddingError("embedding_shard_set_mismatch")

    all_hashes: list[str] = []
    all_roles: list[str] = []
    arrays: dict[str, list[np.ndarray]] = {name: [] for name in dimensions}
    shard_receipt: dict[str, Any] = {}
    for shard_path in shard_order:
        if not shard_path.is_file():
            raise FrozenEmbeddingError(f"embedding_shard_missing:{shard_path}")
        shard_snapshot = snapshot_file(shard_path)
        actual_hash = shard_snapshot.sha256
        if actual_hash != expected_shard_hashes[shard_path.name]:
            raise FrozenEmbeddingError(f"embedding_shard_sha256_mismatch:{shard_path.name}")
        rows = rows_by_shard[shard_path]
        if [int(row["shard_index"]) for row in rows] != list(range(len(rows))):
            raise FrozenEmbeddingError(f"embedding_shard_index_mismatch:{shard_path.name}")
        hashes = [row["sequence_sha256"] for row in rows]
        roles = [row["roles"] for row in rows]
        try:
            payload = torch.load(
                io.BytesIO(shard_snapshot.payload), map_location="cpu", weights_only=True
            )
        except Exception as exc:
            raise FrozenEmbeddingError(f"embedding_shard_load_failed:{shard_path.name}") from exc
        if payload.get("schema_version") != "phase2_v3_embedding_shard_v1":
            raise FrozenEmbeddingError(f"embedding_shard_schema_mismatch:{shard_path.name}")
        if list(payload.get("sequence_sha256", [])) != hashes:
            raise FrozenEmbeddingError(f"embedding_shard_sequence_order_mismatch:{shard_path.name}")
        expected_shard_config = sha256_json(
            {"config": dict(config), "sequence_sha256": hashes}
        )
        if payload.get("config_sha256") != expected_shard_config:
            raise FrozenEmbeddingError(f"embedding_shard_config_hash_mismatch:{shard_path.name}")
        availability = payload.get("vhhbert_available")
        if not isinstance(availability, torch.Tensor) or tuple(availability.shape) != (len(rows),):
            raise FrozenEmbeddingError(f"embedding_shard_availability_shape:{shard_path.name}")
        expected_availability = torch.tensor(
            ["vhh" in role.split(";") for role in roles], dtype=torch.bool
        )
        if not torch.equal(availability.cpu().bool(), expected_availability):
            raise FrozenEmbeddingError(f"embedding_shard_availability_mismatch:{shard_path.name}")
        for channel, dimension in dimensions.items():
            value = payload.get(channel)
            if not isinstance(value, torch.Tensor) or tuple(value.shape) != (len(rows), dimension):
                raise FrozenEmbeddingError(f"embedding_shard_tensor_shape:{shard_path.name}:{channel}")
            array = value.detach().cpu().float().numpy()
            if not np.all(np.isfinite(array)):
                raise FrozenEmbeddingError(f"embedding_shard_non_finite:{shard_path.name}:{channel}")
            arrays[channel].append(array)
        all_hashes.extend(hashes)
        all_roles.extend(roles)
        shard_receipt[shard_path.name] = {
            "path": str(shard_path),
            "sha256": actual_hash,
            "row_count": len(rows),
            "payload_config_sha256": expected_shard_config,
        }
    if all_hashes != manifest_hashes:
        raise FrozenEmbeddingError("embedding_shard_manifest_global_order_mismatch")

    identity_payload = {
        "embedding_manifest_sha256": manifest_hash,
        "embedding_summary_sha256": summary_hash,
        "sequence_manifest_sha256": sequence_manifest_hash,
        "config_sha256": config_sha256,
        "shard_sha256": {
            name: payload["sha256"] for name, payload in sorted(shard_receipt.items())
        },
    }

    return EmbeddingBank(
        index_by_sha256={value: index for index, value in enumerate(all_hashes)},
        sequence_sha256=tuple(all_hashes),
        roles=tuple(all_roles),
        esm2=np.concatenate(arrays["esm2"], axis=0),
        vhhbert=np.concatenate(arrays["vhhbert"], axis=0),
        physchem=np.concatenate(arrays["physchem"], axis=0),
        config_sha256=config_sha256,
        provenance={
            "identity_sha256": sha256_json(identity_payload),
            "identity_payload": identity_payload,
            "snapshot_semantics": "sha256_of_single_open_read_used_for_parsing_or_tensor_load",
            "embedding_manifest": {
                "path": str(manifest_snapshot.path),
                "sha256": manifest_hash,
            },
            "embedding_summary": {
                "path": str(summary_snapshot.path),
                "sha256": summary_hash,
            },
            "sequence_manifest": {
                "path": str(sequence_snapshot.path),
                "sha256": sequence_manifest_hash,
            },
            "config_sha256": config_sha256,
            "dimensions": dimensions,
            "sequence_count": len(all_hashes),
            "vhh_count": vhh_count,
            "shards": shard_receipt,
        },
    )


def fit_dual_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> base.RidgeFit:
    if len(x) != len(y) or not len(y):
        raise FrozenEmbeddingError("dual_ridge_row_mismatch_or_empty")
    if x.ndim != 2 or x.shape[1] == 0 or alpha <= 0.0:
        raise FrozenEmbeddingError("dual_ridge_invalid_shape_or_alpha")
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x - center) / scale
    intercept = float(np.mean(y))
    centered_target = y - intercept
    dual = np.linalg.solve(
        z @ z.T + float(alpha) * np.eye(len(z), dtype=np.float64),
        centered_target,
    )
    coefficient = z.T @ dual
    return base.RidgeFit(intercept, coefficient, center, scale)


def train_embedding_model(
    model_name: str,
    bank: EmbeddingBank,
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    *,
    alphas: Sequence[float],
    ensemble_seeds: Sequence[int],
) -> dict[str, Any]:
    train_hashes = [str(row["sequence_sha256"]) for row in train_rows]
    development_hashes = [str(row["sequence_sha256"]) for row in development_rows]
    x_train = bank.matrix(train_hashes, model_name)
    x_development = bank.matrix(development_hashes, model_name)
    y_train = np.asarray([float(row[base.PRIMARY_TARGET]) for row in train_rows])
    y_development = np.asarray([float(row[base.PRIMARY_TARGET]) for row in development_rows])
    parent_groups = [str(row["parent_framework_cluster"]) for row in development_rows]

    candidates: list[tuple[tuple[float, ...], float, base.RidgeFit, dict[str, float]]] = []
    for alpha in alphas:
        fitted = fit_dual_ridge(x_train, y_train, float(alpha))
        metric = base.regression_metrics(
            y_development, base.predict_ridge(x_development, fitted)
        )
        candidates.append((base.selection_key(metric, float(alpha)), float(alpha), fitted, metric))
    _key, selected_alpha, direct_fit, direct_metric = max(candidates, key=lambda item: item[0])

    seed_predictions: list[np.ndarray] = []
    seed_fits: list[dict[str, Any]] = []
    for seed in ensemble_seeds:
        indices = base.group_bootstrap_indices(train_rows, int(seed))
        fitted = fit_dual_ridge(x_train[indices], y_train[indices], selected_alpha)
        seed_predictions.append(base.predict_ridge(x_development, fitted))
        seed_fits.append(
            {
                "seed": int(seed),
                "sampled_train_row_count": int(len(indices)),
                "sampled_train_candidate_ids_sha256": base.sha256_strings(
                    str(train_rows[index]["candidate_id"]) for index in indices
                ),
                "fit": fitted.to_json(),
            }
        )
    prediction_matrix = np.asarray(seed_predictions, dtype=np.float64)
    ensemble_prediction = prediction_matrix.mean(axis=0)
    ensemble_uncertainty = prediction_matrix.std(axis=0)
    return {
        "model_name": model_name,
        "channels": MODEL_CHANNELS[model_name],
        "feature_dim": int(x_train.shape[1]),
        "solver": "standardized_dual_ridge_n_by_n",
        "selected_alpha": selected_alpha,
        "direct_fit": direct_fit,
        "direct_metrics": direct_metric,
        "ensemble_prediction": ensemble_prediction,
        "ensemble_uncertainty": ensemble_uncertainty,
        "ensemble_metrics": base.regression_metrics(y_development, ensemble_prediction),
        "parent_macro_ensemble_metrics": base.parent_macro_regression_metrics(
            y_development, ensemble_prediction, parent_groups
        ),
        "selective_risk": base.selective_risk(
            y_development, ensemble_prediction, ensemble_uncertainty, parent_groups
        ),
        "ensemble_metric_distribution": base.metric_distribution(
            y_development, prediction_matrix
        ),
        "seed_fits": seed_fits,
        "alpha_development_metrics": {
            str(alpha): metric for _selection, alpha, _fit, metric in candidates
        },
    }


def cdr_length_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    values = []
    for row in rows:
        sequence_length = len(base.validate_sequence(str(row["sequence"]), "sequence"))
        cdr_lengths = [
            len(base.validate_sequence(str(row[field]), field))
            for field in ("cdr1", "cdr2", "cdr3")
        ]
        values.append(
            [
                sequence_length / 160.0,
                cdr_lengths[0] / 20.0,
                cdr_lengths[1] / 20.0,
                cdr_lengths[2] / 30.0,
                sum(cdr_lengths) / 60.0,
            ]
        )
    return np.asarray(values, dtype=np.float64)


def train_cdr_length_only_baseline(
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    *,
    alphas: Sequence[float],
    ensemble_seeds: Sequence[int],
) -> dict[str, Any]:
    x_train = cdr_length_matrix(train_rows)
    x_development = cdr_length_matrix(development_rows)
    y_train = np.asarray([float(row[base.PRIMARY_TARGET]) for row in train_rows])
    y_development = np.asarray(
        [float(row[base.PRIMARY_TARGET]) for row in development_rows]
    )
    parent_groups = [str(row["parent_framework_cluster"]) for row in development_rows]
    candidates = []
    for alpha in alphas:
        fitted = base.fit_ridge(x_train, y_train, float(alpha))
        metric = base.regression_metrics(
            y_development, base.predict_ridge(x_development, fitted)
        )
        candidates.append((base.selection_key(metric, float(alpha)), float(alpha), fitted, metric))
    _selection, selected_alpha, direct_fit, direct_metric = max(
        candidates, key=lambda item: item[0]
    )
    seed_predictions = []
    seed_fits = []
    for seed in ensemble_seeds:
        indices = base.group_bootstrap_indices(train_rows, int(seed))
        fitted = base.fit_ridge(x_train[indices], y_train[indices], selected_alpha)
        seed_predictions.append(base.predict_ridge(x_development, fitted))
        seed_fits.append({"seed": int(seed), "fit": fitted.to_json()})
    prediction_matrix = np.asarray(seed_predictions)
    ensemble_prediction = prediction_matrix.mean(axis=0)
    ensemble_uncertainty = prediction_matrix.std(axis=0)
    return {
        "model_name": "cdr_length_only",
        "feature_names": (
            "sequence_length",
            "cdr1_length",
            "cdr2_length",
            "cdr3_length",
            "total_cdr_length",
        ),
        "selected_alpha": selected_alpha,
        "direct_fit": direct_fit,
        "direct_metrics": direct_metric,
        "ensemble_prediction": ensemble_prediction,
        "ensemble_uncertainty": ensemble_uncertainty,
        "ensemble_metrics": base.regression_metrics(
            y_development, ensemble_prediction
        ),
        "parent_macro_ensemble_metrics": base.parent_macro_regression_metrics(
            y_development, ensemble_prediction, parent_groups
        ),
        "selective_risk": base.selective_risk(
            y_development,
            ensemble_prediction,
            ensemble_uncertainty,
            parent_groups,
        ),
        "ensemble_metric_distribution": base.metric_distribution(
            y_development, prediction_matrix
        ),
        "seed_fits": seed_fits,
        "alpha_development_metrics": {
            str(alpha): metric for _key, alpha, _fit, metric in candidates
        },
    }


def train_models(
    bank: EmbeddingBank,
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    *,
    alphas: Sequence[float],
    ensemble_seeds: Sequence[int],
) -> dict[str, Any]:
    if not alphas or any(float(value) <= 0.0 for value in alphas):
        raise FrozenEmbeddingError("alphas_must_be_positive")
    if len(set(int(value) for value in ensemble_seeds)) < 3:
        raise FrozenEmbeddingError("at_least_three_unique_ensemble_seeds_required")
    embedding_models = {
        name: train_embedding_model(
            name,
            bank,
            train_rows,
            development_rows,
            alphas=alphas,
            ensemble_seeds=ensemble_seeds,
        )
        for name in EMBEDDING_MODELS
    }
    shortcut_models = {
        name: base.train_one_model(
            name,
            train_rows,
            development_rows,
            base.PRIMARY_TARGET,
            alphas,
            ensemble_seeds,
            base.FROZEN_FEATURE_WIDTH,
        )
        for name in base.REQUIRED_BASELINES
    }
    shortcut_models["cdr_length_only"] = train_cdr_length_only_baseline(
        train_rows,
        development_rows,
        alphas=alphas,
        ensemble_seeds=ensemble_seeds,
    )
    shortcut_names = base.REQUIRED_BASELINES + LOCAL_SHORTCUT_MODELS
    strongest_shortcut = max(
        shortcut_names,
        key=lambda name: (
            shortcut_models[name]["ensemble_metrics"]["spearman"],
            shortcut_models[name]["ensemble_metrics"]["ndcg"],
            shortcut_models[name]["ensemble_metrics"][
                "top_quartile_recall_at_25pct_budget"
            ],
            -shortcut_models[name]["ensemble_metrics"]["mae"],
            name,
        ),
    )
    selected_model = max(
        EMBEDDING_MODELS,
        key=lambda name: (
            embedding_models[name]["ensemble_metrics"]["spearman"],
            embedding_models[name]["ensemble_metrics"]["ndcg"],
            embedding_models[name]["ensemble_metrics"][
                "top_quartile_recall_at_25pct_budget"
            ],
            -embedding_models[name]["ensemble_metrics"]["mae"],
            name,
        ),
    )
    performance_gates = base.evaluate_open_performance_gates(
        embedding_models[selected_model], shortcut_models[strongest_shortcut]
    )
    uncertainty_gate_pass = embedding_models[selected_model]["selective_risk"][
        "gate_pass"
    ]
    return {
        "embedding_models": embedding_models,
        "shortcut_models": shortcut_models,
        "strongest_shortcut": strongest_shortcut,
        "selected_model": selected_model,
        "performance_gates": performance_gates,
        "uncertainty_gate_pass": uncertainty_gate_pass,
        "open_gates_pass": performance_gates["all_passed"] and uncertainty_gate_pass,
    }


def serialized_embedding_model(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "channels": list(result["channels"]),
        "feature_dim": result["feature_dim"],
        "solver": result["solver"],
        "selected_alpha": result["selected_alpha"],
        "direct_fit": result["direct_fit"].to_json(),
        "bootstrap_ensemble_fits": result["seed_fits"],
        "fit_split": base.TRAIN_SPLIT,
        "fit_labels": base.PRIMARY_TARGET,
        "development_rows_used_as_fit_rows": 0,
        "prospective_test_rows_used_as_fit_rows": 0,
    }


def load_model_artifact(
    path: Path, *, expected_config_sha256: str | None = None
) -> dict[str, Any]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenEmbeddingError("invalid_frozen_embedding_artifact") from exc
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise FrozenEmbeddingError("frozen_embedding_artifact_schema_mismatch")
    if artifact.get("status") != "FROZEN_MODEL_TEST_LABELS_NOT_READ":
        raise FrozenEmbeddingError("frozen_embedding_artifact_status_mismatch")
    if artifact.get("prospective_test_labels_read") is not False:
        raise FrozenEmbeddingError("frozen_embedding_artifact_test_label_boundary_invalid")
    if expected_config_sha256 is not None and artifact.get("config_sha256") != expected_config_sha256:
        raise FrozenEmbeddingError("frozen_embedding_artifact_config_hash_mismatch")
    if set(artifact.get("models", {})) != set(EMBEDDING_MODELS):
        raise FrozenEmbeddingError("frozen_embedding_artifact_model_set_mismatch")
    if artifact.get("selected_model") not in EMBEDDING_MODELS:
        raise FrozenEmbeddingError("frozen_embedding_artifact_selected_model_invalid")
    return artifact


def predict_artifact_model(
    artifact: Mapping[str, Any],
    model_name: str,
    bank: EmbeddingBank,
    sequence_hashes: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    if model_name not in EMBEDDING_MODELS:
        raise FrozenEmbeddingError(f"unknown_artifact_model:{model_name}")
    if artifact.get("embedding_config_sha256") != bank.config_sha256:
        raise FrozenEmbeddingError("artifact_embedding_config_hash_mismatch")
    if artifact.get("embedding_bank_identity_sha256") != bank.provenance.get(
        "identity_sha256"
    ):
        raise FrozenEmbeddingError("artifact_embedding_bank_identity_mismatch")
    model = artifact["models"][model_name]
    channels = tuple(str(value) for value in model.get("channels", []))
    if channels != MODEL_CHANNELS[model_name]:
        raise FrozenEmbeddingError(f"artifact_model_channel_mismatch:{model_name}")
    x = bank.matrix(sequence_hashes, model_name)
    if int(model.get("feature_dim", -1)) != x.shape[1]:
        raise FrozenEmbeddingError(f"artifact_model_feature_dim_mismatch:{model_name}")
    fits = model.get("bootstrap_ensemble_fits")
    if not isinstance(fits, list) or len(fits) < 3:
        raise FrozenEmbeddingError(f"artifact_model_ensemble_too_small:{model_name}")
    predictions: list[np.ndarray] = []
    seeds: set[int] = set()
    for payload in fits:
        seed = int(payload["seed"])
        if seed in seeds:
            raise FrozenEmbeddingError(f"artifact_duplicate_seed:{model_name}:{seed}")
        seeds.add(seed)
        fitted = base.RidgeFit.from_json(payload["fit"])
        if len(fitted.coefficient) != x.shape[1]:
            raise FrozenEmbeddingError(f"artifact_fit_width_mismatch:{model_name}")
        predictions.append(base.predict_ridge(x, fitted))
    matrix = np.asarray(predictions, dtype=np.float64)
    return matrix.mean(axis=0), matrix.std(axis=0)


def verify_development_roundtrip(
    artifact_path: Path,
    config_path: Path,
    bank: EmbeddingBank,
    development_rows: list[dict[str, Any]],
    trained: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = load_model_artifact(
        artifact_path, expected_config_sha256=base.sha256_file(config_path)
    )
    sequence_hashes = [str(row["sequence_sha256"]) for row in development_rows]
    per_model: dict[str, Any] = {}
    for name in EMBEDDING_MODELS:
        prediction, uncertainty = predict_artifact_model(
            artifact, name, bank, sequence_hashes
        )
        expected_prediction = trained["embedding_models"][name]["ensemble_prediction"]
        expected_uncertainty = trained["embedding_models"][name]["ensemble_uncertainty"]
        prediction_error = float(np.max(np.abs(prediction - expected_prediction)))
        uncertainty_error = float(np.max(np.abs(uncertainty - expected_uncertainty)))
        if prediction_error > 1e-12 or uncertainty_error > 1e-12:
            raise FrozenEmbeddingError(f"artifact_roundtrip_mismatch:{name}")
        per_model[name] = {
            "maximum_absolute_prediction_error": prediction_error,
            "maximum_absolute_uncertainty_error": uncertainty_error,
            "row_count": len(development_rows),
        }
    return {
        "status": "PASS_FROZEN_EMBEDDING_ARTIFACT_ROUNDTRIP",
        "per_model": per_model,
    }


def model_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "channels": list(result["channels"]),
        "feature_dim": result["feature_dim"],
        "solver": result["solver"],
        "selected_alpha": result["selected_alpha"],
        "direct_development_metrics": result["direct_metrics"],
        "ensemble_development_metrics": result["ensemble_metrics"],
        "parent_macro_ensemble_development_metrics": result[
            "parent_macro_ensemble_metrics"
        ],
        "selective_risk": result["selective_risk"],
        "fixed_seed_metric_range": result["ensemble_metric_distribution"],
        "alpha_development_metrics": result["alpha_development_metrics"],
    }


def shortcut_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    output = {
        "ensemble_development_metrics": result["ensemble_metrics"],
        "parent_macro_ensemble_development_metrics": result[
            "parent_macro_ensemble_metrics"
        ],
        "selected_alpha": result["selected_alpha"],
    }
    if "feature_names" in result:
        output["feature_names"] = list(result["feature_names"])
        output["sequence_identity_features_used"] = False
    return output


def validate_output_directory(out_dir: Path) -> None:
    if out_dir.exists() and not out_dir.is_dir():
        raise FrozenEmbeddingError("output_path_is_not_directory")
    if out_dir.exists():
        unexpected = sorted(
            path.name for path in out_dir.iterdir() if path.name not in OUTPUT_FILENAMES
        )
        if unexpected:
            raise FrozenEmbeddingError(
                "unexpected_existing_output_files:" + ",".join(unexpected)
            )


@contextmanager
def publication_lock(out_dir: Path) -> Iterable[None]:
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir.parent / f".{out_dir.name}.frozen-embedding.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise FrozenEmbeddingError("frozen_embedding_publication_lock_exists") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def publish_staged_outputs(
    staging_dir: Path, out_dir: Path, *, expected_stale_receipt: bool
) -> None:
    validate_output_directory(out_dir)
    for name in OUTPUT_FILENAMES:
        if not (staging_dir / name).is_file():
            raise FrozenEmbeddingError(f"staged_output_missing:{name}")
    receipt_name = OUTPUT_FILENAMES[-1]
    receipt_payload = json.loads((staging_dir / receipt_name).read_text(encoding="utf-8"))
    expected_output_hashes = receipt_payload.get("outputs", {})
    expected_paths = {
        str((out_dir / name).resolve()) for name in OUTPUT_FILENAMES[:-1]
    }
    if set(expected_output_hashes) != expected_paths:
        raise FrozenEmbeddingError("staged_receipt_output_set_mismatch")
    out_dir.mkdir(parents=True, exist_ok=True)
    final_receipt = out_dir / receipt_name
    if final_receipt.exists() != expected_stale_receipt:
        raise FrozenEmbeddingError("stale_receipt_state_changed")
    final_receipt.unlink(missing_ok=True)
    for name in OUTPUT_FILENAMES[:-1]:
        final_path = out_dir / name
        os.replace(staging_dir / name, final_path)
        if base.sha256_file(final_path) != expected_output_hashes[str(final_path.resolve())]:
            raise FrozenEmbeddingError(f"published_output_hash_mismatch:{name}")
    os.replace(staging_dir / receipt_name, final_receipt)
    directory_descriptor = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def validate_teacher_audit_snapshot(
    audit_snapshot: FileSnapshot,
    teacher_snapshot: FileSnapshot,
    split_snapshot: FileSnapshot,
) -> dict[str, Any]:
    try:
        audit = json.loads(audit_snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenEmbeddingError("invalid_teacher_audit_snapshot") from exc
    if audit.get("status") != "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE":
        raise FrozenEmbeddingError("teacher_audit_status_not_pass")
    if audit.get("release") != "open_train_and_open_development_only":
        raise FrozenEmbeddingError("teacher_audit_release_not_open_only")
    if audit.get("output", {}).get("sha256") != teacher_snapshot.sha256:
        raise FrozenEmbeddingError("teacher_audit_output_hash_mismatch")
    if audit.get("inputs", {}).get("split_manifest_sha256") != split_snapshot.sha256:
        raise FrozenEmbeddingError("teacher_audit_split_hash_mismatch")
    boundary = audit.get("sealed_data_boundary", {})
    if boundary.get("raw_job_results_opened") != 0:
        raise FrozenEmbeddingError("teacher_audit_reports_sealed_raw_results_opened")
    if boundary.get("sealed_metrics_used_for_teacher_or_ranking") is not False:
        raise FrozenEmbeddingError("teacher_audit_reports_sealed_metrics_used")
    return audit


def validate_release_receipt_snapshot(
    receipt_snapshot: FileSnapshot,
    teacher_snapshot: FileSnapshot,
    teacher_audit_snapshot: FileSnapshot,
    teacher_audit: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        receipt = json.loads(receipt_snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenEmbeddingError("invalid_open_teacher_release_receipt") from exc
    if receipt.get("status") != "PASS_OPEN258_TEACHER_READY_TEST32_SEALED":
        raise FrozenEmbeddingError("open_teacher_release_receipt_status_not_pass")
    if int(receipt.get("row_count", -1)) != 258:
        raise FrozenEmbeddingError("open_teacher_release_receipt_row_count_mismatch")
    if receipt.get("teacher_sha256") != teacher_snapshot.sha256:
        raise FrozenEmbeddingError("open_teacher_release_receipt_teacher_hash_mismatch")
    if receipt.get("teacher_audit_sha256") != teacher_audit_snapshot.sha256:
        raise FrozenEmbeddingError("open_teacher_release_receipt_audit_hash_mismatch")
    audit_boundary = teacher_audit.get("sealed_data_boundary", {})
    receipt_raw_opened = receipt.get(
        "sealed_test_raw_job_results_opened",
        receipt.get("sealed_data_boundary", {}).get("raw_job_results_opened"),
    )
    receipt_sealed_metrics = receipt.get(
        "sealed_metrics_used_for_teacher_or_ranking",
        receipt.get("sealed_data_boundary", {}).get(
            "sealed_metrics_used_for_teacher_or_ranking"
        ),
    )
    if receipt_raw_opened != 0 or audit_boundary.get("raw_job_results_opened") != 0:
        raise FrozenEmbeddingError(
            "open_teacher_release_receipt_sealed_boundary_mismatch:raw_job_results_opened"
        )
    if (
        receipt_sealed_metrics is not False
        or audit_boundary.get("sealed_metrics_used_for_teacher_or_ranking") is not False
    ):
        raise FrozenEmbeddingError(
            "open_teacher_release_receipt_sealed_boundary_mismatch:sealed_metrics"
        )
    audit_closure = teacher_audit.get("inputs", {}).get("raw_aggregate_closure")
    receipt_closure = receipt.get("raw_aggregate_closure")
    receipt_closure_sha256 = receipt.get("raw_aggregate_closure_sha256")
    closure_matches = receipt_closure == audit_closure or (
        isinstance(audit_closure, Mapping)
        and receipt_closure_sha256 == audit_closure.get("closure_sha256")
    )
    if not isinstance(audit_closure, Mapping) or not closure_matches:
        raise FrozenEmbeddingError("open_teacher_release_receipt_raw_closure_mismatch")
    if audit_closure.get("status") != "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES":
        raise FrozenEmbeddingError("open_teacher_release_receipt_raw_closure_not_pass")
    if int(audit_closure.get("job_count", -1)) != 1548:
        raise FrozenEmbeddingError("open_teacher_release_receipt_job_count_mismatch")
    closure_sha256 = str(audit_closure.get("closure_sha256", ""))
    if len(closure_sha256) != 64:
        raise FrozenEmbeddingError("open_teacher_release_receipt_closure_hash_invalid")
    return receipt


def run_pipeline(
    teacher_path: Path,
    teacher_audit_path: Path,
    split_manifest_path: Path,
    embedding_manifest_path: Path,
    embedding_summary_path: Path,
    sequence_manifest_path: Path,
    out_dir: Path,
    *,
    release_receipt_path: Path | None = None,
    alphas: Sequence[float] = base.DEFAULT_ALPHAS,
    ensemble_seeds: Sequence[int] = base.DEFAULT_ENSEMBLE_SEEDS,
    enforce_production_hashes: bool = True,
    test_only_allow_missing_release_receipt: bool = False,
) -> dict[str, Any]:
    teacher_snapshot = snapshot_file(teacher_path)
    teacher_audit_snapshot = snapshot_file(teacher_audit_path)
    split_snapshot = snapshot_file(split_manifest_path)
    embedding_manifest_snapshot = snapshot_file(embedding_manifest_path)
    embedding_summary_snapshot = snapshot_file(embedding_summary_path)
    sequence_manifest_snapshot = snapshot_file(sequence_manifest_path)
    implementation_snapshot = snapshot_file(Path(__file__))
    base_implementation_snapshot = snapshot_file(Path(base.__file__))
    release_receipt_snapshot = (
        snapshot_file(release_receipt_path) if release_receipt_path is not None else None
    )
    if release_receipt_snapshot is None and not test_only_allow_missing_release_receipt:
        raise FrozenEmbeddingError("open_teacher_release_receipt_required")
    if (
        enforce_production_hashes
        and split_snapshot.sha256 != base.EXPECTED_SPLIT_MANIFEST_SHA256
    ):
        raise FrozenEmbeddingError("production_split_manifest_sha256_mismatch")
    teacher_audit = validate_teacher_audit_snapshot(
        teacher_audit_snapshot, teacher_snapshot, split_snapshot
    )
    release_receipt = (
        validate_release_receipt_snapshot(
            release_receipt_snapshot,
            teacher_snapshot,
            teacher_audit_snapshot,
            teacher_audit,
        )
        if release_receipt_snapshot is not None
        else None
    )
    split_rows = read_tsv_snapshot(split_snapshot)
    split_by_id = base.validate_split_manifest(split_rows)
    train_rows, development_rows = base.validate_teacher_rows(
        read_tsv_snapshot(teacher_snapshot), split_by_id
    )
    test_rows = sorted(
        (row for row in split_rows if row["model_split"] == base.SEALED_SPLIT),
        key=lambda row: row["candidate_id"],
    )
    if len(test_rows) != base.EXPECTED_SPLIT_COUNTS[base.SEALED_SPLIT]:
        raise FrozenEmbeddingError("prospective_test_manifest_count_mismatch")
    bank = load_embedding_bank(
        embedding_manifest_path,
        embedding_summary_path,
        sequence_manifest_path,
        enforce_production_hashes=enforce_production_hashes,
        embedding_manifest_snapshot=embedding_manifest_snapshot,
        embedding_summary_snapshot=embedding_summary_snapshot,
        sequence_manifest_snapshot=sequence_manifest_snapshot,
    )
    for row in split_rows:
        sequence = base.validate_sequence(row["sequence"], "split_sequence")
        sequence_hash = str(row["sequence_sha256"]).lower()
        if base.sequence_sha256(sequence) != sequence_hash:
            raise FrozenEmbeddingError(f"split_sequence_sha256_mismatch:{row['candidate_id']}")
        if sequence_hash not in bank.index_by_sha256:
            raise FrozenEmbeddingError(f"split_embedding_missing:{row['candidate_id']}")
        bank_index = bank.index_by_sha256[sequence_hash]
        if "vhh" not in bank.roles[bank_index].split(";"):
            raise FrozenEmbeddingError(f"split_embedding_not_vhh:{row['candidate_id']}")

    trained = train_models(
        bank,
        train_rows,
        development_rows,
        alphas=alphas,
        ensemble_seeds=ensemble_seeds,
    )
    out_dir = out_dir.resolve()
    final_paths = {name: out_dir / name for name in OUTPUT_FILENAMES}
    with publication_lock(out_dir):
        validate_output_directory(out_dir)
        stale_receipt = final_paths[OUTPUT_FILENAMES[-1]].exists()
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".{out_dir.name}.stage.", dir=out_dir.parent)
        )
        try:
            stage_paths = {name: staging_dir / name for name in OUTPUT_FILENAMES}
            train_ids = [str(row["candidate_id"]) for row in train_rows]
            development_ids = [str(row["candidate_id"]) for row in development_rows]
            test_ids = [str(row["candidate_id"]) for row in test_rows]
            config = {
                "schema_version": SCHEMA_VERSION,
                "status": "FROZEN_BEFORE_PROSPECTIVE_TEST_LABEL_UNSEAL",
                "primary_target": base.PRIMARY_TARGET,
                "fit_split": base.TRAIN_SPLIT,
                "selection_split": base.DEVELOPMENT_SPLIT,
                "prediction_only_split": base.SEALED_SPLIT,
                "fit_rows": len(train_rows),
                "selection_rows": len(development_rows),
                "prediction_only_rows": len(test_rows),
                "prospective_test_labels_read": False,
                "prospective_test_label_files_opened": 0,
                "models": list(EMBEDDING_MODELS),
                "shortcut_baselines": list(
                    base.REQUIRED_BASELINES + LOCAL_SHORTCUT_MODELS
                ),
                "model_channels": {
                    name: list(channels) for name, channels in MODEL_CHANNELS.items()
                },
                "solver": "standardized_dual_ridge_n_by_n",
                "alphas": [float(value) for value in alphas],
                "parent_group_bootstrap_seeds": [int(value) for value in ensemble_seeds],
                "fixed_seed_range_is_confidence_interval": False,
                "gate_contract": {
                    "minimum_relative_spearman_delta": base.MINIMUM_OPEN_DELTA,
                    "minimum_absolute_spearman": base.MINIMUM_ABSOLUTE_SPEARMAN,
                    "minimum_recall_at_25pct": base.MINIMUM_TOP_QUARTILE_RECALL,
                    "minimum_parent_macro_spearman": base.MINIMUM_PARENT_MACRO_SPEARMAN,
                    "minimum_parent_macro_recall_at_25pct": base.MINIMUM_PARENT_MACRO_TOP_QUARTILE_RECALL,
                    "parent_aware_uncertainty": True,
                },
                "train_candidate_ids_sha256": base.sha256_strings(train_ids),
                "development_candidate_ids_sha256": base.sha256_strings(development_ids),
                "prospective_test_candidate_ids_sha256": base.sha256_strings(test_ids),
                "embedding_provenance": bank.provenance,
                "inputs": {
                    "teacher": {
                        "path": str(teacher_snapshot.path),
                        "sha256": teacher_snapshot.sha256,
                    },
                    "teacher_audit": {
                        "path": str(teacher_audit_snapshot.path),
                        "sha256": teacher_audit_snapshot.sha256,
                    },
                    "split_manifest": {
                        "path": str(split_snapshot.path),
                        "sha256": split_snapshot.sha256,
                    },
                    "open_teacher_release_receipt": (
                        {
                            "path": str(release_receipt_snapshot.path),
                            "sha256": release_receipt_snapshot.sha256,
                            "status": release_receipt["status"],
                        }
                        if release_receipt_snapshot is not None
                        else {
                            "test_only_bypass": True,
                            "production_cli_available": False,
                        }
                    ),
                },
                "runtime": {
                    "python": sys.version,
                    "numpy": np.__version__,
                    "torch": torch.__version__,
                    "platform": platform.platform(),
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(stage_paths[OUTPUT_FILENAMES[0]], config)
            artifact = {
                "schema_version": SCHEMA_VERSION,
                "status": "FROZEN_MODEL_TEST_LABELS_NOT_READ",
                "config_sha256": base.sha256_file(stage_paths[OUTPUT_FILENAMES[0]]),
                "embedding_config_sha256": bank.config_sha256,
                "embedding_bank_identity_sha256": bank.provenance["identity_sha256"],
                "selected_model": trained["selected_model"],
                "strongest_shortcut": trained["strongest_shortcut"],
                "models": {
                    name: serialized_embedding_model(trained["embedding_models"][name])
                    for name in EMBEDDING_MODELS
                },
                "fit_rows": len(train_rows),
                "development_rows_used_for_selection_only": len(development_rows),
                "prospective_test_rows_used_as_fit_rows": 0,
                "prospective_test_labels_read": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(stage_paths[OUTPUT_FILENAMES[1]], artifact)
            roundtrip = verify_development_roundtrip(
                stage_paths[OUTPUT_FILENAMES[1]],
                stage_paths[OUTPUT_FILENAMES[0]],
                bank,
                development_rows,
                trained,
            )
            reloaded = load_model_artifact(
                stage_paths[OUTPUT_FILENAMES[1]],
                expected_config_sha256=base.sha256_file(stage_paths[OUTPUT_FILENAMES[0]]),
            )
            development_hashes = [str(row["sequence_sha256"]) for row in development_rows]
            test_hashes = [str(row["sequence_sha256"]) for row in test_rows]
            development_predictions = {
                name: predict_artifact_model(reloaded, name, bank, development_hashes)
                for name in EMBEDDING_MODELS
            }
            test_predictions = {
                name: predict_artifact_model(reloaded, name, bank, test_hashes)
                for name in EMBEDDING_MODELS
            }
            development_output: list[dict[str, Any]] = []
            for index, row in enumerate(development_rows):
                output: dict[str, Any] = {
                    "candidate_id": row["candidate_id"],
                    "sequence_sha256": row["sequence_sha256"],
                    "model_split": row["model_split"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                    "target_R_dual_min": round(float(row[base.PRIMARY_TARGET]), 9),
                }
                for name in EMBEDDING_MODELS:
                    prediction, uncertainty = development_predictions[name]
                    output[f"prediction_{name}"] = round(float(prediction[index]), 9)
                    output[f"uncertainty_{name}"] = round(float(uncertainty[index]), 9)
                selected = trained["selected_model"]
                output["selected_model"] = selected
                output["selected_prediction"] = output[f"prediction_{selected}"]
                output["selected_uncertainty"] = output[f"uncertainty_{selected}"]
                development_output.append(output)
            write_tsv(stage_paths[OUTPUT_FILENAMES[2]], development_output)

            test_output: list[dict[str, Any]] = []
            for index, row in enumerate(test_rows):
                output = {
                    "candidate_id": row["candidate_id"],
                    "sequence_sha256": row["sequence_sha256"],
                    "model_split": row["model_split"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                }
                for name in EMBEDDING_MODELS:
                    prediction, uncertainty = test_predictions[name]
                    output[f"prediction_{name}"] = round(float(prediction[index]), 9)
                    output[f"uncertainty_{name}"] = round(float(uncertainty[index]), 9)
                selected = trained["selected_model"]
                output["selected_model"] = selected
                output["selected_prediction"] = output[f"prediction_{selected}"]
                output["selected_uncertainty"] = output[f"uncertainty_{selected}"]
                test_output.append(output)
            write_tsv(stage_paths[OUTPUT_FILENAMES[3]], test_output)

            summary = {
                "schema_version": SCHEMA_VERSION,
                "status": (
                    "PASS_OPEN_GATES_FROZEN_TEST_PREDICTIONS_UNEVALUATED"
                    if trained["open_gates_pass"]
                    else "FAIL_OPEN_GATES_FROZEN_TEST_PREDICTIONS_UNEVALUATED"
                ),
                "teacher_release_status": teacher_audit["status"],
                "open_teacher_release_receipt_status": (
                    release_receipt["status"] if release_receipt is not None else "TEST_ONLY_BYPASS"
                ),
                "selected_model": trained["selected_model"],
                "strongest_shortcut": trained["strongest_shortcut"],
                "open_performance_gates": trained["performance_gates"],
                "uncertainty_gate_pass": trained["uncertainty_gate_pass"],
                "open_gates_pass": trained["open_gates_pass"],
                "embedding_models": {
                    name: model_summary(result)
                    for name, result in trained["embedding_models"].items()
                },
                "shortcut_baselines": {
                    name: shortcut_summary(result)
                    for name, result in trained["shortcut_models"].items()
                },
                "serialized_artifact_roundtrip": roundtrip,
                "prospective_test": {
                    "rows": len(test_rows),
                    "predictions_frozen": True,
                    "labels_read": False,
                    "label_files_opened": 0,
                    "used_for_training_or_selection": False,
                    "prediction_path": str(final_paths[OUTPUT_FILENAMES[3]]),
                    "prediction_sha256": base.sha256_file(stage_paths[OUTPUT_FILENAMES[3]]),
                },
                "deployment_eligible": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(stage_paths[OUTPUT_FILENAMES[4]], summary)

            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE",
                "prospective_test_labels_read": False,
                "publication": {
                    "policy": "stage_then_atomic_replace_receipt_last",
                    "stale_receipt_removed_before_replacement": stale_receipt,
                    "receipt_published_last": True,
                },
                "inputs": {
                    str(teacher_snapshot.path): teacher_snapshot.sha256,
                    str(teacher_audit_snapshot.path): teacher_audit_snapshot.sha256,
                    str(split_snapshot.path): split_snapshot.sha256,
                    str(embedding_manifest_snapshot.path): embedding_manifest_snapshot.sha256,
                    str(embedding_summary_snapshot.path): embedding_summary_snapshot.sha256,
                    str(sequence_manifest_snapshot.path): sequence_manifest_snapshot.sha256,
                    str(implementation_snapshot.path): implementation_snapshot.sha256,
                    str(base_implementation_snapshot.path): base_implementation_snapshot.sha256,
                    **(
                        {str(release_receipt_snapshot.path): release_receipt_snapshot.sha256}
                        if release_receipt_snapshot is not None
                        else {}
                    ),
                    **{
                        payload["path"]: payload["sha256"]
                        for payload in bank.provenance["shards"].values()
                    },
                },
                "outputs": {
                    str(final_paths[name]): base.sha256_file(stage_paths[name])
                    for name in OUTPUT_FILENAMES[:-1]
                },
                "embedding_config_sha256": bank.config_sha256,
                "serialized_artifact_roundtrip_status": roundtrip["status"],
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(stage_paths[OUTPUT_FILENAMES[5]], receipt)
            publish_staged_outputs(
                staging_dir, out_dir, expected_stale_receipt=stale_receipt
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    return {
        "status": summary["status"],
        "selected_model": trained["selected_model"],
        "strongest_shortcut": trained["strongest_shortcut"],
        "summary": str(final_paths[OUTPUT_FILENAMES[4]]),
        "receipt": str(final_paths[OUTPUT_FILENAMES[5]]),
        "prospective_test_predictions": str(final_paths[OUTPUT_FILENAMES[3]]),
        "prospective_test_labels_read": False,
    }


def parse_numbers(value: str, cast: type) -> tuple[Any, ...]:
    try:
        output = tuple(cast(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid_number_list:{value}") from exc
    if not output:
        raise argparse.ArgumentTypeError("empty_number_list")
    return output


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    embedding_root = root / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-audit", type=Path)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument(
        "--embedding-manifest",
        type=Path,
        default=embedding_root / "meanpool_embeddings/embedding_manifest_v3.csv",
    )
    parser.add_argument(
        "--embedding-summary",
        type=Path,
        default=embedding_root / "meanpool_embeddings/embedding_summary_v3.json",
    )
    parser.add_argument(
        "--sequence-manifest",
        type=Path,
        default=embedding_root / "sequence_manifest_v3.csv",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--alphas", default=",".join(str(value) for value in base.DEFAULT_ALPHAS)
    )
    parser.add_argument(
        "--ensemble-seeds",
        default=",".join(str(value) for value in base.DEFAULT_ENSEMBLE_SEEDS),
    )
    args = parser.parse_args(argv)
    teacher_audit = args.teacher_audit or args.teacher.with_suffix(
        args.teacher.suffix + ".audit.json"
    )
    result = run_pipeline(
        args.teacher,
        teacher_audit,
        args.split_manifest,
        args.embedding_manifest,
        args.embedding_summary,
        args.sequence_manifest,
        args.out_dir,
        release_receipt_path=args.release_receipt,
        alphas=parse_numbers(args.alphas, float),
        ensemble_seeds=parse_numbers(args.ensemble_seeds, int),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
