#!/usr/bin/env python3
"""V2.9 variable-size, whole-parent sequence Stage0 training.

This is a versioned successor to the V2.7 open-inner baseline.  It preserves
the validated sequence-only feature and model families while removing frozen
row counts and the failed MLP/naive-mean branches.

The program consumes only an explicitly open teacher partition and pooled ESM2
embedding caches.  It predicts R_8X6B and R_9E6Y directly; R_dual is always
derived with an exact minimum.  It does not consume monomer structures,
Docking poses, contact labels, or sealed/frozen-test truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import torch
from scipy.stats import spearmanr
from sklearn.decomposition import PCA
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, ndcg_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler


SCHEMA = "pvrig_v2_9_sequence_stage0_expanded_v1"
SPLIT_SCHEMA = "pvrig_v2_9_whole_parent_split_v1"
PREFLIGHT_SCHEMA = "pvrig_v2_9_sequence_stage0_preflight_v1"
MULTISEED_SCHEMA = "pvrig_v2_9_sequence_stage0_multiseed_summary_v1"
CLAIM = (
    "Open-development sequence-only approximation of independent 8X6B/9E6Y "
    "computational Docking geometry; not binding, affinity, experimental "
    "blocking, Docking Gold, frozen-test, or formal validation evidence."
)
FORBIDDEN_PATH_TOKENS = (
    "v4_f", "test32", "outer_test", "outer-test", "sealed", "frozen_test",
    "frozen-test",
)
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
MODEL_NAMES = (
    "RIDGE_ESM2_650M",
    "RIDGE_ESM2_3B",
    "RIDGE_ESM2_650M_3B",
    "ELASTICNET_ESM2_650M_PCA",
)
DEFAULT_SEEDS = (43, 97, 193)


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
    return hashlib.sha256(
        ("\n".join(sorted(set(parents))) + "\n").encode()
    ).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    reject_forbidden_path(path, "json")
    require(path.is_file() and not path.is_symlink(), f"json_not_regular:{path}")
    payload = json.loads(path.read_text())
    require(isinstance(payload, dict), f"json_not_object:{path}")
    return payload


def parse_seeds(raw: str) -> tuple[int, ...]:
    try:
        values = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise RuntimeError("invalid_seed_list") from exc
    require(bool(values), "empty_seed_list")
    require(all(value >= 0 for value in values), "negative_seed")
    require(len(set(values)) == len(values), "duplicate_seed")
    return values


def _optional_expected_count(split: dict[str, Any], key: str, observed: int) -> None:
    if key in split:
        require(int(split[key]) == observed, f"{key}_mismatch:{observed}")


def load_rows(
    training_tsv: Path,
    split_manifest: Path,
    expected_training_sha256: str,
    expected_data_version: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load an open teacher partition and prove whole-parent closure.

    The TSV itself must contain only train and open-development score parents.
    Frozen parents must not be present and are not accepted as an exclusion
    list after the fact; this keeps sealed truth outside the process boundary.
    """
    reject_forbidden_path(training_tsv, "training")
    split = load_json(split_manifest)
    require(split.get("schema_version") == SPLIT_SCHEMA, "split_schema")
    require(split.get("data_version") == expected_data_version, "data_version_mismatch")
    require(split.get("open_only") is True, "split_not_open_only")
    require(split.get("frozen_test_access_count") == 0, "frozen_test_access_nonzero")
    require(split.get("sealed_truth_access_count", 0) == 0, "sealed_access_nonzero")
    require(isinstance(split.get("split_id"), str) and split["split_id"], "split_id_missing")
    require(len(expected_training_sha256) == 64, "expected_training_hash_invalid")
    require(sha256_file(training_tsv) == expected_training_sha256, "training_partition_hash_mismatch")
    require(split.get("training_tsv_sha256") == expected_training_sha256, "split_training_hash_mismatch")

    rows: list[dict[str, Any]] = []
    with training_tsv.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(INPUT_ALLOWLIST.issubset(set(reader.fieldnames or [])), "training_columns_missing")
        for raw in reader:
            row = {key: raw[key] for key in INPUT_ALLOWLIST}
            candidate_id = row["candidate_id"].strip()
            require(bool(candidate_id), "empty_candidate_id")
            row["candidate_id"] = candidate_id
            seq = row["sequence"].strip().upper()
            require(bool(seq) and set(seq) <= set(AA), f"invalid_sequence:{candidate_id}")
            require(
                hashlib.sha256(seq.encode("ascii")).hexdigest() == row["sequence_sha256"],
                f"sequence_hash:{candidate_id}",
            )
            r8 = float(row["R_8X6B"])
            r9 = float(row["R_9E6Y"])
            dual = float(row["R_dual_min"])
            weight = float(row["sample_weight"])
            require(all(math.isfinite(value) for value in (r8, r9, dual, weight)), f"nonfinite_numeric:{candidate_id}")
            require(weight > 0, f"nonpositive_sample_weight:{candidate_id}")
            require(abs(min(r8, r9) - dual) < 2e-8, f"truth_exact_min:{candidate_id}")
            row["sequence"] = seq
            row["R_8X6B"], row["R_9E6Y"], row["R_dual_min"] = r8, r9, dual
            row["sample_weight"] = weight
            rows.append(row)

    require(bool(rows), "empty_training_partition")
    train_parents = set(split.get("train_parents", []))
    score_parents = set(split.get("score_parents", []))
    frozen_test_parents = set(split.get("frozen_test_parents", []))
    require(len(train_parents) >= 2, "insufficient_train_parents")
    require(bool(score_parents), "empty_score_parents")
    require(bool(frozen_test_parents), "empty_frozen_test_parent_metadata")
    require(train_parents.isdisjoint(score_parents), "parent_overlap")
    require(train_parents.isdisjoint(frozen_test_parents), "train_frozen_parent_overlap")
    require(score_parents.isdisjoint(frozen_test_parents), "score_frozen_parent_overlap")
    require(stable_parent_hash(train_parents) == split.get("train_parent_set_sha256"), "train_parent_hash")
    require(stable_parent_hash(score_parents) == split.get("score_parent_set_sha256"), "score_parent_hash")
    require(
        stable_parent_hash(frozen_test_parents) == split.get("frozen_test_parent_set_sha256"),
        "frozen_test_parent_hash",
    )
    observed = {row["parent_framework_cluster"] for row in rows}
    require(observed == train_parents | score_parents, "partition_parent_closure")
    require(observed.isdisjoint(frozen_test_parents), "teacher_contains_frozen_parent")
    require(len({row["candidate_id"] for row in rows}) == len(rows), "duplicate_candidate")
    require(len({row["sequence_sha256"] for row in rows}) == len(rows), "duplicate_sequence")

    train_count = sum(row["parent_framework_cluster"] in train_parents for row in rows)
    score_count = len(rows) - train_count
    _optional_expected_count(split, "expected_total_rows", len(rows))
    _optional_expected_count(split, "expected_train_rows", train_count)
    _optional_expected_count(split, "expected_score_rows", score_count)
    return rows, split


