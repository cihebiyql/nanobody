#!/usr/bin/env python3
"""Exploratory V4-E analysis for the real patch and design-mode axes.

The analysis fits one high-score threshold on OPEN_TRAIN and evaluates it on
the parent-disjoint OPEN_DEVELOPMENT set.  It is retrospective and can never
authorize generation by itself.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


EXPECTED_SPLITS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_AXES = {
    "target_patch_id": {"A_CENTER", "B_LOWER", "C_CROSS"},
    "design_mode": {"H1H3", "H3"},
}
PRIMARY_SCORE = "R_dual_min"
TRAIN_QUANTILE = 0.75


class AnalysisError(RuntimeError):
    """Raised when the frozen teacher violates the analysis contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {key: "" if value is None else value for key, value in row.items()}
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def nearest_rank_quantile(values: list[float], quantile: float) -> float:
    if not values or not 0.0 < quantile <= 1.0:
        raise AnalysisError("invalid_nearest_rank_quantile_input")
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def risk_ratio(target_rate: float, comparator_rate: float) -> float | str:
    if comparator_rate == 0.0:
        return "Infinity" if target_rate > 0.0 else 0.0
    return target_rate / comparator_rate


def fisher_greater(a: int, b: int, c: int, d: int) -> float:
    row1 = a + b
    col1 = a + c
    total = a + b + c + d
    if total == 0:
        return 1.0
    denominator = math.comb(total, row1)
    upper = min(row1, col1)
    return min(
        1.0,
        sum(
            math.comb(col1, x) * math.comb(total - col1, row1 - x) / denominator
            for x in range(a, upper + 1)
        ),
    )


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    output: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (name, p_value) in enumerate(ordered):
        running = max(running, min(1.0, p_value * (total - index)))
        output[name] = running
    return output


def mean_score(rows: list[dict[str, Any]]) -> float:
    return statistics.mean(row["_score"] for row in rows)


