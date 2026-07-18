#!/usr/bin/env python3
"""Fail-closed source-stratified OOF collector for residue V2."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "pvrig_v6_residue_v2_oof_collector"
PREREGISTRATION_SCHEMA = "pvrig_v6_residue_v2_preregistration"
PREREGISTRATION_STATUS = "FROZEN_DESIGN_BEFORE_RESIDUE_V2_OOF_RESULTS"
V4D = "V4D_OPEN_MULTI_SEED"
V4H = "V4H_STAGE1_SEED917"
SOURCES = (V4D, V4H)
REQUIRED_PREDICTION_FIELDS = {
    "candidate_id", "parent_framework_cluster", "outer_fold", "R_dual_min",
    "m2_prediction", "residue_prediction",
}
CLAIM_BOUNDARY = (
    "Sequence and label-free-structure approximation of independent dual-receptor "
    "computational Docking geometry; not binding probability, affinity, experimental "
    "competition, blocking, Docking Gold, or final submission evidence."
)
FROZEN_PROMOTION_GATES = {
    "global_spearman_delta_min": 0.01,
    "v4d_spearman_delta_min": 0.0,
    "v4h_spearman_delta_min": 0.0,
    "parent_win_delta_min": 0.01,
    "parent_loss_delta_max": -0.01,
    "global_parent_wins_strictly_greater_than_losses": True,
    "per_source_parent_wins_greater_than_or_equal_to_losses": True,
    "global_top20_budget": 302,
    "global_top20_net_hit_gain_min": 5,
    "v4d_top20_budget": 46,
    "v4h_top20_budget": 257,
    "per_source_top20_net_hit_gain_min": 0,
    "parent_bootstrap_positive_fraction_min": 0.8,
    "parent_bootstrap_median_delta_strictly_positive": True,
    "per_source_parent_bootstrap_positive_fraction_min": 0.8,
    "per_source_parent_bootstrap_median_delta_min": 0.0,
    "per_source_mae_max_degradation": 0.001,
    "all_required": True,
    "negative_status": "DO_NOT_PROMOTE_RESIDUE_V2",
    "positive_status": "PROMOTE_RESIDUE_V2_OVER_M2",
}


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"collector_input_missing_or_symlink:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def average_ranks(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * ((start + 1) + end)
        start = end
    return ranks


def spearman(target: np.ndarray, prediction: np.ndarray) -> float:
    target_rank = average_ranks(target)
    prediction_rank = average_ranks(prediction)
    if len(target_rank) < 2 or np.std(target_rank) < 1e-12 or np.std(prediction_rank) < 1e-12:
        return 0.0
    value = float(np.corrcoef(target_rank, prediction_rank)[0, 1])
    return value if math.isfinite(value) else 0.0


def exact_top_indices(rows: Sequence[Mapping[str, Any]], field: str, budget: int) -> set[int]:
    require(0 < budget <= len(rows), f"top_budget_invalid:{field}:{budget}:{len(rows)}")
    ordered = sorted(
        range(len(rows)),
        key=lambda index: (-float(rows[index][field]), str(rows[index]["candidate_id"])),
    )
    return set(ordered[:budget])


def metrics(rows: Sequence[Mapping[str, Any]], field: str, budget: int) -> dict[str, float | int]:
    require(len(rows) >= 3, f"metric_rows_too_small:{len(rows)}")
    target = np.asarray([float(row["R_dual_min"]) for row in rows])
    prediction = np.asarray([float(row[field]) for row in rows])
    truth = exact_top_indices(rows, "R_dual_min", budget)
    chosen = exact_top_indices(rows, field, budget)
    return {
        "spearman": spearman(target, prediction),
        "mae": float(np.mean(np.abs(target - prediction))),
        "top20_budget": budget,
        "top20_hits": len(truth & chosen),
        "top20_recall": len(truth & chosen) / budget,
    }


def parent_outcomes(
    rows: Sequence[Mapping[str, Any]],
    *,
    win_delta: float,
    loss_delta: float,
) -> dict[str, Any]:
    by_parent: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(str(row["parent_framework_cluster"]), []).append(row)
    outcomes = []
    for parent in sorted(by_parent):
        values = by_parent[parent]
        target = np.asarray([float(row["R_dual_min"]) for row in values])
        baseline = np.asarray([float(row["m2_prediction"]) for row in values])
        model = np.asarray([float(row["residue_prediction"]) for row in values])
        delta = spearman(target, model) - spearman(target, baseline)
        state = "WIN" if delta >= win_delta else "LOSS" if delta <= loss_delta else "TIE"
        outcomes.append({"parent_framework_cluster": parent, "rows": len(values), "delta_spearman": delta, "outcome": state})
    counts = {state: sum(item["outcome"] == state for item in outcomes) for state in ("WIN", "LOSS", "TIE")}
    return {"counts": counts, "parents": outcomes}


def parent_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    repetitions: int,
    seed: int,
) -> dict[str, float | int]:
    require(repetitions >= 100, "bootstrap_repetitions_too_small")
    by_parent: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(str(row["parent_framework_cluster"]), []).append(row)
    parents = sorted(by_parent)
    require(len(parents) >= 2, "bootstrap_parent_count")
    generator = np.random.default_rng(seed)
    values = []
    for _ in range(repetitions):
        sampled = generator.choice(parents, size=len(parents), replace=True)
        replicate = [row for parent in sampled for row in by_parent[str(parent)]]
        target = np.asarray([float(row["R_dual_min"]) for row in replicate])
        baseline = np.asarray([float(row["m2_prediction"]) for row in replicate])
        model = np.asarray([float(row["residue_prediction"]) for row in replicate])
        values.append(spearman(target, model) - spearman(target, baseline))
    array = np.asarray(values)
    return {
        "repetitions": repetitions,
        "seed": seed,
        "parent_count": len(parents),
        "median_delta_spearman": float(np.median(array)),
        "positive_fraction": float(np.mean(array > 0)),
        "ci95_lower": float(np.quantile(array, 0.025)),
        "ci95_upper": float(np.quantile(array, 0.975)),
    }


def validate_preregistration(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "preregistration_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(payload.get("schema_version") == PREREGISTRATION_SCHEMA, "preregistration_schema")
    require(payload.get("status") == PREREGISTRATION_STATUS, "preregistration_status")
    gates = payload.get("promotion_gates") or {}
    required = set(FROZEN_PROMOTION_GATES)
    require(set(gates) == required, f"promotion_gate_key_closure:{sorted(set(gates)^required)}")
    require(gates == FROZEN_PROMOTION_GATES, "promotion_gate_values_not_frozen_v2")
    require(payload.get("training", {}).get("teacher_source_is_model_feature") is False, "teacher_source_feature_contract")
    require(payload.get("sealed_and_excluded", {}).get("teacher_source_as_model_feature") is True, "teacher_source_seal_contract")
    return payload


def validate_and_join_rows(
    training_tsv: Path,
    prediction_tsvs: Sequence[Path],
    preregistration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    training_fields, training_rows = read_tsv(training_tsv)
    needed = {"candidate_id", "parent_framework_cluster", "outer_fold", "R_dual_min", "teacher_source"}
    require(needed <= set(training_fields), f"training_fields_missing:{sorted(needed-set(training_fields))}")
    training = {row["candidate_id"]: row for row in training_rows}
    require(len(training) == len(training_rows), "training_duplicate_candidate")
    expected_count = int(preregistration["training"]["candidate_count"])
    expected_parents = int(preregistration["training"]["parent_cluster_count"])
    require(len(training) == expected_count, f"training_candidate_count:{len(training)}:{expected_count}")
    require(len({row["parent_framework_cluster"] for row in training_rows}) == expected_parents, "training_parent_count")
    source_config = preregistration["sources"]
    for source in SOURCES:
        selected = [row for row in training_rows if row["teacher_source"] == source]
        require(len(selected) == int(source_config[source]["candidates"]), f"training_source_candidates:{source}")
        require(len({row["parent_framework_cluster"] for row in selected}) == int(source_config[source]["parent_clusters"]), f"training_source_parents:{source}")
    require({row["teacher_source"] for row in training_rows} == set(SOURCES), "training_source_closure")
    require(len(prediction_tsvs) == 5, f"collector_requires_five_prediction_files:{len(prediction_tsvs)}")
    predictions: list[dict[str, Any]] = []
    file_audit = []
    for path in prediction_tsvs:
        fields, rows = read_tsv(path)
        require(REQUIRED_PREDICTION_FIELDS <= set(fields), f"prediction_fields_missing:{path}")
        predictions.extend(rows)
        file_audit.append({"path": str(path), "rows": len(rows), "sha256": sha256_file(path)})
    identifiers = [row["candidate_id"] for row in predictions]
    require(len(identifiers) == len(set(identifiers)), "prediction_duplicate_candidate")
    require(set(identifiers) == set(training), "prediction_candidate_exact_closure")
    parent_fold: dict[str, int] = {}
    joined = []
    for row in predictions:
        candidate = row["candidate_id"]
        truth = training[candidate]
        require(row["parent_framework_cluster"] == truth["parent_framework_cluster"], f"prediction_parent:{candidate}")
        require(int(row["outer_fold"]) == int(truth["outer_fold"]), f"prediction_fold:{candidate}")
        require(abs(float(row["R_dual_min"]) - float(truth["R_dual_min"])) <= 1e-9, f"prediction_target:{candidate}")
        if "teacher_source" in row and row["teacher_source"]:
            require(row["teacher_source"] == truth["teacher_source"], f"prediction_source:{candidate}")
        values = [float(row[field]) for field in ("R_dual_min", "m2_prediction", "residue_prediction")]
        require(all(math.isfinite(value) for value in values), f"prediction_nonfinite:{candidate}")
        parent = truth["parent_framework_cluster"]
        fold = int(truth["outer_fold"])
        require(parent not in parent_fold or parent_fold[parent] == fold, f"parent_cross_outer_fold:{parent}")
        parent_fold[parent] = fold
        joined.append({**row, "teacher_source": truth["teacher_source"]})
    require(set(parent_fold.values()) == set(range(5)), f"outer_fold_closure:{sorted(set(parent_fold.values()))}")
    joined.sort(key=lambda row: row["candidate_id"])
    return joined, file_audit


def promotion_report(
    rows: Sequence[Mapping[str, Any]],
    preregistration: Mapping[str, Any],
    *,
    bootstrap_repetitions: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    gates = preregistration["promotion_gates"]
    source_rows = {source: [row for row in rows if row["teacher_source"] == source] for source in SOURCES}
    global_m2 = metrics(rows, "m2_prediction", int(gates["global_top20_budget"]))
    global_model = metrics(rows, "residue_prediction", int(gates["global_top20_budget"]))
    source_budgets = {V4D: int(gates["v4d_top20_budget"]), V4H: int(gates["v4h_top20_budget"])}
    stratified = {}
    for source in SOURCES:
        baseline = metrics(source_rows[source], "m2_prediction", source_budgets[source])
        model = metrics(source_rows[source], "residue_prediction", source_budgets[source])
        source_bootstrap = parent_bootstrap(
            source_rows[source],
            repetitions=bootstrap_repetitions,
            seed=bootstrap_seed,
        )
        stratified[source] = {
            "rows": len(source_rows[source]),
            "parents": len({row["parent_framework_cluster"] for row in source_rows[source]}),
            "M2": baseline,
            "V2": model,
            "delta_spearman": model["spearman"] - baseline["spearman"],
            "mae_degradation": model["mae"] - baseline["mae"],
            "top20_net_hit_gain": model["top20_hits"] - baseline["top20_hits"],
            "parent_outcomes": parent_outcomes(
                source_rows[source],
                win_delta=float(gates["parent_win_delta_min"]),
                loss_delta=float(gates["parent_loss_delta_max"]),
            ),
            "parent_bootstrap": source_bootstrap,
        }
    global_parents = parent_outcomes(
        rows,
        win_delta=float(gates["parent_win_delta_min"]),
        loss_delta=float(gates["parent_loss_delta_max"]),
    )
    bootstrap = parent_bootstrap(rows, repetitions=bootstrap_repetitions, seed=bootstrap_seed)
    checks = {
        "global_spearman_delta_min": global_model["spearman"] - global_m2["spearman"] >= float(gates["global_spearman_delta_min"]),
        "v4d_spearman_non_degradation": stratified[V4D]["delta_spearman"] >= float(gates["v4d_spearman_delta_min"]),
        "v4h_spearman_non_degradation": stratified[V4H]["delta_spearman"] >= float(gates["v4h_spearman_delta_min"]),
        "global_parent_wins_gt_losses": global_parents["counts"]["WIN"] > global_parents["counts"]["LOSS"],
        "v4d_parent_wins_gte_losses": stratified[V4D]["parent_outcomes"]["counts"]["WIN"] >= stratified[V4D]["parent_outcomes"]["counts"]["LOSS"],
        "v4h_parent_wins_gte_losses": stratified[V4H]["parent_outcomes"]["counts"]["WIN"] >= stratified[V4H]["parent_outcomes"]["counts"]["LOSS"],
        "global_top20_net_hit_gain": global_model["top20_hits"] - global_m2["top20_hits"] >= int(gates["global_top20_net_hit_gain_min"]),
        "v4d_top20_net_hit_gain": stratified[V4D]["top20_net_hit_gain"] >= int(gates["per_source_top20_net_hit_gain_min"]),
        "v4h_top20_net_hit_gain": stratified[V4H]["top20_net_hit_gain"] >= int(gates["per_source_top20_net_hit_gain_min"]),
        "parent_bootstrap_positive_fraction": bootstrap["positive_fraction"] >= float(gates["parent_bootstrap_positive_fraction_min"]),
        "parent_bootstrap_median_positive": bootstrap["median_delta_spearman"] > 0.0,
        "v4d_parent_bootstrap_positive_fraction": stratified[V4D]["parent_bootstrap"]["positive_fraction"] >= float(gates["per_source_parent_bootstrap_positive_fraction_min"]),
        "v4d_parent_bootstrap_median_nonnegative": stratified[V4D]["parent_bootstrap"]["median_delta_spearman"] >= float(gates["per_source_parent_bootstrap_median_delta_min"]),
        "v4h_parent_bootstrap_positive_fraction": stratified[V4H]["parent_bootstrap"]["positive_fraction"] >= float(gates["per_source_parent_bootstrap_positive_fraction_min"]),
        "v4h_parent_bootstrap_median_nonnegative": stratified[V4H]["parent_bootstrap"]["median_delta_spearman"] >= float(gates["per_source_parent_bootstrap_median_delta_min"]),
        "v4d_mae_guardrail": stratified[V4D]["mae_degradation"] <= float(gates["per_source_mae_max_degradation"]),
        "v4h_mae_guardrail": stratified[V4H]["mae_degradation"] <= float(gates["per_source_mae_max_degradation"]),
    }
    status = gates["positive_status"] if all(checks.values()) else gates["negative_status"]
    return {
        "status": status,
        "all_required": True,
        "gates": checks,
        "failed_gates": sorted(name for name, passed in checks.items() if not passed),
        "global": {
            "M2": global_m2,
            "V2": global_model,
            "delta_spearman": global_model["spearman"] - global_m2["spearman"],
            "top20_net_hit_gain": global_model["top20_hits"] - global_m2["top20_hits"],
            "parent_outcomes": global_parents,
        },
        "source_stratified": stratified,
        "parent_bootstrap": bootstrap,
    }


def collect(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "collector_output_must_not_exist")
    preregistration = validate_preregistration(args.preregistration)
    rows, input_audit = validate_and_join_rows(args.training_tsv, args.prediction_tsv, preregistration)
    decision = promotion_report(
        rows,
        preregistration,
        bootstrap_repetitions=args.bootstrap_repetitions,
        bootstrap_seed=args.bootstrap_seed,
    )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    oof_path = args.output_dir / "residue_v2_nested_oof_predictions.tsv"
    fields = [
        "candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold",
        "R_dual_min", "m2_prediction", "residue_prediction",
    ]
    with oof_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row[field] for field in fields} for row in rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": decision["status"],
        "claim_boundary": CLAIM_BOUNDARY,
        "candidate_count": len(rows),
        "parent_count": len({row["parent_framework_cluster"] for row in rows}),
        "source_counts": {source: sum(row["teacher_source"] == source for row in rows) for source in SOURCES},
        "training_tsv_sha256": sha256_file(args.training_tsv),
        "preregistration_sha256": sha256_file(args.preregistration),
        "prediction_inputs": input_audit,
        "promotion": decision,
        "outputs": {"oof_predictions_sha256": sha256_file(oof_path)},
        "teacher_source_usage": "collector audit and source-stratified evaluation only; never a model feature",
    }
    atomic_json(args.output_dir / "OOF_PROMOTION_REPORT.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--prediction-tsv", type=Path, action="append", required=True)
    value.add_argument("--preregistration", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--bootstrap-repetitions", type=int, default=1000)
    value.add_argument("--bootstrap-seed", type=int, default=20260718)
    return value


if __name__ == "__main__":
    print(json.dumps(collect(parser().parse_args()), indent=2, sort_keys=True))
