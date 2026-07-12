#!/usr/bin/env python3
"""Dependency-light binary ranking metrics and V3 formal gate utilities."""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np


def _arrays(labels: Sequence[int], scores: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(labels, dtype=np.int8)
    s = np.asarray(scores, dtype=np.float64)
    if y.ndim != 1 or s.ndim != 1 or len(y) != len(s) or not len(y):
        raise ValueError("Labels and scores must be non-empty one-dimensional arrays of equal length")
    if not set(np.unique(y)).issubset({0, 1}) or not np.isfinite(s).all():
        raise ValueError("Binary labels and finite scores are required")
    return y, s


def average_precision(labels: Sequence[int], scores: Sequence[float]) -> float:
    y, s = _arrays(labels, scores)
    positives = int(y.sum())
    if positives == 0:
        return 0.0
    order = np.argsort(-s, kind="mergesort")
    y, s = y[order], s[order]
    true_positive = 0
    false_positive = 0
    value = 0.0
    start = 0
    while start < len(y):
        end = start + 1
        while end < len(y) and s[end] == s[start]:
            end += 1
        group_positive = int(y[start:end].sum())
        true_positive += group_positive
        false_positive += (end - start) - group_positive
        if group_positive:
            precision = true_positive / float(true_positive + false_positive)
            value += (group_positive / positives) * precision
        start = end
    return float(value)


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    y, s = _arrays(labels, scores)
    positives = int(y.sum())
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    y, s = y[order], s[order]
    negatives_before = 0
    concordant = 0.0
    start = 0
    while start < len(y):
        end = start + 1
        while end < len(y) and s[end] == s[start]:
            end += 1
        group_positive = int(y[start:end].sum())
        group_negative = (end - start) - group_positive
        concordant += group_positive * negatives_before + 0.5 * group_positive * group_negative
        negatives_before += group_negative
        start = end
    return float(concordant / (positives * negatives))


def enrichment_and_recall_at_fraction(
    labels: Sequence[int], scores: Sequence[float], fraction: float = 0.01
) -> tuple[float | None, float | None, int]:
    y, s = _arrays(labels, scores)
    positives = int(y.sum())
    if positives == 0:
        return None, None, 0
    count = max(1, int(math.ceil(len(y) * fraction)))
    order = np.argsort(-s, kind="mergesort")[:count]
    found = int(y[order].sum())
    recall = found / positives
    expected = positives / len(y)
    enrichment = (found / count) / expected if expected else None
    return float(enrichment) if enrichment is not None else None, float(recall), count


def binary_ranking_metrics(labels: Sequence[int], scores: Sequence[float]) -> dict[str, Any]:
    y, s = _arrays(labels, scores)
    ef1, recall1, top_count = enrichment_and_recall_at_fraction(y, s, 0.01)
    probabilities = np.clip(s, 0.0, 1.0)
    return {
        "row_count": int(len(y)),
        "positive_count": int(y.sum()),
        "negative_count": int(len(y) - y.sum()),
        "prevalence": float(y.mean()),
        "average_precision": average_precision(y, s),
        "auroc": roc_auc(y, s),
        "ef1_percent": ef1,
        "recall_at_1_percent": recall1,
        "top_1_percent_count": top_count,
        "brier_score": float(np.mean((probabilities - y) ** 2)),
    }


def macro_target_average_precision(
    labels: Sequence[int], scores: Sequence[float], target_ids: Sequence[str]
) -> tuple[float, dict[str, float]]:
    y, s = _arrays(labels, scores)
    targets = np.asarray(target_ids, dtype=object)
    if len(targets) != len(y):
        raise ValueError("target_ids length mismatch")
    values = {}
    for target in sorted(set(str(item) for item in targets)):
        mask = targets.astype(str) == target
        values[target] = average_precision(y[mask], s[mask])
    return float(np.mean(list(values.values()))), values


def paired_bootstrap_ap_delta(
    labels: Sequence[int],
    model_scores: Sequence[float],
    baseline_scores: Sequence[float],
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    y, model = _arrays(labels, model_scores)
    _, baseline = _arrays(labels, baseline_scores)
    observed = average_precision(y, model) - average_precision(y, baseline)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(replicates):
        index = rng.integers(0, len(y), len(y))
        sampled = y[index]
        if sampled.sum() == 0:
            continue
        deltas.append(average_precision(sampled, model[index]) - average_precision(sampled, baseline[index]))
    if not deltas:
        raise ValueError("No evaluable bootstrap samples")
    return {
        "observed_delta": float(observed),
        "replicates_requested": replicates,
        "replicates_evaluable": len(deltas),
        "ci95_lower": float(np.quantile(deltas, 0.025)),
        "ci95_upper": float(np.quantile(deltas, 0.975)),
        "bootstrap_seed": seed,
    }


def paired_permutation_ap_test(
    labels: Sequence[int],
    model_scores: Sequence[float],
    baseline_scores: Sequence[float],
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    y, model = _arrays(labels, model_scores)
    _, baseline = _arrays(labels, baseline_scores)
    observed = average_precision(y, model) - average_precision(y, baseline)
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(replicates):
        swap = rng.integers(0, 2, len(y), dtype=np.int8).astype(bool)
        perm_model = np.where(swap, baseline, model)
        perm_baseline = np.where(swap, model, baseline)
        delta = average_precision(y, perm_model) - average_precision(y, perm_baseline)
        extreme += abs(delta) >= abs(observed) - 1e-15
    return {
        "observed_delta": float(observed),
        "replicates": replicates,
        "two_sided_p_value": float((extreme + 1) / (replicates + 1)),
        "permutation_seed": seed,
    }


def formal_gate_decision(
    seed_deltas: Sequence[float],
    bootstrap: dict[str, Any],
    permutation: dict[str, Any],
    null_control_passed: bool,
    target_shuffle_passed: bool,
) -> dict[str, Any]:
    checks = {
        "ensemble_delta_positive": float(bootstrap["observed_delta"]) > 0.0,
        "all_seed_deltas_positive": bool(seed_deltas) and all(float(value) > 0.0 for value in seed_deltas),
        "bootstrap_ci_lower_gt_zero": float(bootstrap["ci95_lower"]) > 0.0,
        "permutation_p_lt_0_05": float(permutation["two_sided_p_value"]) < 0.05,
        "null_control_did_not_pass": not null_control_passed,
        "target_shuffle_did_not_pass": not target_shuffle_passed,
    }
    return {
        "status": "PASS_IMPROVED_PRIOR" if all(checks.values()) else "FAIL_FALLBACK_TO_BASELINE",
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }
