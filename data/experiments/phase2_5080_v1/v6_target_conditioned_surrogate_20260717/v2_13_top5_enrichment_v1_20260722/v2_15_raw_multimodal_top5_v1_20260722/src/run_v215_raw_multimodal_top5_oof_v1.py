#!/usr/bin/env python3
"""Strict whole-parent OOF Top-5 enrichment from raw label-free multimodal features."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import pickle
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, HistGradientBoostingRegressor


SCHEMA = "pvrig_v2_15_raw_multimodal_top5_oof_v1"
CONTRACT_SCHEMA = "pvrig_v2_15_raw_multimodal_top5_contract_v1"
METHODS = (
    "G0_EQUAL_RANK4",
    "G1_HGB_TOP10_RAW",
    "G2_EXTRA_TREES_TOP10_RAW",
    "G3_HGB_R8R9_RAW",
    "G4_CLASSIFIER_MEAN",
    "G5_CLASSIFIER_BASE_BLEND",
)
CLAIM = "computational_independent_dual_receptor_Docking_geometry_only"


class V215Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise V215Error(message)


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


def percentile_from_train(train_values: np.ndarray, values: np.ndarray) -> np.ndarray:
    ordered = np.sort(np.asarray(train_values, dtype=np.float64))
    return np.searchsorted(ordered, np.asarray(values, dtype=np.float64), side="right") / max(1, len(ordered))


def percentile_rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    result = np.empty(len(values), dtype=np.float64)
    result[order] = (np.arange(len(values), dtype=np.float64) + 1.0) / len(values)
    return result


def rank_order(candidate_ids: Sequence[str], values: np.ndarray) -> list[int]:
    return sorted(range(len(values)), key=lambda i: (-float(values[i]), candidate_ids[i]))


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


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    lrank, rrank = rankdata(left), rankdata(right)
    return 0.0 if np.std(lrank) == 0.0 or np.std(rrank) == 0.0 else float(np.corrcoef(lrank, rrank)[0, 1])


def early_metric(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray, budget: float) -> dict[str, Any]:
    n = len(truth)
    positives, selected = max(1, math.ceil(0.10 * n)), max(1, math.ceil(budget * n))
    truth_set = set(rank_order(candidate_ids, truth)[:positives])
    predicted = rank_order(candidate_ids, score)[:selected]
    hits = len(truth_set & set(predicted))
    relevance = np.asarray([1.0 if i in truth_set else 0.0 for i in predicted])
    discounts = np.log2(np.arange(2, selected + 2, dtype=np.float64))
    ideal_n = min(positives, selected)
    ideal = float(np.sum(1.0 / np.log2(np.arange(2, ideal_n + 2, dtype=np.float64))))
    return {
        "selected": selected,
        "positives": positives,
        "hits": hits,
        "precision": hits / selected,
        "recall": hits / positives,
        "ef": (hits / selected) / (positives / n),
        "binary_ndcg": float(np.sum(relevance / discounts)) / ideal,
    }


def metrics(candidate_ids: Sequence[str], folds: np.ndarray, truth: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    at5, at10 = early_metric(candidate_ids, truth, score, 0.05), early_metric(candidate_ids, truth, score, 0.10)
    fold_ef5 = []
    for fold in sorted(set(folds.tolist())):
        idx = np.flatnonzero(folds == fold)
        fold_ef5.append(float(early_metric([candidate_ids[i] for i in idx], truth[idx], score[idx], 0.05)["ef"]))
    return {
        "pooled_ef5": float(at5["ef"]),
        "pooled_ef10": float(at10["ef"]),
        "hits_at5": int(at5["hits"]),
        "precision_at5": float(at5["precision"]),
        "recall_at5": float(at5["recall"]),
        "binary_ndcg_true_top10_at_budget5": float(at5["binary_ndcg"]),
        "spearman": spearman(truth, score),
        "fold_ef5": fold_ef5,
        "median_fold_ef5": float(np.median(fold_ef5)),
        "worst_fold_ef5": float(np.min(fold_ef5)),
    }


def raw_feature_names(header: Sequence[str]) -> list[str]:
    names = [name for name in header if name.startswith(("ALL__", "CDR1_", "CDR2_", "CDR3_", "CDR_ALL__", "FRAMEWORK__", "C2__"))]
    require(len(names) == len(set(names)), "raw_feature_duplicate")
    return names


def load_raw_firewalled(path: Path, allowed: set[str], expected_features: int) -> tuple[list[str], dict[str, np.ndarray], dict[str, float], int]:
    require(path.is_file() and not path.is_symlink(), f"raw_invalid:{path}")
    result: dict[str, np.ndarray] = {}
    weights: dict[str, float] = {}
    scanned = 0
    with path.open(encoding="utf-8") as handle:
        header_line = handle.readline().rstrip("\n")
        header = header_line.split("\t")
        require(header and header[0] == "candidate_id", "raw_candidate_first")
        features = raw_feature_names(header)
        require(len(features) == expected_features, f"raw_feature_count:{len(features)}")
        index = {name: header.index(name) for name in features}
        weight_index = header.index("sample_weight")
        for line in handle:
            scanned += 1
            candidate = line.split("\t", 1)[0]
            if candidate not in allowed:
                continue
            fields = line.rstrip("\n").split("\t")
            require(len(fields) == len(header), f"raw_field_count:{candidate}")
            vector = np.asarray([float(fields[index[name]]) for name in features], dtype=np.float64)
            require(np.isfinite(vector).all(), f"raw_nonfinite:{candidate}")
            require(candidate not in result, f"raw_duplicate:{candidate}")
            result[candidate] = vector
            weights[candidate] = float(fields[weight_index])
    require(set(result) == allowed, f"raw_candidate_closure:{len(result)}:{len(allowed)}")
    return features, result, weights, scanned


def load_inputs(raw_path: Path, assignment_path: Path, legacy_path: Path, l1_path: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    _, assignment_rows = read_tsv(assignment_path)
    assignment = {row["candidate_id"]: row for row in assignment_rows}
    expected = int(contract["data"]["expected_rows"])
    require(len(assignment) == len(assignment_rows) == expected, "assignment_closure")
    candidate_ids = sorted(assignment)
    features, raw, raw_weight, scanned = load_raw_firewalled(raw_path, set(candidate_ids), int(contract["data"]["expected_raw_numeric_features"]))
    _, legacy_rows = read_tsv(legacy_path)
    _, l1_rows = read_tsv(l1_path)
    legacy = {row["candidate_id"]: row for row in legacy_rows}
    l1 = {row["candidate_id"]: row for row in l1_rows}
    require(set(legacy) == set(l1) == set(candidate_ids), "oof_candidate_closure")
    parents = np.asarray([assignment[c]["parent_framework_cluster"] for c in candidate_ids])
    folds = np.asarray([int(assignment[c]["fold_id"]) for c in candidate_ids], dtype=np.int64)
    require(len(set(parents.tolist())) == int(contract["data"]["expected_parents"]), "parent_count")
    require(set(folds.tolist()) == set(range(int(contract["data"]["expected_folds"]))), "fold_set")
    raw_matrix = np.vstack([raw[c] for c in candidate_ids])
    base_columns = (
        "S0_MATCHED_ESM2_650M_PCA_ELASTICNET__R8", "S0_MATCHED_ESM2_650M_PCA_ELASTICNET__R9", "S0_MATCHED_ESM2_650M_PCA_ELASTICNET__Rdual_exact_min",
        "M2_STRUCTURE_ALPHA10__R8", "M2_STRUCTURE_ALPHA10__R9", "M2_STRUCTURE_ALPHA10__Rdual_exact_min",
        "C2_COARSE_POSE_PCA8__R8", "C2_COARSE_POSE_PCA8__R9", "C2_COARSE_POSE_PCA8__Rdual_exact_min",
    )
    base = np.asarray([[float(legacy[c][name]) for name in base_columns] for c in candidate_ids], dtype=np.float64)
    l1_columns = ("B_TOP5_L1__R8", "B_TOP5_L1__R9", "B_TOP5_L1__Rdual_exact_min")
    l1_matrix = np.asarray([[float(l1[c][name]) for name in l1_columns] for c in candidate_ids], dtype=np.float64)
    truth = np.asarray([[float(legacy[c]["truth_R8"]), float(legacy[c]["truth_R9"])] for c in candidate_ids], dtype=np.float64)
    for i, candidate in enumerate(candidate_ids):
        require(int(l1[candidate]["fold_id"]) == folds[i], f"l1_fold:{candidate}")
        require(abs(min(truth[i]) - float(l1[candidate]["truth_Rdual_exact_min"])) <= 4e-8, f"truth_mismatch:{candidate}")
    weights = np.asarray([raw_weight[c] for c in candidate_ids], dtype=np.float64)
    require(np.isfinite(raw_matrix).all() and np.isfinite(base).all() and np.isfinite(l1_matrix).all() and np.isfinite(truth).all(), "nonfinite_input")
    return {"candidate_ids": candidate_ids, "parents": parents, "folds": folds, "raw": raw_matrix, "base": base, "l1": l1_matrix, "truth": truth, "weights": weights, "raw_feature_names": features, "raw_rows_scanned": scanned}


def augmented_features(data: Mapping[str, Any], train: np.ndarray, idx: np.ndarray) -> np.ndarray:
    base, l1 = data["base"], data["l1"]
    rank_columns = []
    for column in (2, 5, 8):
        rank_columns.append(percentile_from_train(base[train, column], base[idx, column]))
    rank_columns.append(percentile_from_train(l1[train, 2], l1[idx, 2]))
    gaps = np.column_stack((np.abs(base[idx, 0]-base[idx, 1]), np.abs(base[idx, 3]-base[idx, 4]), np.abs(base[idx, 6]-base[idx, 7]), np.abs(l1[idx, 0]-l1[idx, 1])))
    result = np.column_stack((data["raw"][idx], base[idx], l1[idx], np.column_stack(rank_columns), gaps))
    require(result.shape[1] == data["raw"].shape[1] + 20, f"augmented_shape:{result.shape}")
    return result


def balanced_weights(base_weights: np.ndarray, labels: np.ndarray) -> np.ndarray:
    result = np.asarray(base_weights, dtype=np.float64).copy()
    positive = int(labels.sum())
    require(0 < positive < len(labels), "class_balance")
    result[labels == 1] *= len(labels) / (2.0 * positive)
    result[labels == 0] *= len(labels) / (2.0 * (len(labels)-positive))
    return result


def make_hgb_classifier(config: Mapping[str, Any]) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(loss="log_loss", learning_rate=float(config["learning_rate"]), max_iter=int(config["max_iter"]), max_leaf_nodes=int(config["max_leaf_nodes"]), min_samples_leaf=int(config["min_samples_leaf"]), l2_regularization=float(config["l2_regularization"]), early_stopping=False, random_state=43)


def make_extra_trees(config: Mapping[str, Any]) -> ExtraTreesClassifier:
    return ExtraTreesClassifier(n_estimators=int(config["n_estimators"]), max_depth=int(config["max_depth"]), min_samples_leaf=int(config["min_samples_leaf"]), max_features=float(config["max_features"]), n_jobs=int(config["n_jobs"]), bootstrap=False, random_state=43)


def make_hgb_regressor(config: Mapping[str, Any]) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss=str(config["loss"]), learning_rate=float(config["learning_rate"]), max_iter=int(config["max_iter"]), max_leaf_nodes=int(config["max_leaf_nodes"]), min_samples_leaf=int(config["min_samples_leaf"]), l2_regularization=float(config["l2_regularization"]), early_stopping=False, random_state=43)


def run_oof(data: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    n = len(data["candidate_ids"])
    scores = {name: np.full(n, np.nan, dtype=np.float64) for name in METHODS}
    models: dict[str, Any] = {}
    truth_dual = np.min(data["truth"], axis=1)
    for fold in range(int(contract["data"]["expected_folds"])):
        train = np.flatnonzero(data["folds"] != fold)
        test = np.flatnonzero(data["folds"] == fold)
        require(not (set(data["parents"][train]) & set(data["parents"][test])), f"parent_overlap:{fold}")
        train_x, test_x = augmented_features(data, train, train), augmented_features(data, train, test)
        threshold = np.sort(truth_dual[train])[-max(1, math.ceil(0.10 * len(train)))]
        labels = (truth_dual[train] >= threshold).astype(np.int64)
        weights = balanced_weights(data["weights"][train], labels)
        hgb = make_hgb_classifier(contract["hgb_classifier"])
        extra = make_extra_trees(contract["extra_trees"])
        hgb.fit(train_x, labels, sample_weight=weights)
        extra.fit(train_x, labels, sample_weight=weights)
        g1, g2 = hgb.predict_proba(test_x)[:, 1], extra.predict_proba(test_x)[:, 1]
        regressors = []
        regression = []
        for receptor in range(2):
            model = make_hgb_regressor(contract["hgb_regressor"])
            model.fit(train_x, data["truth"][train, receptor], sample_weight=data["weights"][train])
            regressors.append(model)
            regression.append(model.predict(test_x))
        g3 = np.minimum(regression[0], regression[1])
        base_dual = np.column_stack((data["base"][test, 2], data["base"][test, 5], data["base"][test, 8], data["l1"][test, 2]))
        train_dual = (data["base"][train, 2], data["base"][train, 5], data["base"][train, 8], data["l1"][train, 2])
        g0 = np.mean(np.column_stack([percentile_from_train(train_dual[j], base_dual[:, j]) for j in range(4)]), axis=1)
        g4 = 0.5 * percentile_rank(g1) + 0.5 * percentile_rank(g2)
        g5 = 0.70 * g4 + 0.30 * percentile_rank(g0)
        for name, values in zip(METHODS, (g0, g1, g2, g3, g4, g5)):
            scores[name][test] = values
        models[str(fold)] = {"hgb_classifier": hgb, "extra_trees": extra, "hgb_regressors": regressors, "train_rows": len(train), "test_rows": len(test)}
    require(all(np.isfinite(value).all() for value in scores.values()), "nonfinite_oof")
    return scores, models


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def run(contract_path: Path, raw_path: Path, assignment_path: Path, legacy_path: Path, l1_path: Path, output_dir: Path) -> dict[str, Any]:
    require(not output_dir.exists(), "output_exists")
    contract = json.loads(contract_path.read_text())
    require(contract.get("schema_version") == CONTRACT_SCHEMA and contract.get("status") == "FROZEN_BEFORE_V2_15_OOF_EXECUTION", "contract")
    bindings = contract["input_bindings"]
    for path, key in ((raw_path, "raw_multimodal_sha256"), (assignment_path, "assignment_sha256"), (legacy_path, "legacy_oof_sha256"), (l1_path, "l1_oof_sha256")):
        require(sha256_file(path) == bindings[key], f"input_hash:{key}")
    data = load_inputs(raw_path, assignment_path, legacy_path, l1_path, contract)
    require(data["raw_rows_scanned"] - len(data["candidate_ids"]) == int(contract["data"]["open_rows_excluded_before_value_parsing"]), "raw_firewall_excluded_count")
    scores, models = run_oof(data, contract)
    truth = np.min(data["truth"], axis=1)
    observed = {name: metrics(data["candidate_ids"], data["folds"], truth, score) for name, score in scores.items()}
    selected = max(METHODS, key=lambda name: (observed[name]["pooled_ef5"], observed[name]["binary_ndcg_true_top10_at_budget5"], observed[name]["median_fold_ef5"], observed[name]["worst_fold_ef5"], observed[name]["pooled_ef10"], observed[name]["spearman"], -METHODS.index(name)))
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        rows = []
        for i, candidate in enumerate(data["candidate_ids"]):
            row: dict[str, Any] = {"candidate_id": candidate, "parent_framework_cluster": data["parents"][i], "fold_id": int(data["folds"][i]), "truth_Rdual_exact_min": truth[i]}
            for name in METHODS:
                row[f"{name}__frontscreen_score"] = scores[name][i]
            rows.append(row)
        prediction = staging / "V2_15_RAW_MULTIMODAL_TOP5_OOF_PREDICTIONS.tsv"
        write_tsv(prediction, rows)
        report = {
            "schema_version": SCHEMA,
            "status": "PASS_V2_15_RAW_MULTIMODAL_TOP5_OOF",
            "claim_boundary": CLAIM,
            "counts": {"rows": len(rows), "parents": len(set(data["parents"])), "folds": len(set(data["folds"].tolist())), "raw_numeric_features": len(data["raw_feature_names"]), "raw_rows_scanned": data["raw_rows_scanned"]},
            "methods": observed,
            "selected_method": selected,
            "target_ef5": 5.0,
            "target_achieved_in_this_oof": observed[selected]["pooled_ef5"] >= 5.0,
            "feature_firewall": {"open_rows_excluded_before_value_parsing": data["raw_rows_scanned"]-len(rows), "candidate_id_is_model_input": False, "parent_id_is_model_input": False},
            "input_access": contract["input_access"],
        }
        metrics_path = staging / "V2_15_RAW_MULTIMODAL_TOP5_METRICS.json"
        metrics_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        with (staging / "V2_15_FOLD_MODELS.pkl").open("wb") as handle:
            pickle.dump({"schema_version": SCHEMA, "models": models, "raw_feature_names": data["raw_feature_names"]}, handle, pickle.HIGHEST_PROTOCOL)
        receipt = {"schema_version": SCHEMA, "status": report["status"], "selected_method": selected, "target_achieved_in_this_oof": report["target_achieved_in_this_oof"], "input_access": report["input_access"], "outputs": {}}
        for name in (prediction.name, metrics_path.name, "V2_15_FOLD_MODELS.pkl"):
            receipt["outputs"][name] = sha256_file(staging / name)
        (staging / "RUN_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        hashes = {path.name: sha256_file(path) for path in staging.iterdir() if path.is_file()}
        (staging / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())))
        os.replace(staging, output_dir)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--raw-multimodal", type=Path, required=True)
    parser.add_argument("--assignment", type=Path, required=True)
    parser.add_argument("--legacy-oof", type=Path, required=True)
    parser.add_argument("--l1-oof", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.contract, args.raw_multimodal, args.assignment, args.legacy_oof, args.l1_oof, args.output_dir)
    print(json.dumps({"status": result["status"], "selected_method": result["selected_method"], "ef5": result["methods"][result["selected_method"]]["pooled_ef5"], "target_achieved": result["target_achieved_in_this_oof"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
