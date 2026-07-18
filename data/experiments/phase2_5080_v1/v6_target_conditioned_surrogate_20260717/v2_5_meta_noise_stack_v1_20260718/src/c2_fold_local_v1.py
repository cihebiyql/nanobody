#!/usr/bin/env python3
"""Fold-local C2 PCA8/Ridge primitive.

The API makes it impossible for score rows to participate in scaling,
constant filtering, PCA, alpha selection, or Ridge fitting.  It is used to
recompute inner C2 evidence inside each outer-train partition; the existing
outer C2 OOF table remains an independently validated frozen branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from meta_noise_stack_v1 import MetaNoiseError, _finite_array, normalize_weights, require, validate_predictor_names


@dataclass(frozen=True)
class FoldLocalPCA8Ridge:
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    kept_indices: tuple[int, ...]
    components: tuple[tuple[float, ...], ...]
    pca_mean: tuple[float, ...]
    pca_scale: tuple[float, ...]
    coefficient: tuple[tuple[float, float], ...]
    intercept: tuple[float, float]
    ridge_alpha: float
    train_row_count: int


def fit_fold_local_pca8_ridge(
    train_x: np.ndarray,
    train_y: np.ndarray,
    candidate_weights: np.ndarray,
    feature_names: Sequence[str],
    *,
    ridge_alpha: float,
    components: int = 8,
) -> FoldLocalPCA8Ridge:
    validate_predictor_names(feature_names)
    x = _finite_array(train_x, ndim=2, context="c2_train_x")
    y = _finite_array(train_y, ndim=2, context="c2_train_y")
    require(x.shape[0] == y.shape[0] and y.shape[1] == 2, "c2_train_shape")
    require(x.shape[1] == len(feature_names), "c2_feature_name_shape")
    require(ridge_alpha > 0 and components > 0, "c2_hyperparameter")
    weights = normalize_weights(candidate_weights) * len(x)
    require(weights.shape == (len(x),), "c2_weight_shape")
    # Reproduce the existing frozen C2 branch: the label-free PCA transformer
    # itself is unweighted, while the downstream Ridge is hierarchically
    # weighted.  Only current train-parent rows are visible to either stage.
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    kept = np.flatnonzero(scale > 1e-8)
    require(len(kept) >= components, "c2_too_few_nonconstant_features")
    z = (x[:, kept] - mean[kept]) / scale[kept]
    _, _, vt = np.linalg.svd(z, full_matrices=False)
    component_count = min(components, len(kept), len(x) - 1)
    require(component_count > 0, "c2_zero_components")
    basis = vt[:component_count].copy()
    for index in range(len(basis)):
        anchor = int(np.argmax(np.abs(basis[index])))
        if basis[index, anchor] < 0:
            basis[index] *= -1.0
    train_pca = z @ basis.T
    total = weights.sum()
    pca_mean = np.sum(train_pca * weights[:, None], axis=0) / total
    pca_variance = np.sum((train_pca - pca_mean) ** 2 * weights[:, None], axis=0) / total
    pca_scale = np.sqrt(np.maximum(pca_variance, 0.0))
    require(np.all(pca_scale > 1e-10), "c2_pca_component_constant")
    standardized_pca = (train_pca - pca_mean) / pca_scale
    x_mean = np.sum(standardized_pca * weights[:, None], axis=0) / total
    target_mean = np.sum(y * weights[:, None], axis=0) / total
    centered_x = standardized_pca - x_mean
    centered_y = y - target_mean
    coefficient = np.linalg.solve(
        centered_x.T @ (weights[:, None] * centered_x) + ridge_alpha * np.eye(component_count),
        centered_x.T @ (weights[:, None] * centered_y),
    )
    intercept = target_mean - x_mean @ coefficient
    return FoldLocalPCA8Ridge(
        feature_names=tuple(feature_names),
        mean=tuple(map(float, mean)),
        scale=tuple(map(float, scale)),
        kept_indices=tuple(map(int, kept)),
        components=tuple(tuple(map(float, row)) for row in basis),
        pca_mean=tuple(map(float, pca_mean)),
        pca_scale=tuple(map(float, pca_scale)),
        coefficient=tuple(tuple(map(float, row)) for row in coefficient),
        intercept=tuple(map(float, intercept)),
        ridge_alpha=float(ridge_alpha),
        train_row_count=len(x),
    )


def predict_fold_local_pca8_ridge(model: FoldLocalPCA8Ridge, score_x: np.ndarray) -> np.ndarray:
    x = _finite_array(score_x, ndim=2, context="c2_score_x")
    require(x.shape[1] == len(model.feature_names), "c2_score_feature_shape")
    mean, scale = np.asarray(model.mean), np.asarray(model.scale)
    kept = np.asarray(model.kept_indices, dtype=np.int64)
    z = (x[:, kept] - mean[kept]) / scale[kept]
    pca = z @ np.asarray(model.components).T
    standardized_pca = (pca - np.asarray(model.pca_mean)) / np.asarray(model.pca_scale)
    result = standardized_pca @ np.asarray(model.coefficient) + np.asarray(model.intercept)
    require(result.shape == (len(x), 2) and np.isfinite(result).all(), "c2_invalid_prediction")
    return result


def select_c2_alpha_inner_oof(
    inner_truth: np.ndarray,
    predictions_by_alpha: dict[float, np.ndarray],
    candidate_weights: np.ndarray,
) -> float:
    """Select on inner OOF only; ties at 1e-12 choose the largest alpha."""
    truth = _finite_array(inner_truth, ndim=2, context="c2_inner_truth")
    weights = normalize_weights(candidate_weights)
    require(truth.shape[1] == 2 and weights.shape == (len(truth),), "c2_selection_shape")
    losses: dict[float, float] = {}
    for alpha, prediction in predictions_by_alpha.items():
        pred = _finite_array(prediction, ndim=2, context=f"c2_alpha_{alpha}")
        require(pred.shape == truth.shape and alpha > 0, "c2_selection_prediction_shape")
        receptor_mae = np.mean(np.abs(pred - truth), axis=1)
        dual_mae = np.abs(np.minimum(pred[:, 0], pred[:, 1]) - np.minimum(truth[:, 0], truth[:, 1]))
        losses[float(alpha)] = float(np.sum(weights * (2.0 * receptor_mae + dual_mae) / 3.0))
    require(bool(losses), "empty_c2_alpha_grid")
    best = min(losses.values())
    return max(alpha for alpha, loss in losses.items() if abs(loss - best) <= 1e-12)
