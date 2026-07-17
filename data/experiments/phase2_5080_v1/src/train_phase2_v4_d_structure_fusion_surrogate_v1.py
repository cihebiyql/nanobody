#!/usr/bin/env python3
"""Train the preregistered V4-D open258 structure-fusion ablation.

The program consumes only OPEN_TRAIN and OPEN_DEVELOPMENT labels from the
development-only V1.2 teacher.  It has no prospective-test label argument and
does not emit prospective predictions.
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


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v4_d_surrogate as base  # noqa: E402
import train_phase2_v4_d_frozen_embedding_surrogate as embedding  # noqa: E402


SCHEMA_VERSION = "phase2_v4_d_structure_fusion_surrogate_v1"
COMPLETE_STATUS = "COMPLETE_DEV_ONLY_M0_M3_STRUCTURE_FUSION_COMPARISON_TEST32_UNTOUCHED"
EXPECTED_TEACHER_SHA256 = "89ad82c7cde28d862fecedfff4559e810bab68cf2405aa8f9e4dc5f1bd148068"
EXPECTED_STRUCTURE_SHA256 = "37b6fbc4b947f2598dd83ac1a742a9382d36e13aa641a5f460e3050d17e83472"
EXPECTED_PREREG_SHA256 = "026820be4f821e86cada34d581083196cd5c850f759a7229b854b5e59ebe9fe9"
EXPECTED_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
PRIMARY_TARGET = "R_dual_min"
TARGETS = ("R_dual_min", "R_8X6B", "R_9E6Y", "R_dual_gap", "teacher_uncertainty")
MODELS = ("M0_parent_only", "M1_sequence_only", "M2_structure_only", "M3_sequence_structure")
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)
ENSEMBLE_SEEDS = (43, 53, 67, 79, 97)
GROUP_FOLDS = 5
BOOTSTRAP_REPLICATES = 5000
CLAIM_BOUNDARY = (
    "Post-hoc development-only approximation of independent dual-receptor "
    "computational docking geometry; not Docking Gold, binding probability, "
    "affinity, competition, experimental blocking, or final submission authority."
)
KEY_FIELDS = (
    "candidate_id", "sequence_sha256", "model_split", "parent_framework_cluster"
)
STRUCTURE_METADATA_FIELDS = {
    "schema_version", "candidate_id", "sequence_sha256", "model_split",
    "parent_framework_cluster", "monomer_sha256", "claim_boundary",
}


class TrainingError(RuntimeError):
    """Fail-closed training error."""


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


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def build_group_folds(groups: Sequence[str], fold_count: int = GROUP_FOLDS) -> list[np.ndarray]:
    require(len(groups) > 0, "empty_groups")
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    require(len(by_group) >= fold_count, "too_few_groups_for_folds")
    bins: list[list[int]] = [[] for _ in range(fold_count)]
    loads = [0] * fold_count
    for group, indices in sorted(by_group.items(), key=lambda item: (-len(item[1]), item[0])):
        fold = min(range(fold_count), key=lambda value: (loads[value], value))
        bins[fold].extend(indices)
        loads[fold] += len(indices)
    folds = [np.asarray(sorted(indices), dtype=np.int64) for indices in bins]
    require(all(len(fold) > 0 for fold in folds), "empty_group_fold")
    flattened = np.concatenate(folds)
    require(sorted(flattened.tolist()) == list(range(len(groups))), "group_fold_row_closure_failed")
    for fold in folds:
        fold_groups = {str(groups[index]) for index in fold}
        outside_groups = {str(groups[index]) for index in range(len(groups)) if index not in set(fold.tolist())}
        require(not (fold_groups & outside_groups), "group_leakage_between_folds")
    return folds


def fit_ridge_auto(x: np.ndarray, y: np.ndarray, alpha: float) -> base.RidgeFit:
    require(x.ndim == 2 and y.ndim == 1 and len(x) == len(y), "ridge_input_shape_invalid")
    if x.shape[1] > len(x):
        return embedding.fit_dual_ridge(x, y, alpha)
    return base.fit_ridge(x, y, alpha)


def select_alpha_group_cv(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alphas: Sequence[float] = ALPHAS,
) -> tuple[float, dict[str, dict[str, float]]]:
    folds = build_group_folds(groups)
    metrics: dict[str, dict[str, float]] = {}
    candidates: list[tuple[tuple[float, float, float, float, float], float]] = []
    for alpha in alphas:
        predictions = np.empty(len(y), dtype=np.float64)
        for held_out in folds:
            keep = np.ones(len(y), dtype=bool)
            keep[held_out] = False
            fitted = fit_ridge_auto(x[keep], y[keep], float(alpha))
            predictions[held_out] = base.predict_ridge(x[held_out], fitted)
        require(np.isfinite(predictions).all(), f"nonfinite_group_cv_predictions:{alpha}")
        value = development_metrics(y, predictions)
        metrics[str(float(alpha))] = value
        selection_key = (
            value["spearman"],
            value["ndcg"],
            value["top20_percent_recall"],
            -value["mae"],
            -float(alpha),
        )
        candidates.append((selection_key, float(alpha)))
    _key, selected = max(candidates, key=lambda item: item[0])
    return selected, metrics


def categorical_spec(train_rows: Sequence[Mapping[str, str]]) -> dict[str, tuple[str, ...]]:
    return {
        field: tuple(sorted({str(row[field]) for row in train_rows}))
        for field in ("parent_framework_cluster", "design_mode", "target_patch_id")
    }


def categorical_matrix(rows: Sequence[Mapping[str, str]], spec: Mapping[str, Sequence[str]]) -> tuple[np.ndarray, list[str]]:
    names: list[str] = []
    for field in sorted(spec):
        names.extend(f"{field}={value}" for value in spec[field])
    matrix = np.asarray(
        [
            [float(str(row[field]) == category) for field in sorted(spec) for category in spec[field]]
            for row in rows
        ],
        dtype=np.float64,
    )
    require(matrix.shape == (len(rows), len(names)), "categorical_matrix_shape_invalid")
    return matrix, names


def development_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    require(len(y_true) == len(y_pred) and len(y_true) >= 4, "metric_row_count_invalid")
    require(np.isfinite(y_true).all() and np.isfinite(y_pred).all(), "metric_nonfinite")
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


def paired_bootstrap_spearman_delta(
    y_true: np.ndarray,
    m3_pred: np.ndarray,
    m1_pred: np.ndarray,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = 20260717,
) -> dict[str, Any]:
    require(len(y_true) == len(m3_pred) == len(m1_pred), "paired_bootstrap_row_mismatch")
    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    for _ in range(replicates):
        indices = rng.integers(0, len(y_true), size=len(y_true))
        deltas.append(base.spearman(y_true[indices], m3_pred[indices]) - base.spearman(y_true[indices], m1_pred[indices]))
    values = np.asarray(deltas, dtype=np.float64)
    return {
        "replicates": replicates,
        "seed": seed,
        "median_delta": float(np.median(values)),
        "ci95_lower": float(np.quantile(values, 0.025)),
        "ci95_upper": float(np.quantile(values, 0.975)),
        "positive_fraction": float(np.mean(values > 0.0)),
    }


def group_bootstrap_indices(groups: Sequence[str], seed: int) -> np.ndarray:
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    names = sorted(by_group)
    require(len(names) >= 2, "too_few_bootstrap_groups")
    rng = np.random.default_rng(seed)
    sampled = rng.choice(len(names), size=len(names), replace=True)
    return np.asarray([index for value in sampled for index in by_group[names[int(value)]]], dtype=np.int64)


@dataclass
class ModelInputs:
    feature_names: list[str]
    train: np.ndarray
    development: np.ndarray


def save_fits(path: Path, fits: Mapping[str, base.RidgeFit]) -> str:
    arrays: dict[str, np.ndarray] = {}
    for key, fitted in fits.items():
        arrays[f"{key}__intercept"] = np.asarray([fitted.intercept], dtype=np.float64)
        arrays[f"{key}__coefficient"] = np.asarray(fitted.coefficient, dtype=np.float64)
        arrays[f"{key}__center"] = np.asarray(fitted.center, dtype=np.float64)
        arrays[f"{key}__scale"] = np.asarray(fitted.scale, dtype=np.float64)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)
    return sha256_file(path)


def train(
    teacher_path: Path,
    structure_path: Path,
    preregistration_path: Path,
    embedding_manifest: Path,
    embedding_summary: Path,
    sequence_manifest: Path,
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    require(sha256_file(teacher_path) == EXPECTED_TEACHER_SHA256, "teacher_sha256_mismatch")
    require(sha256_file(structure_path) == EXPECTED_STRUCTURE_SHA256, "structure_features_sha256_mismatch")
    require(sha256_file(preregistration_path) == EXPECTED_PREREG_SHA256, "preregistration_sha256_mismatch")
    teacher_fields, teacher_rows = load_tsv(teacher_path)
    require(all(target in teacher_fields for target in TARGETS), "teacher_targets_missing")
    require(Counter(row["model_split"] for row in teacher_rows) == Counter(EXPECTED_COUNTS), "teacher_split_counts_invalid")
    structure_fields, structure_rows = load_tsv(structure_path)
    require(Counter(row["model_split"] for row in structure_rows) == Counter(EXPECTED_COUNTS), "structure_split_counts_invalid")
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    require(len(structure_by_id) == len(structure_rows) == 258, "structure_candidate_closure_invalid")
    structure_feature_names = [name for name in structure_fields if name not in STRUCTURE_METADATA_FIELDS]
    require(len(structure_feature_names) == 126, f"structure_feature_count_invalid:{len(structure_feature_names)}")
    for row in teacher_rows:
        feature_row = structure_by_id.get(row["candidate_id"])
        require(feature_row is not None, f"structure_candidate_missing:{row['candidate_id']}")
        for field in KEY_FIELDS:
            require(row[field] == feature_row[field], f"teacher_structure_key_mismatch:{row['candidate_id']}:{field}")
    train_rows = [row for row in teacher_rows if row["model_split"] == "OPEN_TRAIN"]
    development_rows = [row for row in teacher_rows if row["model_split"] == "OPEN_DEVELOPMENT"]
    require(len(train_rows) == 226 and len(development_rows) == 32, "fit_development_counts_invalid")
    train_groups = [row["parent_framework_cluster"] for row in train_rows]
    development_groups = [row["parent_framework_cluster"] for row in development_rows]
    require(not (set(train_groups) & set(development_groups)), "parent_cluster_split_leakage")

    bank = embedding.load_embedding_bank(
        embedding_manifest,
        embedding_summary,
        sequence_manifest,
        enforce_production_hashes=True,
    )
    train_hashes = [row["sequence_sha256"] for row in train_rows]
    development_hashes = [row["sequence_sha256"] for row in development_rows]
    sequence_train = bank.matrix(train_hashes, "joint_ridge")
    sequence_development = bank.matrix(development_hashes, "joint_ridge")
    structure_train = np.asarray(
        [[float(structure_by_id[row["candidate_id"]][name]) for name in structure_feature_names] for row in train_rows],
        dtype=np.float64,
    )
    structure_development = np.asarray(
        [[float(structure_by_id[row["candidate_id"]][name]) for name in structure_feature_names] for row in development_rows],
        dtype=np.float64,
    )
    require(np.isfinite(structure_train).all() and np.isfinite(structure_development).all(), "nonfinite_structure_matrix")
    spec = categorical_spec(train_rows)
    categorical_train, categorical_names = categorical_matrix(train_rows, spec)
    categorical_development, _ = categorical_matrix(development_rows, spec)
    model_inputs = {
        "M0_parent_only": ModelInputs(categorical_names, categorical_train, categorical_development),
        "M1_sequence_only": ModelInputs(
            [f"joint_embedding_{index}" for index in range(sequence_train.shape[1])], sequence_train, sequence_development
        ),
        "M2_structure_only": ModelInputs(structure_feature_names, structure_train, structure_development),
        "M3_sequence_structure": ModelInputs(
            [f"joint_embedding_{index}" for index in range(sequence_train.shape[1])] + structure_feature_names,
            np.concatenate((sequence_train, structure_train), axis=1),
            np.concatenate((sequence_development, structure_development), axis=1),
        ),
    }
    alpha_selection: dict[str, Any] = {}
    for model_name, inputs in model_inputs.items():
        y_primary = np.asarray([float(row[PRIMARY_TARGET]) for row in train_rows], dtype=np.float64)
        selected, cv_metrics = select_alpha_group_cv(inputs.train, y_primary, train_groups)
        alpha_selection[model_name] = {
            "target_used": PRIMARY_TARGET,
            "selected_alpha": selected,
            "group_cv_metrics": cv_metrics,
            "reused_for_secondary_targets": True,
        }

    fits: dict[str, base.RidgeFit] = {}
    predictions: dict[str, dict[str, np.ndarray]] = {name: {} for name in MODELS}
    uncertainty: dict[str, dict[str, np.ndarray]] = {name: {} for name in MODELS}
    metrics: dict[str, dict[str, dict[str, float]]] = {name: {} for name in MODELS}
    for model_name, inputs in model_inputs.items():
        alpha = float(alpha_selection[model_name]["selected_alpha"])
        for target in TARGETS:
            y_train = np.asarray([float(row[target]) for row in train_rows], dtype=np.float64)
            y_development = np.asarray([float(row[target]) for row in development_rows], dtype=np.float64)
            seed_predictions = []
            for seed in ENSEMBLE_SEEDS:
                indices = group_bootstrap_indices(train_groups, seed)
                fitted = fit_ridge_auto(inputs.train[indices], y_train[indices], alpha)
                key = f"{model_name}__{target}__seed_{seed}"
                fits[key] = fitted
                seed_predictions.append(base.predict_ridge(inputs.development, fitted))
            matrix = np.stack(seed_predictions, axis=1)
            mean = matrix.mean(axis=1)
            std = matrix.std(axis=1)
            require(np.isfinite(mean).all() and np.isfinite(std).all(), f"nonfinite_predictions:{model_name}:{target}")
            predictions[model_name][target] = mean
            uncertainty[model_name][target] = std
            metrics[model_name][target] = development_metrics(y_development, mean)

    primary_truth = np.asarray([float(row[PRIMARY_TARGET]) for row in development_rows], dtype=np.float64)
    structure_delta = paired_bootstrap_spearman_delta(
        primary_truth,
        predictions["M3_sequence_structure"][PRIMARY_TARGET],
        predictions["M1_sequence_only"][PRIMARY_TARGET],
    )
    structure_value_supported = (
        metrics["M3_sequence_structure"][PRIMARY_TARGET]["spearman"]
        > metrics["M1_sequence_only"][PRIMARY_TARGET]["spearman"]
        and structure_delta["median_delta"] > 0.0
    )
    ranked_models = sorted(
        MODELS,
        key=lambda name: (
            metrics[name][PRIMARY_TARGET]["spearman"],
            metrics[name][PRIMARY_TARGET]["ndcg"],
            -metrics[name][PRIMARY_TARGET]["mae"],
            name,
        ),
        reverse=True,
    )

    output_dir.mkdir(parents=True)
    fit_path = output_dir / "structure_fusion_ridge_fits_v1.npz"
    fit_sha = save_fits(fit_path, fits)
    prediction_rows: list[dict[str, Any]] = []
    for index, row in enumerate(development_rows):
        item: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "model_split": row["model_split"],
            "parent_framework_cluster": row["parent_framework_cluster"],
        }
        for target in TARGETS:
            item[f"target__{target}"] = f"{float(row[target]):.9g}"
            for model_name in MODELS:
                item[f"prediction__{model_name}__{target}"] = f"{predictions[model_name][target][index]:.9g}"
                item[f"uncertainty__{model_name}__{target}"] = f"{uncertainty[model_name][target][index]:.9g}"
        item["claim_boundary"] = CLAIM_BOUNDARY
        prediction_rows.append(item)
    prediction_path = output_dir / "open_development_m0_m3_predictions_v1.tsv"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(prediction_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(prediction_rows)
    atomic_write(prediction_path, buffer.getvalue().encode("utf-8"))

    config = {
        "schema_version": SCHEMA_VERSION,
        "status": COMPLETE_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "teacher_sha256": EXPECTED_TEACHER_SHA256,
        "structure_features_sha256": EXPECTED_STRUCTURE_SHA256,
        "preregistration_sha256": EXPECTED_PREREG_SHA256,
        "embedding_provenance": bank.provenance,
        "fit_rows": 226,
        "development_rows": 32,
        "parent_cluster_overlap": [],
        "targets": list(TARGETS),
        "primary_target": PRIMARY_TARGET,
        "models": {
            name: {
                "feature_count": len(inputs.feature_names),
                "feature_names": inputs.feature_names,
                "alpha_selection": alpha_selection[name],
            }
            for name, inputs in model_inputs.items()
        },
        "ensemble_seeds": list(ENSEMBLE_SEEDS),
        "ridge_fit_artifact": fit_path.name,
        "ridge_fit_artifact_sha256": fit_sha,
        "prospective_test_predictions_emitted": 0,
        "prospective_test_labels_accessed": 0,
    }
    config_path = output_dir / "structure_fusion_model_config_v1.json"
    atomic_write(config_path, (json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": COMPLETE_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "primary_target": PRIMARY_TARGET,
        "development_metrics": metrics,
        "primary_model_order": ranked_models,
        "best_development_model": ranked_models[0],
        "M3_minus_M1_paired_candidate_bootstrap": structure_delta,
        "structure_value_supported_by_preregistered_rule": structure_value_supported,
        "artifacts": {
            "predictions": {"path": prediction_path.name, "sha256": sha256_file(prediction_path)},
            "config": {"path": config_path.name, "sha256": sha256_file(config_path)},
            "fits": {"path": fit_path.name, "sha256": fit_sha},
        },
        "sealed_boundary": {
            "prospective_test_predictions_emitted": 0,
            "prospective_test_labels_accessed": 0,
            "legacy128_merged": False,
            "formal_v4_d_pass_claimed": False,
        },
    }
    summary_path = output_dir / "structure_fusion_development_summary_v1.json"
    atomic_write(summary_path, (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": COMPLETE_STATUS,
        "summary_sha256": sha256_file(summary_path),
        "prediction_sha256": sha256_file(prediction_path),
        "config_sha256": sha256_file(config_path),
        "fits_sha256": fit_sha,
        "fit_rows": 226,
        "development_rows": 32,
        "best_development_model": ranked_models[0],
        "structure_value_supported_by_preregistered_rule": structure_value_supported,
        "prospective_test_predictions_emitted": 0,
        "prospective_test_labels_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "structure_fusion_completion_receipt_v1.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": COMPLETE_STATUS,
        "best_development_model": ranked_models[0],
        "primary_metrics": {name: metrics[name][PRIMARY_TARGET] for name in MODELS},
        "structure_value_supported": structure_value_supported,
        "M3_minus_M1_bootstrap": structure_delta,
        "summary_sha256": sha256_file(summary_path),
        "completion_receipt_sha256": sha256_file(receipt_path),
        "prospective_test_labels_accessed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--structure-features", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--embedding-manifest", type=Path, required=True)
    parser.add_argument("--embedding-summary", type=Path, required=True)
    parser.add_argument("--sequence-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = train(
        args.teacher,
        args.structure_features,
        args.preregistration,
        args.embedding_manifest,
        args.embedding_summary,
        args.sequence_manifest,
        args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