def validate_and_prepare(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    if len(rows) != 258:
        raise AnalysisError(f"teacher_row_count_not_258:{len(rows)}")
    ids = [row.get("candidate_id", "") for row in rows]
    hashes = [row.get("sequence_sha256", "") for row in rows]
    if "" in ids or len(ids) != len(set(ids)):
        raise AnalysisError("candidate_id_missing_or_duplicate")
    if "" in hashes or len(hashes) != len(set(hashes)):
        raise AnalysisError("sequence_sha256_missing_or_duplicate")
    split_counts = Counter(row.get("model_split", "") for row in rows)
    if dict(split_counts) != EXPECTED_SPLITS:
        raise AnalysisError(f"split_counts_mismatch:{dict(split_counts)}")
    for axis, expected in EXPECTED_AXES.items():
        observed = {row.get(axis, "") for row in rows}
        if observed != expected:
            raise AnalysisError(f"axis_levels_mismatch:{axis}:{sorted(observed)}")

    prepared: list[dict[str, Any]] = []
    for row in rows:
        try:
            score = float(row.get(PRIMARY_SCORE, ""))
        except ValueError as exc:
            raise AnalysisError(f"invalid_primary_score:{row.get('candidate_id', '')}") from exc
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise AnalysisError(f"primary_score_out_of_range:{row.get('candidate_id', '')}:{score}")
        if not row.get("parent_id"):
            raise AnalysisError(f"parent_id_missing:{row.get('candidate_id', '')}")
        prepared.append({**row, "_score": score})

    train_parents = {row["parent_id"] for row in prepared if row["model_split"] == "OPEN_TRAIN"}
    development_parents = {
        row["parent_id"] for row in prepared if row["model_split"] == "OPEN_DEVELOPMENT"
    }
    overlap = sorted(train_parents & development_parents)
    if overlap:
        raise AnalysisError(f"train_development_parent_overlap:{len(overlap)}")
    return prepared


def group_result(
    *,
    axis: str,
    level: str,
    train: list[dict[str, Any]],
    development: list[dict[str, Any]],
    high_threshold: float,
) -> dict[str, Any]:
    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        target = [row for row in rows if row[axis] == level]
        comparator = [row for row in rows if row[axis] != level]
        target_high = sum(row["_score"] >= high_threshold for row in target)
        comparator_high = sum(row["_score"] >= high_threshold for row in comparator)
        target_rate = rate(target_high, len(target))
        comparator_rate = rate(comparator_high, len(comparator))
        return {
            "target_n": len(target),
            "target_high_n": target_high,
            "target_high_rate": target_rate,
            "target_score_mean": mean_score(target),
            "target_score_median": statistics.median(row["_score"] for row in target),
            "comparator_n": len(comparator),
            "comparator_high_n": comparator_high,
            "comparator_high_rate": comparator_rate,
            "comparator_score_mean": mean_score(comparator),
            "comparator_score_median": statistics.median(row["_score"] for row in comparator),
            "risk_difference": target_rate - comparator_rate,
            "risk_ratio": risk_ratio(target_rate, comparator_rate),
            "mean_score_difference": mean_score(target) - mean_score(comparator),
            "fisher_exact_p_greater": fisher_greater(
                target_high,
                len(target) - target_high,
                comparator_high,
                len(comparator) - comparator_high,
            ),
        }

    train_summary = summarize(train)
    development_summary = summarize(development)
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in development:
        by_parent[row["parent_id"]].append(row)
    parent_effects = []
    for parent_id, parent_rows in sorted(by_parent.items()):
        target = [row for row in parent_rows if row[axis] == level]
        comparator = [row for row in parent_rows if row[axis] != level]
        if not target or not comparator:
            continue
        parent_effects.append(
            {
                "parent_id": parent_id,
                "target_n": len(target),
                "comparator_n": len(comparator),
                "mean_score_difference": mean_score(target) - mean_score(comparator),
            }
        )
    positive_parent_effects = sum(row["mean_score_difference"] > 0.0 for row in parent_effects)
    return {
        "axis": axis,
        "level": level,
        "train": train_summary,
        "development": development_summary,
        "development_parent_effects": parent_effects,
        "development_independent_parent_count": len(parent_effects),
        "development_positive_parent_effect_fraction": rate(positive_parent_effects, len(parent_effects)),
        "direction_consistent_train_to_development": (
            train_summary["risk_difference"] > 0.0
            and development_summary["risk_difference"] > 0.0
        ),
    }


def analyze(teacher: Path) -> dict[str, Any]:
    if not teacher.is_file():
        raise AnalysisError(f"teacher_missing:{teacher}")
    rows = validate_and_prepare(read_tsv(teacher))
    train = [row for row in rows if row["model_split"] == "OPEN_TRAIN"]
    development = [row for row in rows if row["model_split"] == "OPEN_DEVELOPMENT"]
    high_threshold = nearest_rank_quantile([row["_score"] for row in train], TRAIN_QUANTILE)
    development_descriptive_threshold = nearest_rank_quantile(
        [row["_score"] for row in development], TRAIN_QUANTILE
    )

    results = [
        group_result(
            axis=axis,
            level=level,
            train=train,
            development=development,
            high_threshold=high_threshold,
        )
        for axis, levels in EXPECTED_AXES.items()
        for level in sorted(levels)
    ]
    p_values = {
        f"{row['axis']}={row['level']}": row["development"]["fisher_exact_p_greater"]
        for row in results
    }
    adjusted = holm_adjust(p_values)
    thresholds = {
        "minimum_development_candidates": 8,
        "minimum_independent_development_parents": 5,
        "minimum_development_high_rate": 0.20,
        "minimum_risk_difference": 0.10,
        "minimum_risk_ratio": 1.50,
        "maximum_holm_adjusted_p": 0.10,
    }
    candidate_level_signals = []
    for row in results:
        name = f"{row['axis']}={row['level']}"
        row["holm_adjusted_p"] = adjusted[name]
        rr = row["development"]["risk_ratio"]
        rr_numeric = math.inf if rr == "Infinity" else float(rr)
        row["exploratory_candidate_level_signal"] = (
            row["development"]["target_n"] >= thresholds["minimum_development_candidates"]
            and row["development"]["target_high_rate"] >= thresholds["minimum_development_high_rate"]
            and row["development"]["risk_difference"] >= thresholds["minimum_risk_difference"]
            and rr_numeric >= thresholds["minimum_risk_ratio"]
            and row["holm_adjusted_p"] <= thresholds["maximum_holm_adjusted_p"]
            and row["direction_consistent_train_to_development"]
        )
        row["independent_parent_gate_pass"] = (
            row["development_independent_parent_count"]
            >= thresholds["minimum_independent_development_parents"]
        )
        if row["exploratory_candidate_level_signal"]:
            candidate_level_signals.append(name)

    train_high = sum(row["_score"] >= high_threshold for row in train)
    development_high = sum(row["_score"] >= high_threshold for row in development)
    return {
        "schema_version": "pvrig_v4e_design_axis_exploratory_enrichment_v1",
        "status": "PASS_EXPLORATORY_ANALYSIS_NO_GENERATION_RELEASE",
        "formal_gate_status": "NOT_APPLICABLE_RETROSPECTIVE_DISTINCT_AXIS",
        "generation_authorized": False,
        "primary_score": PRIMARY_SCORE,
        "threshold_fitting": {
            "split": "OPEN_TRAIN",
            "method": "nearest_rank_quantile",
            "quantile": TRAIN_QUANTILE,
            "absolute_high_score_threshold": high_threshold,
        },
        "distribution_shift": {
            "train_n": len(train),
            "train_parent_count": len({row["parent_id"] for row in train}),
            "train_score_mean": mean_score(train),
            "train_score_median": statistics.median(row["_score"] for row in train),
            "train_high_n": train_high,
            "train_high_rate": rate(train_high, len(train)),
            "development_n": len(development),
            "development_parent_count": len({row["parent_id"] for row in development}),
            "development_score_mean": mean_score(development),
            "development_score_median": statistics.median(row["_score"] for row in development),
            "development_high_n_at_train_threshold": development_high,
            "development_high_rate_at_train_threshold": rate(development_high, len(development)),
            "development_descriptive_q75_threshold_not_used_for_gate": development_descriptive_threshold,
        },
        "thresholds": thresholds,
        "candidate_level_signals": candidate_level_signals,
        "results": results,
        "limitations": [
            "retrospective_research_teacher_after_original_v4d_failure",
            "open_development_contains_only_3_independent_parent_scaffolds",
            "train_fitted_absolute_high_score_threshold_has_low_transfer_to_open_development",
            "patch_and_design_mode_are_not_p2_p3_p4_phase_labels",
            "sealed_test32_not_opened_or_used",
        ],
        "source": {"path": str(teacher.resolve()), "sha256": sha256_file(teacher)},
        "claim_boundary": (
            "Exploratory computational docking-geometry factor analysis only; not binding, "
            "affinity, competition, experimental blocking, or a prospective generation gate."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = analyze(args.teacher)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "candidate_level_signals": payload["candidate_level_signals"],
        "generation_authorized": payload["generation_authorized"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
