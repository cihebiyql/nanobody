#!/usr/bin/env python3
"""Build the provenance-closed V6 candidate-level training tables."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "pvrig_v6_training_table_v1"
CLAIM = (
    "Candidate-level computational dual-receptor Docking geometry supervision; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(path: Path, delimiter: str = "\t") -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def parent_fold(parent: str, folds: int = 5) -> int:
    digest = hashlib.sha256(f"PVRIG_V6|{parent}".encode()).hexdigest()
    return int(digest[:8], 16) % folds


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def feature_columns(row: dict[str, str]) -> list[str]:
    excluded = {
        "schema_version", "candidate_id", "sequence_sha256", "model_split",
        "parent_framework_cluster", "target_patch_id", "design_mode",
        "monomer_sha256", "claim_boundary",
    }
    return [name for name in row if name not in excluded]


def materialize(args: argparse.Namespace) -> dict[str, object]:
    open_rows = read_rows(args.open_teacher)
    stage_rows = read_rows(args.stage1)
    sequence_rows = read_rows(args.v4h_sequences, ",")
    design_rows = read_rows(args.v4h_designs)
    open_struct_rows = read_rows(args.open_structures)
    stage_struct_rows = read_rows(args.v4h_structures)

    sequence_by_hash = {row["sequence_sha256"]: row["sequence"] for row in sequence_rows}
    design_by_candidate = {row["candidate_id"]: row for row in design_rows}
    open_struct = {row["candidate_id"]: row for row in open_struct_rows}
    stage_struct = {row["candidate_id"]: row for row in stage_struct_rows}
    require(len(sequence_by_hash) == len(sequence_rows), "duplicate_v4h_sequence_hash")
    require(len(design_by_candidate) == len(design_rows), "duplicate_v4h_design_candidate")
    require(len(open_struct) == len(open_struct_rows), "duplicate_open_structure_candidate")
    require(len(stage_struct) == len(stage_struct_rows), "duplicate_stage_structure_candidate")

    open_feature_names = feature_columns(open_struct_rows[0])
    stage_feature_names = feature_columns(stage_struct_rows[0])
    require(open_feature_names == stage_feature_names, "structure_feature_schema_mismatch")
    require(len(open_feature_names) == 126, f"unexpected_structure_feature_count:{len(open_feature_names)}")

    supervised: list[dict[str, object]] = []
    open_development: list[dict[str, object]] = []
    incomplete: list[dict[str, object]] = []

    def add_open(row: dict[str, str], target: list[dict[str, object]], weight: float) -> None:
        srow = open_struct.get(row["candidate_id"])
        require(srow is not None, f"missing_open_structure:{row['candidate_id']}")
        sequence = row["sequence"].strip().upper()
        require(sequence_hash(sequence) == row["sequence_sha256"], f"open_sequence_hash_mismatch:{row['candidate_id']}")
        item: dict[str, object] = {
            "schema_version": SCHEMA,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "sequence": sequence,
            "parent_framework_cluster": row["parent_framework_cluster"],
            "target_patch_id": row["target_patch_id"],
            "design_mode": row["design_mode"],
            "cdr1": row["cdr1"],
            "cdr2": row["cdr2"],
            "cdr3": row["cdr3"],
            "teacher_source": "V4D_OPEN_MULTI_SEED",
            "teacher_reliability": "MULTI_SEED",
            "sample_weight": weight,
            "outer_fold": parent_fold(row["parent_framework_cluster"]),
            "R_8X6B": float(row["R_8X6B"]),
            "R_9E6Y": float(row["R_9E6Y"]),
            "R_dual_min": float(row["R_dual_min"]),
            "teacher_uncertainty": float(row.get("teacher_uncertainty") or 0.0),
            "monomer_sha256": srow["monomer_sha256"],
            "claim_boundary": CLAIM,
        }
        for name in open_feature_names:
            value = float(srow[name])
            require(math.isfinite(value), f"nonfinite_open_feature:{row['candidate_id']}:{name}")
            item[name] = value
        target.append(item)

    for row in open_rows:
        if row["model_split"] == "OPEN_TRAIN":
            add_open(row, supervised, 1.0)
        elif row["model_split"] == "OPEN_DEVELOPMENT":
            add_open(row, open_development, 1.0)

    for row in stage_rows:
        srow = stage_struct.get(row["candidate_id"])
        drow = design_by_candidate.get(row["candidate_id"])
        require(srow is not None, f"missing_stage_structure:{row['candidate_id']}")
        require(drow is not None, f"missing_stage_design:{row['candidate_id']}")
        sequence = sequence_by_hash.get(row["sequence_sha256"])
        require(sequence is not None, f"missing_stage_sequence:{row['candidate_id']}")
        require(sequence_hash(sequence) == row["sequence_sha256"], f"stage_sequence_hash_mismatch:{row['candidate_id']}")
        base: dict[str, object] = {
            "schema_version": SCHEMA,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "sequence": sequence,
            "parent_framework_cluster": row["parent_framework_cluster"],
            "target_patch_id": row["target_patch_id"],
            "design_mode": row["design_mode"],
            "cdr1": drow["cdr1_after"],
            "cdr2": drow["cdr2_after"],
            "cdr3": drow["cdr3_after"],
            "teacher_source": "V4H_STAGE1_SEED917",
            "teacher_reliability": row["docking_evidence_tier"],
            "sample_weight": 0.65 if row["R_dual_min"] else 0.0,
            "outer_fold": parent_fold(row["parent_framework_cluster"]),
            "R_8X6B": float(row["median_score_8X6B"]) if row["R_dual_min"] else "",
            "R_9E6Y": float(row["median_score_9E6Y"]) if row["R_dual_min"] else "",
            "R_dual_min": float(row["R_dual_min"]) if row["R_dual_min"] else "",
            "teacher_uncertainty": "",
            "monomer_sha256": srow["monomer_sha256"],
            "technical_reasons": row["technical_reasons"],
            "claim_boundary": CLAIM,
        }
        for name in open_feature_names:
            value = float(srow[name])
            require(math.isfinite(value), f"nonfinite_stage_feature:{row['candidate_id']}:{name}")
            base[name] = value
        (supervised if row["R_dual_min"] else incomplete).append(base)

    require(len(supervised) == 1507, f"supervised_count:{len(supervised)}")
    require(len(open_development) == 32, f"open_development_count:{len(open_development)}")
    require(len(incomplete) == 39, f"incomplete_count:{len(incomplete)}")
    require(len({row["candidate_id"] for row in supervised}) == len(supervised), "duplicate_supervised_candidate")
    require(len({row["sequence_sha256"] for row in supervised}) == len(supervised), "duplicate_supervised_sequence")
    train_parents = {str(row["parent_framework_cluster"]) for row in supervised}
    dev_parents = {str(row["parent_framework_cluster"]) for row in open_development}
    train_sequences = {str(row["sequence_sha256"]) for row in supervised}
    dev_sequences = {str(row["sequence_sha256"]) for row in open_development}
    require(len(train_parents) == 31, f"train_parent_count:{len(train_parents)}")
    require(len(dev_parents) == 3, f"dev_parent_count:{len(dev_parents)}")
    require(not train_parents.intersection(dev_parents), "train_dev_parent_overlap")
    require(not train_sequences.intersection(dev_sequences), "train_dev_sequence_overlap")

    metadata = [
        "schema_version", "candidate_id", "sequence_sha256", "sequence",
        "parent_framework_cluster", "target_patch_id", "design_mode",
        "cdr1", "cdr2", "cdr3",
        "teacher_source", "teacher_reliability", "sample_weight", "outer_fold",
        "R_8X6B", "R_9E6Y", "R_dual_min", "teacher_uncertainty",
        "monomer_sha256", "technical_reasons", "claim_boundary",
    ]
    fields = metadata + open_feature_names
    outputs = {
        "supervised": args.output_dir / "v6_supervised1507.tsv",
        "open_development": args.output_dir / "v6_open_development32.tsv",
        "incomplete": args.output_dir / "v6_unsupervised_incomplete39.tsv",
        "folds": args.output_dir / "v6_parent_folds.tsv",
    }
    write_rows(outputs["supervised"], sorted(supervised, key=lambda r: str(r["candidate_id"])), fields)
    write_rows(outputs["open_development"], sorted(open_development, key=lambda r: str(r["candidate_id"])), fields)
    write_rows(outputs["incomplete"], sorted(incomplete, key=lambda r: str(r["candidate_id"])), fields)
    fold_rows = [
        {"parent_framework_cluster": parent, "outer_fold": parent_fold(parent)}
        for parent in sorted(train_parents)
    ]
    write_rows(outputs["folds"], fold_rows, ["parent_framework_cluster", "outer_fold"])
    receipt = {
        "schema_version": "pvrig_v6_training_table_receipt_v1",
        "status": "PASS_V6_TRAINING_TABLE_MATERIALIZED",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "counts": {
            "supervised": len(supervised),
            "open_development": len(open_development),
            "technical_incomplete": len(incomplete),
            "train_parent_clusters": len(train_parents),
            "open_development_parent_clusters": len(dev_parents),
            "structure_features": len(open_feature_names),
        },
        "sample_weights": {"V4D_OPEN_MULTI_SEED": 1.0, "V4H_STAGE1_SEED917": 0.65},
        "input_sha256": {
            "open_teacher": sha256_file(args.open_teacher),
            "stage1": sha256_file(args.stage1),
            "v4h_sequences": sha256_file(args.v4h_sequences),
            "v4h_designs": sha256_file(args.v4h_designs),
            "open_structures": sha256_file(args.open_structures),
            "v4h_structures": sha256_file(args.v4h_structures),
        },
        "output_sha256": {name: sha256_file(path) for name, path in outputs.items()},
        "claim_boundary": CLAIM,
    }
    receipt_path = args.output_dir / "v6_training_table_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--open-teacher", type=Path, required=True)
    p.add_argument("--stage1", type=Path, required=True)
    p.add_argument("--v4h-sequences", type=Path, required=True)
    p.add_argument("--v4h-designs", type=Path, required=True)
    p.add_argument("--open-structures", type=Path, required=True)
    p.add_argument("--v4h-structures", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    return p


if __name__ == "__main__":
    ns = parser().parse_args()
    print(json.dumps(materialize(ns), indent=2, sort_keys=True))
