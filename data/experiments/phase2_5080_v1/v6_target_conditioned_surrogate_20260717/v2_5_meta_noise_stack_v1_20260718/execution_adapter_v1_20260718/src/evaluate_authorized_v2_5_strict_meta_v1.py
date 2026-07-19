#!/usr/bin/env python3
"""Authorization-gated V2.5 D-only nested meta evaluation.

The authorization gate is intentionally completed before any canonical label,
D evidence, coarse-pose feature, or prediction table is opened.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
BASE_SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE_SRC))

from c2_fold_local_v1 import fit_fold_local_pca8_ridge, predict_fold_local_pca8_ridge
from execution_common_v1 import (
    ExecutionContractError,
    assert_exact_model_matrix,
    atomic_write_json,
    read_json,
    read_tsv,
    require,
    selected_c2_alpha_rows,
    sha256_file,
    sha256_text,
    unique_by,
    verify_named_hashes,
)
from meta_noise_stack_v1 import (
    GBDTConfig,
    attach_existing_c2_outer_oof,
    crossfit_noise_for_outer_fold,
    exact_min,
    fit_convex_residual_stack,
    fit_gbdt_challenger,
    hierarchical_weights,
    normalize_weights,
    predict_convex_residual_stack,
    predict_gbdt_challenger,
    validate_c2_outer_oof,
)


MODEL_IDS = (
    "D_ONLY_FROZEN_BASE",
    "M2_C2_CONVEX",
    "M2_D_CONVEX",
    "M2_D_C2_CONVEX",
    "M2_D_C2_RELIABILITY_CONVEX",
    "D_C2_CONTACT_RELIABILITY_HIST_GBDT",
)


def authorization_gate(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read only governance artifacts until all authorization bindings pass."""
    manifest_path = Path(args.execution_manifest).resolve()
    closure_path = Path(args.input_closure_receipt).resolve()
    overlay_path = Path(args.authorization_overlay).resolve()
    manifest = read_json(manifest_path)
    closure = read_json(closure_path)
    overlay = read_json(overlay_path)
    require(manifest["status"] == "FROZEN_UNAUTHORIZED_INPUT_VALIDATION_ONLY", "manifest_status")
    require(manifest["execution_authorized"] is False, "manifest_mutated_authorized")
    require(closure["status"] == "PASS_INPUTS_READY_UNAUTHORIZED", "input_closure_not_ready")
    require(closure["execution_authorized"] is False, "closure_mutated_authorized")
    require(overlay.get("schema_version") == "pvrig_v2_5_strict_meta_authorization_overlay_v1", "overlay_schema")
    require(overlay.get("status") == "EXPLICITLY_AUTHORIZED", "overlay_status")
    require(overlay.get("execution_authorized") is True, "overlay_not_authorized")
    require(overlay.get("execution_manifest_sha256") == sha256_file(manifest_path), "overlay_manifest_hash")
    require(overlay.get("input_closure_receipt_sha256") == sha256_file(closure_path), "overlay_closure_hash")
    required_token_hash = str(manifest["authorization_requirements"]["required_token_sha256"])
    require(sha256_text(args.authorization_token) == required_token_hash, "authorization_token_hash")
    require(overlay.get("authorization_token_sha256") == required_token_hash, "overlay_token_hash")
    assert_exact_model_matrix({"formal_model_matrix": manifest["formal_model_matrix"]})
    output = Path(args.output_dir).resolve()
    require(not output.exists() or not any(output.iterdir()), "formal_output_directory_not_empty")
    return manifest, closure, overlay


def _feature_fields(raw_rows: Sequence[Mapping[str, str]], exclusions: Sequence[str]) -> list[str]:
    fields = [name for name in raw_rows[0] if "__" in name and name not in set(exclusions)]
    require(len(fields) == 32, f"c2_retained_dimension:{len(fields)}")
    return fields


