#!/usr/bin/env python3
"""Strict E_SHARED + M2/C2/contact2D nested meta evaluator.

The live 301-job graph is read-only.  All neural/contact evidence is recovered
from immutable raw per-job TSV files and verified against RESULT.json hashes.
M2 and C2 are recomputed inside every parent-held-out inner/outer partition.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
VENDOR = HERE.parent / "vendor"
sys.path.insert(0, str(VENDOR))
from evaluate_m2_c2_double_crossfit_stack_v1 import (  # noqa: E402
    c2_predict,
    fit_m2_ridge,
    m2_hierarchical_weights,
)
from evaluate_nested_oof_challengers_v1 import (  # noqa: E402
    PCA_EXCLUSIONS,
    feature_matrix,
    hierarchical_weights,
    selection_loss,
    target_matrix,
)


PRIMARY_LANE = "E_DECOUPLED_CONTACT_SHARED"
PRIMARY_MODEL = "M2_C2_E_SHARED_CONTACT2D_CONSTRAINED_STACK"
BASELINE_MODEL = "M2_FROZEN_ALPHA10"
EXPECTED_CONTRACT_SHA = "0329a4749d9874f3bef7bda30d744d57b85b626783df9dc33a7fd931f3f75eb2"
C2_ALPHA_GRID = (0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0)
SEEDS = (43, 97, 193)
CLAIM_BOUNDARY = (
    "Open-development whole-parent OOF surrogate of independent 8X6B/9E6Y "
    "computational Docking geometry only; not binding, affinity, experimental "
    "blocking, Docking Gold, sealed V4-F evidence, or submission truth."
)


class EvaluationError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise EvaluationError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    require(isinstance(data, dict), f"json_not_object:{path}")
    return data


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"empty_tsv:{path}")
    return rows


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    require(bool(rows), f"empty_write:{path}")
    fields = list(rows[0])
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            require(list(row) == fields, f"field_order_mismatch:{path}")
            writer.writerow(row)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temp, path)


def unique(rows: Sequence[Mapping[str, str]], key: str) -> dict[str, Mapping[str, str]]:
    result = {}
    for row in rows:
        value = row[key]
        require(value not in result, f"duplicate:{key}:{value}")
        result[value] = row
    return result


def validate_contract(path: Path) -> dict[str, Any]:
    require(sha256(path) == EXPECTED_CONTRACT_SHA, "contract_sha_mismatch")
    contract = read_json(path)
    require(contract["lane_roles"]["formal_primary_base_lane"] == PRIMARY_LANE, "primary_lane_mismatch")
    require(contract["preobservation_assertions"]["v4_f_test32_access_count"] == 0, "sealed_access_nonzero")
    require(contract["prediction_contract"]["independent_Rdual_output_allowed"] is False, "free_dual_enabled")
    return contract


def frozen_selected_alphas(rows: Sequence[Mapping[str, str]]) -> dict[int, float]:
    result = {}
    for row in rows:
        if row["selected"].lower() == "true":
            fold = int(row["outer_fold"])
            require(fold not in result, f"duplicate_selected_alpha:{fold}")
            result[fold] = float(row["alpha"])
    require(set(result) == set(range(5)), "selected_alpha_fold_closure")
    return result


def validate_raw_job(
    directory: Path, *, phase: str, outer_fold: int, inner_fold: int | None,
    hparam_id: str, seed: int, expected_ids: set[str], require_contact: bool,
) -> dict[str, dict[str, str]]:
    result_path = directory / "RESULT.json"
    result = read_json(result_path)
    require(result["status"] == ("PASS_FORMAL_INNER_TRAINING" if phase == "inner" else "PASS_FORMAL_OUTER_REFIT"), f"job_status:{directory}")
    require(result["phase"] == phase and int(result["outer_fold"]) == outer_fold, f"job_scope:{directory}")
    require(result["lane"]["variant"] == PRIMARY_LANE, f"job_lane:{directory}")
    require(result["formal_hparam_id"] == hparam_id and int(result["formal_seed"]) == seed, f"job_fit_identity:{directory}")
    require(result.get("v4_f_test32_access_count") == 0, f"job_sealed_access:{directory}")
    require(result.get("prediction_metrics_access_count") == 0, f"job_metrics_access:{directory}")
    if phase == "inner":
        require(int(result["inner_fold"]) == inner_fold, f"job_inner_fold:{directory}")
    artifact = result["artifacts"]["predictions_no_metrics"]
    prediction_path = directory / artifact["path"]
    require(sha256(prediction_path) == artifact["sha256"], f"job_prediction_hash:{directory}")
    rows = unique(read_tsv(prediction_path), "candidate_id")
    require(set(rows) == expected_ids, f"job_candidate_closure:{directory}")
    for candidate, row in rows.items():
        r8, r9, dual = map(float, (row["neural_R8"], row["neural_R9"], row["neural_Rdual"]))
        require(abs(dual - min(r8, r9)) <= 1e-7, f"job_exact_min:{candidate}")
        if require_contact:
            for field in ("contact_score_R8", "contact_score_R9"):
                require(str(row[field]).strip() != "", f"missing_contact:{candidate}:{field}")
                require(math.isfinite(float(row[field])), f"nonfinite_contact:{candidate}:{field}")
    return rows


def robust_contact_fit(contact: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    require(contact.ndim == 2 and contact.shape[1] == 2 and np.isfinite(contact).all(), "contact_fit_shape")
    center = np.median(contact, axis=0)
    q25, q75 = np.quantile(contact, (0.25, 0.75), axis=0)
    scale = np.maximum((q75 - q25) / 1.349, 1e-6)
    return center, scale


def robust_contact_transform(contact: np.ndarray, center: np.ndarray, scale: np.ndarray) -> np.ndarray:
    result = np.clip((contact - center) / scale, -5.0, 5.0)
    require(result.shape == contact.shape and np.isfinite(result).all(), "contact_transform")
    return result


@dataclass(frozen=True)
class MetaFit:
    w_E: float
    w_C2: float
    beta_C: float
    fit_status: str
    objective: float
    m2_objective: float


def _huber(error: np.ndarray, beta: float = 0.03) -> tuple[np.ndarray, np.ndarray]:
    absolute = np.abs(error)
    loss = np.where(absolute < beta, 0.5 * error * error / beta, absolute - 0.5 * beta)
    gradient = np.where(absolute < beta, error / beta, np.sign(error))
    return loss, gradient


def fit_meta(
    truth: np.ndarray, m2: np.ndarray, c2: np.ndarray, neural: np.ndarray,
    contact_z: np.ndarray, weights: np.ndarray,
) -> MetaFit:
    for name, value in (("truth", truth), ("m2", m2), ("c2", c2), ("neural", neural), ("contact", contact_z)):
        require(value.shape == truth.shape == (len(truth), 2), f"meta_shape:{name}")
        require(np.isfinite(value).all(), f"meta_nonfinite:{name}")
    weights = np.asarray(weights, dtype=np.float64)
    weights = weights / weights.sum()
    d_e, d_c2 = neural - m2, c2 - m2

    def objective(beta: np.ndarray) -> float:
        prediction = m2 + beta[0] * d_e + beta[1] * d_c2 + beta[2] * contact_z
        loss, _ = _huber(prediction - truth)
        regularization = 0.01 * (beta[0] ** 2 + beta[1] ** 2) + 0.10 * beta[2] ** 2
        return float(np.sum(weights[:, None] * loss) / 2.0 + regularization)

    def gradient(beta: np.ndarray) -> np.ndarray:
        prediction = m2 + beta[0] * d_e + beta[1] * d_c2 + beta[2] * contact_z
        _, grad_loss = _huber(prediction - truth)
        result = np.asarray([
            np.sum(weights[:, None] * grad_loss * d_e) / 2.0 + 0.02 * beta[0],
            np.sum(weights[:, None] * grad_loss * d_c2) / 2.0 + 0.02 * beta[1],
            np.sum(weights[:, None] * grad_loss * contact_z) / 2.0 + 0.20 * beta[2],
        ])
        return result

    zero = np.zeros(3, dtype=np.float64)
    m2_objective = objective(zero)
    result = minimize(
        objective, zero, jac=gradient, method="SLSQP",
        bounds=[(0.0, 1.0), (0.0, 1.0), (0.0, None)],
        constraints=[{"type": "ineq", "fun": lambda b: 1.0 - b[0] - b[1], "jac": lambda b: np.asarray([-1.0, -1.0, 0.0])}],
        options={"ftol": 1e-13, "maxiter": 2000, "disp": False},
    )
    beta = np.asarray(result.x, dtype=np.float64)
    valid = bool(result.success) and np.isfinite(beta).all() and np.all(beta >= -1e-10) and beta[0] + beta[1] <= 1.0 + 1e-10
    if not valid or objective(beta) > m2_objective + 1e-12:
        return MetaFit(0.0, 0.0, 0.0, "EXACT_M2_FALLBACK_INVALID_META", m2_objective, m2_objective)
    beta = np.maximum(beta, 0.0)
    beta[beta < 1e-12] = 0.0
    return MetaFit(float(beta[0]), float(beta[1]), float(beta[2]), "PASS_CONSTRAINED_META", objective(beta), m2_objective)


def meta_predict(model: MetaFit, m2: np.ndarray, c2: np.ndarray, neural: np.ndarray, contact_z: np.ndarray) -> np.ndarray:
    prediction = m2 + model.w_E * (neural - m2) + model.w_C2 * (c2 - m2) + model.beta_C * contact_z
    require(prediction.shape == m2.shape and np.isfinite(prediction).all(), "meta_prediction_invalid")
    return prediction


def ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    result = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        result[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return result


def spearman(truth: np.ndarray, prediction: np.ndarray) -> float:
    left, right = ranks(truth), ranks(prediction)
    return 0.0 if np.std(left) == 0 or np.std(right) == 0 else float(np.corrcoef(left, right)[0, 1])


def scalar_metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    error = prediction - truth
    return {"spearman": spearman(truth, prediction), "mae": float(np.mean(np.abs(error))), "rmse": float(np.sqrt(np.mean(error * error)))}


def evaluate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = {"targets": {}, "sources": {}, "parent_macro": {}}
    targets = (("truth_R8", "pred_R8", "R8"), ("truth_R9", "pred_R9", "R9"), ("truth_Rdual", "pred_Rdual", "Rdual"))
    for truth_name, pred_name, label in targets:
        result["targets"][label] = scalar_metrics(np.asarray([float(r[truth_name]) for r in rows]), np.asarray([float(r[pred_name]) for r in rows]))
    for source in sorted({str(r["teacher_source"]) for r in rows}):
        subset = [r for r in rows if r["teacher_source"] == source]
        result["sources"][source] = {}
        for truth_name, pred_name, label in targets:
            result["sources"][source][label] = scalar_metrics(np.asarray([float(r[truth_name]) for r in subset]), np.asarray([float(r[pred_name]) for r in subset]))
    by_parent: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_parent[str(row["parent_framework_cluster"])].append(row)
    for truth_name, pred_name, label in targets:
        values = {parent: float(np.mean([abs(float(r[pred_name]) - float(r[truth_name])) for r in subset])) for parent, subset in by_parent.items()}
        result["parent_macro"][label] = {"macro_mae": float(np.mean(list(values.values()))), "by_parent": values}
    return result


def parent_bootstrap(primary: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]], seed: int = 1931, replicates: int = 10000) -> dict[str, Any]:
    p, b = defaultdict(list), defaultdict(list)
    for row in primary: p[row["parent_framework_cluster"]].append(row)
    for row in baseline: b[row["parent_framework_cluster"]].append(row)
    parents = sorted(p)
    require(set(parents) == set(b), "bootstrap_parent_closure")
    rng = np.random.default_rng(seed)
    delta = np.empty(replicates)
    for index in range(replicates):
        sample = rng.choice(parents, size=len(parents), replace=True)
        pr = [r for parent in sample for r in p[parent]]
        br = [r for parent in sample for r in b[parent]]
        truth = np.asarray([float(r["truth_Rdual"]) for r in pr])
        delta[index] = spearman(truth, np.asarray([float(r["pred_Rdual"]) for r in pr])) - spearman(truth, np.asarray([float(r["pred_Rdual"]) for r in br]))
    return {"mean": float(delta.mean()), "ci95_lower": float(np.quantile(delta, 0.025)), "ci95_upper": float(np.quantile(delta, 0.975)), "seed": seed, "replicates": replicates}


def promotion_decision(contract: Mapping[str, Any], primary_rows: Sequence[Mapping[str, Any]], m2_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    primary, m2 = evaluate_rows(primary_rows), evaluate_rows(m2_rows)
    gate = contract["promotion_gate"]
    bootstrap = parent_bootstrap(primary_rows, m2_rows)
    p_parent, m_parent = primary["parent_macro"]["Rdual"], m2["parent_macro"]["Rdual"]
    improved = sum(p_parent["by_parent"][parent] <= m_parent["by_parent"][parent] for parent in p_parent["by_parent"])
    checks = {
        "Rdual_spearman": primary["targets"]["Rdual"]["spearman"] >= gate["Rdual_spearman_min"],
        "Rdual_mae": primary["targets"]["Rdual"]["mae"] <= gate["Rdual_mae_max"],
        "Rdual_rmse": primary["targets"]["Rdual"]["rmse"] <= gate["Rdual_rmse_max"],
        "each_source_Rdual_mae": all(primary["sources"][source]["Rdual"]["mae"] <= m2["sources"][source]["Rdual"]["mae"] for source in primary["sources"]),
        "both_source_Rdual_spearman": all(primary["sources"][source]["Rdual"]["spearman"] >= m2["sources"][source]["Rdual"]["spearman"] + gate["both_source_delta_Rdual_spearman_min"] for source in primary["sources"]),
        "parent_macro_Rdual_mae": p_parent["macro_mae"] <= m_parent["macro_mae"],
        "parent_count": improved >= gate["parents_with_nonnegative_Rdual_mae_delta_min"],
        "parent_bootstrap": bootstrap["ci95_lower"] > gate["paired_parent_bootstrap_delta_Rdual_spearman_95ci_lower_gt"],
        "R8_floor": primary["targets"]["R8"]["spearman"] >= m2["targets"]["R8"]["spearman"] + gate["R8_and_R9_spearman_floor_vs_M2_delta"],
        "R9_floor": primary["targets"]["R9"]["spearman"] >= m2["targets"]["R9"]["spearman"] + gate["R8_and_R9_spearman_floor_vs_M2_delta"],
    }
    return {"status": "PROMOTE" if all(checks.values()) else "DO_NOT_PROMOTE_EXACT_M2_FALLBACK", "checks": checks, "parents_with_nonnegative_Rdual_mae_delta": improved, "paired_parent_bootstrap": bootstrap, "primary_metrics": primary, "m2_metrics": m2}


def _ensemble_outer(runtime: Path, fold: int, hparam: str, expected_ids: set[str]) -> dict[str, np.ndarray]:
    per_seed = []
    for seed in SEEDS:
        directory = runtime / "outer" / PRIMARY_LANE / f"outer_{fold}" / f"seed_{seed}"
        per_seed.append(validate_raw_job(directory, phase="outer", outer_fold=fold, inner_fold=None, hparam_id=hparam, seed=seed, expected_ids=expected_ids, require_contact=True))
    ordered = sorted(expected_ids)
    neural = np.mean([np.asarray([[float(rows[c]["neural_R8"]), float(rows[c]["neural_R9"])] for c in ordered]) for rows in per_seed], axis=0)
    contact = np.mean([np.asarray([[float(rows[c]["contact_score_R8"]), float(rows[c]["contact_score_R9"])] for c in ordered]) for rows in per_seed], axis=0)
    return {"ids": np.asarray(ordered, dtype=object), "neural": neural, "contact": contact}


def execute(args: argparse.Namespace) -> dict[str, Any]:
    contract = validate_contract(args.contract.resolve())
    runtime = args.runtime_root.resolve()
    terminal = read_json(runtime / "TERMINAL.json")
    require(terminal["status"] == "PASS" and int(terminal["completed"]) == 301, "runtime_not_terminal")
    require(terminal["job_graph_sha256"] == contract["upstream_identity"]["formal_job_graph"]["sha256"], "runtime_graph_sha")
    require(terminal.get("v4_f_test32_access_count") == 0, "runtime_sealed_access")
    final = read_json(runtime / "final" / "RESULT.json")
    require(final["status"] == "PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED", "runtime_final_status")
    require(final.get("v4_f_test32_access_count") == 0, "runtime_final_sealed_access")

    labels = unique(read_tsv(args.labels.resolve()), "candidate_id")
    raw = unique(read_tsv(args.raw_features.resolve()), "candidate_id")
    require(len(labels) == 1507 and set(labels) == set(raw), "open1507_closure")
    outer_manifest = read_tsv(args.outer_manifest.resolve())
    inner_manifest = read_tsv(args.inner_manifest.resolve())
    frozen_alpha = frozen_selected_alphas(read_tsv(args.c2_alpha_selection.resolve()))
    c2_outer_rows = read_tsv(args.c2_outer_oof.resolve())
    c2_outer = {row["candidate_id"]: np.asarray([float(row["pred_R8"]), float(row["pred_R9"])]) for row in c2_outer_rows if row["model_id"] == "C2_INNER_SELECTED_PCA8_RIDGE"}
    require(set(c2_outer) == set(labels), "c2_outer_closure")
    metadata = {cid: {"teacher_source": row["teacher_source"], "parent_framework_cluster": row["parent_framework_cluster"]} for cid, row in labels.items()}
    m2_fields = [field for field in next(iter(labels.values())) if "__" in field]
    c2_fields = [field for field in next(iter(raw.values())) if "__" in field and field not in PCA_EXCLUSIONS]
    require(len(m2_fields) == 126 and len(c2_fields) == 32, "feature_dimensions")

    pretruth_rows = []
    fold_audits = []
    all_m2: dict[str, np.ndarray] = {}
    all_primary: dict[str, np.ndarray] = {}
    candidate_fold = {}
    for fold in range(5):
        outer_rows = [row for row in outer_manifest if int(row["outer_fold"]) == fold]
        train_ids = sorted(row["candidate_id"] for row in outer_rows if row["candidate_role"] == "train")
        score_ids = sorted(row["candidate_id"] for row in outer_rows if row["candidate_role"] == "score")
        require(set(train_ids).isdisjoint(score_ids) and set(train_ids) | set(score_ids) == set(labels), f"outer_split:{fold}")
        selection_path = runtime / "selection" / PRIMARY_LANE / f"outer_{fold}" / "SELECTION.json"
        selection = read_json(selection_path)
        require(selection["status"] == "PASS_INNER_HPARAM_SELECTED" and selection["lane"] == PRIMARY_LANE and int(selection["outer_fold"]) == fold, f"selection:{fold}")
        require(selection.get("v4_f_test32_access_count") == 0, f"selection_sealed:{fold}")
        hparam = selection["selected_hparam_id"]

        inner_e, inner_m2 = {}, {}
        inner_c2_by_alpha = {alpha: {} for alpha in C2_ALPHA_GRID}
        for inner_fold in range(5):
            subset = [row for row in inner_manifest if int(row["outer_fold"]) == fold and int(row["inner_fold"]) == inner_fold]
            inner_train = sorted(row["candidate_id"] for row in subset if row["candidate_role"] == "train")
            inner_score = sorted(row["candidate_id"] for row in subset if row["candidate_role"] == "score")
            require(set(inner_train).isdisjoint(inner_score) and set(inner_train) | set(inner_score) == set(train_ids), f"inner_split:{fold}:{inner_fold}")
            directory = runtime / "inner" / PRIMARY_LANE / hparam / f"outer_{fold}" / f"inner_{inner_fold}"
            e_rows = validate_raw_job(directory, phase="inner", outer_fold=fold, inner_fold=inner_fold, hparam_id=hparam, seed=43, expected_ids=set(inner_score), require_contact=True)
            for cid in inner_score:
                require(cid not in inner_e, f"inner_e_duplicate:{fold}:{cid}")
                inner_e[cid] = np.asarray([float(e_rows[cid]["neural_R8"]), float(e_rows[cid]["neural_R9"]), float(e_rows[cid]["contact_score_R8"]), float(e_rows[cid]["contact_score_R9"])])
            truth = target_matrix(inner_train, labels)
            m2_pred = fit_m2_ridge(feature_matrix(inner_train, labels, m2_fields), truth, feature_matrix(inner_score, labels, m2_fields), m2_hierarchical_weights(inner_train, metadata), 10.0)
            for index, cid in enumerate(inner_score): inner_m2[cid] = m2_pred[index]
            for alpha in C2_ALPHA_GRID:
                pred = c2_predict(feature_matrix(inner_train, raw, c2_fields), truth, feature_matrix(inner_score, raw, c2_fields), hierarchical_weights(inner_train, metadata), alpha)
                for index, cid in enumerate(inner_score): inner_c2_by_alpha[alpha][cid] = pred[index]
        require(set(inner_e) == set(inner_m2) == set(train_ids), f"inner_oof_closure:{fold}")
        truth_inner = target_matrix(train_ids, labels)
        losses = {alpha: selection_loss(train_ids, truth_inner, np.stack([inner_c2_by_alpha[alpha][cid] for cid in train_ids]), metadata) for alpha in C2_ALPHA_GRID}
        best = min(losses.values())
        selected_alpha = max(alpha for alpha, loss in losses.items() if abs(loss - best) <= 1e-12)
        require(abs(selected_alpha - frozen_alpha[fold]) <= 1e-12, f"c2_alpha_mismatch:{fold}")
        inner_m2_array = np.stack([inner_m2[cid] for cid in train_ids])
        inner_c2_array = np.stack([inner_c2_by_alpha[selected_alpha][cid] for cid in train_ids])
        inner_e_array = np.stack([inner_e[cid][:2] for cid in train_ids])
        inner_contact = np.stack([inner_e[cid][2:] for cid in train_ids])
        center, scale = robust_contact_fit(inner_contact)
        inner_contact_z = robust_contact_transform(inner_contact, center, scale)
        meta = fit_meta(truth_inner, inner_m2_array, inner_c2_array, inner_e_array, inner_contact_z, m2_hierarchical_weights(train_ids, metadata))

        truth_train = target_matrix(train_ids, labels)
        outer_m2 = fit_m2_ridge(feature_matrix(train_ids, labels, m2_fields), truth_train, feature_matrix(score_ids, labels, m2_fields), m2_hierarchical_weights(train_ids, metadata), 10.0)
        outer_c2 = c2_predict(feature_matrix(train_ids, raw, c2_fields), truth_train, feature_matrix(score_ids, raw, c2_fields), hierarchical_weights(train_ids, metadata), selected_alpha)
        require(np.max(np.abs(outer_c2 - np.stack([c2_outer[cid] for cid in score_ids]))) <= 1e-10, f"c2_outer_reproduction:{fold}")
        outer_e = _ensemble_outer(runtime, fold, hparam, set(score_ids))
        require(list(outer_e["ids"]) == score_ids, f"outer_e_order:{fold}")
        outer_contact_z = robust_contact_transform(outer_e["contact"], center, scale)
        outer_primary = meta_predict(meta, outer_m2, outer_c2, outer_e["neural"], outer_contact_z)
        for index, cid in enumerate(score_ids):
            require(cid not in all_m2, f"outer_candidate_duplicate:{cid}")
            all_m2[cid], all_primary[cid], candidate_fold[cid] = outer_m2[index], outer_primary[index], fold
            pretruth_rows.extend([
                {"model_id": BASELINE_MODEL, "candidate_id": cid, "outer_fold": fold, "pred_R8": outer_m2[index, 0], "pred_R9": outer_m2[index, 1], "pred_Rdual": min(outer_m2[index])},
                {"model_id": PRIMARY_MODEL, "candidate_id": cid, "outer_fold": fold, "pred_R8": outer_primary[index, 0], "pred_R9": outer_primary[index, 1], "pred_Rdual": min(outer_primary[index])},
            ])
        fold_audits.append({"outer_fold": fold, "selected_neural_hparam": hparam, "selected_c2_alpha": selected_alpha, "contact_center": center.tolist(), "contact_scale": scale.tolist(), "meta": asdict(meta), "inner_rows": len(train_ids), "outer_rows": len(score_ids)})
    require(set(all_m2) == set(all_primary) == set(labels), "final_candidate_closure")
    require(len(pretruth_rows) == 3014, "pretruth_row_count")

    output = args.output_dir.resolve()
    require(not output.exists(), "output_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent)))
    try:
        pretruth_path = staging / "OUTER_PREDICTIONS_PRETRUTH.tsv"
        write_tsv(pretruth_path, pretruth_rows)
        pretruth_sha = sha256(pretruth_path)
        rows_by_model = {BASELINE_MODEL: [], PRIMARY_MODEL: []}
        for model_id, predictions in ((BASELINE_MODEL, all_m2), (PRIMARY_MODEL, all_primary)):
            for cid in sorted(labels):
                truth = labels[cid]
                pred = predictions[cid]
                rows_by_model[model_id].append({"model_id": model_id, "candidate_id": cid, "outer_fold": candidate_fold[cid], "teacher_source": truth["teacher_source"], "parent_framework_cluster": truth["parent_framework_cluster"], "truth_R8": float(truth["R_8X6B"]), "truth_R9": float(truth["R_9E6Y"]), "truth_Rdual": min(float(truth["R_8X6B"]), float(truth["R_9E6Y"])), "pred_R8": float(pred[0]), "pred_R9": float(pred[1]), "pred_Rdual": float(min(pred))})
        m2_metrics = evaluate_rows(rows_by_model[BASELINE_MODEL])
        frozen = contract["promotion_gate"]
        require(abs(m2_metrics["targets"]["Rdual"]["spearman"] - 0.6094011215999979) <= 1e-12, "m2_rho_reproduction")
        require(abs(m2_metrics["targets"]["Rdual"]["mae"] - frozen["Rdual_mae_max"]) <= 1e-12, "m2_mae_reproduction")
        require(abs(m2_metrics["targets"]["Rdual"]["rmse"] - frozen["Rdual_rmse_max"]) <= 1e-12, "m2_rmse_reproduction")
        decision = promotion_decision(contract, rows_by_model[PRIMARY_MODEL], rows_by_model[BASELINE_MODEL])
        formal_rows = rows_by_model[BASELINE_MODEL] + rows_by_model[PRIMARY_MODEL]
        write_tsv(staging / "FORMAL_OUTER_OOF_PREDICTIONS.tsv", formal_rows)
        atomic_json(staging / "FORMAL_PARAMETERS.json", {"schema_version": "pvrig_v2_5_ortho_cross_lane_meta_parameters_v1", "fold_audits": fold_audits, "contract_sha256": EXPECTED_CONTRACT_SHA, "pretruth_prediction_sha256": pretruth_sha})
        atomic_json(staging / "FORMAL_METRICS.json", {"schema_version": "pvrig_v2_5_ortho_cross_lane_meta_metrics_v1", "metrics": {BASELINE_MODEL: m2_metrics, PRIMARY_MODEL: evaluate_rows(rows_by_model[PRIMARY_MODEL])}, "decision": decision, "claim_boundary": CLAIM_BOUNDARY})
        artifacts = {name: sha256(staging / name) for name in ("OUTER_PREDICTIONS_PRETRUTH.tsv", "FORMAL_OUTER_OOF_PREDICTIONS.tsv", "FORMAL_PARAMETERS.json", "FORMAL_METRICS.json")}
        atomic_json(staging / "FORMAL_EXECUTION_RECEIPT.json", {"schema_version": "pvrig_v2_5_ortho_cross_lane_meta_execution_receipt_v1", "status": "PASS_FORMAL_CROSS_LANE_META_EVALUATION_COMPLETED", "contract_sha256": EXPECTED_CONTRACT_SHA, "runtime_job_graph_sha256": terminal["job_graph_sha256"], "runtime_terminal_sha256": sha256(runtime / "TERMINAL.json"), "runtime_final_result_sha256": sha256(runtime / "final" / "RESULT.json"), "artifacts": artifacts, "decision": decision["status"], "v4_f_test32_access_count": 0, "claim_boundary": CLAIM_BOUNDARY})
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"status": "PASS", "decision": decision["status"], "output_dir": str(output), "contract_sha256": EXPECTED_CONTRACT_SHA, "v4_f_test32_access_count": 0}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--contract", type=Path, required=True)
    result.add_argument("--runtime-root", type=Path, required=True)
    result.add_argument("--labels", type=Path, required=True)
    result.add_argument("--raw-features", type=Path, required=True)
    result.add_argument("--outer-manifest", type=Path, required=True)
    result.add_argument("--inner-manifest", type=Path, required=True)
    result.add_argument("--c2-outer-oof", type=Path, required=True)
    result.add_argument("--c2-alpha-selection", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    print(json.dumps(execute(args), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EvaluationError, KeyError, ValueError, OSError) as exc:
        print(f"FAIL_CLOSED:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise SystemExit(2)
