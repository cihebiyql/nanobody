#!/usr/bin/env python3
"""Compute label-free sequence support distances for V4-C deployment control."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "phase2_v4_c_sequence_support_v1"
EXPECTED_SPLIT_SHA256 = "4660260cdf1f863281b12200aeee4b5d58b251ebd3774befae2eace9ca2465fe"
EXPECTED_POOL_SHA256 = "dd97835cfa3e39229d3ebddfe37768c7a8346a6237e35d2dbe16dc3d16ab965b"
KMER_WIDTH = 256
SUPPORT_QUANTILE = 0.95


class SupportError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_table(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def kmer_vector(sequence: str, k: int = 3, width: int = KMER_WIDTH) -> np.ndarray:
    sequence = sequence.strip().upper()
    if len(sequence) < k:
        raise SupportError("sequence_shorter_than_k")
    vector = np.zeros(width, dtype=np.float64)
    for index in range(len(sequence) - k + 1):
        token = sequence[index : index + k].encode("ascii")
        bucket = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % width
        vector[bucket] += 1.0
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


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


def normalized_edit_distance(left: str, right: str) -> float:
    return levenshtein(left, right) / max(len(left), len(right), 1)


def leave_family_out_thresholds(open_rows: list[dict[str, str]]) -> tuple[float, float]:
    vectors = np.stack([kmer_vector(row["sequence"]) for row in open_rows])
    similarities = vectors @ vectors.T
    full_distances = []
    cdr3_distances = []
    for index, row in enumerate(open_rows):
        allowed = [
            other
            for other in range(len(open_rows))
            if open_rows[other]["near_cdr3_family_id"] != row["near_cdr3_family_id"]
        ]
        if not allowed:
            raise SupportError("leave_family_out_neighbor_missing")
        full_distances.append(1.0 - float(np.max(similarities[index, allowed])))
        cdr3_distances.append(
            min(normalized_edit_distance(row["cdr3"], open_rows[other]["cdr3"]) for other in allowed)
        )
    return (
        float(np.quantile(full_distances, SUPPORT_QUANTILE, method="linear")),
        float(np.quantile(cdr3_distances, SUPPORT_QUANTILE, method="linear")),
    )


def score_pool(
    open_rows: list[dict[str, str]], pool_rows: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    full_threshold, cdr3_threshold = leave_family_out_thresholds(open_rows)
    open_vectors = np.stack([kmer_vector(row["sequence"]) for row in open_rows])
    pool_vectors = np.stack([kmer_vector(row["vhh_sequence"]) for row in pool_rows])
    full_distances = 1.0 - np.max(pool_vectors @ open_vectors.T, axis=1)
    output = []
    for index, row in enumerate(pool_rows):
        cdr3 = row["cdr3_after"]
        cdr3_distance = min(
            normalized_edit_distance(cdr3, open_row["cdr3"]) for open_row in open_rows
        )
        in_support = (
            float(full_distances[index]) <= full_threshold
            and cdr3_distance <= cdr3_threshold
        )
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "nearest_open_full_sequence_kmer_cosine_distance": round(float(full_distances[index]), 9),
                "nearest_open_cdr3_normalized_edit_distance": round(cdr3_distance, 9),
                "full_sequence_support_threshold": round(full_threshold, 9),
                "cdr3_support_threshold": round(cdr3_threshold, 9),
                "v4c_in_sequence_support": str(in_support).lower(),
            }
        )
    return output, {
        "full_sequence_support_threshold": full_threshold,
        "cdr3_support_threshold": cdr3_threshold,
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_c/dual128_split_manifest.tsv",
    )
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=root / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "prepared/pvrig_v4_c/candidate7087_sequence_support.csv",
    )
    args = parser.parse_args(argv)
    if sha256_file(args.split_manifest) != EXPECTED_SPLIT_SHA256:
        raise SupportError("split_manifest_sha256_mismatch")
    if sha256_file(args.candidate_pool) != EXPECTED_POOL_SHA256:
        raise SupportError("candidate_pool_sha256_mismatch")
    split = read_table(args.split_manifest, "\t")
    open_rows = [row for row in split if row["model_split"] == "OPEN_DEVELOPMENT"]
    pool = read_table(args.candidate_pool, ",")
    if len(open_rows) != 96 or len(pool) != 7087:
        raise SupportError(f"unexpected_row_counts:{len(open_rows)}:{len(pool)}")
    rows, thresholds = score_pool(open_rows, pool)
    write_csv(args.out, rows)
    in_support = sum(row["v4c_in_sequence_support"] == "true" for row in rows)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_LABEL_FREE_SEQUENCE_SUPPORT_SCORED",
        "split_manifest_sha256": sha256_file(args.split_manifest),
        "candidate_pool_sha256": sha256_file(args.candidate_pool),
        "open_reference_count": len(open_rows),
        "candidate_count": len(rows),
        "kmer_size": 3,
        "kmer_width": KMER_WIDTH,
        "support_quantile": SUPPORT_QUANTILE,
        "thresholds": thresholds,
        "in_support_count": in_support,
        "in_support_fraction": in_support / len(rows),
        "broad_use_coverage_gate_minimum": 0.6,
        "broad_use_coverage_gate_passed": in_support / len(rows) >= 0.6,
        "output": {"path": str(args.out), "sha256": sha256_file(args.out)},
        "claim_boundary": "Label-free sequence support diagnostic, not model correctness or binding evidence.",
    }
    audit_path = args.out.with_suffix(args.out.suffix + ".audit.json")
    write_json(audit_path, audit)
    print(json.dumps({"status": audit["status"], "coverage": audit["in_support_fraction"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
