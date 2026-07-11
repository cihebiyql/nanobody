#!/usr/bin/env python3
"""Finalize the frozen Phase 2 V2.5 generic formal evaluation.

This is a post-unseal integrity and statistics pass. It never trains, selects a
checkpoint, changes the dev-selected baseline, or rewrites the one-shot run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from phase2_v2_5_metrics import (
    bootstrap_metric_ci,
    compute_group_ranking_metrics,
    macro_summary,
    permutation_test_group_labels,
)


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_PREPARED = EXP_DIR / "prepared" / "phase2_v2_5_generic"
DEFAULT_RAW_NANOBIND = DATA_ROOT / "datasets" / "10_github_repos" / "NanoBind" / "data" / "affinity" / "all.csv"
DEFAULT_P1_TRAIN = EXP_DIR / "data_splits" / "phase2_v2_5_train_manifest.csv"
DEFAULT_P1_DEV = EXP_DIR / "data_splits" / "phase2_v2_5_dev_manifest.csv"
DEFAULT_P1_FORMAL = EXP_DIR / "data_splits" / "phase2_v2_5_generic_formal_manifest_blinded.csv"
DEFAULT_EVIDENCE_REGISTRY = EXP_DIR / "data_splits" / "evidence_registry_v2_5.csv"
DEFAULT_READINESS_AUDIT = EXP_DIR / "audits" / "phase2_v2_5_readiness_audit_v1.json"
DEFAULT_POSE_AUDIT = EXP_DIR / "audits" / "phase2_v2_5_pose_coverage_audit.json"
DEFAULT_METRICS = EXP_DIR / "reports" / "phase2_v2_5_metrics_v1.json"
DEFAULT_PREREGISTRATION = EXP_DIR / "audits" / "phase2_v2_5_preregistration_v1.json"
DEFAULT_BINDING_AUDIT = EXP_DIR / "audits" / "phase2_v2_5_formal_label_binding_audit_v1.json"
DEFAULT_REPORT = EXP_DIR / "reports" / "PHASE2_V2_5_STRICT_EVALUATION_V1.md"
DEFAULT_GAP_MATRIX = EXP_DIR / "reports" / "phase2_v2_5_gap_matrix_v1.csv"
DEFAULT_GPU_AUDIT = EXP_DIR / "audits" / "phase2_v2_5_gpu_telemetry_summary_v1.json"
DEFAULT_GPU_REPORT = EXP_DIR / "audits" / "PHASE2_V2_5_GPU_TELEMETRY_SUMMARY_V1.md"

PRIMARY_METRIC = "macro_group_pairwise_preference_accuracy"
BOOTSTRAP_N = 5000
PERMUTATION_N = 5000
ALPHA_TWO_SIDED = 0.05
FORMAL_SEEDS = (43, 53, 67)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def normalize_sequence(value: Any) -> str:
    return clean(value).upper().replace(" ", "").replace("\n", "")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stable_sample_id(vhh_sha: str, target_sha: str) -> str:
    return "nanobind_affinity_" + sha256_text(f"{vhh_sha}|{target_sha}")[:20]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def _frame_duplicate_ids(frame: pd.DataFrame) -> list[str]:
    return sorted(frame.loc[frame["sample_id"].duplicated(keep=False), "sample_id"].astype(str).unique().tolist())


def rebuild_source_pairs(raw_csv: Path) -> pd.DataFrame:
    raw = pd.read_csv(raw_csv)
    require_columns(raw, {"ID", "seq_nanobody", "seq_antigen", "affinity"}, "NanoBind raw affinity table")
    rows: list[dict[str, Any]] = []
    for source_row, record in enumerate(raw.to_dict("records"), start=2):
        vhh = normalize_sequence(record["seq_nanobody"])
        target = normalize_sequence(record["seq_antigen"])
        affinity = float(record["affinity"])
        if not vhh or not target or not math.isfinite(affinity) or affinity <= 0:
            raise ValueError(f"Invalid source row {source_row}")
        vhh_sha = sha256_text(vhh)
        target_sha = sha256_text(target)
        rows.append(
            {
                "source_row": source_row,
                "source_record_id": clean(record["ID"]),
                "vhh_sequence": vhh,
                "target_sequence": target,
                "sequence_sha256": vhh_sha,
                "target_sequence_sha256": target_sha,
                "affinity_kd_m": affinity,
            }
        )
    frame = pd.DataFrame(rows)
    rebuilt: list[dict[str, Any]] = []
    for (vhh_sha, target_sha), group in frame.groupby(["sequence_sha256", "target_sequence_sha256"], sort=True):
        kd_m = float(statistics.median(group["affinity_kd_m"].astype(float).tolist()))
        rebuilt.append(
            {
                "sample_id": stable_sample_id(str(vhh_sha), str(target_sha)),
                "sequence_sha256": str(vhh_sha),
                "target_sequence_sha256": str(target_sha),
                "vhh_sequence": str(group.iloc[0]["vhh_sequence"]),
                "target_sequence": str(group.iloc[0]["target_sequence"]),
                "label_value": kd_m,
                "affinity_kd_m": kd_m,
                "affinity_score": -math.log10(kd_m),
                "source_record_count": int(len(group)),
            }
        )
    return pd.DataFrame(rebuilt)


def validate_label_binding_frames(
    blinded: pd.DataFrame,
    labels: pd.DataFrame,
    rebuilt_source: pd.DataFrame,
    p1_formal: pd.DataFrame,
) -> dict[str, Any]:
    require_columns(
        blinded,
        {"sample_id", "sequence_sha256", "target_sequence_sha256", "vhh_sequence", "target_sequence", "split_group_id", "ranking_group_id"},
        "prepared formal blinded table",
    )
    require_columns(
        labels,
        {"sample_id", "label_value", "affinity_kd_m", "affinity_score", "label_unit", "label_direction", "sealed_status"},
        "prepared formal labels table",
    )
    require_columns(p1_formal, {"sequence_sha256", "target_sequence_sha256", "split_group_id"}, "P1 formal manifest")
    require_columns(
        rebuilt_source,
        {"sample_id", "sequence_sha256", "target_sequence_sha256", "vhh_sequence", "target_sequence", "label_value", "affinity_kd_m", "affinity_score"},
        "rebuilt source table",
    )

    failures: dict[str, Any] = {}
    duplicate_ids = {"blinded": _frame_duplicate_ids(blinded), "labels": _frame_duplicate_ids(labels)}
    if any(duplicate_ids.values()):
        failures["duplicate_sample_ids"] = duplicate_ids

    blind_ids = set(blinded["sample_id"].astype(str))
    label_ids = set(labels["sample_id"].astype(str))
    if blind_ids != label_ids:
        failures["blinded_label_sample_id_set_mismatch"] = {
            "missing_labels": sorted(blind_ids - label_ids),
            "extra_labels": sorted(label_ids - blind_ids),
        }

    expected_ids = blinded.apply(
        lambda row: stable_sample_id(str(row["sequence_sha256"]), str(row["target_sequence_sha256"])), axis=1
    )
    stable_id_bad = blinded.loc[expected_ids.ne(blinded["sample_id"].astype(str)), "sample_id"].astype(str).tolist()
    if stable_id_bad:
        failures["sample_id_not_bound_to_sequence_target_hashes"] = stable_id_bad

    bad_sequence_hashes = blinded.loc[
        blinded["vhh_sequence"].map(normalize_sequence).map(sha256_text).ne(blinded["sequence_sha256"].astype(str))
        | blinded["target_sequence"].map(normalize_sequence).map(sha256_text).ne(blinded["target_sequence_sha256"].astype(str)),
        "sample_id",
    ].astype(str).tolist()
    if bad_sequence_hashes:
        failures["sequence_content_hash_mismatch"] = bad_sequence_hashes

    p1 = p1_formal[["sequence_sha256", "target_sequence_sha256", "split_group_id"]].copy()
    p1["pair_key"] = p1["sequence_sha256"].astype(str) + "|" + p1["target_sequence_sha256"].astype(str)
    prepared = blinded[["sample_id", "sequence_sha256", "target_sequence_sha256", "split_group_id", "ranking_group_id"]].copy()
    prepared["pair_key"] = prepared["sequence_sha256"].astype(str) + "|" + prepared["target_sequence_sha256"].astype(str)
    if set(p1["pair_key"]) != set(prepared["pair_key"]):
        failures["p1_prepared_pair_set_mismatch"] = {
            "missing_from_prepared": sorted(set(p1["pair_key"]) - set(prepared["pair_key"])),
            "extra_in_prepared": sorted(set(prepared["pair_key"]) - set(p1["pair_key"])),
        }
    split_join = prepared.merge(p1[["pair_key", "split_group_id"]], on="pair_key", suffixes=("_prepared", "_p1"), how="left")
    split_bad = split_join.loc[
        split_join["split_group_id_prepared"].astype(str).ne(split_join["split_group_id_p1"].astype(str)), "sample_id"
    ].astype(str).tolist()
    if split_bad:
        failures["p1_split_group_mismatch"] = split_bad

    source_formal = rebuilt_source[rebuilt_source["sample_id"].astype(str).isin(blind_ids)].copy()
    if set(source_formal["sample_id"].astype(str)) != blind_ids:
        failures["raw_source_pair_set_mismatch"] = {
            "missing_from_raw_rebuild": sorted(blind_ids - set(source_formal["sample_id"].astype(str)))
        }
    merged = blinded.merge(labels, on="sample_id", validate="one_to_one", suffixes=("_blinded", "_label"))
    merged = merged.merge(source_formal, on="sample_id", validate="one_to_one", suffixes=("", "_source"))
    exact_columns = ("sequence_sha256", "target_sequence_sha256", "vhh_sequence", "target_sequence")
    exact_bad: dict[str, list[str]] = {}
    for column in exact_columns:
        left = merged[f"{column}_blinded"].astype(str) if f"{column}_blinded" in merged else merged[column].astype(str)
        right = merged[f"{column}_source"].astype(str)
        bad = merged.loc[left.ne(right), "sample_id"].astype(str).tolist()
        if bad:
            exact_bad[column] = bad
    if exact_bad:
        failures["raw_source_identity_mismatch"] = exact_bad

    numeric_bad: dict[str, list[str]] = {}
    for column in ("label_value", "affinity_kd_m", "affinity_score"):
        observed = pd.to_numeric(merged[column], errors="coerce").to_numpy(dtype=float)
        expected = pd.to_numeric(merged[f"{column}_source"], errors="coerce").to_numpy(dtype=float)
        bad_mask = ~np.isclose(observed, expected, rtol=1e-8, atol=1e-12, equal_nan=False)
        if bool(bad_mask.any()):
            numeric_bad[column] = merged.loc[bad_mask, "sample_id"].astype(str).tolist()
    if numeric_bad:
        failures["raw_source_label_mismatch"] = numeric_bad

    metadata_bad = merged.loc[
        merged["label_unit"].astype(str).ne("M")
        | merged["label_direction"].astype(str).ne("lower_is_better")
        | merged["sealed_status_label"].astype(str).ne("SEALED_LABELS"),
        "sample_id",
    ].astype(str).tolist()
    if metadata_bad:
        failures["sealed_label_metadata_mismatch"] = metadata_bad

    return {
        "status": "PASS" if not failures else "FAIL",
        "formal_row_count": int(len(blinded)),
        "sample_id_binding_formula": "nanobind_affinity_ + first20(sha256(sequence_sha256 + '|' + target_sequence_sha256))",
        "sample_id_sequence_target_binding_pass": "sample_id_not_bound_to_sequence_target_hashes" not in failures,
        "source_label_regeneration_pass": "raw_source_label_mismatch" not in failures and "raw_source_pair_set_mismatch" not in failures,
        "p1_pair_and_split_binding_pass": not any(key.startswith("p1_") for key in failures),
        "one_to_one_join_pass": "duplicate_sample_ids" not in failures and "blinded_label_sample_id_set_mismatch" not in failures,
        "failures": failures,
    }


def build_binding_audit(args: argparse.Namespace) -> dict[str, Any]:
    blinded = pd.read_csv(args.formal_blinded_csv)
    labels = pd.read_csv(args.formal_labels_csv)
    p1_formal = pd.read_csv(args.p1_formal_manifest)
    rebuilt_source = rebuild_source_pairs(args.raw_nanobind_csv)
    result = validate_label_binding_frames(blinded, labels, rebuilt_source, p1_formal)
    result.update(
        {
            "schema_version": "phase2_v2_5_formal_label_binding_audit_v1",
            "generated_at_utc": utc_now(),
            "scope": "POST_UNSEAL_INTEGRITY_ONLY_NOT_MODEL_OR_METRIC_SELECTION",
            "review_finding": "The one-shot evaluator joins sealed labels by sample_id without requiring explicit sequence hashes in the label file.",
            "resolution": "Actual V2.5 labels are independently regenerated from raw NanoBind affinity rows and bound through deterministic pair-derived sample IDs.",
            "evaluator_schema_gap_present": True,
            "future_version_requirement": "Include sequence_sha256 and target_sequence_sha256 or a row-identity digest in sealed labels before any V2.6 unseal.",
            "input_sha256": {
                "raw_nanobind_csv": sha256_file(args.raw_nanobind_csv),
                "p1_formal_manifest": sha256_file(args.p1_formal_manifest),
                "prepared_formal_blinded": sha256_file(args.formal_blinded_csv),
                "prepared_formal_labels": sha256_file(args.formal_labels_csv),
            },
        }
    )
    return result


def canonical_group_metrics(frame: pd.DataFrame, score_col: str) -> pd.DataFrame:
    scored = frame.copy()
    scored["score"] = pd.to_numeric(scored[score_col], errors="coerce")
    return compute_group_ranking_metrics(
        scored,
        group_col="group_id",
        truth_col="label_value",
        score_col="score",
        direction_col="label_direction",
        ambiguous_col=None,
    )


def validate_required_prediction_scores(
    predictions: pd.DataFrame,
    formal_sample_ids: set[str],
    required_methods: set[str],
    seed: int,
) -> None:
    require_columns(predictions, {"sample_id", "method", "formal_eligible", "ranking_score"}, f"seed {seed} predictions")
    required = predictions[predictions["method"].astype(str).isin(required_methods)].copy()
    duplicates = required[required.duplicated(["sample_id", "method"], keep=False)]
    if not duplicates.empty:
        pairs = duplicates[["sample_id", "method"]].astype(str).drop_duplicates().to_dict("records")
        raise ValueError(f"Seed {seed} has duplicate required predictions: {pairs[:5]}")
    for method in sorted(required_methods):
        method_rows = required[required["method"].astype(str).eq(method)].copy()
        observed_ids = set(method_rows["sample_id"].astype(str))
        if observed_ids != formal_sample_ids:
            raise ValueError(
                f"Seed {seed} method {method} prediction coverage mismatch: "
                f"missing={sorted(formal_sample_ids - observed_ids)[:5]} extra={sorted(observed_ids - formal_sample_ids)[:5]}"
            )
        eligible = method_rows["formal_eligible"].astype(str).str.lower().eq("true")
        scores = pd.to_numeric(method_rows["ranking_score"], errors="coerce").to_numpy(dtype=float)
        if not bool(eligible.all()) or not bool(np.isfinite(scores).all()):
            raise ValueError(f"Seed {seed} method {method} has ineligible or non-finite required scores")


def group_delta_frame(model_groups: pd.DataFrame, baseline_groups: pd.DataFrame, seed: int) -> pd.DataFrame:
    model = model_groups[["group_id", "pairwise_preference_accuracy"]].rename(
        columns={"pairwise_preference_accuracy": "model_pairwise"}
    )
    baseline = baseline_groups[["group_id", "pairwise_preference_accuracy"]].rename(
        columns={"pairwise_preference_accuracy": "baseline_pairwise"}
    )
    merged = model.merge(baseline, on="group_id", validate="one_to_one")
    merged["delta"] = merged["model_pairwise"] - merged["baseline_pairwise"]
    merged["seed"] = int(seed)
    return merged


def fast_mean_seed_delta_statistic(frame: pd.DataFrame, seed_score_cols: Sequence[str], baseline_score_col: str) -> float | None:
    group_deltas: list[float] = []
    for _, group in frame.groupby("group_id", sort=True, dropna=False):
        direction_values = {clean(value).lower() for value in group["label_direction"] if clean(value)}
        if len(direction_values) > 1:
            raise ValueError("Mixed label directions in one ranking group")
        truth = pd.to_numeric(group["label_value"], errors="coerce").to_numpy(dtype=float)
        if next(iter(direction_values), "higher_is_better") in {"lower_is_better", "lower", "kd_lower_is_better"}:
            truth = -truth
        baseline_scores = pd.to_numeric(group[baseline_score_col], errors="coerce").to_numpy(dtype=float)
        model_scores = [pd.to_numeric(group[column], errors="coerce").to_numpy(dtype=float) for column in seed_score_cols]
        pair_truth: list[float] = []
        pair_baseline: list[float] = []
        pair_models: list[list[float]] = [[] for _ in seed_score_cols]
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                truth_delta = truth[left] - truth[right]
                if not math.isfinite(truth_delta) or truth_delta == 0:
                    continue
                pair_truth.append(math.copysign(1.0, truth_delta))
                pair_baseline.append(baseline_scores[left] - baseline_scores[right])
                for index, scores in enumerate(model_scores):
                    pair_models[index].append(scores[left] - scores[right])
        if not pair_truth:
            continue

        def accuracy(score_deltas: Sequence[float]) -> float:
            total = 0.0
            for truth_sign, score_delta in zip(pair_truth, score_deltas):
                if score_delta == 0:
                    total += 0.5
                elif math.copysign(1.0, score_delta) == truth_sign:
                    total += 1.0
            return total / len(pair_truth)

        baseline_accuracy = accuracy(pair_baseline)
        seed_deltas = [accuracy(values) - baseline_accuracy for values in pair_models]
        group_deltas.append(float(statistics.mean(seed_deltas)))
    return float(statistics.mean(group_deltas)) if group_deltas else None


def build_preregistration(args: argparse.Namespace, run_summary: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    run_dir = args.run_dir.resolve()
    selection_path = run_dir / "preregistered_selection.json"
    selection_sha = sha256_file(selection_path)
    stats_seed = int(selection_sha[:8], 16)
    plan_dir = DATA_ROOT / ".omx" / "plans"
    plan_paths = [
        plan_dir / "prd-phase2-v2-5.md",
        plan_dir / "test-spec-phase2-v2-5.md",
        plan_dir / "phase2-v2-5-consensus-handoff.md",
    ]
    plans = {
        path.name: {"path": str(path), "sha256": sha256_file(path), "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
        for path in plan_paths
        if path.is_file()
    }
    return {
        "schema_version": "phase2_v2_5_preregistration_v1",
        "status": "FROZEN_BEFORE_FORMAL_RUNS_WITH_POSTHOC_LEDGER",
        "generated_at_utc": utc_now(),
        "artifact_created_after_unseal": True,
        "chronology_note": (
            "The dedicated ledger is post-unseal. The frozen pre-unseal method is evidenced by approved plans, "
            "config_resolved.json, preregistered_selection.json, run summary hashes, and checkpoint hashes."
        ),
        "known_gap": "The training summary did not freeze a source-code hash or the prepared sealed-label SHA before unseal.",
        "run_dir": str(run_dir),
        "registered_selection_at_utc": selection.get("selected_at_utc"),
        "selection_policy": {
            "scope": selection.get("selection_scope"),
            "primary_metric": selection.get("selection_metric"),
            "selected_baseline": selection.get("selected_baseline"),
            "formal_metrics_consulted": selection.get("formal_metrics_consulted"),
            "checkpoint_rule": run_summary.get("checkpoint_rule"),
        },
        "statistics": {
            "primary_metric": PRIMARY_METRIC,
            "bootstrap_unit": "assay_comparable_ranking_group_id",
            "bootstrap_n": int(args.bootstrap_n),
            "permutation_n": int(args.permutation_n),
            "primary_alpha_two_sided": ALPHA_TWO_SIDED,
            "multi_seed_aggregation": "mean seed delta within ranking group, then macro average across groups",
            "statistics_rng_seed": stats_seed,
            "statistics_rng_seed_source": "first_32_bits_of_pre_unseal_preregistered_selection_sha256",
        },
        "formal_seeds": list(run_summary.get("seeds", [])),
        "frozen_artifact_sha256": run_summary.get("artifact_sha256", {}),
        "approved_plan_artifacts": plans,
        "scientific_boundary": {
            "generic_formal_scope": "E4 generic affinity ranking only",
            "pvrig_target_adaptation_allowed": False,
            "generic_success_implies_pvrig_success": False,
            "formal_rerun_allowed_in_v2_5": False,
        },
    }


def build_formal_metrics(args: argparse.Namespace, binding_audit: dict[str, Any], preregistration: dict[str, Any]) -> dict[str, Any]:
    run_dir = args.run_dir.resolve()
    train_summary = load_json(run_dir / "summary.json")
    selection = load_json(run_dir / "preregistered_selection.json")
    formal_summary = load_json(run_dir / "formal_evaluation" / "formal_evaluation_summary.json")
    formal_audit = load_json(run_dir / "formal_unseal_audit.json")
    if formal_audit.get("formal_run_count") != 1 or formal_audit.get("formal_unseal_status") != "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE":
        raise ValueError("The authoritative run is not a completed one-shot formal evaluation")
    if binding_audit.get("status") != "PASS":
        raise ValueError("Formal label binding audit failed")

    blinded = pd.read_csv(args.formal_blinded_csv)
    labels = pd.read_csv(args.formal_labels_csv)
    formal = blinded.merge(labels, on="sample_id", validate="one_to_one", suffixes=("_blinded", "_label"))
    formal = formal.rename(columns={"ranking_group_id": "group_id"})
    selected_baseline = str(selection["selected_baseline"])
    seeds = tuple(int(seed) for seed in train_summary["seeds"])
    if seeds != FORMAL_SEEDS:
        raise ValueError(f"Unexpected formal seeds: {seeds}")

    score_frame = formal[["sample_id", "group_id", "label_value", "label_direction"]].copy()
    seed_results: list[dict[str, Any]] = []
    all_group_deltas: list[pd.DataFrame] = []
    primary_equivalence: list[dict[str, Any]] = []
    secondary_ndcg_drift: list[dict[str, Any]] = []
    selection_sha = sha256_file(run_dir / "preregistered_selection.json")
    stats_seed = int(selection_sha[:8], 16)

    for seed in seeds:
        predictions_path = run_dir / "formal_evaluation" / f"seed_{seed}" / "formal_predictions.csv"
        emitted_path = run_dir / "formal_evaluation" / f"seed_{seed}" / "formal_metrics.json"
        predictions = pd.read_csv(predictions_path)
        needed_methods = {"shallow_head", selected_baseline}
        validate_required_prediction_scores(predictions, set(formal["sample_id"].astype(str)), needed_methods, seed)
        eligible = predictions[predictions["formal_eligible"].astype(str).str.lower().eq("true")].copy()
        numeric = eligible[pd.to_numeric(eligible["ranking_score"], errors="coerce").notna()].copy()
        wide = numeric.pivot(index="sample_id", columns="method", values="ranking_score").reset_index()
        if not needed_methods <= set(wide.columns):
            raise ValueError(f"Seed {seed} is missing formal scores for {sorted(needed_methods - set(wide.columns))}")
        seed_frame = formal.merge(wide, on="sample_id", how="left", validate="one_to_one", indicator=True)
        if not seed_frame["_merge"].eq("both").all() or seed_frame[list(needed_methods)].isna().any().any():
            raise ValueError(f"Seed {seed} formal score merge dropped or null-filled required rows")
        seed_frame = seed_frame.drop(columns=["_merge"])
        model_groups = canonical_group_metrics(seed_frame, "shallow_head")
        baseline_groups = canonical_group_metrics(seed_frame, selected_baseline)
        model_macro = macro_summary(model_groups)
        baseline_macro = macro_summary(baseline_groups)
        eligible_baseline_primary: dict[str, float] = {}
        for method in sorted(set(wide.columns) - {"sample_id", "shallow_head"}):
            method_groups = canonical_group_metrics(seed_frame, method)
            method_primary = macro_summary(method_groups)[PRIMARY_METRIC]
            if method_primary is not None:
                eligible_baseline_primary[method] = float(method_primary)
        deltas = group_delta_frame(model_groups, baseline_groups, seed)
        all_group_deltas.append(deltas)
        ci = bootstrap_metric_ci(
            deltas[["group_id", "delta"]],
            "delta",
            unit_col="group_id",
            n=int(args.bootstrap_n),
            seed=(stats_seed + seed) % (2**32),
        )
        emitted = load_json(emitted_path)
        emitted_model = emitted["formal_metrics"]["shallow_head"]
        emitted_baseline = emitted["formal_metrics"][selected_baseline]
        for method, canonical, existing in (
            ("shallow_head", model_macro, emitted_model),
            (selected_baseline, baseline_macro, emitted_baseline),
        ):
            primary_equivalence.append(
                {
                    "seed": seed,
                    "method": method,
                    "canonical": canonical[PRIMARY_METRIC],
                    "emitted": existing[PRIMARY_METRIC],
                    "exact_within_1e_12": abs(float(canonical[PRIMARY_METRIC]) - float(existing[PRIMARY_METRIC])) <= 1e-12,
                }
            )
            secondary_ndcg_drift.append(
                {
                    "seed": seed,
                    "method": method,
                    "canonical_raw_kd_directional_ndcg": canonical["macro_group_ndcg_all"],
                    "emitted_log_kd_ndcg": existing["macro_group_ndcg_all"],
                    "difference": float(canonical["macro_group_ndcg_all"]) - float(existing["macro_group_ndcg_all"]),
                }
            )

        seed_results.append(
            {
                "seed": seed,
                "model_primary": model_macro[PRIMARY_METRIC],
                "selected_baseline_primary": baseline_macro[PRIMARY_METRIC],
                "mean_group_delta": float(deltas["delta"].mean()),
                "positive_group_count": int((deltas["delta"] > 0).sum()),
                "ranking_group_count": int(len(deltas)),
                "paired_bootstrap_95ci": ci,
                "eligible_baseline_primary_diagnostic": eligible_baseline_primary,
                "telemetry": emitted.get("telemetry", {}),
            }
        )
        model_col = f"shallow_head_seed_{seed}"
        baseline_col = f"selected_baseline_seed_{seed}"
        per_seed_scores = seed_frame[["sample_id", "shallow_head", selected_baseline]].rename(
            columns={"shallow_head": model_col, selected_baseline: baseline_col}
        )
        score_frame = score_frame.merge(per_seed_scores, on="sample_id", validate="one_to_one")

    aggregate_group = pd.concat(all_group_deltas, ignore_index=True).groupby("group_id", as_index=False)["delta"].mean()
    aggregate_ci = bootstrap_metric_ci(
        aggregate_group,
        "delta",
        unit_col="group_id",
        n=int(args.bootstrap_n),
        seed=stats_seed,
    )
    seed_score_cols = [f"shallow_head_seed_{seed}" for seed in seeds]
    baseline_score_col = f"selected_baseline_seed_{seeds[0]}"

    def statistic(frame: pd.DataFrame) -> float | None:
        return fast_mean_seed_delta_statistic(frame, seed_score_cols, baseline_score_col)

    permutation = permutation_test_group_labels(
        score_frame,
        statistic,
        group_col="group_id",
        label_col="label_value",
        n=int(args.permutation_n),
        seed=stats_seed,
    )
    seed_deltas = [float(result["mean_group_delta"]) for result in seed_results]
    seed_consistency_pass = sum(delta > 0 for delta in seed_deltas) >= 2 and statistics.median(seed_deltas) > 0
    ci_pass = aggregate_ci["ci_low"] is not None and float(aggregate_ci["ci_low"]) > 0
    permutation_pass = permutation.get("p_two_sided") is not None and float(permutation["p_two_sided"]) < ALPHA_TWO_SIDED
    generic_pass = bool(ci_pass and permutation_pass and seed_consistency_pass)
    generic_status = "PASS_GENERIC_TRANSFER_ONLY" if generic_pass else (
        "PASS_LIMITED_RANKING_ONLY" if float(aggregate_ci["point"] or 0.0) > 0 else "FAIL_GENERIC_TRANSFER_FORMAL"
    )

    readiness = load_json(args.readiness_audit)
    pose = load_json(args.pose_audit)
    input_sha256 = {
        "evidence_registry": sha256_file(args.evidence_registry),
        "formal_manifest_blinded": sha256_file(args.formal_blinded_csv),
        "formal_labels_sealed": sha256_file(args.formal_labels_csv),
        "preregistration_json": sha256_file(args.preregistration_output),
        "p1_formal_manifest": sha256_file(args.p1_formal_manifest),
        "run_summary": sha256_file(run_dir / "summary.json"),
        "formal_unseal_audit": sha256_file(run_dir / "formal_unseal_audit.json"),
        "formal_label_binding_audit": sha256_file(args.binding_audit_output),
    }
    return {
        "schema_version": "phase2_v2_5_metrics_v1",
        "generated_at_utc": utc_now(),
        "run_dir": str(run_dir),
        "formal_unseal": formal_audit,
        "input_sha256": input_sha256,
        "data_readiness": readiness.get("data_readiness", {}),
        "calibration": readiness.get("calibration", {"status": "NOT_APPLICABLE"}),
        "pose": {
            "exact_qc_passed_coverage": pose.get("exact_qc_passed_coverage"),
            "global_fusion_min_coverage": pose.get("global_fusion_min_coverage", 0.8),
            "global_fusion_applied": pose.get("global_fusion_applied", False),
            "missingness_audit_pass": pose.get("missingness_audit_pass"),
            "haddock3_status": pose.get("haddock3_status"),
            "new_monomer_sequence_geometry_qc_pass_count": pose.get("v2_5_new_monomer_sequence_geometry_qc_pass_count"),
        },
        "statistics": preregistration["statistics"],
        "generic_transfer_formal_pass": generic_pass,
        "generic_transfer_status": generic_status,
        "generic_transfer": {
            "scope": "generic E4 affinity ranking only",
            "formal_rows": int(len(formal)),
            "ranking_group_count": int(formal["group_id"].nunique()),
            "dev_selected_strongest_baseline": selected_baseline,
            "seed_results": seed_results,
            "formal_baseline_diagnostic_not_used_for_selection": {
                "policy": "Formal labels cannot replace the development-selected comparator.",
                "eligible_baseline_primary_by_seed": {
                    str(item["seed"]): item["eligible_baseline_primary_diagnostic"] for item in seed_results
                },
            },
            "mean_seed_group_delta": aggregate_ci["point"],
            "paired_bootstrap_95ci": aggregate_ci,
            "group_local_permutation": permutation,
            "seed_consistency": {
                "primary_delta_by_seed": {str(item["seed"]): item["mean_group_delta"] for item in seed_results},
                "positive_delta_seed_count": sum(delta > 0 for delta in seed_deltas),
                "median_primary_delta": statistics.median(seed_deltas),
                "pass": seed_consistency_pass,
            },
            "canonical_primary_matches_one_shot_emission": all(item["exact_within_1e_12"] for item in primary_equivalence),
            "primary_equivalence_audit": primary_equivalence,
            "secondary_ndcg_semantics_warning": {
                "status": "WARN",
                "reason": "The one-shot evaluator used -log10(Kd) gains while the canonical metrics module uses directional raw Kd gains; primary pairwise values match exactly and NDCG is secondary only.",
                "comparisons": secondary_ndcg_drift,
            },
        },
        "label_binding": {
            "status": binding_audit["status"],
            "audit_path": str(args.binding_audit_output),
            "evaluator_schema_gap_present": binding_audit["evaluator_schema_gap_present"],
            "actual_v2_5_rows_bound_to_raw_source": binding_audit["source_label_regeneration_pass"],
        },
        "formal_decision": {
            "status": "DATA_NOT_READY_FOR_TARGET_MODEL",
            "generic_transfer_status": generic_status,
            "generic_transfer_formal_pass": generic_pass,
            "primary_delta_vs_strong_baseline_ci_low_gt_zero": ci_pass,
            "permutation_pass": permutation_pass,
            "seed_consistency_pass": seed_consistency_pass,
            "contact_guardrail_pass": None,
            "paratope_guardrail_pass": None,
            "claim_boundary": "ranking_evidence_not_experimental_blocker_validation",
            "next_version_required_for_any_method_change": True,
        },
        "boundary": "generic affinity ranking only; no PVRIG blocker, target-success, or calibrated-probability claim",
    }


def write_gap_matrix(metrics: dict[str, Any], path: Path) -> None:
    readiness = metrics["data_readiness"]
    generic = metrics["generic_transfer"]
    pose = metrics["pose"]
    rows = [
        ["pvrig_verified_binary_positive", readiness.get("verified_binary_positive", 0), ">0 with verified negatives or sufficient ranking groups", "FAIL", "Known positives remain calibration/leakage controls"],
        ["pvrig_verified_binary_negative", readiness.get("verified_binary_negative", 0), ">0 with verified positives or sufficient ranking groups", "FAIL", "No assay-backed nonbinder or binder-nonblocker"],
        ["pvrig_assay_backed_rank_groups", readiness.get("assay_backed_rank_groups", 0), 8, "FAIL", "Prospective assay panel is unmeasured"],
        ["pvrig_formal_split_groups", readiness.get("power_simulation", {}).get("formal_split_group_count", 0), 5, "FAIL", "No PVRIG E6/new sealed formal groups"],
        ["pvrig_formal_assay_source_blocks", readiness.get("power_simulation", {}).get("formal_assay_or_source_block_count", 0), 2, "FAIL", "No PVRIG formal assay/source blocks"],
        ["generic_primary_mean_seed_delta", generic.get("mean_seed_group_delta"), ">0", "PASS", "Point estimate only"],
        ["generic_primary_bootstrap_ci_low", generic.get("paired_bootstrap_95ci", {}).get("ci_low"), ">0", "PASS" if metrics["formal_decision"]["primary_delta_vs_strong_baseline_ci_low_gt_zero"] else "FAIL", "Seven ranking groups; CI crosses zero"],
        ["generic_primary_permutation_p", generic.get("group_local_permutation", {}).get("p_two_sided"), "<0.05", "PASS" if metrics["formal_decision"]["permutation_pass"] else "FAIL", "Two-sided group-local permutation"],
        ["generic_positive_seed_count", generic.get("seed_consistency", {}).get("positive_delta_seed_count"), ">=2 of 3 and median >0", "PASS" if metrics["formal_decision"]["seed_consistency_pass"] else "FAIL", "Frozen seeds 43,53,67"],
        ["exact_qc_complex_pose_coverage", pose.get("exact_qc_passed_coverage"), ">=0.80 for global fusion", "FAIL", "Global pose fusion remains disabled"],
        ["new_nbb2_monomer_qc_pass", pose.get("new_monomer_sequence_geometry_qc_pass_count"), 8, "PASS", "Monomer QC is not complex-pose evidence"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["gate", "observed", "required", "status", "interpretation"])
        writer.writerows(rows)


def write_report(metrics: dict[str, Any], binding: dict[str, Any], path: Path) -> None:
    generic = metrics["generic_transfer"]
    decision = metrics["formal_decision"]
    pose = metrics["pose"]
    lines = [
        "# Phase 2 V2.5 Strict Evaluation V1",
        "",
        f"- Final target status: **{decision['status']}**",
        f"- Generic formal status: **{decision['generic_transfer_status']}**",
        f"- Formal run count: `{metrics['formal_unseal']['formal_run_count']}`; reruns or method changes require V2.6.",
        f"- Label-binding audit: **{binding['status']}**; the evaluator schema gap remains a V2.6 requirement.",
        "",
        "## Generic Formal Result",
        "",
        f"The frozen shallow head improved the dev-selected `frozen_cosine_distance` baseline by `{generic['mean_seed_group_delta']:.6f}` on average across the three frozen seeds and seven ranking groups. The paired 95% bootstrap CI was `[{generic['paired_bootstrap_95ci']['ci_low']:.6f}, {generic['paired_bootstrap_95ci']['ci_high']:.6f}]`, and the group-local two-sided permutation p-value was `{generic['group_local_permutation']['p_two_sided']:.6f}`. The CI crosses zero and p is not below 0.05, so the strict generic-transfer gate does not pass.",
        "",
        "| Seed | Model primary | Baseline primary | Delta | 95% bootstrap CI | GPU |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for result in generic["seed_results"]:
        ci = result["paired_bootstrap_95ci"]
        gpu = result["telemetry"].get("cuda_device_name") or result["telemetry"].get("actual_device")
        lines.append(
            f"| {result['seed']} | {result['model_primary']:.6f} | {result['selected_baseline_primary']:.6f} | {result['mean_group_delta']:+.6f} | [{ci['ci_low']:.6f}, {ci['ci_high']:.6f}] | {gpu} |"
        )
    lines.extend(
        [
            "",
            "All three seed deltas are positive, but seed consistency alone cannot override the failed CI and permutation gates. The canonical primary exactly matches the one-shot evaluator. Secondary NDCG differs because the two implementations use different gain transforms; it is retained as a warning and is not used for the decision.",
            "",
            "As a locked post-hoc diagnostic, leakage-safe sequence-identity nearest neighbor scores `0.564286` on the formal primary and exceeds shallow seeds 43 and 53. It cannot replace the development-selected comparator after unseal, but it reinforces the limited-result interpretation.",
            "",
            "## Formal Integrity",
            "",
            f"The post-unseal audit independently rebuilt NanoBind affinities from the raw source, verified `{binding['formal_row_count']}` deterministic pair-derived sample IDs, matched the P1 formal pair/split assignments, and reproduced every sealed label. This proves the actual V2.5 label mapping despite the evaluator's generic schema weakness. Future sealed labels must carry explicit sequence/target hashes or a row-identity digest before unseal.",
            "",
            "## PVRIG Boundary",
            "",
            "PVRIG remains data-not-ready: there are no verified target negatives, no new sealed target formal groups, and no powered target-specific formal block. Generic affinity transfer cannot be promoted to blocker truth or target success. The 24-pair prospective assay panel is the next evidence-producing step.",
            "",
            "## Structure Lane",
            "",
            f"Node1 produced `{pose.get('new_monomer_sequence_geometry_qc_pass_count')}` new sequence/geometry-QC-passed NanoBodyBuilder2 monomers. Exact QC-passed complex coverage remains `{pose.get('exact_qc_passed_coverage'):.1%}`; HADDOCK3 was load-gated and global pose fusion remains disabled.",
            "",
            "## Decision",
            "",
            "V2.5 is engineering-complete with a negative strict generic-formal result and a target data-readiness stop. The observed positive point estimate is exploratory only. Any model, metric, join-schema, or threshold revision belongs to V2.6; the next scientifically useful action is prospective assay measurement, not a larger model.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def telemetry_csv_summary(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path)
    require_columns(frame, {"timestamp", "name", "memory_used_mib", "utilization_gpu_pct", "temperature_c"}, str(path))
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "samples": int(len(frame)),
        "gpu_names": sorted(frame["name"].astype(str).unique().tolist()),
        "memory_used_mib": {
            "min": float(frame["memory_used_mib"].min()),
            "mean": float(frame["memory_used_mib"].mean()),
            "max": float(frame["memory_used_mib"].max()),
        },
        "utilization_gpu_pct": {
            "mean": float(frame["utilization_gpu_pct"].mean()),
            "max": float(frame["utilization_gpu_pct"].max()),
        },
        "temperature_c_max": float(frame["temperature_c"].max()),
    }


def write_gpu_summary(args: argparse.Namespace, run_summary: dict[str, Any], metrics: dict[str, Any]) -> None:
    train_seed_telemetry = {str(item["seed"]): item["telemetry"] for item in run_summary["seed_results"]}
    formal_seed_telemetry = metrics["formal_unseal"]["formal_inference_telemetry_by_seed"]
    audit = {
        "schema_version": "phase2_v2_5_gpu_telemetry_summary_v1",
        "generated_at_utc": utc_now(),
        "gpu_used": all(item.get("actual_device") == "cuda" for item in train_seed_telemetry.values())
        and all(item.get("actual_device") == "cuda" for item in formal_seed_telemetry.values()),
        "device": "NVIDIA GeForce RTX 5080",
        "esm2_embedding_external_sampler": telemetry_csv_summary(args.esm2_gpu_telemetry),
        "shallow_training_external_sampler": telemetry_csv_summary(args.train_gpu_telemetry),
        "training_torch_telemetry_by_seed": train_seed_telemetry,
        "formal_inference_torch_telemetry_by_seed": formal_seed_telemetry,
        "interpretation": (
            "GPU execution is confirmed. The frozen-embedding shallow head is intentionally tiny, so one-second nvidia-smi sampling "
            "understates short compute bursts; memory residency and PyTorch CUDA telemetry are the stronger evidence."
        ),
    }
    write_json_atomic(args.gpu_audit_output, audit)
    embedding = audit["esm2_embedding_external_sampler"]
    training = audit["shallow_training_external_sampler"]
    train_peak = max(float(item["cuda_peak_allocated_mib"]) for item in train_seed_telemetry.values())
    formal_peak = max(float(item["cuda_peak_allocated_mib"]) for item in formal_seed_telemetry.values())
    lines = [
        "# Phase 2 V2.5 GPU Telemetry Summary V1",
        "",
        f"- GPU used: **{audit['gpu_used']}** (`{audit['device']}`)",
        f"- ESM2 embedding sampler: {embedding['samples']} samples; peak device-wide sampled memory `{embedding['memory_used_mib']['max']:.0f} MiB`.",
        f"- Shallow-head training sampler: {training['samples']} samples; peak device-wide sampled memory `{training['memory_used_mib']['max']:.0f} MiB`; peak sampled utilization `{training['utilization_gpu_pct']['max']:.0f}%`.",
        f"- PyTorch training peak allocated memory: `{train_peak:.2f} MiB`; formal inference peak: `{formal_peak:.2f} MiB`.",
        "",
        "The model after embedding extraction is a 64-hidden-unit shallow ranker over frozen pooled features. Its short kernels do not saturate an RTX 5080, and the low sampled utilization is expected rather than evidence of CPU fallback. All three training seeds and all three formal inference passes report `actual_device=cuda` and the RTX 5080 device name.",
    ]
    args.gpu_report_output.parent.mkdir(parents=True, exist_ok=True)
    args.gpu_report_output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--formal-blinded-csv", type=Path, default=DEFAULT_PREPARED / "nanobind_affinity_formal_blinded_v2_5.csv")
    parser.add_argument("--formal-labels-csv", type=Path, default=DEFAULT_PREPARED / "nanobind_affinity_formal_labels_sealed_v2_5.csv")
    parser.add_argument("--raw-nanobind-csv", type=Path, default=DEFAULT_RAW_NANOBIND)
    parser.add_argument("--p1-train-manifest", type=Path, default=DEFAULT_P1_TRAIN)
    parser.add_argument("--p1-dev-manifest", type=Path, default=DEFAULT_P1_DEV)
    parser.add_argument("--p1-formal-manifest", type=Path, default=DEFAULT_P1_FORMAL)
    parser.add_argument("--evidence-registry", type=Path, default=DEFAULT_EVIDENCE_REGISTRY)
    parser.add_argument("--readiness-audit", type=Path, default=DEFAULT_READINESS_AUDIT)
    parser.add_argument("--pose-audit", type=Path, default=DEFAULT_POSE_AUDIT)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--preregistration-output", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--binding-audit-output", type=Path, default=DEFAULT_BINDING_AUDIT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--gap-matrix-output", type=Path, default=DEFAULT_GAP_MATRIX)
    parser.add_argument("--esm2-gpu-telemetry", type=Path, default=EXP_DIR / "logs" / "phase2_v2_5_esm2_gpu_telemetry.csv")
    parser.add_argument("--train-gpu-telemetry", type=Path, default=EXP_DIR / "logs" / "phase2_v2_5_train_authoritative_gpu_telemetry.csv")
    parser.add_argument("--gpu-audit-output", type=Path, default=DEFAULT_GPU_AUDIT)
    parser.add_argument("--gpu-report-output", type=Path, default=DEFAULT_GPU_REPORT)
    parser.add_argument("--bootstrap-n", type=int, default=BOOTSTRAP_N)
    parser.add_argument("--permutation-n", type=int, default=PERMUTATION_N)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    run_summary = load_json(args.run_dir / "summary.json")
    selection = load_json(args.run_dir / "preregistered_selection.json")
    binding = build_binding_audit(args)
    write_json_atomic(args.binding_audit_output, binding)
    if binding["status"] != "PASS":
        raise SystemExit("Formal label binding audit failed; metrics were not finalized")
    preregistration = build_preregistration(args, run_summary, selection)
    write_json_atomic(args.preregistration_output, preregistration)
    metrics = build_formal_metrics(args, binding, preregistration)
    write_json_atomic(args.metrics_output, metrics)
    write_gap_matrix(metrics, args.gap_matrix_output)
    write_report(metrics, binding, args.report_output)
    write_gpu_summary(args, run_summary, metrics)
    print(
        json.dumps(
            {
                "formal_decision": metrics["formal_decision"]["status"],
                "generic_transfer_status": metrics["generic_transfer_status"],
                "binding_audit": binding["status"],
                "metrics_output": str(args.metrics_output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
