#!/usr/bin/env python3
"""Train V4-D V1.1 with OPEN_TRAIN-only nested parent-group CV.

The program cannot accept OPEN_DEVELOPMENT or prospective-test labels.  It
reports nested out-of-fold development evidence on the 226 OPEN_TRAIN rows and
freezes four full-train scoring families for later label-free V4-H research
scoring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v4_d_surrogate as base  # noqa: E402
import train_phase2_v4_d_frozen_embedding_surrogate as embedding  # noqa: E402


SCHEMA_VERSION = "phase2_v4_d_open_train_nested_late_fusion_v1_1"
STATUS = "COMPLETE_OPEN_TRAIN_NESTED_OOF_AND_FULL_SCORING_FITS_NO_DEV_OR_TEST_ACCESS"
EXPECTED_LABEL_SHA256 = "8fb90b20e6f939989ef2c3e5fee3fba184217ec0a094cf33c48c4996e2df9ef8"
EXPECTED_STRUCTURE_SHA256 = "37b6fbc4b947f2598dd83ac1a742a9382d36e13aa641a5f460e3050d17e83472"
EXPECTED_EMBEDDING_MANIFEST_SHA256 = "8a479c8c36d6bb7a539004f93bef0e1802262e2b102b7ddacae9e3438763e62e"
EXPECTED_EMBEDDING_SUMMARY_SHA256 = "ddbfdc8ea2ce1c3a85080cffe48ae3568b3831f5a8a38b16362cb2a7106159d7"
EXPECTED_EMBEDDING_SHARD_SHA256 = "3ae48934436d1c58aba83de05940abb961be298eb2a397ad789ed6a56487fa22"
EXPECTED_PREREG_SHA256 = "cabcff4f17cd5a27a5a8b248b2a247c2f39b49dce9b06f1f950db0929e7d7ecf"
PRIMARY_TARGET = "R_dual_min"
MODELS = (
    "M1_sequence_only",
    "M2_structure_only",
    "M4_prediction_late_fusion",
    "M5_structure_plus_sequence_residual",
)
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)
FUSION_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
RESIDUAL_GAMMAS = (0.0, 0.25, 0.5, 0.75, 1.0)
OUTER_FOLDS = 5
INNER_FOLDS = 5
SUB_INNER_FOLDS = 5
BOOTSTRAP_REPLICATES = 5000
STRUCTURE_METADATA_FIELDS = {
    "schema_version", "candidate_id", "sequence_sha256", "model_split",
    "parent_framework_cluster", "monomer_sha256", "claim_boundary",
}
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only development approximation of independent dual-receptor "
    "computational docking geometry; not Docking Gold, binding probability, "
    "affinity, competition, experimental blocking, or final submission authority."
)


class TrainingError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TrainingError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_table(path: Path, delimiter: str = "\t") -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def build_group_folds(groups: Sequence[str], fold_count: int) -> list[np.ndarray]:
    require(fold_count >= 2, "fold_count_too_small")
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    require(len(by_group) >= fold_count, f"too_few_groups:{len(by_group)}:{fold_count}")
    bins: list[list[int]] = [[] for _ in range(fold_count)]
    loads = [0] * fold_count
    for group, indices in sorted(by_group.items(), key=lambda item: (-len(item[1]), item[0])):
        target = min(range(fold_count), key=lambda fold: (loads[fold], fold))
        bins[target].extend(indices)
        loads[target] += len(indices)
    folds = [np.asarray(sorted(indices), dtype=np.int64) for indices in bins]
    require(all(len(fold) for fold in folds), "empty_group_fold")
    require(sorted(np.concatenate(folds).tolist()) == list(range(len(groups))), "fold_row_closure_failed")
    for held in folds:
        held_set = set(held.tolist())
        held_groups = {str(groups[index]) for index in held}
        train_groups = {str(groups[index]) for index in range(len(groups)) if index not in held_set}
        require(not (held_groups & train_groups), "parent_group_leakage")
    return folds


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> base.RidgeFit:
    require(x.ndim == 2 and y.ndim == 1 and len(x) == len(y), "ridge_shape_invalid")
    require(np.isfinite(x).all() and np.isfinite(y).all(), "ridge_nonfinite")
    return embedding.fit_dual_ridge(x, y, alpha) if x.shape[1] > len(x) else base.fit_ridge(x, y, alpha)


def predict_ridge(x: np.ndarray, fitted: base.RidgeFit) -> np.ndarray:
    value = np.asarray(base.predict_ridge(x, fitted), dtype=np.float64)
    require(np.isfinite(value).all(), "prediction_nonfinite")
    return value


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    require(len(y_true) == len(y_pred) and len(y_true) >= 4, "metric_rows_invalid")
    pearson = 0.0 if np.std(y_true) < 1e-12 or np.std(y_pred) < 1e-12 else float(np.corrcoef(y_true, y_pred)[0, 1])
    budget = max(1, math.ceil(0.20 * len(y_true)))
    truth = set(np.argsort(-y_true, kind="mergesort")[:budget].tolist())
    predicted = set(np.argsort(-y_pred, kind="mergesort")[:budget].tolist())
    return {
        "spearman": float(base.spearman(y_true, y_pred)),
        "pearson": pearson,
        "mae": float(np.mean(np.abs(y_true - y_pred))),
        "ndcg": float(base.ndcg(y_true, y_pred)),
        "top20_percent_recall": len(truth & predicted) / len(truth),
    }


def metric_key(value: Mapping[str, float], regularization: float) -> tuple[float, ...]:
    return (
        float(value["spearman"]), float(value["ndcg"]),
        float(value["top20_percent_recall"]), -float(value["mae"]),
        float(regularization),
    )


def crossfit_ridge(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alpha: float,
    fold_count: int,
) -> np.ndarray:
    output = np.empty(len(y), dtype=np.float64)
    for held in build_group_folds(groups, fold_count):
        keep = np.ones(len(y), dtype=bool)
        keep[held] = False
        output[held] = predict_ridge(x[held], fit_ridge(x[keep], y[keep], alpha))
    require(np.isfinite(output).all(), "crossfit_nonfinite")
    return output


def select_alpha_oof(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alphas: Sequence[float],
    fold_count: int,
) -> tuple[float, np.ndarray, dict[str, dict[str, float]]]:
    candidates: list[tuple[tuple[float, ...], float, np.ndarray]] = []
    grid: dict[str, dict[str, float]] = {}
    for alpha in alphas:
        prediction = crossfit_ridge(x, y, groups, float(alpha), fold_count)
        value = metrics(y, prediction)
        grid[str(float(alpha))] = value
        candidates.append((metric_key(value, float(alpha)), float(alpha), prediction))
    _key, selected, prediction = max(candidates, key=lambda item: item[0])
    return selected, prediction, grid


def select_fusion_weight(
    y: np.ndarray,
    sequence_pred: np.ndarray,
    structure_pred: np.ndarray,
    weights: Sequence[float],
) -> tuple[float, np.ndarray, dict[str, dict[str, float]]]:
    candidates: list[tuple[tuple[float, ...], float, np.ndarray]] = []
    grid: dict[str, dict[str, float]] = {}
    for weight in weights:
        prediction = (1.0 - float(weight)) * sequence_pred + float(weight) * structure_pred
        value = metrics(y, prediction)
        grid[str(float(weight))] = value
        key = metric_key(value, 0.0) + (-abs(float(weight) - 0.5), float(weight))
        candidates.append((key, float(weight), prediction))
    _key, selected, prediction = max(candidates, key=lambda item: item[0])
    return selected, prediction, grid


@dataclass
class ResidualMetaComponent:
    keep: np.ndarray
    held: np.ndarray
    residual_target: np.ndarray
    base_prediction: np.ndarray
    local_structure_alpha: float


def prepare_residual_meta_components(
    sequence_x: np.ndarray,
    structure_x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alphas: Sequence[float],
    inner_folds: int,
    sub_inner_folds: int,
) -> list[ResidualMetaComponent]:
    components: list[ResidualMetaComponent] = []
    for held in build_group_folds(groups, inner_folds):
        keep = np.ones(len(y), dtype=bool)
        keep[held] = False
        kept_groups = [str(groups[index]) for index in np.flatnonzero(keep)]
        local_alpha, local_structure_oof, _grid = select_alpha_oof(
            structure_x[keep], y[keep], kept_groups, alphas, sub_inner_folds
        )
        structure_fit = fit_ridge(structure_x[keep], y[keep], local_alpha)
        components.append(ResidualMetaComponent(
            keep=keep,
            held=held,
            residual_target=y[keep] - local_structure_oof,
            base_prediction=predict_ridge(structure_x[held], structure_fit),
            local_structure_alpha=local_alpha,
        ))
    return components


def select_residual_configuration(
    sequence_x: np.ndarray,
    structure_x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alphas: Sequence[float],
    gammas: Sequence[float],
    inner_folds: int,
    sub_inner_folds: int,
) -> tuple[float, float, np.ndarray, dict[str, dict[str, float]], list[dict[str, Any]]]:
    components = prepare_residual_meta_components(
        sequence_x, structure_x, y, groups, alphas, inner_folds, sub_inner_folds
    )
    candidates: list[tuple[tuple[float, ...], float, float, np.ndarray]] = []
    grid: dict[str, dict[str, float]] = {}
    for alpha in alphas:
        residual_oof = np.empty(len(y), dtype=np.float64)
        base_oof = np.empty(len(y), dtype=np.float64)
        for component in components:
            residual_fit = fit_ridge(sequence_x[component.keep], component.residual_target, float(alpha))
            residual_oof[component.held] = predict_ridge(sequence_x[component.held], residual_fit)
            base_oof[component.held] = component.base_prediction
        for gamma in gammas:
            prediction = base_oof + float(gamma) * residual_oof
            value = metrics(y, prediction)
            key_name = f"alpha={float(alpha)};gamma={float(gamma)}"
            grid[key_name] = value
            key = metric_key(value, float(alpha)) + (-float(gamma),)
            candidates.append((key, float(alpha), float(gamma), prediction))
    _key, selected_alpha, selected_gamma, prediction = max(candidates, key=lambda item: item[0])
    component_audit = [
        {
            "held_rows": len(component.held),
            "training_rows": int(component.keep.sum()),
            "local_structure_alpha": component.local_structure_alpha,
        }
        for component in components
    ]
    return selected_alpha, selected_gamma, prediction, grid, component_audit


def paired_group_bootstrap_delta(
    y: np.ndarray,
    prediction_a: np.ndarray,
    prediction_b: np.ndarray,
    groups: Sequence[str],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = 20260717,
) -> dict[str, Any]:
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    names = sorted(by_group)
    require(len(names) >= 2, "bootstrap_groups_too_few")
    rng = np.random.default_rng(seed)
    deltas = np.empty(replicates, dtype=np.float64)
    for replicate in range(replicates):
        sampled = rng.integers(0, len(names), size=len(names))
        indices = np.asarray([index for value in sampled for index in by_group[names[int(value)]]], dtype=np.int64)
        deltas[replicate] = base.spearman(y[indices], prediction_a[indices]) - base.spearman(y[indices], prediction_b[indices])
    return {
        "replicates": replicates,
        "seed": seed,
        "median_delta": float(np.median(deltas)),
        "ci95_lower": float(np.quantile(deltas, 0.025)),
        "ci95_upper": float(np.quantile(deltas, 0.975)),
        "positive_fraction": float(np.mean(deltas > 0.0)),
        "resampling_unit": "parent_framework_cluster",
    }


@dataclass
class NestedResult:
    predictions: dict[str, np.ndarray]
    outer_fold: np.ndarray
    outer_audit: list[dict[str, Any]]


def nested_oof(
    sequence_x: np.ndarray,
    structure_x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    *,
    alphas: Sequence[float] = ALPHAS,
    weights: Sequence[float] = FUSION_WEIGHTS,
    gammas: Sequence[float] = RESIDUAL_GAMMAS,
    outer_folds: int = OUTER_FOLDS,
    inner_folds: int = INNER_FOLDS,
    sub_inner_folds: int = SUB_INNER_FOLDS,
) -> NestedResult:
    require(len(sequence_x) == len(structure_x) == len(y) == len(groups), "nested_row_mismatch")
    predictions = {name: np.empty(len(y), dtype=np.float64) for name in MODELS}
    outer_assignment = np.full(len(y), -1, dtype=np.int64)
    audit: list[dict[str, Any]] = []
    for fold_index, held in enumerate(build_group_folds(groups, outer_folds)):
        keep = np.ones(len(y), dtype=bool)
        keep[held] = False
        kept_indices = np.flatnonzero(keep)
        kept_groups = [str(groups[index]) for index in kept_indices]
        y_train = y[keep]
        sequence_alpha, sequence_inner_oof, sequence_grid = select_alpha_oof(
            sequence_x[keep], y_train, kept_groups, alphas, inner_folds
        )
        structure_alpha, structure_inner_oof, structure_grid = select_alpha_oof(
            structure_x[keep], y_train, kept_groups, alphas, inner_folds
        )
        fusion_weight, _fusion_inner, fusion_grid = select_fusion_weight(
            y_train, sequence_inner_oof, structure_inner_oof, weights
        )
        residual_alpha, residual_gamma, _residual_inner, residual_grid, residual_components = select_residual_configuration(
            sequence_x[keep], structure_x[keep], y_train, kept_groups,
            alphas, gammas, inner_folds, sub_inner_folds,
        )
        sequence_fit = fit_ridge(sequence_x[keep], y_train, sequence_alpha)
        structure_fit = fit_ridge(structure_x[keep], y_train, structure_alpha)
        sequence_held = predict_ridge(sequence_x[held], sequence_fit)
        structure_held = predict_ridge(structure_x[held], structure_fit)
        residual_target = y_train - structure_inner_oof
        residual_fit = fit_ridge(sequence_x[keep], residual_target, residual_alpha)
        residual_held = predict_ridge(sequence_x[held], residual_fit)
        predictions["M1_sequence_only"][held] = sequence_held
        predictions["M2_structure_only"][held] = structure_held
        predictions["M4_prediction_late_fusion"][held] = (
            (1.0 - fusion_weight) * sequence_held + fusion_weight * structure_held
        )
        predictions["M5_structure_plus_sequence_residual"][held] = structure_held + residual_gamma * residual_held
        outer_assignment[held] = fold_index
        audit.append({
            "outer_fold": fold_index,
            "held_rows": len(held),
            "held_parent_clusters": sorted({str(groups[index]) for index in held}),
            "training_rows": int(keep.sum()),
            "training_parent_cluster_count": len(set(kept_groups)),
            "selected_sequence_alpha": sequence_alpha,
            "selected_structure_alpha": structure_alpha,
            "selected_fusion_structure_weight": fusion_weight,
            "selected_residual_alpha": residual_alpha,
            "selected_residual_gamma": residual_gamma,
            "sequence_alpha_grid": sequence_grid,
            "structure_alpha_grid": structure_grid,
            "fusion_weight_grid": fusion_grid,
            "residual_grid": residual_grid,
            "residual_meta_components": residual_components,
        })
    require(np.all(outer_assignment >= 0), "outer_assignment_incomplete")
    require(all(np.isfinite(value).all() for value in predictions.values()), "nested_predictions_nonfinite")
    return NestedResult(predictions, outer_assignment, audit)


def load_small_embedding_matrix(manifest_path: Path, summary_path: Path, shard_path: Path, hashes: Sequence[str]) -> tuple[np.ndarray, dict[str, Any]]:
    require(sha256_file(manifest_path) == EXPECTED_EMBEDDING_MANIFEST_SHA256, "embedding_manifest_hash_mismatch")
    require(sha256_file(summary_path) == EXPECTED_EMBEDDING_SUMMARY_SHA256, "embedding_summary_hash_mismatch")
    require(sha256_file(shard_path) == EXPECTED_EMBEDDING_SHARD_SHA256, "embedding_shard_hash_mismatch")
    _fields, rows = load_table(manifest_path, ",")
    require(len(rows) == 226, "embedding_manifest_count_invalid")
    manifest_hashes = [row["sequence_sha256"] for row in rows]
    require(len(set(manifest_hashes)) == 226, "embedding_manifest_hashes_not_unique")
    summary = json.loads(summary_path.read_text())
    require(summary.get("sequence_count") == 226 and summary.get("vhh_sequence_count") == 226, "embedding_summary_count_invalid")
    payload = torch.load(shard_path, map_location="cpu", weights_only=True)
    require(list(payload.get("sequence_sha256", ())) == manifest_hashes, "embedding_shard_order_mismatch")
    arrays = []
    for channel, dimension in (("vhhbert", 768), ("esm2", 320), ("physchem", 27)):
        tensor = payload.get(channel)
        require(isinstance(tensor, torch.Tensor) and tuple(tensor.shape) == (226, dimension), f"embedding_shape_invalid:{channel}")
        array = tensor.detach().cpu().float().numpy().astype(np.float64, copy=False)
        require(np.isfinite(array).all(), f"embedding_nonfinite:{channel}")
        arrays.append(array)
    available = payload.get("vhhbert_available")
    require(isinstance(available, torch.Tensor) and bool(available.bool().all()), "vhhbert_availability_invalid")
    full = np.concatenate(arrays, axis=1)
    index = {value: position for position, value in enumerate(manifest_hashes)}
    require(not [value for value in hashes if value not in index], "training_hash_missing_from_embedding_bank")
    order = np.asarray([index[value] for value in hashes], dtype=np.int64)
    return full[order], {
        "manifest_sha256": EXPECTED_EMBEDDING_MANIFEST_SHA256,
        "summary_sha256": EXPECTED_EMBEDDING_SUMMARY_SHA256,
        "shard_sha256": EXPECTED_EMBEDDING_SHARD_SHA256,
        "rows": 226,
        "feature_count": 1115,
        "channel_order": ["vhhbert", "esm2", "physchem"],
    }


def save_fit_arrays(path: Path, fits: Mapping[str, base.RidgeFit]) -> str:
    arrays: dict[str, np.ndarray] = {}
    for name, fitted in fits.items():
        arrays[f"{name}__intercept"] = np.asarray([fitted.intercept], dtype=np.float64)
        arrays[f"{name}__coefficient"] = np.asarray(fitted.coefficient, dtype=np.float64)
        arrays[f"{name}__center"] = np.asarray(fitted.center, dtype=np.float64)
        arrays[f"{name}__scale"] = np.asarray(fitted.scale, dtype=np.float64)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)
    return sha256_file(path)


def train(
    labels_path: Path,
    structure_path: Path,
    embedding_manifest: Path,
    embedding_summary: Path,
    embedding_shard: Path,
    preregistration: Path,
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_dir_exists")
    require(sha256_file(labels_path) == EXPECTED_LABEL_SHA256, "labels_hash_mismatch")
    require(sha256_file(structure_path) == EXPECTED_STRUCTURE_SHA256, "structure_hash_mismatch")
    require(sha256_file(preregistration) == EXPECTED_PREREG_SHA256, "preregistration_hash_mismatch")
    fields, rows = load_table(labels_path)
    required = {"candidate_id", "sequence_sha256", "model_split", "parent_framework_cluster", PRIMARY_TARGET}
    require(required <= set(fields), "label_fields_missing")
    require(len(rows) == 226 and {row["model_split"] for row in rows} == {"OPEN_TRAIN"}, "label_scope_not_open_train226")
    require(len({row["candidate_id"] for row in rows}) == 226, "label_candidate_not_unique")
    groups = [row["parent_framework_cluster"] for row in rows]
    require(len(set(groups)) == 20, "parent_cluster_count_invalid")
    y = np.asarray([float(row[PRIMARY_TARGET]) for row in rows], dtype=np.float64)
    require(np.isfinite(y).all(), "target_nonfinite")
    sequence_x, embedding_provenance = load_small_embedding_matrix(
        embedding_manifest, embedding_summary, embedding_shard,
        [row["sequence_sha256"] for row in rows],
    )
    structure_fields, structure_rows = load_table(structure_path)
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    require(len(structure_by_id) == 258, "structure_candidate_count_invalid")
    feature_names = [name for name in structure_fields if name not in STRUCTURE_METADATA_FIELDS]
    require(len(feature_names) == 126, "structure_feature_count_invalid")
    structure_x = np.asarray([
        [float(structure_by_id[row["candidate_id"]][name]) for name in feature_names]
        for row in rows
    ], dtype=np.float64)
    require(np.isfinite(structure_x).all(), "structure_nonfinite")
    for row in rows:
        structure_row = structure_by_id.get(row["candidate_id"])
        require(structure_row is not None, f"structure_missing:{row['candidate_id']}")
        require(structure_row["sequence_sha256"] == row["sequence_sha256"], f"structure_sequence_mismatch:{row['candidate_id']}")
        require(structure_row["parent_framework_cluster"] == row["parent_framework_cluster"], f"structure_parent_mismatch:{row['candidate_id']}")

    nested = nested_oof(sequence_x, structure_x, y, groups)
    model_metrics = {name: metrics(y, prediction) for name, prediction in nested.predictions.items()}
    bootstrap = {
        "M4_minus_M1": paired_group_bootstrap_delta(y, nested.predictions["M4_prediction_late_fusion"], nested.predictions["M1_sequence_only"], groups),
        "M4_minus_M2": paired_group_bootstrap_delta(y, nested.predictions["M4_prediction_late_fusion"], nested.predictions["M2_structure_only"], groups),
        "M5_minus_M2": paired_group_bootstrap_delta(y, nested.predictions["M5_structure_plus_sequence_residual"], nested.predictions["M2_structure_only"], groups),
    }

    sequence_alpha, sequence_oof, sequence_grid = select_alpha_oof(sequence_x, y, groups, ALPHAS, INNER_FOLDS)
    structure_alpha, structure_oof, structure_grid = select_alpha_oof(structure_x, y, groups, ALPHAS, INNER_FOLDS)
    fusion_weight, _fusion_oof, fusion_grid = select_fusion_weight(y, sequence_oof, structure_oof, FUSION_WEIGHTS)
    residual_alpha, residual_gamma, _residual_oof, residual_grid, residual_components = select_residual_configuration(
        sequence_x, structure_x, y, groups, ALPHAS, RESIDUAL_GAMMAS, INNER_FOLDS, SUB_INNER_FOLDS
    )
    fits = {
        "M1_sequence": fit_ridge(sequence_x, y, sequence_alpha),
        "M2_structure": fit_ridge(structure_x, y, structure_alpha),
        "M5_sequence_residual": fit_ridge(sequence_x, y - structure_oof, residual_alpha),
    }

    output_dir.mkdir(parents=True)
    prediction_rows = []
    for index, row in enumerate(rows):
        prediction_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "model_split": row["model_split"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "outer_fold": int(nested.outer_fold[index]),
            "target_R_dual_min": f"{y[index]:.12g}",
            **{f"prediction_{name}": f"{nested.predictions[name][index]:.12g}" for name in MODELS},
            "claim_boundary": CLAIM_BOUNDARY,
        })
    prediction_path = output_dir / "open_train226_nested_oof_predictions_v1_1.tsv"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(prediction_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(prediction_rows)
    atomic_write(prediction_path, buffer.getvalue().encode("utf-8"))

    fit_path = output_dir / "open_train226_scoring_fits_v1_1.npz"
    fit_sha = save_fit_arrays(fit_path, fits)
    config = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "primary_target": PRIMARY_TARGET,
        "fit_rows": 226,
        "parent_framework_clusters": 20,
        "preregistration_sha256": EXPECTED_PREREG_SHA256,
        "input_hashes": {
            "labels": EXPECTED_LABEL_SHA256,
            "structure_features": EXPECTED_STRUCTURE_SHA256,
            **embedding_provenance,
        },
        "feature_dimensions": {"sequence": sequence_x.shape[1], "structure": structure_x.shape[1]},
        "structure_feature_names": feature_names,
        "full_train_hyperparameters": {
            "sequence_alpha": sequence_alpha,
            "structure_alpha": structure_alpha,
            "fusion_structure_weight": fusion_weight,
            "residual_alpha": residual_alpha,
            "residual_gamma": residual_gamma,
        },
        "full_train_selection_grids": {
            "sequence_alpha": sequence_grid,
            "structure_alpha": structure_grid,
            "fusion_weight": fusion_grid,
            "residual": residual_grid,
            "residual_meta_components": residual_components,
        },
        "fit_artifact": fit_path.name,
        "fit_artifact_sha256": fit_sha,
        "prediction_formulas": {
            "M1_sequence_only": "M1_sequence",
            "M2_structure_only": "M2_structure",
            "M4_prediction_late_fusion": "(1-w_structure)*M1_sequence + w_structure*M2_structure",
            "M5_structure_plus_sequence_residual": "M2_structure + gamma*M5_sequence_residual",
        },
        "open_development_target_values_accessed": 0,
        "V4_F_test32_sequences_or_embeddings_accessed": 0,
        "V4_F_test32_predictions_emitted": 0,
        "V4_F_test32_labels_accessed": 0,
        "V4_H_docking_labels_accessed": 0,
    }
    config_path = output_dir / "open_train226_scoring_config_v1_1.json"
    atomic_write(config_path, (json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "nested_oof_metrics": model_metrics,
        "paired_parent_group_bootstrap": bootstrap,
        "outer_fold_audit": nested.outer_audit,
        "formal_pass_claimed": False,
        "same_data_model_family_selection_bias_disclosed": True,
        "sealed_boundaries": {
            "open_development_target_values_accessed": 0,
            "V4_F_test32_sequences_or_embeddings_accessed": 0,
            "V4_F_test32_predictions_emitted": 0,
            "V4_F_test32_labels_accessed": 0,
            "V4_H_docking_labels_accessed": 0,
            "legacy128_merged": False,
        },
        "artifacts": {
            "predictions": {"path": prediction_path.name, "sha256": sha256_file(prediction_path)},
            "config": {"path": config_path.name, "sha256": sha256_file(config_path)},
            "fits": {"path": fit_path.name, "sha256": fit_sha},
        },
    }
    summary_path = output_dir / "open_train226_nested_oof_summary_v1_1.json"
    atomic_write(summary_path, (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_completion_receipt",
        "status": STATUS,
        "prediction_sha256": sha256_file(prediction_path),
        "config_sha256": sha256_file(config_path),
        "fits_sha256": fit_sha,
        "summary_sha256": sha256_file(summary_path),
        "nested_oof_rows": 226,
        "parent_framework_clusters": 20,
        "open_development_target_values_accessed": 0,
        "V4_F_test32_sequences_or_embeddings_accessed": 0,
        "V4_F_test32_predictions_emitted": 0,
        "V4_F_test32_labels_accessed": 0,
        "V4_H_docking_labels_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "open_train226_nested_oof_completion_receipt_v1_1.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "nested_oof_metrics": model_metrics,
        "paired_parent_group_bootstrap": bootstrap,
        "completion_receipt_sha256": sha256_file(receipt_path),
        "open_development_target_values_accessed": 0,
        "V4_F_test32_labels_accessed": 0,
        "V4_H_docking_labels_accessed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--structure-features", type=Path, required=True)
    parser.add_argument("--embedding-manifest", type=Path, required=True)
    parser.add_argument("--embedding-summary", type=Path, required=True)
    parser.add_argument("--embedding-shard", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = train(
        args.labels, args.structure_features, args.embedding_manifest,
        args.embedding_summary, args.embedding_shard, args.preregistration,
        args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
