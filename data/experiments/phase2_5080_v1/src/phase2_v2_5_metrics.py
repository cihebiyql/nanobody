#!/usr/bin/env python3
"""Phase 2 V2.5 ranking metrics and statistical utilities.

The helpers in this module are intentionally dependency-light and operate on
assay-comparable groups. They never mix constructed/pose proxy evidence into the
experimental primary metric.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GroupRankingMetrics:
    group_id: str
    pairwise_preference_accuracy: float | None
    comparable_pair_count: int
    ndcg_all: float | None
    mrr: float | None
    hit_at_1: float | None
    random_pairwise_preference_accuracy: float | None
    random_ndcg_all: float | None
    random_mrr: float | None
    random_hit_at_1: float | None
    unique_best: bool
    item_count: int


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "null", "."} else text


def truth_to_higher_is_better(values: Sequence[Any], direction: str = "higher_is_better") -> np.ndarray:
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    normalized = clean(direction).lower()
    lower_tokens = {"lower_is_better", "lower", "min", "smaller", "kd_lower_is_better", "ic50_lower_is_better", "ec50_lower_is_better"}
    higher_tokens = {"higher_is_better", "higher", "max", "larger", "-log10", "delta_positive_is_better"}
    if normalized in lower_tokens:
        return -arr
    if normalized in higher_tokens or not normalized:
        return arr
    raise ValueError(f"Unrecognized label_direction: {direction!r}")


def _ambiguous_mask(frame: pd.DataFrame, ambiguous_col: str | None) -> np.ndarray:
    if ambiguous_col and ambiguous_col in frame.columns:
        return frame[ambiguous_col].astype(str).str.lower().isin({"1", "true", "yes", "y", "ambiguous", "tie"}).to_numpy()
    return np.zeros(len(frame), dtype=bool)


def pairwise_preference_accuracy(
    frame: pd.DataFrame,
    truth_col: str = "label_value",
    score_col: str = "score",
    direction_col: str | None = "label_direction",
    ambiguous_col: str | None = "ambiguous_tie",
    tie_tolerance: float = 0.0,
) -> tuple[float | None, int]:
    """Return pairwise preference accuracy with truth ties excluded.

    Only pairs with a clear assay-label ordering are counted. Prediction ties on
    counted pairs receive 0.5 credit; ambiguous truth rows are removed before pair
    construction.
    """
    if len(frame) < 2:
        return None, 0
    usable = frame.loc[~_ambiguous_mask(frame, ambiguous_col)].copy()
    if len(usable) < 2:
        return None, 0
    if direction_col and direction_col in usable.columns:
        directions = {clean(v).lower() for v in usable[direction_col] if clean(v)}
        if len(directions) > 1:
            raise ValueError("pairwise metric requires one label_direction per assay-comparable group")
        direction = next(iter(directions), "higher_is_better")
    else:
        direction = "higher_is_better"
    truth = truth_to_higher_is_better(usable[truth_col], direction)
    scores = pd.to_numeric(usable[score_col], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(truth) & np.isfinite(scores)
    truth = truth[valid]
    scores = scores[valid]
    correct = 0.0
    total = 0
    for i in range(len(truth)):
        for j in range(i + 1, len(truth)):
            delta_truth = truth[i] - truth[j]
            if abs(delta_truth) <= tie_tolerance:
                continue
            delta_score = scores[i] - scores[j]
            total += 1
            if delta_score == 0:
                correct += 0.5
            elif math.copysign(1.0, delta_score) == math.copysign(1.0, delta_truth):
                correct += 1.0
    return (correct / total if total else None), total


def _dcg(relevance: np.ndarray) -> float:
    if len(relevance) == 0:
        return float("nan")
    discounts = 1.0 / np.log2(np.arange(2, len(relevance) + 2, dtype=float))
    return float(np.sum(relevance * discounts))


def ndcg_all(labels_higher_better: Sequence[float], scores: Sequence[float]) -> float | None:
    labels = np.asarray(labels_higher_better, dtype=float)
    pred = np.asarray(scores, dtype=float)
    valid = np.isfinite(labels) & np.isfinite(pred)
    labels = labels[valid]
    pred = pred[valid]
    if len(labels) < 2:
        return None
    min_label = float(np.min(labels))
    gains = labels - min_label
    if float(np.max(gains)) == 0.0:
        return None
    order = np.argsort(-pred, kind="mergesort")
    ideal = np.argsort(-gains, kind="mergesort")
    ideal_dcg = _dcg(gains[ideal])
    return float(_dcg(gains[order]) / ideal_dcg) if ideal_dcg > 0 else None


def reciprocal_rank_and_hit(labels_higher_better: Sequence[float], scores: Sequence[float], tie_tolerance: float = 0.0) -> tuple[float | None, float | None, bool]:
    labels = np.asarray(labels_higher_better, dtype=float)
    pred = np.asarray(scores, dtype=float)
    valid = np.isfinite(labels) & np.isfinite(pred)
    labels = labels[valid]
    pred = pred[valid]
    if len(labels) < 2:
        return None, None, False
    best = float(np.max(labels))
    is_best = np.abs(labels - best) <= tie_tolerance
    if int(np.sum(is_best)) != 1:
        return None, None, False
    best_index = int(np.where(is_best)[0][0])
    order = list(np.argsort(-pred, kind="mergesort"))
    rank = order.index(best_index) + 1
    return 1.0 / rank, 1.0 if rank == 1 else 0.0, True


def exact_random_expectations(labels_higher_better: Sequence[float], tie_tolerance: float = 0.0) -> dict[str, float | None]:
    labels = np.asarray(labels_higher_better, dtype=float)
    labels = labels[np.isfinite(labels)]
    n = len(labels)
    if n < 2:
        return {"pairwise_preference_accuracy": None, "ndcg_all": None, "mrr": None, "hit_at_1": None}
    comparable = sum(1 for i in range(n) for j in range(i + 1, n) if abs(float(labels[i] - labels[j])) > tie_tolerance)
    pairwise = 0.5 if comparable else None
    min_label = float(np.min(labels))
    gains = labels - min_label
    if float(np.max(gains)) == 0.0:
        random_ndcg = None
    else:
        discounts = 1.0 / np.log2(np.arange(2, n + 2, dtype=float))
        expected_dcg = float(np.sum(gains) * np.mean(discounts))
        ideal_dcg = _dcg(np.sort(gains)[::-1])
        random_ndcg = expected_dcg / ideal_dcg if ideal_dcg > 0 else None
    best = float(np.max(labels))
    unique_best = int(np.sum(np.abs(labels - best) <= tie_tolerance)) == 1
    harmonic = float(np.sum(1.0 / np.arange(1, n + 1, dtype=float)))
    return {
        "pairwise_preference_accuracy": pairwise,
        "ndcg_all": random_ndcg,
        "mrr": harmonic / n if unique_best else None,
        "hit_at_1": 1.0 / n if unique_best else None,
    }


def compute_group_ranking_metrics(
    frame: pd.DataFrame,
    group_col: str = "group_id",
    truth_col: str = "label_value",
    score_col: str = "score",
    direction_col: str | None = "label_direction",
    ambiguous_col: str | None = "ambiguous_tie",
    tie_tolerance: float = 0.0,
) -> pd.DataFrame:
    rows: list[GroupRankingMetrics] = []
    for group_id, group in frame.groupby(group_col, dropna=False, sort=True):
        usable = group.loc[~_ambiguous_mask(group, ambiguous_col)].copy()
        if direction_col and direction_col in usable.columns:
            directions = {clean(v).lower() for v in usable[direction_col] if clean(v)}
            if len(directions) > 1:
                raise ValueError(f"Group {group_id!r} has mixed label_direction values")
            direction = next(iter(directions), "higher_is_better")
        else:
            direction = "higher_is_better"
        truth = truth_to_higher_is_better(usable[truth_col], direction)
        scores = pd.to_numeric(usable[score_col], errors="coerce").to_numpy(dtype=float)
        pairwise, pair_count = pairwise_preference_accuracy(usable, truth_col, score_col, direction_col, ambiguous_col, tie_tolerance)
        ndcg = ndcg_all(truth, scores)
        mrr, hit1, unique_best = reciprocal_rank_and_hit(truth, scores, tie_tolerance)
        randoms = exact_random_expectations(truth, tie_tolerance)
        rows.append(GroupRankingMetrics(
            group_id=str(group_id),
            pairwise_preference_accuracy=pairwise,
            comparable_pair_count=pair_count,
            ndcg_all=ndcg,
            mrr=mrr,
            hit_at_1=hit1,
            random_pairwise_preference_accuracy=randoms["pairwise_preference_accuracy"],
            random_ndcg_all=randoms["ndcg_all"],
            random_mrr=randoms["mrr"],
            random_hit_at_1=randoms["hit_at_1"],
            unique_best=unique_best,
            item_count=int(len(usable)),
        ))
    return pd.DataFrame([row.__dict__ for row in rows])


def macro_summary(group_metrics: pd.DataFrame) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    mapping = {
        "macro_group_pairwise_preference_accuracy": "pairwise_preference_accuracy",
        "macro_group_ndcg_all": "ndcg_all",
        "group_mrr": "mrr",
        "hit_at_1": "hit_at_1",
        "random_macro_group_pairwise_preference_accuracy": "random_pairwise_preference_accuracy",
        "random_macro_group_ndcg_all": "random_ndcg_all",
        "random_group_mrr": "random_mrr",
        "random_hit_at_1": "random_hit_at_1",
    }
    for name, column in mapping.items():
        values = pd.to_numeric(group_metrics.get(column), errors="coerce")
        values = values[np.isfinite(values)]
        out[name] = float(values.mean()) if len(values) else None
    out["rank_group_count"] = int(len(group_metrics))
    out["comparable_pair_count"] = int(pd.to_numeric(group_metrics.get("comparable_pair_count"), errors="coerce").fillna(0).sum())
    return out


def bootstrap_metric_ci(
    group_values: pd.DataFrame,
    metric_col: str,
    unit_col: str = "group_id",
    strata_cols: Sequence[str] | None = None,
    n: int = 5000,
    seed: int = 0,
) -> dict[str, Any]:
    data = group_values[[unit_col, metric_col] + list(strata_cols or [])].copy()
    data[metric_col] = pd.to_numeric(data[metric_col], errors="coerce")
    data = data[np.isfinite(data[metric_col])]
    if data.empty:
        return {"point": None, "ci_low": None, "ci_high": None, "n_bootstrap": n, "unit_count": 0, "low_power_stratum": True}
    point = float(data[metric_col].mean())
    rng = np.random.default_rng(seed)
    estimates = np.empty(n, dtype=float)
    if strata_cols:
        grouped = [part[metric_col].to_numpy(dtype=float) for _, part in data.groupby(list(strata_cols), dropna=False)]
        low_power = any(len(part) < 3 for part in grouped)
        for i in range(n):
            samples = [rng.choice(part, size=len(part), replace=True) for part in grouped]
            estimates[i] = float(np.mean(np.concatenate(samples)))
    else:
        values = data[metric_col].to_numpy(dtype=float)
        low_power = len(values) < 3
        for i in range(n):
            estimates[i] = float(np.mean(rng.choice(values, size=len(values), replace=True)))
    return {
        "point": point,
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "n_bootstrap": int(n),
        "unit_count": int(data[unit_col].nunique()),
        "low_power_stratum": bool(low_power),
    }


def permutation_test_group_labels(
    frame: pd.DataFrame,
    statistic_fn: Callable[[pd.DataFrame], float | None],
    group_col: str = "group_id",
    label_col: str = "label_value",
    n: int = 5000,
    seed: int = 0,
) -> dict[str, Any]:
    observed = statistic_fn(frame.copy())
    if observed is None or not math.isfinite(float(observed)):
        return {"observed": observed, "p_two_sided": None, "n_permutation": n}
    rng = np.random.default_rng(seed)
    null = np.empty(n, dtype=float)
    groups = list(frame.groupby(group_col, sort=False, dropna=False).indices.items())
    for i in range(n):
        permuted = frame.copy()
        for _, idx in groups:
            values = permuted.loc[idx, label_col].to_numpy(copy=True)
            permuted.loc[idx, label_col] = rng.permutation(values)
        value = statistic_fn(permuted)
        null[i] = np.nan if value is None else float(value)
    null = null[np.isfinite(null)]
    if len(null) == 0:
        return {"observed": float(observed), "p_two_sided": None, "n_permutation": n}
    center = float(np.mean(null))
    p = (1.0 + float(np.sum(np.abs(null - center) >= abs(float(observed) - center)))) / (len(null) + 1.0)
    return {"observed": float(observed), "null_mean": center, "p_two_sided": p, "n_permutation": int(n)}
