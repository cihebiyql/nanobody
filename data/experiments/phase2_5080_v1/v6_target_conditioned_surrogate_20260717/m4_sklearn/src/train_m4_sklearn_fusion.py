#!/usr/bin/env python3
"""Nested whole-parent sklearn baselines for the PVRIG V6 Docking surrogate."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


CLAIM = (
    "Development approximation of independent dual-receptor computational Docking "
    "geometry; not binding, affinity, competition, experimental blocking, or Docking Gold."
)
METADATA = {
    "schema_version", "candidate_id", "sequence_sha256", "sequence",
    "parent_framework_cluster", "target_patch_id", "design_mode", "cdr1", "cdr2", "cdr3",
    "teacher_source", "teacher_reliability", "sample_weight", "outer_fold",
    "R_8X6B", "R_9E6Y", "R_dual_min", "teacher_uncertainty",
    "monomer_sha256", "technical_reasons", "claim_boundary",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_lines(lines: list[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def atomic_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), f"empty_tsv_output:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def average_ranks(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * ((start + 1) + end)
        start = end
    return ranks


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    left_rank = average_ranks(left)
    right_rank = average_ranks(right)
    if len(left_rank) < 2 or np.std(left_rank) == 0 or np.std(right_rank) == 0:
        return 0.0
    value = float(np.corrcoef(left_rank, right_rank)[0, 1])
    return value if math.isfinite(value) else 0.0


def metrics(target: np.ndarray, prediction: np.ndarray, parents: list[str]) -> dict[str, float | int]:
    target = np.asarray(target, dtype=np.float64)
    prediction = np.asarray(prediction, dtype=np.float64)
    require(len(target) >= 3 and len(target) == len(prediction) == len(parents), "metric_row_mismatch")
    centered_target = target.copy()
    centered_prediction = prediction.copy()
    parent_values: list[float] = []
    parent_array = np.asarray(parents)
    for parent in sorted(set(parents)):
        indices = np.flatnonzero(parent_array == parent)
        centered_target[indices] -= centered_target[indices].mean()
        centered_prediction[indices] -= centered_prediction[indices].mean()
        if len(indices) >= 3 and np.std(target[indices]) > 0 and np.std(prediction[indices]) > 0:
            parent_values.append(spearman(target[indices], prediction[indices]))
    budget = max(1, math.ceil(0.2 * len(target)))
    truth_threshold = float(np.sort(target)[-budget])
    prediction_threshold = float(np.sort(prediction)[-budget])
    truth = set(np.flatnonzero(target >= truth_threshold).tolist())
    chosen = set(np.flatnonzero(prediction >= prediction_threshold).tolist())
    return {
        "spearman": spearman(target, prediction),
        "parent_centered_spearman": spearman(centered_target, centered_prediction),
        "macro_parent_spearman": float(np.mean(parent_values)) if parent_values else 0.0,
        "macro_parent_groups": len(parent_values),
        "mae": float(np.mean(np.abs(target - prediction))),
        "top20_recall": len(truth & chosen) / len(truth),
        "top20_truth_rows_tie_inclusive": len(truth),
        "top20_predicted_rows_tie_inclusive": len(chosen),
    }


def selection_key(value: dict[str, float | int]) -> tuple[float, float, float, float]:
    return (
        float(value["spearman"]),
        float(value["parent_centered_spearman"]),
        float(value["top20_recall"]),
        -float(value["mae"]),
    )


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def resolve_shard(root: Path, recorded: str) -> Path:
    path = Path(recorded)
    candidates = [path, root / path, root / "shards" / path.name]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise ValueError(f"embedding_shard_missing:{recorded}")


def load_embedding_cache(root: Path) -> tuple[dict[str, np.ndarray], dict[str, str], dict[str, Any], str]:
    receipt_path = root / "embedding_cache_receipt.json"
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "embedding_receipt_missing_or_symlink")
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get("status") == "PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE", "embedding_receipt_status")
    mapping: dict[str, np.ndarray] = {}
    sequence_hashes: dict[str, str] = {}
    total = 0
    expected_dimension = int(receipt["embedding_dimension"])
    for item in receipt.get("shards", []):
        path = resolve_shard(root, str(item["path"]))
        require(sha256_file(path) == item.get("sha256"), f"embedding_shard_hash:{path}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        metadata = payload.get("metadata", {})
        identifiers = list(metadata.get("candidate_ids", []))
        hashes = list(metadata.get("sequence_sha256", []))
        values = payload["embeddings"].detach().cpu().float().numpy()
        require(values.ndim == 2 and values.shape[1] == expected_dimension, f"embedding_shape:{path}")
        require(len(identifiers) == len(hashes) == len(values) == int(item["rows"]), f"embedding_rows:{path}")
        for candidate, sequence_hash, vector in zip(identifiers, hashes, values):
            require(candidate not in mapping, f"duplicate_embedding:{candidate}")
            mapping[candidate] = np.asarray(vector, dtype=np.float32)
            sequence_hashes[candidate] = str(sequence_hash)
        total += len(values)
    require(total == int(receipt["rows"]) == len(mapping), "embedding_receipt_row_count")
    return mapping, sequence_hashes, receipt, sha256_file(receipt_path)


@dataclass
class Arrays:
    candidate_ids: list[str]
    sequence_hashes: list[str]
    parents: list[str]
    sources: list[str]
    folds: np.ndarray
    embeddings: np.ndarray
    structure: np.ndarray
    target: np.ndarray
    weights: np.ndarray
    feature_names: list[str]
    input_sha256: str
    table_receipt_sha256: str
    embedding_receipt_sha256: str
    embedding_shard_hashes: list[str]
    split_manifest_sha256: str
    feature_names_sha256: str
    training_fingerprint: str


def load_validated_arrays(
    input_path: Path,
    table_receipt_path: Path,
    embedding_root: Path,
    expected_outer_folds: int,
) -> Arrays:
    require(input_path.is_file() and not input_path.is_symlink(), "training_table_missing_or_symlink")
    require(table_receipt_path.is_file() and not table_receipt_path.is_symlink(), "table_receipt_missing_or_symlink")
    fields, rows = read_table(input_path)
    require(bool(rows), "empty_training_table")
    input_sha256 = sha256_file(input_path)
    table_receipt = json.loads(table_receipt_path.read_text())
    require(table_receipt.get("status") == "PASS_V6_TRAINING_TABLE_MATERIALIZED", "table_receipt_status")
    require(table_receipt.get("output_sha256", {}).get("supervised") == input_sha256, "table_receipt_input_hash")
    embedding_map, embedding_hashes, embedding_receipt, embedding_receipt_sha256 = load_embedding_cache(embedding_root)
    require(embedding_receipt.get("input_sha256") == input_sha256, "embedding_receipt_input_hash")
    identifiers = [row["candidate_id"] for row in rows]
    require(len(identifiers) == len(set(identifiers)), "duplicate_training_candidate")
    require(set(identifiers) == set(embedding_map), "embedding_candidate_exact_closure")
    parent_fold: dict[str, int] = {}
    sequence_fold: dict[str, int] = {}
    for row in rows:
        candidate = row["candidate_id"]
        actual = hashlib.sha256(row["sequence"].encode()).hexdigest()
        require(actual == row["sequence_sha256"] == embedding_hashes[candidate], f"sequence_hash:{candidate}")
        fold = int(row["outer_fold"])
        parent = row["parent_framework_cluster"]
        require(parent not in parent_fold or parent_fold[parent] == fold, f"parent_cross_outer_fold:{parent}")
        require(actual not in sequence_fold or sequence_fold[actual] == fold, f"sequence_cross_outer_fold:{actual}")
        parent_fold[parent] = fold
        sequence_fold[actual] = fold
    folds = {int(row["outer_fold"]) for row in rows}
    require(folds == set(range(expected_outer_folds)), f"outer_fold_closure:{sorted(folds)}")
    feature_names = [name for name in fields if name not in METADATA]
    require(len(feature_names) == 126, f"structure_feature_count:{len(feature_names)}")
    structure = np.asarray([[float(row[name]) for name in feature_names] for row in rows], dtype=np.float64)
    embeddings = np.stack([embedding_map[row["candidate_id"]] for row in rows]).astype(np.float64)
    target = np.asarray([float(row["R_dual_min"]) for row in rows], dtype=np.float64)
    weights = np.asarray([float(row["sample_weight"]) for row in rows], dtype=np.float64)
    require(np.isfinite(structure).all() and np.isfinite(embeddings).all(), "nonfinite_features")
    require(np.isfinite(target).all() and np.isfinite(weights).all() and np.all(weights > 0), "nonfinite_target_or_weight")
    feature_names_sha256 = hashlib.sha256("\n".join(feature_names).encode()).hexdigest()
    split_lines = sorted(
        f"{row['candidate_id']}\t{row['sequence_sha256']}\t{row['parent_framework_cluster']}\t{row['outer_fold']}"
        for row in rows
    )
    split_manifest_sha256 = sha256_lines(split_lines)
    fingerprint_payload = {
        "input_sha256": input_sha256,
        "table_receipt_sha256": sha256_file(table_receipt_path),
        "embedding_receipt_sha256": embedding_receipt_sha256,
        "embedding_shards": [item["sha256"] for item in embedding_receipt["shards"]],
        "split_manifest_sha256": split_manifest_sha256,
        "feature_names_sha256": feature_names_sha256,
        "rows": len(rows),
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode()).hexdigest()
    return Arrays(
        candidate_ids=identifiers,
        sequence_hashes=[row["sequence_sha256"] for row in rows],
        parents=[row["parent_framework_cluster"] for row in rows],
        sources=[row["teacher_source"] for row in rows],
        folds=np.asarray([int(row["outer_fold"]) for row in rows], dtype=np.int64),
        embeddings=embeddings,
        structure=structure,
        target=target,
        weights=weights,
        feature_names=feature_names,
        input_sha256=input_sha256,
        table_receipt_sha256=sha256_file(table_receipt_path),
        embedding_receipt_sha256=embedding_receipt_sha256,
        embedding_shard_hashes=[str(item["sha256"]) for item in embedding_receipt["shards"]],
        split_manifest_sha256=split_manifest_sha256,
        feature_names_sha256=feature_names_sha256,
        training_fingerprint=fingerprint,
    )


def balanced_parent_assignment(parents: list[str], folds: int, salt: str) -> np.ndarray:
    unique = sorted(set(parents), key=lambda parent: hashlib.sha256(f"{salt}|{parent}".encode()).hexdigest())
    observed = min(int(folds), len(unique))
    require(observed >= 2, f"too_few_parent_folds:{len(unique)}")
    assignment = {parent: index % observed for index, parent in enumerate(unique)}
    result = np.asarray([assignment[parent] for parent in parents], dtype=np.int64)
    for parent in unique:
        require(len(set(result[index] for index, value in enumerate(parents) if value == parent)) == 1, "inner_parent_split")
    return result


@dataclass
class M2Model:
    scaler: StandardScaler
    ridge: Ridge

    def predict(self, structure: np.ndarray) -> np.ndarray:
        return np.asarray(self.ridge.predict(self.scaler.transform(structure)), dtype=np.float64)


def fit_m2(structure: np.ndarray, target: np.ndarray, weights: np.ndarray, alpha: float) -> M2Model:
    scaler = StandardScaler().fit(structure)
    ridge = Ridge(alpha=float(alpha), fit_intercept=True)
    ridge.fit(scaler.transform(structure), target, sample_weight=weights)
    return M2Model(scaler, ridge)


def crossfit_m2(
    indices: np.ndarray,
    arrays: Arrays,
    alpha: float,
    inner_folds: int,
    salt: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    local_parents = [arrays.parents[index] for index in indices]
    assignments = balanced_parent_assignment(local_parents, inner_folds, salt)
    prediction = np.full(len(indices), np.nan, dtype=np.float64)
    records = []
    for fold in sorted(set(assignments.tolist())):
        held = assignments == fold
        keep = ~held
        model = fit_m2(arrays.structure[indices[keep]], arrays.target[indices[keep]], arrays.weights[indices[keep]], alpha)
        prediction[held] = model.predict(arrays.structure[indices[held]])
        records.append({
            "fold": int(fold),
            "train_rows": int(keep.sum()),
            "held_rows": int(held.sum()),
            "train_parents": len(set(local_parents[index] for index in np.flatnonzero(keep))),
            "held_parents": len(set(local_parents[index] for index in np.flatnonzero(held))),
        })
    require(np.isfinite(prediction).all(), "nonfinite_crossfit_m2")
    return prediction, {
        "assignment": "sha256 salt ordering then balanced round-robin; whole parent",
        "salt": salt,
        "folds": records,
    }


@dataclass
class FusionTransformer:
    pca: PCA
    structure_scaler: StandardScaler
    base_scaler: StandardScaler

    def transform(self, embeddings: np.ndarray, structure: np.ndarray, base: np.ndarray) -> np.ndarray:
        sequence = self.pca.transform(embeddings)
        structural = self.structure_scaler.transform(structure)
        base_value = self.base_scaler.transform(np.asarray(base).reshape(-1, 1))
        return np.column_stack((sequence, structural, base_value))


def fit_transformer(
    embeddings: np.ndarray,
    structure: np.ndarray,
    base: np.ndarray,
    pca_dimension: int,
    seed: int,
) -> FusionTransformer:
    require(pca_dimension > 0 and pca_dimension <= min(len(embeddings) - 1, embeddings.shape[1]), "invalid_pca_dimension")
    pca = PCA(n_components=pca_dimension, whiten=True, svd_solver="randomized", random_state=seed).fit(embeddings)
    return FusionTransformer(
        pca=pca,
        structure_scaler=StandardScaler().fit(structure),
        base_scaler=StandardScaler().fit(np.asarray(base).reshape(-1, 1)),
    )


def fit_head(config: dict[str, Any], features: np.ndarray, residual: np.ndarray, weights: np.ndarray, seed: int):
    family = config["family"]
    if family == "ridge":
        model = Ridge(alpha=float(config["alpha"]), fit_intercept=True)
    elif family == "extra_trees":
        model = ExtraTreesRegressor(
            n_estimators=int(config["n_estimators"]),
            max_features=float(config["max_features"]),
            min_samples_leaf=int(config["min_samples_leaf"]),
            random_state=seed,
            n_jobs=1,
        )
    elif family == "hist_gradient_boosting":
        model = HistGradientBoostingRegressor(
            learning_rate=float(config["learning_rate"]),
            max_leaf_nodes=int(config["max_leaf_nodes"]),
            min_samples_leaf=int(config["min_samples_leaf"]),
            l2_regularization=float(config["l2_regularization"]),
            max_iter=int(config["max_iter"]),
            random_state=seed,
        )
    else:
        raise ValueError(f"unknown_head_family:{family}")
    model.fit(features, residual, sample_weight=weights)
    return model


def parse_numbers(value: str, converter) -> list:
    values = [converter(item.strip()) for item in value.split(",") if item.strip()]
    require(bool(values), f"empty_grid:{value}")
    return values


def build_grid(args: argparse.Namespace) -> list[dict[str, Any]]:
    dimensions = sorted(set(parse_numbers(args.pca_dimensions, int)))
    families = [value.strip() for value in args.head_families.split(",") if value.strip()]
    require(set(families) <= {"ridge", "extra_trees", "hist_gradient_boosting"}, "invalid_head_families")
    configs: list[dict[str, Any]] = []
    for dimension in dimensions:
        if "ridge" in families:
            for alpha in sorted(set(parse_numbers(args.ridge_alphas, float))):
                configs.append({"pca_dimension": dimension, "family": "ridge", "alpha": alpha})
        if "extra_trees" in families:
            for max_features in sorted(set(parse_numbers(args.extra_trees_max_features, float))):
                for leaf in sorted(set(parse_numbers(args.extra_trees_min_samples_leaf, int))):
                    configs.append({
                        "pca_dimension": dimension, "family": "extra_trees",
                        "n_estimators": args.extra_trees_estimators,
                        "max_features": max_features, "min_samples_leaf": leaf,
                    })
        if "hist_gradient_boosting" in families:
            for rate in sorted(set(parse_numbers(args.hist_learning_rates, float))):
                for leaves in sorted(set(parse_numbers(args.hist_max_leaf_nodes, int))):
                    for regularization in sorted(set(parse_numbers(args.hist_l2, float))):
                        configs.append({
                            "pca_dimension": dimension, "family": "hist_gradient_boosting",
                            "learning_rate": rate, "max_leaf_nodes": leaves,
                            "min_samples_leaf": args.hist_min_samples_leaf,
                            "l2_regularization": regularization, "max_iter": args.hist_max_iter,
                        })
    require(bool(configs), "empty_hyperparameter_grid")
    return configs


@dataclass
class SelectionContext:
    fold: int
    train_indices: np.ndarray
    validation_indices: np.ndarray
    train_base: np.ndarray
    validation_base: np.ndarray
    m2_audit: dict[str, Any]


def build_selection_contexts(
    outer_fold: int,
    outer_train: np.ndarray,
    arrays: Arrays,
    args: argparse.Namespace,
) -> tuple[list[SelectionContext], dict[str, Any]]:
    parents = [arrays.parents[index] for index in outer_train]
    salt = f"PVRIG_V6_M4_SELECTION|outer={outer_fold}"
    assignment = balanced_parent_assignment(parents, args.inner_folds, salt)
    contexts = []
    partition_records = []
    for inner_fold in sorted(set(assignment.tolist())):
        held_local = assignment == inner_fold
        keep_local = ~held_local
        train_indices = outer_train[keep_local]
        validation_indices = outer_train[held_local]
        train_base, m2_audit = crossfit_m2(
            train_indices, arrays, args.m2_alpha, args.subinner_folds,
            f"PVRIG_V6_M4_SELECTION_M2|outer={outer_fold}|inner={inner_fold}",
        )
        m2_full = fit_m2(
            arrays.structure[train_indices], arrays.target[train_indices],
            arrays.weights[train_indices], args.m2_alpha,
        )
        validation_base = m2_full.predict(arrays.structure[validation_indices])
        train_parents = sorted(set(arrays.parents[index] for index in train_indices))
        validation_parents = sorted(set(arrays.parents[index] for index in validation_indices))
        require(not set(train_parents) & set(validation_parents), f"inner_parent_leakage:{outer_fold}:{inner_fold}")
        contexts.append(SelectionContext(
            fold=int(inner_fold), train_indices=train_indices, validation_indices=validation_indices,
            train_base=train_base, validation_base=validation_base, m2_audit=m2_audit,
        ))
        partition_records.append({
            "inner_fold": int(inner_fold),
            "train_rows": len(train_indices), "validation_rows": len(validation_indices),
            "train_parents": len(train_parents), "validation_parents": len(validation_parents),
            "train_parent_manifest_sha256": sha256_lines(train_parents),
            "validation_parent_manifest_sha256": sha256_lines(validation_parents),
            "m2_crossfit": m2_audit,
        })
    return contexts, {
        "assignment": "sha256 salt ordering then balanced round-robin; whole parent",
        "salt": salt,
        "partitions": partition_records,
    }


def select_hyperparameters(
    outer_fold: int,
    outer_train: np.ndarray,
    arrays: Arrays,
    args: argparse.Namespace,
) -> dict[str, Any]:
    contexts, partition_audit = build_selection_contexts(outer_fold, outer_train, arrays, args)
    grid = build_grid(args)
    transformed: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
    for context in contexts:
        for dimension in sorted(set(config["pca_dimension"] for config in grid)):
            transformer = fit_transformer(
                arrays.embeddings[context.train_indices], arrays.structure[context.train_indices],
                context.train_base, dimension, args.seed + outer_fold * 1000 + context.fold * 100 + dimension,
            )
            transformed[(context.fold, dimension)] = (
                transformer.transform(
                    arrays.embeddings[context.train_indices], arrays.structure[context.train_indices], context.train_base,
                ),
                transformer.transform(
                    arrays.embeddings[context.validation_indices], arrays.structure[context.validation_indices],
                    context.validation_base,
                ),
            )
    results = []
    best: tuple[tuple[float, float, float, float], str, dict[str, Any]] | None = None
    for config_index, config in enumerate(grid):
        validation_prediction = np.full(len(outer_train), np.nan, dtype=np.float64)
        for context in contexts:
            train_features, validation_features = transformed[(context.fold, config["pca_dimension"])]
            residual = arrays.target[context.train_indices] - context.train_base
            head = fit_head(
                config, train_features, residual, arrays.weights[context.train_indices],
                args.seed + outer_fold * 100000 + config_index * 100 + context.fold,
            )
            local_positions = np.flatnonzero(np.isin(outer_train, context.validation_indices))
            require(len(local_positions) == len(context.validation_indices), "selection_position_closure")
            prediction = np.clip(context.validation_base + head.predict(validation_features), 0.0, 1.0)
            validation_prediction[local_positions] = prediction
        require(np.isfinite(validation_prediction).all(), f"nonfinite_inner_prediction:{config_index}")
        parent_values = [arrays.parents[index] for index in outer_train]
        value = metrics(arrays.target[outer_train], validation_prediction, parent_values)
        serialized = json.dumps(config, sort_keys=True, separators=(",", ":"))
        record = {"config": config, "metrics": value, "selection_key": list(selection_key(value))}
        results.append(record)
        candidate = (selection_key(value), serialized, config)
        if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] < best[1]):
            best = candidate
    assert best is not None
    outer_train_ids = sorted(arrays.candidate_ids[index] for index in outer_train)
    return {
        "schema_version": "pvrig_v6_m4_inner_selection_v1",
        "status": "PASS_V6_M4_INNER_SELECTION",
        "outer_fold": outer_fold,
        "outer_train_rows": len(outer_train),
        "outer_train_parents": len(set(arrays.parents[index] for index in outer_train)),
        "outer_train_candidate_manifest_sha256": sha256_lines(outer_train_ids),
        "selection_data_boundary": "Only explicit outer-train indices are read; outer-test targets and features are not indexed by selection.",
        "partition_audit": partition_audit,
        "grid_size": len(grid),
        "results": results,
        "selected_config": best[2],
        "selected_key": list(best[0]),
        "claim_boundary": CLAIM,
    }


def train_outer_fold(
    outer_fold: int,
    arrays: Arrays,
    args: argparse.Namespace,
    config_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output = args.output_dir / f"fold_{outer_fold}"
    output.mkdir(parents=True, exist_ok=True)
    prediction_path = output / "predictions.tsv"
    model_path = output / "model.joblib"
    selection_path = output / "inner_selection.json"
    terminal_path = output / "terminal.json"
    if terminal_path.exists():
        terminal = json.loads(terminal_path.read_text())
        require(terminal.get("config_hash") == config_hash, f"resume_config_hash:{outer_fold}")
        require(sha256_file(prediction_path) == terminal.get("prediction_sha256"), f"resume_prediction_hash:{outer_fold}")
        require(sha256_file(model_path) == terminal.get("model_sha256"), f"resume_model_hash:{outer_fold}")
        require(sha256_file(selection_path) == terminal.get("inner_selection_sha256"), f"resume_selection_hash:{outer_fold}")
        _, rows = read_table(prediction_path)
        return rows, terminal

    held = arrays.folds == outer_fold
    keep = ~held
    require(held.any() and keep.any(), f"empty_outer_fold:{outer_fold}")
    outer_train = np.flatnonzero(keep)
    outer_test = np.flatnonzero(held)
    train_parents = set(arrays.parents[index] for index in outer_train)
    test_parents = set(arrays.parents[index] for index in outer_test)
    require(not train_parents & test_parents, f"outer_parent_leakage:{outer_fold}")
    selection = select_hyperparameters(outer_fold, outer_train, arrays, args)
    atomic_json(selection_path, selection)
    selected = selection["selected_config"]

    train_base, m2_crossfit_audit = crossfit_m2(
        outer_train, arrays, args.m2_alpha, args.inner_folds,
        f"PVRIG_V6_M4_FINAL_M2|outer={outer_fold}",
    )
    m2_model = fit_m2(
        arrays.structure[outer_train], arrays.target[outer_train], arrays.weights[outer_train], args.m2_alpha,
    )
    test_base = m2_model.predict(arrays.structure[outer_test])
    transformer = fit_transformer(
        arrays.embeddings[outer_train], arrays.structure[outer_train], train_base,
        int(selected["pca_dimension"]), args.seed + outer_fold * 1000 + 991,
    )
    train_features = transformer.transform(arrays.embeddings[outer_train], arrays.structure[outer_train], train_base)
    test_features = transformer.transform(arrays.embeddings[outer_test], arrays.structure[outer_test], test_base)
    head = fit_head(
        selected, train_features, arrays.target[outer_train] - train_base, arrays.weights[outer_train],
        args.seed + outer_fold * 1000 + 997,
    )
    m4_prediction = np.clip(test_base + head.predict(test_features), 0.0, 1.0)
    require(np.isfinite(test_base).all() and np.isfinite(m4_prediction).all(), f"nonfinite_outer_prediction:{outer_fold}")
    artifact = {
        "schema_version": "pvrig_v6_m4_sklearn_model_v1",
        "model_family": "M4_SKLEARN_PCA_STRUCTURE_RESIDUAL",
        "outer_fold": outer_fold,
        "config_hash": config_hash,
        "training_fingerprint": arrays.training_fingerprint,
        "selected_config": selected,
        "m2_alpha": args.m2_alpha,
        # Store only sklearn classes in the portable artifact.  Custom dataclasses
        # are intentionally decomposed because running this file as a script would
        # otherwise pickle them under ``__main__``.
        "m2_model": {"scaler": m2_model.scaler, "ridge": m2_model.ridge},
        "fusion_transformer": {
            "pca": transformer.pca,
            "structure_scaler": transformer.structure_scaler,
            "base_scaler": transformer.base_scaler,
        },
        "residual_head": head,
        "feature_names": arrays.feature_names,
        "feature_names_sha256": arrays.feature_names_sha256,
        "embedding_dimension": arrays.embeddings.shape[1],
        "claim_boundary": CLAIM,
    }
    temporary = model_path.with_suffix(".tmp")
    joblib.dump(artifact, temporary, compress=3)
    temporary.replace(model_path)
    rows = []
    for local, index in enumerate(outer_test):
        rows.append({
            "candidate_id": arrays.candidate_ids[index],
            "sequence_sha256": arrays.sequence_hashes[index],
            "parent_framework_cluster": arrays.parents[index],
            "teacher_source": arrays.sources[index],
            "outer_fold": outer_fold,
            "R_dual_min": format(arrays.target[index], ".12g"),
            "M2_prediction": format(test_base[local], ".12g"),
            "M4_prediction": format(m4_prediction[local], ".12g"),
        })
    atomic_tsv(prediction_path, rows)
    terminal = {
        "schema_version": "pvrig_v6_m4_fold_terminal_v1",
        "status": "PASS_V6_M4_FOLD_TERMINAL",
        "outer_fold": outer_fold,
        "rows": len(rows),
        "train_rows": len(outer_train),
        "train_parents": len(train_parents),
        "test_parents": len(test_parents),
        "config_hash": config_hash,
        "selected_config": selected,
        "m2_crossfit_audit": m2_crossfit_audit,
        "inner_selection_sha256": sha256_file(selection_path),
        "model_sha256": sha256_file(model_path),
        "prediction_sha256": sha256_file(prediction_path),
        "claim_boundary": CLAIM,
    }
    atomic_json(terminal_path, terminal)
    return rows, terminal


def parent_bootstrap_delta(
    target: np.ndarray,
    baseline: np.ndarray,
    model: np.ndarray,
    parents: list[str],
    repetitions: int,
    seed: int,
) -> dict[str, float | int]:
    parent_array = np.asarray(parents)
    grouped = {parent: np.flatnonzero(parent_array == parent) for parent in sorted(set(parents))}
    names = sorted(grouped)
    generator = np.random.default_rng(seed)
    values = []
    for _ in range(repetitions):
        selected = generator.choice(names, size=len(names), replace=True)
        indices = np.concatenate([grouped[parent] for parent in selected])
        values.append(spearman(target[indices], model[indices]) - spearman(target[indices], baseline[indices]))
    values_array = np.asarray(values)
    return {
        "repetitions": repetitions,
        "seed": seed,
        "median_delta_spearman": float(np.median(values_array)),
        "ci95_lower": float(np.quantile(values_array, 0.025)),
        "ci95_upper": float(np.quantile(values_array, 0.975)),
        "positive_fraction": float(np.mean(values_array > 0)),
    }


def main(args: argparse.Namespace) -> dict[str, Any]:
    arrays = load_validated_arrays(args.input, args.table_receipt, args.embeddings, args.expected_outer_folds)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        key: (str(value) if isinstance(value, Path) else value)
        for key, value in vars(args).items()
    }
    config["model_family"] = "M4_SKLEARN_PCA_STRUCTURE_RESIDUAL"
    config["training_fingerprint"] = arrays.training_fingerprint
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    all_rows: list[dict[str, Any]] = []
    terminals = []
    for fold in range(args.expected_outer_folds):
        rows, terminal = train_outer_fold(fold, arrays, args, config_hash)
        all_rows.extend(rows)
        terminals.append(terminal)
    require(len(all_rows) == len(arrays.candidate_ids), f"oof_row_count:{len(all_rows)}:{len(arrays.candidate_ids)}")
    require(len({row["candidate_id"] for row in all_rows}) == len(all_rows), "oof_duplicate_candidate")
    require(set(row["candidate_id"] for row in all_rows) == set(arrays.candidate_ids), "oof_candidate_closure")
    all_rows.sort(key=lambda row: row["candidate_id"])
    oof_path = args.output_dir / "oof_predictions.tsv"
    atomic_tsv(oof_path, all_rows)
    target = np.asarray([float(row["R_dual_min"]) for row in all_rows])
    m2_prediction = np.asarray([float(row["M2_prediction"]) for row in all_rows])
    m4_prediction = np.asarray([float(row["M4_prediction"]) for row in all_rows])
    parents = [row["parent_framework_cluster"] for row in all_rows]
    sources = [row["teacher_source"] for row in all_rows]
    m2_metrics = metrics(target, m2_prediction, parents)
    m4_metrics = metrics(target, m4_prediction, parents)
    source_metrics = {}
    source_array = np.asarray(sources)
    for source in sorted(set(sources)):
        indices = np.flatnonzero(source_array == source)
        source_metrics[source] = {
            "rows": len(indices),
            "parents": len(set(parents[index] for index in indices)),
            "M2": metrics(target[indices], m2_prediction[indices], [parents[index] for index in indices]),
            "M4": metrics(target[indices], m4_prediction[indices], [parents[index] for index in indices]),
        }
    summary = {
        "schema_version": "pvrig_v6_m4_oof_summary_v1",
        "status": "PASS_V6_M4_OOF_COMPLETE",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_family": "M4_SKLEARN_PCA_STRUCTURE_RESIDUAL",
        "rows": len(all_rows),
        "parent_clusters": len(set(parents)),
        "input_sha256": arrays.input_sha256,
        "table_receipt_sha256": arrays.table_receipt_sha256,
        "embedding_receipt_sha256": arrays.embedding_receipt_sha256,
        "embedding_shard_hashes": arrays.embedding_shard_hashes,
        "feature_names_sha256": arrays.feature_names_sha256,
        "split_manifest_sha256": arrays.split_manifest_sha256,
        "training_fingerprint": arrays.training_fingerprint,
        "config": config,
        "config_hash": config_hash,
        "M2": m2_metrics,
        "M4": m4_metrics,
        "parent_bootstrap_delta": parent_bootstrap_delta(
            target, m2_prediction, m4_prediction, parents, args.bootstrap_repetitions, args.seed + 9000,
        ),
        "source_stratified": source_metrics,
        "comparison": {
            "global_spearman_delta": float(m4_metrics["spearman"] - m2_metrics["spearman"]),
            "parent_centered_spearman_delta": float(
                m4_metrics["parent_centered_spearman"] - m2_metrics["parent_centered_spearman"]
            ),
            "mae_delta_M4_minus_M2": float(m4_metrics["mae"] - m2_metrics["mae"]),
            "top20_recall_delta": float(m4_metrics["top20_recall"] - m2_metrics["top20_recall"]),
        },
        "outer_test_selection_boundary": "Each fold selected PCA/head hyperparameters using outer-train inner whole-parent CV only.",
        "oof_prediction_sha256": sha256_file(oof_path),
        "claim_boundary": CLAIM,
    }
    summary_path = args.output_dir / "summary.json"
    atomic_json(summary_path, summary)
    terminal = {
        "schema_version": "pvrig_v6_m4_terminal_receipt_v1",
        "status": "PASS_V6_M4_TRAINING_TERMINAL",
        "summary_sha256": sha256_file(summary_path),
        "oof_prediction_sha256": sha256_file(oof_path),
        "fold_terminals": terminals,
        "claim_boundary": CLAIM,
    }
    atomic_json(args.output_dir / "terminal_receipt.json", terminal)
    return summary


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--input", type=Path, required=True)
    value.add_argument("--table-receipt", type=Path, required=True)
    value.add_argument("--embeddings", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--expected-outer-folds", type=int, default=5)
    value.add_argument("--inner-folds", type=int, default=5)
    value.add_argument("--subinner-folds", type=int, default=4)
    value.add_argument("--m2-alpha", type=float, default=10.0)
    value.add_argument("--pca-dimensions", default="8,16,32")
    value.add_argument("--head-families", default="ridge,extra_trees,hist_gradient_boosting")
    value.add_argument("--ridge-alphas", default="1,10,100")
    value.add_argument("--extra-trees-estimators", type=int, default=300)
    value.add_argument("--extra-trees-max-features", default="0.5,1.0")
    value.add_argument("--extra-trees-min-samples-leaf", default="2,5")
    value.add_argument("--hist-learning-rates", default="0.03,0.08")
    value.add_argument("--hist-max-leaf-nodes", default="7,15")
    value.add_argument("--hist-min-samples-leaf", type=int, default=10)
    value.add_argument("--hist-l2", default="1,10")
    value.add_argument("--hist-max-iter", type=int, default=250)
    value.add_argument("--bootstrap-repetitions", type=int, default=1000)
    value.add_argument("--seed", type=int, default=43)
    return value


if __name__ == "__main__":
    print(json.dumps(main(parser().parse_args()), indent=2, sort_keys=True))