def _feature_matrix(ids: Sequence[str], raw: Mapping[str, Mapping[str, str]], fields: Sequence[str]) -> np.ndarray:
    values = np.asarray([[float(raw[candidate][name]) for name in fields] for candidate in ids], dtype=np.float64)
    require(np.isfinite(values).all(), "c2_feature_nonfinite")
    return values


def _truth_matrix(ids: Sequence[str], labels: Mapping[str, Mapping[str, str]]) -> np.ndarray:
    return np.asarray([[float(labels[c]["R_8X6B"]), float(labels[c]["R_9E6Y"])] for c in ids], dtype=np.float64)


def _metadata_rows(ids: Sequence[str], labels: Mapping[str, Mapping[str, str]]) -> list[dict[str, str]]:
    return [{
        "candidate_id": candidate,
        "teacher_source": str(labels[candidate]["teacher_source"]),
        "parent_framework_cluster": str(labels[candidate]["parent_framework_cluster"]),
    } for candidate in ids]


def _parent_macro_three_target_mae(
    ids: Sequence[str], truth: np.ndarray, prediction: np.ndarray,
    labels: Mapping[str, Mapping[str, str]],
) -> float:
    by_parent: dict[str, list[int]] = defaultdict(list)
    for index, candidate in enumerate(ids):
        by_parent[str(labels[candidate]["parent_framework_cluster"])].append(index)
    truth_three = np.column_stack([truth, exact_min(truth)])
    prediction_three = np.column_stack([prediction, exact_min(prediction)])
    return float(np.mean([
        np.mean(np.abs(prediction_three[indices] - truth_three[indices]))
        for indices in by_parent.values()
    ]))


def recompute_inner_c2(
    contract: Mapping[str, Any], labels: Mapping[str, Mapping[str, str]],
    raw: Mapping[str, Mapping[str, str]], inner_manifest: Sequence[Mapping[str, str]],
    frozen_alpha: Mapping[int, float],
) -> tuple[dict[int, dict[str, np.ndarray]], list[dict[str, Any]]]:
    fields = _feature_fields(list(raw.values()), contract["c2_protocol"]["feature_exclusions"])
    alpha_grid = [float(value) for value in contract["c2_protocol"]["ridge_alpha_grid"]]
    all_predictions: dict[int, dict[str, np.ndarray]] = {}
    audits = []
    for outer_fold in range(5):
        rows = [row for row in inner_manifest if int(row["outer_fold"]) == outer_fold]
        outer_train_ids = sorted({row["candidate_id"] for row in rows})
        predictions_by_alpha: dict[float, dict[str, np.ndarray]] = {}
        losses: dict[float, float] = {}
        for alpha in alpha_grid:
            predicted: dict[str, np.ndarray] = {}
            for inner_fold in range(5):
                subset = [row for row in rows if int(row["inner_fold"]) == inner_fold]
                train_ids = sorted(row["candidate_id"] for row in subset if row["candidate_role"] == "train")
                score_ids = sorted(row["candidate_id"] for row in subset if row["candidate_role"] == "score")
                require(set(train_ids).isdisjoint(score_ids), f"c2_inner_overlap:{outer_fold}:{inner_fold}")
                train_rows = _metadata_rows(train_ids, labels)
                model = fit_fold_local_pca8_ridge(
                    _feature_matrix(train_ids, raw, fields), _truth_matrix(train_ids, labels),
                    hierarchical_weights(train_rows), fields, ridge_alpha=alpha, components=8,
                )
                score_prediction = predict_fold_local_pca8_ridge(model, _feature_matrix(score_ids, raw, fields))
                for index, candidate in enumerate(score_ids):
                    require(candidate not in predicted, f"c2_inner_scored_twice:{outer_fold}:{candidate}")
                    predicted[candidate] = score_prediction[index]
            require(set(predicted) == set(outer_train_ids), f"c2_inner_candidate_closure:{outer_fold}:{alpha}")
            ordered_prediction = np.stack([predicted[candidate] for candidate in outer_train_ids])
            predictions_by_alpha[alpha] = predicted
            losses[alpha] = _parent_macro_three_target_mae(
                outer_train_ids, _truth_matrix(outer_train_ids, labels), ordered_prediction, labels,
            )
        best_loss = min(losses.values())
        selected = max(alpha for alpha, loss in losses.items() if abs(loss - best_loss) <= 1e-12)
        require(abs(selected - frozen_alpha[outer_fold]) <= 1e-12, f"c2_selected_alpha_mismatch:{outer_fold}:{selected}:{frozen_alpha[outer_fold]}")
        all_predictions[outer_fold] = predictions_by_alpha[selected]
        audits.append({
            "outer_fold": outer_fold,
            "selected_alpha": selected,
            "frozen_selected_alpha": frozen_alpha[outer_fold],
            "inner_parent_macro_three_target_mae_by_alpha": {str(k): v for k, v in losses.items()},
            "candidate_count": len(outer_train_ids),
        })
    return all_predictions, audits


