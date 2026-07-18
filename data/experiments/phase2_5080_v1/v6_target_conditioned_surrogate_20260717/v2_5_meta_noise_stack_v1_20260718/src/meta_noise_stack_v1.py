#!/usr/bin/env python3
"""Leakage-safe V2.5 CPU meta/noise components.

This module deliberately separates fitting from scoring.  The primary model is
an M2-fallback convex residual stack.  The measurement-noise challenger learns
only from candidates with real repeated Docking seeds (tiers A/B), and every
reliability value used to fit a meta-head is itself whole-parent cross-fitted.

All outputs are computational Docking-geometry surrogates.  They are not
binding, affinity, experimental blocking, Docking Gold, or submission truth.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize


MODEL_VERSION = "pvrig_v2_5_ortho_contact_pose_meta_noise_v1"
PRIMARY_MODEL_ID = "M2_FALLBACK_CONVEX_RESIDUAL_STACK"
RELIABILITY_MODEL_ID = "M2_FALLBACK_RELIABILITY_WEIGHTED_CHALLENGER"
GBDT_MODEL_ID = "SHALLOW_HIST_GBDT_CHALLENGER"
BRANCH_NAMES = ("neural", "contact", "c2")
RECEPTORS = ("R8", "R9")
REPEATED_TIERS = frozenset({"A", "B"})
UNREPEATED_TIER = "C"
CLAIM_BOUNDARY = (
    "Open-development computational surrogate of independent 8X6B/9E6Y "
    "Docking geometry; not binding, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)
_SEALED = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])|test32", re.I)
_IDENTIFIER_TOKEN = re.compile(
    r"(^|_)(candidate|parent|campaign|source|fold|split|job|run|batch|seed)_?id($|_)",
    re.I,
)

BASE_PREDICTION_COLUMNS = tuple(
    f"{branch}_{receptor}" for branch in ("m2", *BRANCH_NAMES) for receptor in RECEPTORS
)
NOISE_FEATURE_NAMES = (
    *BASE_PREDICTION_COLUMNS,
    "m2_receptor_gap",
    "neural_receptor_gap",
    "contact_receptor_gap",
    "c2_receptor_gap",
    "neural_m2_disagreement",
    "contact_m2_disagreement",
    "c2_m2_disagreement",
    "neural_contact_disagreement",
    "neural_c2_disagreement",
    "contact_c2_disagreement",
)
GBDT_FEATURE_NAMES = (*NOISE_FEATURE_NAMES, "predicted_reliability")


class MetaNoiseError(RuntimeError):
    """Fail-closed contract error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MetaNoiseError(message)


def reject_sealed(value: str | Path, context: str) -> None:
    require(not _SEALED.search(str(value)), f"sealed_v4f_forbidden:{context}:{value}")


def validate_predictor_names(names: Sequence[str]) -> None:
    require(bool(names), "empty_predictor_names")
    require(len(set(names)) == len(names), "duplicate_predictor_name")
    for name in names:
        normalized = name.strip().lower()
        require(bool(normalized), "blank_predictor_name")
        require(not _IDENTIFIER_TOKEN.search(normalized), f"identifier_predictor_forbidden:{name}")
        require(normalized not in {
            "candidate_id", "parent_framework_cluster", "teacher_source",
            "campaign_id", "outer_fold", "inner_fold", "design_seed",
        }, f"identifier_predictor_forbidden:{name}")


