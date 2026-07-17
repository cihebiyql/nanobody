#!/usr/bin/env python3
"""Compare frozen V4-H sequence and structure surrogate rankings without labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCHEMA_VERSION = "phase2_v4_h_research1320_sequence_structure_comparison_v1"
STATUS = "COMPLETE_LABEL_FREE_V4_H_SEQUENCE_STRUCTURE_SURROGATE_COMPARISON"
EXPECTED_SEQUENCE_SHA256 = "a87d37d9edf130b2eb82e301746d52abee4a56fd7babf5bde4b5b0eefcc92fbc"
EXPECTED_STRUCTURE_SHA256 = "f864c675db2c9ec449e52a7debacdd283ff5d404f40b6abfbd9cb0ef3e6b9d5a"
EXPECTED_ROWS = 1320
TOP_SIZES = (20, 50, 100)
CLAIM_BOUNDARY = (
    "Label-free comparison of frozen OPEN_TRAIN sequence and monomer-structure "
    "surrogates for computational docking geometry R_dual_min; no V4-H docking "
    "result, pose, geometry label, binding, affinity, or experimental blocking truth."
)


class ComparisonError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ComparisonError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    output = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        output[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return output


def correlation(left: np.ndarray, right: np.ndarray) -> float:
    require(len(left) == len(right) and len(left) >= 2, "correlation_length_invalid")
    require(np.isfinite(left).all() and np.isfinite(right).all(), "correlation_nonfinite")
    require(float(np.std(left)) > 0 and float(np.std(right)) > 0, "correlation_constant")
    return float(np.corrcoef(left, right)[0, 1])


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), f"cannot_write_empty_table:{path.name}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def top_parent_counts(rows: list[dict[str, Any]], rank_key: str, size: int) -> dict[str, int]:
    ordered = sorted(rows, key=lambda row: (row[rank_key], row["candidate_id"]))[:size]
    return dict(sorted(Counter(row["parent_framework_cluster"] for row in ordered).items()))


def compare(
    sequence_path: Path,
    structure_path: Path,
    output_dir: Path,
    *,
    expected_sequence_sha256: str = EXPECTED_SEQUENCE_SHA256,
    expected_structure_sha256: str = EXPECTED_STRUCTURE_SHA256,
    expected_rows: int = EXPECTED_ROWS,
    expected_parent_count: int = 11,
    expected_patch_count: int = 3,
    expected_mode_count: int = 2,
    expected_rows_per_stratum: int = 20,
    portfolio_per_stratum: int = 2,
    disagreement_tail_size: int = 50,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    require(sha256_file(sequence_path) == expected_sequence_sha256, "sequence_ranking_hash_mismatch")
    require(sha256_file(structure_path) == expected_structure_sha256, "structure_ranking_hash_mismatch")
    sequence_rows = load_tsv(sequence_path)
    structure_rows = load_tsv(structure_path)
    require(len(sequence_rows) == len(structure_rows) == expected_rows, "ranking_row_count_invalid")
    require(len({row["candidate_id"] for row in sequence_rows}) == expected_rows, "sequence_candidate_ids_not_unique")
    require(len({row["candidate_id"] for row in structure_rows}) == expected_rows, "structure_candidate_ids_not_unique")
    sequence_by_id = {row["candidate_id"]: row for row in sequence_rows}
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    require(set(sequence_by_id) == set(structure_by_id), "ranking_candidate_set_mismatch")

    combined: list[dict[str, Any]] = []
    for candidate_id in sorted(sequence_by_id):
        sequence = sequence_by_id[candidate_id]
        structure = structure_by_id[candidate_id]
        for field in ("sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"):
            require(sequence[field] == structure[field], f"ranking_metadata_mismatch:{candidate_id}:{field}")
        sequence_rank = int(sequence["research_rank"])
        structure_rank = int(structure["research_rank"])
        sequence_prediction = float(sequence["predicted_R_dual_min_sequence_only"])
        structure_prediction = float(structure["predicted_R_dual_min_structure_only"])
        require(np.isfinite(sequence_prediction) and np.isfinite(structure_prediction), f"prediction_nonfinite:{candidate_id}")
        combined.append({
            "candidate_id": candidate_id,
            "sequence_sha256": sequence["sequence_sha256"],
            "parent_framework_cluster": sequence["parent_framework_cluster"],
            "target_patch_id": sequence["target_patch_id"],
            "design_mode": sequence["design_mode"],
            "sequence_prediction": sequence_prediction,
            "structure_prediction": structure_prediction,
            "sequence_rank": sequence_rank,
            "structure_rank": structure_rank,
            "sequence_rank_percentile": float(sequence["research_rank_percentile"]),
            "structure_rank_percentile": float(structure["research_rank_percentile"]),
            "rank_delta_sequence_minus_structure": sequence_rank - structure_rank,
        })
    require(sorted(row["sequence_rank"] for row in combined) == list(range(1, expected_rows + 1)), "sequence_ranks_invalid")
    require(sorted(row["structure_rank"] for row in combined) == list(range(1, expected_rows + 1)), "structure_ranks_invalid")
    parents = sorted({row["parent_framework_cluster"] for row in combined})
    patches = sorted({row["target_patch_id"] for row in combined})
    modes = sorted({row["design_mode"] for row in combined})
    require(len(parents) == expected_parent_count, "parent_count_invalid")
    require(len(patches) == expected_patch_count, "patch_count_invalid")
    require(len(modes) == expected_mode_count, "mode_count_invalid")
    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in combined:
        strata[(row["parent_framework_cluster"], row["target_patch_id"], row["design_mode"])].append(row)
    require(len(strata) == expected_parent_count * expected_patch_count * expected_mode_count, "stratum_count_invalid")
    require(all(len(rows) == expected_rows_per_stratum for rows in strata.values()), "stratum_size_invalid")

    sequence_values = np.asarray([row["sequence_prediction"] for row in combined], dtype=np.float64)
    structure_values = np.asarray([row["structure_prediction"] for row in combined], dtype=np.float64)
    prediction_pearson = correlation(sequence_values, structure_values)
    prediction_spearman = correlation(average_ranks(sequence_values), average_ranks(structure_values))

    top_overlap: dict[str, Any] = {}
    for size in TOP_SIZES:
        sequence_top = {row["candidate_id"] for row in combined if row["sequence_rank"] <= size}
        structure_top = {row["candidate_id"] for row in combined if row["structure_rank"] <= size}
        overlap = len(sequence_top & structure_top)
        top_overlap[str(size)] = {
            "overlap_count": overlap,
            "overlap_fraction_of_each_topN": overlap / size,
            "jaccard": overlap / len(sequence_top | structure_top),
            "sequence_parent_counts": top_parent_counts(combined, "sequence_rank", size),
            "structure_parent_counts": top_parent_counts(combined, "structure_rank", size),
        }

    parent_rows: list[dict[str, Any]] = []
    for parent in parents:
        subset = [row for row in combined if row["parent_framework_cluster"] == parent]
        seq = np.asarray([row["sequence_prediction"] for row in subset], dtype=np.float64)
        struct = np.asarray([row["structure_prediction"] for row in subset], dtype=np.float64)
        parent_rows.append({
            "schema_version": SCHEMA_VERSION,
            "parent_framework_cluster": parent,
            "row_count": len(subset),
            "sequence_prediction_mean": f"{np.mean(seq):.12g}",
            "sequence_prediction_median": f"{np.median(seq):.12g}",
            "structure_prediction_mean": f"{np.mean(struct):.12g}",
            "structure_prediction_median": f"{np.median(struct):.12g}",
            "within_parent_prediction_pearson": f"{correlation(seq, struct):.12g}",
            **{f"sequence_top{size}_count": sum(row["sequence_rank"] <= size for row in subset) for size in TOP_SIZES},
            **{f"structure_top{size}_count": sum(row["structure_rank"] <= size for row in subset) for size in TOP_SIZES},
            "claim_boundary": CLAIM_BOUNDARY,
        })

    disagreement_rows: list[dict[str, Any]] = []
    directions = (
        ("STRUCTURE_FAVORED", sorted(combined, key=lambda row: (-row["rank_delta_sequence_minus_structure"], row["candidate_id"]))),
        ("SEQUENCE_FAVORED", sorted(combined, key=lambda row: (row["rank_delta_sequence_minus_structure"], row["candidate_id"]))),
    )
    for direction, ordered in directions:
        for tail_rank, row in enumerate(ordered[:disagreement_tail_size], start=1):
            disagreement_rows.append({
                "schema_version": SCHEMA_VERSION,
                "disagreement_direction": direction,
                "tail_rank": tail_rank,
                **{key: row[key] for key in (
                    "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode",
                    "sequence_prediction", "structure_prediction", "sequence_rank", "structure_rank",
                    "rank_delta_sequence_minus_structure",
                )},
                "claim_boundary": CLAIM_BOUNDARY,
            })

    portfolio_rows: list[dict[str, Any]] = []
    for stratum in sorted(strata):
        rows = strata[stratum]
        consensus = sorted(
            rows,
            key=lambda row: (
                -(row["sequence_rank_percentile"] + row["structure_rank_percentile"]) / 2.0,
                row["candidate_id"],
            ),
        )[0]
        selected = [("CONSENSUS_HIGH", consensus)]
        if portfolio_per_stratum > 1:
            remaining = [row for row in rows if row["candidate_id"] != consensus["candidate_id"]]
            disagreement = sorted(
                remaining,
                key=lambda row: (-abs(row["rank_delta_sequence_minus_structure"]), row["candidate_id"]),
            )[0]
            delta = disagreement["rank_delta_sequence_minus_structure"]
            role = "STRUCTURE_FAVORED_DISAGREEMENT" if delta > 0 else "SEQUENCE_FAVORED_DISAGREEMENT" if delta < 0 else "LOW_DISAGREEMENT_CONTROL"
            selected.append((role, disagreement))
        require(len(selected) == portfolio_per_stratum, "portfolio_per_stratum_not_supported")
        for role, row in selected:
            portfolio_rows.append({
                "schema_version": SCHEMA_VERSION,
                "portfolio_role": role,
                **{key: row[key] for key in (
                    "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode",
                    "sequence_prediction", "structure_prediction", "sequence_rank", "structure_rank",
                    "sequence_rank_percentile", "structure_rank_percentile", "rank_delta_sequence_minus_structure",
                )},
                "claim_boundary": CLAIM_BOUNDARY,
            })
    require(len({row["candidate_id"] for row in portfolio_rows}) == len(portfolio_rows), "portfolio_candidates_not_unique")

    output_dir.mkdir(parents=True)
    parent_path = output_dir / "v4h_research1320_sequence_structure_parent_summary_v1.tsv"
    disagreement_path = output_dir / "v4h_research1320_sequence_structure_disagreement_tails_v1.tsv"
    portfolio_path = output_dir / "v4h_research1320_sequence_structure_balanced132_v1.tsv"
    write_tsv(parent_path, parent_rows)
    write_tsv(disagreement_path, disagreement_rows)
    write_tsv(portfolio_path, portfolio_rows)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": {"sequence_ranking": expected_sequence_sha256, "structure_ranking": expected_structure_sha256},
        "row_count": expected_rows,
        "parent_count": len(parents),
        "patch_count": len(patches),
        "design_mode_count": len(modes),
        "prediction_pearson": prediction_pearson,
        "prediction_spearman": prediction_spearman,
        "top_overlap": top_overlap,
        "balanced_portfolio": {
            "row_count": len(portfolio_rows),
            "per_parent_patch_mode_stratum": portfolio_per_stratum,
            "roles": dict(sorted(Counter(row["portfolio_role"] for row in portfolio_rows).items())),
            "selection_intent": "diagnostic coverage and future label-free portfolio review, not efficacy ranking",
        },
        "outputs": {
            "parent_summary": {"path": parent_path.name, "sha256": sha256_file(parent_path)},
            "disagreement_tails": {"path": disagreement_path.name, "sha256": sha256_file(disagreement_path)},
            "balanced_portfolio": {"path": portfolio_path.name, "sha256": sha256_file(portfolio_path)},
        },
        "sealed_boundary": {
            "V4_H_docking_result_files_opened": 0,
            "V4_H_status_files_opened": 0,
            "V4_H_pose_files_opened": 0,
            "V4_H_geometry_labels_accessed": 0,
            "V4_F_test32_rows_accessed": 0,
            "formal_or_prospective_authority": False,
        },
    }
    audit_path = output_dir / "v4h_research1320_sequence_structure_comparison_v1.audit.json"
    atomic_write(audit_path, (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "audit_sha256": sha256_file(audit_path),
        "prediction_pearson": prediction_pearson,
        "prediction_spearman": prediction_spearman,
        "balanced_portfolio_rows": len(portfolio_rows),
        "V4_H_geometry_labels_accessed": 0,
        "V4_F_test32_rows_accessed": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "v4h_research1320_sequence_structure_comparison_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "row_count": expected_rows,
        "prediction_pearson": prediction_pearson,
        "prediction_spearman": prediction_spearman,
        "top_overlap": top_overlap,
        "balanced_portfolio_rows": len(portfolio_rows),
        "receipt_sha256": sha256_file(receipt_path),
        "V4_H_geometry_labels_accessed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence-ranking", type=Path, required=True)
    parser.add_argument("--structure-ranking", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = compare(args.sequence_ranking, args.structure_ranking, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
