#!/usr/bin/env python3
"""Open-development diagnostics for residual capacity and label shortcuts.

This script is deliberately descriptive.  It consumes only open OOF predictions
and the open 1,507-candidate teacher table.  It does not fit a promotable model
and it never reads sealed V4-F artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np


SCHEMA = "pvrig_v2_4_prearchitecture_limits_diagnostic_v1"


class DiagnosticError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"empty_tsv:{path}")
    return rows


def metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    require(truth.shape == prediction.shape and truth.ndim == 1, "metric_shape")
    difference = prediction - truth
    correlation = spearman(truth, prediction)
    return {
        "mae": float(np.mean(np.abs(difference))),
        "rmse": float(np.sqrt(np.mean(np.square(difference)))),
        "spearman": correlation,
    }


def average_ranks(values: np.ndarray) -> np.ndarray:
    """Return one-based average ranks with deterministic tie handling."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * ((start + 1) + end)
        start = end
    return ranks


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    require(left.shape == right.shape and left.ndim == 1 and len(left) >= 2, "spearman_shape")
    left_rank = average_ranks(left)
    right_rank = average_ranks(right)
    left_centered = left_rank - np.mean(left_rank)
    right_centered = right_rank - np.mean(right_rank)
    denominator = float(np.sqrt(np.square(left_centered).sum() * np.square(right_centered).sum()))
    require(denominator > 0, "spearman_zero_variance")
    return float(np.dot(left_centered, right_centered) / denominator)


def oracle_clipped_residual(
    rows: Sequence[Mapping[str, str]], caps: Iterable[float]
) -> dict[str, object]:
    outputs: dict[str, object] = {}
    truth_by_receptor = {
        "R8": np.asarray([float(row["truth_R8"]) for row in rows]),
        "R9": np.asarray([float(row["truth_R9"]) for row in rows]),
    }
    base_by_receptor = {
        "R8": np.asarray([float(row["M2_R8"]) for row in rows]),
        "R9": np.asarray([float(row["M2_R9"]) for row in rows]),
    }
    for cap in caps:
        require(cap > 0 and math.isfinite(cap), "cap_invalid")
        receptor_predictions: dict[str, np.ndarray] = {}
        receptor_outputs: dict[str, object] = {}
        for receptor in ("R8", "R9"):
            truth = truth_by_receptor[receptor]
            base = base_by_receptor[receptor]
            required = truth - base
            prediction = base + np.clip(required, -cap, cap)
            receptor_predictions[receptor] = prediction
            receptor_outputs[receptor] = {
                "required_residual_abs_gt_cap_fraction": float(np.mean(np.abs(required) > cap)),
                "required_residual_abs_q50": float(np.quantile(np.abs(required), 0.50)),
                "required_residual_abs_q90": float(np.quantile(np.abs(required), 0.90)),
                "required_residual_abs_q95": float(np.quantile(np.abs(required), 0.95)),
                "oracle_metrics": metrics(truth, prediction),
            }
        dual_truth = np.minimum(truth_by_receptor["R8"], truth_by_receptor["R9"])
        dual_prediction = np.minimum(receptor_predictions["R8"], receptor_predictions["R9"])
        outputs[f"cap_{cap:.3f}"] = {
            "cap": cap,
            "receptors": receptor_outputs,
            "derived_exact_min_dual_metrics": metrics(dual_truth, dual_prediction),
        }
    return outputs


def group_eta_squared(rows: Sequence[Mapping[str, str]], label: str, fields: Sequence[str]) -> float:
    values = np.asarray([float(row[label]) for row in rows], dtype=float)
    grand_mean = float(np.mean(values))
    total = float(np.square(values - grand_mean).sum())
    require(total > 0, f"zero_variance:{label}")
    groups: dict[tuple[str, ...], list[float]] = defaultdict(list)
    for row, value in zip(rows, values):
        groups[tuple(row[field] for field in fields)].append(float(value))
    between = sum(len(group) * (float(np.mean(group)) - grand_mean) ** 2 for group in groups.values())
    return float(between / total)


