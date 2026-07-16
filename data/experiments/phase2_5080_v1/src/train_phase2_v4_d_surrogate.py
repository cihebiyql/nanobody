#!/usr/bin/env python3
"""Train and freeze V4-D open-split sequence-to-docking surrogates.

Only OPEN_TRAIN labels are used for fitting. OPEN_DEVELOPMENT labels are used
for model and hyperparameter selection. The prospective test split is read
only from the label-free split manifest and is never accepted in the teacher.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "phase2_v4_d_open_surrogate_v1"
EXPECTED_SPLIT_MANIFEST_SHA256 = (
    "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
)
PRIMARY_TARGET = "R_dual_min"
TRAIN_SPLIT = "OPEN_TRAIN"
DEVELOPMENT_SPLIT = "OPEN_DEVELOPMENT"
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_SPLIT_COUNTS = {TRAIN_SPLIT: 226, DEVELOPMENT_SPLIT: 32, SEALED_SPLIT: 32}
EXPECTED_CLUSTER_COUNTS = {TRAIN_SPLIT: 20, DEVELOPMENT_SPLIT: 3, SEALED_SPLIT: 3}
DEFAULT_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)
DEFAULT_ENSEMBLE_SEEDS = (2026071601, 2026071602, 2026071603, 2026071604, 2026071605)
FROZEN_FEATURE_WIDTH = 160
AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"
AA_SET = frozenset(AA_ORDER)
REQUIRED_BASELINES = (
    "constant",
    "parent_only",
    "metadata_shortcut",
    "cdr3_only",
    "handcrafted_full_sequence",
    "generic_prior_only",
)
CANDIDATE_MODELS = ("frozen_feature_ridge",)
MODEL_NAMES = REQUIRED_BASELINES + CANDIDATE_MODELS
OUTPUT_FILENAMES = (
    "frozen_open_model_config.json",
    "frozen_open_model_artifact.json",
    "open_development_predictions.tsv",
    "open_development_summary.json",
    "frozen_open_artifact_sha256_receipt.json",
)
MINIMUM_OPEN_DELTA = 0.1
MINIMUM_ABSOLUTE_SPEARMAN = 0.2
MINIMUM_TOP_QUARTILE_RECALL = 0.25
MINIMUM_PARENT_MACRO_SPEARMAN = 0.2
MINIMUM_PARENT_MACRO_TOP_QUARTILE_RECALL = 0.25
MINIMUM_UNCERTAINTY_UNIQUE_FRACTION = 0.25
MAXIMUM_UNCERTAINTY_TIE_FRACTION = 0.25
CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence-to-independent-dual-docking computational geometry "
    "surrogate only; not binding, affinity, competition, experimental blocking, "
    "Docking Gold, or final submission authority."
)

MANIFEST_FEATURE_FIELDS = (
    "sequence_sha256",
    "sequence",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
)
MANIFEST_FIELDS = (
    "candidate_id",
    "model_split",
    "parent_framework_cluster",
) + MANIFEST_FEATURE_FIELDS
TEACHER_FIELDS = (
    "candidate_id",
    "model_split",
    "parent_framework_cluster",
    "sequence_sha256",
    "sequence",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
    "generic_binding_prior",
)
METADATA_FIELDS = ("design_method", "design_mode", "target_patch_id")


class SurrogateError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_strings(values: Iterable[str]) -> str:
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(validate_sequence(sequence).encode("ascii")).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise SurrogateError("refusing_to_write_empty_predictions")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def finite_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise SurrogateError(f"invalid_numeric_field:{field}") from exc
    if not math.isfinite(output):
        raise SurrogateError(f"non_finite_numeric_field:{field}")
    return output


def validate_sequence(value: str, field: str = "sequence") -> str:
    sequence = str(value).strip().upper()
    if not sequence or any(amino_acid not in AA_SET for amino_acid in sequence):
        raise SurrogateError(f"invalid_standard_amino_acid_sequence:{field}")
    return sequence


def require_fields(row: Mapping[str, Any], fields: Sequence[str], context: str) -> None:
    missing = [field for field in fields if field not in row or str(row[field]).strip() == ""]
    if missing:
        raise SurrogateError(f"missing_fields:{context}:{','.join(missing)}")


def validate_split_manifest(
    rows: list[dict[str, str]],
    expected_counts: Mapping[str, int] = EXPECTED_SPLIT_COUNTS,
    expected_cluster_counts: Mapping[str, int] = EXPECTED_CLUSTER_COUNTS,
) -> dict[str, dict[str, str]]:
    if len(rows) != sum(expected_counts.values()):
        raise SurrogateError(f"split_row_count_mismatch:{len(rows)}")
    by_id: dict[str, dict[str, str]] = {}
    split_clusters: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    for row in rows:
        require_fields(row, MANIFEST_FIELDS, "split_manifest")
        candidate_id = row["candidate_id"]
        if candidate_id in by_id:
            raise SurrogateError(f"duplicate_candidate_in_split:{candidate_id}")
        model_split = row["model_split"]
        if model_split not in expected_counts:
            raise SurrogateError(f"unknown_model_split:{model_split}")
        by_id[candidate_id] = row
        counts[model_split] += 1
        split_clusters[model_split].add(row["parent_framework_cluster"])
        sequence = validate_sequence(row["sequence"], "manifest_sequence")
        observed_sha256 = sequence_sha256(sequence)
        if str(row["sequence_sha256"]).lower() != observed_sha256:
            raise SurrogateError(f"manifest_sequence_sha256_mismatch:{candidate_id}")
        for field in ("cdr1", "cdr2", "cdr3"):
            validate_sequence(row[field], f"manifest_{field}")
    if dict(counts) != dict(expected_counts):
        raise SurrogateError(f"split_counts_mismatch:{dict(sorted(counts.items()))}")
    actual_cluster_counts = {name: len(split_clusters[name]) for name in expected_counts}
    if actual_cluster_counts != dict(expected_cluster_counts):
        raise SurrogateError(f"split_cluster_counts_mismatch:{actual_cluster_counts}")
    names = list(expected_counts)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            overlap = split_clusters[left] & split_clusters[right]
            if overlap:
                raise SurrogateError(
                    f"parent_cluster_split_leakage:{left}:{right}:{','.join(sorted(overlap))}"
                )
    return by_id


def validate_teacher_rows(
    rows: list[Mapping[str, Any]],
    split_by_id: Mapping[str, Mapping[str, str]],
    target: str = PRIMARY_TARGET,
    expected_counts: Mapping[str, int] = EXPECTED_SPLIT_COUNTS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the open teacher without ever touching a sealed target value."""
    open_ids = {
        candidate_id
        for candidate_id, row in split_by_id.items()
        if row["model_split"] in {TRAIN_SPLIT, DEVELOPMENT_SPLIT}
    }
    if len(rows) != expected_counts[TRAIN_SPLIT] + expected_counts[DEVELOPMENT_SPLIT]:
        raise SurrogateError(f"open_teacher_row_count_mismatch:{len(rows)}")

    by_id: dict[str, Mapping[str, Any]] = {}
    # Membership and split checks intentionally precede feature and target access.
    for row in rows:
        require_fields(row, ("candidate_id", "model_split"), "teacher_identity")
        candidate_id = str(row["candidate_id"])
        if candidate_id in by_id:
            raise SurrogateError(f"duplicate_candidate_in_teacher:{candidate_id}")
        if candidate_id not in open_ids:
            raise SurrogateError(f"teacher_contains_non_open_candidate:{candidate_id}")
        manifest_row = split_by_id[candidate_id]
        if row["model_split"] != manifest_row["model_split"]:
            raise SurrogateError(f"teacher_split_mismatch:{candidate_id}")
        if row["model_split"] not in {TRAIN_SPLIT, DEVELOPMENT_SPLIT}:
            raise SurrogateError(f"teacher_contains_sealed_split:{candidate_id}")
        by_id[candidate_id] = row
    if set(by_id) != open_ids:
        missing = sorted(open_ids - set(by_id))
        raise SurrogateError(f"teacher_missing_open_candidates:{','.join(missing[:5])}")

    normalized: list[dict[str, Any]] = []
    for candidate_id in sorted(by_id):
        source = by_id[candidate_id]
        require_fields(source, TEACHER_FIELDS + (target,), "teacher")
        manifest_row = split_by_id[candidate_id]
        if source["parent_framework_cluster"] != manifest_row["parent_framework_cluster"]:
            raise SurrogateError(f"teacher_parent_cluster_mismatch:{candidate_id}")
        row = {key: str(value) for key, value in source.items()}
        for field in ("sequence", "cdr1", "cdr2", "cdr3"):
            row[field] = validate_sequence(row[field], field)
            manifest_value = validate_sequence(
                str(manifest_row[field]), f"manifest_{field}"
            )
            if row[field] != manifest_value:
                raise SurrogateError(f"teacher_manifest_{field}_mismatch:{candidate_id}")
        observed_sha256 = sequence_sha256(row["sequence"])
        teacher_sha256 = str(source["sequence_sha256"]).strip().lower()
        manifest_sha256 = str(manifest_row["sequence_sha256"]).strip().lower()
        if teacher_sha256 != observed_sha256:
            raise SurrogateError(f"teacher_sequence_sha256_mismatch:{candidate_id}")
        if teacher_sha256 != manifest_sha256:
            raise SurrogateError(f"teacher_manifest_sequence_sha256_mismatch:{candidate_id}")
        row["sequence_sha256"] = teacher_sha256
        for field in METADATA_FIELDS:
            teacher_value = str(source[field]).strip()
            manifest_value = str(manifest_row[field]).strip()
            if teacher_value != manifest_value:
                raise SurrogateError(f"teacher_manifest_{field}_mismatch:{candidate_id}")
            row[field] = teacher_value
        row[target] = finite_float(source[target], target)
        row["generic_binding_prior"] = finite_float(
            source["generic_binding_prior"], "generic_binding_prior"
        )
        normalized.append(row)
    train_rows = [row for row in normalized if row["model_split"] == TRAIN_SPLIT]
    development_rows = [row for row in normalized if row["model_split"] == DEVELOPMENT_SPLIT]
    if len(train_rows) != expected_counts[TRAIN_SPLIT]:
        raise SurrogateError(f"train_row_count_mismatch:{len(train_rows)}")
    if len(development_rows) != expected_counts[DEVELOPMENT_SPLIT]:
        raise SurrogateError(f"development_row_count_mismatch:{len(development_rows)}")
    train_clusters = {row["parent_framework_cluster"] for row in train_rows}
    development_clusters = {row["parent_framework_cluster"] for row in development_rows}
    if train_clusters & development_clusters:
        raise SurrogateError("teacher_parent_cluster_leakage")
    return train_rows, development_rows


