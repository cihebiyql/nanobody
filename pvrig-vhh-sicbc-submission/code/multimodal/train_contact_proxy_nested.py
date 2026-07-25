#!/usr/bin/env python3
"""Evaluate leakage-safe docking-contact bottlenecks on OPEN_TRAIN226."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import run_v5_tb_open_train as v5  # noqa: E402


SCHEMA_VERSION = "pvrig_v5_rc_contact_proxy_nested_v1"
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only development comparison of label-free monomer/sequence proxies "
    "for computational docking contact intermediates and R_dual_min; not binding, "
    "affinity, competition, experimental blocking, Docking Gold, or submission authority."
)
MODELS = (
    "C0_structure_linear",
    "C1_structure_physchem_random_relu",
    "C2_predicted_contact_bottleneck",
    "C3_structure_plus_predicted_contact_stack",
    "C4_structure_nonlinear_plus_predicted_contact_stack",
)
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
RANDOM_SEEDS = (101, 211, 307)
UNITS_PER_SEED = 128
OUTER_FOLDS = 5
INNER_FOLDS = 5
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = 20260717
CONTACT_BASES = (
    "pair_contact_mass",
    "pvrig_soft_coverage",
    "pvrig_hard50_coverage",
    "full_hotspot_soft_coverage",
    "anchor_hotspot_soft_coverage",
    "holdout_hotspot_soft_coverage",
    "off_interface_soft_coverage",
    "interface_specificity",
    "cdr1_contact_mass",
    "cdr2_contact_mass",
    "cdr3_contact_mass",
    "framework_contact_mass",
    "cdr1_contact_fraction",
    "cdr2_contact_fraction",
    "cdr3_contact_fraction",
    "framework_contact_fraction",
    "pvrig_profile_entropy",
    "mean_pair_seed_std",
    "robust_pair_count",
    "observed_union_pair_count",
)


class ContactProxyError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactProxyError(message)


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


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def contact_feature_names(fields: Sequence[str]) -> list[str]:
    expected = []
    for receptor in ("8x6b", "9e6y"):
        expected.extend(f"{receptor}_{base}" for base in CONTACT_BASES)
    for summary in ("dual_mean", "dual_min", "dual_abs_gap"):
        expected.extend(f"{summary}_{base}" for base in CONTACT_BASES)
    expected.append("dual_pvrig_profile_jsd")
    missing = sorted(set(expected) - set(fields))
    require(not missing, f"contact_features_missing:{','.join(missing[:5])}")
    return expected


@dataclass(frozen=True)
class MultiRidge:
    x_center: np.ndarray
    x_scale: np.ndarray
    y_center: np.ndarray
    y_scale: np.ndarray
    coefficient: np.ndarray


def fit_multi_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> MultiRidge:
    require(x.ndim == 2 and y.ndim == 2 and len(x) == len(y), "multi_ridge_shape_invalid")
    require(np.isfinite(x).all() and np.isfinite(y).all(), "multi_ridge_nonfinite")
    x_center = x.mean(axis=0)
    x_scale = x.std(axis=0)
    x_scale[x_scale < 1e-12] = 1.0
    y_center = y.mean(axis=0)
    y_scale = y.std(axis=0)
    y_scale[y_scale < 1e-12] = 1.0
    xz = (x - x_center) / x_scale
    yz = (y - y_center) / y_scale
    if xz.shape[1] > len(xz):
        kernel = xz @ xz.T
        dual = np.linalg.solve(kernel + float(alpha) * np.eye(len(xz)), yz)
        coefficient = xz.T @ dual
    else:
        coefficient = np.linalg.solve(xz.T @ xz + float(alpha) * np.eye(xz.shape[1]), xz.T @ yz)
    return MultiRidge(x_center, x_scale, y_center, y_scale, coefficient)


def predict_multi_ridge(x: np.ndarray, fitted: MultiRidge) -> np.ndarray:
    prediction = ((x - fitted.x_center) / fitted.x_scale) @ fitted.coefficient
    prediction = prediction * fitted.y_scale + fitted.y_center
    require(np.isfinite(prediction).all(), "multi_ridge_prediction_nonfinite")
    return prediction


@dataclass(frozen=True)
class RandomReluMap:
    center: np.ndarray
    scale: np.ndarray
    weights: tuple[np.ndarray, ...]
    biases: tuple[np.ndarray, ...]


def fit_random_relu_map(x: np.ndarray) -> RandomReluMap:
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    weights = []
    biases = []
    for seed in RANDOM_SEEDS:
        rng = np.random.default_rng(seed)
        weights.append(rng.normal(0.0, 1.0 / math.sqrt(x.shape[1]), size=(x.shape[1], UNITS_PER_SEED)))
        biases.append(rng.normal(0.0, 0.1, size=(UNITS_PER_SEED,)))
    return RandomReluMap(center, scale, tuple(weights), tuple(biases))


def transform_random_relu(x: np.ndarray, mapping: RandomReluMap) -> np.ndarray:
    standardized = (x - mapping.center) / mapping.scale
    nonlinear = [np.maximum(standardized @ weight + bias, 0.0) for weight, bias in zip(mapping.weights, mapping.biases)]
    output = np.concatenate([standardized, *nonlinear], axis=1)
    require(np.isfinite(output).all(), "random_relu_nonfinite")
    return output


def nonlinear_crossfit(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
    alpha: float,
) -> np.ndarray:
    output_shape = (len(x),) if y.ndim == 1 else y.shape
    output = np.empty(output_shape, dtype=np.float64)
    for held in v5.v4.build_group_folds(groups, INNER_FOLDS):
        keep = np.ones(len(x), dtype=bool)
        keep[held] = False
        mapping = fit_random_relu_map(x[keep])
        train = transform_random_relu(x[keep], mapping)
        test = transform_random_relu(x[held], mapping)
        if y.ndim == 1:
            fitted = v5.v4.fit_ridge(train, y[keep], alpha)
            output[held] = v5.v4.predict_ridge(test, fitted)
        else:
            output[held] = predict_multi_ridge(test, fit_multi_ridge(train, y[keep], alpha))
    return output


def select_nonlinear_alpha(
    x: np.ndarray,
    y: np.ndarray,
    groups: Sequence[str],
) -> tuple[float, np.ndarray, dict[str, Any]]:
    candidates = []
    grid = {}
    for alpha in ALPHAS:
        prediction = nonlinear_crossfit(x, y, groups, alpha)
        if y.ndim == 1:
            metric = v5.extended_metrics(y, prediction, groups)
            key = v5.selection_key(metric, alpha)
        else:
            scale = y.std(axis=0)
            scale[scale < 1e-12] = 1.0
            standardized_mse = float(np.mean(((y - prediction) / scale) ** 2))
            per_feature_spearman = [
                float(v5.v4.base.spearman(y[:, index], prediction[:, index]))
                for index in range(y.shape[1]) if np.std(y[:, index]) >= 1e-12
            ]
            metric = {
                "standardized_mse": standardized_mse,
                "median_feature_spearman": float(np.median(per_feature_spearman)),
                "mean_feature_spearman": float(np.mean(per_feature_spearman)),
            }
            key = (-standardized_mse, metric["median_feature_spearman"], float(alpha))
        grid[str(alpha)] = metric
        candidates.append((key, alpha, prediction))
    _key, selected, prediction = max(candidates, key=lambda item: item[0])
    return float(selected), prediction, grid


def fit_predict_nonlinear(
    train_x: np.ndarray,
    train_y: np.ndarray,
    held_x: np.ndarray,
    alpha: float,
) -> np.ndarray:
    mapping = fit_random_relu_map(train_x)
    transformed_train = transform_random_relu(train_x, mapping)
    transformed_held = transform_random_relu(held_x, mapping)
    if train_y.ndim == 1:
        return v5.v4.predict_ridge(transformed_held, v5.v4.fit_ridge(transformed_train, train_y, alpha))
    return predict_multi_ridge(transformed_held, fit_multi_ridge(transformed_train, train_y, alpha))


def nested_evaluate(
    dataset: v5.Dataset,
    contact_y: np.ndarray,
) -> tuple[dict[str, np.ndarray], np.ndarray, list[dict[str, Any]], np.ndarray]:
    predictions = {model: np.empty(len(dataset.ydual), dtype=np.float64) for model in MODELS}
    contact_predictions = np.empty_like(contact_y)
    outer_fold = np.full(len(dataset.ydual), -1, dtype=np.int64)
    audit: list[dict[str, Any]] = []
    combined_x = np.concatenate([dataset.structure_x, dataset.physchem_x], axis=1)
    for fold_index, held in enumerate(v5.v4.build_group_folds(dataset.groups, OUTER_FOLDS)):
        keep = np.ones(len(dataset.ydual), dtype=bool)
        keep[held] = False
        train_groups = [dataset.groups[index] for index in np.flatnonzero(keep)]
        y_train = dataset.ydual[keep]
        structure_train = dataset.structure_x[keep]
        combined_train = combined_x[keep]

        linear_alpha, linear_oof, linear_grid = v5.v4.select_alpha_oof(
            structure_train, y_train, train_groups, ALPHAS, INNER_FOLDS
        )
        nonlinear_alpha, nonlinear_oof, nonlinear_grid = select_nonlinear_alpha(
            combined_train, y_train, train_groups
        )
        contact_alpha, contact_oof, contact_grid = select_nonlinear_alpha(
            combined_train, contact_y[keep], train_groups
        )

        linear_held = v5.v4.predict_ridge(
            dataset.structure_x[held], v5.v4.fit_ridge(structure_train, y_train, linear_alpha)
        )
        nonlinear_held = fit_predict_nonlinear(
            combined_train, y_train, combined_x[held], nonlinear_alpha
        )
        contact_held = fit_predict_nonlinear(
            combined_train, contact_y[keep], combined_x[held], contact_alpha
        )
        contact_predictions[held] = contact_held

        meta_inputs = {
            "C2_predicted_contact_bottleneck": (contact_oof, contact_held),
            "C3_structure_plus_predicted_contact_stack": (
                np.column_stack([linear_oof, contact_oof]),
                np.column_stack([linear_held, contact_held]),
            ),
            "C4_structure_nonlinear_plus_predicted_contact_stack": (
                np.column_stack([linear_oof, nonlinear_oof, contact_oof]),
                np.column_stack([linear_held, nonlinear_held, contact_held]),
            ),
        }
        meta_audit = {}
        predictions["C0_structure_linear"][held] = linear_held
        predictions["C1_structure_physchem_random_relu"][held] = nonlinear_held
        for model, (meta_train, meta_held) in meta_inputs.items():
            alpha, _meta_oof, grid = v5.v4.select_alpha_oof(
                meta_train, y_train, train_groups, ALPHAS, INNER_FOLDS
            )
            predictions[model][held] = v5.v4.predict_ridge(
                meta_held, v5.v4.fit_ridge(meta_train, y_train, alpha)
            )
            meta_audit[model] = {"alpha": alpha, "grid": grid}
        outer_fold[held] = fold_index
        audit.append({
            "fold": fold_index,
            "held_rows": len(held),
            "held_parent_clusters": sorted({dataset.groups[index] for index in held}),
            "selected_alphas": {
                "linear": linear_alpha,
                "nonlinear": nonlinear_alpha,
                "contact_proxy": contact_alpha,
            },
            "linear_grid": linear_grid,
            "nonlinear_grid": nonlinear_grid,
            "contact_grid": contact_grid,
            "meta": meta_audit,
        })
    require(np.all(outer_fold >= 0), "outer_fold_incomplete")
    require(all(np.isfinite(value).all() for value in predictions.values()), "model_predictions_nonfinite")
    require(np.isfinite(contact_predictions).all(), "contact_predictions_nonfinite")
    return predictions, outer_fold, audit, contact_predictions


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# V5-RC OPEN_TRAIN226 Contact-Proxy 嵌套验证结果",
        "",
        f"状态：`{summary['status']}`",
        "",
        "## 证据边界",
        "",
        CLAIM_BOUNDARY,
        "",
        "held-out candidate 的真实 Docking contact 从未作为模型输入；它只在 outer-fold 预测固定后用于 contact-proxy 诊断。",
        "",
        "## 主结果",
        "",
        "| 模型 | Spearman | Parent-centered | Macro-parent | MAE | Top20 recall |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        metric = summary["nested_oof_metrics"][model]
        lines.append(
            f"| {model} | {metric['spearman']:.4f} | {metric['parent_centered_spearman']:.4f} | "
            f"{metric['per_parent_macro_mean_spearman']:.4f} | {metric['mae']:.5f} | "
            f"{metric['top20_percent_recall']:.4f} |"
        )
    lines.extend([
        "",
        "## Contact proxy 可预测性",
        "",
        f"- contact target 数：{summary['contact_proxy_metrics']['target_count']}",
        f"- target-wise Spearman 中位数：{summary['contact_proxy_metrics']['median_target_spearman']:.4f}",
        f"- target-wise Spearman 均值：{summary['contact_proxy_metrics']['mean_target_spearman']:.4f}",
        f"- standardized MSE：{summary['contact_proxy_metrics']['standardized_mse']:.4f}",
        "",
        "## 决策",
        "",
        f"`{summary['development_gate_result']}`",
        "",
        "只有同时超过 C0，并且相对同容量 C1 仍有优势，才能把增益归因于 contact supervision。",
        "",
    ])
    return "\n".join(lines)


def run(
    teacher: Path,
    structure: Path,
    contacts: Path,
    contract: Path,
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    dataset = v5.load_dataset(teacher, structure)
    contact_fields, contact_rows = load_tsv(contacts)
    require(len(contact_rows) == 226, f"contact_row_count_invalid:{len(contact_rows)}")
    require(len({row["candidate_id"] for row in contact_rows}) == 226, "contact_candidate_not_unique")
    names = contact_feature_names(contact_fields)
    contact_by_id = {row["candidate_id"]: row for row in contact_rows}
    contact_values = []
    for row in dataset.rows:
        contact = contact_by_id.get(row["candidate_id"])
        require(contact is not None, f"contact_candidate_missing:{row['candidate_id']}")
        require(contact["sequence_sha256"] == row["sequence_sha256"], f"contact_sequence_mismatch:{row['candidate_id']}")
        require(contact["parent_framework_cluster"] == row["parent_framework_cluster"], f"contact_parent_mismatch:{row['candidate_id']}")
        contact_values.append([float(contact[name]) for name in names])
    contact_y = np.asarray(contact_values, dtype=np.float64)
    require(contact_y.shape == (226, 101), f"contact_matrix_shape_invalid:{contact_y.shape}")
    require(np.isfinite(contact_y).all(), "contact_matrix_nonfinite")
    predictions, outer_fold, outer_audit, contact_predictions = nested_evaluate(dataset, contact_y)
    metrics = {model: v5.extended_metrics(dataset.ydual, prediction, dataset.groups) for model, prediction in predictions.items()}
    reference = metrics["C0_structure_linear"]
    bootstrap = {
        model: v5.v4.paired_group_bootstrap_delta(
            dataset.ydual, predictions[model], predictions["C0_structure_linear"], dataset.groups,
            replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED,
        )
        for model in MODELS if model != "C0_structure_linear"
    }
    contact_scale = contact_y.std(axis=0)
    contact_scale[contact_scale < 1e-12] = 1.0
    target_spearman = [
        float(v5.v4.base.spearman(contact_y[:, index], contact_predictions[:, index]))
        for index in range(contact_y.shape[1]) if np.std(contact_y[:, index]) >= 1e-12
    ]
    contact_metrics = {
        "target_count": len(names),
        "nonconstant_target_count": len(target_spearman),
        "median_target_spearman": float(np.median(target_spearman)),
        "mean_target_spearman": float(np.mean(target_spearman)),
        "standardized_mse": float(np.mean(((contact_y - contact_predictions) / contact_scale) ** 2)),
    }
    candidate_models = MODELS[1:]
    best = max(candidate_models, key=lambda name: (
        metrics[name]["spearman"], metrics[name]["parent_centered_spearman"], metrics[name]["top20_percent_recall"]
    ))
    gates = {
        "global_spearman_improved": metrics[best]["spearman"] > reference["spearman"],
        "parent_centered_not_worse": metrics[best]["parent_centered_spearman"] >= reference["parent_centered_spearman"],
        "top20_not_worse": metrics[best]["top20_percent_recall"] >= reference["top20_percent_recall"],
        "bootstrap_median_positive": bootstrap[best]["median_delta"] > 0.0,
    }
    contact_attribution = best in MODELS[2:] and metrics[best]["spearman"] > metrics["C1_structure_physchem_random_relu"]["spearman"]
    passed = all(gates.values()) and contact_attribution
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_OPEN_TRAIN226_CONTACT_PROXY_NESTED_COMPARISON",
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": {
            "teacher": sha256_file(teacher),
            "structure": sha256_file(structure),
            "contacts": sha256_file(contacts),
            "contract": sha256_file(contract),
            "implementation": sha256_file(Path(__file__)),
        },
        "rows": 226,
        "parent_framework_clusters": 20,
        "structure_feature_count": 126,
        "physchem_feature_count": 27,
        "contact_feature_count": len(names),
        "contact_feature_names": names,
        "nested_oof_metrics": metrics,
        "paired_parent_bootstrap_vs_C0": bootstrap,
        "contact_proxy_metrics": contact_metrics,
        "outer_fold_audit": outer_audit,
        "best_candidate_model": best,
        "development_gates": gates,
        "contact_attribution_over_C1": contact_attribution,
        "development_gate_result": (
            f"PASS_DEVELOPMENT_CANDIDATE_{best}" if passed else "FAIL_KEEP_C0_STRUCTURE_LINEAR"
        ),
        "sealed_boundaries": {
            "open_development_labels_read": 0,
            "prospective_test_labels_read": 0,
            "true_held_out_contacts_used_as_inputs": 0,
        },
    }
    output_dir.mkdir(parents=True)
    prediction_fields = [
        "candidate_id", "sequence_sha256", "parent_framework_cluster", "outer_fold", "R_dual_min",
        *[f"prediction_{model}" for model in MODELS],
    ]
    prediction_rows = []
    for index, row in enumerate(dataset.rows):
        prediction_rows.append({
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "outer_fold": int(outer_fold[index]),
            "R_dual_min": float(dataset.ydual[index]),
            **{f"prediction_{model}": float(predictions[model][index]) for model in MODELS},
        })
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=prediction_fields, delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(prediction_rows)
    predictions_path = output_dir / "open_train226_v5_rc_nested_oof_predictions.tsv"
    atomic_write(predictions_path, buffer.getvalue().encode("utf-8"))
    summary_path = output_dir / "open_train226_v5_rc_summary.json"
    atomic_write(summary_path, (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    report_path = output_dir / "OPEN_TRAIN226_V5_RC_RESULTS_ZH.md"
    atomic_write(report_path, (render_report(summary) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": summary["status"],
        "development_gate_result": summary["development_gate_result"],
        "formal_pass_claimed": False,
        "predictions_sha256": sha256_file(predictions_path),
        "summary_sha256": sha256_file(summary_path),
        "report_sha256": sha256_file(report_path),
    }
    receipt_path = output_dir / "RUN_RECEIPT.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": summary["status"],
        "best_candidate_model": best,
        "development_gate_result": summary["development_gate_result"],
        "receipt_sha256": sha256_file(receipt_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--structure-features", type=Path, required=True)
    parser.add_argument("--contact-features", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args.teacher, args.structure_features, args.contact_features, args.contract, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
