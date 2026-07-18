#!/usr/bin/env python3
"""Audit the V4-H Stage-1 to adaptive multi-seed scalar-label update."""

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


SCHEMA_VERSION = "pvrig_v2_4_adaptive_scalar_update_diagnostic_v1"
V4H_SOURCE = "V4H_STAGE1_SEED917"
TIERS = ("DUAL_3_SEED", "DUAL_2_SEED", "DUAL_1_SEED")
TARGETS = (
    ("R_8X6B", "median_score_8X6B"),
    ("R_9E6Y", "median_score_9E6Y"),
    ("R_dual_min", "R_dual_min"),
)
CLAIM_BOUNDARY = (
    "Development diagnostic for computational dual-receptor Docking geometry labels; "
    "not binding, affinity, experimental blocking, Docking Gold, or submission evidence."
)


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
    require(path.is_file() and not path.is_symlink(), f"input_missing_or_symlink:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"empty_tsv:{path}")
    return rows


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


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    require(left.shape == right.shape and left.ndim == 1 and len(left) >= 2, "spearman_shape")
    left_rank, right_rank = rankdata(left), rankdata(right)
    if np.std(left_rank) < 1e-12 or np.std(right_rank) < 1e-12:
        return 0.0
    return float(np.corrcoef(left_rank, right_rank)[0, 1])


def top_fraction_overlap(left: np.ndarray, right: np.ndarray, fraction: float) -> dict[str, float | int]:
    require(0.0 < fraction < 1.0 and len(left) == len(right), "top_fraction_invalid")
    count = max(1, int(math.ceil(len(left) * fraction)))
    left_top = set(np.argsort(-left, kind="mergesort")[:count].tolist())
    right_top = set(np.argsort(-right, kind="mergesort")[:count].tolist())
    intersection = len(left_top & right_top)
    union = len(left_top | right_top)
    return {
        "budget": count,
        "retained": intersection,
        "recall": intersection / count,
        "jaccard": intersection / union,
    }


def summarize(old: np.ndarray, new: np.ndarray) -> dict[str, Any]:
    require(old.shape == new.shape and len(old) > 0, "summary_shape")
    delta = new - old
    absolute = np.abs(delta)
    return {
        "rows": len(old),
        "changed_rows_at_1e_12": int(np.sum(absolute > 1e-12)),
        "mean_signed_delta": float(np.mean(delta)),
        "mean_absolute_delta": float(np.mean(absolute)),
        "median_absolute_delta": float(np.median(absolute)),
        "q90_absolute_delta": float(np.quantile(absolute, 0.90)),
        "q95_absolute_delta": float(np.quantile(absolute, 0.95)),
        "max_absolute_delta": float(np.max(absolute)),
        "spearman_stage1_vs_adaptive": spearman(old, new) if len(old) >= 2 else None,
        "top20_overlap": top_fraction_overlap(old, new, 0.20) if len(old) >= 2 else None,
    }


def build_report(training_rows: Sequence[Mapping[str, str]], adaptive_rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    require(len(training_rows) == 1507, f"training_count:{len(training_rows)}")
    require(len(adaptive_rows) == 1320, f"adaptive_count:{len(adaptive_rows)}")
    adaptive_by_id = {row["candidate_id"]: row for row in adaptive_rows}
    require(len(adaptive_by_id) == len(adaptive_rows), "adaptive_candidate_duplicate")
    v4h = [row for row in training_rows if row["teacher_source"] == V4H_SOURCE]
    require(len(v4h) == 1281, f"v4h_training_count:{len(v4h)}")
    require(all(row["candidate_id"] in adaptive_by_id for row in v4h), "v4h_adaptive_join_missing")
    selected = [(row, adaptive_by_id[row["candidate_id"]]) for row in v4h]
    observed_tiers = Counter(new["docking_evidence_tier"] for _old, new in selected)
    require(observed_tiers == Counter({"DUAL_3_SEED": 123, "DUAL_2_SEED": 241, "DUAL_1_SEED": 917}), f"tier_counts:{dict(observed_tiers)}")

    per_target: dict[str, Any] = {}
    for old_name, new_name in TARGETS:
        old = np.asarray([float(row[old_name]) for row, _new in selected], dtype=np.float64)
        new = np.asarray([float(adaptive[new_name]) for _row, adaptive in selected], dtype=np.float64)
        require(bool(np.all(np.isfinite(old))) and bool(np.all(np.isfinite(new))), f"target_nonfinite:{old_name}")
        per_tier = {}
        for tier in TIERS:
            indices = [index for index, (_row, adaptive) in enumerate(selected) if adaptive["docking_evidence_tier"] == tier]
            per_tier[tier] = summarize(old[indices], new[indices])
        per_target[old_name] = {"all": summarize(old, new), "by_tier": per_tier}

    exact_min_failures = 0
    for _old, adaptive in selected:
        expected = min(float(adaptive["median_score_8X6B"]), float(adaptive["median_score_9E6Y"]))
        exact_min_failures += abs(expected - float(adaptive["R_dual_min"])) > 1e-12
    require(exact_min_failures == 0, f"adaptive_exact_min_failures:{exact_min_failures}")

    dispersion: dict[str, Any] = {}
    for tier in TIERS:
        values = np.asarray([
            float(adaptive["seed_dispersion_max"])
            for _old, adaptive in selected
            if adaptive["docking_evidence_tier"] == tier
        ], dtype=np.float64)
        dispersion[tier] = {
            "rows": len(values),
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "q90": float(np.quantile(values, 0.90)),
            "max": float(np.max(values)),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V4H_ADAPTIVE_SCALAR_UPDATE_DIAGNOSTIC",
        "counts": {
            "training_rows": len(training_rows),
            "v4h_analyzable_rows": len(v4h),
            "adaptive_terminal_rows": len(adaptive_rows),
            "tiers": dict(observed_tiers),
        },
        "targets": per_target,
        "seed_dispersion_max_by_tier": dispersion,
        "adaptive_exact_min_failures": exact_min_failures,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-tsv", type=Path, required=True)
    parser.add_argument("--adaptive-ranking-tsv", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.output_json.exists() and not args.output_json.is_symlink(), "output_exists")
    report = build_report(read_tsv(args.training_tsv), read_tsv(args.adaptive_ranking_tsv))
    report["input_sha256"] = {
        "training_tsv": sha256_file(args.training_tsv),
        "adaptive_ranking_tsv": sha256_file(args.adaptive_ranking_tsv),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "output": str(args.output_json)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