def validate_teacher_audit(
    teacher_path: Path,
    audit_path: Path,
    split_path: Path,
) -> dict[str, Any]:
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurrogateError(f"invalid_teacher_audit:{audit_path}") from exc
    if audit.get("status") != "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE":
        raise SurrogateError("teacher_audit_status_not_pass")
    if audit.get("release") != "open_train_and_open_development_only":
        raise SurrogateError("teacher_audit_release_not_open_only")
    if audit.get("output", {}).get("sha256") != sha256_file(teacher_path):
        raise SurrogateError("teacher_audit_output_hash_mismatch")
    if audit.get("inputs", {}).get("split_manifest_sha256") != sha256_file(split_path):
        raise SurrogateError("teacher_audit_split_hash_mismatch")
    boundary = audit.get("sealed_data_boundary", {})
    if boundary.get("raw_job_results_opened") != 0:
        raise SurrogateError("teacher_audit_reports_sealed_raw_results_opened")
    if boundary.get("sealed_metrics_used_for_teacher_or_ranking") is not False:
        raise SurrogateError("teacher_audit_reports_sealed_metrics_used")
    return audit


def composition(sequence: str) -> list[float]:
    counts = Counter(validate_sequence(sequence))
    return [counts.get(amino_acid, 0) / len(sequence) for amino_acid in AA_ORDER]


def physicochemical(sequence: str) -> list[float]:
    sequence = validate_sequence(sequence)
    residue_sets = (
        set("AILMFWVY"),
        set("FWY"),
        set("KRH"),
        set("DE"),
        set("STNQ"),
        set("GP"),
        set("C"),
    )
    fractions = [sum(amino_acid in group for amino_acid in sequence) / len(sequence) for group in residue_sets]
    charge = (
        sum(amino_acid in set("KR") for amino_acid in sequence)
        - sum(amino_acid in set("DE") for amino_acid in sequence)
    ) / len(sequence)
    return fractions + [charge]


def unsigned_hashed_kmers(sequence: str, k_values: Sequence[int], width: int) -> list[float]:
    output = np.zeros(width, dtype=np.float64)
    total = 0
    for k in k_values:
        for index in range(max(0, len(sequence) - k + 1)):
            token = f"K{k}:{sequence[index:index + k]}".encode("ascii")
            bucket = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % width
            output[bucket] += 1.0
            total += 1
    if total:
        output /= total
    return output.tolist()


def signed_hash_features(tokens: Iterable[str], width: int) -> list[float]:
    output = np.zeros(width, dtype=np.float64)
    count = 0
    for token in tokens:
        digest = hashlib.sha256(token.encode("ascii")).digest()
        bucket = int.from_bytes(digest[:8], "big") % width
        output[bucket] += 1.0 if digest[8] & 1 else -1.0
        count += 1
    if count:
        output /= math.sqrt(count)
    return output.tolist()


