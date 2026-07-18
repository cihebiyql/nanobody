#!/usr/bin/env python3
"""Post-hoc descriptive correlation on open labels; never imported by extractor."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def read_tsv(path):
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def ranks(values):
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    result = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        result[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return result


def spearman(left, right):
    a, b = ranks(left), ranks(right)
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def main(args):
    feature_rows = read_tsv(args.feature_tsv)
    label_rows = {row["candidate_id"]: row for row in read_tsv(args.open_teacher_tsv)}
    joined = [(row, label_rows[row["candidate_id"]]) for row in feature_rows if row["candidate_id"] in label_rows]
    feature_fields = [field for field in feature_rows[0] if "__" in field]
    targets = ["R_8X6B", "R_9E6Y", "R_dual_min"]
    correlations = []
    for feature in feature_fields:
        values = [float(row[feature]) for row, _ in joined]
        for target in targets:
            truth = [float(label[target]) for _, label in joined]
            correlations.append({"feature": feature, "target": target, "spearman": spearman(values, truth)})
    top = {}
    for target in targets:
        target_rows = [row for row in correlations if row["target"] == target]
        top[target] = sorted(target_rows, key=lambda row: abs(row["spearman"]), reverse=True)[:10]
    receipt = {
        "schema_version": "pvrig_v2_5_coarse_pose_open_descriptive_correlation_v1",
        "status": "DESCRIPTIVE_ONLY_DO_NOT_TUNE_OR_PROMOTE",
        "joined_candidate_count": len(joined),
        "selection_used_teacher_labels": False,
        "feature_generation_used_teacher_labels": False,
        "evaluation_opened_teacher_labels_after_feature_freeze": True,
        "top_absolute_spearman": top,
        "claim_boundary": "Small open-panel descriptive correlation only; not cross-validation, generalization evidence, Docking equivalence, binding, affinity, or experimental blocking.",
    }
    Path(args.output_json).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-tsv", required=True)
    parser.add_argument("--open-teacher-tsv", required=True)
    parser.add_argument("--output-json", required=True)
    main(parser.parse_args())