def _merge_label_fields(row: Mapping[str, Any], label: Mapping[str, Any], c2: Sequence[float]) -> dict[str, Any]:
    merged = dict(row)
    merged.update({
        "truth_R8": float(label["R_8X6B"]),
        "truth_R9": float(label["R_9E6Y"]),
        "development_reliability_tier": str(label["development_reliability_tier"]),
        "seed_dispersion_max": str(label.get("seed_dispersion_max", "")),
        "m2_R8": float(row["M2_R8"]), "m2_R9": float(row["M2_R9"]),
        "neural_R8": float(row["neural_R8"]), "neural_R9": float(row["neural_R9"]),
        "contact_R8": float(row["contact_score_R8"]), "contact_R9": float(row["contact_score_R9"]),
        "c2_R8": float(c2[0]), "c2_R9": float(c2[1]),
    })
    return merged


def _branches(rows: Sequence[Mapping[str, Any]], variant: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    m2 = np.asarray([[float(row["m2_R8"]), float(row["m2_R9"])] for row in rows])
    d = np.asarray([[float(row["neural_R8"]), float(row["neural_R9"])] for row in rows])
    c2 = np.asarray([[float(row["c2_R8"]), float(row["c2_R9"])] for row in rows])
    if variant == "M2_C2_CONVEX":
        return m2, {"neural": m2, "contact": m2, "c2": c2}
    if variant == "M2_D_CONVEX":
        return m2, {"neural": d, "contact": m2, "c2": m2}
    require(variant in {"M2_D_C2_CONVEX", "M2_D_C2_RELIABILITY_CONVEX"}, f"unknown_convex_variant:{variant}")
    return m2, {"neural": d, "contact": m2, "c2": c2}


def fit_predict_outer_models(inner_rows: Sequence[Mapping[str, Any]], outer_rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    truth = np.asarray([[float(row["truth_R8"]), float(row["truth_R9"])] for row in inner_rows])
    base_weight = hierarchical_weights(inner_rows)
    predictions: dict[str, np.ndarray] = {
        "D_ONLY_FROZEN_BASE": np.asarray([[float(row["neural_R8"]), float(row["neural_R9"])] for row in outer_rows])
    }
    audits: dict[str, Any] = {"D_ONLY_FROZEN_BASE": {"fit": "none"}}
    for model_id in ("M2_C2_CONVEX", "M2_D_CONVEX", "M2_D_C2_CONVEX"):
        inner_m2, inner_branches = _branches(inner_rows, model_id)
        outer_m2, outer_branches = _branches(outer_rows, model_id)
        model = fit_convex_residual_stack(truth, inner_m2, inner_branches, base_weight, l2_toward_m2=1e-3)
        predictions[model_id] = predict_convex_residual_stack(model, outer_m2, outer_branches)
        audits[model_id] = model.audit()

    inner_reliability, outer_reliability, noise_audit = crossfit_noise_for_outer_fold(inner_rows, outer_rows)
    inner_m2, inner_branches = _branches(inner_rows, "M2_D_C2_RELIABILITY_CONVEX")
    outer_m2, outer_branches = _branches(outer_rows, "M2_D_C2_RELIABILITY_CONVEX")
    reliability_model = fit_convex_residual_stack(
        truth, inner_m2, inner_branches, normalize_weights(base_weight * inner_reliability),
        l2_toward_m2=1e-3,
    )
    predictions["M2_D_C2_RELIABILITY_CONVEX"] = predict_convex_residual_stack(
        reliability_model, outer_m2, outer_branches,
    )
    audits["M2_D_C2_RELIABILITY_CONVEX"] = {
        "stack": reliability_model.audit(), "noise": noise_audit,
    }
    gbdt = fit_gbdt_challenger(inner_rows, base_weight, inner_reliability, GBDTConfig())
    predictions["D_C2_CONTACT_RELIABILITY_HIST_GBDT"] = predict_gbdt_challenger(
        gbdt, outer_rows, outer_reliability,
    )
    audits["D_C2_CONTACT_RELIABILITY_HIST_GBDT"] = {"config": asdict(gbdt.config)}
    require(set(predictions) == set(MODEL_IDS), "model_prediction_matrix_closure")
    return predictions, audits


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return ranks


def _spearman(truth: np.ndarray, prediction: np.ndarray) -> float:
    left, right = _rankdata(truth), _rankdata(prediction)
    if np.std(left) == 0 or np.std(right) == 0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _scalar_metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    error = prediction - truth
    return {
        "spearman": _spearman(truth, prediction),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error * error))),
    }


