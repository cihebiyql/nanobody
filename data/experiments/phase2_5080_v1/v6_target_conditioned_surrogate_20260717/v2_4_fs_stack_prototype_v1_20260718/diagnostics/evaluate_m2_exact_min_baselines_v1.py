#!/usr/bin/env python3
"""Evaluate leakage-free M2 Ridge baselines for V2.4 open development.

The script never reads neural predictions or sealed evaluation data.  It fits
whole-parent outer-fold Ridge models on the 126 label-free monomer features,
predicts R8/R9, and derives the production-compatible dual score by exact min.
An independently fitted third output is reported only as a non-promotable
diagnostic of the consistency constraint's cost.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import spearmanr


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


def read_rows(path: Path) -> list[dict[str, str]]:
    require(path.is_file() and not path.is_symlink(), f"input_missing_or_symlink:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(len(rows) > 0, "input_empty")
    required = {
        "candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold",
        "R_8X6B", "R_9E6Y", "R_dual_min", "sample_weight",
        "development_reliability_weight",
    }
    require(required <= set(rows[0]), f"missing_columns:{sorted(required-set(rows[0]))}")
    require(len({row["candidate_id"] for row in rows}) == len(rows), "duplicate_candidate")
    for row in rows:
        r8, r9, dual = map(float, (row["R_8X6B"], row["R_9E6Y"], row["R_dual_min"]))
        require(all(math.isfinite(value) for value in (r8, r9, dual)), "nonfinite_target")
        require(np.float64(dual).tobytes() == np.minimum(np.float64(r8), np.float64(r9)).tobytes(), "truth_not_exact_min")
    return rows


def hierarchical_weights(
    rows: Sequence[Mapping[str, str]], indices: np.ndarray, *, reliability: bool,
) -> np.ndarray:
    """0.5/source -> equal parent -> equal or reliability-proportional candidate."""
    weights = np.zeros(len(indices), dtype=np.float64)
    sources = sorted({rows[index]["teacher_source"] for index in indices})
    require(len(sources) == 2, "expected_two_sources")
    for source in sources:
        parents = sorted({
            rows[index]["parent_framework_cluster"]
            for index in indices if rows[index]["teacher_source"] == source
        })
        for parent in parents:
            local = [
                offset for offset, index in enumerate(indices)
                if rows[index]["teacher_source"] == source
                and rows[index]["parent_framework_cluster"] == parent
            ]
            raw = np.asarray([
                float(rows[indices[offset]]["development_reliability_weight"])
                if reliability else 1.0
                for offset in local
            ], dtype=np.float64)
            require(bool(np.all(np.isfinite(raw) & (raw > 0))), "invalid_reliability")
            raw /= raw.sum()
            weights[local] = (0.5 / len(parents)) * raw
    require(np.isclose(weights.sum(), 1.0, atol=1e-14, rtol=0.0), "hierarchical_weight_sum")
    return weights


def fit_ridge(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> tuple[np.ndarray, ...]:
    require(x.ndim == 2 and y.ndim == 2 and len(x) == len(y) == len(weights), "ridge_shape")
    require(alpha > 0 and bool(np.all(weights > 0)), "ridge_weight_or_alpha")
    normalized = weights / weights.sum()
    x_mean = np.sum(x * normalized[:, None], axis=0)
    x_scale = np.sqrt(np.sum((x - x_mean) ** 2 * normalized[:, None], axis=0))
    x_scale[x_scale < 1e-8] = 1.0
    y_mean = np.sum(y * normalized[:, None], axis=0)
    standardized = (x - x_mean) / x_scale
    root = np.sqrt(weights)[:, None]
    coefficient = np.linalg.solve(
        (standardized * root).T @ (standardized * root) + alpha * np.eye(x.shape[1]),
        (standardized * root).T @ ((y - y_mean) * root),
    )
    return x_mean, x_scale, y_mean, coefficient


def metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    return {
        "spearman": float(spearmanr(truth, prediction).statistic),
        "mae": float(np.mean(np.abs(truth - prediction))),
        "rmse": float(np.sqrt(np.mean((truth - prediction) ** 2))),
    }


def evaluate(rows: Sequence[Mapping[str, str]], *, alpha: float = 10.0) -> dict[str, Any]:
    features = [column for column in rows[0] if "__" in column]
    require(len(features) == 126, f"structure_feature_count:{len(features)}")
    x = np.asarray([[float(row[column]) for column in features] for row in rows], dtype=np.float64)
    direct = np.asarray([[float(row["R_8X6B"]), float(row["R_9E6Y"])] for row in rows], dtype=np.float64)
    truth = np.column_stack((direct, np.minimum(direct[:, 0], direct[:, 1])))
    folds = np.asarray([int(row["outer_fold"]) for row in rows], dtype=int)
    require(set(folds.tolist()) == set(range(5)), "outer_fold_closure")

    variants: dict[str, Any] = {}
    for weight_name, reliability in (("hierarchical_equal", False), ("hierarchical_fixed_tier", True)):
        for output_count in (2, 3):
            target = direct if output_count == 2 else truth
            prediction = np.full_like(target, np.nan)
            fold_audit: dict[str, Any] = {}
            for fold in range(5):
                train = np.where(folds != fold)[0]
                score = np.where(folds == fold)[0]
                train_parents = {rows[index]["parent_framework_cluster"] for index in train}
                score_parents = {rows[index]["parent_framework_cluster"] for index in score}
                require(train_parents.isdisjoint(score_parents), f"parent_leakage:{fold}")
                weights = hierarchical_weights(rows, train, reliability=reliability)
                x_mean, x_scale, y_mean, coefficient = fit_ridge(x[train], target[train], weights, alpha)
                prediction[score] = (x[score] - x_mean) / x_scale @ coefficient + y_mean
                fold_audit[str(fold)] = {
                    "train_candidates": len(train), "score_candidates": len(score),
                    "train_parents": len(train_parents), "score_parents": len(score_parents),
                }
            require(bool(np.all(np.isfinite(prediction))), "prediction_nonfinite")
            if output_count == 2:
                reported = np.column_stack((prediction, np.minimum(prediction[:, 0], prediction[:, 1])))
                output_contract = "direct_R8_R9_then_exact_min"
                promotable = True
            else:
                reported = prediction
                output_contract = "independent_third_dual_diagnostic_only"
                promotable = False
            variants[f"{weight_name}__outputs_{output_count}"] = {
                "promotable_architecture": promotable,
                "output_contract": output_contract,
                "R8": metrics(truth[:, 0], reported[:, 0]),
                "R9": metrics(truth[:, 1], reported[:, 1]),
                "Rdual": metrics(truth[:, 2], reported[:, 2]),
                "folds": fold_audit,
            }
    return {
        "schema_version": "pvrig_v2_4_m2_exact_min_baseline_diagnostic_v1",
        "status": "PASS_OPEN_DEVELOPMENT_M2_BASELINES",
        "claim_boundary": "Open computational Docking geometry development evidence only; no sealed V4-F access.",
        "rows": len(rows),
        "parents": len({row["parent_framework_cluster"] for row in rows}),
        "structure_features": len(features),
        "ridge_alpha": alpha,
        "primary_variant": "hierarchical_equal__outputs_2",
        "variants": variants,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-tsv", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--alpha", type=float, default=10.0)
    args = parser.parse_args()
    require(not args.output_json.exists(), f"output_exists:{args.output_json}")
    report = evaluate(read_rows(args.input_tsv), alpha=args.alpha)
    report["input"] = {"path": str(args.input_tsv.resolve()), "sha256": sha256_file(args.input_tsv)}
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