def frozen_sequence_projection(row: Mapping[str, Any], width: int) -> list[float]:
    """Fixed, position-aware sequence projection; no labels or fitted encoder state."""
    tokens: list[str] = []
    for field in ("sequence", "cdr1", "cdr2", "cdr3"):
        sequence = validate_sequence(str(row[field]), field)
        bins = 48 if field == "sequence" else 16
        for index, amino_acid in enumerate(sequence):
            position_bin = min(bins - 1, index * bins // len(sequence))
            tokens.append(f"{field}:P{position_bin}:{amino_acid}")
        for k in (2, 3):
            tokens.extend(
                f"{field}:K{k}:{sequence[index:index + k]}"
                for index in range(max(0, len(sequence) - k + 1))
            )
    return signed_hash_features(tokens, width)


@dataclass(frozen=True)
class FeatureSpec:
    model_name: str
    feature_names: tuple[str, ...]
    categories: dict[str, tuple[str, ...]]
    frozen_feature_width: int

    def to_json(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "feature_names": list(self.feature_names),
            "categories": {key: list(values) for key, values in sorted(self.categories.items())},
            "frozen_feature_width": self.frozen_feature_width,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "FeatureSpec":
        try:
            model_name = str(payload["model_name"])
            feature_names = tuple(str(value) for value in payload["feature_names"])
            categories = {
                str(key): tuple(str(value) for value in values)
                for key, values in dict(payload["categories"]).items()
            }
            frozen_feature_width = int(payload["frozen_feature_width"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SurrogateError("invalid_serialized_feature_spec") from exc
        if model_name not in MODEL_NAMES or frozen_feature_width < 1:
            raise SurrogateError("invalid_serialized_feature_spec")
        return cls(model_name, feature_names, categories, frozen_feature_width)


def build_feature_spec(
    model_name: str,
    train_rows: list[dict[str, Any]],
    frozen_feature_width: int = FROZEN_FEATURE_WIDTH,
) -> FeatureSpec:
    if model_name not in MODEL_NAMES:
        raise SurrogateError(f"unknown_model:{model_name}")
    categories: dict[str, tuple[str, ...]] = {}
    names: list[str] = []
    if model_name == "parent_only":
        categories["parent_framework_cluster"] = tuple(
            sorted({str(row["parent_framework_cluster"]) for row in train_rows})
        )
    elif model_name == "metadata_shortcut":
        for field in METADATA_FIELDS:
            categories[field] = tuple(sorted({str(row[field]) for row in train_rows}))
    if categories:
        for field in sorted(categories):
            names.extend(f"{field}={value}" for value in categories[field])
    elif model_name == "constant":
        names = []
    elif model_name == "generic_prior_only":
        names = ["generic_binding_prior"]
    elif model_name == "cdr3_only":
        names = (
            ["cdr3_length_scaled"]
            + [f"cdr3_composition_{amino_acid}" for amino_acid in AA_ORDER]
            + [f"cdr3_physchem_{index}" for index in range(8)]
            + [f"cdr3_kmer_hash_{index}" for index in range(64)]
        )
    elif model_name == "handcrafted_full_sequence":
        names = (
            ["sequence_length_scaled"]
            + [f"sequence_composition_{amino_acid}" for amino_acid in AA_ORDER]
            + [f"sequence_physchem_{index}" for index in range(8)]
        )
        for field in ("cdr1", "cdr2", "cdr3"):
            names.extend([f"{field}_length_scaled"])
            names.extend(f"{field}_composition_{amino_acid}" for amino_acid in AA_ORDER)
            names.extend(f"{field}_physchem_{index}" for index in range(8))
        names.extend(f"sequence_kmer_hash_{index}" for index in range(96))
    elif model_name == "frozen_feature_ridge":
        names = [f"frozen_signed_projection_{index}" for index in range(frozen_feature_width)]
    return FeatureSpec(model_name, tuple(names), categories, frozen_feature_width)


def encode_features(row: Mapping[str, Any], spec: FeatureSpec) -> list[float]:
    model_name = spec.model_name
    if model_name == "constant":
        return []
    if spec.categories:
        output: list[float] = []
        for field in sorted(spec.categories):
            output.extend(float(str(row[field]) == category) for category in spec.categories[field])
        return output
    if model_name == "generic_prior_only":
        return [finite_float(row["generic_binding_prior"], "generic_binding_prior")]
    if model_name == "cdr3_only":
        cdr3 = validate_sequence(str(row["cdr3"]), "cdr3")
        return (
            [len(cdr3) / 30.0]
            + composition(cdr3)
            + physicochemical(cdr3)
            + unsigned_hashed_kmers(cdr3, (2, 3), 64)
        )
    if model_name == "handcrafted_full_sequence":
        sequence = validate_sequence(str(row["sequence"]), "sequence")
        output = [len(sequence) / 150.0] + composition(sequence) + physicochemical(sequence)
        for field, scale in (("cdr1", 15.0), ("cdr2", 15.0), ("cdr3", 30.0)):
            region = validate_sequence(str(row[field]), field)
            output.extend([len(region) / scale] + composition(region) + physicochemical(region))
        output.extend(unsigned_hashed_kmers(sequence, (2, 3), 96))
        return output
    if model_name == "frozen_feature_ridge":
        return frozen_sequence_projection(row, spec.frozen_feature_width)
    raise SurrogateError(f"unknown_model:{model_name}")


def feature_matrix(rows: list[dict[str, Any]], spec: FeatureSpec) -> np.ndarray:
    matrix = np.asarray([encode_features(row, spec) for row in rows], dtype=np.float64)
    if matrix.shape != (len(rows), len(spec.feature_names)):
        raise SurrogateError(
            f"feature_shape_mismatch:{spec.model_name}:{matrix.shape}:{len(spec.feature_names)}"
        )
    if not np.all(np.isfinite(matrix)):
        raise SurrogateError(f"non_finite_features:{spec.model_name}")
    return matrix


@dataclass
class RidgeFit:
    intercept: float
    coefficient: np.ndarray
    center: np.ndarray
    scale: np.ndarray

    def to_json(self) -> dict[str, Any]:
        return {
            "intercept": float(self.intercept),
            "coefficient": [float(value) for value in self.coefficient],
            "center": [float(value) for value in self.center],
            "scale": [float(value) for value in self.scale],
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "RidgeFit":
        try:
            intercept = finite_float(payload["intercept"], "serialized_intercept")
            coefficient = np.asarray(payload["coefficient"], dtype=np.float64)
            center = np.asarray(payload["center"], dtype=np.float64)
            scale = np.asarray(payload["scale"], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as exc:
            raise SurrogateError("invalid_serialized_ridge_fit") from exc
        if coefficient.ndim != 1 or center.shape != coefficient.shape or scale.shape != coefficient.shape:
            raise SurrogateError("invalid_serialized_ridge_fit_shape")
        if not all(np.all(np.isfinite(values)) for values in (coefficient, center, scale)):
            raise SurrogateError("non_finite_serialized_ridge_fit")
        if np.any(scale <= 0.0):
            raise SurrogateError("non_positive_serialized_ridge_scale")
        return cls(intercept, coefficient, center, scale)


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> RidgeFit:
    if len(x) != len(y):
        raise SurrogateError("ridge_row_mismatch")
    if len(y) == 0:
        raise SurrogateError("ridge_empty_fit")
    if x.shape[1] == 0:
        return RidgeFit(float(np.mean(y)), np.zeros(0), np.zeros(0), np.ones(0))
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x - center) / scale
    intercept = float(np.mean(y))
    target = y - intercept
    gram = z.T @ z + float(alpha) * np.eye(z.shape[1], dtype=np.float64)
    coefficient = np.linalg.solve(gram, z.T @ target)
    return RidgeFit(intercept, coefficient, center, scale)


def predict_ridge(x: np.ndarray, fitted: RidgeFit) -> np.ndarray:
    if x.shape[1] == 0:
        return np.repeat(fitted.intercept, len(x))
    return fitted.intercept + ((x - fitted.center) / fitted.scale) @ fitted.coefficient


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    true_rank = rankdata(y_true)
    predicted_rank = rankdata(y_pred)
    if np.std(true_rank) < 1e-12 or np.std(predicted_rank) < 1e-12:
        return 0.0
    return float(np.corrcoef(true_rank, predicted_rank)[0, 1])


def ndcg(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    minimum = float(np.min(y_true))
    relevance = y_true - minimum if minimum < 0.0 else y_true.copy()

    def dcg(order: np.ndarray) -> float:
        return float(
            sum(
                (2.0 ** float(relevance[index]) - 1.0) / math.log2(rank + 2.0)
                for rank, index in enumerate(order)
            )
        )

    predicted_order = np.argsort(-y_pred, kind="mergesort")
    ideal_order = np.argsort(-y_true, kind="mergesort")
    denominator = dcg(ideal_order)
    return dcg(predicted_order) / denominator if denominator > 0.0 else 0.0


def top_quartile_recall(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    count = max(1, math.ceil(len(y_true) * 0.25))
    true_top = set(np.argsort(-y_true, kind="mergesort")[:count].tolist())
    predicted_top = set(np.argsort(-y_pred, kind="mergesort")[:count].tolist())
    return len(true_top & predicted_top) / len(true_top)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "spearman": round(spearman(y_true, y_pred), 9),
        "ndcg": round(ndcg(y_true, y_pred), 9),
        "top_quartile_recall_at_25pct_budget": round(top_quartile_recall(y_true, y_pred), 9),
        "mae": round(float(np.mean(np.abs(y_true - y_pred))), 9),
    }


def parent_macro_regression_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    parent_groups: Sequence[str],
) -> dict[str, Any]:
    if len(y_true) != len(y_pred) or len(y_true) != len(parent_groups):
        raise SurrogateError("parent_macro_row_count_mismatch")
    by_parent: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(parent_groups):
        by_parent[str(group)].append(index)
    if len(by_parent) < 2:
        raise SurrogateError("parent_macro_requires_at_least_two_parent_groups")
    per_parent = {
        parent: regression_metrics(y_true[indices], y_pred[indices])
        for parent, indices in sorted(by_parent.items())
    }
    fields = ("spearman", "ndcg", "top_quartile_recall_at_25pct_budget", "mae")
    macro = {
        field: round(
            float(np.mean([metrics[field] for metrics in per_parent.values()])), 9
        )
        for field in fields
    }
    return {
        "group_unit": "parent_framework_cluster",
        "parent_count": len(per_parent),
        "macro": macro,
        "per_parent": per_parent,
    }


def selection_key(metric: Mapping[str, float], alpha: float) -> tuple[float, float, float, float, float]:
    return (
        metric["spearman"],
        metric["ndcg"],
        metric["top_quartile_recall_at_25pct_budget"],
        -metric["mae"],
        -alpha,
    )


def group_bootstrap_indices(
    rows: list[dict[str, Any]], seed: int, group_field: str = "parent_framework_cluster"
) -> np.ndarray:
    by_group: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_group[str(row[group_field])].append(index)
    groups = sorted(by_group)
    if len(groups) < 2:
        raise SurrogateError("at_least_two_train_groups_required")
    rng = np.random.default_rng(seed)
    sampled = rng.choice(len(groups), size=len(groups), replace=True)
    return np.asarray(
        [index for group_index in sampled for index in by_group[groups[int(group_index)]]],
        dtype=np.int64,
    )


def uncertainty_diagnostics(uncertainty: np.ndarray) -> dict[str, Any]:
    values = np.asarray(uncertainty, dtype=np.float64)
    if values.ndim != 1 or len(values) < 4 or not np.all(np.isfinite(values)):
        raise SurrogateError("invalid_uncertainty_vector")
    if np.any(values < 0.0):
        raise SurrogateError("negative_uncertainty")
    sorted_values = np.sort(values)
    scale = max(1.0, float(np.max(np.abs(sorted_values))))
    tolerance = max(1e-12, scale * 1e-12)
    tie_counts: list[int] = []
    start = 0
    while start < len(sorted_values):
        end = start + 1
        while end < len(sorted_values) and abs(sorted_values[end] - sorted_values[start]) <= tolerance:
            end += 1
        tie_counts.append(end - start)
        start = end
    unique_count = len(tie_counts)
    unique_fraction = unique_count / len(values)
    maximum_tie_count = max(tie_counts)
    maximum_tie_fraction = maximum_tie_count / len(values)
    spread = float(sorted_values[-1] - sorted_values[0])
    spread_pass = spread > tolerance
    unique_pass = unique_fraction >= MINIMUM_UNCERTAINTY_UNIQUE_FRACTION
    tie_pass = maximum_tie_fraction <= MAXIMUM_UNCERTAINTY_TIE_FRACTION
    return {
        "row_count": len(values),
        "minimum": float(sorted_values[0]),
        "maximum": float(sorted_values[-1]),
        "spread": spread,
        "tie_tolerance": tolerance,
        "approximately_unique_count": unique_count,
        "approximately_unique_fraction": unique_fraction,
        "maximum_tie_count": maximum_tie_count,
        "maximum_tie_fraction": maximum_tie_fraction,
        "nonzero_spread_pass": spread_pass,
        "minimum_unique_fraction": MINIMUM_UNCERTAINTY_UNIQUE_FRACTION,
        "unique_fraction_pass": unique_pass,
        "maximum_allowed_tie_fraction": MAXIMUM_UNCERTAINTY_TIE_FRACTION,
        "maximum_tie_fraction_pass": tie_pass,
        "informative_pass": spread_pass and unique_pass and tie_pass,
    }


def risk_slice(
    y_true: np.ndarray, prediction: np.ndarray, uncertainty: np.ndarray
) -> dict[str, Any]:
    count = len(y_true)
    if len(prediction) != count or len(uncertainty) != count or count < 4:
        raise SurrogateError("selective_risk_row_count_mismatch")
    retained_count = max(1, math.floor(count * 0.75))
    quartile_count = max(1, math.ceil(count * 0.25))
    order = np.argsort(uncertainty, kind="mergesort")
    absolute_error = np.abs(y_true - prediction)
    overall_mae = float(np.mean(absolute_error))
    retained_mae = float(np.mean(absolute_error[order[:retained_count]]))
    low_mae = float(np.mean(absolute_error[order[:quartile_count]]))
    high_mae = float(np.mean(absolute_error[order[-quartile_count:]]))
    reduction = (overall_mae - retained_mae) / overall_mae if overall_mae > 1e-12 else 0.0
    ratio = high_mae / low_mae if low_mae > 1e-12 else None
    return {
        "row_count": count,
        "overall_mae": overall_mae,
        "mae_after_removing_highest_uncertainty_25pct": retained_mae,
        "relative_mae_reduction": reduction,
        "lowest_uncertainty_quartile_mae": low_mae,
        "highest_uncertainty_quartile_mae": high_mae,
        "highest_to_lowest_quartile_mae_ratio": ratio,
    }


def rounded_risk_slice(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (
            None
            if value is None
            else round(float(value), 9)
            if isinstance(value, (float, np.floating))
            else value
        )
        for key, value in payload.items()
    }


def selective_risk(
    y_true: np.ndarray,
    prediction: np.ndarray,
    uncertainty: np.ndarray,
    parent_groups: Sequence[str],
) -> dict[str, Any]:
    if len(y_true) != len(parent_groups):
        raise SurrogateError("selective_risk_parent_group_count_mismatch")
    global_diagnostics = uncertainty_diagnostics(uncertainty)
    global_metrics = risk_slice(y_true, prediction, uncertainty)
    by_parent: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(parent_groups):
        by_parent[str(group)].append(index)
    if len(by_parent) < 2:
        raise SurrogateError("selective_risk_requires_at_least_two_parent_groups")

    per_parent: dict[str, Any] = {}
    raw_parent_risks: dict[str, dict[str, Any]] = {}
    for parent, indices in sorted(by_parent.items()):
        if len(indices) < 4:
            raise SurrogateError(f"selective_risk_parent_has_fewer_than_four_rows:{parent}")
        index_array = np.asarray(indices, dtype=np.int64)
        raw_risk = risk_slice(
            y_true[index_array], prediction[index_array], uncertainty[index_array]
        )
        raw_parent_risks[parent] = raw_risk
        per_parent[parent] = {
            "uncertainty_diagnostics": uncertainty_diagnostics(uncertainty[index_array]),
            "risk": rounded_risk_slice(raw_risk),
        }

    macro_overall = float(
        np.mean([value["overall_mae"] for value in raw_parent_risks.values()])
    )
    macro_retained = float(
        np.mean(
            [
                value["mae_after_removing_highest_uncertainty_25pct"]
                for value in raw_parent_risks.values()
            ]
        )
    )
    macro_low = float(
        np.mean(
            [value["lowest_uncertainty_quartile_mae"] for value in raw_parent_risks.values()]
        )
    )
    macro_high = float(
        np.mean(
            [value["highest_uncertainty_quartile_mae"] for value in raw_parent_risks.values()]
        )
    )
    macro_reduction = (
        (macro_overall - macro_retained) / macro_overall
        if macro_overall > 1e-12
        else 0.0
    )
    macro_ratio = macro_high / macro_low if macro_low > 1e-12 else None
    macro_reduction_pass = macro_reduction >= 0.10
    macro_ratio_pass = macro_ratio is not None and macro_ratio >= 1.25
    all_parent_uncertainties_informative = all(
        value["uncertainty_diagnostics"]["informative_pass"]
        for value in per_parent.values()
    )
    uncertainty_informative = (
        global_diagnostics["informative_pass"] and all_parent_uncertainties_informative
    )
    parent_macro = rounded_risk_slice(
        {
            "parent_count": len(per_parent),
            "overall_mae": macro_overall,
            "mae_after_removing_highest_uncertainty_25pct": macro_retained,
            "relative_mae_reduction": macro_reduction,
            "lowest_uncertainty_quartile_mae": macro_low,
            "highest_uncertainty_quartile_mae": macro_high,
            "highest_to_lowest_quartile_mae_ratio": macro_ratio,
        }
    )
    return {
        **rounded_risk_slice(global_metrics),
        "uncertainty_diagnostics": global_diagnostics,
        "all_parent_uncertainties_informative": all_parent_uncertainties_informative,
        "parent_macro": parent_macro,
        "per_parent": per_parent,
        "parent_macro_relative_mae_reduction_at_least_10pct": macro_reduction_pass,
        "parent_macro_highest_to_lowest_quartile_ratio_at_least_1_25": macro_ratio_pass,
        "gate_pass": uncertainty_informative and macro_reduction_pass and macro_ratio_pass,
    }


def metric_distribution(
    y_true: np.ndarray, seed_predictions: np.ndarray
) -> dict[str, Any]:
    rows = [regression_metrics(y_true, prediction) for prediction in seed_predictions]
    output: dict[str, Any] = {
        "per_seed": rows,
        "seed_count": len(rows),
        "is_confidence_interval": False,
        "interpretation": (
            "Descriptive range across fixed group-bootstrap ensemble members; "
            "the 2.5/97.5 percentiles are not a confidence interval."
        ),
    }
    for field in ("spearman", "ndcg", "top_quartile_recall_at_25pct_budget", "mae"):
        values = np.asarray([row[field] for row in rows], dtype=np.float64)
        output[field] = {
            "mean": round(float(np.mean(values)), 9),
            "standard_deviation": round(float(np.std(values)), 9),
            "percentile_2_5": round(float(np.quantile(values, 0.025)), 9),
            "percentile_97_5": round(float(np.quantile(values, 0.975)), 9),
        }
    return output


def train_one_model(
    model_name: str,
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    target: str,
    alphas: Sequence[float],
    ensemble_seeds: Sequence[int],
    frozen_feature_width: int,
) -> dict[str, Any]:
    spec = build_feature_spec(model_name, train_rows, frozen_feature_width)
    x_train = feature_matrix(train_rows, spec)
    x_development = feature_matrix(development_rows, spec)
    y_train = np.asarray([finite_float(row[target], target) for row in train_rows])
    y_development = np.asarray([finite_float(row[target], target) for row in development_rows])
    development_parent_groups = [
        str(row["parent_framework_cluster"]) for row in development_rows
    ]

    alpha_grid = (0.0,) if model_name == "constant" else tuple(float(value) for value in alphas)
    candidates: list[tuple[tuple[float, ...], float, RidgeFit, np.ndarray, dict[str, float]]] = []
    for alpha in alpha_grid:
        fitted = fit_ridge(x_train, y_train, alpha)
        prediction = predict_ridge(x_development, fitted)
        metric = regression_metrics(y_development, prediction)
        candidates.append((selection_key(metric, alpha), alpha, fitted, prediction, metric))
    _key, selected_alpha, direct_fit, direct_prediction, direct_metric = max(
        candidates, key=lambda item: item[0]
    )

    seed_predictions: list[np.ndarray] = []
    seed_fits: list[dict[str, Any]] = []
    for seed in ensemble_seeds:
        indices = group_bootstrap_indices(train_rows, int(seed))
        fitted = fit_ridge(x_train[indices], y_train[indices], selected_alpha)
        seed_predictions.append(predict_ridge(x_development, fitted))
        seed_fits.append(
            {
                "seed": int(seed),
                "sampled_train_row_count": int(len(indices)),
                "sampled_train_candidate_ids_sha256": sha256_strings(
                    str(train_rows[index]["candidate_id"]) for index in indices
                ),
                "fit": fitted.to_json(),
            }
        )
    prediction_matrix = np.asarray(seed_predictions, dtype=np.float64)
    ensemble_mean = prediction_matrix.mean(axis=0)
    ensemble_uncertainty = prediction_matrix.std(axis=0)
    ensemble_metric = regression_metrics(y_development, ensemble_mean)
    parent_macro_metric = parent_macro_regression_metrics(
        y_development, ensemble_mean, development_parent_groups
    )
    risk = selective_risk(
        y_development,
        ensemble_mean,
        ensemble_uncertainty,
        development_parent_groups,
    )
    return {
        "model_name": model_name,
        "feature_spec": spec,
        "selected_alpha": selected_alpha,
        "direct_fit": direct_fit,
        "direct_prediction": direct_prediction,
        "direct_metrics": direct_metric,
        "ensemble_prediction": ensemble_mean,
        "ensemble_uncertainty": ensemble_uncertainty,
        "ensemble_metrics": ensemble_metric,
        "parent_macro_ensemble_metrics": parent_macro_metric,
        "ensemble_metric_distribution": metric_distribution(y_development, prediction_matrix),
        "selective_risk": risk,
        "seed_fits": seed_fits,
        "alpha_development_metrics": {
            str(alpha): metric for _candidate_key, alpha, _fit, _prediction, metric in candidates
        },
    }


def evaluate_open_performance_gates(
    candidate_result: Mapping[str, Any],
    strongest_shortcut_result: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_metrics = candidate_result["ensemble_metrics"]
    shortcut_metrics = strongest_shortcut_result["ensemble_metrics"]
    parent_macro = candidate_result["parent_macro_ensemble_metrics"]["macro"]
    delta = candidate_metrics["spearman"] - shortcut_metrics["spearman"]
    gates = {
        "relative_spearman_delta": {
            "observed": round(delta, 9),
            "minimum": MINIMUM_OPEN_DELTA,
            "passed": delta >= MINIMUM_OPEN_DELTA,
        },
        "absolute_spearman": {
            "observed": candidate_metrics["spearman"],
            "minimum": MINIMUM_ABSOLUTE_SPEARMAN,
            "passed": candidate_metrics["spearman"] >= MINIMUM_ABSOLUTE_SPEARMAN,
        },
        "absolute_top_quartile_recall_at_25pct_budget": {
            "observed": candidate_metrics["top_quartile_recall_at_25pct_budget"],
            "minimum": MINIMUM_TOP_QUARTILE_RECALL,
            "passed": candidate_metrics["top_quartile_recall_at_25pct_budget"]
            >= MINIMUM_TOP_QUARTILE_RECALL,
        },
        "parent_macro_spearman": {
            "observed": parent_macro["spearman"],
            "minimum": MINIMUM_PARENT_MACRO_SPEARMAN,
            "passed": parent_macro["spearman"] >= MINIMUM_PARENT_MACRO_SPEARMAN,
        },
        "parent_macro_top_quartile_recall_at_25pct_budget": {
            "observed": parent_macro["top_quartile_recall_at_25pct_budget"],
            "minimum": MINIMUM_PARENT_MACRO_TOP_QUARTILE_RECALL,
            "passed": parent_macro["top_quartile_recall_at_25pct_budget"]
            >= MINIMUM_PARENT_MACRO_TOP_QUARTILE_RECALL,
        },
    }
    return {"all_passed": all(gate["passed"] for gate in gates.values()), "gates": gates}


def train_surrogates(
    train_rows: list[dict[str, Any]],
    development_rows: list[dict[str, Any]],
    target: str = PRIMARY_TARGET,
    alphas: Sequence[float] = DEFAULT_ALPHAS,
    ensemble_seeds: Sequence[int] = DEFAULT_ENSEMBLE_SEEDS,
    frozen_feature_width: int = FROZEN_FEATURE_WIDTH,
) -> dict[str, Any]:
    if len(set(ensemble_seeds)) < 3:
        raise SurrogateError("at_least_three_unique_ensemble_seeds_required")
    if not alphas or any(value <= 0.0 for value in alphas):
        raise SurrogateError("ridge_alphas_must_be_positive")
    if frozen_feature_width < 1:
        raise SurrogateError("frozen_feature_width_must_be_positive")
    models = {
        model_name: train_one_model(
            model_name,
            train_rows,
            development_rows,
            target,
            alphas,
            ensemble_seeds,
            frozen_feature_width,
        )
        for model_name in MODEL_NAMES
    }
    strongest_shortcut = max(
        REQUIRED_BASELINES,
        key=lambda name: (
            models[name]["ensemble_metrics"]["spearman"],
            models[name]["ensemble_metrics"]["ndcg"],
            models[name]["ensemble_metrics"]["top_quartile_recall_at_25pct_budget"],
            -models[name]["ensemble_metrics"]["mae"],
            name,
        ),
    )
    selected_candidate = max(
        CANDIDATE_MODELS,
        key=lambda name: (
            models[name]["ensemble_metrics"]["spearman"],
            models[name]["ensemble_metrics"]["ndcg"],
            -models[name]["ensemble_metrics"]["mae"],
            name,
        ),
    )
    performance_gates = evaluate_open_performance_gates(
        models[selected_candidate], models[strongest_shortcut]
    )
    return {
        "models": models,
        "strongest_shortcut": strongest_shortcut,
        "selected_candidate": selected_candidate,
        "open_spearman_delta_over_strongest_shortcut": performance_gates["gates"][
            "relative_spearman_delta"
        ]["observed"],
        "open_delta_gate_pass": performance_gates["gates"]["relative_spearman_delta"][
            "passed"
        ],
        "open_performance_gates": performance_gates,
        "absolute_performance_gate_pass": all(
            performance_gates["gates"][name]["passed"]
            for name in (
                "absolute_spearman",
                "absolute_top_quartile_recall_at_25pct_budget",
            )
        ),
        "parent_macro_gate_pass": all(
            performance_gates["gates"][name]["passed"]
            for name in (
                "parent_macro_spearman",
                "parent_macro_top_quartile_recall_at_25pct_budget",
            )
        ),
        "uncertainty_gate_pass": models[selected_candidate]["selective_risk"]["gate_pass"],
    }


def json_model_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected_alpha": result["selected_alpha"],
        "feature_spec": result["feature_spec"].to_json(),
        "direct_fit": result["direct_fit"].to_json(),
        "bootstrap_ensemble_fits": result["seed_fits"],
        "fit_split": TRAIN_SPLIT,
        "fit_labels": PRIMARY_TARGET,
        "development_rows_used_as_fit_rows": 0,
        "prospective_test_rows_used_as_fit_rows": 0,
    }


def load_model_artifact(
    path: Path, *, expected_config_sha256: str | None = None
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurrogateError(f"invalid_model_artifact:{path}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SurrogateError("model_artifact_schema_version_mismatch")
    if payload.get("status") != "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED":
        raise SurrogateError("model_artifact_status_mismatch")
    if expected_config_sha256 is not None and payload.get("config_sha256") != expected_config_sha256:
        raise SurrogateError("model_artifact_config_hash_mismatch")
    if set(payload.get("models", {})) != set(MODEL_NAMES):
        raise SurrogateError("model_artifact_model_set_mismatch")
    return payload


def predict_serialized_model(
    artifact: Mapping[str, Any],
    model_name: str,
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    try:
        model = artifact["models"][model_name]
        spec = FeatureSpec.from_json(model["feature_spec"])
        serialized_fits = model["bootstrap_ensemble_fits"]
    except (KeyError, TypeError) as exc:
        raise SurrogateError(f"invalid_serialized_model:{model_name}") from exc
    if spec.model_name != model_name:
        raise SurrogateError(f"serialized_model_feature_spec_mismatch:{model_name}")
    if not isinstance(serialized_fits, list) or len(serialized_fits) < 3:
        raise SurrogateError(f"serialized_model_ensemble_too_small:{model_name}")
    x = feature_matrix(rows, spec)
    predictions: list[np.ndarray] = []
    seeds: set[int] = set()
    for serialized in serialized_fits:
        try:
            seed = int(serialized["seed"])
            fitted = RidgeFit.from_json(serialized["fit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SurrogateError(f"invalid_serialized_ensemble_fit:{model_name}") from exc
        if seed in seeds:
            raise SurrogateError(f"duplicate_serialized_ensemble_seed:{model_name}:{seed}")
        seeds.add(seed)
        if len(fitted.coefficient) != x.shape[1]:
            raise SurrogateError(f"serialized_feature_fit_width_mismatch:{model_name}")
        predictions.append(predict_ridge(x, fitted))
    matrix = np.asarray(predictions, dtype=np.float64)
    return matrix.mean(axis=0), matrix.std(axis=0)


def verify_artifact_prediction_roundtrip(
    artifact_path: Path,
    config_path: Path,
    rows: list[dict[str, Any]],
    trained: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = load_model_artifact(
        artifact_path, expected_config_sha256=sha256_file(config_path)
    )
    per_model: dict[str, Any] = {}
    for model_name in MODEL_NAMES:
        prediction, uncertainty = predict_serialized_model(artifact, model_name, rows)
        expected_prediction = np.asarray(
            trained["models"][model_name]["ensemble_prediction"], dtype=np.float64
        )
        expected_uncertainty = np.asarray(
            trained["models"][model_name]["ensemble_uncertainty"], dtype=np.float64
        )
        prediction_error = float(np.max(np.abs(prediction - expected_prediction)))
        uncertainty_error = float(np.max(np.abs(uncertainty - expected_uncertainty)))
        rounded_prediction_match = np.array_equal(
            np.round(prediction, 9), np.round(expected_prediction, 9)
        )
        rounded_uncertainty_match = np.array_equal(
            np.round(uncertainty, 9), np.round(expected_uncertainty, 9)
        )
        if (
            prediction_error > 1e-12
            or uncertainty_error > 1e-12
            or not rounded_prediction_match
            or not rounded_uncertainty_match
        ):
            raise SurrogateError(f"model_artifact_prediction_roundtrip_mismatch:{model_name}")
        per_model[model_name] = {
            "row_count": len(rows),
            "maximum_absolute_prediction_error": prediction_error,
            "maximum_absolute_uncertainty_error": uncertainty_error,
            "rounded_9_decimal_prediction_match": rounded_prediction_match,
            "rounded_9_decimal_uncertainty_match": rounded_uncertainty_match,
        }
    return {
        "status": "PASS_SERIALIZED_ARTIFACT_PREDICTION_ROUNDTRIP",
        "model_count": len(MODEL_NAMES),
        "per_model": per_model,
    }


def summary_model_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected_alpha": result["selected_alpha"],
        "feature_count": len(result["feature_spec"].feature_names),
        "direct_development_metrics": result["direct_metrics"],
        "ensemble_development_metrics": result["ensemble_metrics"],
        "parent_macro_ensemble_development_metrics": result[
            "parent_macro_ensemble_metrics"
        ],
        "bootstrap_seed_metric_distribution": result["ensemble_metric_distribution"],
        "selective_risk": result["selective_risk"],
        "alpha_development_metrics": result["alpha_development_metrics"],
    }


def parse_numbers(value: str, cast: type) -> tuple[Any, ...]:
    try:
        output = tuple(cast(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid_comma_separated_numbers:{value}") from exc
    if not output:
        raise argparse.ArgumentTypeError("empty_comma_separated_numbers")
    return output


def validate_existing_output_directory(out_dir: Path) -> None:
    if out_dir.exists() and not out_dir.is_dir():
        raise SurrogateError(f"output_path_is_not_directory:{out_dir}")
    if not out_dir.exists():
        return
    allowed = set(OUTPUT_FILENAMES)
    unexpected = sorted(path.name for path in out_dir.iterdir() if path.name not in allowed)
    if unexpected:
        raise SurrogateError(
            "unexpected_existing_output_files:" + ",".join(unexpected)
        )


@contextmanager
def output_publication_lock(out_dir: Path) -> Iterable[None]:
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir.parent / f".{out_dir.name}.publication.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SurrogateError(f"output_publication_lock_exists:{lock_path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def publish_staged_outputs(
    staging_dir: Path,
    out_dir: Path,
    *,
    expected_stale_receipt: bool | None = None,
) -> dict[str, Any]:
    validate_existing_output_directory(out_dir)
    for name in OUTPUT_FILENAMES:
        if not (staging_dir / name).is_file():
            raise SurrogateError(f"staged_output_missing:{name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_name = OUTPUT_FILENAMES[-1]
    try:
        staged_receipt = json.loads((staging_dir / receipt_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurrogateError("invalid_staged_receipt") from exc
    expected_output_hashes = staged_receipt.get("outputs", {})
    expected_final_paths = {
        str((out_dir / name).resolve()) for name in OUTPUT_FILENAMES[:-1]
    }
    if set(expected_output_hashes) != expected_final_paths:
        raise SurrogateError("staged_receipt_output_set_mismatch")
    final_receipt = out_dir / receipt_name
    stale_receipt_removed = final_receipt.exists()
    if (
        expected_stale_receipt is not None
        and stale_receipt_removed != expected_stale_receipt
    ):
        raise SurrogateError("publication_stale_receipt_state_changed")
    # Removing the old receipt first makes every interrupted replacement fail closed.
    final_receipt.unlink(missing_ok=True)
    for name in OUTPUT_FILENAMES[:-1]:
        os.replace(staging_dir / name, out_dir / name)
        final_path = (out_dir / name).resolve()
        if sha256_file(final_path) != expected_output_hashes[str(final_path)]:
            raise SurrogateError(f"published_output_hash_mismatch:{name}")
    os.replace(staging_dir / receipt_name, final_receipt)
    directory_descriptor = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return {
        "policy": "stage_all_outputs_then_atomic_file_replace_with_receipt_last",
        "stale_receipt_removed_before_replacement": stale_receipt_removed,
        "receipt_published_last": True,
    }


def run_pipeline(
    teacher_path: Path,
    teacher_audit_path: Path,
    split_manifest_path: Path,
    out_dir: Path,
    *,
    target: str = PRIMARY_TARGET,
    alphas: Sequence[float] = DEFAULT_ALPHAS,
    ensemble_seeds: Sequence[int] = DEFAULT_ENSEMBLE_SEEDS,
    frozen_feature_width: int = FROZEN_FEATURE_WIDTH,
    enforce_production_split_hash: bool = True,
) -> dict[str, Any]:
    if target != PRIMARY_TARGET:
        raise SurrogateError(f"primary_target_must_remain_{PRIMARY_TARGET}")
    if enforce_production_split_hash and sha256_file(split_manifest_path) != EXPECTED_SPLIT_MANIFEST_SHA256:
        raise SurrogateError("split_manifest_sha256_mismatch")
    audit = validate_teacher_audit(teacher_path, teacher_audit_path, split_manifest_path)
    split_rows = read_tsv(split_manifest_path)
    split_by_id = validate_split_manifest(split_rows)
    teacher_rows = read_tsv(teacher_path)
    train_rows, development_rows = validate_teacher_rows(teacher_rows, split_by_id, target)
    trained = train_surrogates(
        train_rows,
        development_rows,
        target,
        alphas,
        ensemble_seeds,
        frozen_feature_width,
    )

    out_dir = out_dir.resolve()
    final_paths = {name: out_dir / name for name in OUTPUT_FILENAMES}
    train_ids_hash = sha256_strings(str(row["candidate_id"]) for row in train_rows)
    development_ids_hash = sha256_strings(str(row["candidate_id"]) for row in development_rows)
    test_manifest_ids = sorted(
        row["candidate_id"] for row in split_rows if row["model_split"] == SEALED_SPLIT
    )

    with output_publication_lock(out_dir):
        validate_existing_output_directory(out_dir)
        preexisting_receipt = final_paths[OUTPUT_FILENAMES[-1]].exists()
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".{out_dir.name}.stage.", dir=out_dir.parent)
        )
        try:
            config_path = staging_dir / OUTPUT_FILENAMES[0]
            model_path = staging_dir / OUTPUT_FILENAMES[1]
            predictions_path = staging_dir / OUTPUT_FILENAMES[2]
            summary_path = staging_dir / OUTPUT_FILENAMES[3]
            receipt_path = staging_dir / OUTPUT_FILENAMES[4]

            config = {
                "schema_version": SCHEMA_VERSION,
                "status": "FROZEN_OPEN_CONFIGURATION_BEFORE_PROSPECTIVE_TEST_UNSEAL",
                "primary_target": target,
                "fit_split": TRAIN_SPLIT,
                "selection_split": DEVELOPMENT_SPLIT,
                "group_unit": "parent_framework_cluster",
                "fit_rows": len(train_rows),
                "selection_rows": len(development_rows),
                "prospective_test_rows": len(test_manifest_ids),
                "prospective_test_labels_read": False,
                "prospective_test_label_files_opened": 0,
                "required_baselines": list(REQUIRED_BASELINES),
                "candidate_models": list(CANDIDATE_MODELS),
                "alphas": list(alphas),
                "group_bootstrap_ensemble_seeds": list(ensemble_seeds),
                "ensemble_range_interpretation": (
                    "Descriptive fixed-seed range, not a confidence interval."
                ),
                "frozen_feature_definition": {
                    "id": "deterministic_position_aware_signed_sequence_projection_v1",
                    "width": frozen_feature_width,
                    "label_fitted": False,
                    "language_model_claim": False,
                },
                "teacher_manifest_feature_closure_fields": list(MANIFEST_FEATURE_FIELDS),
                "open_performance_gate_thresholds": {
                    "minimum_spearman_delta_over_strongest_shortcut": MINIMUM_OPEN_DELTA,
                    "minimum_absolute_spearman": MINIMUM_ABSOLUTE_SPEARMAN,
                    "minimum_top_quartile_recall_at_25pct_budget": MINIMUM_TOP_QUARTILE_RECALL,
                    "minimum_parent_macro_spearman": MINIMUM_PARENT_MACRO_SPEARMAN,
                    "minimum_parent_macro_top_quartile_recall_at_25pct_budget": MINIMUM_PARENT_MACRO_TOP_QUARTILE_RECALL,
                },
                "uncertainty_gate_thresholds": {
                    "minimum_approximately_unique_fraction": MINIMUM_UNCERTAINTY_UNIQUE_FRACTION,
                    "maximum_approximately_tied_fraction": MAXIMUM_UNCERTAINTY_TIE_FRACTION,
                    "minimum_parent_macro_relative_mae_reduction": 0.10,
                    "minimum_parent_macro_highest_to_lowest_error_ratio": 1.25,
                    "parent_aware": True,
                },
                "train_candidate_ids_sha256": train_ids_hash,
                "development_candidate_ids_sha256": development_ids_hash,
                "prospective_test_manifest_candidate_ids_sha256": sha256_strings(
                    test_manifest_ids
                ),
                "inputs": {
                    "teacher_sha256": sha256_file(teacher_path),
                    "teacher_audit_sha256": sha256_file(teacher_audit_path),
                    "split_manifest_sha256": sha256_file(split_manifest_path),
                },
                "publication_policy": (
                    "stage_all_outputs_then_atomic_file_replace_with_receipt_last"
                ),
                "runtime_provenance": {
                    "python_version": sys.version,
                    "numpy_version": np.__version__,
                    "platform": platform.platform(),
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(config_path, config)

            model_artifact = {
                "schema_version": SCHEMA_VERSION,
                "status": "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
                "config_sha256": sha256_file(config_path),
                "selected_candidate_model": trained["selected_candidate"],
                "strongest_shortcut_baseline": trained["strongest_shortcut"],
                "models": {
                    name: json_model_result(trained["models"][name]) for name in MODEL_NAMES
                },
                "fit_row_count": len(train_rows),
                "development_row_count_used_for_selection_only": len(development_rows),
                "prospective_test_labels_read": False,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(model_path, model_artifact)
            roundtrip = verify_artifact_prediction_roundtrip(
                model_path, config_path, development_rows, trained
            )
            reloaded_artifact = load_model_artifact(
                model_path, expected_config_sha256=sha256_file(config_path)
            )
            serialized_predictions = {
                name: predict_serialized_model(reloaded_artifact, name, development_rows)
                for name in MODEL_NAMES
            }

            prediction_rows: list[dict[str, Any]] = []
            y_development = np.asarray(
                [row[target] for row in development_rows], dtype=np.float64
            )
            for index, row in enumerate(development_rows):
                output: dict[str, Any] = {
                    "candidate_id": row["candidate_id"],
                    "model_split": row["model_split"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                    "target_R_dual_min": round(float(y_development[index]), 9),
                }
                for name in MODEL_NAMES:
                    prediction, uncertainty = serialized_predictions[name]
                    output[f"prediction_{name}"] = round(float(prediction[index]), 9)
                    output[f"uncertainty_{name}"] = round(float(uncertainty[index]), 9)
                selected = trained["selected_candidate"]
                output["selected_model"] = selected
                output["selected_prediction"] = output[f"prediction_{selected}"]
                output["selected_uncertainty"] = output[f"uncertainty_{selected}"]
                prediction_rows.append(output)
            write_tsv(predictions_path, prediction_rows)

            open_gates_pass = (
                trained["open_performance_gates"]["all_passed"]
                and trained["uncertainty_gate_pass"]
            )
            summary = {
                "schema_version": SCHEMA_VERSION,
                "status": (
                    "PASS_OPEN_DEVELOPMENT_GATES_PROSPECTIVE_TEST_STILL_SEALED"
                    if open_gates_pass
                    else "FAIL_OPEN_DEVELOPMENT_GATES_PROSPECTIVE_TEST_STILL_SEALED"
                ),
                "teacher_release_status": audit["status"],
                "primary_target": target,
                "fit": {
                    "split": TRAIN_SPLIT,
                    "rows": len(train_rows),
                    "parent_clusters": len(
                        {row["parent_framework_cluster"] for row in train_rows}
                    ),
                },
                "selection": {
                    "split": DEVELOPMENT_SPLIT,
                    "rows": len(development_rows),
                    "parent_clusters": len(
                        {row["parent_framework_cluster"] for row in development_rows}
                    ),
                },
                "prospective_test": {
                    "split": SEALED_SPLIT,
                    "manifest_rows": len(test_manifest_ids),
                    "labels_read": False,
                    "label_files_opened": 0,
                    "used_for_training_or_selection": False,
                },
                "models": {
                    name: summary_model_result(trained["models"][name])
                    for name in MODEL_NAMES
                },
                "strongest_shortcut_baseline": trained["strongest_shortcut"],
                "selected_candidate_model": trained["selected_candidate"],
                "open_performance_gates": trained["open_performance_gates"],
                "open_spearman_delta_over_strongest_shortcut": trained[
                    "open_spearman_delta_over_strongest_shortcut"
                ],
                "open_delta_gate_pass": trained["open_delta_gate_pass"],
                "absolute_performance_gate_pass": trained[
                    "absolute_performance_gate_pass"
                ],
                "parent_macro_gate_pass": trained["parent_macro_gate_pass"],
                "uncertainty_gate_pass": trained["uncertainty_gate_pass"],
                "serialized_artifact_prediction_roundtrip": roundtrip,
                "deployment_eligible": False,
                "artifacts": {
                    "config": {
                        "path": str(final_paths[OUTPUT_FILENAMES[0]]),
                        "sha256": sha256_file(config_path),
                    },
                    "model": {
                        "path": str(final_paths[OUTPUT_FILENAMES[1]]),
                        "sha256": sha256_file(model_path),
                    },
                    "predictions": {
                        "path": str(final_paths[OUTPUT_FILENAMES[2]]),
                        "sha256": sha256_file(predictions_path),
                    },
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(summary_path, summary)

            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE",
                "prospective_test_labels_read": False,
                "serialized_artifact_prediction_roundtrip_status": roundtrip["status"],
                "publication": {
                    "policy": "stage_all_outputs_then_atomic_file_replace_with_receipt_last",
                    "stale_receipt_removed_before_replacement": preexisting_receipt,
                    "receipt_published_last": True,
                },
                "inputs": {
                    str(teacher_path.resolve()): sha256_file(teacher_path),
                    str(teacher_audit_path.resolve()): sha256_file(teacher_audit_path),
                    str(split_manifest_path.resolve()): sha256_file(split_manifest_path),
                    str(Path(__file__).resolve()): sha256_file(Path(__file__)),
                },
                "outputs": {
                    str(final_paths[OUTPUT_FILENAMES[0]]): sha256_file(config_path),
                    str(final_paths[OUTPUT_FILENAMES[1]]): sha256_file(model_path),
                    str(final_paths[OUTPUT_FILENAMES[2]]): sha256_file(predictions_path),
                    str(final_paths[OUTPUT_FILENAMES[3]]): sha256_file(summary_path),
                },
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(receipt_path, receipt)
            publication = publish_staged_outputs(
                staging_dir,
                out_dir,
                expected_stale_receipt=preexisting_receipt,
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    return {
        "status": summary["status"],
        "summary": str(final_paths[OUTPUT_FILENAMES[3]]),
        "receipt": str(final_paths[OUTPUT_FILENAMES[4]]),
        "selected_candidate_model": trained["selected_candidate"],
        "strongest_shortcut_baseline": trained["strongest_shortcut"],
        "prospective_test_labels_read": False,
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-audit", type=Path)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--target", default=PRIMARY_TARGET)
    parser.add_argument("--alphas", default=",".join(str(value) for value in DEFAULT_ALPHAS))
    parser.add_argument(
        "--ensemble-seeds", default=",".join(str(value) for value in DEFAULT_ENSEMBLE_SEEDS)
    )
    parser.add_argument("--frozen-feature-width", type=int, default=FROZEN_FEATURE_WIDTH)
    args = parser.parse_args(argv)
    audit_path = args.teacher_audit or args.teacher.with_suffix(args.teacher.suffix + ".audit.json")
    result = run_pipeline(
        args.teacher,
        audit_path,
        args.split_manifest,
        args.out_dir,
        target=args.target,
        alphas=parse_numbers(args.alphas, float),
        ensemble_seeds=parse_numbers(args.ensemble_seeds, int),
        frozen_feature_width=args.frozen_feature_width,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
