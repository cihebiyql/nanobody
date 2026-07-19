#!/usr/bin/env python3
"""Open-inner ensemble audit for M2, B and F0.

This script is intentionally limited to outer=0, inner=0 open-development
rows.  It does not read the outer score partition or sealed V4-F/test32.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr


ROOT = Path(__file__).resolve().parents[2]
REPORT = Path(__file__).resolve().parent
SUPERVISED = ROOT / (
    "experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/"
    "v2_4_fs_stack_prototype_v1_20260718/data_contract/materialized_v1/"
    "v6_supervised1507_v2_4.tsv"
)
INNER_MANIFEST = ROOT / (
    "experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/"
    "v2_4_fs_stack_prototype_v1_20260718/split_contract/prepared/"
    "whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4/"
    "inner_nested_oof_manifest.tsv"
)
PREDICTION_INPUTS = {
    "B": REPORT / "inputs/B_seed43.tsv",
    "F0_seed43": REPORT / "inputs/F0_seed43.tsv",
    "F0_seed97": REPORT / "inputs/F0_seed97.tsv",
    "F0_seed193": REPORT / "inputs/F0_seed193.tsv",
}
COLLECTOR_RESULT = REPORT / "inputs/INNER_PILOT_RESULT.json"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def m2_weights(candidate_ids: list[str], rows: dict[str, dict[str, str]]) -> np.ndarray:
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, candidate_id in enumerate(candidate_ids):
        row = rows[candidate_id]
        groups[row["teacher_source"]][row["parent_framework_cluster"]].append(index)
    if len(groups) != 2:
        raise ValueError(f"M2 expected two sources, observed {sorted(groups)}")
    weights = np.zeros(len(candidate_ids), dtype=np.float64)
    for parents in groups.values():
        for indices in parents.values():
            weights[indices] = 0.5 / len(parents) / len(indices)
    if not np.isclose(weights.sum(), 1.0, atol=1e-14, rtol=0.0):
        raise ValueError("M2 weights do not sum to one")
    return weights


def fit_m2(
    train_x: np.ndarray,
    train_y: np.ndarray,
    score_x: np.ndarray,
    weights: np.ndarray,
    alpha: float = 10.0,
) -> np.ndarray:
    normalized = weights / weights.sum()
    x_mean = np.sum(train_x * normalized[:, None], axis=0)
    x_scale = np.sqrt(np.sum((train_x - x_mean) ** 2 * normalized[:, None], axis=0))
    x_scale[x_scale < 1e-8] = 1.0
    y_mean = np.sum(train_y * normalized[:, None], axis=0)
    standardized = (train_x - x_mean) / x_scale
    root = np.sqrt(weights)[:, None]
    coefficient = np.linalg.solve(
        (standardized * root).T @ (standardized * root)
        + alpha * np.eye(train_x.shape[1]),
        (standardized * root).T @ ((train_y - y_mean) * root),
    )
    return (score_x - x_mean) / x_scale @ coefficient + y_mean


def descending_percentile(values: np.ndarray) -> np.ndarray:
    # 1.0 is best; average ties are deterministic.
    return 1.0 - (rankdata(-values, method="average") - 1.0) / max(len(values) - 1, 1)


def standardize(values: np.ndarray) -> np.ndarray:
    sd = float(np.std(values))
    return (values - float(np.mean(values))) / (sd if sd > 1e-12 else 1.0)


def k_for_fraction(n: int, fraction: float) -> int:
    return max(1, int(math.ceil(n * fraction)))


def top_indices(values: np.ndarray, k: int) -> np.ndarray:
    return np.argsort(-values, kind="mergesort")[:k]


def enrichment(values: np.ndarray, truth: np.ndarray, positive_fraction: float, budget: float) -> dict:
    n = len(truth)
    positives_k = k_for_fraction(n, positive_fraction)
    budget_k = k_for_fraction(n, budget)
    positive = set(top_indices(truth, positives_k).tolist())
    selected = set(top_indices(values, budget_k).tolist())
    hits = len(positive & selected)
    precision = hits / budget_k
    recall = hits / positives_k
    prevalence = positives_k / n
    return {
        "rows": n,
        "positive_fraction": positive_fraction,
        "positive_count": positives_k,
        "budget_fraction": budget,
        "budget_count": budget_k,
        "hits": hits,
        "precision": precision,
        "recall": recall,
        "enrichment_factor": precision / prevalence,
    }


def tie_aware_enrichment(
    values: np.ndarray, truth: np.ndarray, positive_fraction: float, budget: float
) -> dict:
    n = len(truth)
    positives_k = k_for_fraction(n, positive_fraction)
    budget_k = k_for_fraction(n, budget)
    positive = set(top_indices(truth, positives_k).tolist())
    cutoff = float(np.sort(values)[::-1][budget_k - 1])
    above = set(np.flatnonzero(values > cutoff).tolist())
    tied = set(np.flatnonzero(values == cutoff).tolist())
    need = budget_k - len(above)
    positive_above = len(positive & above)
    positive_tied = len(positive & tied)
    minimum_additional = max(0, need - (len(tied) - positive_tied))
    maximum_additional = min(need, positive_tied)
    expected_additional = need * positive_tied / len(tied)
    prevalence = positives_k / n
    def values_for(hits: float) -> dict:
        precision = hits / budget_k
        return {
            "hits": hits,
            "recall": hits / positives_k,
            "enrichment_factor": precision / prevalence,
        }
    return {
        "rows": n,
        "positive_fraction": positive_fraction,
        "positive_count": positives_k,
        "budget_fraction": budget,
        "budget_count": budget_k,
        "cutoff_score": cutoff,
        "strictly_above_cutoff": len(above),
        "cutoff_tie_size": len(tied),
        "slots_taken_from_cutoff_tie": need,
        "positives_strictly_above": positive_above,
        "positives_in_cutoff_tie": positive_tied,
        "worst": values_for(positive_above + minimum_additional),
        "expected_random_tiebreak": values_for(positive_above + expected_additional),
        "best": values_for(positive_above + maximum_additional),
    }


def raw_union_enrichment(
    model_values: list[np.ndarray], truth: np.ndarray, positive_fraction: float, budget: float
) -> dict:
    n = len(truth)
    positives_k = k_for_fraction(n, positive_fraction)
    per_model_k = k_for_fraction(n, budget)
    positive = set(top_indices(truth, positives_k).tolist())
    selected: set[int] = set()
    for values in model_values:
        selected.update(top_indices(values, per_model_k).tolist())
    hits = len(positive & selected)
    actual = len(selected)
    precision = hits / actual
    prevalence = positives_k / n
    return {
        "rows": n,
        "positive_fraction": positive_fraction,
        "positive_count": positives_k,
        "per_model_budget_fraction": budget,
        "per_model_budget_count": per_model_k,
        "actual_union_count": actual,
        "actual_union_fraction": actual / n,
        "hits": hits,
        "precision": precision,
        "recall": hits / positives_k,
        "enrichment_factor_at_actual_union_size": precision / prevalence,
    }


def error_metrics(values: np.ndarray, truth: np.ndarray) -> dict:
    return {
        "spearman": float(spearmanr(values, truth).statistic),
        "mae": float(np.mean(np.abs(values - truth))),
        "rmse": float(np.sqrt(np.mean((values - truth) ** 2))),
    }


def within_parent_enrichment(
    values: np.ndarray,
    truth: np.ndarray,
    parents: list[str],
    positive_fraction: float = 0.2,
    budget: float = 0.2,
) -> dict:
    recalls, efs = [], []
    for parent in sorted(set(parents)):
        indices = np.array([i for i, value in enumerate(parents) if value == parent], dtype=int)
        positive_k = k_for_fraction(len(indices), positive_fraction)
        budget_k = k_for_fraction(len(indices), budget)
        positive_local = set(top_indices(truth[indices], positive_k).tolist())
        selected_local = set(top_indices(values[indices], budget_k).tolist())
        hits = len(positive_local & selected_local)
        recalls.append(hits / positive_k)
        precision = hits / budget_k
        efs.append(precision / (positive_k / len(indices)))
    return {
        "parents": len(recalls),
        "macro_recall": float(np.mean(recalls)),
        "macro_enrichment_factor": float(np.mean(efs)),
    }


def main() -> None:
    labels = {row["candidate_id"]: row for row in read_tsv(SUPERVISED)}
    if len(labels) != 1507:
        raise ValueError(f"supervised table is not open1507: {len(labels)}")
    if any("V4F" in candidate.upper() for candidate in labels):
        raise ValueError("sealed V4-F candidate detected")

    split_rows = [
        row for row in read_tsv(INNER_MANIFEST)
        if row["outer_fold"] == "0" and row["inner_fold"] == "0"
    ]
    train_ids = sorted(row["candidate_id"] for row in split_rows if row["candidate_role"] == "train")
    score_ids = sorted(row["candidate_id"] for row in split_rows if row["candidate_role"] == "score")
    if len(train_ids) != 1085 or len(score_ids) != 184:
        raise ValueError(f"unexpected inner split sizes:{len(train_ids)}:{len(score_ids)}")
    if set(train_ids) & set(score_ids):
        raise ValueError("inner split overlap")
    train_parents = {labels[c]["parent_framework_cluster"] for c in train_ids}
    score_parents = {labels[c]["parent_framework_cluster"] for c in score_ids}
    if train_parents & score_parents:
        raise ValueError("parent leakage in inner split")

    m2_fields = [field for field in next(iter(labels.values())) if "__" in field]
    if len(m2_fields) != 126:
        raise ValueError(f"M2 feature dimension changed:{len(m2_fields)}")
    train_x = np.asarray([[float(labels[c][f]) for f in m2_fields] for c in train_ids])
    train_y = np.asarray([[float(labels[c]["R_8X6B"]), float(labels[c]["R_9E6Y"])] for c in train_ids])
    score_x = np.asarray([[float(labels[c][f]) for f in m2_fields] for c in score_ids])
    m2_two = fit_m2(train_x, train_y, score_x, m2_weights(train_ids, labels))

    imported: dict[str, dict[str, dict[str, str]]] = {}
    for name, path in PREDICTION_INPUTS.items():
        rows = {row["candidate_id"]: row for row in read_tsv(path)}
        if set(rows) != set(score_ids):
            raise ValueError(f"prediction closure failed:{name}")
        imported[name] = rows

    truth_r8 = np.asarray([float(labels[c]["R_8X6B"]) for c in score_ids])
    truth_r9 = np.asarray([float(labels[c]["R_9E6Y"]) for c in score_ids])
    truth = np.minimum(truth_r8, truth_r9)
    b = np.asarray([float(imported["B"][c]["neural_Rdual"]) for c in score_ids])
    f0_seeds = {
        name: np.asarray([float(rows[c]["neural_Rdual"]) for c in score_ids])
        for name, rows in imported.items() if name.startswith("F0_seed")
    }
    f0_seed_r8 = {
        name: np.asarray([float(rows[c]["neural_R8"]) for c in score_ids])
        for name, rows in imported.items() if name.startswith("F0_seed")
    }
    f0_seed_r9 = {
        name: np.asarray([float(rows[c]["neural_R9"]) for c in score_ids])
        for name, rows in imported.items() if name.startswith("F0_seed")
    }
    # Match the frozen collector: ensemble direct receptor outputs first, then exact min.
    f0_r8 = np.mean(np.stack(list(f0_seed_r8.values())), axis=0)
    f0_r9 = np.mean(np.stack(list(f0_seed_r9.values())), axis=0)
    f0 = np.minimum(f0_r8, f0_r9)
    m2 = np.min(m2_two, axis=1)

    base_models = {"M2": m2, "B_seed43": b, "F0_ensemble": f0, **f0_seeds}
    rank_models = {name: descending_percentile(values) for name, values in base_models.items()}
    fused = {
        "M2_B_rank_mean": (rank_models["M2"] + rank_models["B_seed43"]) / 2.0,
        "M2_F0_rank_mean": (rank_models["M2"] + rank_models["F0_ensemble"]) / 2.0,
        "B_F0_rank_mean": (rank_models["B_seed43"] + rank_models["F0_ensemble"]) / 2.0,
        "M2_B_F0_rank_mean": (
            rank_models["M2"] + rank_models["B_seed43"] + rank_models["F0_ensemble"]
        ) / 3.0,
        "M2_F0_best_rank_OR": np.maximum(rank_models["M2"], rank_models["F0_ensemble"]),
        "M2_B_F0_best_rank_OR": np.maximum.reduce([
            rank_models["M2"], rank_models["B_seed43"], rank_models["F0_ensemble"]
        ]),
        "M2_F0_zmean": (standardize(m2) + standardize(f0)) / 2.0,
        "M2_B_F0_zmean": (standardize(m2) + standardize(b) + standardize(f0)) / 3.0,
    }
    all_models = {**base_models, **fused}

    metrics = {
        "schema_version": "pvrig_v2_6_open_inner_ensemble_audit_v1",
        "status": "OPEN_DEVELOPMENT_DESCRIPTIVE_ONLY",
        "claim_boundary": (
            "outer0/inner0 open-development whole-parent score partition only; "
            "computational Docking geometry surrogate evidence, not binding, affinity, "
            "experimental blocking, Docking Gold, sealed V4-F/test32, or outer-test truth"
        ),
        "access_audit": {
            "v4_f_test32_access_count": 0,
            "outer_test_truth_access_count": 0,
            "outer_metrics_access_count": 0,
        },
        "split": {
            "outer_fold": 0,
            "inner_fold": 0,
            "train_rows": len(train_ids),
            "train_parents": len(train_parents),
            "score_rows": len(score_ids),
            "score_parents": len(score_parents),
            "parent_overlap": len(train_parents & score_parents),
        },
        "inputs": {
            "supervised_sha256": sha256_file(SUPERVISED),
            "inner_manifest_sha256": sha256_file(INNER_MANIFEST),
            **{name: sha256_file(path) for name, path in PREDICTION_INPUTS.items()},
            "collector_result_sha256": sha256_file(COLLECTOR_RESULT),
        },
        "models": {},
        "pairwise_prediction_spearman": {},
        "top_overlap": {},
        "raw_top_union": {},
        "within_parent_top20": {},
        "score_resolution": {},
        "tie_aware_early_enrichment": {},
        "rounding_sensitivity_trueTop10_predTop5": {},
    }

    enrichment_rows = []
    for name, values in all_models.items():
        metrics["models"][name] = error_metrics(values, truth)
        if name in fused:
            metrics["models"][name]["mae"] = None
            metrics["models"][name]["rmse"] = None
            metrics["models"][name]["scale_note"] = "rank/z-score fusion; absolute-error scale is undefined"
        metrics["within_parent_top20"][name] = within_parent_enrichment(
            values, truth, [labels[c]["parent_framework_cluster"] for c in score_ids]
        )
        counts = defaultdict(int)
        for value in values.tolist():
            counts[float(value)] += 1
        metrics["score_resolution"][name] = {
            "unique_scores": len(counts),
            "maximum_tie_size": max(counts.values()),
        }
        for positive_fraction in (0.1, 0.2):
            for budget in (0.05, 0.1, 0.2):
                row = {"model": name, **enrichment(values, truth, positive_fraction, budget)}
                enrichment_rows.append(row)
                metrics["tie_aware_early_enrichment"][
                    f"{name}|positive={positive_fraction}|budget={budget}"
                ] = tie_aware_enrichment(values, truth, positive_fraction, budget)

    collector = json.loads(COLLECTOR_RESULT.read_text())
    for local_name, collector_name in (
        ("B_seed43", "B_SCALAR_ATTENTION_ONLY"),
        ("F0_ensemble", "F0_SHARED_GATED_NO_RANK"),
    ):
        expected = collector["variant_metrics"][collector_name]["Rdual"]
        observed = metrics["models"][local_name]
        for field in ("spearman", "mae", "rmse"):
            if abs(float(expected[field]) - float(observed[field])) > 1e-12:
                raise ValueError(f"collector reproduction failed:{local_name}:{field}")
    metrics["collector_reproduction"] = {
        "B_seed43_Rdual": "PASS_EXACT_WITHIN_1E-12",
        "F0_ensemble_Rdual": "PASS_EXACT_WITHIN_1E-12",
    }

    core = ["M2", "B_seed43", "F0_ensemble"]
    for name in core:
        values = base_models[name]
        metrics["rounding_sensitivity_trueTop10_predTop5"][name] = {}
        for positive_rule, positive_k in (
            ("floor", max(1, int(len(score_ids) * 0.1))),
            ("ceil", k_for_fraction(len(score_ids), 0.1)),
        ):
            for budget_rule, budget_k in (
                ("floor", max(1, int(len(score_ids) * 0.05))),
                ("ceil", k_for_fraction(len(score_ids), 0.05)),
            ):
                positives = set(top_indices(truth, positive_k).tolist())
                selected = set(top_indices(values, budget_k).tolist())
                metrics["rounding_sensitivity_trueTop10_predTop5"][name][
                    f"positive_{positive_rule}__budget_{budget_rule}"
                ] = {
                    "positive_count": positive_k,
                    "budget_count": budget_k,
                    "hits": len(positives & selected),
                }
    for i, left in enumerate(core):
        for right in core[i + 1:]:
            key = f"{left}__{right}"
            metrics["pairwise_prediction_spearman"][key] = float(
                spearmanr(base_models[left], base_models[right]).statistic
            )
            metrics["top_overlap"][key] = {}
            for budget in (0.05, 0.1, 0.2):
                k = k_for_fraction(len(score_ids), budget)
                a = set(top_indices(base_models[left], k).tolist())
                bset = set(top_indices(base_models[right], k).tolist())
                metrics["top_overlap"][key][str(budget)] = {
                    "k": k,
                    "intersection": len(a & bset),
                    "intersection_over_k": len(a & bset) / k,
                    "jaccard": len(a & bset) / len(a | bset),
                }
            for positive_fraction in (0.1, 0.2):
                for budget in (0.05, 0.1, 0.2):
                    union_key = f"{key}|positive={positive_fraction}|budget={budget}"
                    metrics["raw_top_union"][union_key] = raw_union_enrichment(
                        [base_models[left], base_models[right]], truth, positive_fraction, budget
                    )

    for positive_fraction in (0.1, 0.2):
        for budget in (0.05, 0.1, 0.2):
            key = f"M2__B_seed43__F0_ensemble|positive={positive_fraction}|budget={budget}"
            metrics["raw_top_union"][key] = raw_union_enrichment(
                [m2, b, f0], truth, positive_fraction, budget
            )

    prediction_fields = [
        "candidate_id", "teacher_source", "parent_framework_cluster", "truth_R8", "truth_R9",
        "truth_Rdual", "M2_R8", "M2_R9", "M2_Rdual", "B_Rdual", "F0_seed43_Rdual",
        "F0_seed97_Rdual", "F0_seed193_Rdual", "F0_ensemble_Rdual",
    ] + list(fused)
    with (REPORT / "open_inner_predictions_and_fusions.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prediction_fields, delimiter="\t")
        writer.writeheader()
        for index, candidate_id in enumerate(score_ids):
            row = {
                "candidate_id": candidate_id,
                "teacher_source": labels[candidate_id]["teacher_source"],
                "parent_framework_cluster": labels[candidate_id]["parent_framework_cluster"],
                "truth_R8": truth_r8[index],
                "truth_R9": truth_r9[index],
                "truth_Rdual": truth[index],
                "M2_R8": m2_two[index, 0],
                "M2_R9": m2_two[index, 1],
                "M2_Rdual": m2[index],
                "B_Rdual": b[index],
                "F0_seed43_Rdual": f0_seeds["F0_seed43"][index],
                "F0_seed97_Rdual": f0_seeds["F0_seed97"][index],
                "F0_seed193_Rdual": f0_seeds["F0_seed193"][index],
                "F0_ensemble_Rdual": f0[index],
                **{name: values[index] for name, values in fused.items()},
            }
            writer.writerow(row)

    with (REPORT / "early_enrichment.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(enrichment_rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(enrichment_rows)

    (REPORT / "METRICS.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    checksums = [
        f"{sha256_file(REPORT / name)}  {name}"
        for name in ("METRICS.json", "early_enrichment.tsv", "open_inner_predictions_and_fusions.tsv")
    ]
    (REPORT / "OUTPUT_SHA256SUMS").write_text("\n".join(checksums) + "\n")


if __name__ == "__main__":
    main()
