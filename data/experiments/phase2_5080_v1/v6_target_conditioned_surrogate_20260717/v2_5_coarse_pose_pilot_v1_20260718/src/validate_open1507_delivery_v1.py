#!/usr/bin/env python3
"""Fail-closed validation of the label-free open1507 coarse-pose delivery."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from coarse_pose_features_v1 import sha256_file


def read_tsv(path):
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def unique_map(rows, label):
    output = {}
    for row in rows:
        candidate = row["candidate_id"]
        if candidate in output:
            raise ValueError(f"duplicate {label} candidate: {candidate}")
        output[candidate] = row
    return output


def main(args):
    manifest_path = Path(args.manifest).resolve()
    raw_path = Path(args.raw_features).resolve()
    compact_path = Path(args.compact_features).resolve()
    manifest = unique_map(read_tsv(manifest_path), "manifest")
    raw = unique_map(read_tsv(raw_path), "raw")
    compact = unique_map(read_tsv(compact_path), "compact")
    if len(manifest) != 1507 or set(manifest) != set(raw) or set(manifest) != set(compact):
        raise ValueError("1507 candidate-set closure failed")
    if any("V4F" in candidate.upper() for candidate in manifest):
        raise ValueError("V4-F candidate detected")
    raw_fields = [field for field in next(iter(raw.values())) if "__" in field]
    compact_fields = [
        field for field in next(iter(compact.values())) if field not in {"candidate_id", "feature_schema"}
    ]
    if len(raw_fields) != 36 or len(compact_fields) != 12:
        raise ValueError("feature dimension closure failed")
    raw_values = np.asarray([[float(raw[c][f]) for f in raw_fields] for c in sorted(raw)])
    compact_values = np.asarray([[float(compact[c][f]) for f in compact_fields] for c in sorted(compact)])
    if not np.isfinite(raw_values).all() or not np.isfinite(compact_values).all():
        raise ValueError("non-finite delivery value")
    forbidden = {"R_8X6B", "R_9E6Y", "R_dual_min", "teacher_uncertainty", "sample_weight"}
    if forbidden.intersection(raw_fields) or forbidden.intersection(compact_fields):
        raise ValueError("scalar teacher field present in feature delivery")
    source_counts = Counter(row["structure_source"] for row in manifest.values())
    fold_counts = Counter(row["outer_fold"] for row in manifest.values())
    parent_counts = Counter(row["parent_framework_cluster"] for row in manifest.values())
    receipt = {
        "schema_version": "pvrig_v2_5_open1507_label_free_coarse_pose_delivery_v1",
        "status": "PASS_OPEN1507_LABEL_FREE_COARSE_POSE_DELIVERY",
        "promotion_status": "NOT_EVALUATED_DO_NOT_PROMOTE",
        "candidate_count": len(manifest),
        "parent_count": len(parent_counts),
        "raw_feature_count": len(raw_fields),
        "compact_feature_count": len(compact_fields),
        "all_features_finite": True,
        "structure_source_counts": dict(source_counts),
        "outer_fold_counts": dict(fold_counts),
        "parent_candidate_count_min": min(parent_counts.values()),
        "parent_candidate_count_max": max(parent_counts.values()),
        "sealed_boundary": {
            "candidate_docking_pose_inputs": 0,
            "scalar_teacher_feature_columns": 0,
            "v4_f_or_test32_candidates": 0,
            "performance_metrics_computed": 0,
        },
        "artifacts": {
            "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "raw36d": {"path": str(raw_path), "sha256": sha256_file(raw_path)},
            "symmetric12d": {"path": str(compact_path), "sha256": sha256_file(compact_path)},
            "oof_contract": {
                "path": str(Path(args.oof_contract).resolve()),
                "sha256": sha256_file(Path(args.oof_contract)),
            },
        },
        "remaining_blockers": [
            "No nested whole-parent OOF model has been trained or compared.",
            "PCA8 must remain fold-local and may only be stacked through fold-specific base predictions.",
            "V4-F/test32 remains sealed until a later prediction freeze."
        ],
        "claim_boundary": "Label-free coarse rigid-body feature delivery only; no performance, binding, affinity, experimental blocking, Docking Gold, or promotion claim.",
    }
    Path(args.output_json).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--raw-features", required=True)
    parser.add_argument("--compact-features", required=True)
    parser.add_argument("--oof-contract", required=True)
    parser.add_argument("--output-json", required=True)
    main(parser.parse_args())
