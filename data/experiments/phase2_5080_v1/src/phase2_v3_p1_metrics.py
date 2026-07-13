#!/usr/bin/env python3
"""Cluster-aware ranking and geometry metrics for formal V3-P1 evaluation."""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np


def _finite_vector(values: Sequence[float], name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise ValueError(f"{name} must be a non-empty finite one-dimensional vector")
    return array


def _ranking_inputs(
    relevance: Sequence[int | float], scores: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    rel = _finite_vector(relevance, "relevance")
    score = _finite_vector(scores, "scores")
    if len(rel) != len(score):
        raise ValueError("relevance and scores must have equal length")
    if np.any(rel < 0):
        raise ValueError("relevance must be non-negative")
    return rel, score


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def spearman_correlation(values: Sequence[float], predictions: Sequence[float]) -> float:
    actual = _finite_vector(values, "values")
    predicted = _finite_vector(predictions, "predictions")
    if len(actual) != len(predicted):
        raise ValueError("values and predictions must have equal length")
    if len(actual) < 2:
        return 0.0
    actual_rank = _rankdata(actual)
    predicted_rank = _rankdata(predicted)
    if np.std(actual_rank) == 0.0 or np.std(predicted_rank) == 0.0:
        return 0.0
    return float(np.corrcoef(actual_rank, predicted_rank)[0, 1])


def recall_at_fraction(
    relevance: Sequence[int | float],
    scores: Sequence[float],
    fraction: float = 0.20,
    positive_threshold: float = 3.0,
) -> dict[str, float | int]:
    rel, score = _ranking_inputs(relevance, scores)
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be in (0, 1]")
    positive = rel >= positive_threshold
    positive_count = int(positive.sum())
    count = max(1, int(math.ceil(len(rel) * fraction)))
    order = np.argsort(-score, kind="mergesort")[:count]
    found = int(positive[order].sum())
    return {
        "fraction": float(fraction),
        "top_count": count,
        "positive_threshold": float(positive_threshold),
        "positive_count": positive_count,
        "positive_found": found,
        "recall": float(found / positive_count) if positive_count else 0.0,
    }


def enrichment_factor_at_fraction(
    relevance: Sequence[int | float],
    scores: Sequence[float],
    fraction: float = 0.10,
    positive_threshold: float = 3.0,
) -> dict[str, float | int]:
    rel, score = _ranking_inputs(relevance, scores)
    result = recall_at_fraction(rel, score, fraction, positive_threshold)
    prevalence = float(np.mean(rel >= positive_threshold))
    selected_prevalence = float(result["positive_found"]) / int(result["top_count"])
    return {
        **result,
        "prevalence": prevalence,
        "selected_prevalence": selected_prevalence,
        "enrichment_factor": float(selected_prevalence / prevalence) if prevalence else 0.0,
    }


def ndcg(
    relevance: Sequence[int | float], scores: Sequence[float], k: int | None = 100
) -> float:
    rel, score = _ranking_inputs(relevance, scores)
    if k is None:
        count = len(rel)
    else:
        if k <= 0:
            raise ValueError("k must be positive or None")
        count = min(int(k), len(rel))
    order = np.argsort(-score, kind="mergesort")
    ideal = np.argsort(-rel, kind="mergesort")[:count]
    discounts = np.log2(np.arange(count, dtype=np.float64) + 2.0)
    gains = np.expm1(rel * math.log(2.0))
    actual_dcg = 0.0
    start = 0
    while start < count:
        end = start + 1
        while end < len(order) and score[order[end]] == score[order[start]]:
            end += 1
        clipped_end = min(end, count)
        # A tied score provides no ordering information, so use its expected DCG.
        actual_dcg += float(
            np.mean(gains[order[start:end]])
            * np.sum(1.0 / discounts[start:clipped_end])
        )
        start = end
    ideal_dcg = float(np.sum(np.expm1(rel[ideal] * math.log(2.0)) / discounts))
    return actual_dcg / ideal_dcg if ideal_dcg else 0.0


def ordinal_ranking_metrics(
    relevance: Sequence[int | float], scores: Sequence[float], ndcg_k: int = 100
) -> dict[str, Any]:
    rel, score = _ranking_inputs(relevance, scores)
    recall = recall_at_fraction(rel, score, 0.20, 3.0)
    enrichment = enrichment_factor_at_fraction(rel, score, 0.10, 3.0)
    return {
        "row_count": int(len(rel)),
        "g1_g2_count": int(np.sum(rel >= 3.0)),
        "g1_g2_recall_at_20_percent": recall["recall"],
        "top_20_percent_count": recall["top_count"],
        "g1_g2_found_at_20_percent": recall["positive_found"],
        "g1_g2_ef_at_10_percent": enrichment["enrichment_factor"],
        "top_10_percent_count": enrichment["top_count"],
        "g1_g2_found_at_10_percent": enrichment["positive_found"],
        "ordinal_ndcg_at_100": ndcg(rel, score, ndcg_k),
        "ordinal_ndcg_effective_k": min(ndcg_k, len(rel)),
        "relevance_spearman": spearman_correlation(rel, score),
    }


def geometry_metrics(
    true_by_field: Mapping[str, Sequence[float]],
    predicted_by_field: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    if not true_by_field or set(true_by_field) != set(predicted_by_field):
        raise ValueError("true and predicted geometry fields must be the same non-empty set")
    per_field: dict[str, dict[str, float]] = {}
    lengths: set[int] = set()
    for field in sorted(true_by_field):
        actual = _finite_vector(true_by_field[field], f"true_{field}")
        predicted = _finite_vector(predicted_by_field[field], f"predicted_{field}")
        if len(actual) != len(predicted):
            raise ValueError(f"Geometry length mismatch for {field}")
        lengths.add(len(actual))
        per_field[field] = {
            "mae": float(np.mean(np.abs(actual - predicted))),
            "spearman": spearman_correlation(actual, predicted),
        }
    if len(lengths) != 1:
        raise ValueError("Geometry fields have inconsistent row counts")
    return {
        "row_count": lengths.pop(),
        "field_count": len(per_field),
        "macro_field_mae": float(np.mean([value["mae"] for value in per_field.values()])),
        "macro_field_spearman": float(
            np.mean([value["spearman"] for value in per_field.values()])
        ),
        "per_field": per_field,
    }


def paired_parent_cluster_bootstrap(
    relevance: Sequence[int | float],
    candidate_scores: Sequence[float],
    baseline_scores: Sequence[float],
    parent_clusters: Sequence[str],
    metric: Callable[[np.ndarray, np.ndarray], float] = ndcg,
    replicates: int = 2000,
    seed: int = 20260713,
) -> dict[str, Any]:
    rel, candidate = _ranking_inputs(relevance, candidate_scores)
    _, baseline = _ranking_inputs(relevance, baseline_scores)
    clusters = np.asarray(parent_clusters, dtype=str)
    if len(clusters) != len(rel) or not np.all(clusters != ""):
        raise ValueError("parent_clusters must be non-empty and match relevance")
    if replicates <= 0:
        raise ValueError("replicates must be positive")
    unique = np.asarray(sorted(set(clusters)), dtype=str)
    groups = [np.flatnonzero(clusters == cluster) for cluster in unique]
    observed = float(metric(rel, candidate) - metric(rel, baseline))
    rng = np.random.default_rng(seed)
    deltas = np.empty(replicates, dtype=np.float64)
    for index in range(replicates):
        sampled = rng.integers(0, len(groups), size=len(groups))
        rows = np.concatenate([groups[group_index] for group_index in sampled])
        deltas[index] = metric(rel[rows], candidate[rows]) - metric(rel[rows], baseline[rows])
    return {
        "unit": "parent_framework_cluster",
        "cluster_count": int(len(unique)),
        "replicates": int(replicates),
        "seed": int(seed),
        "observed_delta": observed,
        "ci95_lower": float(np.quantile(deltas, 0.025)),
        "ci95_upper": float(np.quantile(deltas, 0.975)),
        "probability_delta_le_zero": float(np.mean(deltas <= 0.0)),
    }


def paired_parent_cluster_permutation(
    relevance: Sequence[int | float],
    candidate_scores: Sequence[float],
    baseline_scores: Sequence[float],
    parent_clusters: Sequence[str],
    metric: Callable[[np.ndarray, np.ndarray], float] = ndcg,
    replicates: int = 2000,
    seed: int = 20260714,
) -> dict[str, Any]:
    rel, candidate = _ranking_inputs(relevance, candidate_scores)
    _, baseline = _ranking_inputs(relevance, baseline_scores)
    clusters = np.asarray(parent_clusters, dtype=str)
    if len(clusters) != len(rel) or not np.all(clusters != ""):
        raise ValueError("parent_clusters must be non-empty and match relevance")
    if replicates <= 0:
        raise ValueError("replicates must be positive")
    unique = sorted(set(clusters))
    observed = float(metric(rel, candidate) - metric(rel, baseline))
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(replicates):
        permuted_candidate = candidate.copy()
        permuted_baseline = baseline.copy()
        for cluster in unique:
            if rng.integers(0, 2):
                mask = clusters == cluster
                permuted_candidate[mask], permuted_baseline[mask] = (
                    baseline[mask],
                    candidate[mask],
                )
        delta = float(metric(rel, permuted_candidate) - metric(rel, permuted_baseline))
        extreme += abs(delta) >= abs(observed) - 1e-15
    return {
        "unit": "parent_framework_cluster",
        "cluster_count": len(unique),
        "replicates": int(replicates),
        "seed": int(seed),
        "observed_delta": observed,
        "two_sided_p_value": float((extreme + 1) / (replicates + 1)),
    }
