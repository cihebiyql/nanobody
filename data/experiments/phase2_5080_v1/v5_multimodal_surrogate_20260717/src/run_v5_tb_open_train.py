#!/usr/bin/env python3
"""Run dependency-light V5-TB development comparisons on OPEN_TRAIN226.

This script never reads OPEN_DEVELOPMENT or prospective-test inputs. It uses
deterministic whole-parent nested cross-validation and compares continuous,
dual-receptor, low-dimensional fusion, classification-assisted, and pairwise
ranking heads against the existing structure-only Ridge baseline.
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
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np


PHASE2_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SRC = PHASE2_ROOT / "src"
if str(LEGACY_SRC) not in sys.path:
    sys.path.insert(0, str(LEGACY_SRC))

import phase2_v3_contracts as contracts  # noqa: E402
import train_phase2_v4_d_open_train_nested_late_fusion_v1_1 as v4  # noqa: E402


SCHEMA_VERSION = "pvrig_v5_tb_open_train_development_v1"
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only development approximation of independent dual-receptor "
    "computational docking geometry; not Docking Gold, binding probability, "
    "affinity, competition, experimental blocking, or final submission authority."
)
MODELS = (
    "B0_train_mean",
    "B1_structure_direct",
    "B2_dual_receptor_min",
    "B3_structure_plus_physchem",
    "B4_direct_dual_convex",
    "B5_top20_ridge_classifier",
    "B6_within_parent_pairwise_ridge",
)
STRUCTURE_METADATA_FIELDS = {
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "model_split",
    "parent_framework_cluster",
    "target_patch_id",
    "design_mode",
    "monomer_sha256",
    "claim_boundary",
}


class V5Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise V5Error(message)


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


@dataclass(frozen=True)
class Dataset:
    rows: list[dict[str, str]]
    structure_x: np.ndarray
    physchem_x: np.ndarray
    structure_feature_names: list[str]
    y8: np.ndarray
    y9: np.ndarray
    ydual: np.ndarray
    ygap: np.ndarray
    groups: list[str]


def load_dataset(teacher_path: Path, structure_path: Path) -> Dataset:
    teacher_fields, teacher_rows = load_table(teacher_path)
    required_teacher = {
        "candidate_id",
        "sequence_sha256",
        "sequence",
        "model_split",
        "parent_framework_cluster",
        "R_8X6B",
        "R_9E6Y",
        "R_dual_min",
        "R_dual_gap",
    }
    require(required_teacher <= set(teacher_fields), "teacher_fields_missing")
    rows = [row for row in teacher_rows if row["model_split"] == "OPEN_TRAIN"]
    require(len(rows) == 226, f"open_train_row_count_invalid:{len(rows)}")
    require(len({row["candidate_id"] for row in rows}) == 226, "candidate_id_not_unique")
    require(len({row["sequence_sha256"] for row in rows}) == 226, "sequence_sha256_not_unique")
    groups = [row["parent_framework_cluster"] for row in rows]
    require(len(set(groups)) == 20, f"parent_cluster_count_invalid:{len(set(groups))}")
    require(not any(row["model_split"] != "OPEN_TRAIN" for row in rows), "forbidden_split_exposed")

    structure_fields, structure_rows = load_table(structure_path)
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    require(len(structure_by_id) == len(structure_rows), "structure_candidate_not_unique")
    feature_names = [field for field in structure_fields if field not in STRUCTURE_METADATA_FIELDS]
    require(len(feature_names) == 126, f"structure_feature_count_invalid:{len(feature_names)}")

    structure_values: list[list[float]] = []
    physicochemical_values: list[list[float]] = []
    for row in rows:
        structure = structure_by_id.get(row["candidate_id"])
        require(structure is not None, f"structure_missing:{row['candidate_id']}")
        require(structure["sequence_sha256"] == row["sequence_sha256"], f"sequence_mismatch:{row['candidate_id']}")
        require(
            structure["parent_framework_cluster"] == row["parent_framework_cluster"],
            f"parent_mismatch:{row['candidate_id']}",
        )
        structure_values.append([float(structure[name]) for name in feature_names])
        physicochemical_values.append(contracts.physicochemical_features(row["sequence"]))

    structure_x = np.asarray(structure_values, dtype=np.float64)
    physchem_x = np.asarray(physicochemical_values, dtype=np.float64)
    require(structure_x.shape == (226, 126), "structure_shape_invalid")
    require(physchem_x.shape == (226, 27), "physchem_shape_invalid")
    require(np.isfinite(structure_x).all() and np.isfinite(physchem_x).all(), "features_nonfinite")

    y8 = np.asarray([float(row["R_8X6B"]) for row in rows], dtype=np.float64)
    y9 = np.asarray([float(row["R_9E6Y"]) for row in rows], dtype=np.float64)
    ydual = np.asarray([float(row["R_dual_min"]) for row in rows], dtype=np.float64)
    ygap = np.asarray([float(row["R_dual_gap"]) for row in rows], dtype=np.float64)
    require(np.allclose(np.minimum(y8, y9), ydual, atol=1e-9), "dual_min_contract_failed")
    require(np.allclose(np.abs(y8 - y9), ygap, atol=1e-9), "dual_gap_contract_failed")
    return Dataset(rows, structure_x, physchem_x, feature_names, y8, y9, ydual, ygap, groups)


def parent_center(values: np.ndarray, groups: Sequence[str]) -> np.ndarray:
    output = np.empty_like(values, dtype=np.float64)
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    for indices in by_group.values():
        selected = np.asarray(indices, dtype=np.int64)
        output[selected] = values[selected] - float(np.mean(values[selected]))
    return output


def extended_metrics(y: np.ndarray, prediction: np.ndarray, groups: Sequence[str]) -> dict[str, float]:
    result = dict(v4.metrics(y, prediction))
    result["parent_centered_spearman"] = float(
        v4.base.spearman(parent_center(y, groups), parent_center(prediction, groups))
    )
    per_parent = []
    for group in sorted(set(groups)):
        indices = np.asarray([index for index, value in enumerate(groups) if value == group], dtype=np.int64)
        if len(indices) >= 4:
            per_parent.append(float(v4.base.spearman(y[indices], prediction[indices])))
    result["per_parent_macro_mean_spearman"] = float(np.mean(per_parent))
    result["per_parent_macro_median_spearman"] = float(np.median(per_parent))
    return result


def selection_key(value: Mapping[str, float], alpha: float) -> tuple[float, ...]:
    return (
        float(value["spearman"]),
        float(value["ndcg"]),
        float(value["top20_percent_recall"]),
        -float(value["mae"]),
        float(alpha),
    )


def crossfit_dual(
    x: np.ndarray,
    y8: np.ndarray,
    y9: np.ndarray,
    groups: Sequence[str],
    alpha: float,
    fold_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pred8 = np.empty(len(y8), dtype=np.float64)
    pred9 = np.empty(len(y9), dtype=np.float64)
    for held in v4.build_group_folds(groups, fold_count):
        keep = np.ones(len(y8), dtype=bool)
        keep[held] = False
        pred8[held] = v4.predict_ridge(x[held], v4.fit_ridge(x[keep], y8[keep], alpha))
        pred9[held] = v4.predict_ridge(x[held], v4.fit_ridge(x[keep], y9[keep], alpha))
    return pred8, pred9, np.minimum(pred8, pred9)


def select_dual_alpha(
    x: np.ndarray,
    y8: np.ndarray,
    y9: np.ndarray,
    groups: Sequence[str],
    alphas: Sequence[float],
    fold_count: int,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    ydual = np.minimum(y8, y9)
    candidates = []
    grid: dict[str, Any] = {}
    for alpha in alphas:
        pred8, pred9, preddual = crossfit_dual(x, y8, y9, groups, float(alpha), fold_count)
        value = extended_metrics(ydual, preddual, groups)
        grid[str(float(alpha))] = {
            "dual": value,
            "R_8X6B": v4.metrics(y8, pred8),
            "R_9E6Y": v4.metrics(y9, pred9),
        }
        candidates.append((selection_key(value, float(alpha)), float(alpha), pred8, pred9, preddual))
    _key, selected, pred8, pred9, preddual = max(candidates, key=lambda item: item[0])
    return selected, pred8, pred9, preddual, grid


@dataclass
class CalibratedHead:
    primary: v4.base.RidgeFit
    calibration: v4.base.RidgeFit


def fit_top20_head(x: np.ndarray, y: np.ndarray, alpha: float) -> CalibratedHead:
    threshold = float(np.quantile(y, 0.80, method="higher"))
    labels = (y >= threshold).astype(np.float64)
    require(0 < int(labels.sum()) < len(labels), "top20_binary_degenerate")
    classifier = v4.fit_ridge(x, labels, alpha)
    raw = v4.predict_ridge(x, classifier)
    calibration = v4.fit_ridge(raw.reshape(-1, 1), y, 1.0)
    return CalibratedHead(classifier, calibration)


def predict_calibrated_head(x: np.ndarray, fitted: CalibratedHead) -> tuple[np.ndarray, np.ndarray]:
    raw = v4.predict_ridge(x, fitted.primary)
    calibrated = v4.predict_ridge(raw.reshape(-1, 1), fitted.calibration)
    return raw, calibrated


def build_pairwise_rows(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    minimum_delta: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    differences = []
    targets = []
    logical_pairs = 0
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        by_group[str(group)].append(index)
    for indices in by_group.values():
        for left_position, left in enumerate(indices):
            for right in indices[left_position + 1 :]:
                delta = float(y[left] - y[right])
                if abs(delta) < minimum_delta:
                    continue
                difference = x[left] - x[right]
                differences.extend((difference, -difference))
                targets.extend((delta, -delta))
                logical_pairs += 1
    require(logical_pairs > 0, "pairwise_rows_empty")
    return np.asarray(differences, dtype=np.float64), np.asarray(targets, dtype=np.float64), logical_pairs


def fit_pairwise_head(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alpha: float,
    minimum_delta: float,
) -> tuple[CalibratedHead, int]:
    pair_x, pair_y, logical_pairs = build_pairwise_rows(x, y, groups, minimum_delta)
    ranker = v4.fit_ridge(pair_x, pair_y, alpha)
    raw = v4.predict_ridge(x, ranker)
    calibration = v4.fit_ridge(raw.reshape(-1, 1), y, 1.0)
    return CalibratedHead(ranker, calibration), logical_pairs


def crossfit_custom(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alpha: float,
    fold_count: int,
    fit_head: Callable[[np.ndarray, np.ndarray, Sequence[str], float], tuple[CalibratedHead, int] | CalibratedHead],
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    raw = np.empty(len(y), dtype=np.float64)
    calibrated = np.empty(len(y), dtype=np.float64)
    pair_counts: list[int] = []
    for held in v4.build_group_folds(groups, fold_count):
        keep = np.ones(len(y), dtype=bool)
        keep[held] = False
        fitted_result = fit_head(x[keep], y[keep], [groups[index] for index in np.flatnonzero(keep)], alpha)
        if isinstance(fitted_result, tuple):
            fitted, count = fitted_result
            pair_counts.append(int(count))
        else:
            fitted = fitted_result
        raw[held], calibrated[held] = predict_calibrated_head(x[held], fitted)
    require(np.isfinite(raw).all() and np.isfinite(calibrated).all(), "custom_crossfit_nonfinite")
    return raw, calibrated, pair_counts


def select_custom_alpha(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alphas: Sequence[float],
    fold_count: int,
    fit_head: Callable[[np.ndarray, np.ndarray, Sequence[str], float], tuple[CalibratedHead, int] | CalibratedHead],
) -> tuple[float, np.ndarray, np.ndarray, dict[str, Any]]:
    candidates = []
    grid: dict[str, Any] = {}
    for alpha in alphas:
        raw, calibrated, counts = crossfit_custom(x, y, groups, float(alpha), fold_count, fit_head)
        value = extended_metrics(y, calibrated, groups)
        grid[str(float(alpha))] = {"metrics": value, "pair_counts": counts}
        candidates.append((selection_key(value, float(alpha)), float(alpha), raw, calibrated))
    _key, selected, raw, calibrated = max(candidates, key=lambda item: item[0])
    return selected, raw, calibrated, grid


def average_precision_for_top20(y: np.ndarray, score: np.ndarray) -> float:
    budget = max(1, math.ceil(0.20 * len(y)))
    positive = set(np.argsort(-y, kind="mergesort")[:budget].tolist())
    order = np.argsort(-score, kind="mergesort")
    hits = 0
    precisions = []
    for rank, index in enumerate(order, start=1):
        if int(index) in positive:
            hits += 1
            precisions.append(hits / rank)
    return float(np.mean(precisions))


@dataclass
class Evaluation:
    predictions: dict[str, np.ndarray]
    pred8: np.ndarray
    pred9: np.ndarray
    raw_top20: np.ndarray
    outer_fold: np.ndarray
    outer_audit: list[dict[str, Any]]


def nested_evaluate(
    dataset: Dataset,
    *,
    alphas: Sequence[float] = v4.ALPHAS,
    weights: Sequence[float] = v4.FUSION_WEIGHTS,
    outer_folds: int = 5,
    inner_folds: int = 5,
    pairwise_minimum_delta: float = 0.02,
) -> Evaluation:
    n = len(dataset.ydual)
    combined_x = np.concatenate((dataset.structure_x, dataset.physchem_x), axis=1)
    predictions = {name: np.empty(n, dtype=np.float64) for name in MODELS}
    pred8 = np.empty(n, dtype=np.float64)
    pred9 = np.empty(n, dtype=np.float64)
    raw_top20 = np.empty(n, dtype=np.float64)
    outer_assignment = np.full(n, -1, dtype=np.int64)
    audits: list[dict[str, Any]] = []

    for fold_index, held in enumerate(v4.build_group_folds(dataset.groups, outer_folds)):
        keep = np.ones(n, dtype=bool)
        keep[held] = False
        kept_indices = np.flatnonzero(keep)
        train_groups = [dataset.groups[index] for index in kept_indices]
        y_train = dataset.ydual[keep]

        direct_alpha, direct_inner, direct_grid = v4.select_alpha_oof(
            dataset.structure_x[keep], y_train, train_groups, alphas, inner_folds
        )
        dual_alpha, inner8, inner9, dual_inner, dual_grid = select_dual_alpha(
            dataset.structure_x[keep], dataset.y8[keep], dataset.y9[keep], train_groups, alphas, inner_folds
        )
        combined_alpha, _combined_inner, combined_grid = v4.select_alpha_oof(
            combined_x[keep], y_train, train_groups, alphas, inner_folds
        )
        fusion_weight, _fusion_inner, fusion_grid = v4.select_fusion_weight(
            y_train, direct_inner, dual_inner, weights
        )

        top20_alpha, _top20_raw_inner, _top20_inner, top20_grid = select_custom_alpha(
            dataset.structure_x[keep],
            y_train,
            train_groups,
            alphas,
            inner_folds,
            lambda x, y, _groups, alpha: fit_top20_head(x, y, alpha),
        )
        pairwise_alpha, _pair_raw_inner, _pair_inner, pair_grid = select_custom_alpha(
            dataset.structure_x[keep],
            y_train,
            train_groups,
            alphas,
            inner_folds,
            lambda x, y, groups, alpha: fit_pairwise_head(
                x, y, groups, alpha, pairwise_minimum_delta
            ),
        )

        direct_fit = v4.fit_ridge(dataset.structure_x[keep], y_train, direct_alpha)
        direct_held = v4.predict_ridge(dataset.structure_x[held], direct_fit)
        fit8 = v4.fit_ridge(dataset.structure_x[keep], dataset.y8[keep], dual_alpha)
        fit9 = v4.fit_ridge(dataset.structure_x[keep], dataset.y9[keep], dual_alpha)
        held8 = v4.predict_ridge(dataset.structure_x[held], fit8)
        held9 = v4.predict_ridge(dataset.structure_x[held], fit9)
        dual_held = np.minimum(held8, held9)
        combined_fit = v4.fit_ridge(combined_x[keep], y_train, combined_alpha)
        combined_held = v4.predict_ridge(combined_x[held], combined_fit)

        top20_fit = fit_top20_head(dataset.structure_x[keep], y_train, top20_alpha)
        top20_raw_held, top20_held = predict_calibrated_head(dataset.structure_x[held], top20_fit)
        pair_fit, pair_count = fit_pairwise_head(
            dataset.structure_x[keep], y_train, train_groups, pairwise_alpha, pairwise_minimum_delta
        )
        _pair_raw_held, pair_held = predict_calibrated_head(dataset.structure_x[held], pair_fit)

        predictions["B0_train_mean"][held] = float(np.mean(y_train))
        predictions["B1_structure_direct"][held] = direct_held
        predictions["B2_dual_receptor_min"][held] = dual_held
        predictions["B3_structure_plus_physchem"][held] = combined_held
        predictions["B4_direct_dual_convex"][held] = (
            (1.0 - fusion_weight) * direct_held + fusion_weight * dual_held
        )
        predictions["B5_top20_ridge_classifier"][held] = top20_held
        predictions["B6_within_parent_pairwise_ridge"][held] = pair_held
        pred8[held] = held8
        pred9[held] = held9
        raw_top20[held] = top20_raw_held
        outer_assignment[held] = fold_index

        audits.append({
            "outer_fold": fold_index,
            "held_rows": len(held),
            "held_parent_clusters": sorted({dataset.groups[index] for index in held}),
            "training_rows": int(keep.sum()),
            "training_parent_cluster_count": len(set(train_groups)),
            "selected_direct_alpha": direct_alpha,
            "selected_dual_alpha": dual_alpha,
            "selected_combined_alpha": combined_alpha,
            "selected_fusion_dual_weight": fusion_weight,
            "selected_top20_alpha": top20_alpha,
            "selected_pairwise_alpha": pairwise_alpha,
            "pairwise_logical_pair_count": pair_count,
            "direct_alpha_grid": direct_grid,
            "dual_alpha_grid": dual_grid,
            "combined_alpha_grid": combined_grid,
            "fusion_grid": fusion_grid,
            "top20_grid": top20_grid,
            "pairwise_grid": pair_grid,
            "inner_dual_receptor_prediction_correlation": float(np.corrcoef(inner8, inner9)[0, 1]),
        })

    require(np.all(outer_assignment >= 0), "outer_assignment_incomplete")
    require(all(np.isfinite(value).all() for value in predictions.values()), "predictions_nonfinite")
    return Evaluation(predictions, pred8, pred9, raw_top20, outer_assignment, audits)


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# PVRIG V5-TB OPEN_TRAIN226 执行结果",
        "",
        f"状态：`{summary['status']}`",
        "",
        "## 证据边界",
        "",
        summary["claim_boundary"],
        "",
        "## Nested whole-parent OOF",
        "",
        "| model | Spearman | parent-centered | macro-parent | MAE | NDCG | Top20 recall | ΔSpearman vs B1 CI |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    metrics = summary["nested_oof_metrics"]
    bootstrap = summary["paired_parent_bootstrap_vs_B1"]
    for model in MODELS:
        value = metrics[model]
        if model == "B1_structure_direct":
            interval = "reference"
        else:
            boot = bootstrap[model]
            interval = f"{boot['median_delta']:+.4f} [{boot['ci95_lower']:+.4f},{boot['ci95_upper']:+.4f}]"
        lines.append(
            f"| {model} | {value['spearman']:.4f} | {value['parent_centered_spearman']:.4f} | "
            f"{value['per_parent_macro_mean_spearman']:.4f} | {value['mae']:.5f} | "
            f"{value['ndcg']:.5f} | {value['top20_percent_recall']:.4f} | {interval} |"
        )
    lines.extend([
        "",
        "## 双受体辅助结果",
        "",
        f"- R_8X6B Spearman: `{summary['dual_receptor_auxiliary_metrics']['R_8X6B']['spearman']:.4f}`",
        f"- R_9E6Y Spearman: `{summary['dual_receptor_auxiliary_metrics']['R_9E6Y']['spearman']:.4f}`",
        f"- R_dual_gap Spearman: `{summary['dual_receptor_auxiliary_metrics']['R_dual_gap']['spearman']:.4f}`",
        f"- Top20 classifier raw AP: `{summary['top20_classifier_average_precision']:.4f}`",
        "",
        "## 当前选择",
        "",
        f"- 最佳候选：`{summary['best_candidate_model']}`",
        f"- 相对 B1 的 development gates：`{summary['development_gate_result']}`",
        "- 本轮不宣称 formal PASS；V4-F/test32 与 OPEN_DEVELOPMENT 未访问。",
        "",
    ])
    return "\n".join(lines)


def run(teacher_path: Path, structure_path: Path, preregistration: Path, output_dir: Path) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_dir_exists")
    prereg = json.loads(preregistration.read_text())
    require(prereg.get("status") == "FROZEN_BEFORE_FIRST_V5_TB_RESULT", "preregistration_not_frozen")
    require(prereg.get("primary_target") == "R_dual_min", "preregistered_target_invalid")
    alphas = tuple(float(value) for value in prereg["ridge_alphas"])
    weights = tuple(float(value) for value in prereg["convex_weights"])
    dataset = load_dataset(teacher_path, structure_path)
    evaluation = nested_evaluate(
        dataset,
        alphas=alphas,
        weights=weights,
        outer_folds=int(prereg["validation"]["outer_folds"]),
        inner_folds=int(prereg["validation"]["inner_folds"]),
        pairwise_minimum_delta=float(prereg["pairwise_minimum_absolute_delta"]),
    )

    model_metrics = {
        name: extended_metrics(dataset.ydual, prediction, dataset.groups)
        for name, prediction in evaluation.predictions.items()
    }
    bootstrap = {}
    for offset, name in enumerate(MODELS):
        if name == "B1_structure_direct":
            continue
        bootstrap[name] = v4.paired_group_bootstrap_delta(
            dataset.ydual,
            evaluation.predictions[name],
            evaluation.predictions["B1_structure_direct"],
            dataset.groups,
            replicates=int(prereg["validation"]["bootstrap_replicates"]),
            seed=int(prereg["validation"]["bootstrap_seed"]) + offset,
        )

    candidate_models = [name for name in MODELS if name not in {"B0_train_mean", "B1_structure_direct"}]
    best = max(candidate_models, key=lambda name: selection_key(model_metrics[name], 0.0))
    reference = model_metrics["B1_structure_direct"]
    selected = model_metrics[best]
    gates = {
        "global_spearman_improved": selected["spearman"] > reference["spearman"],
        "parent_centered_not_worse": selected["parent_centered_spearman"] >= reference["parent_centered_spearman"],
        "top20_recall_not_worse": selected["top20_percent_recall"] >= reference["top20_percent_recall"],
    }
    gate_result = "PASS_DEVELOPMENT_GATES_NO_FORMAL_CLAIM" if all(gates.values()) else "FAIL_KEEP_B1_STRUCTURE_DIRECT"

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_OPEN_TRAIN226_NESTED_DEVELOPMENT_COMPARISON",
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": {
            "teacher": sha256_file(teacher_path),
            "structure_features": sha256_file(structure_path),
            "preregistration": sha256_file(preregistration),
        },
        "rows": 226,
        "parent_framework_clusters": 20,
        "structure_feature_count": 126,
        "physchem_feature_count": 27,
        "nested_oof_metrics": model_metrics,
        "paired_parent_bootstrap_vs_B1": bootstrap,
        "dual_receptor_auxiliary_metrics": {
            "R_8X6B": extended_metrics(dataset.y8, evaluation.pred8, dataset.groups),
            "R_9E6Y": extended_metrics(dataset.y9, evaluation.pred9, dataset.groups),
            "R_dual_gap": extended_metrics(dataset.ygap, np.abs(evaluation.pred8 - evaluation.pred9), dataset.groups),
        },
        "top20_classifier_average_precision": average_precision_for_top20(dataset.ydual, evaluation.raw_top20),
        "best_candidate_model": best,
        "development_gates": gates,
        "development_gate_result": gate_result,
        "outer_fold_audit": evaluation.outer_audit,
        "sealed_boundaries": {
            "OPEN_DEVELOPMENT_labels_accessed": 0,
            "V4_F_test32_accessed": 0,
            "prospective_labels_accessed": 0,
            "partial937_used_for_model_selection": 0,
            "formal_pass_claimed": False,
        },
    }

    output_dir.mkdir(parents=True)
    prediction_rows = []
    for index, row in enumerate(dataset.rows):
        prediction_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "outer_fold": int(evaluation.outer_fold[index]),
            "target_R_8X6B": f"{dataset.y8[index]:.12g}",
            "target_R_9E6Y": f"{dataset.y9[index]:.12g}",
            "target_R_dual_min": f"{dataset.ydual[index]:.12g}",
            "target_R_dual_gap": f"{dataset.ygap[index]:.12g}",
            "prediction_B2_R_8X6B": f"{evaluation.pred8[index]:.12g}",
            "prediction_B2_R_9E6Y": f"{evaluation.pred9[index]:.12g}",
            "raw_B5_top20_score": f"{evaluation.raw_top20[index]:.12g}",
            **{
                f"prediction_{name}": f"{evaluation.predictions[name][index]:.12g}"
                for name in MODELS
            },
            "claim_boundary": CLAIM_BOUNDARY,
        })
    prediction_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        prediction_buffer,
        fieldnames=list(prediction_rows[0]),
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(prediction_rows)
    predictions_path = output_dir / "open_train226_v5_tb_nested_oof_predictions.tsv"
    atomic_write(predictions_path, prediction_buffer.getvalue().encode("utf-8"))

    summary_path = output_dir / "open_train226_v5_tb_summary.json"
    atomic_write(
        summary_path,
        (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
    )
    report_path = output_dir / "OPEN_TRAIN226_V5_TB_RESULTS_ZH.md"
    atomic_write(report_path, (render_report(summary) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": summary["status"],
        "predictions_sha256": sha256_file(predictions_path),
        "summary_sha256": sha256_file(summary_path),
        "report_sha256": sha256_file(report_path),
        "development_gate_result": gate_result,
        "formal_pass_claimed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "RUN_RECEIPT.json"
    atomic_write(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {
        "status": summary["status"],
        "best_candidate_model": best,
        "development_gate_result": gate_result,
        "summary_sha256": sha256_file(summary_path),
        "receipt_sha256": sha256_file(receipt_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--structure-features", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args.teacher, args.structure_features, args.preregistration, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