def evaluate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    targets = {}
    for truth_name, pred_name, label in (
        ("truth_R8", "pred_R8", "R8"), ("truth_R9", "pred_R9", "R9"),
        ("truth_Rdual", "pred_Rdual", "Rdual"),
    ):
        targets[label] = _scalar_metrics(
            np.asarray([float(row[truth_name]) for row in rows]),
            np.asarray([float(row[pred_name]) for row in rows]),
        )
    sources = {}
    for source in sorted({str(row["teacher_source"]) for row in rows}):
        subset = [row for row in rows if row["teacher_source"] == source]
        sources[source] = evaluate_rows(subset)["targets"] if len(subset) != len(rows) else targets
    parents: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        parents[str(row["parent_framework_cluster"])].append(row)
    parent_mae = {}
    for truth_name, pred_name, label in (
        ("truth_R8", "pred_R8", "R8"), ("truth_R9", "pred_R9", "R9"),
        ("truth_Rdual", "pred_Rdual", "Rdual"),
    ):
        by_parent = {
            parent: float(np.mean([
                abs(float(row[pred_name]) - float(row[truth_name])) for row in subset
            ]))
            for parent, subset in parents.items()
        }
        parent_mae[label] = {"macro_mae": float(np.mean(list(by_parent.values()))), "by_parent": by_parent}
    return {"targets": targets, "sources": sources, "parent_macro": parent_mae}


def _parent_bootstrap_delta_spearman(
    primary: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]],
    *, seed: int, replicates: int,
) -> dict[str, float]:
    by_parent_primary: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_parent_baseline: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in primary: by_parent_primary[str(row["parent_framework_cluster"])].append(row)
    for row in baseline: by_parent_baseline[str(row["parent_framework_cluster"])].append(row)
    parents = sorted(by_parent_primary)
    require(set(parents) == set(by_parent_baseline), "bootstrap_parent_closure")
    rng = np.random.default_rng(seed)
    deltas = np.empty(replicates, dtype=np.float64)
    for index in range(replicates):
        selected = rng.choice(parents, size=len(parents), replace=True)
        p_rows = [row for parent in selected for row in by_parent_primary[parent]]
        b_rows = [row for parent in selected for row in by_parent_baseline[parent]]
        truth = np.asarray([float(row["truth_Rdual"]) for row in p_rows])
        deltas[index] = _spearman(truth, np.asarray([float(row["pred_Rdual"]) for row in p_rows])) - _spearman(
            truth, np.asarray([float(row["pred_Rdual"]) for row in b_rows])
        )
    return {
        "mean": float(np.mean(deltas)),
        "ci95_lower": float(np.quantile(deltas, 0.025)),
        "ci95_upper": float(np.quantile(deltas, 0.975)),
        "replicates": replicates,
        "seed": seed,
    }