def _finite_array(values: Any, *, ndim: int | None = None, context: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if ndim is not None:
        require(array.ndim == ndim, f"{context}_ndim:{array.ndim}")
    require(array.size > 0, f"{context}_empty")
    require(np.isfinite(array).all(), f"{context}_nonfinite")
    return array


def exact_min(prediction_two: np.ndarray) -> np.ndarray:
    values = _finite_array(prediction_two, ndim=2, context="exact_min")
    require(values.shape[1] == 2, "exact_min_requires_two_receptors")
    return np.minimum(values[:, 0], values[:, 1])


def hierarchical_weights(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Equal source -> equal parent -> equal candidate weights."""
    require(bool(rows), "empty_weight_rows")
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(rows):
        source = str(row["teacher_source"])
        parent = str(row["parent_framework_cluster"])
        reject_sealed(source, "teacher_source")
        groups[source][parent].append(index)
    weights = np.zeros(len(rows), dtype=np.float64)
    for parents in groups.values():
        for indices in parents.values():
            weights[indices] = 1.0 / len(groups) / len(parents) / len(indices)
    require(np.isclose(weights.sum(), 1.0, atol=1e-14, rtol=0.0), "weight_sum_not_one")
    return weights


def normalize_weights(weights: np.ndarray) -> np.ndarray:
    values = _finite_array(weights, ndim=1, context="weights")
    require(np.all(values >= 0), "negative_weight")
    require(float(values.sum()) > 0, "zero_weight_sum")
    return values / values.sum()


@dataclass(frozen=True)
class ConvexResidualStack:
    neural_weight: float
    contact_weight: float
    c2_weight: float
    l2_toward_m2: float

    def weights(self) -> np.ndarray:
        return np.asarray(
            [self.neural_weight, self.contact_weight, self.c2_weight], dtype=np.float64
        )

    def audit(self) -> dict[str, Any]:
        weights = self.weights()
        return {
            "model_version": MODEL_VERSION,
            "model_id": PRIMARY_MODEL_ID,
            "branch_names": list(BRANCH_NAMES),
            "branch_weights": {name: float(value) for name, value in zip(BRANCH_NAMES, weights)},
            "m2_fallback_weight": float(1.0 - weights.sum()),
            "weight_sum": float(weights.sum()),
            "l2_toward_m2": self.l2_toward_m2,
            "shared_weights_across_receptors": True,
            "intercept": False,
        }


def fit_convex_residual_stack(
    truth_two: np.ndarray,
    m2_two: np.ndarray,
    branch_predictions: Mapping[str, np.ndarray],
    candidate_weights: np.ndarray,
    *,
    l2_toward_m2: float = 1.0e-3,
) -> ConvexResidualStack:
    """Fit shared nonnegative branch residuals with sum(weights) <= 1."""
    truth = _finite_array(truth_two, ndim=2, context="truth")
    m2 = _finite_array(m2_two, ndim=2, context="m2")
    require(truth.shape == m2.shape and truth.shape[1] == 2, "stack_target_shape")
    require(set(branch_predictions) == set(BRANCH_NAMES), "stack_branch_closure")
    branches = np.stack([
        _finite_array(branch_predictions[name], ndim=2, context=f"branch_{name}")
        for name in BRANCH_NAMES
    ], axis=2)
    require(branches.shape == (len(truth), 2, len(BRANCH_NAMES)), "stack_branch_shape")
    weights = normalize_weights(candidate_weights)
    require(weights.shape == (len(truth),), "stack_weight_shape")
    require(l2_toward_m2 > 0 and math.isfinite(l2_toward_m2), "invalid_stack_l2")

    delta = branches - m2[:, :, None]
    residual = truth - m2

    def objective(beta: np.ndarray) -> float:
        error = np.einsum("nrb,b->nr", delta, beta) - residual
        return float(np.sum(weights[:, None] * error * error) + l2_toward_m2 * beta @ beta)

    def gradient(beta: np.ndarray) -> np.ndarray:
        error = np.einsum("nrb,b->nr", delta, beta) - residual
        return 2.0 * np.einsum("n,nr,nrb->b", weights, error, delta) + 2.0 * l2_toward_m2 * beta

    result = minimize(
        objective,
        np.zeros(len(BRANCH_NAMES), dtype=np.float64),
        jac=gradient,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * len(BRANCH_NAMES),
        constraints=[{"type": "ineq", "fun": lambda beta: 1.0 - float(np.sum(beta)),
                      "jac": lambda beta: -np.ones_like(beta)}],
        options={"ftol": 1e-14, "maxiter": 2000, "disp": False},
    )
    require(bool(result.success), f"convex_stack_fit_failed:{result.message}")
    beta = np.maximum(np.asarray(result.x, dtype=np.float64), 0.0)
    require(float(beta.sum()) <= 1.0 + 1e-10, "convex_stack_sum_violation")
    beta[beta < 1e-12] = 0.0
    return ConvexResidualStack(*map(float, beta), l2_toward_m2=float(l2_toward_m2))


def predict_convex_residual_stack(
    model: ConvexResidualStack,
    m2_two: np.ndarray,
    branch_predictions: Mapping[str, np.ndarray],
) -> np.ndarray:
    m2 = _finite_array(m2_two, ndim=2, context="score_m2")
    require(m2.shape[1] == 2, "score_m2_shape")
    require(set(branch_predictions) == set(BRANCH_NAMES), "score_branch_closure")
    branches = np.stack([
        _finite_array(branch_predictions[name], ndim=2, context=f"score_{name}")
        for name in BRANCH_NAMES
    ], axis=2)
    require(branches.shape == (len(m2), 2, len(BRANCH_NAMES)), "score_branch_shape")
    beta = model.weights()
    require(np.all(beta >= 0) and float(beta.sum()) <= 1.0 + 1e-10, "invalid_model_weights")
    prediction = m2 + np.einsum("nrb,b->nr", branches - m2[:, :, None], beta)
    require(np.isfinite(prediction).all(), "nonfinite_stack_prediction")
    return prediction


def _row_float(row: Mapping[str, Any], name: str) -> float:
    try:
        value = float(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise MetaNoiseError(f"invalid_numeric_field:{name}") from exc
    require(math.isfinite(value), f"nonfinite_numeric_field:{name}")
    return value


def _first_row_float(row: Mapping[str, Any], names: Sequence[str]) -> float:
    for name in names:
        if name in row and str(row[name]).strip() != "":
            return _row_float(row, name)
    raise MetaNoiseError(f"missing_numeric_aliases:{','.join(names)}")


def base_arrays(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    require(bool(rows), "empty_base_rows")
    m2 = np.asarray([[
        _first_row_float(row, ("m2_R8", "M2_R8")),
        _first_row_float(row, ("m2_R9", "M2_R9")),
    ] for row in rows])
    branches = {
        name: np.asarray([
            [
                _first_row_float(row, (
                    f"{name}_R8",
                    "contact_score_R8" if name == "contact" else f"{name}_R8",
                )),
                _first_row_float(row, (
                    f"{name}_R9",
                    "contact_score_R9" if name == "contact" else f"{name}_R9",
                )),
            ]
            for row in rows
        ])
        for name in BRANCH_NAMES
    }
    return m2, branches


def truth_array(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    return np.asarray([[
        _first_row_float(row, ("truth_R8", "R_8X6B")),
        _first_row_float(row, ("truth_R9", "R_9E6Y")),
    ] for row in rows])


def noise_feature_matrix(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Low-dimensional evidence only; no IDs, labels, poses, or raw latent vectors."""
    validate_predictor_names(NOISE_FEATURE_NAMES)
    m2, branches = base_arrays(rows)
    neural, contact, c2 = (branches[name] for name in BRANCH_NAMES)
    base = np.column_stack([m2, neural, contact, c2])
    gaps = np.column_stack([
        np.abs(m2[:, 0] - m2[:, 1]),
        np.abs(neural[:, 0] - neural[:, 1]),
        np.abs(contact[:, 0] - contact[:, 1]),
        np.abs(c2[:, 0] - c2[:, 1]),
    ])
    disagreements = np.column_stack([
        np.mean(np.abs(neural - m2), axis=1),
        np.mean(np.abs(contact - m2), axis=1),
        np.mean(np.abs(c2 - m2), axis=1),
        np.mean(np.abs(neural - contact), axis=1),
        np.mean(np.abs(neural - c2), axis=1),
        np.mean(np.abs(contact - c2), axis=1),
    ])
    result = np.column_stack([base, gaps, disagreements])
    require(result.shape == (len(rows), len(NOISE_FEATURE_NAMES)), "noise_feature_shape")
    require(np.isfinite(result).all(), "noise_feature_nonfinite")
    return result


@dataclass(frozen=True)
class NoiseHead:
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coefficient: tuple[float, ...]
    intercept_log_variance: float
    reference_variance: float
    ridge_alpha: float
    epsilon: float
    reliability_min: float
    reliability_max: float

    def audit(self) -> dict[str, Any]:
        return {
            "model_version": MODEL_VERSION,
            "fit_tiers": sorted(REPEATED_TIERS),
            "tier_C_used_as_variance_truth": False,
            "feature_names": list(self.feature_names),
            "ridge_alpha": self.ridge_alpha,
            "epsilon": self.epsilon,
            "reference_variance": self.reference_variance,
            "reliability_bounds": [self.reliability_min, self.reliability_max],
        }


def fit_noise_head(
    rows: Sequence[Mapping[str, Any]],
    candidate_weights: np.ndarray,
    *,
    ridge_alpha: float = 10.0,
    epsilon: float = 1.0e-6,
    reliability_min: float = 0.25,
    reliability_max: float = 4.0,
) -> NoiseHead:
    """Fit log variance on repeated A/B rows only; C is ignored, never zero-imputed."""
    require(bool(rows), "empty_noise_rows")
    weights_all = normalize_weights(candidate_weights)
    require(weights_all.shape == (len(rows),), "noise_weight_shape")
    indices = [i for i, row in enumerate(rows) if str(row["development_reliability_tier"]) in REPEATED_TIERS]
    require(indices, "no_repeated_seed_rows_for_noise_fit")
    require(ridge_alpha > 0 and epsilon > 0, "invalid_noise_hyperparameters")
    require(0 < reliability_min <= reliability_max, "invalid_reliability_bounds")
    x = noise_feature_matrix(rows)[indices]
    dispersion = np.asarray([_row_float(rows[i], "seed_dispersion_max") for i in indices])
    require(np.all(dispersion >= 0), "negative_seed_dispersion")
    y = np.log(dispersion * dispersion + epsilon)
    weights = normalize_weights(weights_all[indices])
    mean = np.sum(weights[:, None] * x, axis=0)
    variance = np.sum(weights[:, None] * (x - mean) ** 2, axis=0)
    scale = np.sqrt(np.maximum(variance, 0.0))
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    intercept = float(np.sum(weights * y))
    root = np.sqrt(weights * len(weights))[:, None]
    coefficient = np.linalg.solve(
        (z * root).T @ (z * root) + ridge_alpha * np.eye(z.shape[1]),
        (z * root).T @ ((y - intercept)[:, None] * root),
    ).reshape(-1)
    reference_variance = float(math.exp(intercept))
    require(reference_variance > 0 and math.isfinite(reference_variance), "invalid_reference_variance")
    return NoiseHead(
        feature_names=tuple(NOISE_FEATURE_NAMES),
        mean=tuple(map(float, mean)),
        scale=tuple(map(float, scale)),
        coefficient=tuple(map(float, coefficient)),
        intercept_log_variance=intercept,
        reference_variance=reference_variance,
        ridge_alpha=float(ridge_alpha),
        epsilon=float(epsilon),
        reliability_min=float(reliability_min),
        reliability_max=float(reliability_max),
    )


def predict_noise(model: NoiseHead, rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    require(tuple(model.feature_names) == tuple(NOISE_FEATURE_NAMES), "noise_feature_contract_mismatch")
    x = noise_feature_matrix(rows)
    z = (x - np.asarray(model.mean)) / np.asarray(model.scale)
    log_variance = model.intercept_log_variance + z @ np.asarray(model.coefficient)
    log_variance = np.clip(log_variance, math.log(model.epsilon), math.log(1.0))
    variance = np.exp(log_variance)
    reliability = np.clip(
        model.reference_variance / (variance + model.epsilon),
        model.reliability_min,
        model.reliability_max,
    )
    require(np.isfinite(variance).all() and np.isfinite(reliability).all(), "nonfinite_noise_prediction")
    return variance, reliability


def crossfit_noise_for_outer_fold(
    inner_oof_rows: Sequence[Mapping[str, Any]],
    outer_score_rows: Sequence[Mapping[str, Any]],
    *,
    expected_inner_folds: Iterable[int] = range(5),
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Generate OOF reliability for meta fit and train-only reliability for outer score."""
    require(bool(inner_oof_rows) and bool(outer_score_rows), "empty_crossfit_noise_rows")
    inner_ids = [str(row["candidate_id"]) for row in inner_oof_rows]
    outer_ids = [str(row["candidate_id"]) for row in outer_score_rows]
    require(len(set(inner_ids)) == len(inner_ids), "duplicate_inner_oof_candidate")
    require(len(set(outer_ids)) == len(outer_ids), "duplicate_outer_score_candidate")
    require(set(inner_ids).isdisjoint(outer_ids), "same_row_inner_outer_leakage")
    inner_parents = {str(row["parent_framework_cluster"]) for row in inner_oof_rows}
    outer_parents = {str(row["parent_framework_cluster"]) for row in outer_score_rows}
    require(inner_parents.isdisjoint(outer_parents), "outer_parent_leakage")
    fold_values = sorted({int(row["inner_fold"]) for row in inner_oof_rows})
    expected = sorted(set(expected_inner_folds))
    require(fold_values == expected, f"inner_fold_closure:{fold_values}")
    oof_reliability = np.empty(len(inner_oof_rows), dtype=np.float64)
    fold_audits = []
    for fold in expected:
        train_indices = [i for i, row in enumerate(inner_oof_rows) if int(row["inner_fold"]) != fold]
        score_indices = [i for i, row in enumerate(inner_oof_rows) if int(row["inner_fold"]) == fold]
        train_rows = [inner_oof_rows[i] for i in train_indices]
        score_rows = [inner_oof_rows[i] for i in score_indices]
        train_parents = {str(row["parent_framework_cluster"]) for row in train_rows}
        score_parents = {str(row["parent_framework_cluster"]) for row in score_rows}
        require(train_parents.isdisjoint(score_parents), f"noise_inner_parent_leakage:{fold}")
        model = fit_noise_head(train_rows, hierarchical_weights(train_rows))
        _, reliability = predict_noise(model, score_rows)
        oof_reliability[score_indices] = reliability
        fold_audits.append({
            "inner_fold": fold,
            "fit_candidates": len(train_rows),
            "fit_repeated_candidates": sum(
                str(row["development_reliability_tier"]) in REPEATED_TIERS for row in train_rows
            ),
            "score_candidates": len(score_rows),
            "fit_parent_count": len(train_parents),
            "score_parent_count": len(score_parents),
            "fit_score_parent_overlap": 0,
        })
    require(np.isfinite(oof_reliability).all(), "incomplete_noise_oof")
    final_model = fit_noise_head(inner_oof_rows, hierarchical_weights(inner_oof_rows))
    outer_variance, outer_reliability = predict_noise(final_model, outer_score_rows)
    return oof_reliability, outer_reliability, {
        "schema_version": "pvrig_v2_5_noise_double_crossfit_audit_v1",
        "inner_candidate_count": len(inner_oof_rows),
        "outer_score_candidate_count": len(outer_score_rows),
        "same_row_leakage": False,
        "outer_parent_leakage": False,
        "tier_C_used_as_variance_truth": False,
        "fold_audits": fold_audits,
        "final_noise_model": final_model.audit(),
        "outer_predicted_variance_min": float(outer_variance.min()),
        "outer_predicted_variance_max": float(outer_variance.max()),
    }


@dataclass(frozen=True)
class GBDTConfig:
    max_depth: int = 2
    max_iter: int = 64
    learning_rate: float = 0.05
    min_samples_leaf: int = 64
    l2_regularization: float = 2.0
    random_state: int = 1931
    role: str = "CHALLENGER_ONLY_NOT_PRIMARY"


@dataclass
class GBDTChallenger:
    config: GBDTConfig
    feature_names: tuple[str, ...]
    models: tuple[Any, Any]


def fit_gbdt_challenger(
    rows: Sequence[Mapping[str, Any]], candidate_weights: np.ndarray,
    predicted_reliability: np.ndarray,
    config: GBDTConfig = GBDTConfig(),
) -> GBDTChallenger:
    """Fit a fixed shallow challenger on inner-OOF evidence only."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    validate_predictor_names(GBDT_FEATURE_NAMES)
    reliability = _finite_array(predicted_reliability, ndim=1, context="gbdt_fit_reliability")
    require(reliability.shape == (len(rows),), "gbdt_fit_reliability_shape")
    x = np.column_stack([noise_feature_matrix(rows), reliability])
    y = truth_array(rows)
    weights = normalize_weights(candidate_weights) * len(rows)
    require(config.role == "CHALLENGER_ONLY_NOT_PRIMARY", "gbdt_role_mismatch")
    models = []
    for receptor_index in range(2):
        model = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=config.learning_rate,
            max_iter=config.max_iter,
            max_depth=config.max_depth,
            min_samples_leaf=config.min_samples_leaf,
            l2_regularization=config.l2_regularization,
            random_state=config.random_state + receptor_index,
            early_stopping=False,
        )
        model.fit(x, y[:, receptor_index], sample_weight=weights)
        models.append(model)
    return GBDTChallenger(config=config, feature_names=tuple(GBDT_FEATURE_NAMES), models=tuple(models))


def predict_gbdt_challenger(
    model: GBDTChallenger,
    rows: Sequence[Mapping[str, Any]],
    predicted_reliability: np.ndarray,
) -> np.ndarray:
    require(model.config.role == "CHALLENGER_ONLY_NOT_PRIMARY", "gbdt_not_challenger")
    require(model.feature_names == tuple(GBDT_FEATURE_NAMES), "gbdt_feature_contract_mismatch")
    reliability = _finite_array(predicted_reliability, ndim=1, context="gbdt_score_reliability")
    require(reliability.shape == (len(rows),), "gbdt_score_reliability_shape")
    x = np.column_stack([noise_feature_matrix(rows), reliability])
    result = np.column_stack([estimator.predict(x) for estimator in model.models])
    require(result.shape == (len(rows), 2) and np.isfinite(result).all(), "invalid_gbdt_prediction")
    return result


def run_outer_fold(
    inner_oof_rows: Sequence[Mapping[str, Any]],
    outer_score_rows: Sequence[Mapping[str, Any]],
    *,
    l2_toward_m2: float = 1.0e-3,
    include_gbdt: bool = True,
) -> dict[str, Any]:
    """Fit on inner OOF rows and score untouched outer-parent rows."""
    require(bool(inner_oof_rows) and bool(outer_score_rows), "empty_outer_fold")
    outer_folds = {int(row["outer_fold"]) for row in (*inner_oof_rows, *outer_score_rows)}
    require(len(outer_folds) == 1, "mixed_outer_fold_rows")
    inner_ids = {str(row["candidate_id"]) for row in inner_oof_rows}
    outer_ids = {str(row["candidate_id"]) for row in outer_score_rows}
    require(len(inner_ids) == len(inner_oof_rows), "duplicate_inner_candidate")
    require(len(outer_ids) == len(outer_score_rows), "duplicate_outer_candidate")
    require(inner_ids.isdisjoint(outer_ids), "same_row_base_feature_leakage")
    require(
        {str(row["parent_framework_cluster"]) for row in inner_oof_rows}.isdisjoint(
            {str(row["parent_framework_cluster"]) for row in outer_score_rows}
        ),
        "same_parent_outer_leakage",
    )

    truth = truth_array(inner_oof_rows)
    inner_m2, inner_branches = base_arrays(inner_oof_rows)
    outer_m2, outer_branches = base_arrays(outer_score_rows)
    base_weight = hierarchical_weights(inner_oof_rows)
    primary = fit_convex_residual_stack(
        truth, inner_m2, inner_branches, base_weight, l2_toward_m2=l2_toward_m2
    )
    primary_prediction = predict_convex_residual_stack(primary, outer_m2, outer_branches)

    inner_reliability, outer_reliability, noise_audit = crossfit_noise_for_outer_fold(
        inner_oof_rows, outer_score_rows
    )
    reliability_weight = normalize_weights(base_weight * inner_reliability)
    reliability_model = fit_convex_residual_stack(
        truth, inner_m2, inner_branches, reliability_weight,
        l2_toward_m2=l2_toward_m2,
    )
    reliability_prediction = predict_convex_residual_stack(
        reliability_model, outer_m2, outer_branches
    )

    output: dict[str, Any] = {
        "outer_fold": next(iter(outer_folds)),
        "candidate_ids": [str(row["candidate_id"]) for row in outer_score_rows],
        "primary_prediction_two": primary_prediction,
        "primary_prediction_dual": exact_min(primary_prediction),
        "primary_model": primary,
        "reliability_prediction_two": reliability_prediction,
        "reliability_prediction_dual": exact_min(reliability_prediction),
        "reliability_model": reliability_model,
        "outer_predicted_reliability": outer_reliability,
        "noise_audit": noise_audit,
        "outer_truth_accessed_for_fit": False,
        "same_row_stacking": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if include_gbdt:
        gbdt = fit_gbdt_challenger(inner_oof_rows, base_weight, inner_reliability)
        gbdt_prediction = predict_gbdt_challenger(gbdt, outer_score_rows, outer_reliability)
        output.update({
            "gbdt_prediction_two": gbdt_prediction,
            "gbdt_prediction_dual": exact_min(gbdt_prediction),
            "gbdt_config": asdict(gbdt.config),
        })
    return output


def run_strict_outer_crossfit(
    inner_oof_rows: Sequence[Mapping[str, Any]],
    outer_score_rows: Sequence[Mapping[str, Any]],
    *,
    include_gbdt: bool = True,
) -> dict[str, Any]:
    """Run all five outer folds from already closed inner/outer base evidence."""
    require(bool(inner_oof_rows) and bool(outer_score_rows), "empty_strict_crossfit")
    require({int(row["outer_fold"]) for row in inner_oof_rows} == set(range(5)),
            "strict_inner_outer_fold_closure")
    require({int(row["outer_fold"]) for row in outer_score_rows} == set(range(5)),
            "strict_outer_score_fold_closure")
    candidate_ids = [str(row["candidate_id"]) for row in outer_score_rows]
    require(len(set(candidate_ids)) == len(candidate_ids), "strict_outer_candidate_scored_twice")
    fold_results = []
    output_rows = []
    for outer_fold in range(5):
        inner = [row for row in inner_oof_rows if int(row["outer_fold"]) == outer_fold]
        outer = [row for row in outer_score_rows if int(row["outer_fold"]) == outer_fold]
        result = run_outer_fold(inner, outer, include_gbdt=include_gbdt)
        fold_results.append({
            "outer_fold": outer_fold,
            "primary_model": result["primary_model"].audit(),
            "reliability_model": result["reliability_model"].audit(),
            "noise_audit": result["noise_audit"],
            "gbdt_config": result.get("gbdt_config"),
        })
        for index, candidate in enumerate(result["candidate_ids"]):
            row = {
                "candidate_id": candidate,
                "outer_fold": outer_fold,
                "primary_R8": float(result["primary_prediction_two"][index, 0]),
                "primary_R9": float(result["primary_prediction_two"][index, 1]),
                "primary_Rdual": float(result["primary_prediction_dual"][index]),
                "reliability_R8": float(result["reliability_prediction_two"][index, 0]),
                "reliability_R9": float(result["reliability_prediction_two"][index, 1]),
                "reliability_Rdual": float(result["reliability_prediction_dual"][index]),
                "predicted_reliability": float(result["outer_predicted_reliability"][index]),
            }
            if include_gbdt:
                row.update({
                    "gbdt_R8": float(result["gbdt_prediction_two"][index, 0]),
                    "gbdt_R9": float(result["gbdt_prediction_two"][index, 1]),
                    "gbdt_Rdual": float(result["gbdt_prediction_dual"][index]),
                })
            output_rows.append(row)
    require({row["candidate_id"] for row in output_rows} == set(candidate_ids),
            "strict_outer_candidate_closure")
    return {
        "schema_version": "pvrig_v2_5_strict_outer_crossfit_result_v1",
        "outer_folds": 5,
        "candidate_count": len(output_rows),
        "same_row_stacking": False,
        "outer_truth_accessed_for_fit": False,
        "v4_f_test32_access_count": 0,
        "fold_audits": fold_results,
        "predictions": output_rows,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def read_tsv(path: Path) -> list[dict[str, str]]:
    reject_sealed(path.resolve(), "input_path")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"empty_tsv:{path}")
    return rows


def validate_c2_outer_oof(
    prediction_rows: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
    *,
    c2_model_id: str = "C2_INNER_SELECTED_PCA8_RIDGE",
) -> dict[str, Any]:
    """Bind the existing fold-specific C2 OOF branch to the fixed outer splits."""
    c2_rows = [row for row in prediction_rows if str(row.get("model_id")) == c2_model_id]
    require(len(c2_rows) == len(labels), "c2_candidate_count_mismatch")
    seen: set[str] = set()
    fold_counts: dict[int, int] = defaultdict(int)
    fold_alphas: dict[int, set[float]] = defaultdict(set)
    for row in c2_rows:
        candidate = str(row["candidate_id"])
        reject_sealed(candidate, "c2_candidate")
        require(candidate in labels, f"unknown_c2_candidate:{candidate}")
        require(candidate not in seen, f"duplicate_c2_candidate:{candidate}")
        seen.add(candidate)
        label = labels[candidate]
        fold = int(row["outer_fold"])
        require(fold == int(label["outer_fold"]), f"c2_outer_fold_mismatch:{candidate}")
        require(str(row["parent_framework_cluster"]) == str(label["parent_framework_cluster"]),
                f"c2_parent_mismatch:{candidate}")
        require(str(row["teacher_source"]) == str(label["teacher_source"]),
                f"c2_source_mismatch:{candidate}")
        pred8, pred9 = _row_float(row, "pred_R8"), _row_float(row, "pred_R9")
        require(abs(_row_float(row, "pred_Rdual") - min(pred8, pred9)) <= 1e-12,
                f"c2_exact_min_violation:{candidate}")
        fold_counts[fold] += 1
        fold_alphas[fold].add(_row_float(row, "selected_c2_alpha"))
    require(seen == set(labels), "c2_candidate_closure")
    require(set(fold_counts) == set(range(5)), "c2_fold_closure")
    require(all(len(values) == 1 for values in fold_alphas.values()), "c2_alpha_not_fold_specific")
    return {
        "schema_version": "pvrig_v2_5_c2_fold_specific_oof_closure_v1",
        "candidate_count": len(seen),
        "outer_fold_counts": {str(k): v for k, v in sorted(fold_counts.items())},
        "selected_alpha_by_outer_fold": {
            str(k): next(iter(values)) for k, values in sorted(fold_alphas.items())
        },
        "candidate_scored_exactly_once": True,
        "outer_fold_matches_frozen_label": True,
        "exact_min_violations": 0,
        "v4_f_test32_access_count": 0,
    }


def attach_existing_c2_outer_oof(
    outer_base_rows: Sequence[Mapping[str, Any]],
    c2_prediction_rows: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join the independently validated existing outer C2 OOF branch by ID/fold."""
    validate_c2_outer_oof(c2_prediction_rows, labels)
    c2_index = {
        str(row["candidate_id"]): row for row in c2_prediction_rows
        if str(row.get("model_id")) == "C2_INNER_SELECTED_PCA8_RIDGE"
    }
    require(len(outer_base_rows) == len(c2_index), "outer_base_c2_count_mismatch")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in outer_base_rows:
        candidate = str(row["candidate_id"])
        require(candidate in c2_index and candidate not in seen, f"outer_base_c2_join:{candidate}")
        seen.add(candidate)
        c2 = c2_index[candidate]
        require(int(row["outer_fold"]) == int(c2["outer_fold"]), f"outer_base_c2_fold:{candidate}")
        merged = dict(row)
        merged["c2_R8"] = _row_float(c2, "pred_R8")
        merged["c2_R9"] = _row_float(c2, "pred_R9")
        output.append(merged)
    require(seen == set(c2_index), "outer_base_c2_join_closure")
    return output


def validate_whole_parent_split_contract(
    label_rows: Sequence[Mapping[str, Any]],
    outer_rows: Sequence[Mapping[str, Any]],
    inner_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate five outer and 25 inner whole-parent partitions."""
    labels = {str(row["candidate_id"]): row for row in label_rows}
    require(len(labels) == len(label_rows), "duplicate_label_candidate")
    all_candidates = set(labels)
    all_parents = {str(row["parent_framework_cluster"]) for row in label_rows}
    require(len(all_parents) > 5, "insufficient_parent_count")
    outer_contract: dict[int, dict[str, set[str]]] = {}
    for outer_fold in range(5):
        rows = [row for row in outer_rows if int(row["outer_fold"]) == outer_fold]
        require({str(row["candidate_id"]) for row in rows} == all_candidates,
                f"outer_candidate_closure:{outer_fold}")
        by_parent: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            candidate = str(row["candidate_id"])
            require(str(row["parent_framework_cluster"]) == str(labels[candidate]["parent_framework_cluster"]),
                    f"outer_parent_identity:{candidate}")
            by_parent[str(row["parent_framework_cluster"])].add(str(row["candidate_role"]))
        require(all(len(roles) == 1 for roles in by_parent.values()), f"outer_parent_split:{outer_fold}")
        train = {parent for parent, roles in by_parent.items() if roles == {"train"}}
        score = {parent for parent, roles in by_parent.items() if roles == {"score"}}
        require(train and score and train.isdisjoint(score) and train | score == all_parents,
                f"outer_parent_partition:{outer_fold}")
        outer_contract[outer_fold] = {"train": train, "score": score}
    for candidate, label in labels.items():
        score_folds = [
            int(row["outer_fold"]) for row in outer_rows
            if str(row["candidate_id"]) == candidate and str(row["candidate_role"]) == "score"
        ]
        require(score_folds == [int(label["outer_fold"])], f"outer_score_once:{candidate}")

    for outer_fold in range(5):
        expected_parents = outer_contract[outer_fold]["train"]
        expected_candidates = {
            candidate for candidate, row in labels.items()
            if str(row["parent_framework_cluster"]) in expected_parents
        }
        scored: set[str] = set()
        score_parent_union: set[str] = set()
        for inner_fold in range(5):
            rows = [
                row for row in inner_rows
                if int(row["outer_fold"]) == outer_fold and int(row["inner_fold"]) == inner_fold
            ]
            require({str(row["candidate_id"]) for row in rows} == expected_candidates,
                    f"inner_candidate_closure:{outer_fold}:{inner_fold}")
            by_parent: dict[str, set[str]] = defaultdict(set)
            for row in rows:
                by_parent[str(row["parent_framework_cluster"])].add(str(row["candidate_role"]))
            require(all(len(roles) == 1 for roles in by_parent.values()),
                    f"inner_parent_split:{outer_fold}:{inner_fold}")
            train = {parent for parent, roles in by_parent.items() if roles == {"train"}}
            score = {parent for parent, roles in by_parent.items() if roles == {"score"}}
            require(train and score and train.isdisjoint(score) and train | score == expected_parents,
                    f"inner_parent_partition:{outer_fold}:{inner_fold}")
            require(score_parent_union.isdisjoint(score), f"inner_score_parent_repeated:{outer_fold}:{inner_fold}")
            score_parent_union |= score
            fold_scored = {
                str(row["candidate_id"]) for row in rows if str(row["candidate_role"]) == "score"
            }
            require(scored.isdisjoint(fold_scored), f"inner_candidate_scored_twice:{outer_fold}")
            scored |= fold_scored
        require(score_parent_union == expected_parents, f"inner_score_parent_closure:{outer_fold}")
        require(scored == expected_candidates, f"inner_oof_candidate_closure:{outer_fold}")
    return {
        "schema_version": "pvrig_v2_5_whole_parent_nested_split_audit_v1",
        "candidate_count": len(labels),
        "parent_count": len(all_parents),
        "outer_folds": 5,
        "inner_folds_per_outer": 5,
        "same_parent_leakage": False,
        "each_candidate_outer_score_once": True,
        "each_outer_train_candidate_inner_score_once": True,
        "v4_f_test32_access_count": 0,
    }