def load_embedding_cache(
    cache_dir: Path,
    expected_sequence_sha256_by_candidate: dict[str, str],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Load a variable-size cache; extra label-free cache rows are permitted."""
    reject_forbidden_path(cache_dir, "embedding")
    receipt_path = cache_dir / "embedding_cache_receipt.json"
    receipt = load_json(receipt_path)
    require(receipt.get("schema_version") == "pvrig_v6_esm_embedding_cache_v1", "embedding_schema")
    require(isinstance(receipt.get("rows"), int) and receipt["rows"] > 0, "embedding_receipt_rows")
    require(isinstance(receipt.get("shards"), list) and receipt["shards"], "embedding_shards_missing")
    by_id: dict[str, np.ndarray] = {}
    by_sha: dict[str, str] = {}
    for item in receipt["shards"]:
        path = Path(item["path"])
        require(path.parent == cache_dir / "shards", "embedding_shard_outside_cache")
        require(path.is_file() and not path.is_symlink(), f"embedding_shard_not_regular:{path}")
        require(sha256_file(path) == item["sha256"], f"embedding_shard_hash:{path.name}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        ids = payload["metadata"]["candidate_ids"]
        sequence_hashes = payload["metadata"]["sequence_sha256"]
        values = payload["embeddings"].float().numpy()
        require(values.ndim == 2, f"embedding_shard_rank:{path.name}")
        require(values.shape[0] == len(ids) == len(sequence_hashes), f"embedding_shard_shape:{path.name}")
        for candidate_id, sequence_sha256, value in zip(ids, sequence_hashes, values):
            require(candidate_id not in by_id, f"duplicate_embedding:{candidate_id}")
            require(np.isfinite(value).all(), f"nonfinite_embedding:{candidate_id}")
            by_id[candidate_id] = value.astype(np.float32, copy=False)
            by_sha[candidate_id] = sequence_sha256
    require(receipt["rows"] == len(by_id), "embedding_receipt_row_count_mismatch")
    require(set(expected_sequence_sha256_by_candidate) <= set(by_id), "embedding_candidate_missing")
    for candidate_id, sequence_sha256 in expected_sequence_sha256_by_candidate.items():
        require(by_sha[candidate_id] == sequence_sha256, f"embedding_sequence_closure:{candidate_id}")
    loaded = dict(receipt)
    loaded["receipt_sha256"] = sha256_file(receipt_path)
    loaded["sequence_sha256_by_candidate"] = by_sha
    return by_id, loaded


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
            region = row[key].strip().upper()
            require(region and region in row["sequence"], f"cdr_not_in_sequence:{row['candidate_id']}:{key}")
            feature.extend(region_features(region))
        values.append(feature)
    array = np.asarray(values, dtype=np.float32)
    require(np.isfinite(array).all(), "physchem_nonfinite")
    return array


def exact_min(predictions: np.ndarray) -> np.ndarray:
    require(predictions.ndim == 2 and predictions.shape[1] == 2, "prediction_shape")
    return np.minimum(predictions[:, 0], predictions[:, 1])


def fit_scaled_ridge(
    x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float
) -> dict[str, Any]:
    scaler = StandardScaler().fit(x, sample_weight=weights)
    model = Ridge(alpha=alpha, solver="lsqr").fit(
        scaler.transform(x), y, sample_weight=weights
    )
    return {"scaler": scaler, "model": model, "alpha": alpha}


def predict_scaled(bundle: dict[str, Any], x: np.ndarray) -> np.ndarray:
    return np.asarray(
        bundle["model"].predict(bundle["scaler"].transform(x)), dtype=np.float64
    )


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    value = spearmanr(y_true, y_pred).statistic
    return float(value) if np.isfinite(value) else 0.0


def choose_ridge_alpha(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    groups: np.ndarray,
    alphas: tuple[float, ...],
) -> tuple[float, dict[str, Any]]:
    unique_groups = len(set(groups.tolist()))
    n_splits = min(4, unique_groups)
    require(n_splits >= 2, "insufficient_groups_for_cv")
    cv = GroupKFold(n_splits=n_splits)
    summary: dict[str, Any] = {}
    for alpha in alphas:
        fold_values = []
        for train, score in cv.split(x, y, groups):
            bundle = fit_scaled_ridge(x[train], y[train], weights[train], alpha)
            pred = predict_scaled(bundle, x[score])
            fold_values.append(spearman(exact_min(y[score]), exact_min(pred)))
        summary[str(alpha)] = {
            "fold_spearman": fold_values,
            "mean_spearman": float(np.mean(fold_values)),
        }
    selected = max(alphas, key=lambda value: (summary[str(value)]["mean_spearman"], -value))
    return selected, {"group_cv_splits": n_splits, "alphas": summary}


def fit_pca_features(
    embedding_train: np.ndarray,
    embedding_score: np.ndarray,
    phys_train: np.ndarray,
    phys_score: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    components = min(128, len(embedding_train) - 1, embedding_train.shape[1])
    require(components >= 1, "insufficient_rows_for_pca")
    pca = PCA(
        n_components=components,
        whiten=True,
        svd_solver="randomized",
        random_state=seed,
    )
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
        binary = np.asarray([1.0 if index in true_idx else 0.0 for index in range(n)])
        for budget in (0.05, 0.10, 0.20):
            selected = max(1, math.ceil(n * budget))
            predicted_idx = set(np.argsort(-y_score, kind="stable")[:selected].tolist())
            hits = len(true_idx & predicted_idx)
            precision = hits / selected
            result.append({
                "true_top_fraction": true_fraction,
                "predicted_budget_fraction": budget,
                "n": n,
                "positives": positives,
                "selected": selected,
                "hits": hits,
                "precision": precision,
                "recall": hits / positives,
                "enrichment_factor": precision / prevalence,
                "binary_ndcg": float(
                    ndcg_score(binary.reshape(1, -1), y_score.reshape(1, -1), k=selected)
                ),
            })
    return result


def within_parent_top20(
    rows: list[dict[str, Any]], y_true: np.ndarray, y_score: np.ndarray
) -> dict[str, Any]:
    by_parent: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_parent.setdefault(row["parent_framework_cluster"], []).append(index)
    details = []
    for parent, indices in sorted(by_parent.items()):
        k = max(1, math.ceil(len(indices) * 0.20))
        truth_order = sorted(indices, key=lambda i: (-y_true[i], i))[:k]
        pred_order = sorted(indices, key=lambda i: (-y_score[i], i))[:k]
        hits = len(set(truth_order) & set(pred_order))
        recall = hits / k
        prevalence = k / len(indices)
        details.append({
            "parent": parent,
            "n": len(indices),
            "k": k,
            "hits": hits,
            "recall": recall,
            "ef": recall / prevalence,
        })
    return {
        "macro_recall": float(np.mean([item["recall"] for item in details])),
        "macro_enrichment_factor": float(np.mean([item["ef"] for item in details])),
        "parents": details,
    }


def model_metrics(
    rows: list[dict[str, Any]], y: np.ndarray, pred: np.ndarray
) -> dict[str, Any]:
    dual_true = exact_min(y)
    dual_pred = exact_min(pred)
    return {
        "R8": {
            "spearman": spearman(y[:, 0], pred[:, 0]),
            "mae": float(mean_absolute_error(y[:, 0], pred[:, 0])),
            "rmse": float(mean_squared_error(y[:, 0], pred[:, 0]) ** 0.5),
        },
        "R9": {
            "spearman": spearman(y[:, 1], pred[:, 1]),
            "mae": float(mean_absolute_error(y[:, 1], pred[:, 1])),
            "rmse": float(mean_squared_error(y[:, 1], pred[:, 1]) ** 0.5),
        },
        "Rdual_exact_min": {
            "spearman": spearman(dual_true, dual_pred),
            "mae": float(mean_absolute_error(dual_true, dual_pred)),
            "rmse": float(mean_squared_error(dual_true, dual_pred) ** 0.5),
        },
        "early_enrichment": enrichment_table(dual_true, dual_pred),
        "within_parent_top20": within_parent_top20(rows, dual_true, dual_pred),
        "exact_min_violation_count": 0,
    }


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), "empty_tsv")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def build_preflight(
    training_tsv: Path,
    expected_training_sha256: str,
    split_manifest: Path,
    expected_data_version: str,
    esm2_650m_cache: Path,
    esm2_3b_cache: Path,
    seeds: tuple[int, ...],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any], dict[str, Any]]:
    rows, split = load_rows(
        training_tsv,
        split_manifest,
        expected_training_sha256,
        expected_data_version,
    )
    sequence_hashes = {row["candidate_id"]: row["sequence_sha256"] for row in rows}
    emb650, receipt650 = load_embedding_cache(esm2_650m_cache, sequence_hashes)
    emb3b, receipt3b = load_embedding_cache(esm2_3b_cache, sequence_hashes)
    train_parents = set(split["train_parents"])
    train_rows = [row for row in rows if row["parent_framework_cluster"] in train_parents]
    score_rows = [row for row in rows if row["parent_framework_cluster"] in set(split["score_parents"])]
    require(bool(train_rows) and bool(score_rows), "empty_train_or_score_partition")
    preflight = {
        "schema_version": PREFLIGHT_SCHEMA,
        "status": "PASS_PREFLIGHT",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": CLAIM,
        "data_version": expected_data_version,
        "split_id": split["split_id"],
        "total_rows": len(rows),
        "train_rows": len(train_rows),
        "score_rows": len(score_rows),
        "train_parent_count": len(train_parents),
        "score_parent_count": len(split["score_parents"]),
        "frozen_test_parent_metadata_count": len(split["frozen_test_parents"]),
        "frozen_test_parent_set_sha256": split["frozen_test_parent_set_sha256"],
        "teacher_frozen_parent_overlap_count": 0,
        "seeds": list(seeds),
        "model_names": list(MODEL_NAMES),
        "mlp_enabled": False,
        "naive_mean_enabled": False,
        "target_contract": "predict R8/R9 directly; derive Rdual with exact min",
        "training_tsv_sha256": expected_training_sha256,
        "split_manifest_sha256": sha256_file(split_manifest),
        "esm2_650m_cache_rows": receipt650["rows"],
        "esm2_650m_cache_receipt_sha256": receipt650["receipt_sha256"],
        "esm2_3b_cache_rows": receipt3b["rows"],
        "esm2_3b_cache_receipt_sha256": receipt3b["receipt_sha256"],
        "frozen_test_access_count": 0,
        "sealed_truth_access_count": 0,
    }
    return preflight, rows, split, emb650, emb3b, receipt650, receipt3b


def train_seed(
    *,
    seed: int,
    rows: list[dict[str, Any]],
    split: dict[str, Any],
    emb650: dict[str, np.ndarray],
    emb3b: dict[str, np.ndarray],
    output_dir: Path,
    training_tsv: Path,
    split_manifest: Path,
    receipt650: dict[str, Any],
    receipt3b: dict[str, Any],
    ridge_alphas: tuple[float, ...],
) -> dict[str, Any]:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    output_dir.mkdir(parents=True, exist_ok=False)
    train_parents = set(split["train_parents"])
    score_parents = set(split["score_parents"])
    train_rows = [row for row in rows if row["parent_framework_cluster"] in train_parents]
    score_rows = [row for row in rows if row["parent_framework_cluster"] in score_parents]

    phys = build_physchem(rows)
    phys_by_id = {row["candidate_id"]: phys[index] for index, row in enumerate(rows)}

    def matrix(selected: list[dict[str, Any]], cache: dict[str, np.ndarray]) -> np.ndarray:
        return np.stack([cache[row["candidate_id"]] for row in selected]).astype(np.float32)

    x650_train, x650_score = matrix(train_rows, emb650), matrix(score_rows, emb650)
    x3b_train, x3b_score = matrix(train_rows, emb3b), matrix(score_rows, emb3b)
    p_train = np.stack([phys_by_id[row["candidate_id"]] for row in train_rows])
    p_score = np.stack([phys_by_id[row["candidate_id"]] for row in score_rows])
    y_train = np.asarray([[row["R_8X6B"], row["R_9E6Y"]] for row in train_rows])
    y_score = np.asarray([[row["R_8X6B"], row["R_9E6Y"]] for row in score_rows])
    weights = np.asarray([row["sample_weight"] for row in train_rows])
    groups = np.asarray([row["parent_framework_cluster"] for row in train_rows])

    feature_sets = {
        "RIDGE_ESM2_650M": (
            np.concatenate((x650_train, p_train), axis=1),
            np.concatenate((x650_score, p_score), axis=1),
        ),
        "RIDGE_ESM2_3B": (
            np.concatenate((x3b_train, p_train), axis=1),
            np.concatenate((x3b_score, p_score), axis=1),
        ),
        "RIDGE_ESM2_650M_3B": (
            np.concatenate((x650_train, x3b_train, p_train), axis=1),
            np.concatenate((x650_score, x3b_score, p_score), axis=1),
        ),
    }
    predictions: dict[str, np.ndarray] = {}
    artifacts: dict[str, Any] = {}
    selection: dict[str, Any] = {}
    for name, (x_train, x_score) in feature_sets.items():
        alpha, cv = choose_ridge_alpha(x_train, y_train, weights, groups, ridge_alphas)
        bundle = fit_scaled_ridge(x_train, y_train, weights, alpha)
        predictions[name] = predict_scaled(bundle, x_score)
        artifacts[name] = bundle
        selection[name] = {"selected_alpha": alpha, "train_only_group_cv": cv}

    pca_train, pca_score, pca_artifacts = fit_pca_features(
        x650_train, x650_score, p_train, p_score, seed
    )
    elastic_models = []
    elastic_pred = []
    for target in range(2):
        model = ElasticNet(
            alpha=0.003,
            l1_ratio=0.10,
            max_iter=20000,
            tol=1e-6,
            random_state=seed,
        )
        model.fit(pca_train, y_train[:, target], sample_weight=weights)
        elastic_models.append(model)
        elastic_pred.append(model.predict(pca_score))
    predictions["ELASTICNET_ESM2_650M_PCA"] = np.column_stack(elastic_pred)
    artifacts["ELASTICNET_ESM2_650M_PCA"] = {"models": elastic_models, **pca_artifacts}
    require(tuple(predictions) == MODEL_NAMES, "model_contract_changed")

    metrics = {name: model_metrics(score_rows, y_score, pred) for name, pred in predictions.items()}
    prediction_rows = []
    for index, row in enumerate(score_rows):
        out = {
            "candidate_id": row["candidate_id"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "truth_R8": f"{y_score[index, 0]:.9f}",
            "truth_R9": f"{y_score[index, 1]:.9f}",
            "truth_Rdual_exact_min": f"{min(y_score[index]):.9f}",
        }
        for name, pred in predictions.items():
            out[f"{name}__R8"] = f"{pred[index, 0]:.9f}"
            out[f"{name}__R9"] = f"{pred[index, 1]:.9f}"
            out[f"{name}__Rdual_exact_min"] = f"{min(pred[index]):.9f}"
        prediction_rows.append(out)
    write_tsv(output_dir / "OPEN_SCORE_PREDICTIONS.tsv", prediction_rows)

    joblib.dump({
        "schema_version": SCHEMA,
        "claim_boundary": CLAIM,
        "seed": seed,
        "feature_contract": "ESM2 pooled whole/CDR1/CDR2/CDR3 plus sequence-derived physicochemical features only",
        "artifacts": artifacts,
        "base_model_names": list(MODEL_NAMES),
        "ensemble": None,
        "target_contract": "R8/R9 direct; Rdual exact min",
    }, output_dir / "SEQUENCE_STAGE0_MODELS.joblib", compress=3)

    result = {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_SEQUENCE_STAGE0_COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": CLAIM,
        "data_version": split["data_version"],
        "split_id": split["split_id"],
        "seed": seed,
        "train_rows": len(train_rows),
        "score_rows": len(score_rows),
        "train_parent_count": len(train_parents),
        "score_parent_count": len(score_parents),
        "model_names": list(MODEL_NAMES),
        "mlp_enabled": False,
        "naive_mean_enabled": False,
        "input_access": {
            "frozen_test": 0,
            "sealed_truth": 0,
            "candidate_monomer_structure": 0,
            "docking_pose_input": 0,
        },
        "inputs": {
            "training_tsv": str(training_tsv),
            "training_tsv_sha256": sha256_file(training_tsv),
            "split_manifest": str(split_manifest),
            "split_manifest_sha256": sha256_file(split_manifest),
            "esm2_650m_cache_receipt_sha256": receipt650["receipt_sha256"],
            "esm2_3b_cache_receipt_sha256": receipt3b["receipt_sha256"],
        },
        "model_selection": selection,
        "metrics": metrics,
        "projected_100k_budgets": {
            "top_5_percent": 5000,
            "top_10_percent": 10000,
            "top_20_percent": 20000,
        },
    }
    (output_dir / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    hashes = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            hashes[path.name] = sha256_file(path)
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in hashes.items())
    )
    return result


def build_multiseed_summary(
    results: list[dict[str, Any]], preflight: dict[str, Any]
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for model_name in MODEL_NAMES:
        values = [
            result["metrics"][model_name]["Rdual_exact_min"]["spearman"]
            for result in results
        ]
        metrics[model_name] = {
            "Rdual_spearman_by_seed": {
                str(result["seed"]): value for result, value in zip(results, values)
            },
            "Rdual_spearman_mean": float(np.mean(values)),
            "Rdual_spearman_std": float(np.std(values)),
        }
    return {
        "schema_version": MULTISEED_SCHEMA,
        "status": "PASS_MULTISEED_COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": CLAIM,
        "data_version": preflight["data_version"],
        "split_id": preflight["split_id"],
        "seeds": preflight["seeds"],
        "train_rows": preflight["train_rows"],
        "score_rows": preflight["score_rows"],
        "model_names": list(MODEL_NAMES),
        "metrics": metrics,
    }


def parse_alphas(raw: str) -> tuple[float, ...]:
    try:
        values = tuple(float(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise RuntimeError("invalid_alpha_list") from exc
    require(bool(values) and all(value > 0 for value in values), "invalid_alpha_list")
    require(len(set(values)) == len(values), "duplicate_alpha")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-tsv", type=Path, required=True)
    parser.add_argument("--expected-training-tsv-sha256", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--expected-data-version", choices=("D0", "D1"), required=True)
    parser.add_argument("--esm2-650m-cache", type=Path, required=True)
    parser.add_argument("--esm2-3b-cache", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    parser.add_argument("--ridge-alphas", default="1,10,100,1000")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-json", type=Path)
    args = parser.parse_args()

    seeds = parse_seeds(args.seeds)
    ridge_alphas = parse_alphas(args.ridge_alphas)
    for path, label in (
        (args.training_tsv, "training"),
        (args.split_manifest, "split"),
        (args.esm2_650m_cache, "650m"),
        (args.esm2_3b_cache, "3b"),
        (args.output_dir, "output"),
    ):
        reject_forbidden_path(path, label)
    if args.preflight_json:
        reject_forbidden_path(args.preflight_json, "preflight")

    preflight, rows, split, emb650, emb3b, receipt650, receipt3b = build_preflight(
        args.training_tsv,
        args.expected_training_tsv_sha256,
        args.split_manifest,
        args.expected_data_version,
        args.esm2_650m_cache,
        args.esm2_3b_cache,
        seeds,
    )
    if args.preflight_json:
        require(not args.preflight_json.exists(), "preflight_json_exists")
        args.preflight_json.parent.mkdir(parents=True, exist_ok=True)
        args.preflight_json.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n")
    if args.dry_run:
        require(not args.output_dir.exists(), "dry_run_output_exists")
        print(json.dumps(preflight, sort_keys=True))
        return

    require(not args.output_dir.exists(), "output_dir_exists")
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "PREFLIGHT.json").write_text(
        json.dumps(preflight, indent=2, sort_keys=True) + "\n"
    )
    results = []
    for seed in seeds:
        results.append(train_seed(
            seed=seed,
            rows=rows,
            split=split,
            emb650=emb650,
            emb3b=emb3b,
            output_dir=args.output_dir / f"seed_{seed}",
            training_tsv=args.training_tsv,
            split_manifest=args.split_manifest,
            receipt650=receipt650,
            receipt3b=receipt3b,
            ridge_alphas=ridge_alphas,
        ))
    summary = build_multiseed_summary(results, preflight)
    (args.output_dir / "MULTISEED_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    hashes = {}
    for path in sorted(args.output_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            hashes[path.name] = sha256_file(path)
    (args.output_dir / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in hashes.items())
    )
    print(json.dumps({
        "status": summary["status"],
        "data_version": summary["data_version"],
        "seeds": summary["seeds"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