def decide(contract: Mapping[str, Any], metrics: Mapping[str, Any], rows_by_model: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    baseline = metrics["M2_C2_CONVEX"]  # diagnostic only; frozen M2 numeric gate remains authoritative below
    primary = metrics["M2_D_C2_CONVEX"]
    gate = contract["formal_gates"]["primary_M2_D_C2"]
    frozen_m2 = contract["formal_gates"]["frozen_M2"]
    m2_rows = [{
        **row,
        "pred_R8": row["m2_R8"],
        "pred_R9": row["m2_R9"],
        "pred_Rdual": min(row["m2_R8"], row["m2_R9"]),
    } for row in rows_by_model["M2_D_C2_CONVEX"]]
    m2_metrics = evaluate_rows(m2_rows)
    bootstrap = _parent_bootstrap_delta_spearman(
        rows_by_model["M2_D_C2_CONVEX"],
        m2_rows,
        seed=int(gate["bootstrap_seed"]), replicates=int(gate["bootstrap_replicates"]),
    )
    parent_primary = primary["parent_macro"]["Rdual"]
    parent_m2_values = {}
    for parent in parent_primary["by_parent"]:
        subset = [row for row in rows_by_model["M2_D_C2_CONVEX"] if row["parent_framework_cluster"] == parent]
        parent_m2_values[parent] = float(np.mean([abs(min(row["m2_R8"], row["m2_R9"]) - row["truth_Rdual"]) for row in subset]))
    parent_nonnegative = sum(parent_primary["by_parent"][parent] <= parent_m2_values[parent] for parent in parent_m2_values)
    checks = {
        "Rdual_spearman": primary["targets"]["Rdual"]["spearman"] >= float(gate["Rdual_spearman_min"]),
        "Rdual_mae": primary["targets"]["Rdual"]["mae"] <= float(gate["Rdual_mae_max"]),
        "Rdual_rmse": primary["targets"]["Rdual"]["rmse"] <= float(gate["Rdual_rmse_max"]),
        "parent_bootstrap": bootstrap["ci95_lower"] > float(gate["parent_bootstrap_delta_spearman_95ci_lower_gt"]),
        "both_source_delta_spearman": all(
            primary["sources"][source]["Rdual"]["spearman"] >= m2_metrics["sources"][source]["Rdual"]["spearman"] + float(gate["both_source_delta_spearman_min"])
            for source in primary["sources"]
        ),
        "parent_macro_mae": parent_primary["macro_mae"] <= float(np.mean(list(parent_m2_values.values()))),
        "parent_count_nonnegative": parent_nonnegative >= int(gate["parents_with_nonnegative_Rdual_mae_delta_min"]),
        "R8_floor": primary["targets"]["R8"]["spearman"] >= m2_metrics["targets"]["R8"]["spearman"] + float(gate["R8_and_R9_spearman_floor_vs_M2_delta"]),
        "R9_floor": primary["targets"]["R9"]["spearman"] >= m2_metrics["targets"]["R9"]["spearman"] + float(gate["R8_and_R9_spearman_floor_vs_M2_delta"]),
    }
    primary_pass = all(checks.values())
    challenger_gate = contract["formal_gates"]["challenger_replacement"]
    challenger_decisions = {}
    for challenger_id in (
        "M2_D_C2_RELIABILITY_CONVEX", "D_C2_CONTACT_RELIABILITY_HIST_GBDT",
    ):
        current = metrics[challenger_id]
        challenger_bootstrap = _parent_bootstrap_delta_spearman(
            rows_by_model[challenger_id], rows_by_model["M2_D_C2_CONVEX"],
            seed=int(gate["bootstrap_seed"]), replicates=int(gate["bootstrap_replicates"]),
        )
        challenger_checks = {
            "primary_gate_passed": primary_pass,
            "Rdual_spearman_delta": current["targets"]["Rdual"]["spearman"] - primary["targets"]["Rdual"]["spearman"] >= float(challenger_gate["Rdual_spearman_delta_vs_primary_min"]),
            "Rdual_mae": current["targets"]["Rdual"]["mae"] <= primary["targets"]["Rdual"]["mae"],
            "Rdual_rmse": current["targets"]["Rdual"]["rmse"] <= primary["targets"]["Rdual"]["rmse"],
            "source_mae": all(
                current["sources"][source]["Rdual"]["mae"] <= primary["sources"][source]["Rdual"]["mae"]
                for source in current["sources"]
            ),
            "parent_macro_mae": current["parent_macro"]["Rdual"]["macro_mae"] <= primary["parent_macro"]["Rdual"]["macro_mae"],
            "paired_parent_bootstrap": challenger_bootstrap["ci95_lower"] > float(challenger_gate["paired_parent_bootstrap_delta_spearman_95ci_lower_gt"]),
        }
        challenger_decisions[challenger_id] = {
            "status": "REPLACE_PRIMARY" if all(challenger_checks.values()) else "DO_NOT_REPLACE_PRIMARY",
            "checks": challenger_checks,
            "parent_bootstrap_delta_vs_primary": challenger_bootstrap,
        }
    return {
        "primary_status": "PASS_PROMOTION_GATE" if primary_pass else "DO_NOT_PROMOTE",
        "primary_checks": checks,
        "parent_bootstrap_delta_vs_M2": bootstrap,
        "parents_with_nonnegative_Rdual_mae_delta": parent_nonnegative,
        "observed_M2_metrics": m2_metrics,
        "frozen_M2_gate_reference": frozen_m2,
        "diagnostic_M2_C2_metrics": baseline,
        "challengers": challenger_decisions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-manifest", required=True)
    parser.add_argument("--input-closure-receipt", required=True)
    parser.add_argument("--authorization-overlay", required=True)
    parser.add_argument("--authorization-token", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    manifest, closure, overlay = authorization_gate(args)

    contract = read_json(Path(args.contract).resolve())
    require(sha256_file(Path(args.contract).resolve()) == manifest["contract"]["sha256"], "contract_manifest_hash")
    assert_exact_model_matrix(contract)
    input_root = Path(args.input_root).resolve()
    runtime_root = Path(args.runtime_root).resolve()
    verify_named_hashes(input_root, contract["canonical_inputs"])
    labels_rows = read_tsv(input_root / contract["canonical_inputs"]["labels"]["filename"])
    labels = unique_by(labels_rows, "candidate_id", "label")
    raw = unique_by(read_tsv(input_root / contract["canonical_inputs"]["coarse_pose_raw36"]["filename"]), "candidate_id", "raw36")
    inner_manifest = read_tsv(input_root / contract["canonical_inputs"]["inner_manifest"]["filename"])
    c2_rows = read_tsv(input_root / contract["canonical_inputs"]["existing_c2_outer_oof"]["filename"])
    validate_c2_outer_oof(c2_rows, labels)
    frozen_alpha = selected_c2_alpha_rows(read_tsv(input_root / contract["canonical_inputs"]["existing_c2_alpha_selection"]["filename"]))
    inner_c2, c2_audits = recompute_inner_c2(contract, labels, raw, inner_manifest, frozen_alpha)
    c2_outer_index = {
        row["candidate_id"]: np.asarray([float(row["pred_R8"]), float(row["pred_R9"])])
        for row in c2_rows if row["model_id"] == "C2_INNER_SELECTED_PCA8_RIDGE"
    }

    rows_by_model: dict[str, list[dict[str, Any]]] = {model: [] for model in MODEL_IDS}
    fold_audits = []
    for fold in range(5):
        evidence_root = runtime_root / "evidence" / "D_SPLIT_PAIR" / f"outer_{fold}"
        inner_base = read_tsv(evidence_root / "inner_oof_base.tsv")
        outer_base = read_tsv(evidence_root / "outer_test_base.tsv")
        inner_rows = [_merge_label_fields(row, labels[row["candidate_id"]], inner_c2[fold][row["candidate_id"]]) for row in inner_base]
        outer_rows = [_merge_label_fields(row, labels[row["candidate_id"]], c2_outer_index[row["candidate_id"]]) for row in outer_base]
        predictions, audit = fit_predict_outer_models(inner_rows, outer_rows)
        fold_audits.append({"outer_fold": fold, "models": audit})
        for model_id, prediction_two in predictions.items():
            prediction_dual = exact_min(prediction_two)
            for index, base in enumerate(outer_rows):
                rows_by_model[model_id].append({
                    "model_id": model_id,
                    "candidate_id": base["candidate_id"],
                    "outer_fold": fold,
                    "teacher_source": base["teacher_source"],
                    "parent_framework_cluster": base["parent_framework_cluster"],
                    "truth_R8": float(base["truth_R8"]), "truth_R9": float(base["truth_R9"]),
                    "truth_Rdual": min(float(base["truth_R8"]), float(base["truth_R9"])),
                    "m2_R8": float(base["m2_R8"]), "m2_R9": float(base["m2_R9"]),
                    "pred_R8": float(prediction_two[index, 0]), "pred_R9": float(prediction_two[index, 1]),
                    "pred_Rdual": float(prediction_dual[index]),
                })
    for model_id, rows in rows_by_model.items():
        require(len(rows) == int(contract["expected_counts"]["candidates"]), f"model_candidate_count:{model_id}")
        require(len({row["candidate_id"] for row in rows}) == len(rows), f"model_candidate_duplicate:{model_id}")
        require(all(abs(row["pred_Rdual"] - min(row["pred_R8"], row["pred_R9"])) <= 1e-12 for row in rows), f"model_exact_min:{model_id}")

    metrics = {model: evaluate_rows(rows) for model, rows in rows_by_model.items()}
    decision = decide(contract, metrics, rows_by_model)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    prediction_path = output_dir / "FORMAL_OUTER_OOF_PREDICTIONS.tsv"
    fields = list(next(iter(rows_by_model.values()))[0])
    with prediction_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for model_id in MODEL_IDS:
            writer.writerows(rows_by_model[model_id])
    atomic_write_json(output_dir / "FORMAL_METRICS.json", {
        "schema_version": "pvrig_v2_5_strict_meta_formal_metrics_v1",
        "metrics": metrics, "decision": decision, "claim_boundary": contract["claim_boundary"],
    })
    atomic_write_json(output_dir / "FORMAL_PARAMETERS.json", {
        "schema_version": "pvrig_v2_5_strict_meta_parameters_v1",
        "fold_audits": fold_audits, "c2_audits": c2_audits,
    })
    artifacts = {name: sha256_file(output_dir / name) for name in (
        "FORMAL_OUTER_OOF_PREDICTIONS.tsv", "FORMAL_METRICS.json", "FORMAL_PARAMETERS.json",
    )}
    atomic_write_json(output_dir / "FORMAL_EXECUTION_RECEIPT.json", {
        "schema_version": "pvrig_v2_5_strict_meta_formal_execution_receipt_v1",
        "status": "PASS_FORMAL_EVALUATION_COMPLETED",
        "execution_authorized": True,
        "execution_manifest_sha256": sha256_file(Path(args.execution_manifest).resolve()),
        "input_closure_receipt_sha256": sha256_file(Path(args.input_closure_receipt).resolve()),
        "authorization_overlay_sha256": sha256_file(Path(args.authorization_overlay).resolve()),
        "artifacts": artifacts,
        "v4_f_test32_access_count": 0,
        "claim_boundary": contract["claim_boundary"],
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExecutionContractError, KeyError, ValueError, OSError) as exc:
        print(f"FAIL_CLOSED:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise SystemExit(2)
