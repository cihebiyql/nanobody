#!/usr/bin/env python3
"""Nested whole-parent evaluation of a conservative C0/contact rank blend."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_contact_proxy_nested as rc  # noqa: E402


SCHEMA_VERSION = "pvrig_v5_rc2_budget_contact_rank_blend_v1"
CLAIM_BOUNDARY = (
    "OPEN_TRAIN-only computational docking-geometry acquisition research; not "
    "binding, affinity, competition, experimental blocking, Docking Gold, or "
    "final submission authority."
)
MODELS = (
    "RC2_C0_structure_linear",
    "RC2_C1_structure_nonlinear",
    "RC2_C2_contact_bottleneck",
    "RC2_budget_rank_blend",
)
GAMMAS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
MAX_SPEARMAN_DROP = 0.005
MAX_PARENT_CENTERED_DROP = 0.005
CALIBRATION_ALPHA = 1.0


class BudgetBlendError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BudgetBlendError(message)


def percentile_train(values: np.ndarray) -> np.ndarray:
    require(values.ndim == 1 and len(values) >= 2, "percentile_train_shape_invalid")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(len(values), dtype=np.float64)
    return ranks / float(len(values) - 1)


def percentile_apply(reference: np.ndarray, values: np.ndarray) -> np.ndarray:
    require(reference.ndim == values.ndim == 1 and len(reference) >= 2, "percentile_apply_shape_invalid")
    ordered = np.sort(reference, kind="mergesort")
    return np.searchsorted(ordered, values, side="right").astype(np.float64) / float(len(ordered))


def select_gamma(
    y: np.ndarray,
    c0_score: np.ndarray,
    contact_score: np.ndarray,
    groups: Sequence[str],
) -> tuple[float, np.ndarray, dict[str, Any]]:
    c0_rank = percentile_train(c0_score)
    contact_rank = percentile_train(contact_score)
    baseline = rc.v5.extended_metrics(y, c0_rank, groups)
    candidates = []
    grid = {}
    for gamma in GAMMAS:
        blend = (1.0 - gamma) * c0_rank + gamma * contact_rank
        metric = rc.v5.extended_metrics(y, blend, groups)
        eligible = (
            metric["spearman"] >= baseline["spearman"] - MAX_SPEARMAN_DROP
            and metric["parent_centered_spearman"]
            >= baseline["parent_centered_spearman"] - MAX_PARENT_CENTERED_DROP
        )
        grid[str(gamma)] = {**metric, "eligible": eligible}
        key = (
            int(eligible),
            round(metric["top20_percent_recall"], 12),
            round(metric["spearman"], 12),
            round(metric["parent_centered_spearman"], 12),
            -gamma,
        )
        candidates.append((key, gamma, blend))
    _key, gamma, blend = max(candidates, key=lambda item: item[0])
    require(grid[str(gamma)]["eligible"], "selected_gamma_not_eligible")
    return float(gamma), blend, grid


def load_contact_targets(dataset: rc.v5.Dataset, path: Path) -> tuple[list[str], np.ndarray]:
    fields, rows = rc.load_tsv(path)
    require(len(rows) == 226, f"contact_row_count_invalid:{len(rows)}")
    names = rc.contact_feature_names(fields)
    by_id = {row["candidate_id"]: row for row in rows}
    require(len(by_id) == 226, "contact_candidate_not_unique")
    values = []
    for row in dataset.rows:
        contact = by_id.get(row["candidate_id"])
        require(contact is not None, f"contact_missing:{row['candidate_id']}")
        require(contact["sequence_sha256"] == row["sequence_sha256"], f"contact_sequence_mismatch:{row['candidate_id']}")
        values.append([float(contact[name]) for name in names])
    matrix = np.asarray(values, dtype=np.float64)
    require(matrix.shape == (226, 101) and np.isfinite(matrix).all(), "contact_matrix_invalid")
    return names, matrix


def nested_evaluate(
    dataset: rc.v5.Dataset,
    contact_y: np.ndarray,
) -> tuple[dict[str, np.ndarray], np.ndarray, list[dict[str, Any]]]:
    predictions = {model: np.empty(len(dataset.ydual), dtype=np.float64) for model in MODELS}
    outer_fold = np.full(len(dataset.ydual), -1, dtype=np.int64)
    audit = []
    combined_x = np.concatenate([dataset.structure_x, dataset.physchem_x], axis=1)
    for fold_index, held in enumerate(rc.v5.v4.build_group_folds(dataset.groups, rc.OUTER_FOLDS)):
        keep = np.ones(len(dataset.ydual), dtype=bool)
        keep[held] = False
        train_groups = [dataset.groups[index] for index in np.flatnonzero(keep)]
        y_train = dataset.ydual[keep]
        structure_train = dataset.structure_x[keep]
        combined_train = combined_x[keep]

        linear_alpha, linear_oof, linear_grid = rc.v5.v4.select_alpha_oof(
            structure_train, y_train, train_groups, rc.ALPHAS, rc.INNER_FOLDS
        )
        nonlinear_alpha, nonlinear_oof, nonlinear_grid = rc.select_nonlinear_alpha(
            combined_train, y_train, train_groups
        )
        contact_alpha, contact_oof, contact_grid = rc.select_nonlinear_alpha(
            combined_train, contact_y[keep], train_groups
        )
        contact_meta_alpha, contact_scalar_oof, contact_meta_grid = rc.v5.v4.select_alpha_oof(
            contact_oof, y_train, train_groups, rc.ALPHAS, rc.INNER_FOLDS
        )

        linear_held = rc.v5.v4.predict_ridge(
            dataset.structure_x[held], rc.v5.v4.fit_ridge(structure_train, y_train, linear_alpha)
        )
        nonlinear_held = rc.fit_predict_nonlinear(
            combined_train, y_train, combined_x[held], nonlinear_alpha
        )
        contact_held = rc.fit_predict_nonlinear(
            combined_train, contact_y[keep], combined_x[held], contact_alpha
        )
        contact_scalar_held = rc.v5.v4.predict_ridge(
            contact_held, rc.v5.v4.fit_ridge(contact_oof, y_train, contact_meta_alpha)
        )

        gamma, blend_train, gamma_grid = select_gamma(
            y_train, linear_oof, contact_scalar_oof, train_groups
        )
        blend_held = (
            (1.0 - gamma) * percentile_apply(linear_oof, linear_held)
            + gamma * percentile_apply(contact_scalar_oof, contact_scalar_held)
        )
        calibration = rc.v5.v4.fit_ridge(
            blend_train[:, None], y_train, CALIBRATION_ALPHA
        )
        blend_prediction = rc.v5.v4.predict_ridge(blend_held[:, None], calibration)

        predictions["RC2_C0_structure_linear"][held] = linear_held
        predictions["RC2_C1_structure_nonlinear"][held] = nonlinear_held
        predictions["RC2_C2_contact_bottleneck"][held] = contact_scalar_held
        predictions["RC2_budget_rank_blend"][held] = blend_prediction
        outer_fold[held] = fold_index
        audit.append({
            "fold": fold_index,
            "held_rows": len(held),
            "held_parent_clusters": sorted({dataset.groups[index] for index in held}),
            "selected_alphas": {
                "linear": linear_alpha,
                "nonlinear": nonlinear_alpha,
                "contact_proxy": contact_alpha,
                "contact_scalar": contact_meta_alpha,
                "calibration": CALIBRATION_ALPHA,
            },
            "selected_gamma": gamma,
            "gamma_grid": gamma_grid,
            "linear_grid": linear_grid,
            "nonlinear_grid": nonlinear_grid,
            "contact_grid": contact_grid,
            "contact_meta_grid": contact_meta_grid,
        })
    require(np.all(outer_fold >= 0), "outer_fold_incomplete")
    require(all(np.isfinite(value).all() for value in predictions.values()), "prediction_nonfinite")
    return predictions, outer_fold, audit


def report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# V5-RC.2 Budget-aware Contact Rank-Blend 结果",
        "",
        f"状态：`{summary['status']}`",
        "",
        CLAIM_BOUNDARY,
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
        f"Outer-fold gamma：`{summary['selected_gamma_by_outer_fold']}`",
        "",
        f"决策：`{summary['development_gate_result']}`",
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
    dataset = rc.v5.load_dataset(teacher, structure)
    names, contact_y = load_contact_targets(dataset, contacts)
    predictions, outer_fold, audit = nested_evaluate(dataset, contact_y)
    metrics = {
        model: rc.v5.extended_metrics(dataset.ydual, prediction, dataset.groups)
        for model, prediction in predictions.items()
    }
    comparator = metrics["RC2_C0_structure_linear"]
    candidate = metrics["RC2_budget_rank_blend"]
    bootstrap = rc.v5.v4.paired_group_bootstrap_delta(
        dataset.ydual,
        predictions["RC2_budget_rank_blend"],
        predictions["RC2_C0_structure_linear"],
        dataset.groups,
        replicates=rc.BOOTSTRAP_REPLICATES,
        seed=rc.BOOTSTRAP_SEED,
    )
    gates = {
        "global_spearman_not_worse": candidate["spearman"] >= comparator["spearman"],
        "parent_centered_not_worse": candidate["parent_centered_spearman"] >= comparator["parent_centered_spearman"],
        "top20_strictly_improved": candidate["top20_percent_recall"] > comparator["top20_percent_recall"],
        "bootstrap_median_nonnegative": bootstrap["median_delta"] >= 0.0,
    }
    passed = all(gates.values())
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_OPEN_TRAIN226_BUDGET_CONTACT_BLEND_COMPARISON",
        "claim_boundary": CLAIM_BOUNDARY,
        "input_hashes": {
            "teacher": rc.sha256_file(teacher),
            "structure": rc.sha256_file(structure),
            "contacts": rc.sha256_file(contacts),
            "contract": rc.sha256_file(contract),
            "implementation": rc.sha256_file(Path(__file__)),
        },
        "rows": 226,
        "parent_framework_clusters": 20,
        "contact_target_count": len(names),
        "nested_oof_metrics": metrics,
        "paired_parent_bootstrap_blend_vs_C0": bootstrap,
        "selected_gamma_by_outer_fold": [row["selected_gamma"] for row in audit],
        "outer_fold_audit": audit,
        "development_gates": gates,
        "development_gate_result": (
            "PASS_DEVELOPMENT_BUDGET_CONTACT_BLEND" if passed
            else "FAIL_CONTACT_ONLY_EXPLORATION_NOT_EXPLOITATION"
        ),
        "sealed_boundaries": {
            "open_development_labels_or_contacts_read": 0,
            "prospective_test_labels_or_contacts_read": 0,
            "true_outer_held_contacts_used_as_inputs": 0,
        },
    }
    output_dir.mkdir(parents=True)
    fields = [
        "candidate_id", "sequence_sha256", "parent_framework_cluster", "outer_fold", "R_dual_min",
        *[f"prediction_{model}" for model in MODELS],
    ]
    rows = []
    for index, row in enumerate(dataset.rows):
        rows.append({
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "outer_fold": int(outer_fold[index]),
            "R_dual_min": float(dataset.ydual[index]),
            **{f"prediction_{model}": float(predictions[model][index]) for model in MODELS},
        })
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    predictions_path = output_dir / "open_train226_v5_rc2_nested_oof_predictions.tsv"
    rc.atomic_write(predictions_path, buffer.getvalue().encode("utf-8"))
    summary_path = output_dir / "open_train226_v5_rc2_summary.json"
    rc.atomic_write(summary_path, (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    report_path = output_dir / "OPEN_TRAIN226_V5_RC2_RESULTS_ZH.md"
    rc.atomic_write(report_path, (report(summary) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": summary["status"],
        "development_gate_result": summary["development_gate_result"],
        "formal_pass_claimed": False,
        "predictions_sha256": rc.sha256_file(predictions_path),
        "summary_sha256": rc.sha256_file(summary_path),
        "report_sha256": rc.sha256_file(report_path),
    }
    receipt_path = output_dir / "RUN_RECEIPT.json"
    rc.atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": summary["status"],
        "development_gate_result": summary["development_gate_result"],
        "selected_gamma_by_outer_fold": summary["selected_gamma_by_outer_fold"],
        "receipt_sha256": rc.sha256_file(receipt_path),
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
