#!/usr/bin/env python3
"""Strict nested whole-parent OOF evaluation for V2.18 pose-aux models."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


SCHEMA = "pvrig_v2_18_pose_aux_crossfit_oof_v1_1"
METHODS = ("A0_L1", "A1_RIDGE_AUX", "A2_HGB2_AUX", "A3_RIDGE_AUX_UNCERTAINTY")
META_FIELDS = {
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster", "cdr1", "cdr2", "cdr3",
    "sample_weight", "R_8X6B", "R_9E6Y", "R_dual_min", "teacher_source", "teacher_reliability",
    "model_split", "asset_lane", "monomer_sha256",
}
AUX_META = {
    "candidate_id", "parent_framework_cluster", "sequence_sha256", "successful_dual_seed_count",
    "multiseed_uncertainty_available", "seed_dispersion_Rdual",
}


class V218Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise V218Error(message)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"missing_header:{path}")
        rows = list(reader)
    return list(reader.fieldnames), rows


def unique(rows: Sequence[Mapping[str, str]], key: str, label: str) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        value = row[key]
        require(value and value not in result, f"duplicate_or_empty:{label}:{value}")
        result[value] = row
    return result


def raw_feature_names(header: Sequence[str]) -> list[str]:
    names = [name for name in header if name.startswith(("ALL__", "CDR1_", "CDR2_", "CDR3_", "CDR_ALL__", "FRAMEWORK__", "C2__"))]
    require(len(names) == len(set(names)) == 162, f"raw_feature_count:{len(names)}")
    require(not (set(names) & META_FIELDS), "raw_feature_metadata_overlap")
    return names


def load_data(raw_path: Path, strict_path: Path, l1_path: Path, aux_path: Path) -> dict[str, Any]:
    strict_header, strict_rows = read_tsv(strict_path)
    strict = unique(strict_rows, "candidate_id", "strict")
    require(len(strict) == 9849 or len(strict) < 100, f"strict_row_count:{len(strict)}")
    required = {"candidate_id", "parent_framework_cluster", "fold_id", "truth_R8", "truth_R9", "truth_Rdual_exact_min"}
    require(required.issubset(strict_header), f"strict_schema:{sorted(required-set(strict_header))}")
    ids = sorted(strict)

    raw_header, raw_rows = read_tsv(raw_path)
    raw_features = raw_feature_names(raw_header)
    raw = unique([row for row in raw_rows if row["candidate_id"] in strict], "candidate_id", "raw")
    require(set(raw) == set(ids), f"raw_closure:{len(raw)}:{len(ids)}")

    _, l1_rows = read_tsv(l1_path)
    l1 = unique(l1_rows, "candidate_id", "l1")
    require(set(l1) == set(ids), f"l1_closure:{len(l1)}:{len(ids)}")

    aux_header, aux_rows = read_tsv(aux_path)
    aux = unique(aux_rows, "candidate_id", "aux")
    require(set(aux).issubset(ids), "aux_outside_strict")
    aux_targets = [name for name in aux_header if name not in AUX_META]
    require(len(aux_targets) >= 20, f"aux_target_count:{len(aux_targets)}")

    parents = np.asarray([strict[candidate]["parent_framework_cluster"] for candidate in ids])
    folds = np.asarray([int(strict[candidate]["fold_id"]) for candidate in ids], dtype=np.int64)
    require(set(folds.tolist()) == set(range(5)) or len(ids) < 100, f"fold_set:{set(folds.tolist())}")
    require(all(len(set(parents[folds == fold])) > 0 for fold in set(folds.tolist())), "empty_fold_parent")
    x = np.asarray([[float(raw[candidate][name]) for name in raw_features] for candidate in ids], dtype=np.float64)
    truth = np.asarray([[float(strict[candidate]["truth_R8"]), float(strict[candidate]["truth_R9"])] for candidate in ids], dtype=np.float64)
    truth_dual = np.min(truth, axis=1)
    for i, candidate in enumerate(ids):
        require(abs(float(strict[candidate]["truth_Rdual_exact_min"]) - truth_dual[i]) <= 5e-8, f"truth_exact_min:{candidate}")
    weights = np.asarray([float(raw[candidate]["sample_weight"]) for candidate in ids], dtype=np.float64)
    l1_score = np.asarray([float(l1[candidate]["B_TOP5_L1__Rdual_exact_min"]) for candidate in ids], dtype=np.float64)
    id_to_index = {candidate: i for i, candidate in enumerate(ids)}
    aux_matrix = np.full((len(ids), len(aux_targets)), np.nan, dtype=np.float64)
    uncertainty = np.full(len(ids), np.nan, dtype=np.float64)
    for candidate, row in aux.items():
        index = id_to_index[candidate]
        aux_matrix[index] = [float(row[name]) for name in aux_targets]
        if row["multiseed_uncertainty_available"] == "1":
            uncertainty[index] = float(row["seed_dispersion_Rdual"])
    require(np.isfinite(x).all() and np.isfinite(truth).all() and np.isfinite(weights).all(), "nonfinite_core")
    require(np.isfinite(aux_matrix).all(axis=1).sum() == len(aux), "aux_nonfinite")
    return {
        "ids": ids, "parents": parents, "folds": folds, "x": x, "truth": truth, "truth_dual": truth_dual,
        "weights": weights, "l1": l1_score, "aux": aux_matrix, "uncertainty": uncertainty,
        "raw_features": raw_features, "aux_targets": aux_targets, "aux_rows": len(aux),
    }


def balanced_parent_folds(parents: np.ndarray, indices: np.ndarray, fold_count: int) -> list[np.ndarray]:
    groups: dict[str, list[int]] = {}
    for index in indices.tolist():
        groups.setdefault(str(parents[index]), []).append(index)
    require(len(groups) >= fold_count, f"inner_parent_count:{len(groups)}")
    bins: list[list[int]] = [[] for _ in range(fold_count)]
    loads = [0] * fold_count
    for parent, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        del parent
        target = min(range(fold_count), key=lambda value: (loads[value], value))
        bins[target].extend(members)
        loads[target] += len(members)
    return [np.asarray(sorted(members), dtype=np.int64) for members in bins]


def fit_aux(x: np.ndarray, y: np.ndarray, alpha: float) -> Any:
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
    model.fit(x, y)
    return model


def crossfit_aux(data: Mapping[str, Any], outer_train: np.ndarray, outer_test: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    x, y = data["x"], data["aux"]
    target_count = y.shape[1]
    train_predictions = np.full((len(outer_train), target_count), np.nan)
    train_uncertainty = np.full(len(outer_train), np.nan)
    position = {int(index): position for position, index in enumerate(outer_train.tolist())}
    inner_folds = balanced_parent_folds(data["parents"], outer_train, 4)
    audit: dict[str, Any] = {}
    for inner_fold, validation in enumerate(inner_folds):
        fit_indices = np.setdiff1d(outer_train, validation, assume_unique=False)
        aux_fit = fit_indices[np.isfinite(y[fit_indices]).all(axis=1)]
        require(len(aux_fit) >= 100 or len(outer_train) < 100, f"inner_aux_too_small:{inner_fold}:{len(aux_fit)}")
        aux_model = fit_aux(x[aux_fit], y[aux_fit], 100.0)
        predicted = aux_model.predict(x[validation])
        for row, index in enumerate(validation.tolist()):
            train_predictions[position[index]] = predicted[row]

        uncertainty_fit = fit_indices[np.isfinite(data["uncertainty"][fit_indices])]
        require(len(uncertainty_fit) >= 20 or len(outer_train) < 100, f"inner_uncertainty_too_small:{inner_fold}:{len(uncertainty_fit)}")
        uncertainty_model = fit_aux(x[uncertainty_fit], np.log1p(data["uncertainty"][uncertainty_fit]), 100.0)
        uncertainty_prediction = np.expm1(uncertainty_model.predict(x[validation])).clip(min=0.0)
        for row, index in enumerate(validation.tolist()):
            train_uncertainty[position[index]] = uncertainty_prediction[row]
        audit[str(inner_fold)] = {
            "fit_rows": len(fit_indices), "validation_rows": len(validation),
            "aux_fit_rows": len(aux_fit), "uncertainty_fit_rows": len(uncertainty_fit),
            "parent_overlap": len(set(data["parents"][fit_indices]) & set(data["parents"][validation])),
        }
    require(np.isfinite(train_predictions).all() and np.isfinite(train_uncertainty).all(), "inner_crossfit_incomplete")

    aux_fit = outer_train[np.isfinite(y[outer_train]).all(axis=1)]
    aux_model = fit_aux(x[aux_fit], y[aux_fit], 100.0)
    test_predictions = aux_model.predict(x[outer_test])
    uncertainty_fit = outer_train[np.isfinite(data["uncertainty"][outer_train])]
    uncertainty_model = fit_aux(x[uncertainty_fit], np.log1p(data["uncertainty"][uncertainty_fit]), 100.0)
    test_uncertainty = np.expm1(uncertainty_model.predict(x[outer_test])).clip(min=0.0)
    return train_predictions, test_predictions, train_uncertainty, test_uncertainty, audit


def top_weight(truth: np.ndarray, base: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(truth, kind="stable"), kind="stable")
    rank = order / max(1, len(order) - 1)
    multiplier = 1.0 + 3.0 / (1.0 + np.exp(-(rank - 0.85) / 0.05))
    return base * multiplier


def fit_ridge(x: np.ndarray, y: np.ndarray, weight: np.ndarray) -> Any:
    model = make_pipeline(StandardScaler(), Ridge(alpha=100.0))
    model.fit(x, y, ridge__sample_weight=weight)
    return model


def fit_hgb(x: np.ndarray, y: np.ndarray, weight: np.ndarray) -> list[HistGradientBoostingRegressor]:
    models: list[HistGradientBoostingRegressor] = []
    for column in range(2):
        model = HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=0.05, max_iter=200, max_depth=2,
            min_samples_leaf=30, l2_regularization=10.0, early_stopping=False, random_state=43,
        )
        model.fit(x, y[:, column], sample_weight=weight)
        models.append(model)
    return models


def predict_hgb(models: Sequence[HistGradientBoostingRegressor], x: np.ndarray) -> np.ndarray:
    return np.column_stack([model.predict(x) for model in models])


def average_rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1)
        start = end
    return ranks


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    a, b = average_rank(left), average_rank(right)
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def early_metric(ids: Sequence[str], truth: np.ndarray, score: np.ndarray, fraction: float) -> dict[str, float | int]:
    n = len(ids)
    selected = max(1, math.ceil(fraction * n))
    positives = max(1, math.ceil(0.10 * n))
    truth_order = sorted(range(n), key=lambda i: (-truth[i], ids[i]))
    score_order = sorted(range(n), key=lambda i: (-score[i], ids[i]))
    positive_set = set(truth_order[:positives])
    hits = sum(index in positive_set for index in score_order[:selected])
    precision = hits / selected
    return {
        "selected": selected, "positives": positives, "hits": hits, "precision": precision,
        "recall": hits / positives, "ef": precision / (positives / n),
    }


def metrics(data: Mapping[str, Any], score: np.ndarray) -> dict[str, Any]:
    pooled = early_metric(data["ids"], data["truth_dual"], score, 0.05)
    fold_ef: list[float] = []
    for fold in range(5):
        index = np.flatnonzero(data["folds"] == fold)
        fold_ef.append(float(early_metric([data["ids"][i] for i in index], data["truth_dual"][index], score[index], 0.05)["ef"]))
    return {
        "pooled_ef5": float(pooled["ef"]), "hits_at5": int(pooled["hits"]),
        "precision_at5": float(pooled["precision"]), "recall_at5": float(pooled["recall"]),
        "spearman": spearman(data["truth_dual"], score), "fold_ef5": fold_ef,
        "median_fold_ef5": float(np.median(fold_ef)), "worst_fold_ef5": float(np.min(fold_ef)),
    }


def run_oof(data: Mapping[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    n = len(data["ids"])
    scores = {method: np.full(n, np.nan) for method in METHODS}
    scores["A0_L1"][:] = data["l1"]
    audit: dict[str, Any] = {}
    for fold in range(5):
        outer_train = np.flatnonzero(data["folds"] != fold)
        outer_test = np.flatnonzero(data["folds"] == fold)
        overlap = set(data["parents"][outer_train]) & set(data["parents"][outer_test])
        require(not overlap, f"outer_parent_overlap:{fold}:{sorted(overlap)}")
        aux_train, aux_test, unc_train, unc_test, inner_audit = crossfit_aux(data, outer_train, outer_test)
        train_basic = np.column_stack((data["x"][outer_train], aux_train))
        test_basic = np.column_stack((data["x"][outer_test], aux_test))
        train_unc = np.column_stack((train_basic, unc_train))
        test_unc = np.column_stack((test_basic, unc_test))
        weights = top_weight(data["truth_dual"][outer_train], data["weights"][outer_train])

        ridge = fit_ridge(train_basic, data["truth"][outer_train], weights)
        ridge_prediction = ridge.predict(test_basic)
        scores["A1_RIDGE_AUX"][outer_test] = np.min(ridge_prediction, axis=1)
        hgb = fit_hgb(train_basic, data["truth"][outer_train], weights)
        scores["A2_HGB2_AUX"][outer_test] = np.min(predict_hgb(hgb, test_basic), axis=1)
        ridge_unc = fit_ridge(train_unc, data["truth"][outer_train], weights)
        scores["A3_RIDGE_AUX_UNCERTAINTY"][outer_test] = np.min(ridge_unc.predict(test_unc), axis=1)
        audit[str(fold)] = {
            "outer_train_rows": len(outer_train), "outer_test_rows": len(outer_test),
            "outer_parent_overlap": 0, "inner": inner_audit,
        }
    require(all(np.isfinite(score).all() for score in scores.values()), "oof_nonfinite")
    return scores, audit


def write_tsv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(raw: Path, strict: Path, l1: Path, aux: Path, output: Path) -> dict[str, Any]:
    require(not output.exists(), f"output_exists:{output}")
    data = load_data(raw, strict, l1, aux)
    scores, audit = run_oof(data)
    observed = {method: metrics(data, score) for method, score in scores.items()}
    selected = max(METHODS, key=lambda method: (observed[method]["pooled_ef5"], observed[method]["spearman"], -METHODS.index(method)))
    baseline = observed["A0_L1"]
    selected_metric = observed[selected]
    promoted = (
        selected != "A0_L1" and selected_metric["pooled_ef5"] >= 3.4
        and selected_metric["pooled_ef5"] - baseline["pooled_ef5"] >= 0.3
        and selected_metric["hits_at5"] >= 168
        and selected_metric["spearman"] >= baseline["spearman"] - 0.03
    )
    report = {
        "schema_version": SCHEMA, "status": "PASS_V2_18_STRICT_OOF", "methods": observed,
        "best_observed_method": selected, "promotion_pass": promoted,
        "goal_ef5_achieved": selected_metric["pooled_ef5"] >= 5.0 and selected_metric["hits_at5"] >= 247,
        "data": {"strict_rows": len(data["ids"]), "parents": len(set(data["parents"])), "pose_aux_rows": data["aux_rows"]},
        "crossfit_audit": audit,
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
        "claim_boundary": "Computational independent dual-receptor Docking-geometry surrogate enrichment only.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        rows = []
        for i, candidate in enumerate(data["ids"]):
            row: dict[str, object] = {
                "candidate_id": candidate, "parent_framework_cluster": data["parents"][i],
                "fold_id": int(data["folds"][i]), "truth_Rdual_exact_min": data["truth_dual"][i],
            }
            row.update({f"{method}__frontscreen_score": scores[method][i] for method in METHODS})
            rows.append(row)
        write_tsv(temp / "V2_18_POSE_AUX_OOF_PREDICTIONS.tsv", rows)
        (temp / "V2_18_POSE_AUX_METRICS.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (temp / "RUN_RECEIPT.json").write_text(json.dumps({
            "schema_version": SCHEMA, "status": report["status"], "best_observed_method": selected,
            "promotion_pass": promoted, "goal_ef5_achieved": report["goal_ef5_achieved"],
        }, indent=2, sort_keys=True) + "\n")
        os.replace(temp, output)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--strict-oof", type=Path, required=True)
    parser.add_argument("--l1-oof", type=Path, required=True)
    parser.add_argument("--pose-aux", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.raw, args.strict_oof, args.l1_oof, args.pose_aux, args.output_dir)
    print(json.dumps({
        "best": report["best_observed_method"],
        "ef5": report["methods"][report["best_observed_method"]]["pooled_ef5"],
        "promotion": report["promotion_pass"], "goal": report["goal_ef5_achieved"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
