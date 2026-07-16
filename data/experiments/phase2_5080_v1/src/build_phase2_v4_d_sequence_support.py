#!/usr/bin/env python3
"""Build the label-free V4-D sequence-support and OOD deployment audit.

Production mode is fail-closed: input hashes, calibration, null controls, and
deployment gates are code-locked. Tests may override them only through the
explicit ``--test-only-allow-unfrozen-config`` switch.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "phase2_v4_d_sequence_support_v2"
PRODUCTION_LOCK_ID = "pvrig_v4_d_sequence_support_exact3mer_nested_parent_v2_20260716"
EXPECTED_SPLIT_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_POOL_SHA256 = "dd97835cfa3e39229d3ebddfe37768c7a8346a6237e35d2dbe16dc3d16ab965b"
REFERENCE_SPLIT = "OPEN_TRAIN"
KMER_SIZE = 3
AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"
AA_INDEX = {amino_acid: index for index, amino_acid in enumerate(AA_ORDER)}
KMER_WIDTH = len(AA_ORDER) ** KMER_SIZE
SUPPORT_QUANTILE = 0.95
QUANTILE_METHOD = "linear"
OUTER_FOLDS = 5
FOLD_SEED = 20260716
NULL_SEED = 20260715
NULL_REPLICATES = 1000
CANONICAL_AA = frozenset(AA_ORDER)

EXPECTED_SPLIT_COUNT = 290
EXPECTED_REFERENCE_COUNT = 226
EXPECTED_CANDIDATE_COUNT = 7087
EXPECTED_TRAIN_REFERENCE_OVERLAP = 226
MINIMUM_COVERAGE = 0.60
MINIMUM_IN_SUPPORT_COUNT = 4117  # ceil(0.60 * (7087 - 226))
MINIMUM_NESTED_FULL_PASS = 0.80
MINIMUM_NESTED_CDR3_PASS = 0.80
MINIMUM_NESTED_JOINT_PARENT_PASS = 0.60
MAXIMUM_SHUFFLE_FULL_PASS = 0.05
MAXIMUM_SHUFFLE_CDR3_PASS = 0.10
MAXIMUM_SHUFFLE_JOINT_PARENT_PASS = 0.01
MAXIMUM_CHIMERA_JOINT_PARENT_PASS = 0.10
MAXIMUM_CHIMERA_JOINT_REFERENCE_PASS = 0.05


class SupportError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def read_table(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def count_table_rows(path: Path) -> int:
    delimiter = "\t" if path.suffix == ".tsv" else ","
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _row in csv.DictReader(handle, delimiter=delimiter))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise SupportError("cannot_write_empty_csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def normalize_sequence(sequence: str, field: str) -> str:
    normalized = sequence.strip().upper()
    if not normalized:
        raise SupportError(f"empty_sequence:{field}")
    invalid = sorted(set(normalized) - CANONICAL_AA)
    if invalid:
        raise SupportError(f"noncanonical_sequence:{field}:{''.join(invalid)}")
    return normalized


def validate_unique_ids(rows: Iterable[Mapping[str, str]], label: str) -> None:
    seen: set[str] = set()
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        if not candidate_id:
            raise SupportError(f"missing_candidate_id:{label}")
        if candidate_id in seen:
            raise SupportError(f"duplicate_candidate_id:{label}:{candidate_id}")
        seen.add(candidate_id)


def canonicalize_reference_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        sequence = normalize_sequence(row.get("sequence", ""), "reference_sequence")
        cdr3 = normalize_sequence(row.get("cdr3", ""), "reference_cdr3")
        sequence_sha256 = row.get("sequence_sha256", "")
        observed_sha256 = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if sequence_sha256 != observed_sha256:
            raise SupportError(f"reference_sequence_sha256_mismatch:{row.get('candidate_id', '')}")
        cluster = row.get("parent_framework_cluster", "")
        if not cluster:
            raise SupportError(f"missing_parent_framework_cluster:{row.get('candidate_id', '')}")
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": sequence_sha256,
                "sequence": sequence,
                "cdr3": cdr3,
                "parent_framework_cluster": cluster,
            }
        )
    validate_unique_ids(output, "reference")
    if len({row["parent_framework_cluster"] for row in output}) < OUTER_FOLDS:
        raise SupportError("nested_parent_validation_requires_at_least_outer_fold_clusters")
    return output


def canonicalize_candidate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        sequence = normalize_sequence(row.get("vhh_sequence", ""), "candidate_sequence")
        cdr3 = normalize_sequence(row.get("cdr3_after", ""), "candidate_cdr3")
        sequence_sha256 = row.get("sequence_sha256", "")
        observed_sha256 = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if sequence_sha256 != observed_sha256:
            raise SupportError(f"candidate_sequence_sha256_mismatch:{row.get('candidate_id', '')}")
        parent_cluster = row.get("parent_framework_cluster", "")
        if not parent_cluster:
            raise SupportError(f"missing_candidate_parent_framework_cluster:{row.get('candidate_id', '')}")
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": sequence_sha256,
                "sequence": sequence,
                "cdr3": cdr3,
                "parent_framework_cluster": parent_cluster,
            }
        )
    validate_unique_ids(output, "candidate")
    return output


def exact_trimer_index(token: str) -> int:
    if len(token) != KMER_SIZE:
        raise SupportError("exact_trimer_requires_length_three")
    return (
        (AA_INDEX[token[0]] * len(AA_ORDER) + AA_INDEX[token[1]]) * len(AA_ORDER)
        + AA_INDEX[token[2]]
    )


def kmer_vector(
    sequence: str, k: int = KMER_SIZE, width: int = KMER_WIDTH
) -> np.ndarray:
    """Return exact canonical 3-mer counts; no hash collisions are allowed."""
    sequence = normalize_sequence(sequence, "kmer_sequence")
    if k != KMER_SIZE or width != KMER_WIDTH:
        raise SupportError("production_representation_is_exact_8000_dimensional_trimer")
    if len(sequence) < k:
        raise SupportError("sequence_shorter_than_k")
    vector = np.zeros(KMER_WIDTH, dtype=np.float32)
    for index in range(len(sequence) - k + 1):
        vector[exact_trimer_index(sequence[index : index + k])] += 1.0
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise SupportError("zero_kmer_vector")
    return vector / norm


def kmer_matrix(rows: list[dict[str, str]]) -> np.ndarray:
    return np.stack([kmer_vector(row["sequence"]) for row in rows])


def levenshtein(left: str, right: str) -> int:
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for right_index, right_char in enumerate(right, 1):
        current = [right_index]
        for left_index, left_char in enumerate(left, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[left_index] + 1,
                    previous[left_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def normalized_levenshtein_distance(left: str, right: str) -> float:
    return levenshtein(left, right) / max(len(left), len(right), 1)


def cosine_distance(similarity: float) -> float:
    return min(1.0, max(0.0, 1.0 - similarity))


def clamp_cosine_distance(value: float) -> float:
    """Backward-compatible helper for tests using an already-computed distance."""
    return min(1.0, max(0.0, value))


def parent_indices(rows: list[dict[str, str]]) -> dict[str, np.ndarray]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[row["parent_framework_cluster"]].append(index)
    return {
        parent: np.asarray(indices, dtype=np.int64)
        for parent, indices in sorted(grouped.items())
    }


def row_distance_channels(
    sequence: str,
    cdr3: str,
    reference_rows: list[dict[str, str]],
    reference_vectors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    vector = kmer_vector(sequence)
    full_distances = np.asarray(
        [cosine_distance(float(value)) for value in reference_vectors @ vector],
        dtype=np.float64,
    )
    cdr3_distances = np.asarray(
        [normalized_levenshtein_distance(cdr3, row["cdr3"]) for row in reference_rows],
        dtype=np.float64,
    )
    return full_distances, cdr3_distances


def nearest_channel_metrics(
    full_distances: np.ndarray,
    cdr3_distances: np.ndarray,
    reference_rows: list[dict[str, str]],
    *,
    full_threshold: float,
    cdr3_threshold: float,
) -> dict[str, Any]:
    full_index = int(np.argmin(full_distances))
    cdr3_index = int(np.argmin(cdr3_distances))
    by_parent = parent_indices(reference_rows)
    parent_candidates: list[tuple[float, float, str, int, int]] = []
    for parent, indices in by_parent.items():
        local_full = int(indices[int(np.argmin(full_distances[indices]))])
        local_cdr3 = int(indices[int(np.argmin(cdr3_distances[indices]))])
        full_value = float(full_distances[local_full])
        cdr3_value = float(cdr3_distances[local_cdr3])
        scaled_max = max(
            full_value / max(full_threshold, 1e-12),
            cdr3_value / max(cdr3_threshold, 1e-12),
        )
        parent_candidates.append(
            (scaled_max, full_value + cdr3_value, parent, local_full, local_cdr3)
        )
    _scaled, _sum_distance, joint_parent, joint_full_index, joint_cdr3_index = min(
        parent_candidates
    )
    reference_candidates = [
        (
            max(
                float(full_distances[index]) / max(full_threshold, 1e-12),
                float(cdr3_distances[index]) / max(cdr3_threshold, 1e-12),
            ),
            float(full_distances[index] + cdr3_distances[index]),
            index,
        )
        for index in range(len(reference_rows))
    ]
    _reference_scaled, _reference_sum, joint_reference_index = min(reference_candidates)
    joint_parent_full = float(full_distances[joint_full_index])
    joint_parent_cdr3 = float(cdr3_distances[joint_cdr3_index])
    joint_reference_full = float(full_distances[joint_reference_index])
    joint_reference_cdr3 = float(cdr3_distances[joint_reference_index])
    return {
        "nearest_full_index": full_index,
        "nearest_cdr3_index": cdr3_index,
        "nearest_full_distance": float(full_distances[full_index]),
        "nearest_cdr3_distance": float(cdr3_distances[cdr3_index]),
        "full_channel_pass": float(full_distances[full_index]) <= full_threshold,
        "cdr3_channel_pass": float(cdr3_distances[cdr3_index]) <= cdr3_threshold,
        "joint_parent": joint_parent,
        "joint_parent_full_index": joint_full_index,
        "joint_parent_cdr3_index": joint_cdr3_index,
        "joint_parent_full_distance": joint_parent_full,
        "joint_parent_cdr3_distance": joint_parent_cdr3,
        "joint_parent_pass": (
            joint_parent_full <= full_threshold and joint_parent_cdr3 <= cdr3_threshold
        ),
        "joint_reference_index": joint_reference_index,
        "joint_reference_full_distance": joint_reference_full,
        "joint_reference_cdr3_distance": joint_reference_cdr3,
        "joint_reference_pass": (
            joint_reference_full <= full_threshold
            and joint_reference_cdr3 <= cdr3_threshold
        ),
    }


def calibrate_lopo_thresholds(
    reference_rows: list[dict[str, str]],
    *,
    support_quantile: float = SUPPORT_QUANTILE,
) -> dict[str, Any]:
    vectors = kmer_matrix(reference_rows)
    similarities = vectors @ vectors.T
    full_distances: list[float] = []
    cdr3_distances: list[float] = []
    row_controls: list[dict[str, Any]] = []
    for index, row in enumerate(reference_rows):
        allowed = np.asarray(
            [
                other
                for other, candidate in enumerate(reference_rows)
                if candidate["parent_framework_cluster"] != row["parent_framework_cluster"]
            ],
            dtype=np.int64,
        )
        if not len(allowed):
            raise SupportError("lopo_neighbor_missing")
        local_full = 1.0 - similarities[index, allowed]
        nearest_local = int(np.argmin(local_full))
        nearest_full_index = int(allowed[nearest_local])
        full_distance = clamp_cosine_distance(float(local_full[nearest_local]))
        cdr3_pairs = [
            (
                normalized_levenshtein_distance(
                    row["cdr3"], reference_rows[int(other)]["cdr3"]
                ),
                int(other),
            )
            for other in allowed
        ]
        cdr3_distance, nearest_cdr3_index = min(cdr3_pairs, key=lambda pair: (pair[0], pair[1]))
        full_distances.append(full_distance)
        cdr3_distances.append(cdr3_distance)
        row_controls.append(
            {
                "candidate_id": row["candidate_id"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "nearest_lopo_full_candidate_id": reference_rows[nearest_full_index]["candidate_id"],
                "nearest_lopo_full_distance": full_distance,
                "nearest_lopo_cdr3_candidate_id": reference_rows[nearest_cdr3_index]["candidate_id"],
                "nearest_lopo_cdr3_distance": cdr3_distance,
            }
        )
    return {
        "full_sequence_threshold": float(
            np.quantile(full_distances, support_quantile, method=QUANTILE_METHOD)
        ),
        "cdr3_threshold": float(
            np.quantile(cdr3_distances, support_quantile, method=QUANTILE_METHOD)
        ),
        "calibration_row_count": len(reference_rows),
        "calibration_parent_cluster_count": len(
            {row["parent_framework_cluster"] for row in reference_rows}
        ),
        "row_controls": row_controls,
        "reference_vectors": vectors,
    }


def lopo_calibration(
    reference_rows: list[dict[str, str]],
    *,
    support_quantile: float = SUPPORT_QUANTILE,
) -> dict[str, Any]:
    """Compatibility wrapper; no pass gate is computed on calibration rows."""
    return calibrate_lopo_thresholds(reference_rows, support_quantile=support_quantile)


def assign_parent_folds(
    reference_rows: list[dict[str, str]],
    fold_count: int = OUTER_FOLDS,
    seed: int = FOLD_SEED,
) -> dict[str, int]:
    counts = Counter(row["parent_framework_cluster"] for row in reference_rows)
    if len(counts) < fold_count:
        raise SupportError("fewer_parent_clusters_than_outer_folds")
    ordered = sorted(
        counts,
        key=lambda parent: (
            -counts[parent],
            hashlib.sha256(f"{seed}:{parent}".encode("ascii")).hexdigest(),
        ),
    )
    loads = [0] * fold_count
    assignment: dict[str, int] = {}
    for parent in ordered:
        fold = min(range(fold_count), key=lambda value: (loads[value], value))
        assignment[parent] = fold
        loads[fold] += counts[parent]
    return assignment


def nested_parent_validation(
    reference_rows: list[dict[str, str]],
    *,
    support_quantile: float = SUPPORT_QUANTILE,
    fold_count: int = OUTER_FOLDS,
    seed: int = FOLD_SEED,
) -> dict[str, Any]:
    assignments = assign_parent_folds(reference_rows, fold_count, seed)
    totals = Counter()
    folds: list[dict[str, Any]] = []
    for fold in range(fold_count):
        validation_clusters = {parent for parent, value in assignments.items() if value == fold}
        calibration_rows = [
            row for row in reference_rows if row["parent_framework_cluster"] not in validation_clusters
        ]
        validation_rows = [
            row for row in reference_rows if row["parent_framework_cluster"] in validation_clusters
        ]
        calibration_clusters = {row["parent_framework_cluster"] for row in calibration_rows}
        if calibration_clusters & validation_clusters:
            raise SupportError("nested_parent_cluster_leakage")
        calibration = calibrate_lopo_thresholds(
            calibration_rows, support_quantile=support_quantile
        )
        reference_vectors = calibration["reference_vectors"]
        fold_counts = Counter()
        for row in validation_rows:
            full_distances, cdr3_distances = row_distance_channels(
                row["sequence"], row["cdr3"], calibration_rows, reference_vectors
            )
            metric = nearest_channel_metrics(
                full_distances,
                cdr3_distances,
                calibration_rows,
                full_threshold=calibration["full_sequence_threshold"],
                cdr3_threshold=calibration["cdr3_threshold"],
            )
            fold_counts["rows"] += 1
            fold_counts["full"] += int(metric["full_channel_pass"])
            fold_counts["cdr3"] += int(metric["cdr3_channel_pass"])
            fold_counts["joint_parent"] += int(metric["joint_parent_pass"])
            fold_counts["joint_reference"] += int(metric["joint_reference_pass"])
        totals.update(fold_counts)
        folds.append(
            {
                "fold": fold,
                "calibration_parent_clusters": sorted(calibration_clusters),
                "validation_parent_clusters": sorted(validation_clusters),
                "calibration_row_count": len(calibration_rows),
                "validation_row_count": len(validation_rows),
                "full_sequence_threshold": calibration["full_sequence_threshold"],
                "cdr3_threshold": calibration["cdr3_threshold"],
                "full_channel_pass_fraction": fold_counts["full"] / fold_counts["rows"],
                "cdr3_channel_pass_fraction": fold_counts["cdr3"] / fold_counts["rows"],
                "joint_parent_pass_fraction": fold_counts["joint_parent"] / fold_counts["rows"],
                "joint_reference_pass_fraction": fold_counts["joint_reference"] / fold_counts["rows"],
            }
        )
    return {
        "policy": "outer_parent_cluster_holdout_with_inner_lopo_threshold_calibration",
        "fold_count": fold_count,
        "fold_seed": seed,
        "row_count": totals["rows"],
        "full_channel_pass_fraction": totals["full"] / totals["rows"],
        "cdr3_channel_pass_fraction": totals["cdr3"] / totals["rows"],
        "joint_parent_pass_fraction": totals["joint_parent"] / totals["rows"],
        "joint_reference_pass_fraction": totals["joint_reference"] / totals["rows"],
        "folds": folds,
    }


def shuffled_copy(sequence: str, rng: np.random.Generator) -> str:
    indices = rng.permutation(len(sequence))
    return "".join(sequence[int(index)] for index in indices)


def composition_preserving_shuffle_null(
    reference_rows: list[dict[str, str]],
    reference_vectors: np.ndarray,
    *,
    full_threshold: float,
    cdr3_threshold: float,
    replicates: int = NULL_REPLICATES,
    seed: int = NULL_SEED,
) -> dict[str, Any]:
    if replicates < 1:
        raise SupportError("null_replicates_must_be_positive")
    rng = np.random.default_rng(seed)
    counts = Counter()
    source_counts: Counter[str] = Counter()
    for _replicate in range(replicates):
        source_index = int(rng.integers(0, len(reference_rows)))
        source = reference_rows[source_index]
        source_cluster = source["parent_framework_cluster"]
        source_counts[source_cluster] += 1
        allowed_indices = [
            index
            for index, row in enumerate(reference_rows)
            if row["parent_framework_cluster"] != source_cluster
        ]
        allowed_rows = [reference_rows[index] for index in allowed_indices]
        allowed_vectors = reference_vectors[allowed_indices]
        full_distances, cdr3_distances = row_distance_channels(
            shuffled_copy(source["sequence"], rng),
            shuffled_copy(source["cdr3"], rng),
            allowed_rows,
            allowed_vectors,
        )
        metric = nearest_channel_metrics(
            full_distances,
            cdr3_distances,
            allowed_rows,
            full_threshold=full_threshold,
            cdr3_threshold=cdr3_threshold,
        )
        counts["full"] += int(metric["full_channel_pass"])
        counts["cdr3"] += int(metric["cdr3_channel_pass"])
        counts["joint_parent"] += int(metric["joint_parent_pass"])
        counts["joint_reference"] += int(metric["joint_reference_pass"])
    return {
        "seed": seed,
        "replicates": replicates,
        "source_sampling": "uniform_reference_row_with_replacement",
        "reference_exclusion": "source_parent_framework_cluster",
        "shuffle_policy": "independent_full_sequence_and_imgt_cdr3_composition_preserving_permutations",
        "full_channel_pass_count": counts["full"],
        "full_channel_pass_fraction": counts["full"] / replicates,
        "cdr3_channel_pass_count": counts["cdr3"],
        "cdr3_channel_pass_fraction": counts["cdr3"] / replicates,
        "joint_parent_pass_count": counts["joint_parent"],
        "joint_parent_pass_fraction": counts["joint_parent"] / replicates,
        "joint_reference_pass_count": counts["joint_reference"],
        "joint_reference_pass_fraction": counts["joint_reference"] / replicates,
        "sampled_source_parent_cluster_counts": dict(sorted(source_counts.items())),
    }


def unseen_parent_chimera_null(
    reference_rows: list[dict[str, str]],
    reference_vectors: np.ndarray,
    *,
    full_threshold: float,
    cdr3_threshold: float,
    replicates: int = NULL_REPLICATES,
    seed: int = NULL_SEED + 1,
) -> dict[str, Any]:
    """Score cross-parent chimeras after excluding both source parent clusters."""
    if replicates < 1:
        raise SupportError("null_replicates_must_be_positive")
    rng = np.random.default_rng(seed)
    by_parent = parent_indices(reference_rows)
    parents = sorted(by_parent)
    if len(parents) < 3:
        raise SupportError("chimera_null_requires_three_parent_clusters")
    counts = Counter()
    for _replicate in range(replicates):
        selected_parent_indices = rng.choice(len(parents), size=2, replace=False)
        source_parent = parents[int(selected_parent_indices[0])]
        donor_parent = parents[int(selected_parent_indices[1])]
        source_index = int(rng.choice(by_parent[source_parent]))
        donor_index = int(rng.choice(by_parent[donor_parent]))
        allowed_indices = [
            index
            for index, row in enumerate(reference_rows)
            if row["parent_framework_cluster"] not in {source_parent, donor_parent}
        ]
        allowed_rows = [reference_rows[index] for index in allowed_indices]
        allowed_vectors = reference_vectors[allowed_indices]
        full_distances, cdr3_distances = row_distance_channels(
            reference_rows[source_index]["sequence"],
            reference_rows[donor_index]["cdr3"],
            allowed_rows,
            allowed_vectors,
        )
        metric = nearest_channel_metrics(
            full_distances,
            cdr3_distances,
            allowed_rows,
            full_threshold=full_threshold,
            cdr3_threshold=cdr3_threshold,
        )
        counts["full"] += int(metric["full_channel_pass"])
        counts["cdr3"] += int(metric["cdr3_channel_pass"])
        counts["joint_parent"] += int(metric["joint_parent_pass"])
        counts["joint_reference"] += int(metric["joint_reference_pass"])
    return {
        "seed": seed,
        "replicates": replicates,
        "policy": "cross_parent_full_sequence_plus_cdr3_chimera_with_both_source_parents_excluded",
        "full_channel_pass_fraction": counts["full"] / replicates,
        "cdr3_channel_pass_fraction": counts["cdr3"] / replicates,
        "joint_parent_pass_fraction": counts["joint_parent"] / replicates,
        "joint_reference_pass_fraction": counts["joint_reference"] / replicates,
    }


def score_candidates(
    reference_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    *,
    reference_vectors: np.ndarray,
    full_threshold: float,
    cdr3_threshold: float,
) -> list[dict[str, Any]]:
    reference_ids = {row["candidate_id"] for row in reference_rows}
    reference_hashes = {row["sequence_sha256"] for row in reference_rows}
    reference_parents = parent_indices(reference_rows)
    output: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        full_distances, cdr3_distances = row_distance_channels(
            candidate["sequence"], candidate["cdr3"], reference_rows, reference_vectors
        )
        metric = nearest_channel_metrics(
            full_distances,
            cdr3_distances,
            reference_rows,
            full_threshold=full_threshold,
            cdr3_threshold=cdr3_threshold,
        )
        parent = candidate["parent_framework_cluster"]
        parent_seen = parent in reference_parents
        declared_parent_pass = False
        declared_parent_full = None
        declared_parent_cdr3 = None
        if parent_seen:
            indices = reference_parents[parent]
            declared_parent_full = float(np.min(full_distances[indices]))
            declared_parent_cdr3 = float(np.min(cdr3_distances[indices]))
            declared_parent_pass = (
                declared_parent_full <= full_threshold
                and declared_parent_cdr3 <= cdr3_threshold
            )
        is_train_reference = (
            candidate["candidate_id"] in reference_ids
            or candidate["sequence_sha256"] in reference_hashes
        )
        if is_train_reference:
            support_domain = "TRAIN_REFERENCE"
            domain_reason = "exact_open_train_candidate_or_sequence"
        elif parent_seen and declared_parent_pass:
            support_domain = "IN_DOMAIN"
            domain_reason = "declared_parent_seen_and_both_channels_supported_within_parent"
        elif not parent_seen:
            support_domain = "NEAR_DOMAIN"
            domain_reason = "declared_parent_unseen_default_near_not_exploitation_supported"
        elif metric["joint_parent_pass"] or metric["full_channel_pass"] or metric["cdr3_channel_pass"]:
            support_domain = "NEAR_DOMAIN"
            domain_reason = "seen_parent_failed_declared_parent_joint_gate_but_has_partial_or_other_parent_support"
        else:
            support_domain = "OOD"
            domain_reason = "seen_parent_and_no_supported_channel"
        in_support = support_domain == "IN_DOMAIN"
        full_index = metric["nearest_full_index"]
        cdr3_index = metric["nearest_cdr3_index"]
        joint_full_index = metric["joint_parent_full_index"]
        joint_cdr3_index = metric["joint_parent_cdr3_index"]
        joint_reference_index = metric["joint_reference_index"]
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "sequence_sha256": candidate["sequence_sha256"],
                "parent_framework_cluster": parent,
                "parent_cluster_seen_in_open_train": str(parent_seen).lower(),
                "is_open_train_reference": str(is_train_reference).lower(),
                "nearest_full_reference_candidate_id": reference_rows[full_index]["candidate_id"],
                "nearest_full_reference_parent_cluster": reference_rows[full_index]["parent_framework_cluster"],
                "nearest_full_sequence_exact_3mer_cosine_distance": round(metric["nearest_full_distance"], 9),
                "nearest_cdr3_reference_candidate_id": reference_rows[cdr3_index]["candidate_id"],
                "nearest_cdr3_reference_parent_cluster": reference_rows[cdr3_index]["parent_framework_cluster"],
                "nearest_cdr3_normalized_levenshtein_distance": round(metric["nearest_cdr3_distance"], 9),
                "nearest_joint_parent_cluster": metric["joint_parent"],
                "joint_parent_full_reference_candidate_id": reference_rows[joint_full_index]["candidate_id"],
                "joint_parent_cdr3_reference_candidate_id": reference_rows[joint_cdr3_index]["candidate_id"],
                "joint_parent_full_distance": round(metric["joint_parent_full_distance"], 9),
                "joint_parent_cdr3_distance": round(metric["joint_parent_cdr3_distance"], 9),
                "joint_parent_supported": str(metric["joint_parent_pass"]).lower(),
                "nearest_joint_reference_candidate_id": reference_rows[joint_reference_index]["candidate_id"],
                "joint_reference_full_distance": round(metric["joint_reference_full_distance"], 9),
                "joint_reference_cdr3_distance": round(metric["joint_reference_cdr3_distance"], 9),
                "joint_reference_supported": str(metric["joint_reference_pass"]).lower(),
                "declared_parent_full_distance": "" if declared_parent_full is None else round(declared_parent_full, 9),
                "declared_parent_cdr3_distance": "" if declared_parent_cdr3 is None else round(declared_parent_cdr3, 9),
                "declared_parent_joint_supported": str(declared_parent_pass).lower(),
                "full_sequence_support_threshold": round(full_threshold, 9),
                "cdr3_support_threshold": round(cdr3_threshold, 9),
                "full_sequence_channel_supported": str(metric["full_channel_pass"]).lower(),
                "cdr3_channel_supported": str(metric["cdr3_channel_pass"]).lower(),
                "v4d_in_sequence_support": str(in_support).lower(),
                "v4d_support_domain": support_domain,
                "v4d_support_domain_reason": domain_reason,
            }
        )
    return output


def production_locked_values() -> dict[str, Any]:
    return {
        "expected_split_sha256": EXPECTED_SPLIT_SHA256,
        "expected_candidate_pool_sha256": EXPECTED_POOL_SHA256,
        "expected_split_count": EXPECTED_SPLIT_COUNT,
        "expected_reference_count": EXPECTED_REFERENCE_COUNT,
        "expected_candidate_count": EXPECTED_CANDIDATE_COUNT,
        "expected_train_reference_overlap": EXPECTED_TRAIN_REFERENCE_OVERLAP,
        "support_quantile": SUPPORT_QUANTILE,
        "outer_folds": OUTER_FOLDS,
        "fold_seed": FOLD_SEED,
        "null_seed": NULL_SEED,
        "null_replicates": NULL_REPLICATES,
        "minimum_coverage": MINIMUM_COVERAGE,
        "minimum_in_support_count": MINIMUM_IN_SUPPORT_COUNT,
        "minimum_nested_full_pass": MINIMUM_NESTED_FULL_PASS,
        "minimum_nested_cdr3_pass": MINIMUM_NESTED_CDR3_PASS,
        "minimum_nested_joint_parent_pass": MINIMUM_NESTED_JOINT_PARENT_PASS,
        "maximum_shuffle_full_pass": MAXIMUM_SHUFFLE_FULL_PASS,
        "maximum_shuffle_cdr3_pass": MAXIMUM_SHUFFLE_CDR3_PASS,
        "maximum_shuffle_joint_parent_pass": MAXIMUM_SHUFFLE_JOINT_PARENT_PASS,
        "maximum_chimera_joint_parent_pass": MAXIMUM_CHIMERA_JOINT_PARENT_PASS,
        "maximum_chimera_joint_reference_pass": MAXIMUM_CHIMERA_JOINT_REFERENCE_PASS,
    }


def validate_production_lock(args: argparse.Namespace) -> str:
    if args.test_only_allow_unfrozen_config:
        return "TEST_ONLY_UNFROZEN_CONFIGURATION"
    expected = production_locked_values()
    mismatches = [
        key for key, value in expected.items() if getattr(args, key) != value
    ]
    if mismatches:
        raise SupportError("production_configuration_override_forbidden:" + ",".join(mismatches))
    return "PRODUCTION_LOCKED_CONFIGURATION"


def build_configuration(args: argparse.Namespace, execution_mode: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "production_lock_id": PRODUCTION_LOCK_ID,
        "execution_mode": execution_mode,
        "reference_split": REFERENCE_SPLIT,
        "sequence_channel": {
            "representation": "exact_canonical_amino_acid_3mer_counts_l2_normalized",
            "kmer_size": KMER_SIZE,
            "width": KMER_WIDTH,
            "hashing": False,
            "distance": "one_minus_cosine_similarity",
        },
        "cdr3_channel": {
            "region": "IMGT_CDR3",
            "distance": "levenshtein_distance_divided_by_max_length",
        },
        "calibration": {
            "threshold_policy": "inner_leave_one_parent_cluster_out_nearest_distance",
            "validation_policy": "outer_parent_cluster_holdout_never_used_for_its_fold_threshold",
            "support_quantile": args.support_quantile,
            "quantile_method": QUANTILE_METHOD,
            "outer_folds": args.outer_folds,
            "fold_seed": args.fold_seed,
        },
        "joint_neighbor_policy": {
            "primary": "both_channels_supported_within_same_parent_cluster",
            "secondary_diagnostic": "both_channels_supported_by_same_reference_sequence",
            "in_domain": "declared_parent_seen_and_both_channels_supported_within_declared_parent",
            "unseen_declared_parent": "NEAR_DOMAIN_not_exploitation_supported",
            "train_reference": "TRAIN_REFERENCE_excluded_from_deployment_coverage",
        },
        "null_controls": {
            "composition_shuffle": "per_channel_and_joint_gates",
            "unseen_parent_chimera": "cross_parent_sequence_cdr3_pair_with_both_source_parents_excluded",
            "seed": args.null_seed,
            "replicates": args.null_replicates,
        },
        "expected_counts": {
            "split_manifest": args.expected_split_count,
            "open_train_reference": args.expected_reference_count,
            "candidate_pool": args.expected_candidate_count,
            "train_reference_overlap": args.expected_train_reference_overlap,
        },
        "gates": {
            "deployment_coverage_fraction_minimum": args.minimum_coverage,
            "deployment_in_support_count_minimum": args.minimum_in_support_count,
            "nested_full_pass_minimum": args.minimum_nested_full_pass,
            "nested_cdr3_pass_minimum": args.minimum_nested_cdr3_pass,
            "nested_joint_parent_pass_minimum": args.minimum_nested_joint_parent_pass,
            "shuffle_full_pass_maximum": args.maximum_shuffle_full_pass,
            "shuffle_cdr3_pass_maximum": args.maximum_shuffle_cdr3_pass,
            "shuffle_joint_parent_pass_maximum": args.maximum_shuffle_joint_parent_pass,
            "chimera_joint_parent_pass_maximum": args.maximum_chimera_joint_parent_pass,
            "chimera_joint_reference_pass_maximum": args.maximum_chimera_joint_reference_pass,
        },
    }


def gate(observed: float | int, threshold: float | int, comparison: str) -> dict[str, Any]:
    if comparison == "minimum":
        passed = observed >= threshold
    elif comparison == "maximum":
        passed = observed <= threshold
    else:
        raise SupportError(f"unknown_gate_comparison:{comparison}")
    return {"observed": observed, comparison: threshold, "passed": passed}


def verify_hash_record(record: Mapping[str, Any], label: str) -> None:
    path = Path(str(record.get("path", "")))
    expected = record.get("sha256")
    if not path.is_file():
        raise SupportError(f"closure_path_missing:{label}:{path}")
    if sha256_file(path) != expected:
        raise SupportError(f"closure_sha256_mismatch:{label}:{path}")
    if "row_count" in record and count_table_rows(path) != int(record["row_count"]):
        raise SupportError(f"closure_row_count_mismatch:{label}:{path}")


def verify_artifact_closure(audit_path: Path, receipt_path: Path) -> dict[str, Any]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    claimed_payload_hash = audit.pop("audit_payload_sha256", None)
    if claimed_payload_hash != sha256_json(audit):
        raise SupportError("audit_payload_sha256_mismatch")
    if audit.get("configuration_sha256") != sha256_json(audit.get("configuration")):
        raise SupportError("configuration_sha256_mismatch")
    for label, record in audit["inputs"].items():
        verify_hash_record(record, f"input:{label}")
    verify_hash_record(audit["implementation"], "implementation")
    for label, record in audit["outputs"].items():
        verify_hash_record(record, f"output:{label}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS_COMPLETE_HASH_CLOSURE":
        raise SupportError("receipt_status_not_pass")
    verify_hash_record(receipt["audit"], "audit")
    if receipt.get("configuration_sha256") != audit["configuration_sha256"]:
        raise SupportError("receipt_configuration_sha256_mismatch")
    expected_bindings = {
        "split_manifest": audit["inputs"]["split_manifest"],
        "candidate_pool": audit["inputs"]["candidate_pool"],
        "implementation": audit["implementation"],
        "sequence_support_csv": audit["outputs"]["sequence_support_csv"],
    }
    if receipt.get("bindings") != expected_bindings:
        raise SupportError("receipt_audit_binding_mismatch")
    for label, record in receipt["bindings"].items():
        verify_hash_record(record, f"receipt_binding:{label}")
    return {
        "status": "PASS_COMPLETE_HASH_CLOSURE",
        "audit_sha256": sha256_file(audit_path),
        "receipt_path": str(receipt_path),
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=root / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "prepared/pvrig_v4_d/candidate7087_sequence_support.csv",
    )
    parser.add_argument("--audit-out", type=Path)
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--expected-split-sha256", default=EXPECTED_SPLIT_SHA256)
    parser.add_argument("--expected-candidate-pool-sha256", default=EXPECTED_POOL_SHA256)
    parser.add_argument("--expected-split-count", type=int, default=EXPECTED_SPLIT_COUNT)
    parser.add_argument("--expected-reference-count", type=int, default=EXPECTED_REFERENCE_COUNT)
    parser.add_argument("--expected-candidate-count", type=int, default=EXPECTED_CANDIDATE_COUNT)
    parser.add_argument(
        "--expected-train-reference-overlap", type=int, default=EXPECTED_TRAIN_REFERENCE_OVERLAP
    )
    parser.add_argument("--support-quantile", type=float, default=SUPPORT_QUANTILE)
    parser.add_argument("--outer-folds", type=int, default=OUTER_FOLDS)
    parser.add_argument("--fold-seed", type=int, default=FOLD_SEED)
    parser.add_argument("--null-seed", type=int, default=NULL_SEED)
    parser.add_argument("--null-replicates", type=int, default=NULL_REPLICATES)
    parser.add_argument("--minimum-coverage", type=float, default=MINIMUM_COVERAGE)
    parser.add_argument("--minimum-in-support-count", type=int, default=MINIMUM_IN_SUPPORT_COUNT)
    parser.add_argument("--minimum-nested-full-pass", type=float, default=MINIMUM_NESTED_FULL_PASS)
    parser.add_argument("--minimum-nested-cdr3-pass", type=float, default=MINIMUM_NESTED_CDR3_PASS)
    parser.add_argument(
        "--minimum-nested-joint-parent-pass",
        type=float,
        default=MINIMUM_NESTED_JOINT_PARENT_PASS,
    )
    parser.add_argument("--maximum-shuffle-full-pass", type=float, default=MAXIMUM_SHUFFLE_FULL_PASS)
    parser.add_argument("--maximum-shuffle-cdr3-pass", type=float, default=MAXIMUM_SHUFFLE_CDR3_PASS)
    parser.add_argument(
        "--maximum-shuffle-joint-parent-pass",
        type=float,
        default=MAXIMUM_SHUFFLE_JOINT_PARENT_PASS,
    )
    parser.add_argument(
        "--maximum-chimera-joint-parent-pass",
        type=float,
        default=MAXIMUM_CHIMERA_JOINT_PARENT_PASS,
    )
    parser.add_argument(
        "--maximum-chimera-joint-reference-pass",
        type=float,
        default=MAXIMUM_CHIMERA_JOINT_REFERENCE_PASS,
    )
    parser.add_argument("--test-only-allow-unfrozen-config", action="store_true")
    args = parser.parse_args(argv)

    execution_mode = validate_production_lock(args)
    if not 0.0 < args.support_quantile <= 1.0:
        raise SupportError("support_quantile_out_of_range")
    for name in (
        "minimum_coverage",
        "minimum_nested_full_pass",
        "minimum_nested_cdr3_pass",
        "minimum_nested_joint_parent_pass",
        "maximum_shuffle_full_pass",
        "maximum_shuffle_cdr3_pass",
        "maximum_shuffle_joint_parent_pass",
        "maximum_chimera_joint_parent_pass",
        "maximum_chimera_joint_reference_pass",
    ):
        if not 0.0 <= getattr(args, name) <= 1.0:
            raise SupportError(f"fraction_gate_out_of_range:{name}")

    split_sha256 = sha256_file(args.split_manifest)
    pool_sha256 = sha256_file(args.candidate_pool)
    if split_sha256 != args.expected_split_sha256:
        raise SupportError("split_manifest_sha256_mismatch")
    if pool_sha256 != args.expected_candidate_pool_sha256:
        raise SupportError("candidate_pool_sha256_mismatch")
    split_rows = read_table(args.split_manifest, "\t")
    pool_rows = read_table(args.candidate_pool, ",")
    reference_raw = [row for row in split_rows if row.get("model_split") == REFERENCE_SPLIT]
    if len(split_rows) != args.expected_split_count:
        raise SupportError(f"unexpected_split_count:{len(split_rows)}:{args.expected_split_count}")
    if len(reference_raw) != args.expected_reference_count:
        raise SupportError(
            f"unexpected_reference_count:{len(reference_raw)}:{args.expected_reference_count}"
        )
    if len(pool_rows) != args.expected_candidate_count:
        raise SupportError(f"unexpected_candidate_count:{len(pool_rows)}:{args.expected_candidate_count}")

    reference_rows = canonicalize_reference_rows(reference_raw)
    candidate_rows = canonicalize_candidate_rows(pool_rows)
    reference_ids = {row["candidate_id"] for row in reference_rows}
    candidate_ids = {row["candidate_id"] for row in candidate_rows}
    reference_hashes = {row["sequence_sha256"] for row in reference_rows}
    train_reference_overlap = sum(
        row["candidate_id"] in reference_ids or row["sequence_sha256"] in reference_hashes
        for row in candidate_rows
    )
    if train_reference_overlap != args.expected_train_reference_overlap:
        raise SupportError(
            f"unexpected_train_reference_overlap:{train_reference_overlap}:"
            f"{args.expected_train_reference_overlap}"
        )
    if not reference_ids <= candidate_ids:
        raise SupportError("open_train_reference_ids_not_closed_in_candidate_pool")

    nested_validation = nested_parent_validation(
        reference_rows,
        support_quantile=args.support_quantile,
        fold_count=args.outer_folds,
        seed=args.fold_seed,
    )
    final_calibration = calibrate_lopo_thresholds(
        reference_rows, support_quantile=args.support_quantile
    )
    reference_vectors = final_calibration["reference_vectors"]
    full_threshold = final_calibration["full_sequence_threshold"]
    cdr3_threshold = final_calibration["cdr3_threshold"]
    shuffle_null = composition_preserving_shuffle_null(
        reference_rows,
        reference_vectors,
        full_threshold=full_threshold,
        cdr3_threshold=cdr3_threshold,
        replicates=args.null_replicates,
        seed=args.null_seed,
    )
    chimera_null = unseen_parent_chimera_null(
        reference_rows,
        reference_vectors,
        full_threshold=full_threshold,
        cdr3_threshold=cdr3_threshold,
        replicates=args.null_replicates,
        seed=args.null_seed + 1,
    )
    output_rows = score_candidates(
        reference_rows,
        candidate_rows,
        reference_vectors=reference_vectors,
        full_threshold=full_threshold,
        cdr3_threshold=cdr3_threshold,
    )
    write_csv(args.out, output_rows)

    domain_counts = Counter(row["v4d_support_domain"] for row in output_rows)
    deployment_rows = [row for row in output_rows if row["v4d_support_domain"] != "TRAIN_REFERENCE"]
    in_support_count = sum(row["v4d_support_domain"] == "IN_DOMAIN" for row in deployment_rows)
    deployment_count = len(deployment_rows)
    coverage = in_support_count / deployment_count
    gates = {
        "deployment_coverage_fraction": gate(coverage, args.minimum_coverage, "minimum"),
        "deployment_in_support_count": gate(
            in_support_count, args.minimum_in_support_count, "minimum"
        ),
        "nested_unseen_parent_full_channel": gate(
            nested_validation["full_channel_pass_fraction"],
            args.minimum_nested_full_pass,
            "minimum",
        ),
        "nested_unseen_parent_cdr3_channel": gate(
            nested_validation["cdr3_channel_pass_fraction"],
            args.minimum_nested_cdr3_pass,
            "minimum",
        ),
        "nested_unseen_parent_joint_parent": gate(
            nested_validation["joint_parent_pass_fraction"],
            args.minimum_nested_joint_parent_pass,
            "minimum",
        ),
        "shuffle_full_channel": gate(
            shuffle_null["full_channel_pass_fraction"],
            args.maximum_shuffle_full_pass,
            "maximum",
        ),
        "shuffle_cdr3_channel": gate(
            shuffle_null["cdr3_channel_pass_fraction"],
            args.maximum_shuffle_cdr3_pass,
            "maximum",
        ),
        "shuffle_joint_parent": gate(
            shuffle_null["joint_parent_pass_fraction"],
            args.maximum_shuffle_joint_parent_pass,
            "maximum",
        ),
        "unseen_parent_chimera_joint_parent": gate(
            chimera_null["joint_parent_pass_fraction"],
            args.maximum_chimera_joint_parent_pass,
            "maximum",
        ),
        "unseen_parent_chimera_joint_reference": gate(
            chimera_null["joint_reference_pass_fraction"],
            args.maximum_chimera_joint_reference_pass,
            "maximum",
        ),
    }
    all_gates_passed = all(value["passed"] for value in gates.values())
    configuration = build_configuration(args, execution_mode)
    production_prefix = "" if execution_mode == "PRODUCTION_LOCKED_CONFIGURATION" else "TEST_ONLY_"
    audit: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "production_lock_id": PRODUCTION_LOCK_ID,
        "execution_mode": execution_mode,
        "status": production_prefix
        + (
            "PASS_LABEL_FREE_SEQUENCE_SUPPORT_GATES"
            if all_gates_passed
            else "FAIL_LABEL_FREE_SEQUENCE_SUPPORT_GATES"
        ),
        "all_gates_passed": all_gates_passed,
        "inputs": {
            "split_manifest": {
                "path": str(args.split_manifest.resolve()),
                "sha256": split_sha256,
                "row_count": len(split_rows),
            },
            "candidate_pool": {
                "path": str(args.candidate_pool.resolve()),
                "sha256": pool_sha256,
                "row_count": len(pool_rows),
            },
        },
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
        "reference": {
            "split": REFERENCE_SPLIT,
            "row_count": len(reference_rows),
            "parent_framework_cluster_count": len(
                {row["parent_framework_cluster"] for row in reference_rows}
            ),
            "train_reference_overlap_count": train_reference_overlap,
            "train_references_excluded_from_deployment_coverage": True,
        },
        "thresholds": {
            "full_sequence_exact_3mer_cosine_distance": full_threshold,
            "imgt_cdr3_normalized_levenshtein_distance": cdr3_threshold,
            "quantile": args.support_quantile,
            "method": QUANTILE_METHOD,
            "role": "final_thresholds_calibrated_on_all_open_train_after_nested_method_validation",
        },
        "controls": {
            "nested_parent_cluster_validation": nested_validation,
            "composition_preserving_shuffle_null": shuffle_null,
            "unseen_parent_chimera_null": chimera_null,
        },
        "coverage": {
            "candidate_count": len(output_rows),
            "train_reference_count_excluded": domain_counts["TRAIN_REFERENCE"],
            "deployment_candidate_count": deployment_count,
            "in_support_count": in_support_count,
            "in_support_fraction": coverage,
            "domain_counts": dict(sorted(domain_counts.items())),
        },
        "gates": gates,
        "outputs": {
            "sequence_support_csv": {
                "path": str(args.out.resolve()),
                "sha256": sha256_file(args.out),
                "row_count": len(output_rows),
            }
        },
        "claim_boundary": (
            "Label-free support/OOD diagnostic for a sequence-to-independent-dual-docking "
            "surrogate. It is not model correctness, binding, affinity, competition, Docking "
            "Gold, or experimental blocking evidence. A failed gate forbids surrogate "
            "exploitation but does not invalidate direct docking evidence."
        ),
    }
    audit["audit_payload_sha256"] = sha256_json(audit)
    audit_path = args.audit_out or args.out.with_suffix(args.out.suffix + ".audit.json")
    write_json(audit_path, audit)
    receipt_path = args.receipt_out or args.out.with_suffix(args.out.suffix + ".receipt.json")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_HASH_CLOSURE",
        "production_lock_id": PRODUCTION_LOCK_ID,
        "audit": {"path": str(audit_path.resolve()), "sha256": sha256_file(audit_path)},
        "bindings": {
            "split_manifest": audit["inputs"]["split_manifest"],
            "candidate_pool": audit["inputs"]["candidate_pool"],
            "implementation": audit["implementation"],
            "sequence_support_csv": audit["outputs"]["sequence_support_csv"],
        },
        "configuration_sha256": audit["configuration_sha256"],
    }
    write_json(receipt_path, receipt)
    closure = verify_artifact_closure(audit_path, receipt_path)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "coverage": coverage,
                "in_support_count": in_support_count,
                "deployment_candidate_count": deployment_count,
                "nested_joint_parent_pass_fraction": nested_validation[
                    "joint_parent_pass_fraction"
                ],
                "shuffle_cdr3_pass_fraction": shuffle_null["cdr3_channel_pass_fraction"],
                "chimera_joint_parent_pass_fraction": chimera_null[
                    "joint_parent_pass_fraction"
                ],
                "out": str(args.out),
                "audit": str(audit_path),
                "receipt": str(receipt_path),
                "hash_closure": closure["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
