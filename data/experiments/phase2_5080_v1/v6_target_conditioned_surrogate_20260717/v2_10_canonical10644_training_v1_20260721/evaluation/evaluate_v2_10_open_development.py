#!/usr/bin/env python3
"""Fail-closed V2.10 open-development Stage0 evaluator.

This evaluator consumes the canonical open-only teacher, its split manifest,
and one or more Stage0 prediction tables.  It never accepts a frozen-test
truth path.  Prediction-file truth columns, when present for compatibility
with V2.9 outputs, are checked against the canonical *development* rows but
are not used as the source of truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA = "pvrig_v2_10_open_development_stage0_evaluation_v1"
SPLIT_SCHEMA = "pvrig_v2_9_whole_parent_split_v1"
FORBIDDEN_PATH_TOKENS = (
    "frozen_test", "frozen-test", "sealed_truth", "test32", "v4_f",
    "outer_test", "outer-test",
)
REQUIRED_TEACHER_COLUMNS = {
    "candidate_id", "sequence_sha256", "parent_framework_cluster",
    "R_8X6B", "R_9E6Y", "R_dual_min", "sample_weight",
    "teacher_reliability",
}


class EvaluationError(RuntimeError):
    """Fail-closed evaluation error."""


@dataclass(frozen=True)
class ExpectedCounts:
    train: int = 9849
    development: int = 795
    total: int = 10644


@dataclass(frozen=True)
class TruthRow:
    candidate_id: str
    parent: str
    r8: float
    r9: float

    @property
    def dual(self) -> float:
        return min(self.r8, self.r9)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_forbidden_path(path: Path, role: str) -> None:
    text = str(path.resolve()).lower()
    for token in FORBIDDEN_PATH_TOKENS:
        require(token not in text, f"forbidden_{role}_path_token:{token}")


def require_regular(path: Path, role: str) -> None:
    reject_forbidden_path(path, role)
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular:{path}")


def stable_parent_hash(parents: Iterable[str]) -> str:
    payload = "\n".join(sorted(set(parents))) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_sha256sums(path: Path, required_names: set[str]) -> dict[str, str]:
    require_regular(path, "sha256sums")
    entries: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        require(len(parts) == 2, f"invalid_sha256sums_line:{line_number}")
        digest, raw_name = parts
        name = raw_name.lstrip("* ")
        require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), f"invalid_sha256:{line_number}")
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe_sha256_path:{name}")
        require(name not in entries, f"duplicate_sha256_entry:{name}")
        target = path.parent / relative
        require(target.is_file() and not target.is_symlink(), f"hashed_file_not_regular:{name}")
        require(target.resolve().parent == path.parent.resolve(), f"hashed_file_outside_directory:{name}")
        require(sha256_file(target) == digest, f"hashed_file_mismatch:{name}")
        entries[name] = digest
    require(required_names <= set(entries), f"sha256_required_entries_missing:{sorted(required_names-set(entries))}")
    return entries


def finite(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise EvaluationError(f"invalid_numeric:{label}:{raw!r}") from exc
    require(math.isfinite(value), f"nonfinite_numeric:{label}")
    return value


def load_manifest(path: Path, teacher_sha256: str, counts: ExpectedCounts) -> dict[str, Any]:
    require_regular(path, "split_manifest")
    payload = json.loads(path.read_text())
    require(isinstance(payload, dict), "split_manifest_not_object")
    require(payload.get("schema_version") == SPLIT_SCHEMA, "split_schema")
    require(payload.get("data_version") == "D1", "split_data_version")
    require(payload.get("open_only") is True, "split_not_open_only")
    require(int(payload.get("frozen_test_access_count", -1)) == 0, "frozen_access_nonzero")
    require(int(payload.get("sealed_truth_access_count", -1)) == 0, "sealed_access_nonzero")
    require(payload.get("training_tsv_sha256") == teacher_sha256, "split_teacher_hash")
    require(int(payload.get("expected_train_rows", -1)) == counts.train, "expected_train_rows")
    require(int(payload.get("expected_score_rows", -1)) == counts.development, "expected_development_rows")
    require(int(payload.get("expected_total_rows", -1)) == counts.total, "expected_total_rows")
    train = set(payload.get("train_parents", []))
    development = set(payload.get("score_parents", []))
    frozen = set(payload.get("frozen_test_parents", []))
    require(train and development and frozen, "empty_parent_partition")
    require(train.isdisjoint(development), "train_development_parent_overlap")
    require(train.isdisjoint(frozen), "train_frozen_parent_overlap")
    require(development.isdisjoint(frozen), "development_frozen_parent_overlap")
    require(stable_parent_hash(train) == payload.get("train_parent_set_sha256"), "train_parent_hash")
    require(stable_parent_hash(development) == payload.get("score_parent_set_sha256"), "development_parent_hash")
    require(stable_parent_hash(frozen) == payload.get("frozen_test_parent_set_sha256"), "frozen_parent_hash")
    return payload


def load_open_teacher(
    path: Path,
    expected_sha256: str,
    split: Mapping[str, Any],
    counts: ExpectedCounts,
) -> dict[str, TruthRow]:
    require_regular(path, "teacher")
    require(len(expected_sha256) == 64, "invalid_expected_teacher_hash")
    require(sha256_file(path) == expected_sha256, "teacher_hash_mismatch")
    train_parents = set(split["train_parents"])
    development_parents = set(split["score_parents"])
    frozen_parents = set(split["frozen_test_parents"])
    seen_candidates: set[str] = set()
    seen_sequences: set[str] = set()
    development: dict[str, TruthRow] = {}
    train_count = 0
    total = 0
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(REQUIRED_TEACHER_COLUMNS <= set(reader.fieldnames or []), "teacher_columns_missing")
        for raw in reader:
            total += 1
            candidate = raw["candidate_id"].strip()
            sequence_sha256 = raw["sequence_sha256"].strip()
            parent = raw["parent_framework_cluster"].strip()
            require(candidate and candidate not in seen_candidates, f"duplicate_candidate:{candidate}")
            require(sequence_sha256 and sequence_sha256 not in seen_sequences, f"duplicate_sequence:{candidate}")
            seen_candidates.add(candidate)
            seen_sequences.add(sequence_sha256)
            require(parent not in frozen_parents, f"teacher_contains_frozen_parent:{candidate}")
            require(parent in train_parents | development_parents, f"teacher_parent_outside_open:{candidate}")
            reliability = raw["teacher_reliability"].upper()
            require("TECHNICAL_NA" not in reliability and "QUARANTINE" not in reliability, f"invalid_teacher_state:{candidate}")
            r8 = finite(raw["R_8X6B"], f"R8:{candidate}")
            r9 = finite(raw["R_9E6Y"], f"R9:{candidate}")
            dual = finite(raw["R_dual_min"], f"Rdual:{candidate}")
            weight = finite(raw["sample_weight"], f"sample_weight:{candidate}")
            require(weight > 0, f"nonpositive_weight:{candidate}")
            require(abs(dual - min(r8, r9)) < 2e-8, f"truth_exact_min:{candidate}")
            if parent in train_parents:
                train_count += 1
            else:
                development[candidate] = TruthRow(candidate, parent, r8, r9)
    require(total == counts.total, f"teacher_total_rows:{total}")
    require(train_count == counts.train, f"teacher_train_rows:{train_count}")
    require(len(development) == counts.development, f"teacher_development_rows:{len(development)}")
    return development


def prediction_model_names(header: Sequence[str]) -> tuple[str, ...]:
    models = tuple(column[:-4] for column in header if column.endswith("__R8"))
    require(bool(models), "prediction_models_missing")
    for model in models:
        require(f"{model}__R9" in header, f"prediction_R9_missing:{model}")
    require(len(models) == len(set(models)), "duplicate_prediction_model")
    return models


def load_predictions(
    path: Path,
    truth: Mapping[str, TruthRow],
) -> tuple[tuple[str, ...], dict[str, dict[str, tuple[float, float]]]]:
    require_regular(path, "prediction")
    rows: dict[str, dict[str, tuple[float, float]]] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        header = list(reader.fieldnames or [])
        require("candidate_id" in header and "parent_framework_cluster" in header, "prediction_identity_columns")
        models = prediction_model_names(header)
        for raw in reader:
            candidate = raw["candidate_id"].strip()
            require(candidate in truth, f"prediction_candidate_outside_development:{candidate}")
            require(candidate not in rows, f"duplicate_prediction_candidate:{candidate}")
            expected = truth[candidate]
            require(raw["parent_framework_cluster"].strip() == expected.parent, f"prediction_parent_mismatch:{candidate}")
            for field, expected_value in (
                ("truth_R8", expected.r8),
                ("truth_R9", expected.r9),
                ("truth_Rdual_exact_min", expected.dual),
            ):
                if field in header:
                    require(abs(finite(raw[field], f"{field}:{candidate}") - expected_value) < 2e-8, f"prediction_truth_mismatch:{field}:{candidate}")
            values: dict[str, tuple[float, float]] = {}
            for model in models:
                r8 = finite(raw[f"{model}__R8"], f"prediction_R8:{model}:{candidate}")
                r9 = finite(raw[f"{model}__R9"], f"prediction_R9:{model}:{candidate}")
                dual_column = f"{model}__Rdual_exact_min"
                if dual_column in header:
                    require(abs(finite(raw[dual_column], f"prediction_Rdual:{model}:{candidate}") - min(r8, r9)) < 2e-8, f"prediction_exact_min:{model}:{candidate}")
                values[model] = (r8, r9)
            rows[candidate] = values
    require(set(rows) == set(truth), f"prediction_development_closure:{len(rows)}!={len(truth)}")
    return models, rows


def validate_stage0_run(
    predictions: Sequence[tuple[int, Path]],
    expected_teacher_sha256: str,
    expected_split_sha256: str,
    counts: ExpectedCounts,
    expected_seeds: tuple[int, ...],
) -> dict[str, Any]:
    seeds = tuple(seed for seed, _ in predictions)
    require(seeds == expected_seeds, f"seed_contract:{seeds}!={expected_seeds}")
    run_roots = {path.parent.parent.resolve() for _, path in predictions}
    require(len(run_roots) == 1, "prediction_run_root_mismatch")
    run_root = next(iter(run_roots))
    reject_forbidden_path(run_root, "run_root")
    root_hashes = verify_sha256sums(run_root / "SHA256SUMS", {"PREFLIGHT.json", "MULTISEED_SUMMARY.json"})
    preflight_path = run_root / "PREFLIGHT.json"
    summary_path = run_root / "MULTISEED_SUMMARY.json"
    preflight = json.loads(preflight_path.read_text())
    summary = json.loads(summary_path.read_text())
    require(preflight.get("status") == "PASS_PREFLIGHT", "preflight_status")
    require(summary.get("status") == "PASS_MULTISEED_COMPLETE", "multiseed_status")
    for payload, label in ((preflight, "preflight"), (summary, "multiseed")):
        require(payload.get("data_version") == "D1", f"{label}_data_version")
        require(tuple(payload.get("seeds", [])) == expected_seeds, f"{label}_seeds")
        require(int(payload.get("train_rows", -1)) == counts.train, f"{label}_train_rows")
        require(int(payload.get("score_rows", -1)) == counts.development, f"{label}_development_rows")
    require(int(preflight.get("total_rows", -1)) == counts.total, "preflight_total_rows")
    require(int(preflight.get("frozen_test_access_count", -1)) == 0, "preflight_frozen_access")
    require(int(preflight.get("sealed_truth_access_count", -1)) == 0, "preflight_sealed_access")
    require(int(preflight.get("teacher_frozen_parent_overlap_count", -1)) == 0, "preflight_frozen_parent_overlap")
    require(preflight.get("training_tsv_sha256") == expected_teacher_sha256, "preflight_teacher_hash")
    require(preflight.get("split_manifest_sha256") == expected_split_sha256, "preflight_split_hash")
    require(tuple(preflight.get("model_names", [])) == tuple(summary.get("model_names", [])), "root_model_contract")

    seed_results: dict[str, dict[str, Any]] = {}
    seed_hashes: dict[str, Any] = {}
    for seed, prediction_path in predictions:
        require(prediction_path.name == "OPEN_SCORE_PREDICTIONS.tsv", f"prediction_filename:{seed}")
        require(prediction_path.parent.name == f"seed_{seed}", f"prediction_seed_directory:{seed}")
        require(prediction_path.parent.parent.resolve() == run_root, f"prediction_run_root:{seed}")
        hashes = verify_sha256sums(
            prediction_path.parent / "SHA256SUMS",
            {"OPEN_SCORE_PREDICTIONS.tsv", "RESULT.json"},
        )
        result_path = prediction_path.parent / "RESULT.json"
        result = json.loads(result_path.read_text())
        require(result.get("status") == "PASS_OPEN_SEQUENCE_STAGE0_COMPLETE", f"seed_result_status:{seed}")
        require(int(result.get("seed", -1)) == seed, f"seed_result_seed:{seed}")
        require(result.get("data_version") == "D1", f"seed_result_data_version:{seed}")
        require(int(result.get("train_rows", -1)) == counts.train, f"seed_result_train_rows:{seed}")
        require(int(result.get("score_rows", -1)) == counts.development, f"seed_result_development_rows:{seed}")
        require(tuple(result.get("model_names", [])) == tuple(preflight["model_names"]), f"seed_result_models:{seed}")
        access = result.get("input_access", {})
        require(int(access.get("frozen_test", -1)) == 0, f"seed_result_frozen_access:{seed}")
        require(int(access.get("sealed_truth", -1)) == 0, f"seed_result_sealed_access:{seed}")
        inputs = result.get("inputs", {})
        require(inputs.get("training_tsv_sha256") == expected_teacher_sha256, f"seed_result_teacher_hash:{seed}")
        require(inputs.get("split_manifest_sha256") == expected_split_sha256, f"seed_result_split_hash:{seed}")
        seed_results[str(seed)] = result
        seed_hashes[str(seed)] = {
            "prediction_sha256": hashes["OPEN_SCORE_PREDICTIONS.tsv"],
            "result_sha256": hashes["RESULT.json"],
            "sha256sums_sha256": sha256_file(prediction_path.parent / "SHA256SUMS"),
        }
    return {
        "run_root": str(run_root),
        "preflight_sha256": root_hashes["PREFLIGHT.json"],
        "multiseed_summary_sha256": root_hashes["MULTISEED_SUMMARY.json"],
        "root_sha256sums_sha256": sha256_file(run_root / "SHA256SUMS"),
        "seed_hashes": seed_hashes,
        "seed_results": seed_results,
        "model_names": list(preflight["model_names"]),
    }


def spearman(truth: np.ndarray, prediction: np.ndarray) -> float:
    def average_ranks(values: np.ndarray) -> np.ndarray:
        order = np.argsort(values, kind="stable")
        ranks = np.empty(len(values), dtype=np.float64)
        cursor = 0
        while cursor < len(order):
            end = cursor + 1
            while end < len(order) and values[order[end]] == values[order[cursor]]:
                end += 1
            ranks[order[cursor:end]] = (cursor + end - 1) / 2.0
            cursor = end
        return ranks

    left = average_ranks(np.asarray(truth, dtype=np.float64))
    right = average_ranks(np.asarray(prediction, dtype=np.float64))
    left -= np.mean(left)
    right -= np.mean(right)
    denominator = math.sqrt(float(np.sum(left * left) * np.sum(right * right)))
    return float(np.sum(left * right) / denominator) if denominator > 0 else 0.0


def ranked_indices(candidate_ids: Sequence[str], values: np.ndarray) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (-float(values[index]), candidate_ids[index]))


def binary_ndcg(candidate_ids: Sequence[str], relevance: np.ndarray, score: np.ndarray, k: int) -> float:
    order = ranked_indices(candidate_ids, score)[:k]
    discounts = np.log2(np.arange(2, len(order) + 2, dtype=np.float64))
    dcg = float(np.sum(relevance[order] / discounts))
    positives = min(int(np.sum(relevance)), k)
    if positives == 0:
        return 0.0
    ideal_discounts = np.log2(np.arange(2, positives + 2, dtype=np.float64))
    return dcg / float(np.sum(1.0 / ideal_discounts))


def enrichment_table(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray) -> list[dict[str, Any]]:
    n = len(truth)
    true_order = ranked_indices(candidate_ids, truth)
    predicted_order = ranked_indices(candidate_ids, score)
    result = []
    for true_fraction in (0.10, 0.20):
        positives = max(1, math.ceil(n * true_fraction))
        true_idx = set(true_order[:positives])
        prevalence = positives / n
        binary = np.asarray([1.0 if index in true_idx else 0.0 for index in range(n)])
        for budget in (0.05, 0.10, 0.20):
            selected = max(1, math.ceil(n * budget))
            predicted_idx = set(predicted_order[:selected])
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
                "binary_ndcg": binary_ndcg(candidate_ids, binary, score, selected),
            })
    return result


def within_parent_top20(candidate_ids: Sequence[str], parents: Sequence[str], truth: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    groups: dict[str, list[int]] = {}
    for index, parent in enumerate(parents):
        groups.setdefault(parent, []).append(index)
    details = []
    for parent, indices in sorted(groups.items()):
        k = max(1, math.ceil(len(indices) * 0.20))
        true_order = sorted(indices, key=lambda index: (-float(truth[index]), candidate_ids[index]))[:k]
        pred_order = sorted(indices, key=lambda index: (-float(score[index]), candidate_ids[index]))[:k]
        hits = len(set(true_order) & set(pred_order))
        recall = hits / k
        details.append({
            "parent": parent, "n": len(indices), "k": k, "hits": hits,
            "recall": recall, "enrichment_factor": recall / (k / len(indices)),
        })
    return {
        "macro_recall": float(np.mean([item["recall"] for item in details])),
        "macro_enrichment_factor": float(np.mean([item["enrichment_factor"] for item in details])),
        "parents": details,
    }


def find_enrichment(table: Sequence[Mapping[str, Any]], true_fraction: float, budget: float) -> Mapping[str, Any]:
    return next(item for item in table if item["true_top_fraction"] == true_fraction and item["predicted_budget_fraction"] == budget)


def seed_stability(
    candidate_ids: Sequence[str],
    seed_predictions: Mapping[str, np.ndarray],
    per_seed_metrics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    labels = list(seed_predictions)
    dual = {label: np.minimum(value[:, 0], value[:, 1]) for label, value in seed_predictions.items()}
    stack = np.stack([dual[label] for label in labels])
    candidate_std = np.std(stack, axis=0)
    pairs: dict[str, Any] = {}
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1:]:
            key = f"{left}__{right}"
            overlap = {}
            for budget in (0.05, 0.10, 0.20):
                k = max(1, math.ceil(len(candidate_ids) * budget))
                left_top = set(ranked_indices(candidate_ids, dual[left])[:k])
                right_top = set(ranked_indices(candidate_ids, dual[right])[:k])
                intersection = len(left_top & right_top)
                overlap[str(budget)] = {
                    "k": k,
                    "intersection": intersection,
                    "overlap_fraction": intersection / k,
                    "jaccard": intersection / len(left_top | right_top),
                }
            pairs[key] = {
                "Rdual_prediction_spearman": spearman(dual[left], dual[right]),
                "top_budget_overlap": overlap,
            }

    metric_dispersion: dict[str, Any] = {}
    paths = {
        "recall_true_top20_at_budget20": ("primary_summary", "recall_true_top20_at_budget20"),
        "ef_true_top10_at_budget10": ("primary_summary", "ef_true_top10_at_budget10"),
        "binary_ndcg_true_top10_at_budget10": ("primary_summary", "binary_ndcg_true_top10_at_budget10"),
        "within_parent_macro_recall_top20": ("primary_summary", "within_parent_macro_recall_top20"),
        "Rdual_spearman": ("Rdual_exact_min", "spearman"),
    }
    for name, path in paths.items():
        values = [float(per_seed_metrics[label][path[0]][path[1]]) for label in labels]
        metric_dispersion[name] = {
            "by_seed": dict(zip(labels, values)),
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "range": float(max(values) - min(values)),
        }
    return {
        "candidate_Rdual_seed_std": {
            "mean": float(np.mean(candidate_std)),
            "p95": float(np.quantile(candidate_std, 0.95)),
            "max": float(np.max(candidate_std)),
        },
        "pairwise_seed_agreement": pairs,
        "development_metric_dispersion": metric_dispersion,
    }


def metrics(candidate_ids: Sequence[str], parents: Sequence[str], y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    dual_truth = np.minimum(y[:, 0], y[:, 1])
    dual_pred = np.minimum(pred[:, 0], pred[:, 1])
    enrichment = enrichment_table(candidate_ids, dual_truth, dual_pred)
    top20 = find_enrichment(enrichment, 0.20, 0.20)
    top10 = find_enrichment(enrichment, 0.10, 0.10)
    parent = within_parent_top20(candidate_ids, parents, dual_truth, dual_pred)
    return {
        "R8": {
            "spearman": spearman(y[:, 0], pred[:, 0]),
            "mae": float(np.mean(np.abs(y[:, 0] - pred[:, 0]))),
            "rmse": float(np.sqrt(np.mean((y[:, 0] - pred[:, 0]) ** 2))),
        },
        "R9": {
            "spearman": spearman(y[:, 1], pred[:, 1]),
            "mae": float(np.mean(np.abs(y[:, 1] - pred[:, 1]))),
            "rmse": float(np.sqrt(np.mean((y[:, 1] - pred[:, 1]) ** 2))),
        },
        "Rdual_exact_min": {
            "spearman": spearman(dual_truth, dual_pred),
            "mae": float(np.mean(np.abs(dual_truth - dual_pred))),
            "rmse": float(np.sqrt(np.mean((dual_truth - dual_pred) ** 2))),
        },
        "early_enrichment": enrichment,
        "primary_summary": {
            "recall_true_top20_at_budget20": top20["recall"],
            "ef_true_top10_at_budget10": top10["enrichment_factor"],
            "binary_ndcg_true_top10_at_budget10": top10["binary_ndcg"],
            "within_parent_macro_recall_top20": parent["macro_recall"],
        },
        "within_parent_top20": parent,
        "exact_min_violation_count": 0,
    }


def parse_prediction_arg(raw: str) -> tuple[int, Path]:
    label, separator, path = raw.partition("=")
    require(bool(separator) and bool(label.strip()) and bool(path.strip()), f"invalid_prediction_arg:{raw}")
    try:
        seed = int(label.strip())
    except ValueError as exc:
        raise EvaluationError(f"prediction_seed_not_integer:{label}") from exc
    require(seed >= 0, f"prediction_seed_negative:{seed}")
    return seed, Path(path.strip())


def parse_seeds(raw: str) -> tuple[int, ...]:
    try:
        values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise EvaluationError("invalid_expected_seeds") from exc
    require(values and len(values) == len(set(values)) and all(value >= 0 for value in values), "invalid_expected_seeds")
    return values


def evaluate(
    teacher_path: Path,
    expected_teacher_sha256: str,
    split_path: Path,
    predictions: Sequence[tuple[int, Path]],
    counts: ExpectedCounts = ExpectedCounts(),
    expected_seeds: tuple[int, ...] = (43, 97, 193),
) -> dict[str, Any]:
    require(bool(predictions), "no_prediction_inputs")
    labels = [str(label) for label, _ in predictions]
    require(len(labels) == len(set(labels)), "duplicate_prediction_label")
    split = load_manifest(split_path, expected_teacher_sha256, counts)
    truth_by_id = load_open_teacher(teacher_path, expected_teacher_sha256, split, counts)
    run_contract = validate_stage0_run(
        predictions,
        expected_teacher_sha256,
        sha256_file(split_path),
        counts,
        expected_seeds,
    )
    candidate_ids = sorted(truth_by_id)
    parents = [truth_by_id[candidate].parent for candidate in candidate_ids]
    y = np.asarray([[truth_by_id[candidate].r8, truth_by_id[candidate].r9] for candidate in candidate_ids], dtype=np.float64)
    loaded: dict[str, dict[str, dict[str, tuple[float, float]]]] = {}
    model_contract: tuple[str, ...] | None = None
    input_hashes: dict[str, str] = {}
    for seed, path in predictions:
        label = str(seed)
        models, rows = load_predictions(path, truth_by_id)
        if model_contract is None:
            model_contract = models
        require(models == model_contract, f"prediction_model_contract_mismatch:{label}")
        loaded[label] = rows
        input_hashes[label] = sha256_file(path)
    assert model_contract is not None
    require(tuple(model_contract) == tuple(run_contract["model_names"]), "prediction_result_model_contract")

    all_metrics: dict[str, Any] = {}
    ensemble_metrics: dict[str, Any] = {}
    stability: dict[str, Any] = {}
    for model in model_contract:
        seed_predictions = []
        per_seed_for_model: dict[str, Any] = {}
        predictions_for_model: dict[str, np.ndarray] = {}
        for seed, _ in predictions:
            label = str(seed)
            pred = np.asarray([loaded[label][candidate][model] for candidate in candidate_ids], dtype=np.float64)
            evaluated = metrics(candidate_ids, parents, y, pred)
            all_metrics[f"{label}/{model}"] = evaluated
            per_seed_for_model[label] = evaluated
            predictions_for_model[label] = pred
            seed_predictions.append(pred)
        ensemble = np.mean(np.stack(seed_predictions), axis=0)
        ensemble_metrics[model] = metrics(candidate_ids, parents, y, ensemble)
        stability[model] = seed_stability(candidate_ids, predictions_for_model, per_seed_for_model)

    def selection_key(model: str) -> tuple[float, float, float, float, str]:
        value = ensemble_metrics[model]
        summary = value["primary_summary"]
        return (
            -summary["recall_true_top20_at_budget20"],
            -summary["within_parent_macro_recall_top20"],
            -summary["binary_ndcg_true_top10_at_budget10"],
            -value["Rdual_exact_min"]["spearman"],
            model,
        )

    selected = min(model_contract, key=selection_key)
    return {
        "schema_version": SCHEMA,
        "status": "PASS_V2_10_OPEN_DEVELOPMENT_EVALUATION",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": "Open-development approximation of computational Docking geometry only; not frozen-test, binding, affinity, experimental blocking, or formal validation evidence.",
        "counts": {
            "train": counts.train,
            "development": counts.development,
            "total_open": counts.total,
            "development_parents": len(set(parents)),
        },
        "input_access": {
            "frozen_test_truth_rows": 0,
            "sealed_truth_files": 0,
            "development_truth_rows": counts.development,
        },
        "inputs": {
            "teacher_sha256": sha256_file(teacher_path),
            "split_manifest_sha256": sha256_file(split_path),
            "prediction_sha256_by_label": input_hashes,
            "stage0_run_contract": {key: value for key, value in run_contract.items() if key != "seed_results"},
        },
        "metric_contract": {
            "truth_target": "Rdual_exact_min=min(R8,R9)",
            "recall_at_20": "true top ceil(0.20*N) recovered in predicted top ceil(0.20*N)",
            "ef_at_10": "precision among predicted top ceil(0.10*N), divided by prevalence of true top ceil(0.10*N)",
            "ndcg": "binary relevance defined by each true-top fraction; deterministic DCG at the declared predicted budget",
            "tie_break": "candidate_id ascending after score descending",
            "selection_order": [
                "recall_true_top20_at_budget20",
                "within_parent_macro_recall_top20",
                "binary_ndcg_true_top10_at_budget10",
                "Rdual_exact_min_spearman",
                "model_name_ascending_tie_break",
            ],
        },
        "prediction_labels": labels,
        "models": list(model_contract),
        "per_prediction_metrics": all_metrics,
        "seed_mean_R8_R9_then_exact_min_metrics": ensemble_metrics,
        "seed_stability": stability,
        "development_selected_model": selected,
        "development_selection_is_formal_test_evidence": False,
    }


def write_outputs(output_dir: Path, result: Mapping[str, Any]) -> None:
    reject_forbidden_path(output_dir, "output")
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp.", dir=output_dir.parent))
    try:
        result_path = temp / "DEVELOPMENT_METRICS.json"
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rows = []
        for model, value in result["seed_mean_R8_R9_then_exact_min_metrics"].items():
            summary = value["primary_summary"]
            rows.append({
                "model": model,
                "selected": str(model == result["development_selected_model"]).lower(),
                **summary,
                "Rdual_spearman": value["Rdual_exact_min"]["spearman"],
                "Rdual_mae": value["Rdual_exact_min"]["mae"],
                "Rdual_rmse": value["Rdual_exact_min"]["rmse"],
            })
        with (temp / "MODEL_SELECTION.tsv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        hashes = {
            "DEVELOPMENT_METRICS.json": sha256_file(result_path),
            "MODEL_SELECTION.tsv": sha256_file(temp / "MODEL_SELECTION.tsv"),
        }
        (temp / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
        os.replace(temp, output_dir)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-tsv", type=Path, required=True)
    parser.add_argument("--expected-teacher-sha256", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--prediction", action="append", required=True, help="seed=seed_N/OPEN_SCORE_PREDICTIONS.tsv; repeat for each seed")
    parser.add_argument("--expected-seeds", default="43,97,193")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate(
        args.teacher_tsv,
        args.expected_teacher_sha256,
        args.split_manifest,
        [parse_prediction_arg(raw) for raw in args.prediction],
        expected_seeds=parse_seeds(args.expected_seeds),
    )
    write_outputs(args.output_dir, result)
    print(json.dumps({
        "status": result["status"],
        "development_rows": result["counts"]["development"],
        "selected_model": result["development_selected_model"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
