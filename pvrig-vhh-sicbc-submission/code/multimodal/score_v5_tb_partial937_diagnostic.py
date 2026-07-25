#!/usr/bin/env python3
"""Fit V5-TB on OPEN_TRAIN226 and run a frozen partial937 diagnostic.

The partial labels are read only after every fit and hyperparameter has been
selected from OPEN_TRAIN226. They are never used for model selection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np


LOCAL_SRC = Path(__file__).resolve().parent
if str(LOCAL_SRC) not in sys.path:
    sys.path.insert(0, str(LOCAL_SRC))
import run_v5_tb_open_train as v5  # noqa: E402


SCHEMA_VERSION = "pvrig_v5_tb_partial937_diagnostic_v1"


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


def load_external_features(
    manifest_path: Path,
    structure_path: Path,
) -> tuple[list[dict[str, str]], np.ndarray, np.ndarray]:
    manifest_fields, rows = v5.load_table(manifest_path)
    required = {
        "candidate_id",
        "sequence_sha256",
        "sequence",
        "parent_framework_cluster",
        "target_patch_id",
        "design_mode",
    }
    v5.require(required <= set(manifest_fields), "external_manifest_fields_missing")
    v5.require(len(rows) == 1320, f"external_manifest_count_invalid:{len(rows)}")
    v5.require(len({row["candidate_id"] for row in rows}) == 1320, "external_candidate_not_unique")
    v5.require(len({row["sequence_sha256"] for row in rows}) == 1320, "external_sequence_not_unique")

    structure_fields, structure_rows = v5.load_table(structure_path)
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    v5.require(len(structure_by_id) == 1320, "external_structure_count_invalid")
    feature_names = [field for field in structure_fields if field not in v5.STRUCTURE_METADATA_FIELDS]
    v5.require(len(feature_names) == 126, "external_structure_feature_count_invalid")
    structure_x = []
    physchem_x = []
    for row in rows:
        structure = structure_by_id.get(row["candidate_id"])
        v5.require(structure is not None, f"external_structure_missing:{row['candidate_id']}")
        v5.require(structure["sequence_sha256"] == row["sequence_sha256"], f"external_sequence_mismatch:{row['candidate_id']}")
        v5.require(
            structure["parent_framework_cluster"] == row["parent_framework_cluster"],
            f"external_parent_mismatch:{row['candidate_id']}",
        )
        structure_x.append([float(structure[name]) for name in feature_names])
        physchem_x.append(v5.contracts.physicochemical_features(row["sequence"]))
    structure_array = np.asarray(structure_x, dtype=np.float64)
    physchem_array = np.asarray(physchem_x, dtype=np.float64)
    v5.require(structure_array.shape == (1320, 126), "external_structure_shape_invalid")
    v5.require(physchem_array.shape == (1320, 27), "external_physchem_shape_invalid")
    v5.require(np.isfinite(structure_array).all() and np.isfinite(physchem_array).all(), "external_features_nonfinite")
    return rows, structure_array, physchem_array


def fit_and_predict(
    train: v5.Dataset,
    external_structure: np.ndarray,
    external_physchem: np.ndarray,
    prereg: Mapping[str, Any],
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, dict[str, Any]]:
    alphas = tuple(float(value) for value in prereg["ridge_alphas"])
    weights = tuple(float(value) for value in prereg["convex_weights"])
    inner_folds = int(prereg["validation"]["inner_folds"])
    minimum_delta = float(prereg["pairwise_minimum_absolute_delta"])
    train_combined = np.concatenate((train.structure_x, train.physchem_x), axis=1)
    external_combined = np.concatenate((external_structure, external_physchem), axis=1)

    direct_alpha, direct_oof, direct_grid = v5.v4.select_alpha_oof(
        train.structure_x, train.ydual, train.groups, alphas, inner_folds
    )
    dual_alpha, inner8, inner9, dual_oof, dual_grid = v5.select_dual_alpha(
        train.structure_x, train.y8, train.y9, train.groups, alphas, inner_folds
    )
    combined_alpha, _combined_oof, combined_grid = v5.v4.select_alpha_oof(
        train_combined, train.ydual, train.groups, alphas, inner_folds
    )
    fusion_weight, _fusion_oof, fusion_grid = v5.v4.select_fusion_weight(
        train.ydual, direct_oof, dual_oof, weights
    )
    top20_alpha, _top20_raw, _top20_calibrated, top20_grid = v5.select_custom_alpha(
        train.structure_x,
        train.ydual,
        train.groups,
        alphas,
        inner_folds,
        lambda x, y, _groups, alpha: v5.fit_top20_head(x, y, alpha),
    )
    pairwise_alpha, _pair_raw, _pair_calibrated, pairwise_grid = v5.select_custom_alpha(
        train.structure_x,
        train.ydual,
        train.groups,
        alphas,
        inner_folds,
        lambda x, y, groups, alpha: v5.fit_pairwise_head(x, y, groups, alpha, minimum_delta),
    )

    direct_fit = v5.v4.fit_ridge(train.structure_x, train.ydual, direct_alpha)
    pred_direct = v5.v4.predict_ridge(external_structure, direct_fit)
    fit8 = v5.v4.fit_ridge(train.structure_x, train.y8, dual_alpha)
    fit9 = v5.v4.fit_ridge(train.structure_x, train.y9, dual_alpha)
    pred8 = v5.v4.predict_ridge(external_structure, fit8)
    pred9 = v5.v4.predict_ridge(external_structure, fit9)
    pred_dual = np.minimum(pred8, pred9)
    combined_fit = v5.v4.fit_ridge(train_combined, train.ydual, combined_alpha)
    pred_combined = v5.v4.predict_ridge(external_combined, combined_fit)
    top20_fit = v5.fit_top20_head(train.structure_x, train.ydual, top20_alpha)
    raw_top20, pred_top20 = v5.predict_calibrated_head(external_structure, top20_fit)
    pair_fit, pair_count = v5.fit_pairwise_head(
        train.structure_x, train.ydual, train.groups, pairwise_alpha, minimum_delta
    )
    _raw_pair, pred_pair = v5.predict_calibrated_head(external_structure, pair_fit)

    predictions = {
        "B0_train_mean": np.full(len(external_structure), float(np.mean(train.ydual))),
        "B1_structure_direct": pred_direct,
        "B2_dual_receptor_min": pred_dual,
        "B3_structure_plus_physchem": pred_combined,
        "B4_direct_dual_convex": (1.0 - fusion_weight) * pred_direct + fusion_weight * pred_dual,
        "B5_top20_ridge_classifier": pred_top20,
        "B6_within_parent_pairwise_ridge": pred_pair,
    }
    audit = {
        "selected_direct_alpha": direct_alpha,
        "selected_dual_alpha": dual_alpha,
        "selected_combined_alpha": combined_alpha,
        "selected_fusion_dual_weight": fusion_weight,
        "selected_top20_alpha": top20_alpha,
        "selected_pairwise_alpha": pairwise_alpha,
        "pairwise_logical_pair_count": pair_count,
        "inner_dual_receptor_prediction_correlation": float(np.corrcoef(inner8, inner9)[0, 1]),
        "selection_grids": {
            "direct": direct_grid,
            "dual": dual_grid,
            "combined": combined_grid,
            "fusion": fusion_grid,
            "top20": top20_grid,
            "pairwise": pairwise_grid,
        },
        "partial_labels_accessed_during_fit_or_selection": 0,
    }
    return predictions, pred8, pred9, {"fit": audit, "raw_top20": raw_top20}


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# PVRIG V5-TB partial937 冻结外部诊断",
        "",
        summary["claim_boundary"],
        "",
        "## 结果",
        "",
        "| model | Spearman | parent-centered | macro-parent | MAE | NDCG | Top20 recall | ΔSpearman vs B1 CI |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in v5.MODELS:
        value = summary["partial937_metrics"][model]
        if model == "B1_structure_direct":
            interval = "reference"
        else:
            boot = summary["paired_parent_bootstrap_vs_B1"][model]
            interval = f"{boot['median_delta']:+.4f} [{boot['ci95_lower']:+.4f},{boot['ci95_upper']:+.4f}]"
        lines.append(
            f"| {model} | {value['spearman']:.4f} | {value['parent_centered_spearman']:.4f} | "
            f"{value['per_parent_macro_mean_spearman']:.4f} | {value['mae']:.5f} | "
            f"{value['ndcg']:.5f} | {value['top20_percent_recall']:.4f} | {interval} |"
        )
    lines.extend([
        "",
        "## 限制",
        "",
        "- 这是 active campaign partial snapshot，存在完成顺序和技术成功选择偏差。",
        "- 本结果未用于选择模型、超参数、阈值或输入特征。",
        "- 无论结果方向如何，都不能称为 independent validation 或 formal PASS。",
        "",
    ])
    return "\n".join(lines)


def run(
    train_teacher: Path,
    train_structure: Path,
    preregistration: Path,
    protocol_path: Path,
    external_manifest: Path,
    external_structure: Path,
    partial_labels: Path,
    output_dir: Path,
) -> dict[str, Any]:
    v5.require(not output_dir.exists() and not output_dir.is_symlink(), "output_dir_exists")
    prereg = json.loads(preregistration.read_text())
    protocol = json.loads(protocol_path.read_text())
    v5.require(prereg.get("status") == "FROZEN_BEFORE_FIRST_V5_TB_RESULT", "prereg_not_frozen")
    v5.require(
        protocol.get("status") == "FROZEN_AFTER_OPEN226_BEFORE_V5_PARTIAL937_PREDICTIONS",
        "partial_protocol_not_frozen",
    )
    v5.require(protocol.get("model_selection_on_partial_labels") is False, "partial_selection_must_be_false")

    train = v5.load_dataset(train_teacher, train_structure)
    external_rows, structure_x, physchem_x = load_external_features(external_manifest, external_structure)
    predictions, pred8, pred9, fit_audit = fit_and_predict(train, structure_x, physchem_x, prereg)

    # Partial labels are intentionally opened only after fit_and_predict returns.
    partial_fields, partial_rows = v5.load_table(partial_labels)
    required_partial = {
        "candidate_id",
        "sequence_sha256",
        "parent_framework_cluster",
        "preview_state",
        "median_score_8X6B",
        "median_score_9E6Y",
        "R_dual_min",
    }
    v5.require(required_partial <= set(partial_fields), "partial_fields_missing")
    v5.require(len(partial_rows) == 1320, "partial_row_count_invalid")
    partial_by_id = {row["candidate_id"]: row for row in partial_rows}
    v5.require(len(partial_by_id) == 1320, "partial_candidate_not_unique")
    analyzable_indices = []
    y8 = []
    y9 = []
    ydual = []
    groups = []
    for index, row in enumerate(external_rows):
        label = partial_by_id.get(row["candidate_id"])
        v5.require(label is not None, f"partial_label_missing:{row['candidate_id']}")
        v5.require(label["sequence_sha256"] == row["sequence_sha256"], f"partial_sequence_mismatch:{row['candidate_id']}")
        if label["preview_state"] != "PARTIAL_ANALYZABLE":
            continue
        analyzable_indices.append(index)
        y8.append(float(label["median_score_8X6B"]))
        y9.append(float(label["median_score_9E6Y"]))
        ydual.append(float(label["R_dual_min"]))
        groups.append(row["parent_framework_cluster"])
    v5.require(len(analyzable_indices) == int(protocol["expected_partial_analyzable"]), "partial_analyzable_count_invalid")
    selected = np.asarray(analyzable_indices, dtype=np.int64)
    y8_array = np.asarray(y8, dtype=np.float64)
    y9_array = np.asarray(y9, dtype=np.float64)
    ydual_array = np.asarray(ydual, dtype=np.float64)
    v5.require(np.allclose(np.minimum(y8_array, y9_array), ydual_array, atol=1e-9), "partial_dual_min_contract_failed")

    metrics = {
        name: v5.extended_metrics(ydual_array, prediction[selected], groups)
        for name, prediction in predictions.items()
    }
    bootstrap = {}
    for offset, model in enumerate(v5.MODELS):
        if model == "B1_structure_direct":
            continue
        bootstrap[model] = v5.v4.paired_group_bootstrap_delta(
            ydual_array,
            predictions[model][selected],
            predictions["B1_structure_direct"][selected],
            groups,
            replicates=int(prereg["validation"]["bootstrap_replicates"]),
            seed=int(prereg["validation"]["bootstrap_seed"]) + 100 + offset,
        )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_BIAS_DISCLOSED_PARTIAL937_DIAGNOSTIC_NO_MODEL_SELECTION",
        "claim_boundary": protocol["claim_boundary"],
        "input_hashes": {
            "train_teacher": sha256_file(train_teacher),
            "train_structure": sha256_file(train_structure),
            "preregistration": sha256_file(preregistration),
            "partial_protocol": sha256_file(protocol_path),
            "external_manifest": sha256_file(external_manifest),
            "external_structure": sha256_file(external_structure),
            "partial_labels": sha256_file(partial_labels),
        },
        "external_candidates": 1320,
        "partial_analyzable": len(selected),
        "partial_parent_counts": {
            group: int(sum(value == group for value in groups)) for group in sorted(set(groups))
        },
        "OPEN_TRAIN226_fit_audit": fit_audit["fit"],
        "partial937_metrics": metrics,
        "paired_parent_bootstrap_vs_B1": bootstrap,
        "dual_receptor_auxiliary_metrics": {
            "R_8X6B": v5.extended_metrics(y8_array, pred8[selected], groups),
            "R_9E6Y": v5.extended_metrics(y9_array, pred9[selected], groups),
            "R_dual_gap": v5.extended_metrics(
                np.abs(y8_array - y9_array), np.abs(pred8[selected] - pred9[selected]), groups
            ),
        },
        "partial_labels_used_for_model_selection": 0,
        "formal_pass_claimed": False,
    }

    output_dir.mkdir(parents=True)
    output_rows = []
    for index, row in enumerate(external_rows):
        label = partial_by_id[row["candidate_id"]]
        output_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "preview_state": label["preview_state"],
            "partial_R_dual_min": label["R_dual_min"] if label["preview_state"] == "PARTIAL_ANALYZABLE" else "",
            "prediction_B2_R_8X6B": f"{pred8[index]:.12g}",
            "prediction_B2_R_9E6Y": f"{pred9[index]:.12g}",
            "raw_B5_top20_score": f"{fit_audit['raw_top20'][index]:.12g}",
            **{f"prediction_{name}": f"{predictions[name][index]:.12g}" for name in v5.MODELS},
            "claim_boundary": protocol["claim_boundary"],
        })
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    predictions_path = output_dir / "v4h1320_v5_tb_predictions_with_partial937_diagnostic.tsv"
    atomic_write(predictions_path, buffer.getvalue().encode("utf-8"))
    summary_path = output_dir / "partial937_v5_tb_diagnostic_summary.json"
    atomic_write(
        summary_path,
        (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
    )
    report_path = output_dir / "PARTIAL937_V5_TB_DIAGNOSTIC_ZH.md"
    atomic_write(report_path, (render_report(summary) + "\n").encode("utf-8"))
    receipt = {
        "schema_version": f"{SCHEMA_VERSION}_receipt",
        "status": summary["status"],
        "predictions_sha256": sha256_file(predictions_path),
        "summary_sha256": sha256_file(summary_path),
        "report_sha256": sha256_file(report_path),
        "partial_labels_used_for_model_selection": 0,
        "formal_pass_claimed": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    receipt_path = output_dir / "RUN_RECEIPT.json"
    atomic_write(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {
        "status": summary["status"],
        "partial_analyzable": len(selected),
        "summary_sha256": sha256_file(summary_path),
        "receipt_sha256": sha256_file(receipt_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-teacher", type=Path, required=True)
    parser.add_argument("--train-structure", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--partial-protocol", type=Path, required=True)
    parser.add_argument("--external-manifest", type=Path, required=True)
    parser.add_argument("--external-structure", type=Path, required=True)
    parser.add_argument("--partial-labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(
        args.train_teacher,
        args.train_structure,
        args.preregistration,
        args.partial_protocol,
        args.external_manifest,
        args.external_structure,
        args.partial_labels,
        args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