def variance_shortcut_summary(rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    groupings = {
        "parent": ("parent_framework_cluster",),
        "target_patch": ("target_patch_id",),
        "design_mode": ("design_mode",),
        "parent_patch_mode": ("parent_framework_cluster", "target_patch_id", "design_mode"),
    }
    outputs: dict[str, object] = {}
    for label in ("R_8X6B", "R_9E6Y", "R_dual_min"):
        outputs[label] = {
            name: {
                "descriptive_eta_squared": group_eta_squared(rows, label, fields),
                "group_count": len({tuple(row[field] for field in fields) for row in rows}),
            }
            for name, fields in groupings.items()
        }
    return outputs


def reliability_summary(rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    by_tier: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get("teacher_uncertainty", "")
        if value != "":
            by_tier[row["development_reliability_tier"]].append(float(value))
    result: dict[str, object] = {}
    for tier, values in sorted(by_tier.items()):
        array = np.asarray(values, dtype=float)
        result[tier] = {
            "rows": len(values),
            "uncertainty_mean": float(np.mean(array)),
            "uncertainty_q50": float(np.quantile(array, 0.50)),
            "uncertainty_q90": float(np.quantile(array, 0.90)),
        }
    return result


def build_diagnostic(
    teacher_table: Path, prediction_paths: Sequence[Path], caps: Sequence[float]
) -> dict[str, object]:
    teacher_rows = read_tsv(teacher_table)
    prediction_rows: list[dict[str, str]] = []
    for path in prediction_paths:
        prediction_rows.extend(read_tsv(path))
    candidate_ids = [row["candidate_id"] for row in prediction_rows]
    require(len(candidate_ids) == len(set(candidate_ids)), "duplicate_prediction_candidate")
    require(len(prediction_rows) == len(teacher_rows), "prediction_teacher_row_count")
    require(set(candidate_ids) == {row["candidate_id"] for row in teacher_rows}, "candidate_closure")
    require(all(row.get("lane") == "A_VHH_ONLY" for row in prediction_rows), "prediction_lane_not_A")
    return {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_PREARCHITECTURE_DIAGNOSTICS",
        "claim_boundary": (
            "Descriptive open-development computational Docking geometry diagnostics only; "
            "not model performance, binding, affinity, experimental blocking, or Docking Gold."
        ),
        "rows": len(teacher_rows),
        "parents": len({row["parent_framework_cluster"] for row in teacher_rows}),
        "inputs": {
            "teacher_table": {"path": str(teacher_table), "sha256": sha256_file(teacher_table)},
            "prediction_files": [
                {"path": str(path), "sha256": sha256_file(path)} for path in prediction_paths
            ],
            "sealed_v4_f_access_count": 0,
        },
        "oracle_clipped_m2_residual": oracle_clipped_residual(prediction_rows, caps),
        "descriptive_variance_shortcuts": variance_shortcut_summary(teacher_rows),
        "teacher_uncertainty_by_tier": reliability_summary(teacher_rows),
        "limitations": [
            "Oracle residual uses truth and is a capacity upper bound, not a trainable result.",
            "Eta-squared values are descriptive and non-causal for the unbalanced campaign design.",
            "Teacher uncertainty summaries are not an ICC or a formal noise ceiling; raw per-seed scores are required.",
            "V2.4 neural lanes are direct orthogonal predictors, so old residual-head saturation is not applicable to them.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher-table", type=Path, required=True)
    parser.add_argument("--prediction-tsv", type=Path, nargs="+", required=True)
    parser.add_argument("--caps", type=float, nargs="+", default=(0.02, 0.03, 0.05))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_diagnostic(args.teacher_table, args.prediction_tsv, args.caps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    require(not args.output.exists(), f"output_exists:{args.output}")
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": payload["status"], "rows": payload["rows"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
