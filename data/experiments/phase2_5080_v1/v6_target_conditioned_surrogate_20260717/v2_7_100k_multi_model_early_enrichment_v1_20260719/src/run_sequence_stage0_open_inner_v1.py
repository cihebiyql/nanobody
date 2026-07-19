#!/usr/bin/env python3
"""Sequence-only open-inner early-enrichment baselines for PVRIG V2.7.

This program intentionally does not consume candidate monomer structures,
Docking poses, contact labels, V4-F/test32, or any outer-test truth/metrics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import torch
from scipy.stats import rankdata, spearmanr
from sklearn.decomposition import PCA
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, ndcg_score
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler


SCHEMA = "pvrig_v2_7_sequence_stage0_open_inner_v1"
CLAIM = (
    "Open-development sequence-only approximation of independent 8X6B/9E6Y "
    "computational Docking geometry; not binding, affinity, experimental "
    "blocking, Docking Gold, V4-F/test32, or outer-test evidence."
)
FORBIDDEN_PATH_TOKENS = ("v4_f", "test32", "outer_test", "outer-test", "sealed")
AA = "ACDEFGHIKLMNPQRSTVWY"
HYDROPHOBIC = set("AVILMFWY")
AROMATIC = set("FWY")
POSITIVE = set("KRH")
NEGATIVE = set("DE")
INPUT_ALLOWLIST = {
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster",
    "cdr1", "cdr2", "cdr3", "sample_weight", "R_8X6B", "R_9E6Y",
    "R_dual_min", "teacher_source", "teacher_reliability",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def reject_forbidden_path(path: Path, label: str) -> None:
    text = str(path).lower()
    for token in FORBIDDEN_PATH_TOKENS:
        require(token not in text, f"forbidden_{label}_path_token:{token}")


def stable_parent_hash(parents: Iterable[str]) -> str:
    # Canonical split-builder convention: sorted identifiers, one per line,
    # including a final newline.
    return hashlib.sha256(("\n".join(sorted(set(parents))) + "\n").encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    reject_forbidden_path(path, "json")
    require(path.is_file() and not path.is_symlink(), f"json_not_regular:{path}")
    return json.loads(path.read_text())


def load_rows(training_tsv: Path, split_manifest: Path, expected_training_sha256: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reject_forbidden_path(training_tsv, "training")
    split = load_json(split_manifest)
    require(split.get("open_only") is True, "split_not_open_only")
    require(split.get("split_id") == "outer_0_inner_0", "unexpected_split_id")
    require(split.get("v4_f_test32_access_count") == 0, "sealed_access_nonzero")
    require(len(expected_training_sha256) == 64, "expected_training_hash_invalid")
    require(sha256_file(training_tsv) == expected_training_sha256, "training_partition_hash_mismatch")
    # The split manifest binds the source 1507-row teacher, while this program
    # receives the already-filtered 1269-row inner partition.  Do not weaken
    # either identity by pretending the two files should have the same hash.
    require(len(str(split.get("training_tsv_sha256", ""))) == 64, "source_teacher_hash_missing")

    rows: list[dict[str, Any]] = []
    with training_tsv.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(INPUT_ALLOWLIST.issubset(set(reader.fieldnames or [])), "training_columns_missing")
        for raw in reader:
            row = {key: raw[key] for key in INPUT_ALLOWLIST}
            seq = row["sequence"].strip().upper()
            require(set(seq) <= set(AA), f"invalid_sequence:{row['candidate_id']}")
            require(hashlib.sha256(seq.encode("ascii")).hexdigest() == row["sequence_sha256"], f"sequence_hash:{row['candidate_id']}")
            require(abs(min(float(row["R_8X6B"]), float(row["R_9E6Y"])) - float(row["R_dual_min"])) < 2e-8, f"truth_exact_min:{row['candidate_id']}")
            row["sequence"] = seq
            for key in ("R_8X6B", "R_9E6Y", "R_dual_min", "sample_weight"):
                row[key] = float(row[key])
            rows.append(row)

    train_parents = set(split["train_parents"])
    score_parents = set(split["score_parents"])
    require(train_parents.isdisjoint(score_parents), "parent_overlap")
    require(stable_parent_hash(train_parents) == split["train_parent_set_sha256"], "train_parent_hash")
    require(stable_parent_hash(score_parents) == split["score_parent_set_sha256"], "score_parent_hash")
    observed = {r["parent_framework_cluster"] for r in rows}
    require(observed == train_parents | score_parents, "partition_parent_closure")
    require(all(r["parent_framework_cluster"] in train_parents | score_parents for r in rows), "unknown_parent")
    require(len({r["candidate_id"] for r in rows}) == len(rows), "duplicate_candidate")
    return rows, split


def load_embedding_cache(cache_dir: Path, expected_ids: set[str]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    reject_forbidden_path(cache_dir, "embedding")
    receipt_path = cache_dir / "embedding_cache_receipt.json"
    receipt = load_json(receipt_path)
    require(receipt.get("schema_version") == "pvrig_v6_esm_embedding_cache_v1", "embedding_schema")
    require(receipt.get("rows") == 1507, "embedding_row_count")
    by_id: dict[str, np.ndarray] = {}
    by_sha: dict[str, str] = {}
    for item in receipt["shards"]:
        path = Path(item["path"])
        require(path.parent == cache_dir / "shards", "embedding_shard_outside_cache")
        require(path.is_file() and not path.is_symlink(), f"embedding_shard_not_regular:{path}")
        require(sha256_file(path) == item["sha256"], f"embedding_shard_hash:{path.name}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        ids = payload["metadata"]["candidate_ids"]
        seq_hashes = payload["metadata"]["sequence_sha256"]
        values = payload["embeddings"].float().numpy()
        require(values.shape[0] == len(ids) == len(seq_hashes), f"embedding_shard_shape:{path.name}")
        for candidate_id, sequence_sha256, value in zip(ids, seq_hashes, values):
            require(candidate_id not in by_id, f"duplicate_embedding:{candidate_id}")
            require(np.isfinite(value).all(), f"nonfinite_embedding:{candidate_id}")
            by_id[candidate_id] = value.astype(np.float32, copy=False)
            by_sha[candidate_id] = sequence_sha256
    require(expected_ids <= set(by_id), "embedding_candidate_missing")
    receipt = dict(receipt)
    receipt["receipt_sha256"] = sha256_file(receipt_path)
    receipt["sequence_sha256_by_candidate"] = by_sha
    return by_id, receipt


def region_features(sequence: str) -> list[float]:
    n = len(sequence)
    require(n > 0, "empty_region")
    counts = {aa: sequence.count(aa) for aa in AA}
    probabilities = [counts[aa] / n for aa in AA]
    entropy = -sum(p * math.log(p + 1e-12) for p in probabilities) / math.log(len(AA))
    return [
        float(n),
        *probabilities,
        sum(counts[x] for x in HYDROPHOBIC) / n,
        sum(counts[x] for x in AROMATIC) / n,
        sum(counts[x] for x in POSITIVE) / n,
        sum(counts[x] for x in NEGATIVE) / n,
        (sum(counts[x] for x in POSITIVE) - sum(counts[x] for x in NEGATIVE)) / n,
        counts["G"] / n,
        counts["P"] / n,
        counts["C"] / n,
        entropy,
        max(counts.values()) / n,
    ]


def build_physchem(rows: list[dict[str, Any]]) -> np.ndarray:
    values = []
    for row in rows:
        feature = []
        for key in ("sequence", "cdr1", "cdr2", "cdr3"):
            region = row[key]
            require(region and region in row["sequence"], f"cdr_not_in_sequence:{row['candidate_id']}:{key}")
            feature.extend(region_features(region))
        values.append(feature)
    array = np.asarray(values, dtype=np.float32)
    require(np.isfinite(array).all(), "physchem_nonfinite")
    return array


def exact_min(predictions: np.ndarray) -> np.ndarray:
    require(predictions.ndim == 2 and predictions.shape[1] == 2, "prediction_shape")
    return np.minimum(predictions[:, 0], predictions[:, 1])


def fit_scaled_ridge(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> dict[str, Any]:
    scaler = StandardScaler().fit(x, sample_weight=weights)
    model = Ridge(alpha=alpha, solver="lsqr").fit(scaler.transform(x), y, sample_weight=weights)
    return {"scaler": scaler, "model": model, "alpha": alpha}


def predict_scaled(bundle: dict[str, Any], x: np.ndarray) -> np.ndarray:
    return np.asarray(bundle["model"].predict(bundle["scaler"].transform(x)), dtype=np.float64)


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    value = spearmanr(y_true, y_pred).statistic
    return float(value) if np.isfinite(value) else 0.0


def choose_ridge_alpha(x: np.ndarray, y: np.ndarray, weights: np.ndarray, groups: np.ndarray) -> tuple[float, dict[str, Any]]:
    alphas = (1.0, 10.0, 100.0, 1000.0)
    cv = GroupKFold(n_splits=4)
    summary: dict[str, Any] = {}
    for alpha in alphas:
        fold_values = []
        for train, score in cv.split(x, y, groups):
            bundle = fit_scaled_ridge(x[train], y[train], weights[train], alpha)
            pred = predict_scaled(bundle, x[score])
            fold_values.append(spearman(exact_min(y[score]), exact_min(pred)))
        summary[str(alpha)] = {"fold_spearman": fold_values, "mean_spearman": float(np.mean(fold_values))}
    selected = max(alphas, key=lambda a: (summary[str(a)]["mean_spearman"], -a))
    return selected, summary


def fit_pca_features(embedding_train: np.ndarray, embedding_score: np.ndarray, phys_train: np.ndarray, phys_score: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    components = min(128, len(embedding_train) - 1, embedding_train.shape[1])
    pca = PCA(n_components=components, whiten=True, svd_solver="randomized", random_state=seed)
    train_emb = pca.fit_transform(embedding_train)
    score_emb = pca.transform(embedding_score)
    train = np.concatenate((train_emb, phys_train), axis=1)
    score = np.concatenate((score_emb, phys_score), axis=1)
    scaler = StandardScaler().fit(train)
    return scaler.transform(train), scaler.transform(score), {"pca": pca, "scaler": scaler}


def enrichment_table(y_true: np.ndarray, y_score: np.ndarray) -> list[dict[str, Any]]:
    n = len(y_true)
    result = []
    for true_fraction in (0.10, 0.20):
        positives = max(1, math.ceil(n * true_fraction))
        true_idx = set(np.argsort(-y_true, kind="stable")[:positives].tolist())
        prevalence = positives / n
        binary = np.asarray([1.0 if i in true_idx else 0.0 for i in range(n)])
        for budget in (0.05, 0.10, 0.20):
            selected = max(1, math.ceil(n * budget))
            predicted_idx = set(np.argsort(-y_score, kind="stable")[:selected].tolist())
            hits = len(true_idx & predicted_idx)
            precision = hits / selected
            recall = hits / positives
            result.append({
                "true_top_fraction": true_fraction,
                "predicted_budget_fraction": budget,
                "n": n,
                "positives": positives,
                "selected": selected,
                "hits": hits,
                "precision": precision,
                "recall": recall,
                "enrichment_factor": precision / prevalence,
                "binary_ndcg": float(ndcg_score(binary.reshape(1, -1), y_score.reshape(1, -1), k=selected)),
            })
    return result


def within_parent_top20(rows: list[dict[str, Any]], y_true: np.ndarray, y_score: np.ndarray) -> dict[str, Any]:
    by_parent: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_parent.setdefault(row["parent_framework_cluster"], []).append(index)
    details = []
    for parent, indices in sorted(by_parent.items()):
        k = max(1, math.ceil(len(indices) * 0.20))
        truth_order = sorted(indices, key=lambda i: (-y_true[i], i))[:k]
        pred_order = sorted(indices, key=lambda i: (-y_score[i], i))[:k]
        hits = len(set(truth_order) & set(pred_order))
        precision = hits / k
        prevalence = k / len(indices)
        details.append({"parent": parent, "n": len(indices), "k": k, "hits": hits, "recall": precision, "ef": precision / prevalence})
    return {
        "macro_recall": float(np.mean([x["recall"] for x in details])),
        "macro_enrichment_factor": float(np.mean([x["ef"] for x in details])),
        "parents": details,
    }


def model_metrics(rows: list[dict[str, Any]], y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    dual_true = exact_min(y)
    dual_pred = exact_min(pred)
    return {
        "R8": {"spearman": spearman(y[:, 0], pred[:, 0]), "mae": float(mean_absolute_error(y[:, 0], pred[:, 0])), "rmse": float(mean_squared_error(y[:, 0], pred[:, 0]) ** 0.5)},
        "R9": {"spearman": spearman(y[:, 1], pred[:, 1]), "mae": float(mean_absolute_error(y[:, 1], pred[:, 1])), "rmse": float(mean_squared_error(y[:, 1], pred[:, 1]) ** 0.5)},
        "Rdual_exact_min": {"spearman": spearman(dual_true, dual_pred), "mae": float(mean_absolute_error(dual_true, dual_pred)), "rmse": float(mean_squared_error(dual_true, dual_pred) ** 0.5)},
        "early_enrichment": enrichment_table(dual_true, dual_pred),
        "within_parent_top20": within_parent_top20(rows, dual_true, dual_pred),
        "exact_min_violation_count": int(np.sum(np.abs(dual_pred - np.minimum(pred[:, 0], pred[:, 1])) > 0)),
    }


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), "empty_tsv")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-tsv", type=Path, required=True)
    parser.add_argument("--expected-training-tsv-sha256", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--esm2-650m-cache", type=Path, required=True)
    parser.add_argument("--esm2-3b-cache", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=43)
    args = parser.parse_args()

    for path, label in ((args.training_tsv, "training"), (args.split_manifest, "split"), (args.esm2_650m_cache, "650m"), (args.esm2_3b_cache, "3b"), (args.output_dir, "output")):
        reject_forbidden_path(path, label)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=False)

    rows, split = load_rows(args.training_tsv, args.split_manifest, args.expected_training_tsv_sha256)
    candidate_ids = {r["candidate_id"] for r in rows}
    emb650, receipt650 = load_embedding_cache(args.esm2_650m_cache, candidate_ids)
    emb3b, receipt3b = load_embedding_cache(args.esm2_3b_cache, candidate_ids)
    for row in rows:
        candidate = row["candidate_id"]
        require(receipt650["sequence_sha256_by_candidate"][candidate] == row["sequence_sha256"], f"650m_sequence_closure:{candidate}")
        require(receipt3b["sequence_sha256_by_candidate"][candidate] == row["sequence_sha256"], f"3b_sequence_closure:{candidate}")

    train_parents = set(split["train_parents"])
    train_rows = [r for r in rows if r["parent_framework_cluster"] in train_parents]
    score_rows = [r for r in rows if r["parent_framework_cluster"] in set(split["score_parents"])]
    require(len(train_rows) == 1085 and len(score_rows) == 184, "frozen_partition_counts")

    phys = build_physchem(rows)
    phys_by_id = {r["candidate_id"]: phys[i] for i, r in enumerate(rows)}
    def matrix(selected: list[dict[str, Any]], cache: dict[str, np.ndarray]) -> np.ndarray:
        return np.stack([cache[r["candidate_id"]] for r in selected]).astype(np.float32)
    x650_train, x650_score = matrix(train_rows, emb650), matrix(score_rows, emb650)
    x3b_train, x3b_score = matrix(train_rows, emb3b), matrix(score_rows, emb3b)
    p_train = np.stack([phys_by_id[r["candidate_id"]] for r in train_rows])
    p_score = np.stack([phys_by_id[r["candidate_id"]] for r in score_rows])
    y_train = np.asarray([[r["R_8X6B"], r["R_9E6Y"]] for r in train_rows])
    y_score = np.asarray([[r["R_8X6B"], r["R_9E6Y"]] for r in score_rows])
    weights = np.asarray([r["sample_weight"] for r in train_rows])
    groups = np.asarray([r["parent_framework_cluster"] for r in train_rows])

    feature_sets = {
        "RIDGE_ESM2_650M": (np.concatenate((x650_train, p_train), axis=1), np.concatenate((x650_score, p_score), axis=1)),
        "RIDGE_ESM2_3B": (np.concatenate((x3b_train, p_train), axis=1), np.concatenate((x3b_score, p_score), axis=1)),
        "RIDGE_ESM2_650M_3B": (np.concatenate((x650_train, x3b_train, p_train), axis=1), np.concatenate((x650_score, x3b_score, p_score), axis=1)),
    }
    predictions: dict[str, np.ndarray] = {}
    artifacts: dict[str, Any] = {}
    selection: dict[str, Any] = {}
    for name, (x_train, x_score) in feature_sets.items():
        alpha, cv = choose_ridge_alpha(x_train, y_train, weights, groups)
        bundle = fit_scaled_ridge(x_train, y_train, weights, alpha)
        predictions[name] = predict_scaled(bundle, x_score)
        artifacts[name] = bundle
        selection[name] = {"selected_alpha": alpha, "train_only_group_cv": cv}

    pca_train, pca_score, pca_artifacts = fit_pca_features(x650_train, x650_score, p_train, p_score, args.seed)
    elastic_models = []
    elastic_pred = []
    for target in range(2):
        model = ElasticNet(alpha=0.003, l1_ratio=0.10, max_iter=20000, tol=1e-6, random_state=args.seed)
        model.fit(pca_train, y_train[:, target], sample_weight=weights)
        elastic_models.append(model)
        elastic_pred.append(model.predict(pca_score))
    predictions["ELASTICNET_ESM2_650M_PCA"] = np.column_stack(elastic_pred)
    artifacts["ELASTICNET_ESM2_650M_PCA"] = {"models": elastic_models, **pca_artifacts}

    mlp = MLPRegressor(hidden_layer_sizes=(96, 32), activation="relu", solver="adam", alpha=0.01, batch_size=64, learning_rate_init=5e-4, max_iter=400, early_stopping=False, random_state=args.seed)
    mlp.fit(pca_train, y_train)
    predictions["MLP_ESM2_650M_PCA"] = np.asarray(mlp.predict(pca_score))
    artifacts["MLP_ESM2_650M_PCA"] = {"model": mlp, **pca_artifacts}

    base_names = list(predictions)
    predictions["MEAN_5MODEL"] = np.mean(np.stack([predictions[name] for name in base_names]), axis=0)

    metrics = {name: model_metrics(score_rows, y_score, pred) for name, pred in predictions.items()}
    overlap: dict[str, Any] = {}
    for fraction in (0.05, 0.10, 0.20):
        k = max(1, math.ceil(len(score_rows) * fraction))
        top = {name: set(np.argsort(-exact_min(pred), kind="stable")[:k].tolist()) for name, pred in predictions.items()}
        overlap[str(fraction)] = {
            a: {b: len(top[a] & top[b]) / k for b in top} for a in top
        }

    prediction_rows = []
    for index, row in enumerate(score_rows):
        out = {
            "candidate_id": row["candidate_id"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "truth_R8": f"{y_score[index,0]:.9f}",
            "truth_R9": f"{y_score[index,1]:.9f}",
            "truth_Rdual_exact_min": f"{min(y_score[index]):.9f}",
        }
        for name, pred in predictions.items():
            out[f"{name}__R8"] = f"{pred[index,0]:.9f}"
            out[f"{name}__R9"] = f"{pred[index,1]:.9f}"
            out[f"{name}__Rdual_exact_min"] = f"{min(pred[index]):.9f}"
        prediction_rows.append(out)
    write_tsv(args.output_dir / "OPEN_INNER_SCORE_PREDICTIONS.tsv", prediction_rows)

    model_bundle = {
        "schema_version": SCHEMA,
        "claim_boundary": CLAIM,
        "feature_contract": "ESM2 pooled whole/CDR1/CDR2/CDR3 plus sequence-derived physicochemical features only",
        "artifacts": artifacts,
        "base_model_names": base_names,
        "ensemble": "arithmetic mean of base R8/R9 followed by exact min",
    }
    joblib.dump(model_bundle, args.output_dir / "SEQUENCE_STAGE0_MODELS.joblib", compress=3)

    result = {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_INNER_SEQUENCE_STAGE0_COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": CLAIM,
        "split_id": split["split_id"],
        "train_rows": len(train_rows),
        "score_rows": len(score_rows),
        "train_parent_count": len(split["train_parents"]),
        "score_parent_count": len(split["score_parents"]),
        "input_access": {"v4_f_test32": 0, "outer_test_truth": 0, "outer_test_metrics": 0, "candidate_monomer_structure": 0, "docking_pose_input": 0},
        "inputs": {
            "training_tsv": str(args.training_tsv), "training_tsv_sha256": sha256_file(args.training_tsv),
            "source_teacher_sha256_from_split_manifest": split["training_tsv_sha256"],
            "split_manifest": str(args.split_manifest), "split_manifest_sha256": sha256_file(args.split_manifest),
            "esm2_650m_cache_receipt_sha256": receipt650["receipt_sha256"],
            "esm2_3b_cache_receipt_sha256": receipt3b["receipt_sha256"],
        },
        "input_column_allowlist": sorted(INPUT_ALLOWLIST),
        "model_selection": selection,
        "metrics": metrics,
        "topk_overlap_fraction": overlap,
        "projected_100k_budgets": {"top_5_percent": 5000, "top_10_percent": 10000, "top_20_percent": 20000},
    }
    (args.output_dir / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    best_spearman = max(metrics, key=lambda name: metrics[name]["Rdual_exact_min"]["spearman"])
    lines = [
        "# V2.7 Stage 0 open-inner 结果", "",
        f"状态：`{result['status']}`", "",
        f"数据：{len(train_rows)} train / {len(score_rows)} score；whole-parent 隔离为 {len(split['train_parents'])} / {len(split['score_parents'])} 个 parent。", "",
        "## 连续预测", "", "| 模型 | Rdual Spearman | MAE | RMSE |", "|---|---:|---:|---:|",
    ]
    for name, value in metrics.items():
        d = value["Rdual_exact_min"]
        lines.append(f"| {name} | {d['spearman']:.4f} | {d['mae']:.4f} | {d['rmse']:.4f} |")
    lines += ["", f"当前 split 上 Spearman 最高的是 `{best_spearman}`。该选择是 open-development 观察，不是 formal test 结论。", "", "## 早期富集", ""]
    for name, value in metrics.items():
        lines += [f"### {name}", "", "| 真值正类 | 预测预算 | hits | recall | precision | EF |", "|---|---:|---:|---:|---:|---:|"]
        for item in value["early_enrichment"]:
            lines.append(f"| Top{int(item['true_top_fraction']*100)}% | Top{int(item['predicted_budget_fraction']*100)}% | {item['hits']} | {item['recall']:.3f} | {item['precision']:.3f} | {item['enrichment_factor']:.2f}x |")
        lines.append("")
    lines += [
        "## 边界", "",
        "本结果只验证 sequence-only 模型对 computational Docking geometry 的早期富集能力；不代表结合或实验阻断。",
        "V4-F/test32、outer-test truth/metrics、候选单体结构和 Docking pose 输入访问计数均为 0。", "",
        "## 100k 推理", "",
        "缓存 embedding 后，线性模型/浅层 MLP 的打分成本远低于 Docking。建议后续以固定模型集成 + 多样性配额产生 5,000–10,000 条首轮 Docking shortlist，再用新增 Docking teacher 进行主动学习。", "",
    ]
    (args.output_dir / "REPORT_ZH.md").write_text("\n".join(lines))

    output_hashes = {}
    for path in sorted(args.output_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            output_hashes[path.name] = sha256_file(path)
    (args.output_dir / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in output_hashes.items()))
    print(json.dumps({"status": result["status"], "output_dir": str(args.output_dir), "best_spearman_model": best_spearman}, sort_keys=True))


if __name__ == "__main__":
    main()
