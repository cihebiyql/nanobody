#!/usr/bin/env python3
"""Nested whole-parent OOF evaluation for frozen V2.5 coarse-pose challengers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

from pca8_fold_transformer_v1 import fit_pca8, transform_pca8


TARGETS = ("R_8X6B", "R_9E6Y", "R_dual_min")
PCA_EXCLUSIONS = {
    "8x6b__pose_count", "9e6y__pose_count",
    "8x6b__top20_score_entropy", "9e6y__top20_score_entropy",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def unique_rows(rows: Sequence[Mapping[str, str]], label: str) -> Dict[str, Mapping[str, str]]:
    output = {}
    for row in rows:
        candidate = row["candidate_id"]
        if candidate in output:
            raise ValueError(f"duplicate {label} candidate: {candidate}")
        output[candidate] = row
    return output


def rankdata(values: Sequence[float]) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return ranks


def spearman(truth: Sequence[float], prediction: Sequence[float]) -> float:
    left, right = rankdata(truth), rankdata(prediction)
    if np.std(left) == 0 or np.std(right) == 0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def scalar_metrics(truth: np.ndarray, prediction: np.ndarray) -> Dict[str, float]:
    error = prediction - truth
    return {
        "spearman": spearman(truth, prediction),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
    }


def hierarchical_weights(
    candidate_ids: Sequence[str], metadata: Mapping[str, Mapping[str, str]]
) -> np.ndarray:
    groups: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    for index, candidate in enumerate(candidate_ids):
        row = metadata[candidate]
        groups[row["teacher_source"]][row["parent_framework_cluster"]].append(index)
    weights = np.zeros(len(candidate_ids), dtype=np.float64)
    source_count = len(groups)
    for parents in groups.values():
        for indices in parents.values():
            value = 1.0 / source_count / len(parents) / len(indices)
            weights[indices] = value
    weights *= len(candidate_ids) / weights.sum()
    return weights


def weighted_standardize_fit(values: np.ndarray, weights: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    total = weights.sum()
    mean = np.sum(values * weights[:, None], axis=0) / total
    variance = np.sum(((values - mean) ** 2) * weights[:, None], axis=0) / total
    scale = np.sqrt(np.maximum(variance, 0.0))
    if np.any(scale <= 1e-10):
        raise ValueError("train-fold feature became constant")
    return mean, scale


def ridge_predict(
    train_x: np.ndarray,
    train_y: np.ndarray,
    score_x: np.ndarray,
    weights: np.ndarray,
    alpha: float,
) -> np.ndarray:
    mean, scale = weighted_standardize_fit(train_x, weights)
    x = (train_x - mean) / scale
    z = (score_x - mean) / scale
    total = weights.sum()
    x_mean = np.sum(x * weights[:, None], axis=0) / total
    y_mean = np.sum(train_y * weights[:, None], axis=0) / total
    xc, yc = x - x_mean, train_y - y_mean
    gram = xc.T @ (weights[:, None] * xc) + alpha * np.eye(x.shape[1])
    rhs = xc.T @ (weights[:, None] * yc)
    coefficients = np.linalg.solve(gram, rhs)
    intercept = y_mean - x_mean @ coefficients
    return z @ coefficients + intercept


def branch_predict(
    branch: str,
    train_x: np.ndarray,
    train_y: np.ndarray,
    score_x: np.ndarray,
    weights: np.ndarray,
    alpha: float,
) -> np.ndarray:
    if branch == "C1_SYMMETRIC12D_RIDGE":
        return ridge_predict(train_x, train_y, score_x, weights, alpha)
    if branch == "C2_INNER_TRAIN_PCA8_RIDGE":
        pca = fit_pca8(train_x, components=8)
        train_pca = transform_pca8(train_x, pca)
        score_pca = transform_pca8(score_x, pca)
        return ridge_predict(train_pca, train_y, score_pca, weights, alpha)
    raise ValueError(f"unknown branch: {branch}")


def exact_min(two_output: np.ndarray) -> np.ndarray:
    if two_output.ndim != 2 or two_output.shape[1] != 2:
        raise ValueError("exact-min requires two direct receptor outputs")
    return np.minimum(two_output[:, 0], two_output[:, 1])


def selection_loss(
    candidate_ids: Sequence[str],
    truth_two: np.ndarray,
    prediction_two: np.ndarray,
    metadata: Mapping[str, Mapping[str, str]],
) -> float:
    truth = np.column_stack([truth_two, exact_min(truth_two)])
    prediction = np.column_stack([prediction_two, exact_min(prediction_two)])
    by_parent: Dict[str, List[int]] = defaultdict(list)
    for index, candidate in enumerate(candidate_ids):
        by_parent[metadata[candidate]["parent_framework_cluster"]].append(index)
    parent_losses = []
    for indices in by_parent.values():
        parent_losses.append(float(np.mean(np.abs(prediction[indices] - truth[indices]))))
    return float(np.mean(parent_losses))


def target_matrix(ids: Sequence[str], labels: Mapping[str, Mapping[str, str]]) -> np.ndarray:
    return np.asarray([[float(labels[c]["R_8X6B"]), float(labels[c]["R_9E6Y"])] for c in ids])


def feature_matrix(ids: Sequence[str], rows: Mapping[str, Mapping[str, str]], fields: Sequence[str]) -> np.ndarray:
    values = np.asarray([[float(rows[c][field]) for field in fields] for c in ids], dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("non-finite feature matrix")
    return values


def evaluate_predictions(rows: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    targets = {}
    for truth_key, prediction_key, name in (
        ("truth_R8", "pred_R8", "R_8X6B"),
        ("truth_R9", "pred_R9", "R_9E6Y"),
        ("truth_Rdual", "pred_Rdual", "R_dual_min"),
    ):
        targets[name] = scalar_metrics(
            np.asarray([float(row[truth_key]) for row in rows]),
            np.asarray([float(row[prediction_key]) for row in rows]),
        )
    sources = {}
    for source in sorted({str(row["teacher_source"]) for row in rows}):
        subset = [row for row in rows if row["teacher_source"] == source]
        sources[source] = evaluate_predictions(subset)["targets"] if len(subset) != len(rows) else targets
    by_parent: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        by_parent[str(row["parent_framework_cluster"])].append(row)
    parent_summary = {}
    for truth_key, prediction_key, name in (
        ("truth_R8", "pred_R8", "R_8X6B"),
        ("truth_R9", "pred_R9", "R_9E6Y"),
        ("truth_Rdual", "pred_Rdual", "R_dual_min"),
    ):
        maes, rmses, correlations = [], [], []
        for subset in by_parent.values():
            truth = np.asarray([float(row[truth_key]) for row in subset])
            prediction = np.asarray([float(row[prediction_key]) for row in subset])
            metric = scalar_metrics(truth, prediction)
            maes.append(metric["mae"]); rmses.append(metric["rmse"])
            if len(subset) >= 3 and np.std(truth) > 0 and np.std(prediction) > 0:
                correlations.append(metric["spearman"])
        parent_summary[name] = {
            "macro_mae": float(np.mean(maes)),
            "macro_rmse": float(np.mean(rmses)),
            "macro_within_parent_spearman": float(np.mean(correlations)) if correlations else 0.0,
            "spearman_parent_count": len(correlations),
        }
    return {"targets": targets, "sources": sources, "parent_macro": parent_summary}


def main(args):
    contract_path = Path(args.selection_contract).resolve()
    contract = json.loads(contract_path.read_text())
    if contract["status"] != "FROZEN_BEFORE_OPEN1507_PERFORMANCE_COMPUTATION":
        raise ValueError("selection contract is not frozen")
    alphas = [float(value) for value in contract["ridge_alpha_grid"]]

    labels = unique_rows(read_tsv(Path(args.labels)), "label")
    compact = unique_rows(read_tsv(Path(args.compact_features)), "compact")
    raw = unique_rows(read_tsv(Path(args.raw_features)), "raw")
    manifest = unique_rows(read_tsv(Path(args.cohort_manifest)), "cohort")
    candidates = set(labels) & set(compact) & set(raw) & set(manifest)
    if len(candidates) != 1507 or not all(set(table) == candidates for table in (labels, compact, raw, manifest)):
        raise ValueError("open1507 table closure failed")
    if any("V4F" in candidate.upper() for candidate in candidates):
        raise ValueError("V4-F/test candidate detected")
    metadata = {
        c: {
            "teacher_source": labels[c]["teacher_source"],
            "parent_framework_cluster": labels[c]["parent_framework_cluster"],
        }
        for c in candidates
    }
    compact_fields = [field for field in next(iter(compact.values())) if field not in {"candidate_id", "feature_schema"}]
    raw_fields = [field for field in next(iter(raw.values())) if "__" in field and field not in PCA_EXCLUSIONS]
    if len(compact_fields) != 12 or len(raw_fields) != 32:
        raise ValueError("frozen feature dimension mismatch")

    outer_rows = read_tsv(Path(args.outer_manifest))
    inner_rows = read_tsv(Path(args.inner_manifest))
    branches = {
        "C1_SYMMETRIC12D_RIDGE": (compact, compact_fields),
        "C2_INNER_TRAIN_PCA8_RIDGE": (raw, raw_fields),
    }
    predictions: Dict[str, List[Dict[str, object]]] = {branch: [] for branch in branches}
    null_predictions: List[Dict[str, object]] = []
    selection_rows = []

    for outer_fold in range(5):
        outer_fold_rows = [row for row in outer_rows if int(row["outer_fold"]) == outer_fold]
        train_ids = sorted(row["candidate_id"] for row in outer_fold_rows if row["candidate_role"] == "train")
        score_ids = sorted(row["candidate_id"] for row in outer_fold_rows if row["candidate_role"] == "score")
        if set(train_ids) & set(score_ids) or set(train_ids) | set(score_ids) != candidates:
            raise ValueError(f"outer fold closure failed: {outer_fold}")
        train_y = target_matrix(train_ids, labels)
        score_y = target_matrix(score_ids, labels)
        train_weights = hierarchical_weights(train_ids, metadata)
        null_two = np.repeat(
            (np.sum(train_y * train_weights[:, None], axis=0) / train_weights.sum())[None, :],
            len(score_ids), axis=0,
        )
        for index, candidate in enumerate(score_ids):
            null_predictions.append({
                "model_id": "C0_NO_FEATURE_WEIGHTED_MEAN",
                "candidate_id": candidate,
                "outer_fold": outer_fold,
                "teacher_source": metadata[candidate]["teacher_source"],
                "parent_framework_cluster": metadata[candidate]["parent_framework_cluster"],
                "selected_alpha": "",
                "truth_R8": score_y[index, 0], "truth_R9": score_y[index, 1],
                "truth_Rdual": min(score_y[index]),
                "pred_R8": null_two[index, 0], "pred_R9": null_two[index, 1],
                "pred_Rdual": min(null_two[index]),
            })

        for branch, (feature_rows, fields) in branches.items():
            alpha_losses = {}
            for alpha in alphas:
                inner_predictions = {}
                inner_truth = {}
                for inner_fold in range(5):
                    subset = [
                        row for row in inner_rows
                        if int(row["outer_fold"]) == outer_fold and int(row["inner_fold"]) == inner_fold
                    ]
                    inner_train = sorted(row["candidate_id"] for row in subset if row["candidate_role"] == "train")
                    inner_score = sorted(row["candidate_id"] for row in subset if row["candidate_role"] == "score")
                    if set(inner_train) & set(inner_score):
                        raise ValueError("inner train/score overlap")
                    x_train = feature_matrix(inner_train, feature_rows, fields)
                    x_score = feature_matrix(inner_score, feature_rows, fields)
                    y_train = target_matrix(inner_train, labels)
                    weight = hierarchical_weights(inner_train, metadata)
                    pred = branch_predict(branch, x_train, y_train, x_score, weight, alpha)
                    for index, candidate in enumerate(inner_score):
                        if candidate in inner_predictions:
                            raise ValueError("candidate scored twice in combined inner OOF")
                        inner_predictions[candidate] = pred[index]
                        inner_truth[candidate] = target_matrix([candidate], labels)[0]
                if set(inner_predictions) != set(train_ids):
                    raise ValueError(f"inner OOF does not cover outer train: fold {outer_fold}")
                ordered = sorted(inner_predictions)
                alpha_losses[alpha] = selection_loss(
                    ordered,
                    np.stack([inner_truth[candidate] for candidate in ordered]),
                    np.stack([inner_predictions[candidate] for candidate in ordered]),
                    metadata,
                )
            best_loss = min(alpha_losses.values())
            selected_alpha = max(alpha for alpha, loss in alpha_losses.items() if abs(loss - best_loss) <= 1e-12)
            for alpha in alphas:
                selection_rows.append({
                    "branch": branch, "outer_fold": outer_fold, "alpha": alpha,
                    "inner_parent_macro_three_target_mae": alpha_losses[alpha],
                    "selected": str(alpha == selected_alpha).lower(),
                })
            x_train = feature_matrix(train_ids, feature_rows, fields)
            x_score = feature_matrix(score_ids, feature_rows, fields)
            pred = branch_predict(branch, x_train, train_y, x_score, train_weights, selected_alpha)
            for index, candidate in enumerate(score_ids):
                predictions[branch].append({
                    "model_id": branch,
                    "candidate_id": candidate,
                    "outer_fold": outer_fold,
                    "teacher_source": metadata[candidate]["teacher_source"],
                    "parent_framework_cluster": metadata[candidate]["parent_framework_cluster"],
                    "selected_alpha": selected_alpha,
                    "truth_R8": score_y[index, 0], "truth_R9": score_y[index, 1],
                    "truth_Rdual": min(score_y[index]),
                    "pred_R8": pred[index, 0], "pred_R9": pred[index, 1],
                    "pred_Rdual": min(pred[index]),
                })

    all_prediction_rows = null_predictions + [row for branch in branches for row in predictions[branch]]
    for model in ["C0_NO_FEATURE_WEIGHTED_MEAN", *branches]:
        rows = [row for row in all_prediction_rows if row["model_id"] == model]
        if len(rows) != 1507 or len({row["candidate_id"] for row in rows}) != 1507:
            raise ValueError(f"OOF prediction closure failed: {model}")
        if any(abs(float(row["pred_Rdual"]) - min(float(row["pred_R8"]), float(row["pred_R9"]))) > 1e-12 for row in rows):
            raise ValueError("exact-min prediction violation")

    metrics = {"C0_NO_FEATURE_WEIGHTED_MEAN": evaluate_predictions(null_predictions)}
    for branch in branches:
        metrics[branch] = evaluate_predictions(predictions[branch])
    null = metrics["C0_NO_FEATURE_WEIGHTED_MEAN"]
    comparator = contract["unchanged_v2_4_promotion_gate"]
    decisions = {}
    for branch in branches:
        current = metrics[branch]
        overall = current["targets"]["R_dual_min"]
        null_overall = null["targets"]["R_dual_min"]
        source_gate = all(
            current["sources"][source]["R_dual_min"]["mae"]
            < null["sources"][source]["R_dual_min"]["mae"]
            for source in current["sources"]
        )
        parent_gate = (
            current["parent_macro"]["R_dual_min"]["macro_mae"]
            < null["parent_macro"]["R_dual_min"]["macro_mae"]
        )
        sanity = (
            overall["spearman"] >= null_overall["spearman"] + 0.01
            and overall["mae"] < null_overall["mae"]
            and overall["rmse"] < null_overall["rmse"]
            and source_gate and parent_gate
        )
        promote = (
            overall["spearman"] >= comparator["required_Rdual_spearman"]
            and overall["mae"] <= comparator["M2_Rdual_mae_ceiling"]
            and overall["rmse"] <= comparator["M2_Rdual_rmse_ceiling"]
            and source_gate and parent_gate
        )
        decisions[branch] = {
            "no_target_leakage_sanity": "PASS" if sanity else "FAIL",
            "unchanged_v2_4_promotion_gate": "PASS" if promote else "FAIL",
            "promotion_status": "PASS_PROMOTE" if promote else "DO_NOT_PROMOTE",
            "source_mae_gate": source_gate,
            "parent_macro_mae_gate": parent_gate,
            "Rdual_spearman_delta_vs_null": overall["spearman"] - null_overall["spearman"],
            "Rdual_spearman_delta_vs_M2": overall["spearman"] - comparator["M2_Rdual_spearman"],
        }
    best = max(branches, key=lambda branch: metrics[branch]["targets"]["R_dual_min"]["spearman"])
    global_status = "PASS_PROMOTE_V2_5_COARSE_POSE" if any(
        decision["promotion_status"] == "PASS_PROMOTE" for decision in decisions.values()
    ) else "DO_NOT_PROMOTE_V2_5_COARSE_POSE"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / "open1507_nested_outer_oof_predictions.tsv"
    with prediction_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_prediction_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(all_prediction_rows)
    selection_path = output_dir / "inner_alpha_selection.tsv"
    with selection_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(selection_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(selection_rows)
    metric_payload = {
        "schema_version": "pvrig_v2_5_coarse_pose_nested_whole_parent_oof_metrics_v1",
        "status": global_status,
        "best_open_development_branch": best,
        "metrics": metrics,
        "decisions": decisions,
        "comparator": comparator,
        "claim_boundary": contract["claim_boundary"],
    }
    metric_path = output_dir / "METRICS.json"
    metric_path.write_text(json.dumps(metric_payload, indent=2, sort_keys=True) + "\n")
    receipt = {
        "schema_version": "pvrig_v2_5_coarse_pose_nested_whole_parent_oof_result_v1",
        "status": global_status,
        "prediction_rows": len(all_prediction_rows),
        "models": 3,
        "candidates_per_model": 1507,
        "exact_min_violations": 0,
        "same_row_stacking_used": False,
        "v4_f_or_test32_access": False,
        "candidate_docking_pose_features": False,
        "artifacts": {
            "predictions": {"path": str(prediction_path), "sha256": sha256_file(prediction_path)},
            "selection": {"path": str(selection_path), "sha256": sha256_file(selection_path)},
            "metrics": {"path": str(metric_path), "sha256": sha256_file(metric_path)},
            "selection_contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        },
        "claim_boundary": contract["claim_boundary"],
    }
    (output_dir / "RESULT_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True)
    parser.add_argument("--compact-features", required=True)
    parser.add_argument("--raw-features", required=True)
    parser.add_argument("--cohort-manifest", required=True)
    parser.add_argument("--outer-manifest", required=True)
    parser.add_argument("--inner-manifest", required=True)
    parser.add_argument("--selection-contract", required=True)
    parser.add_argument("--output-dir", required=True)
    main(parser.parse_args())
