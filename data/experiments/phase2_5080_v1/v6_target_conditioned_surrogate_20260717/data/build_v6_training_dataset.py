#!/usr/bin/env python3
"""Build the leakage-closed V6 PVRIG docking-geometry training dataset.

This builder intentionally combines only two computational teacher campaigns:

* V4-D OPEN_TRAIN: 226 multi-seed independent 8X6B/9E6Y candidates.
* V4-H Stage 1: 1,281 terminal dual-receptor single-seed candidates.

The 32 OPEN_DEVELOPMENT rows are read only to build parent/sequence exclusion
sets.  Their targets are never emitted.  The 39 technically incomplete V4-H
rows are emitted into a separate label-free table and are never converted to
negative examples.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v6_target_conditioned_training_data_v1"
RECEIPT_SCHEMA_VERSION = f"{SCHEMA_VERSION}_receipt"
FOLD_ALGORITHM = "deterministic_greedy_row_balance_v1"
N_FOLDS = 5
OPEN_TRAIN_WEIGHT = 1.0
STAGE1_WEIGHT = 0.65
CLAIM_BOUNDARY = (
    "Development-only sequence-to-independent-dual-docking computational "
    "geometry supervision; not binding, affinity, competition, experimental "
    "blocking, Docking Gold, formal validation, or final submission authority."
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OPEN_TEACHER = WORKSPACE_ROOT / (
    "experiments/phase2_5080_v1/prepared/"
    "pvrig_v4_d_dev1_open258_v1_2/delivery_dev1_v1_2/by_sha256/"
    "21f00fc17b153dadb2dcd93d90f24a28c4161ccddfe1876c90f0c21ab6a0467d/"
    "outputs/v4d_dev1_open258_continuous_geometry_v1_2.tsv"
)
DEFAULT_STAGE1_RANKING = WORKSPACE_ROOT / (
    "experiments/phase2_5080_v1/prepared/"
    "pvrig_v4_h_stage1_terminal_v1_20260717/stage1_seed917_ranking.tsv"
)
DEFAULT_STAGE1_METADATA = WORKSPACE_ROOT / (
    "experiments/phase2_5080_v1/prepared/"
    "pvrig_v4_h_research_pool_v1/outputs/research_ready1320.tsv"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent

SUPERVISED_FIELDS = [
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "sequence_length",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "campaign",
    "source_dataset",
    "source_release",
    "teacher_type",
    "reliability_weight",
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    "successful_seed_count_8X6B",
    "successful_seed_count_9E6Y",
    "teacher_uncertainty",
    "fold_id",
    "claim_boundary",
]

UNSUPERVISED_FIELDS = [
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "sequence_length",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "campaign",
    "source_dataset",
    "source_release",
    "supervision_state",
    "successful_seed_count_8X6B",
    "successful_seed_count_9E6Y",
    "technical_reasons",
    "fold_id",
    "claim_boundary",
]

FOLD_FIELDS = [
    "schema_version",
    "parent_framework_cluster",
    "fold_id",
    "supervised_candidate_count",
    "campaign",
]


class DataContractError(RuntimeError):
    """Raised when an input violates the frozen data contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise DataContractError(f"missing_input:{path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise DataContractError(f"missing_header:{path}")
        return [dict(row) for row in reader]


def require_fields(rows: Sequence[Mapping[str, str]], fields: Iterable[str], label: str) -> None:
    if not rows:
        raise DataContractError(f"empty_input:{label}")
    missing = sorted(set(fields) - set(rows[0]))
    if missing:
        raise DataContractError(f"missing_fields:{label}:{','.join(missing)}")


def require_unique(rows: Sequence[Mapping[str, str]], key: str, label: str) -> None:
    counts = Counter(row[key] for row in rows)
    duplicates = sorted(value for value, count in counts.items() if count != 1)
    if duplicates:
        raise DataContractError(f"non_unique_{key}:{label}:{duplicates[:5]}")


def finite_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DataContractError(f"invalid_float:{label}:{value!r}") from exc
    if not math.isfinite(parsed):
        raise DataContractError(f"non_finite_float:{label}:{value!r}")
    return parsed


def validate_geometry(row: Mapping[str, str], label: str) -> tuple[float, float, float]:
    r8 = finite_float(row["R_8X6B"], f"{label}:R_8X6B")
    r9 = finite_float(row["R_9E6Y"], f"{label}:R_9E6Y")
    rdual = finite_float(row["R_dual_min"], f"{label}:R_dual_min")
    if abs(rdual - min(r8, r9)) > 1e-8:
        raise DataContractError(
            f"r_dual_min_mismatch:{label}:observed={rdual}:expected={min(r8, r9)}"
        )
    return r8, r9, rdual


def assert_no_overlap(
    supervised_rows: Sequence[Mapping[str, str]],
    excluded_rows: Sequence[Mapping[str, str]],
) -> dict[str, int]:
    """Fail closed on candidate, sequence or parent leakage into development32."""

    metrics: dict[str, int] = {}
    for key in ("candidate_id", "sequence_sha256", "parent_framework_cluster"):
        overlap = {row[key] for row in supervised_rows} & {row[key] for row in excluded_rows}
        metrics[f"{key}_overlap"] = len(overlap)
        if overlap:
            raise DataContractError(f"open_development_overlap:{key}:{sorted(overlap)[:5]}")
    return metrics


def assign_parent_folds(
    supervised_rows: Sequence[Mapping[str, str]], n_folds: int = N_FOLDS
) -> dict[str, int]:
    """Deterministically balance whole parents by supervised row count.

    Parents are ordered by descending row count, then SHA256 of the parent ID.
    Each is placed in the currently lightest fold; fold ID resolves ties.  This
    depends only on the parent/count manifest and is stable across input row
    order and Python hash seeds.
    """

    if n_folds < 2:
        raise DataContractError("n_folds_must_be_at_least_2")
    counts = Counter(row["parent_framework_cluster"] for row in supervised_rows)
    ordered = sorted(
        counts,
        key=lambda parent: (
            -counts[parent],
            hashlib.sha256(parent.encode("utf-8")).hexdigest(),
            parent,
        ),
    )
    fold_loads = [0] * n_folds
    fold_parent_counts = [0] * n_folds
    assignments: dict[str, int] = {}
    for parent in ordered:
        fold_id = min(
            range(n_folds),
            key=lambda fold: (fold_loads[fold], fold_parent_counts[fold], fold),
        )
        assignments[parent] = fold_id
        fold_loads[fold_id] += counts[parent]
        fold_parent_counts[fold_id] += 1
    if len(set(assignments.values())) != n_folds:
        raise DataContractError("not_all_folds_populated")
    return assignments


def write_tsv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def build_dataset(
    open_teacher_path: Path,
    stage1_ranking_path: Path,
    stage1_metadata_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    open_rows = read_tsv(open_teacher_path)
    stage1_rows = read_tsv(stage1_ranking_path)
    metadata_rows = read_tsv(stage1_metadata_path)

    require_fields(
        open_rows,
        [
            "candidate_id",
            "sequence_sha256",
            "sequence",
            "parent_id",
            "parent_framework_cluster",
            "model_split",
            "design_method",
            "design_mode",
            "target_patch_id",
            "R_8X6B",
            "R_9E6Y",
            "R_dual_min",
            "successful_seed_count_8X6B",
            "successful_seed_count_9E6Y",
            "teacher_uncertainty",
        ],
        "open_teacher",
    )
    require_fields(
        stage1_rows,
        [
            "candidate_id",
            "sequence_sha256",
            "parent_framework_cluster",
            "target_patch_id",
            "design_mode",
            "docking_evidence_tier",
            "successful_seed_count_8X6B",
            "successful_seed_count_9E6Y",
            "median_score_8X6B",
            "median_score_9E6Y",
            "R_dual_min",
            "technical_reasons",
            "ranking_release",
        ],
        "stage1_ranking",
    )
    require_fields(
        metadata_rows,
        [
            "candidate_id",
            "sequence_sha256",
            "sequence",
            "sequence_length",
            "parent_id",
            "parent_framework_cluster",
            "target_patch_id",
            "design_mode",
        ],
        "stage1_metadata",
    )
    require_unique(open_rows, "candidate_id", "open_teacher")
    require_unique(stage1_rows, "candidate_id", "stage1_ranking")
    require_unique(metadata_rows, "candidate_id", "stage1_metadata")

    split_counts = Counter(row["model_split"] for row in open_rows)
    if split_counts != {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}:
        raise DataContractError(f"unexpected_open_teacher_splits:{dict(split_counts)}")
    if len(stage1_rows) != 1320 or len(metadata_rows) != 1320:
        raise DataContractError(
            f"unexpected_stage1_counts:ranking={len(stage1_rows)}:metadata={len(metadata_rows)}"
        )

    open_train = [row for row in open_rows if row["model_split"] == "OPEN_TRAIN"]
    open_development = [row for row in open_rows if row["model_split"] == "OPEN_DEVELOPMENT"]
    metadata_by_id = {row["candidate_id"]: row for row in metadata_rows}
    if set(metadata_by_id) != {row["candidate_id"] for row in stage1_rows}:
        raise DataContractError("stage1_ranking_metadata_candidate_set_mismatch")

    supervised: list[dict[str, object]] = []
    incomplete: list[dict[str, object]] = []

    for row in open_train:
        validate_geometry(row, row["candidate_id"])
        sequence = row["sequence"].strip()
        if hashlib.sha256(sequence.encode("utf-8")).hexdigest() != row["sequence_sha256"]:
            raise DataContractError(f"sequence_hash_mismatch:{row['candidate_id']}")
        if int(row["successful_seed_count_8X6B"]) < 2 or int(row["successful_seed_count_9E6Y"]) < 2:
            raise DataContractError(f"open_train_not_multi_seed:{row['candidate_id']}")
        supervised.append(
            {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "sequence": sequence,
                "sequence_length": len(sequence),
                "parent_id": row["parent_id"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "design_method": row["design_method"],
                "design_mode": row["design_mode"],
                "target_patch_id": row["target_patch_id"],
                "campaign": "V4_D_OPEN_TRAIN_MULTI_SEED",
                "source_dataset": "pvrig_v4_d_open_continuous_teacher_v1",
                "source_release": row.get("dev_release_track", "V4-D-DEV1-V1.2"),
                "teacher_type": "DUAL_RECEPTOR_MULTI_SEED",
                "reliability_weight": f"{OPEN_TRAIN_WEIGHT:.2f}",
                "R_8X6B": row["R_8X6B"],
                "R_9E6Y": row["R_9E6Y"],
                "R_dual_min": row["R_dual_min"],
                "successful_seed_count_8X6B": row["successful_seed_count_8X6B"],
                "successful_seed_count_9E6Y": row["successful_seed_count_9E6Y"],
                "teacher_uncertainty": row["teacher_uncertainty"],
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )

    for row in stage1_rows:
        metadata = metadata_by_id[row["candidate_id"]]
        for key in (
            "sequence_sha256",
            "parent_framework_cluster",
            "target_patch_id",
            "design_mode",
        ):
            if row[key] != metadata[key]:
                raise DataContractError(f"stage1_metadata_mismatch:{row['candidate_id']}:{key}")
        sequence = metadata["sequence"].strip()
        if hashlib.sha256(sequence.encode("utf-8")).hexdigest() != row["sequence_sha256"]:
            raise DataContractError(f"sequence_hash_mismatch:{row['candidate_id']}")
        if len(sequence) != int(metadata["sequence_length"]):
            raise DataContractError(f"sequence_length_mismatch:{row['candidate_id']}")
        common = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "sequence": sequence,
            "sequence_length": int(metadata["sequence_length"]),
            "parent_id": metadata["parent_id"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "design_method": "RFantibody_RFdiffusion_ProteinMPNN",
            "design_mode": row["design_mode"],
            "target_patch_id": row["target_patch_id"],
            "campaign": "V4_H_STAGE1_SEED917",
            "source_dataset": "pvrig_v4_h_stage1_terminal_v1_20260717",
            "source_release": row["ranking_release"],
            "successful_seed_count_8X6B": row["successful_seed_count_8X6B"],
            "successful_seed_count_9E6Y": row["successful_seed_count_9E6Y"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        if row["docking_evidence_tier"] == "DUAL_1_SEED":
            geometry = {
                "R_8X6B": row["median_score_8X6B"],
                "R_9E6Y": row["median_score_9E6Y"],
                "R_dual_min": row["R_dual_min"],
            }
            validate_geometry(geometry, row["candidate_id"])
            if int(row["successful_seed_count_8X6B"]) != 1 or int(row["successful_seed_count_9E6Y"]) != 1:
                raise DataContractError(f"stage1_dual_not_exactly_one_seed:{row['candidate_id']}")
            supervised.append(
                {
                    **common,
                    "teacher_type": "DUAL_RECEPTOR_SINGLE_SEED",
                    "reliability_weight": f"{STAGE1_WEIGHT:.2f}",
                    **geometry,
                    "teacher_uncertainty": "",
                }
            )
        elif row["docking_evidence_tier"] == "TECHNICAL_INCOMPLETE":
            if row["R_dual_min"] or not row["technical_reasons"]:
                raise DataContractError(f"invalid_technical_incomplete:{row['candidate_id']}")
            incomplete.append(
                {
                    **common,
                    "supervision_state": "TECHNICALLY_INCOMPLETE_UNSUPERVISED_ONLY",
                    "technical_reasons": row["technical_reasons"],
                }
            )
        else:
            raise DataContractError(
                f"unexpected_stage1_evidence_tier:{row['candidate_id']}:{row['docking_evidence_tier']}"
            )

    if len(supervised) != 1507 or len(incomplete) != 39:
        raise DataContractError(
            f"unexpected_output_counts:supervised={len(supervised)}:incomplete={len(incomplete)}"
        )
    require_unique(supervised, "candidate_id", "supervised")
    require_unique(supervised, "sequence_sha256", "supervised")
    require_unique(incomplete, "candidate_id", "incomplete")
    if {row["candidate_id"] for row in supervised} & {row["candidate_id"] for row in incomplete}:
        raise DataContractError("supervised_incomplete_candidate_overlap")

    overlap_metrics = assert_no_overlap(supervised, open_development)
    parent_count = len({row["parent_framework_cluster"] for row in supervised})
    if parent_count != 31:
        raise DataContractError(f"unexpected_supervised_parent_count:{parent_count}")

    fold_by_parent = assign_parent_folds(supervised)
    for row in supervised:
        row["fold_id"] = fold_by_parent[str(row["parent_framework_cluster"])]
    for row in incomplete:
        row["fold_id"] = fold_by_parent[str(row["parent_framework_cluster"])]

    supervised.sort(key=lambda row: (int(row["fold_id"]), str(row["parent_framework_cluster"]), str(row["candidate_id"])))
    incomplete.sort(key=lambda row: (int(row["fold_id"]), str(row["parent_framework_cluster"]), str(row["candidate_id"])))

    parent_counts = Counter(str(row["parent_framework_cluster"]) for row in supervised)
    campaigns_by_parent: dict[str, set[str]] = defaultdict(set)
    for row in supervised:
        campaigns_by_parent[str(row["parent_framework_cluster"])].add(str(row["campaign"]))
    fold_rows = [
        {
            "schema_version": SCHEMA_VERSION,
            "parent_framework_cluster": parent,
            "fold_id": fold_by_parent[parent],
            "supervised_candidate_count": parent_counts[parent],
            "campaign": ";".join(sorted(campaigns_by_parent[parent])),
        }
        for parent in sorted(fold_by_parent, key=lambda value: (fold_by_parent[value], value))
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    supervised_path = output_dir / "v6_supervised1507.tsv"
    incomplete_path = output_dir / "v6_unsupervised_incomplete39.tsv"
    folds_path = output_dir / "v6_whole_parent_fold_assignments.tsv"
    receipt_path = output_dir / "V6_DATASET_RECEIPT.json"
    write_tsv(supervised_path, supervised, SUPERVISED_FIELDS)
    write_tsv(incomplete_path, incomplete, UNSUPERVISED_FIELDS)
    write_tsv(folds_path, fold_rows, FOLD_FIELDS)

    campaign_counts = Counter(str(row["campaign"]) for row in supervised)
    fold_candidate_counts = Counter(str(row["fold_id"]) for row in supervised)
    fold_parent_counts = Counter(str(row["fold_id"]) for row in fold_rows)
    receipt: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "COMPLETE_LEAKAGE_CLOSED_V6_DATASET",
        "claim_boundary": CLAIM_BOUNDARY,
        "inputs": {
            "open_teacher": {"path": str(open_teacher_path), "sha256": sha256_file(open_teacher_path)},
            "stage1_ranking": {"path": str(stage1_ranking_path), "sha256": sha256_file(stage1_ranking_path)},
            "stage1_metadata": {"path": str(stage1_metadata_path), "sha256": sha256_file(stage1_metadata_path)},
        },
        "counts": {
            "supervised_candidates": len(supervised),
            "supervised_parents": parent_count,
            "open_train_multi_seed": campaign_counts["V4_D_OPEN_TRAIN_MULTI_SEED"],
            "stage1_dual_single_seed": campaign_counts["V4_H_STAGE1_SEED917"],
            "stage1_technical_incomplete_unsupervised": len(incomplete),
            "open_development_exclusion_rows": len(open_development),
            "open_development_exclusion_parents": len(
                {row["parent_framework_cluster"] for row in open_development}
            ),
        },
        "reliability_weights": {
            "V4_D_OPEN_TRAIN_MULTI_SEED": OPEN_TRAIN_WEIGHT,
            "V4_H_STAGE1_SEED917": STAGE1_WEIGHT,
        },
        "open_development_overlap": overlap_metrics,
        "open_development_targets_emitted": 0,
        "technical_incomplete_targets_emitted": 0,
        "folds": {
            "n_folds": N_FOLDS,
            "algorithm": FOLD_ALGORITHM,
            "candidate_counts": dict(sorted(fold_candidate_counts.items())),
            "parent_counts": dict(sorted(fold_parent_counts.items())),
        },
        "outputs": {
            "supervised": {
                "path": str(supervised_path),
                "rows": len(supervised),
                "sha256": sha256_file(supervised_path),
            },
            "incomplete_unsupervised": {
                "path": str(incomplete_path),
                "rows": len(incomplete),
                "sha256": sha256_file(incomplete_path),
            },
            "parent_folds": {
                "path": str(folds_path),
                "rows": len(fold_rows),
                "sha256": sha256_file(folds_path),
            },
        },
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-teacher", type=Path, default=DEFAULT_OPEN_TEACHER)
    parser.add_argument("--stage1-ranking", type=Path, default=DEFAULT_STAGE1_RANKING)
    parser.add_argument("--stage1-metadata", type=Path, default=DEFAULT_STAGE1_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_dataset(
        open_teacher_path=args.open_teacher,
        stage1_ranking_path=args.stage1_ranking,
        stage1_metadata_path=args.stage1_metadata,
        output_dir=args.output_dir,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
