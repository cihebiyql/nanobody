#!/usr/bin/env python3
"""Train dependency-light grouped ridge baselines for the V4-C teacher."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np


SCHEMA_VERSION = "phase2_v4_c_grouped_ridge_baselines_v1"
AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"
AA_INDEX = {aa: index for index, aa in enumerate(AA_ORDER)}
ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)
FOLDS = 5
EXPECTED_OPEN_ROWS = 96
EXPECTED_SPLIT_MANIFEST_SHA256 = "4660260cdf1f863281b12200aeee4b5d58b251ebd3774befae2eace9ca2465fe"
PRIMARY_TARGET = "R_dual_min"
GROUP_NULL_REPLICATES = 100
GROUP_NULL_SEED = 20260715
CLAIM_BOUNDARY = (
    "Development-only fixed-PVRIG computational docking surrogate baseline; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


class BaselineError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise BaselineError("refusing_to_write_empty_predictions")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def validate_sequence(sequence: str) -> str:
    sequence = sequence.strip().upper()
    if not sequence or any(aa not in AA_INDEX for aa in sequence):
        raise BaselineError(f"invalid_standard_amino_acid_sequence:{sequence!r}")
    return sequence


def composition(sequence: str) -> list[float]:
    sequence = validate_sequence(sequence)
    counts = Counter(sequence)
    return [counts.get(aa, 0) / len(sequence) for aa in AA_ORDER]


def physicochemical(sequence: str) -> list[float]:
    sequence = validate_sequence(sequence)
    length = len(sequence)
    sets = (
        set("AILMFWVY"),
        set("FWY"),
        set("KRH"),
        set("DE"),
        set("STNQ"),
        set("GP"),
        set("C"),
    )
    fractions = [sum(aa in group for aa in sequence) / length for group in sets]
    net_charge_proxy = (sum(aa in set("KR") for aa in sequence) - sum(aa in set("DE") for aa in sequence)) / length
    return fractions + [net_charge_proxy]


def hashed_kmers(sequence: str, k_values: Sequence[int], width: int) -> list[float]:
    sequence = validate_sequence(sequence)
    output = np.zeros(width, dtype=np.float64)
    total = 0
    for k in k_values:
        for index in range(max(0, len(sequence) - k + 1)):
            token = sequence[index : index + k].encode("ascii")
            bucket = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % width
            output[bucket] += 1.0
            total += 1
    if total:
        output /= total
    return output.tolist()


def cdr3_features(row: dict[str, str]) -> list[float]:
    cdr3 = validate_sequence(row["cdr3"])
    return [len(cdr3) / 30.0] + composition(cdr3) + physicochemical(cdr3) + hashed_kmers(cdr3, (2, 3), 64)


def full_sequence_features(row: dict[str, str]) -> list[float]:
    sequence = validate_sequence(row["sequence"])
    output = [len(sequence) / 150.0] + composition(sequence) + physicochemical(sequence)
    for field, scale in (("cdr1", 15.0), ("cdr2", 15.0), ("cdr3", 30.0)):
        region = validate_sequence(row[field])
        output.extend([len(region) / scale] + composition(region) + physicochemical(region))
    output.extend(hashed_kmers(sequence, (2, 3), 128))
    return output


def categorical_encoder(train_rows: list[dict[str, str]], fields: Sequence[str]) -> Callable[[dict[str, str]], list[float]]:
    categories = {field: sorted({row[field] for row in train_rows}) for field in fields}

    def encode(row: dict[str, str]) -> list[float]:
        output: list[float] = []
        for field in fields:
            output.extend(float(row[field] == value) for value in categories[field])
        return output

    return encode


def feature_matrices(
    model_name: str,
    train_rows: list[dict[str, str]],
    eval_rows: list[dict[str, str]],
) -> tuple[np.ndarray, np.ndarray]:
    if model_name == "constant":
        return np.zeros((len(train_rows), 0)), np.zeros((len(eval_rows), 0))
    if model_name == "scaffold_only":
        encoder = categorical_encoder(train_rows, ("scaffold_id",))
    elif model_name == "metadata_shortcut":
        encoder = categorical_encoder(
            train_rows, ("scaffold_id", "phase", "selection_bucket", "h3_regime")
        )
    elif model_name == "cdr3_only":
        encoder = cdr3_features
    elif model_name == "full_sequence":
        encoder = full_sequence_features
    elif model_name == "generic_prior_only":
        if any(row.get("generic_binding_prior", "") == "" for row in train_rows + eval_rows):
            raise BaselineError("generic_prior_only_requested_but_column_missing")
        encoder = lambda row: [float(row["generic_binding_prior"])]
    else:
        raise BaselineError(f"unknown_model:{model_name}")
    return (
        np.asarray([encoder(row) for row in train_rows], dtype=np.float64),
        np.asarray([encoder(row) for row in eval_rows], dtype=np.float64),
    )


def grouped_folds(rows: list[dict[str, str]], fold_count: int = FOLDS) -> list[int]:
    groups: dict[str, int] = Counter(row["near_cdr3_family_id"] for row in rows)
    ordered = sorted(
        groups,
        key=lambda group: (
            -groups[group],
            hashlib.sha256(f"20260715:{group}".encode()).hexdigest(),
        ),
    )
    loads = [0] * fold_count
    assignment: dict[str, int] = {}
    for group in ordered:
        fold = min(range(fold_count), key=lambda index: (loads[index], index))
        assignment[group] = fold
        loads[fold] += groups[group]
    return [assignment[row["near_cdr3_family_id"]] for row in rows]


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if x.shape[0] != y.shape[0]:
        raise BaselineError("ridge_row_mismatch")
    if x.shape[1] == 0:
        return np.asarray([float(np.mean(y))]), np.zeros(0), np.ones(0)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x - center) / scale
    design = np.column_stack([np.ones(len(z)), z])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    return coef, center, scale


def predict_ridge(x: np.ndarray, fitted: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    coef, center, scale = fitted
    if x.shape[1] == 0:
        return np.repeat(coef[0], len(x))
    z = (x - center) / scale
    return np.column_stack([np.ones(len(z)), z]) @ coef


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


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    left, right = rankdata(y_true), rankdata(y_pred)
    if np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def ndcg(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    def dcg(order: np.ndarray) -> float:
        return float(
            sum(
                (2.0 ** float(y_true[index]) - 1.0) / math.log2(rank + 2.0)
                for rank, index in enumerate(order)
            )
        )

    predicted = np.argsort(-y_pred, kind="mergesort")
    ideal = np.argsort(-y_true, kind="mergesort")
    denominator = dcg(ideal)
    return dcg(predicted) / denominator if denominator > 0.0 else 0.0


def top_quartile_recall(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    count = max(1, math.ceil(len(y_true) * 0.25))
    true_top = set(np.argsort(-y_true, kind="mergesort")[:count].tolist())
    predicted_top = set(np.argsort(-y_pred, kind="mergesort")[:count].tolist())
    return len(true_top & predicted_top) / len(true_top)


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "spearman": round(spearman(y_true, y_pred), 9),
        "ndcg": round(ndcg(y_true, y_pred), 9),
        "top_quartile_recall_at_25pct_budget": round(top_quartile_recall(y_true, y_pred), 9),
        "mae": round(float(np.mean(np.abs(y_true - y_pred))), 9),
    }


def cross_validated_predictions(
    rows: list[dict[str, str]],
    y: np.ndarray,
    model_name: str,
    alpha: float,
    folds: list[int],
) -> np.ndarray:
    output = np.zeros(len(rows), dtype=np.float64)
    for fold in sorted(set(folds)):
        train_indices = [index for index, value in enumerate(folds) if value != fold]
        eval_indices = [index for index, value in enumerate(folds) if value == fold]
        train_rows = [rows[index] for index in train_indices]
        eval_rows = [rows[index] for index in eval_indices]
        x_train, x_eval = feature_matrices(model_name, train_rows, eval_rows)
        fitted = fit_ridge(x_train, y[train_indices], alpha)
        output[eval_indices] = predict_ridge(x_eval, fitted)
    return output


def select_alpha(
    rows: list[dict[str, str]], y: np.ndarray, model_name: str, folds: list[int]
) -> tuple[float, np.ndarray, dict[str, float]]:
    if model_name == "constant":
        prediction = cross_validated_predictions(rows, y, model_name, 0.0, folds)
        return 0.0, prediction, metrics(y, prediction)
    candidates = []
    for alpha in ALPHAS:
        prediction = cross_validated_predictions(rows, y, model_name, alpha, folds)
        score = metrics(y, prediction)
        key = (
            score["spearman"] + score["ndcg"] + score["top_quartile_recall_at_25pct_budget"],
            score["spearman"],
            -alpha,
        )
        candidates.append((key, alpha, prediction, score))
    _key, alpha, prediction, score = max(candidates, key=lambda item: item[0])
    return alpha, prediction, score


def nested_grouped_predictions(
    rows: list[dict[str, str]],
    y: np.ndarray,
    model_name: str,
    outer_folds: list[int],
) -> tuple[np.ndarray, list[float]]:
    output = np.zeros(len(rows), dtype=np.float64)
    selected_alphas: list[float] = []
    for outer in sorted(set(outer_folds)):
        train_indices = [index for index, value in enumerate(outer_folds) if value != outer]
        eval_indices = [index for index, value in enumerate(outer_folds) if value == outer]
        train_rows = [rows[index] for index in train_indices]
        eval_rows = [rows[index] for index in eval_indices]
        train_y = y[train_indices]
        inner_fold_count = min(4, len({row["near_cdr3_family_id"] for row in train_rows}))
        inner_folds = grouped_folds(train_rows, inner_fold_count)
        alpha, _inner_prediction, _inner_metrics = select_alpha(
            train_rows, train_y, model_name, inner_folds
        )
        x_train, x_eval = feature_matrices(model_name, train_rows, eval_rows)
        output[eval_indices] = predict_ridge(x_eval, fit_ridge(x_train, train_y, alpha))
        selected_alphas.append(float(alpha))
    return output, selected_alphas


def group_permuted_target(
    rows: list[dict[str, str]], y: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(row["near_cdr3_family_id"], []).append(index)
    names = sorted(groups)
    means = {name: float(np.mean(y[groups[name]])) for name in names}
    permuted_names = names.copy()
    rng.shuffle(permuted_names)
    mapping = {name: means[source] for name, source in zip(names, permuted_names)}
    output = y.copy()
    for name, indices in groups.items():
        residuals = y[indices] - means[name]
        output[indices] = mapping[name] + residuals
    return output


def group_null_distribution(
    rows: list[dict[str, str]],
    y: np.ndarray,
    folds: list[int],
    alpha: float,
) -> dict[str, Any]:
    rng = np.random.default_rng(GROUP_NULL_SEED)
    values = []
    for _replicate in range(GROUP_NULL_REPLICATES):
        shuffled = group_permuted_target(rows, y, rng)
        prediction = cross_validated_predictions(rows, shuffled, "full_sequence", alpha, folds)
        values.append(spearman(y, prediction))
    array = np.asarray(values, dtype=np.float64)
    return {
        "replicates": GROUP_NULL_REPLICATES,
        "seed": GROUP_NULL_SEED,
        "permutation_unit": "near_cdr3_family_mean_within_family_residual_preserved",
        "spearman_mean": round(float(np.mean(array)), 9),
        "spearman_95th_percentile": round(float(np.quantile(array, 0.95)), 9),
        "spearman_max": round(float(np.max(array)), 9),
    }


def validate_teacher(rows: list[dict[str, str]], target: str) -> np.ndarray:
    if len(rows) != EXPECTED_OPEN_ROWS:
        raise BaselineError(f"expected_{EXPECTED_OPEN_ROWS}_open_rows_got_{len(rows)}")
    if any(row.get("model_split") != "OPEN_DEVELOPMENT" for row in rows):
        raise BaselineError("trainer_received_non_open_row")
    if len({row["candidate_id"] for row in rows}) != len(rows):
        raise BaselineError("duplicate_candidate_id")
    try:
        y = np.asarray([float(row[target]) for row in rows], dtype=np.float64)
    except (KeyError, ValueError) as exc:
        raise BaselineError(f"invalid_target:{target}") from exc
    if not np.all(np.isfinite(y)):
        raise BaselineError("non_finite_target")
    return y


def validate_teacher_binding(
    teacher_path: Path,
    audit_path: Path,
    split_manifest_path: Path,
    teacher_rows: list[dict[str, str]],
) -> dict[str, Any]:
    if sha256_file(split_manifest_path) != EXPECTED_SPLIT_MANIFEST_SHA256:
        raise BaselineError("split_manifest_sha256_mismatch")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS_V4_C_CONTINUOUS_TEACHER_RELEASE":
        raise BaselineError("teacher_audit_status_not_pass")
    if audit.get("release") != "open_development_only":
        raise BaselineError("teacher_audit_not_open_development")
    if audit.get("inputs", {}).get("split_manifest_sha256") != EXPECTED_SPLIT_MANIFEST_SHA256:
        raise BaselineError("teacher_audit_split_binding_mismatch")
    if audit.get("output", {}).get("sha256") != sha256_file(teacher_path):
        raise BaselineError("teacher_file_not_bound_to_audit")
    split_rows = read_tsv(split_manifest_path)
    expected_ids = {
        row["candidate_id"] for row in split_rows if row["model_split"] == "OPEN_DEVELOPMENT"
    }
    actual_ids = {row["candidate_id"] for row in teacher_rows}
    if actual_ids != expected_ids or len(actual_ids) != EXPECTED_OPEN_ROWS:
        raise BaselineError("teacher_candidate_ids_do_not_match_frozen_open_split")
    return audit


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-audit", type=Path)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_c/dual128_split_manifest.tsv",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--target", default=PRIMARY_TARGET)
    args = parser.parse_args(argv)

    rows = read_tsv(args.teacher)
    teacher_audit_path = args.teacher_audit or args.teacher.with_suffix(args.teacher.suffix + ".audit.json")
    validate_teacher_binding(
        args.teacher,
        teacher_audit_path,
        args.split_manifest,
        rows,
    )
    y = validate_teacher(rows, args.target)
    folds = grouped_folds(rows)
    model_names = ["constant", "scaffold_only", "metadata_shortcut", "cdr3_only", "full_sequence"]
    if all(row.get("generic_binding_prior", "") != "" for row in rows):
        model_names.append("generic_prior_only")
    results: dict[str, Any] = {}
    prediction_rows = [
        {
            "candidate_id": row["candidate_id"],
            "near_cdr3_family_id": row["near_cdr3_family_id"],
            "fold": folds[index],
            "target": round(float(y[index]), 9),
        }
        for index, row in enumerate(rows)
    ]
    for model_name in model_names:
        alpha, tuned_prediction, tuned_score = select_alpha(rows, y, model_name, folds)
        nested_prediction, outer_alphas = nested_grouped_predictions(
            rows, y, model_name, folds
        )
        nested_score = metrics(y, nested_prediction)
        results[model_name] = {
            "full_open_tuning_alpha": alpha,
            "tuned_grouped_cv_metrics": tuned_score,
            "nested_grouped_cv_metrics": nested_score,
            "nested_outer_selected_alphas": outer_alphas,
        }
        for index, value in enumerate(nested_prediction):
            prediction_rows[index][f"prediction_{model_name}"] = round(float(value), 9)

    null_alpha = float(results["full_sequence"]["full_open_tuning_alpha"])
    results["label_shuffle_null"] = {
        "alpha": null_alpha,
        "distribution": group_null_distribution(rows, y, folds, null_alpha),
    }

    eligible_models = [name for name in results if name != "label_shuffle_null"]
    strongest = max(
        eligible_models,
        key=lambda name: (
            results[name]["nested_grouped_cv_metrics"]["spearman"],
            results[name]["nested_grouped_cv_metrics"]["ndcg"],
            name,
        ),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = args.out_dir / "open_grouped_cv_predictions.tsv"
    summary_path = args.out_dir / "baseline_summary.json"
    write_tsv(prediction_path, prediction_rows)
    write_json(
        summary_path,
        {
            "schema_version": SCHEMA_VERSION,
            "status": "DEVELOPMENT_ONLY_RETROSPECTIVE_CHALLENGE_NOT_READ",
            "teacher": {"path": str(args.teacher), "sha256": sha256_file(args.teacher), "rows": len(rows)},
            "target": args.target,
            "group_unit": "near_cdr3_family_id",
            "fold_count": FOLDS,
            "fold_row_counts": dict(sorted(Counter(folds).items())),
            "alphas": list(ALPHAS),
            "models": results,
            "strongest_non_shortcut_open_baseline": strongest,
            "retrospective_challenge_read": False,
            "deployment_eligible": False,
            "predictions": {"path": str(prediction_path), "sha256": sha256_file(prediction_path)},
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS_OPEN_DEVELOPMENT_BASELINES",
                "strongest": strongest,
                "summary": str(summary_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
