#!/usr/bin/env python3
"""Train and explicitly unseal-evaluate the V2.5 generic ordinal ranker.

The default command trains only on OPEN_DEVELOPMENT train/dev labels. Formal
evaluation is a separate --unseal-evaluate command that requires an existing
run directory and an explicit sealed-label path.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import torch
from torch import nn

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_PREPARED = EXP_DIR / "prepared" / "phase2_v2_5_generic"
DEFAULT_RECORDS = DEFAULT_PREPARED / "nanobind_affinity_train_dev_v2_5.csv"
DEFAULT_FORMAL_BLINDED = DEFAULT_PREPARED / "nanobind_affinity_formal_blinded_v2_5.csv"
DEFAULT_EMBEDDINGS = DEFAULT_PREPARED / "frozen_sequence_embeddings.pt"
DEFAULT_OUT = EXP_DIR / "runs" / "phase2_v2_5_generic"
DEFAULT_V2_4_CHECKPOINT = EXP_DIR / "checkpoints" / "phase2_v2_4_best_checkpoint.pt"

LABEL_COLUMNS = {"label_value", "label_unit", "label_direction", "affinity_kd_m", "affinity_score"}
MODEL_INPUT_COLUMNS = {
    "sample_id",
    "sequence_sha256",
    "target_sequence_sha256",
    "vhh_sequence",
    "target_sequence",
    "vhh_sequence_length",
    "target_sequence_length",
    "split_group_id",
    "ranking_group_id",
    "split",
    "assay_type",
    "source_id",
    "evidence_level",
    "ground_truth_kind",
    "real_assay_lane",
    "proxy_lane",
    "allowed_use",
    "sealed_status",
}
REQUIRED_TRAIN_COLUMNS = MODEL_INPUT_COLUMNS | LABEL_COLUMNS
BASELINE_ORDER = (
    "random_within_group",
    "train_only_source_assay_prior",
    "leakage_safe_sequence_identity_nn",
    "frozen_cosine_distance",
    "frozen_v2_4",
    "nanobind_external_prior",
)


@dataclass
class Config:
    records_csv: str = str(DEFAULT_RECORDS)
    embeddings_pt: str = str(DEFAULT_EMBEDDINGS)
    formal_blinded_csv: str = str(DEFAULT_FORMAL_BLINDED)
    out_dir: str = str(DEFAULT_OUT)
    run_dir: str = ""
    seeds: tuple[int, ...] = (43, 53, 67)
    epochs: int = 40
    lr: float = 1e-3
    weight_decay: float = 1e-4
    hidden_dim: int = 64
    dropout: float = 0.05
    device: str = "auto"
    min_group_size: int = 2
    batch_groups: int = 8
    v2_4_checkpoint: str = str(DEFAULT_V2_4_CHECKPOINT)
    unseal_evaluate: bool = False
    formal_labels_csv: str = ""


class ShallowOrdinalRanker(nn.Module):
    def __init__(self, embedding_dim: int, hidden_dim: int, dropout: float):
        super().__init__()
        input_dim = embedding_dim * 4 + 4
        self.net = nn.Sequential(
            nn.LayerNorm(input_dim),
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.net(features).squeeze(-1)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def write_csv_atomic(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_sha256(path: Path, expected: str, label: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"Frozen artifact SHA256 mismatch for {label}: expected {expected}, observed {observed}")


def validate_lane_rows(rows: Sequence[dict[str, Any]], expected_split: str | None = None) -> None:
    for row in rows:
        if text_value(row.get("evidence_level")) != "E4" or text_value(row.get("ground_truth_kind")) != "real_assay_binding_kd":
            raise ValueError("V2.5 generic slice accepts only E4 real-assay binding rows")
        if text_value(row.get("real_assay_lane")).lower() != "yes" or text_value(row.get("proxy_lane")).lower() != "no":
            raise ValueError("Real-assay/proxy lane separation was violated")
        if text_value(row.get("allowed_use")) != "EXPERIMENTAL_RANKING_ONLY":
            raise ValueError("V2.5 generic rows require allowed_use=EXPERIMENTAL_RANKING_ONLY")
        if expected_split is not None and text_value(row.get("split")) != expected_split:
            raise ValueError(f"Expected only {expected_split} rows")


def read_records(path: Path, require_labels: bool = True) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    required = REQUIRED_TRAIN_COLUMNS if require_labels else MODEL_INPUT_COLUMNS
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Records missing required columns: {sorted(missing)}")
    rows = frame.to_dict("records")
    validate_lane_rows(rows)
    if require_labels:
        for row in rows:
            if text_value(row.get("split")) == "formal":
                raise ValueError("Training records must not include formal rows")
            if text_value(row.get("split")) not in {"train", "dev"}:
                raise ValueError(f"Unexpected development split: {row.get('split')!r}")
            if text_value(row.get("sealed_status")) != "OPEN_DEVELOPMENT":
                raise ValueError("Train/dev labels must have sealed_status=OPEN_DEVELOPMENT")
            float(row["affinity_score"])
    return rows


def read_formal_blinded(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    exposed = set(frame.columns) & LABEL_COLUMNS
    if exposed:
        raise ValueError(f"Formal blinded manifest exposes label columns: {sorted(exposed)}")
    missing = MODEL_INPUT_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Formal blinded manifest is missing model inputs: {sorted(missing)}")
    rows = frame.to_dict("records")
    validate_lane_rows(rows, expected_split="formal")
    for row in rows:
        if text_value(row.get("sealed_status")) != "SEALED_LABELS":
            raise ValueError("Formal blinded rows must have sealed_status=SEALED_LABELS")
        vhh = text_value(row.get("vhh_sequence"))
        target = text_value(row.get("target_sequence"))
        if not vhh or not target:
            raise ValueError("Formal blinded rows must retain both model-input sequences")
        if int(row["vhh_sequence_length"]) != len(vhh) or int(row["target_sequence_length"]) != len(target):
            raise ValueError("Formal sequence length metadata does not match retained sequences")
    return rows


def feature_input_fingerprint(rows: Sequence[dict[str, Any]]) -> str:
    columns = sorted(MODEL_INPUT_COLUMNS)
    payload = [{column: text_value(row.get(column)) for column in columns} for row in rows]
    payload.sort(key=lambda row: row["sample_id"])
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def merge_formal_labels(blinded_rows: Sequence[dict[str, Any]], labels_csv: Path) -> list[dict[str, Any]]:
    labels = pd.read_csv(labels_csv)
    required = {"sample_id", *LABEL_COLUMNS, "sealed_status"}
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"Formal labels missing columns: {sorted(missing)}")
    if labels["sample_id"].duplicated().any():
        raise ValueError("Formal labels contain duplicate sample_id values")
    if set(labels["sealed_status"].astype(str)) != {"SEALED_LABELS"}:
        raise ValueError("Formal label file must have sealed_status=SEALED_LABELS")
    label_by_id = {text_value(row["sample_id"]): row for row in labels.to_dict("records")}
    blinded_ids = [text_value(row["sample_id"]) for row in blinded_rows]
    if set(blinded_ids) != set(label_by_id) or len(blinded_ids) != len(label_by_id):
        raise ValueError("Formal labels do not exactly match blinded manifest")
    before = feature_input_fingerprint(blinded_rows)
    merged: list[dict[str, Any]] = []
    for blinded in blinded_rows:
        row = dict(blinded)
        label = label_by_id[text_value(blinded["sample_id"])]
        for column in LABEL_COLUMNS:
            row[column] = label[column]
        float(row["affinity_score"])
        merged.append(row)
    if feature_input_fingerprint(merged) != before:
        raise RuntimeError("Unsealing changed formal model inputs")
    return merged


def load_formal_for_unseal(blinded_csv: Path, labels_csv: Path) -> list[dict[str, Any]]:
    return merge_formal_labels(read_formal_blinded(blinded_csv), labels_csv)


def identity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    length = max(len(a), len(b))
    matches = sum(1 for left, right in zip(a, b) if left == right)
    return matches / float(length)


def make_features(rows: Sequence[dict[str, Any]], embeddings: dict[str, torch.Tensor]) -> torch.Tensor:
    features: list[torch.Tensor] = []
    for row in rows:
        vhh = embeddings[text_value(row["sequence_sha256"])].float()
        target = embeddings[text_value(row["target_sequence_sha256"])].float()
        if vhh.ndim != 1 or target.ndim != 1 or vhh.shape != target.shape:
            raise ValueError(f"Embedding shape mismatch for {row['sample_id']}")
        vhh_length = int(row["vhh_sequence_length"])
        target_length = int(row["target_sequence_length"])
        if vhh_length != len(text_value(row["vhh_sequence"])) or target_length != len(text_value(row["target_sequence"])):
            raise ValueError(f"Sequence length metadata mismatch for {row['sample_id']}")
        cosine = torch.nn.functional.cosine_similarity(vhh.unsqueeze(0), target.unsqueeze(0)).squeeze(0)
        distance = torch.linalg.vector_norm(vhh - target).reshape(1)
        scalars = torch.tensor(
            [float(cosine), float(distance), math.log1p(vhh_length), math.log1p(target_length)], dtype=torch.float32
        )
        features.append(torch.cat([vhh, target, torch.abs(vhh - target), vhh * target, scalars]))
    return torch.stack(features) if features else torch.empty((0, 0), dtype=torch.float32)


def group_indices(rows: Sequence[dict[str, Any]], split: str, min_group_size: int) -> list[list[int]]:
    buckets: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        if text_value(row["split"]) == split:
            buckets.setdefault(text_value(row["ranking_group_id"]), []).append(index)
    return [indices for _, indices in sorted(buckets.items()) if len(indices) >= min_group_size]


def assert_exact_split_isolation(rows: Sequence[dict[str, Any]]) -> None:
    for column in ("sequence_sha256", "target_sequence_sha256", "split_group_id", "ranking_group_id"):
        seen: dict[str, set[str]] = {}
        for row in rows:
            seen.setdefault(text_value(row[column]), set()).add(text_value(row["split"]))
        leaking = [key for key, splits in seen.items() if len(splits) > 1]
        if leaking:
            raise ValueError(f"Exact split leakage in {column}: {leaking[:3]}")


def assert_train_formal_disjoint(train_dev_rows: Sequence[dict[str, Any]], formal_rows: Sequence[dict[str, Any]]) -> None:
    for column in ("sequence_sha256", "target_sequence_sha256", "split_group_id", "ranking_group_id"):
        development = {text_value(row[column]) for row in train_dev_rows}
        formal = {text_value(row[column]) for row in formal_rows}
        overlap = development & formal
        if overlap:
            raise ValueError(f"Formal leakage against development in {column}: {sorted(overlap)[:3]}")


def ordinal_pair_loss(scores: torch.Tensor, labels: torch.Tensor, groups: Sequence[Sequence[int]]) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    for indices in groups:
        index = torch.tensor(list(indices), dtype=torch.long, device=scores.device)
        group_scores = scores[index]
        group_labels = labels[index]
        for left in range(len(indices)):
            for right in range(len(indices)):
                if float(group_labels[left] - group_labels[right]) > 1e-8:
                    losses.append(nn.functional.softplus(-(group_scores[left] - group_scores[right])))
    return torch.stack(losses).mean() if losses else scores.sum() * 0.0


def pairwise_group_values(
    rows: Sequence[dict[str, Any]], scores: Sequence[float], groups: Sequence[Sequence[int]]
) -> dict[str, float]:
    labels = [float(row["affinity_score"]) for row in rows]
    values: dict[str, float] = {}
    for indices in groups:
        correct = 0.0
        total = 0
        for left_pos in range(len(indices)):
            for right_pos in range(left_pos + 1, len(indices)):
                left, right = indices[left_pos], indices[right_pos]
                label_delta = labels[left] - labels[right]
                if abs(label_delta) <= 1e-8:
                    continue
                score_delta = float(scores[left]) - float(scores[right])
                total += 1
                if abs(score_delta) <= 1e-12:
                    correct += 0.5
                elif score_delta * label_delta > 0:
                    correct += 1.0
        if total:
            values[text_value(rows[indices[0]]["ranking_group_id"])] = correct / total
    return values


def pairwise_accuracy(rows: Sequence[dict[str, Any]], scores: Sequence[float], groups: Sequence[Sequence[int]]) -> float:
    values = pairwise_group_values(rows, scores, groups)
    return float(statistics.mean(values.values())) if values else 0.0


def _expected_dcg_with_score_ties(indices: Sequence[int], scores: Sequence[float], gains: dict[int, float]) -> float:
    ranked = sorted(indices, key=lambda index: (-float(scores[index]), index))
    total = 0.0
    start = 0
    while start < len(ranked):
        end = start + 1
        while end < len(ranked) and abs(float(scores[ranked[end]]) - float(scores[ranked[start]])) <= 1e-12:
            end += 1
        mean_gain = statistics.mean(gains[index] for index in ranked[start:end])
        total += mean_gain * sum(1.0 / math.log2(rank + 2) for rank in range(start, end))
        start = end
    return total


def ndcg_group_values(rows: Sequence[dict[str, Any]], scores: Sequence[float], groups: Sequence[Sequence[int]]) -> dict[str, float]:
    labels = [float(row["affinity_score"]) for row in rows]
    values: dict[str, float] = {}
    for indices in groups:
        minimum = min(labels[index] for index in indices)
        gains = {index: max(labels[index] - minimum, 0.0) for index in indices}
        ideal = sorted(indices, key=lambda index: labels[index], reverse=True)
        ideal_dcg = sum(gains[index] / math.log2(rank + 2) for rank, index in enumerate(ideal))
        dcg = _expected_dcg_with_score_ties(indices, scores, gains)
        values[text_value(rows[indices[0]]["ranking_group_id"])] = dcg / ideal_dcg if ideal_dcg > 0 else 1.0
    return values


def ndcg(rows: Sequence[dict[str, Any]], scores: Sequence[float], groups: Sequence[Sequence[int]]) -> float:
    values = ndcg_group_values(rows, scores, groups)
    return float(statistics.mean(values.values())) if values else 0.0


def unique_best_rank_metrics(
    rows: Sequence[dict[str, Any]], scores: Sequence[float], groups: Sequence[Sequence[int]]
) -> tuple[float | None, float | None, int]:
    labels = [float(row["affinity_score"]) for row in rows]
    reciprocal_ranks: list[float] = []
    hit_at_one: list[float] = []
    for indices in groups:
        best_label = max(labels[index] for index in indices)
        best = [index for index in indices if abs(labels[index] - best_label) <= 1e-8]
        if len(best) != 1:
            continue
        best_index = best[0]
        best_score = float(scores[best_index])
        higher = sum(float(scores[index]) > best_score + 1e-12 for index in indices)
        tied = sum(abs(float(scores[index]) - best_score) <= 1e-12 for index in indices)
        reciprocal_ranks.append(statistics.mean(1.0 / rank for rank in range(higher + 1, higher + tied + 1)))
        hit_at_one.append(1.0 / tied if higher == 0 else 0.0)
    if not reciprocal_ranks:
        return None, None, 0
    return float(statistics.mean(reciprocal_ranks)), float(statistics.mean(hit_at_one)), len(reciprocal_ranks)


def score_metrics(rows: Sequence[dict[str, Any]], scores: Sequence[float], groups: Sequence[Sequence[int]]) -> dict[str, Any]:
    mrr, hit, best_group_count = unique_best_rank_metrics(rows, scores, groups)
    pair_values = pairwise_group_values(rows, scores, groups)
    return {
        "macro_group_pairwise_preference_accuracy": float(statistics.mean(pair_values.values())) if pair_values else 0.0,
        "macro_group_ndcg_all": ndcg(rows, scores, groups),
        "group_mrr": mrr,
        "hit_at_1": hit,
        "group_count": len(groups),
        "pairwise_evaluable_group_count": len(pair_values),
        "unique_best_group_count": best_group_count,
    }


def exact_random_group_expectations(
    rows: Sequence[dict[str, Any]], groups: Sequence[Sequence[int]]
) -> dict[str, dict[str, float | None]]:
    labels = [float(row["affinity_score"]) for row in rows]
    output: dict[str, dict[str, float | None]] = {}
    for indices in groups:
        group_id = text_value(rows[indices[0]]["ranking_group_id"])
        minimum = min(labels[index] for index in indices)
        gains = [max(labels[index] - minimum, 0.0) for index in indices]
        ideal_gains = sorted(gains, reverse=True)
        ideal_dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(ideal_gains))
        expected_dcg = statistics.mean(gains) * sum(1.0 / math.log2(rank + 2) for rank in range(len(indices)))
        unique_best = sum(abs(labels[index] - max(labels[item] for item in indices)) <= 1e-8 for index in indices) == 1
        output[group_id] = {
            "pairwise": 0.5,
            "ndcg": expected_dcg / ideal_dcg if ideal_dcg > 0 else 1.0,
            "mrr": sum(1.0 / rank for rank in range(1, len(indices) + 1)) / len(indices) if unique_best else None,
            "hit_at_1": 1.0 / len(indices) if unique_best else None,
        }
    return output


def exact_random_metrics(rows: Sequence[dict[str, Any]], groups: Sequence[Sequence[int]]) -> dict[str, Any]:
    expectations = exact_random_group_expectations(rows, groups)
    pairwise_groups = pairwise_group_values(rows, [0.0] * len(rows), groups)
    ndcg_values = [float(item["ndcg"]) for item in expectations.values()]
    mrr_values = [float(item["mrr"]) for item in expectations.values() if item["mrr"] is not None]
    hit_values = [float(item["hit_at_1"]) for item in expectations.values() if item["hit_at_1"] is not None]
    return {
        "macro_group_pairwise_preference_accuracy": 0.5 if pairwise_groups else 0.0,
        "macro_group_ndcg_all": float(statistics.mean(ndcg_values)) if ndcg_values else 0.0,
        "group_mrr": float(statistics.mean(mrr_values)) if mrr_values else None,
        "hit_at_1": float(statistics.mean(hit_values)) if hit_values else None,
        "group_count": len(groups),
        "pairwise_evaluable_group_count": len(pairwise_groups),
        "unique_best_group_count": len(mrr_values),
        "expectation_kind": "EXACT_UNIFORM_RANDOM_PERMUTATION_BY_GROUP_SIZE",
    }


def evaluate_named(
    rows: Sequence[dict[str, Any]], groups: Sequence[Sequence[int]], named_scores: dict[str, Sequence[float]]
) -> dict[str, dict[str, Any]]:
    return {name: score_metrics(rows, scores, groups) for name, scores in named_scores.items()}


def source_assay_prior(train_rows: Sequence[dict[str, Any]], rows: Sequence[dict[str, Any]]) -> list[float]:
    values: dict[tuple[str, str], list[float]] = {}
    all_values: list[float] = []
    for row in train_rows:
        label = float(row["affinity_score"])
        values.setdefault((text_value(row["source_id"]), text_value(row["assay_type"])), []).append(label)
        all_values.append(label)
    global_median = float(statistics.median(all_values)) if all_values else 0.0
    priors = {key: float(statistics.median(group_values)) for key, group_values in values.items()}
    return [priors.get((text_value(row["source_id"]), text_value(row["assay_type"])), global_median) for row in rows]


def sequence_identity_nn(train_rows: Sequence[dict[str, Any]], rows: Sequence[dict[str, Any]]) -> list[float]:
    scores: list[float] = []
    for row in rows:
        best_similarity = -1.0
        best_label = 0.0
        for train_row in train_rows:
            similarity = 0.5 * identity(text_value(row.get("vhh_sequence")), text_value(train_row.get("vhh_sequence")))
            similarity += 0.5 * identity(text_value(row.get("target_sequence")), text_value(train_row.get("target_sequence")))
            if similarity > best_similarity:
                best_similarity = similarity
                best_label = float(train_row["affinity_score"])
        scores.append(best_label)
    return scores


def frozen_cosine_distance(rows: Sequence[dict[str, Any]], embeddings: dict[str, torch.Tensor]) -> list[float]:
    scores: list[float] = []
    for row in rows:
        vhh = embeddings[text_value(row["sequence_sha256"])].float()
        target = embeddings[text_value(row["target_sequence_sha256"])].float()
        cosine = float(torch.nn.functional.cosine_similarity(vhh.unsqueeze(0), target.unsqueeze(0)).squeeze(0))
        distance = float(torch.linalg.vector_norm(vhh - target))
        scores.append(cosine - 0.01 * distance)
    return scores


def baseline_registry(cfg: Config) -> dict[str, dict[str, Any]]:
    v2_4_path = Path(cfg.v2_4_checkpoint)
    v2_4_presence = "present" if v2_4_path.exists() else "missing"
    return {
        "random_within_group": {
            "status": "ELIGIBLE_EXACT_EXPECTATION",
            "formal_eligible": True,
            "reason": "Analytic uniform-random expectation at each actual ranking-group size",
        },
        "train_only_source_assay_prior": {
            "status": "ELIGIBLE",
            "formal_eligible": True,
            "reason": "Median affinity score estimated from training rows only",
        },
        "leakage_safe_sequence_identity_nn": {
            "status": "ELIGIBLE",
            "formal_eligible": True,
            "reason": "Nearest-neighbor labels come only from the exact-component-isolated training split",
        },
        "frozen_cosine_distance": {
            "status": "ELIGIBLE",
            "formal_eligible": True,
            "reason": "Fixed score from the same frozen sequence embeddings used by the shallow head",
        },
        "frozen_v2_4": {
            "status": "INELIGIBLE_WITH_REASON",
            "formal_eligible": False,
            "checkpoint": str(v2_4_path),
            "reason": (
                f"Local checkpoint is {v2_4_presence}, but V2.4 requires residue-level ESM2 tensors, CDR masks, and its contact/pair "
                "encoder contract; this slice has pooled frozen embeddings only. Reusing the pair head would require feature "
                "regeneration or retraining and would not be a frozen like-for-like baseline."
            ),
        },
        "nanobind_external_prior": {
            "status": "LEAKAGE_UNSAFE_DIAGNOSTIC",
            "eligibility": "INELIGIBLE",
            "formal_eligible": False,
            "reason": (
                "Available NanoBind external-prior checkpoints were trained with source rows that overlap this custom split; "
                "they are recorded for provenance only and are excluded from formal scoring and baseline selection."
            ),
        },
    }


def eligible_baseline_scores(
    train_rows: Sequence[dict[str, Any]], rows: Sequence[dict[str, Any]], embeddings: dict[str, torch.Tensor]
) -> dict[str, list[float]]:
    return {
        "train_only_source_assay_prior": source_assay_prior(train_rows, rows),
        "leakage_safe_sequence_identity_nn": sequence_identity_nn(train_rows, rows),
        "frozen_cosine_distance": frozen_cosine_distance(rows, embeddings),
    }


def metrics_with_registry(
    rows: Sequence[dict[str, Any]],
    groups: Sequence[Sequence[int]],
    scores_by_method: dict[str, Sequence[float]],
    registry: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for method in BASELINE_ORDER:
        entry = dict(registry[method])
        if method == "random_within_group":
            entry.update(exact_random_metrics(rows, groups))
        elif registry[method]["formal_eligible"]:
            entry.update(score_metrics(rows, scores_by_method[method], groups))
        output[method] = entry
    return output


def select_strongest_baseline(
    dev_metrics: dict[str, dict[str, Any]], registry: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    candidates: list[tuple[float, int, str]] = []
    candidate_metrics: dict[str, float] = {}
    for order, method in enumerate(BASELINE_ORDER):
        if not registry[method]["formal_eligible"]:
            continue
        value = float(dev_metrics[method]["macro_group_pairwise_preference_accuracy"])
        candidate_metrics[method] = value
        candidates.append((value, -order, method))
    if not candidates:
        raise ValueError("No eligible preregistered baseline is available for development selection")
    selected = max(candidates)[2]
    return {
        "schema_version": "phase2_v2_5_generic_dev_baseline_selection_v1",
        "selected_baseline": selected,
        "selection_metric": "macro_group_pairwise_preference_accuracy",
        "selection_scope": "DEVELOPMENT_ONLY_BEFORE_FORMAL_UNSEAL",
        "tie_break": "BASELINE_ORDER_FIRST",
        "candidate_dev_metrics": candidate_metrics,
        "formal_metrics_consulted": False,
        "selected_at_utc": utc_now(),
    }


def resolve_device(requested: str) -> torch.device:
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA training/evaluation was requested but torch.cuda.is_available() is false")
    return torch.device(requested)


def train_one_seed(
    cfg: Config,
    seed: int,
    rows: list[dict[str, Any]],
    embeddings: dict[str, torch.Tensor],
    run_root: Path,
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = resolve_device(cfg.device)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.set_float32_matmul_precision("high")
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)

    features = make_features(rows, embeddings).to(device)
    labels = torch.tensor([float(row["affinity_score"]) for row in rows], dtype=torch.float32, device=device)
    train_groups = group_indices(rows, "train", cfg.min_group_size)
    dev_groups = group_indices(rows, "dev", cfg.min_group_size)
    if not train_groups or not dev_groups:
        raise ValueError(f"Need non-empty target ranking groups, got train={len(train_groups)} dev={len(dev_groups)}")

    embedding_dim = (features.shape[1] - 4) // 4
    model = ShallowOrdinalRanker(embedding_dim=embedding_dim, hidden_dim=cfg.hidden_dim, dropout=cfg.dropout).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    history: list[dict[str, float]] = []
    best_dev = -1.0
    best_epoch = -1
    best_state: dict[str, torch.Tensor] | None = None
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        shuffled = list(train_groups)
        random.shuffle(shuffled)
        losses: list[float] = []
        for start in range(0, len(shuffled), max(cfg.batch_groups, 1)):
            batch_groups = shuffled[start : start + max(cfg.batch_groups, 1)]
            optimizer.zero_grad(set_to_none=True)
            scores = model(features)
            loss = ordinal_pair_loss(scores, labels, batch_groups)
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite V2.5 loss at seed={seed} epoch={epoch}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        model.eval()
        with torch.no_grad():
            shallow_scores = model(features).detach().cpu().tolist()
        dev_metric = pairwise_accuracy(rows, shallow_scores, dev_groups)
        history.append({"epoch": float(epoch), "train_loss": statistics.mean(losses), "dev_pairwise": dev_metric})
        if dev_metric > best_dev:
            best_dev = dev_metric
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("No development-selected shallow checkpoint was produced")
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        shallow_scores = model(features).detach().cpu().tolist()

    train_rows = [row for row in rows if text_value(row["split"]) == "train"]
    baseline_scores = eligible_baseline_scores(train_rows, rows, embeddings)
    dev_metrics = metrics_with_registry(rows, dev_groups, baseline_scores, registry)
    dev_metrics["shallow_head"] = {
        "status": "ELIGIBLE_MODEL",
        "formal_eligible": True,
        **score_metrics(rows, shallow_scores, dev_groups),
    }

    seed_dir = run_root / f"seed_{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    predictions = [
        {
            "sample_id": row["sample_id"],
            "split": row["split"],
            "split_group_id": row["split_group_id"],
            "ranking_group_id": row["ranking_group_id"],
            "ranking_score": f"{score:.9f}",
            "supported_label_axis": "binding",
            "evidence_level": row["evidence_level"],
            "model_support_domain": "generic_real_assay_transfer_only",
            "abstain": "false",
            "abstain_reason": "",
            "claim_boundary": "No blocker probability, Kd, IC50, or PVRIG target claim",
        }
        for row, score in zip(rows, shallow_scores)
    ]
    write_csv_atomic(seed_dir / "predictions_train_dev.csv", predictions, list(predictions[0]))
    checkpoint = {
        "schema_version": "phase2_v2_5_generic_shallow_checkpoint_v2",
        "model": best_state,
        "config": asdict(cfg),
        "seed": seed,
        "embedding_dim": int(embedding_dim),
        "best_epoch": best_epoch,
        "best_dev_pairwise": best_dev,
        "checkpoint_selection_scope": "DEVELOPMENT_ONLY",
    }
    checkpoint_path = seed_dir / "shallow_head_checkpoint.pt"
    torch.save(checkpoint, checkpoint_path)

    if device.type == "cuda":
        torch.cuda.synchronize(device)
        cuda_name = torch.cuda.get_device_name(device)
        peak_bytes: int | None = int(torch.cuda.max_memory_allocated(device))
    else:
        cuda_name = None
        peak_bytes = None
    telemetry = {
        "requested_device": cfg.device,
        "actual_device": device.type,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_name": cuda_name,
        "cuda_peak_allocated_bytes": peak_bytes,
        "cuda_peak_allocated_mib": (peak_bytes / (1024.0 * 1024.0)) if peak_bytes is not None else None,
        "torch_cuda_version": torch.version.cuda,
        "elapsed_seconds": time.perf_counter() - started,
    }
    result = {
        "seed": seed,
        "device": device.type,
        "best_epoch": best_epoch,
        "best_dev_pairwise": best_dev,
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "dev_metrics": dev_metrics,
        "history": history,
        "telemetry": telemetry,
        "formal_unseal_status": "SEALED_LABELS_NOT_READ",
        "calibration": {"status": "NOT_APPLICABLE", "reason": "No verified binary positive/negative lane"},
    }
    write_json_atomic(seed_dir / "metrics.json", result)
    return result


def _method_pairwise_values(
    method: str,
    rows: Sequence[dict[str, Any]],
    groups: Sequence[Sequence[int]],
    scores_by_method: dict[str, Sequence[float]],
) -> dict[str, float]:
    if method == "random_within_group":
        evaluable = pairwise_group_values(rows, [0.0] * len(rows), groups)
        return {group_id: 0.5 for group_id in evaluable}
    return pairwise_group_values(rows, scores_by_method[method], groups)


def paired_group_delta(
    rows: Sequence[dict[str, Any]],
    groups: Sequence[Sequence[int]],
    shallow_scores: Sequence[float],
    selected_baseline: str,
    baseline_scores: dict[str, Sequence[float]],
) -> dict[str, Any]:
    shallow = pairwise_group_values(rows, shallow_scores, groups)
    baseline = _method_pairwise_values(selected_baseline, rows, groups, baseline_scores)
    common = sorted(set(shallow) & set(baseline))
    values = [shallow[group_id] - baseline[group_id] for group_id in common]
    return {
        "baseline": selected_baseline,
        "unit": "ranking_group_id",
        "group_count": len(values),
        "mean_delta": float(statistics.mean(values)) if values else None,
        "median_delta": float(statistics.median(values)) if values else None,
        "positive_group_count": sum(value > 0 for value in values),
        "positive_group_fraction": (sum(value > 0 for value in values) / len(values)) if values else None,
        "group_deltas": [{"ranking_group_id": group_id, "delta": value} for group_id, value in zip(common, values)],
    }


def average_ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: (float(values[index]), index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and abs(float(values[ordered[end]]) - float(values[ordered[start]])) <= 1e-12:
            end += 1
        rank = (start + 1 + end) / 2.0
        for index in ordered[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.mean(left), statistics.mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_norm = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_norm = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    return numerator / (left_norm * right_norm) if left_norm > 0 and right_norm > 0 else None


def seed_consistency(
    rows: Sequence[dict[str, Any]],
    groups: Sequence[Sequence[int]],
    seed_scores: dict[int, Sequence[float]],
    seed_deltas: dict[int, float | None],
    output_dir: Path,
) -> dict[str, Any]:
    seeds = sorted(seed_scores)
    comparisons: list[dict[str, Any]] = []
    for left_pos, left_seed in enumerate(seeds):
        for right_seed in seeds[left_pos + 1 :]:
            left_scores, right_scores = seed_scores[left_seed], seed_scores[right_seed]
            top_agreements = []
            for indices in groups:
                left_top = max(indices, key=lambda index: (float(left_scores[index]), text_value(rows[index]["sample_id"])))
                right_top = max(indices, key=lambda index: (float(right_scores[index]), text_value(rows[index]["sample_id"])))
                top_agreements.append(left_top == right_top)
            comparisons.append(
                {
                    "left_seed": left_seed,
                    "right_seed": right_seed,
                    "global_spearman": pearson(average_ranks(left_scores), average_ranks(right_scores)),
                    "ranking_group_top1_agreement": statistics.mean(top_agreements) if top_agreements else None,
                }
            )
    sample_rows = []
    for index, row in enumerate(rows):
        values = [float(seed_scores[seed][index]) for seed in seeds]
        sample_rows.append(
            {
                "sample_id": row["sample_id"],
                "ranking_group_id": row["ranking_group_id"],
                "seed_score_mean": statistics.mean(values),
                "seed_score_std": statistics.pstdev(values) if len(values) > 1 else 0.0,
                "seed_score_min": min(values),
                "seed_score_max": max(values),
            }
        )
    write_csv_atomic(output_dir / "formal_seed_consistency.csv", sample_rows, list(sample_rows[0]))
    finite_deltas = [value for value in seed_deltas.values() if value is not None]
    return {
        "seed_count": len(seeds),
        "pairwise_seed_comparisons": comparisons,
        "primary_delta_by_seed": {str(seed): seed_deltas[seed] for seed in seeds},
        "median_primary_delta": float(statistics.median(finite_deltas)) if finite_deltas else None,
        "positive_delta_seed_count": sum(value > 0 for value in finite_deltas),
        "at_least_two_of_three_positive": len(seeds) == 3 and sum(value > 0 for value in finite_deltas) >= 2,
    }


def formal_predictions(
    rows: Sequence[dict[str, Any]],
    groups: Sequence[Sequence[int]],
    seed: int,
    baseline_scores: dict[str, Sequence[float]],
    shallow_scores: Sequence[float],
    registry: dict[str, dict[str, Any]],
    selected_baseline: str,
) -> list[dict[str, Any]]:
    random_expectations = exact_random_group_expectations(rows, groups)
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        group_id = text_value(row["ranking_group_id"])
        for method in (*BASELINE_ORDER, "shallow_head"):
            if method == "shallow_head":
                status, eligible, reason, score = "ELIGIBLE_MODEL", True, "", float(shallow_scores[index])
            else:
                entry = registry[method]
                status = text_value(entry["status"])
                eligible = bool(entry["formal_eligible"])
                reason = text_value(entry.get("reason"))
                score = float(baseline_scores[method][index]) if method in baseline_scores else None
            random_group = random_expectations[group_id] if method == "random_within_group" else {}
            output.append(
                {
                    "sample_id": row["sample_id"],
                    "split_group_id": row["split_group_id"],
                    "ranking_group_id": group_id,
                    "seed": seed,
                    "method": method,
                    "status": status,
                    "formal_eligible": str(eligible).lower(),
                    "ranking_score": "" if score is None else f"{score:.9f}",
                    "random_pairwise_expectation": random_group.get("pairwise", ""),
                    "random_group_ndcg_expectation": random_group.get("ndcg", ""),
                    "random_group_mrr_expectation": random_group.get("mrr", ""),
                    "random_group_hit_at_1_expectation": random_group.get("hit_at_1", ""),
                    "ineligible_reason": reason if not eligible else "",
                    "dev_selected_strongest_baseline": selected_baseline,
                    "supported_label_axis": "binding",
                    "model_support_domain": "generic_real_assay_transfer_only",
                    "claim_boundary": "No blocker probability, Kd, IC50, or PVRIG target claim",
                }
            )
    return output


def evaluate_formal(cfg: Config) -> dict[str, Any]:
    if not cfg.run_dir:
        raise ValueError("--unseal-evaluate requires --run-dir for an already trained run")
    if not cfg.formal_labels_csv:
        raise ValueError("--unseal-evaluate requires an explicit --formal-labels-csv path")
    run_root = Path(cfg.run_dir).resolve()
    labels_path = Path(cfg.formal_labels_csv).resolve()
    blinded_path = Path(cfg.formal_blinded_csv).resolve()
    if not run_root.is_dir() or not labels_path.is_file() or not blinded_path.is_file():
        raise FileNotFoundError("Formal evaluation requires existing run, blinded manifest, and sealed labels")
    started_marker = run_root / "formal_unseal_started.json"
    final_audit_path = run_root / "formal_unseal_audit.json"
    if started_marker.exists() or final_audit_path.exists():
        raise RuntimeError("This V2.5 run already started formal unsealing; any rerun requires a new version")

    config_path = run_root / "config_resolved.json"
    registry_path = run_root / "baseline_registry.json"
    train_config = json.loads(config_path.read_text(encoding="utf-8"))
    train_summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    selection_path = run_root / "preregistered_selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    artifact_sha256 = train_summary.get("artifact_sha256", {})
    required_hashes = {
        "records_csv",
        "embeddings_pt",
        "formal_blinded_csv",
        "config_resolved_json",
        "baseline_registry_json",
        "preregistered_selection_json",
        "seed_checkpoints",
    }
    if required_hashes - set(artifact_sha256):
        raise ValueError("Training summary lacks the frozen artifact SHA256 preregistration")
    verify_sha256(config_path, artifact_sha256["config_resolved_json"], "config_resolved_json")
    verify_sha256(registry_path, artifact_sha256["baseline_registry_json"], "baseline_registry_json")
    verify_sha256(selection_path, artifact_sha256["preregistered_selection_json"], "preregistered_selection_json")
    verify_sha256(Path(train_config["records_csv"]), artifact_sha256["records_csv"], "records_csv")
    verify_sha256(Path(train_config["embeddings_pt"]), artifact_sha256["embeddings_pt"], "embeddings_pt")
    verify_sha256(blinded_path, artifact_sha256["formal_blinded_csv"], "formal_blinded_csv")
    selected_baseline = text_value(selection["selected_baseline"])
    if selection.get("formal_metrics_consulted") is not False or not registry[selected_baseline]["formal_eligible"]:
        raise ValueError("Development baseline selection artifact is invalid")

    train_dev_rows = read_records(Path(train_config["records_csv"]), require_labels=True)
    train_rows = [row for row in train_dev_rows if text_value(row["split"]) == "train"]
    blinded_rows = read_formal_blinded(blinded_path)
    assert_train_formal_disjoint(train_dev_rows, blinded_rows)
    input_fingerprint = feature_input_fingerprint(blinded_rows)
    embeddings: dict[str, torch.Tensor] = torch.load(train_config["embeddings_pt"], map_location="cpu", weights_only=False)
    needed = {text_value(row["sequence_sha256"]) for row in blinded_rows} | {
        text_value(row["target_sequence_sha256"]) for row in blinded_rows
    }
    missing_embeddings = needed - set(embeddings)
    if missing_embeddings:
        raise ValueError(f"Formal embeddings missing hashes: {sorted(missing_embeddings)[:5]}")

    baseline_scores = eligible_baseline_scores(train_rows, blinded_rows, embeddings)
    features = make_features(blinded_rows, embeddings)
    device = resolve_device(cfg.device)
    seeds = [int(seed) for seed in train_summary["seeds"]]
    seed_scores: dict[int, list[float]] = {}
    checkpoint_paths: dict[str, str] = {}
    formal_telemetry: dict[int, dict[str, Any]] = {}
    for seed in seeds:
        seed_started = time.perf_counter()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)
        checkpoint_path = run_root / f"seed_{seed}" / "shallow_head_checkpoint.pt"
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"Missing preregistered seed checkpoint: {checkpoint_path}")
        expected_checkpoint_sha = artifact_sha256["seed_checkpoints"].get(str(seed))
        if not expected_checkpoint_sha:
            raise ValueError(f"Training summary lacks checkpoint SHA256 for seed {seed}")
        verify_sha256(checkpoint_path, expected_checkpoint_sha, f"seed_{seed}_checkpoint")
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        checkpoint_cfg = checkpoint["config"]
        model = ShallowOrdinalRanker(
            embedding_dim=int(checkpoint["embedding_dim"]),
            hidden_dim=int(checkpoint_cfg["hidden_dim"]),
            dropout=float(checkpoint_cfg["dropout"]),
        ).to(device)
        model.load_state_dict(checkpoint["model"])
        model.eval()
        device_features = features.to(device)
        with torch.inference_mode():
            seed_scores[seed] = model(device_features).detach().cpu().tolist()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
            cuda_device_name = torch.cuda.get_device_name(device)
            peak_bytes: int | None = int(torch.cuda.max_memory_allocated(device))
        else:
            cuda_device_name = None
            peak_bytes = None
        formal_telemetry[seed] = {
            "requested_device": cfg.device,
            "actual_device": device.type,
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_device_name": cuda_device_name,
            "cuda_peak_allocated_bytes": peak_bytes,
            "cuda_peak_allocated_mib": (peak_bytes / (1024.0 * 1024.0)) if peak_bytes is not None else None,
            "torch_cuda_version": torch.version.cuda,
            "elapsed_seconds": time.perf_counter() - seed_started,
        }
        checkpoint_paths[str(seed)] = str(checkpoint_path)
        del model, device_features

    write_json_atomic(
        started_marker,
        {
            "schema_version": "phase2_v2_5_generic_formal_unseal_start_v1",
            "status": "UNSEAL_STARTED_ONE_SHOT",
            "started_at_utc": utc_now(),
            "formal_inference_completed_before_labels_read": True,
            "formal_feature_input_sha256": input_fingerprint,
            "checkpoint_paths": checkpoint_paths,
            "formal_inference_telemetry_by_seed": {str(seed): formal_telemetry[seed] for seed in seeds},
            "selected_baseline_loaded_before_labels_read": selected_baseline,
            "selection_artifact_sha256": sha256_file(selection_path),
        },
    )

    formal_rows = merge_formal_labels(blinded_rows, labels_path)
    if feature_input_fingerprint(formal_rows) != input_fingerprint:
        raise RuntimeError("Formal feature generation changed after label unseal")
    groups = group_indices(formal_rows, "formal", int(train_config["min_group_size"]))
    if not groups:
        raise ValueError("Formal manifest has no evaluable target-specific ranking groups")

    formal_dir = run_root / "formal_evaluation"
    baseline_metrics = metrics_with_registry(formal_rows, groups, baseline_scores, registry)
    seed_results: list[dict[str, Any]] = []
    seed_deltas: dict[int, float | None] = {}
    for seed in seeds:
        shallow_scores = seed_scores[seed]
        metrics = json.loads(json.dumps(baseline_metrics))
        metrics["shallow_head"] = {
            "status": "ELIGIBLE_MODEL",
            "formal_eligible": True,
            **score_metrics(formal_rows, shallow_scores, groups),
        }
        delta = paired_group_delta(formal_rows, groups, shallow_scores, selected_baseline, baseline_scores)
        seed_deltas[seed] = delta["mean_delta"]
        result = {
            "seed": seed,
            "checkpoint": checkpoint_paths[str(seed)],
            "checkpoint_selection_scope": "DEVELOPMENT_ONLY",
            "baseline_selection_scope": "DEVELOPMENT_ONLY_BEFORE_FORMAL_UNSEAL",
            "selected_baseline": selected_baseline,
            "telemetry": formal_telemetry[seed],
            "formal_metrics": metrics,
            "paired_group_delta_vs_dev_selected_baseline": delta,
            "formal_labels_used_for_selection": False,
        }
        seed_dir = formal_dir / f"seed_{seed}"
        predictions = formal_predictions(
            formal_rows, groups, seed, baseline_scores, shallow_scores, registry, selected_baseline
        )
        write_csv_atomic(seed_dir / "formal_predictions.csv", predictions, list(predictions[0]))
        write_json_atomic(seed_dir / "formal_metrics.json", result)
        seed_results.append(result)

    consistency = seed_consistency(formal_rows, groups, seed_scores, seed_deltas, formal_dir)
    write_json_atomic(formal_dir / "formal_seed_consistency.json", consistency)
    summary = {
        "schema_version": "phase2_v2_5_generic_formal_evaluation_v1",
        "run_dir": str(run_root),
        "formal_evaluation_dir": str(formal_dir),
        "formal_unseal_status": "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE",
        "formal_rows": len(formal_rows),
        "ranking_group_count": len(groups),
        "seeds": seeds,
        "dev_selected_strongest_eligible_baseline": selected_baseline,
        "baseline_selection_source": "preregistered_development_only_artifact",
        "formal_labels_used_for_checkpoint_or_method_selection": False,
        "feature_input_sha256_before_and_after_unseal": input_fingerprint,
        "formal_inference_telemetry_by_seed": {str(seed): formal_telemetry[seed] for seed in seeds},
        "seed_results": seed_results,
        "seed_consistency": consistency,
        "claim_boundary": "Generic E4 affinity ranking only; no PVRIG blocking or target-specific claim",
    }
    write_json_atomic(formal_dir / "formal_evaluation_summary.json", summary)
    write_json_atomic(
        final_audit_path,
        {
            "formal_unseal_status": "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE",
            "completed_at_utc": utc_now(),
            "formal_blinded_csv": str(blinded_path),
            "formal_blinded_sha256": sha256_file(blinded_path),
            "formal_labels_csv": str(labels_path),
            "formal_labels_sha256": sha256_file(labels_path),
            "formal_rows": len(formal_rows),
            "formal_run_count": 1,
            "inference_completed_before_labels_read": True,
            "formal_inference_telemetry_by_seed": {str(seed): formal_telemetry[seed] for seed in seeds},
            "formal_features_unchanged_after_unseal": True,
            "formal_labels_used_for_selection": False,
            "next_version_required_for_any_change_or_rerun": True,
        },
    )
    print(json.dumps({"run_dir": str(run_root), "formal_unseal_status": summary["formal_unseal_status"]}, sort_keys=True))
    return summary


def train(cfg: Config) -> dict[str, Any]:
    if cfg.unseal_evaluate:
        return evaluate_formal(cfg)
    records_path = Path(cfg.records_csv)
    embeddings_path = Path(cfg.embeddings_pt)
    formal_blinded_path = Path(cfg.formal_blinded_csv)
    if not formal_blinded_path.is_file():
        raise FileNotFoundError("Training preregistration requires the blinded formal manifest")
    rows = read_records(records_path, require_labels=True)
    assert_exact_split_isolation(rows)
    embeddings: dict[str, torch.Tensor] = torch.load(embeddings_path, map_location="cpu", weights_only=False)
    needed = {text_value(row["sequence_sha256"]) for row in rows} | {text_value(row["target_sequence_sha256"]) for row in rows}
    missing = needed - set(embeddings)
    if missing:
        raise ValueError(f"Embeddings missing required sequence hashes: {sorted(missing)[:5]}")
    if not cfg.seeds:
        raise ValueError("At least one training seed is required")

    timestamp = datetime.now(timezone.utc).strftime("phase2_v2_5_generic_%Y%m%dT%H%M%S_%fZ")
    run_root = Path(cfg.out_dir) / timestamp
    run_root.mkdir(parents=True, exist_ok=False)
    config_path = run_root / "config_resolved.json"
    registry_path = run_root / "baseline_registry.json"
    selection_path = run_root / "preregistered_selection.json"
    write_json_atomic(config_path, asdict(cfg))
    registry = baseline_registry(cfg)
    write_json_atomic(registry_path, registry)
    results = [train_one_seed(cfg, seed, rows, embeddings, run_root, registry) for seed in cfg.seeds]
    selection = select_strongest_baseline(results[0]["dev_metrics"], registry)
    write_json_atomic(selection_path, selection)
    artifact_sha256 = {
        "records_csv": sha256_file(records_path),
        "embeddings_pt": sha256_file(embeddings_path),
        "formal_blinded_csv": sha256_file(formal_blinded_path),
        "config_resolved_json": sha256_file(config_path),
        "baseline_registry_json": sha256_file(registry_path),
        "preregistered_selection_json": sha256_file(selection_path),
        "seed_checkpoints": {str(result["seed"]): result["checkpoint_sha256"] for result in results},
    }
    summary = {
        "schema_version": "phase2_v2_5_generic_train_summary_v2",
        "run_dir": str(run_root),
        "seeds": list(cfg.seeds),
        "seed_results": results,
        "baseline_registry": registry,
        "preregistered_selection": selection,
        "artifact_sha256": artifact_sha256,
        "checkpoint_rule": "maximum development macro-group pairwise accuracy; first epoch on ties",
        "formal_unseal_status": "SEALED_LABELS_NOT_READ",
        "lane_policy": {
            "training_uses_formal_labels": False,
            "real_assay_proxy_separated": True,
            "generic_transfer_only": True,
            "ranking_groups_use_exact_target_not_split_component": True,
        },
    }
    write_json_atomic(run_root / "summary.json", summary)
    print(json.dumps({"run_dir": str(run_root), "formal_unseal_status": summary["formal_unseal_status"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-csv", default=str(DEFAULT_RECORDS))
    parser.add_argument("--embeddings-pt", default=str(DEFAULT_EMBEDDINGS))
    parser.add_argument("--formal-blinded-csv", default=str(DEFAULT_FORMAL_BLINDED))
    parser.add_argument("--formal-labels-csv", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--run-dir", default="", help="Existing trained run; required only with --unseal-evaluate")
    parser.add_argument("--seeds", default="43,53,67")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--min-group-size", type=int, default=2)
    parser.add_argument("--batch-groups", type=int, default=8)
    parser.add_argument("--v2-4-checkpoint", default=str(DEFAULT_V2_4_CHECKPOINT))
    parser.add_argument("--unseal-evaluate", action="store_true")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        records_csv=args.records_csv,
        embeddings_pt=args.embeddings_pt,
        formal_blinded_csv=args.formal_blinded_csv,
        out_dir=args.out_dir,
        run_dir=args.run_dir,
        seeds=tuple(int(item) for item in str(args.seeds).split(",") if item.strip()),
        epochs=args.epochs,
        lr=args.lr,
        weight_decay=args.weight_decay,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
        device=args.device,
        min_group_size=args.min_group_size,
        batch_groups=args.batch_groups,
        v2_4_checkpoint=args.v2_4_checkpoint,
        unseal_evaluate=args.unseal_evaluate,
        formal_labels_csv=args.formal_labels_csv,
    )


def main() -> None:
    train(config_from_args(parse_args()))


if __name__ == "__main__":
    main()
