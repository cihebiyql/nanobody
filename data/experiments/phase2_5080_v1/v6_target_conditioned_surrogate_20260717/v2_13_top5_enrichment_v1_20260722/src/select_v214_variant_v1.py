#!/usr/bin/env python3
"""Apply the result-blind V2.14 listwise promotion contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCHEMA = "pvrig_v2_14_listwise_selection_v1"
CONTRACT_SCHEMA = "pvrig_v2_14_listwise_promotion_contract_v1"
VARIANTS = ("N1", "N2", "N3")


class SelectionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SelectionError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"tsv_empty:{path}")
    return fields, rows


def rank_order(candidate_ids: Sequence[str], score: np.ndarray) -> list[int]:
    return sorted(range(len(score)), key=lambda index: (-float(score[index]), candidate_ids[index]))


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    result = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        result[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    return result


def spearman(truth: np.ndarray, prediction: np.ndarray) -> float:
    left, right = rankdata(truth), rankdata(prediction)
    if np.std(left) == 0.0 or np.std(right) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def early_metric(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray, budget: float) -> dict[str, float | int]:
    count = len(truth)
    positives = max(1, math.ceil(0.10 * count))
    selected = max(1, math.ceil(budget * count))
    truth_set = set(rank_order(candidate_ids, truth)[:positives])
    prediction = rank_order(candidate_ids, score)[:selected]
    hits = len(truth_set & set(prediction))
    relevance = np.asarray([1.0 if index in truth_set else 0.0 for index in prediction])
    discounts = np.log2(np.arange(2, selected + 2, dtype=np.float64))
    ideal_count = min(positives, selected)
    ideal = float(np.sum(1.0 / np.log2(np.arange(2, ideal_count + 2, dtype=np.float64))))
    return {
        "selected": selected,
        "positives": positives,
        "hits": hits,
        "precision": hits / selected,
        "recall": hits / positives,
        "ef": (hits / selected) / (positives / count),
        "binary_ndcg": float(np.sum(relevance / discounts)) / ideal,
    }


def metrics(candidate_ids: Sequence[str], folds: np.ndarray, truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    pooled5, pooled10 = early_metric(candidate_ids, truth, prediction, 0.05), early_metric(candidate_ids, truth, prediction, 0.10)
    fold_ef5 = []
    for fold in sorted(set(folds.tolist())):
        indices = np.flatnonzero(folds == fold)
        fold_ef5.append(float(early_metric([candidate_ids[index] for index in indices], truth[indices], prediction[indices], 0.05)["ef"]))
    return {
        "pooled_ef5": float(pooled5["ef"]),
        "pooled_ef10": float(pooled10["ef"]),
        "binary_ndcg_true_top10_at_budget5": float(pooled5["binary_ndcg"]),
        "rdual_spearman": spearman(truth, prediction),
        "rdual_mae": float(np.mean(np.abs(prediction - truth))),
        "fold_ef5": fold_ef5,
        "median_fold_ef5": float(np.median(fold_ef5)),
        "worst_fold_ef5": float(np.min(fold_ef5)),
    }


def load_prediction(path: Path, prediction_column: str) -> dict[str, dict[str, str]]:
    fields, rows = read_tsv(path)
    required = {"candidate_id", "fold_id", "truth_Rdual_exact_min", prediction_column}
    require(required <= set(fields), f"prediction_fields_missing:{path}:{sorted(required-set(fields))}")
    result = {row["candidate_id"]: row for row in rows}
    require(len(result) == len(rows) == 9849, f"candidate_closure:{path}")
    return result


def select(contract_path: Path, baseline_path: Path, phase_a_root: Path, output_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    require(contract.get("schema_version") == CONTRACT_SCHEMA, "contract_schema")
    require(contract.get("status") == "FROZEN_RESULT_BLIND_BEFORE_V2_14_OOF", "contract_status")
    expected_baseline_sha = str(contract["baseline"]["oof_sha256"])
    require(sha256_file(baseline_path) == expected_baseline_sha, "baseline_sha256")
    baseline = load_prediction(baseline_path, "B_CLEAN_TARGET_ATTENTION__Rdual_exact_min")
    candidate_ids = sorted(baseline)
    truth = np.asarray([float(baseline[candidate]["truth_Rdual_exact_min"]) for candidate in candidate_ids])
    folds = np.asarray([int(baseline[candidate]["fold_id"]) for candidate in candidate_ids])
    baseline_score = np.asarray([float(baseline[candidate]["B_CLEAN_TARGET_ATTENTION__Rdual_exact_min"]) for candidate in candidate_ids])
    baseline_metrics = metrics(candidate_ids, folds, truth, baseline_score)
    frozen_baseline = contract["baseline"]
    require(abs(baseline_metrics["pooled_ef5"] - float(frozen_baseline["ef5"])) <= 1e-9, "baseline_ef5_replay")
    require(abs(baseline_metrics["pooled_ef10"] - float(frozen_baseline["ef10"])) <= 1e-9, "baseline_ef10_replay")
    gate = contract["phase_a_candidate_gate"]
    evaluated: dict[str, Any] = {}
    eligible = []
    complexity = {"N1": 1, "N2": 2, "N3": 3}
    for variant in VARIANTS:
        path = phase_a_root / variant / "OOF_AGGREGATE" / f"V214_{variant}_TRAIN9849_OOF_PREDICTIONS.tsv"
        rows = load_prediction(path, f"B_TOP5_{variant}__Rdual_exact_min")
        require(set(rows) == set(baseline), f"variant_candidate_set:{variant}")
        for candidate in candidate_ids:
            require(int(rows[candidate]["fold_id"]) == int(baseline[candidate]["fold_id"]), f"variant_fold:{variant}:{candidate}")
            require(abs(float(rows[candidate]["truth_Rdual_exact_min"]) - float(baseline[candidate]["truth_Rdual_exact_min"])) <= 4e-8, f"variant_truth:{variant}:{candidate}")
        score = np.asarray([float(rows[candidate][f"B_TOP5_{variant}__Rdual_exact_min"]) for candidate in candidate_ids])
        observed = metrics(candidate_ids, folds, truth, score)
        fold_delta = np.asarray(observed["fold_ef5"]) - np.asarray(baseline_metrics["fold_ef5"])
        checks = {
            "pooled_ef5": observed["pooled_ef5"] >= float(gate["minimum_pooled_ef5"]),
            "ef10": observed["pooled_ef10"] >= float(gate["minimum_ef10"]),
            "spearman": observed["rdual_spearman"] >= float(gate["minimum_rdual_spearman"]),
            "mae": observed["rdual_mae"] <= float(gate["maximum_rdual_mae"]),
            "fold_count": int(np.sum(fold_delta >= -0.50)) >= int(gate["minimum_folds_with_ef5_delta_at_least_minus_0p50"]),
            "single_fold": float(np.min(fold_delta)) >= float(gate["minimum_allowed_single_fold_ef5_delta"]),
        }
        observed.update({"fold_ef5_delta_vs_baseline": fold_delta.tolist(), "gate_checks": checks, "eligible": all(checks.values()), "input_sha256": sha256_file(path)})
        evaluated[variant] = observed
        if observed["eligible"]:
            eligible.append(variant)
    ranking = lambda variant: (
        evaluated[variant]["pooled_ef5"],
        evaluated[variant]["binary_ndcg_true_top10_at_budget5"],
        evaluated[variant]["median_fold_ef5"],
        evaluated[variant]["worst_fold_ef5"],
        evaluated[variant]["rdual_spearman"],
        -evaluated[variant]["rdual_mae"],
        -complexity[variant],
    )
    selected = max(eligible, key=ranking) if eligible else None
    result = {
        "schema_version": SCHEMA,
        "status": "PASS_V2_14_VARIANT_PROMOTED" if selected else contract["failure"]["no_eligible_variant"],
        "selected_variant": selected,
        "eligible_variants": eligible,
        "baseline": baseline_metrics,
        "variants": evaluated,
        "selection_order": contract["selection_order_descending"],
        "input_bindings": {"contract_sha256": sha256_file(contract_path), "baseline_sha256": sha256_file(baseline_path)},
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
    }
    require(not output_path.exists(), "selection_output_exists")
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--baseline-oof", type=Path, required=True)
    parser.add_argument("--phase-a-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = select(args.contract, args.baseline_oof, args.phase_a_root, args.output)
    print(json.dumps({"status": result["status"], "selected_variant": result["selected_variant"]}, sort_keys=True))
    return 0 if result["selected_variant"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
