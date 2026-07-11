#!/usr/bin/env python3
"""Strict final-audit sidecar for Phase 2 V2.4 artifacts.

The validator is intentionally side-effect-light: it reads completed artifacts,
writes optional audit outputs, and keeps all candidate-ranking evidence bounded as
computational proxy evidence, not biological validation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_JSON = EXP_DIR / "audits" / "phase2_v2_4_final_audit_v1.json"
DEFAULT_MARKDOWN = EXP_DIR / "audits" / "PHASE2_V2_4_FINAL_AUDIT_V1.md"
REQUIRED_SEEDS = (43, 53, 67)
PROXY_BOUNDARY = "V2.4 ranks constructed proxy contrasts only; it is not a calibrated biological classifier or blocker-validation assay."
BIOLOGICAL_CLAIM_FORBIDDEN = (
    "biologically validated",
    "validated biological classifier",
    "validated blocker",
    "proven blocker",
    "verified non-binder",
    "verified nonbinder",
    "calibrated binding probability",
    "classifier boundary passed",
)
DEFAULT_PREFERENCE_THRESHOLDS = {
    "ranking_mrr_mean_min": 0.56,
    "ranking_hit_at_1_mean_min": 0.25,
    "hard_negative_win_mean_min": 0.60,
    "contact_auprc_mean_floor": 0.489729,
    "paratope_auprc_mean_floor": 0.600628,
    "v2_3_ranking_mrr_mean": 0.524921,
    "v2_3_random_mrr_mean": 0.532976,
}


@dataclass
class Check:
    name: str
    status: str
    evidence: Any
    severity: str = "REQUIRED"

    @property
    def passed(self) -> bool:
        return self.status in {"PASS", "WARN"}


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."} else text


def normalize_sequence(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper() if "A" <= ch <= "Z")


def sequence_hash(sequence: Any) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json_value(path: Path) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty JSON artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    value = load_json_value(path)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty CSV artifact: {path}")
    return pd.read_csv(path)


def rel_or_abs(path: Path) -> str:
    try:
        return str(path.relative_to(DATA_ROOT))
    except ValueError:
        return str(path)


def coerce_seed(value: Any) -> int | None:
    text = clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        match = re.search(r"seed(\d+)", text)
        return int(match.group(1)) if match else None


def discover_runs(exp_dir: Path, required_seeds: tuple[int, ...]) -> list[Path]:
    candidates: dict[int, list[Path]] = {seed: [] for seed in required_seeds}
    for metrics_path in sorted((exp_dir / "runs").glob("phase2_v2_4*/test_metrics.json")):
        seed = coerce_seed(metrics_path.parent.name)
        if seed in required_seeds:
            candidates[seed].append(metrics_path.parent)
    by_seed: dict[int, Path] = {}
    for seed, paths in candidates.items():
        if paths:
            by_seed[seed] = sorted(paths, key=lambda path: ("strict" not in path.name.lower(), -path.stat().st_mtime))[0]
    return [by_seed[seed] for seed in required_seeds if seed in by_seed]


def parse_iso_datetime(value: Any) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def first_telemetry_timestamp(path: Path) -> datetime | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle), None)
    return parse_iso_datetime(row.get("timestamp")) if row else None


def finite_leaf_values(value: Any, prefix: str = "") -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            out.extend(finite_leaf_values(child, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(finite_leaf_values(child, f"{prefix}[{idx}]"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out.append((prefix, float(value)))
    return out


def has_boundary_text(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower()
    return (
        ("proxy" in text or "proxies" in text)
        and "not" in text
        and ("classifier" in text or "non-binder" in text or "nonbinder" in text or "blocker" in text)
    )


def add_check(checks: list[Check], name: str, condition: bool, evidence: Any, severity: str = "REQUIRED") -> None:
    if condition:
        status = "PASS"
    elif severity == "WARN":
        status = "WARN"
    else:
        status = "FAIL"
    checks.append(Check(name=name, status=status, evidence=evidence, severity=severity))


def extract_candidate_ids(frame: pd.DataFrame) -> set[str]:
    for column in ("candidate_id", "candidate_pair_id", "sample_id"):
        if column in frame.columns:
            return {clean(v) for v in frame[column] if clean(v)}
    return set()


def audit_manifests(checks: list[Check], args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_json(args.manifest_audit)
    ranking = read_csv(args.ranking_csv)
    controls = read_csv(args.controls_csv)
    pose = read_csv(args.pose_summary_csv)

    required_ranking = {
        "ranking_group_id", "split", "candidate_pair_id", "candidate_role", "negative_type",
        "vhh_seq", "proxy_label_policy", "ordinary_bce_eligible", "ranking_weight", "ranking_margin",
    }
    add_check(checks, "manifest_builder_status_pass", manifest.get("status") == "PASS", manifest.get("status"))
    add_check(checks, "ranking_manifest_required_columns_present", required_ranking <= set(ranking.columns), sorted(required_ranking - set(ranking.columns)))
    add_check(checks, "control_manifest_has_47_isolated_pvrig_controls", len(controls) == args.expected_control_rows, {"rows": len(controls), "expected": args.expected_control_rows})
    add_check(checks, "pose_proxy_summary_has_one_row_per_control", len(pose) == len(controls), {"pose_rows": len(pose), "control_rows": len(controls)})

    if required_ranking <= set(ranking.columns):
        grouped = ranking.groupby("ranking_group_id", dropna=False)
        roles = grouped["candidate_role"].value_counts().unstack(fill_value=0)
        positive_complete = bool((roles.get("observed_cognate_positive", 0) == 1).all())
        negative_complete = bool((roles.get("constructed_contrastive_candidate", 0) >= 1).all())
        one_split = bool(grouped["split"].nunique(dropna=False).max() == 1)
        no_duplicate_candidate = not ranking.duplicated(["ranking_group_id", "candidate_pair_id"]).any()
        add_check(checks, "ranking_groups_are_complete_and_split_local", positive_complete and negative_complete and one_split and no_duplicate_candidate, {"groups": int(ranking["ranking_group_id"].nunique()), "one_positive": positive_complete, "has_negative": negative_complete, "one_split": one_split, "no_duplicate_candidate": no_duplicate_candidate})
        negatives = ranking[ranking["candidate_role"].astype(str) == "constructed_contrastive_candidate"]
        proxy_ok = set(negatives["proxy_label_policy"].astype(str)) == {"constructed_preference_not_verified_nonbinder"}
        bce_ok = set(negatives["ordinary_bce_eligible"].astype(str).str.lower()) == {"no"}
        add_check(checks, "constructed_candidates_keep_proxy_not_classifier_semantics", proxy_ok and bce_ok, {"proxy_values": sorted(set(negatives["proxy_label_policy"].astype(str))), "ordinary_bce_values": sorted(set(negatives["ordinary_bce_eligible"].astype(str).str.lower()))})
        ranking_hashes = {sequence_hash(v) for v in ranking["vhh_seq"]}
    else:
        ranking_hashes = set()

    control_hash_column = "sequence_sha256" if "sequence_sha256" in controls.columns else None
    control_hashes = set(controls[control_hash_column].astype(str)) if control_hash_column else {sequence_hash(v) for v in controls.get("sequence", [])}
    overlap = ranking_hashes & control_hashes
    control_flags = ["ordinary_train_allowed", "ordinary_test_allowed", "candidate_ranking_allowed"]
    isolated = all(column in controls.columns and not controls[column].astype(str).str.lower().isin({"true", "1", "yes"}).any() for column in control_flags)
    add_check(checks, "pvrig_controls_have_zero_exact_hash_overlap_with_ranking", len(overlap) == 0 and len(controls) == args.expected_control_rows, {"control_rows": len(controls), "unique_control_hashes": len(control_hashes), "hash_overlap": len(overlap)})
    add_check(checks, "pvrig_controls_are_not_ordinary_training_test_or_candidate_rows", isolated, {column: sorted(set(controls[column].astype(str))) if column in controls.columns else "MISSING" for column in control_flags})
    pose_semantics = set(pose.get("proxy_semantics", pd.Series(dtype=str)).astype(str))
    add_check(checks, "pose_proxy_semantics_are_docking_not_experimental_labels", pose_semantics == {"docking_proxy_not_experimental_label"}, sorted(pose_semantics))
    boundaries = manifest.get("boundaries", {})
    add_check(checks, "manifest_boundaries_explicitly_proxy_not_classifier", has_boundary_text(boundaries), boundaries)

    return {"manifest": manifest, "ranking": ranking, "controls": controls, "pose": pose}


def audit_run(checks: list[Check], run_dir: Path, seed: int, args: argparse.Namespace) -> dict[str, Any]:
    metrics = load_json(run_dir / "test_metrics.json")
    summary = load_json(run_dir / "run_summary.json")
    history = load_json_value(run_dir / "metrics_history.json") if (run_dir / "metrics_history.json").exists() else summary.get("history", [])
    config = load_json(run_dir / "config_resolved.json") if (run_dir / "config_resolved.json").exists() else {}
    checkpoint = run_dir / "best_checkpoint.pt"

    add_check(checks, f"seed{seed}_artifacts_present", checkpoint.exists() and checkpoint.stat().st_size > 0, rel_or_abs(checkpoint))
    seed_checkpoint = args.exp_dir / "checkpoints" / f"phase2_v2_4_strict_seed{seed}_best_checkpoint.pt"
    byte_identical = (
        checkpoint.exists()
        and seed_checkpoint.exists()
        and file_sha256(checkpoint) == file_sha256(seed_checkpoint)
    )
    portability_audit = load_json(args.portable_checkpoint_audit) if args.portable_checkpoint_audit and args.portable_checkpoint_audit.exists() else {}
    portability_record = next((row for row in portability_audit.get("checkpoints", []) if coerce_seed(row.get("seed")) == seed), {})
    audited_model_equivalence = (
        bool(portability_record.get("model_state_roundtrip_equal"))
        and checkpoint.exists()
        and seed_checkpoint.exists()
        and portability_record.get("source_sha256") == file_sha256(checkpoint)
        and portability_record.get("portable_sha256") == file_sha256(seed_checkpoint)
    )
    add_check(
        checks,
        f"seed{seed}_durable_checkpoint_model_equivalent_to_run_best",
        byte_identical or audited_model_equivalence,
        {"run_best": rel_or_abs(checkpoint), "durable": rel_or_abs(seed_checkpoint), "byte_identical": byte_identical, "audited_model_equivalence": audited_model_equivalence},
    )
    config_seed = coerce_seed(config.get("seed"))
    run_seed = coerce_seed(summary.get("env", {}).get("run_id")) or coerce_seed(run_dir.name)
    add_check(checks, f"seed{seed}_identity_matches_required_seed", config_seed == seed and run_seed == seed, {"config_seed": config_seed, "run_seed": run_seed, "run_dir": run_dir.name})

    warmstart = summary.get("warmstart") or metrics.get("warmstart") or {}
    warm_source = clean(warmstart.get("source"))
    add_check(
        checks,
        f"seed{seed}_warmstarted_from_matching_v2_3_checkpoint",
        warmstart.get("status") == "loaded"
        and "v2_3" in warm_source
        and f"seed{seed}" in warm_source
        and int(warmstart.get("loaded_keys", 0)) > 0,
        warmstart,
    )

    env = summary.get("env", {})
    device_text = json.dumps(env, ensure_ascii=False).lower()
    add_check(checks, f"seed{seed}_cuda_rtx5080_environment", "cuda" in device_text and args.required_gpu_name.lower() in device_text, env)
    telemetry_json = args.exp_dir / "audits" / f"{run_dir.name}_gpu_telemetry_summary.json"
    telemetry_csv = args.exp_dir / "logs" / f"{run_dir.name}_gpu_telemetry.csv"
    telemetry = load_json(telemetry_json) if telemetry_json.exists() else {}
    telemetry_ok = (
        int(telemetry.get("train_exit_code", -1)) == 0
        and int(telemetry.get("samples", 0)) >= 10
        and args.required_gpu_name in telemetry.get("gpu_names", [])
        and float(telemetry.get("max_utilization_gpu_pct") or 0.0) >= 10.0
        and float(telemetry.get("max_memory_used_mib") or 0.0) >= 1000.0
    )
    add_check(checks, f"seed{seed}_gpu_telemetry_proves_real_cuda_work", telemetry_ok, telemetry or rel_or_abs(telemetry_json))

    nonfinite = [(path, value) for path, value in finite_leaf_values(metrics) if not math.isfinite(value)]
    add_check(checks, f"seed{seed}_metrics_are_finite", not nonfinite, nonfinite[:10])

    boundary_blob = {"metrics": metrics, "summary": summary}
    add_check(checks, f"seed{seed}_proxy_not_classifier_boundary_explicit", has_boundary_text(boundary_blob) and PROXY_BOUNDARY.lower().split(";")[0] in PROXY_BOUNDARY.lower(), metrics.get("label_boundary") or metrics.get("ranking_test", {}).get("ranking_metric_boundary"))
    calibration = metrics.get("calibration", {})
    brier = metrics.get("brier") or metrics.get("brier_score") or calibration.get("brier") or calibration.get("brier_score")
    ece = metrics.get("ece") or metrics.get("expected_calibration_error") or calibration.get("ece") or calibration.get("expected_calibration_error")
    add_check(checks, f"seed{seed}_brier_ece_not_applicable", calibration.get("status") == "NOT_APPLICABLE" and brier in (None, "NOT_APPLICABLE") and ece in (None, "NOT_APPLICABLE"), calibration)

    best_epoch = int(summary.get("env", {}).get("best_epoch", -1))
    history_rows = history if isinstance(history, list) else summary.get("history", [])
    selected_rows = [row for row in history_rows if int(row.get("epoch", -999)) == best_epoch]
    def selection_score(row: dict[str, Any]) -> float:
        return (
            float(row.get("val_contact_auprc", 0.0))
            + 1.25 * float(row.get("val_ranking_mrr", 0.0))
            + 0.25 * float(row.get("val_ranking_hard_negative_win_rate", 0.0))
            + 0.3 * float(row.get("val_paratope_auprc", 0.0))
        )
    best_validation_epoch = int(max(history_rows, key=selection_score).get("epoch", -1)) if history_rows else -1
    add_check(
        checks,
        f"seed{seed}_checkpoint_selected_by_validation_epoch",
        best_epoch > 0 and bool(selected_rows) and best_epoch == best_validation_epoch,
        {"best_epoch": best_epoch, "recomputed_best_validation_epoch": best_validation_epoch, "history_epochs": [row.get("epoch") for row in history_rows]},
    )

    strict_inputs = summary.get("strict_inputs", {})
    forbidden_test_select = json.dumps({"summary": summary, "config": config}, ensure_ascii=False).lower()
    prereg = load_json(args.preregistration_json) if args.preregistration_json and args.preregistration_json.exists() else None
    prereg_policy = prereg.get("selection_policy", {}) if prereg else {}
    test_used_for_selection = prereg.get("test_metrics_used_for_selection", prereg_policy.get("test_metrics_used_for_selection", True)) if prereg else True
    prereg_status_ok = prereg is not None and clean(prereg.get("status")) in {"PASS", "REGISTERED", "LOCKED", "FROZEN_BEFORE_FORMAL_RUNS"}
    registered_at = parse_iso_datetime(prereg.get("registered_at_utc")) if prereg else None
    telemetry_started_at = first_telemetry_timestamp(telemetry_csv)
    chronology_ok = registered_at is None or telemetry_started_at is None or registered_at <= telemetry_started_at
    prereg_ok = prereg_status_ok and str(test_used_for_selection).lower() in {"false", "0", "no"} and chronology_ok
    no_test_selection_language = "test_metrics_used_for_selection\": true" not in forbidden_test_select and "test-selected" not in forbidden_test_select
    add_check(
        checks,
        f"seed{seed}_preregistration_before_test_selection",
        prereg_ok and no_test_selection_language,
        {
            "preregistration_status": prereg.get("status") if prereg else "MISSING",
            "test_metrics_used_for_selection": test_used_for_selection,
            "registered_at": registered_at.isoformat() if registered_at else "not_recorded",
            "telemetry_started_at": telemetry_started_at.isoformat() if telemetry_started_at else "not_recorded",
            "chronology_ok": chronology_ok,
            "no_test_selection_language": no_test_selection_language,
        },
    )

    durable_sha = file_sha256(seed_checkpoint) if seed_checkpoint.exists() else ""
    return {"seed": seed, "run_dir": run_dir, "metrics": metrics, "summary": summary, "checkpoint": checkpoint, "strict_inputs": strict_inputs, "sha256": durable_sha}


def audit_runs(checks: list[Check], args: argparse.Namespace) -> list[dict[str, Any]]:
    run_dirs = list(args.run_dir) if args.run_dir else discover_runs(args.exp_dir, tuple(args.required_seeds))
    seed_to_run: dict[int, Path] = {}
    for run_dir in run_dirs:
        seed = coerce_seed(run_dir.name)
        if seed is None and (run_dir / "config_resolved.json").exists():
            seed = coerce_seed(load_json(run_dir / "config_resolved.json").get("seed"))
        if seed is not None:
            seed_to_run[seed] = run_dir
    add_check(checks, "exact_seed_set_43_53_67_present", set(seed_to_run) == set(args.required_seeds), {"found": sorted(seed_to_run), "required": list(args.required_seeds)})
    runs = [audit_run(checks, seed_to_run[seed], seed, args) for seed in args.required_seeds if seed in seed_to_run]

    if runs:
        dataset_sizes = [run["metrics"].get("dataset_sizes") for run in runs]
        add_check(checks, "per_seed_dataset_sizes_match", all(value == dataset_sizes[0] for value in dataset_sizes), dataset_sizes)
        if args.canonical_checkpoint and args.canonical_checkpoint.exists():
            canonical_sha = file_sha256(args.canonical_checkpoint)
            matching = [run["seed"] for run in runs if run["sha256"] == canonical_sha]
            add_check(checks, "canonical_checkpoint_matches_one_seed_best_checkpoint", len(matching) == 1, {"canonical": rel_or_abs(args.canonical_checkpoint), "matching_seeds": matching})
        else:
            add_check(checks, "canonical_checkpoint_present_for_sha_equivalence", False, rel_or_abs(args.canonical_checkpoint), severity="WARN")
    return runs


def audit_aggregate(checks: list[Check], runs: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if not args.aggregate_json or not args.aggregate_json.exists():
        add_check(checks, "aggregate_summary_present", False, rel_or_abs(args.aggregate_json) if args.aggregate_json else "not configured", severity="WARN")
        return
    aggregate = load_json(args.aggregate_json)
    aggregate_text = json.dumps(aggregate, ensure_ascii=False).lower()
    claim_scan_text = aggregate_text.replace("not verified non-binders", "").replace("not verified non-binder", "")
    add_check(checks, "aggregate_boundary_does_not_claim_biological_validation", not any(term in claim_scan_text for term in BIOLOGICAL_CLAIM_FORBIDDEN), "forbidden claim scan passed")
    seeds = {coerce_seed(seed) for seed in aggregate.get("seeds", [])}
    seeds.discard(None)
    add_check(checks, "aggregate_seed_set_matches_runs", seeds == {run["seed"] for run in runs} == set(args.required_seeds), {"aggregate_seeds": sorted(seeds), "run_seeds": sorted(run["seed"] for run in runs)})
    if "n_runs" in aggregate:
        add_check(checks, "aggregate_n_runs_consistent", int(aggregate.get("n_runs", -1)) == len(runs), {"aggregate_n_runs": aggregate.get("n_runs"), "runs": len(runs)})
    calibration = aggregate.get("calibration", {})
    add_check(checks, "aggregate_brier_ece_not_applicable", calibration.get("status") == "NOT_APPLICABLE" and "brier" not in aggregate_text and "expected_calibration_error" not in aggregate_text, calibration)

    prereg = load_json(args.preregistration_json) if args.preregistration_json and args.preregistration_json.exists() else {}
    thresholds = {**DEFAULT_PREFERENCE_THRESHOLDS, **prereg.get("preferred_thresholds", {})}
    metric_table = aggregate.get("metrics", {})

    def mean_metric(name: str) -> float | None:
        payload = metric_table.get(name, {})
        value = payload.get("mean") if isinstance(payload, dict) else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    preference_checks = {
        "ranking_mrr_preferred_threshold": (
            mean_metric("ranking_mrr"),
            max(float(thresholds["ranking_mrr_mean_min"]), float(thresholds["v2_3_ranking_mrr_mean"]), float(thresholds["v2_3_random_mrr_mean"])),
        ),
        "ranking_hit_at_1_preferred_threshold": (mean_metric("ranking_hit_at_1"), float(thresholds["ranking_hit_at_1_mean_min"])),
        "hard_negative_win_preferred_threshold": (mean_metric("ranking_hard_negative_win_rate"), float(thresholds["hard_negative_win_mean_min"])),
        "contact_auprc_guardrail": (mean_metric("contact_auprc"), float(thresholds["contact_auprc_mean_floor"])),
        "paratope_auprc_guardrail": (mean_metric("paratope_auprc"), float(thresholds["paratope_auprc_mean_floor"])),
    }
    for name, (observed, threshold) in preference_checks.items():
        add_check(
            checks,
            name,
            observed is not None and math.isfinite(observed) and observed >= threshold,
            {"observed_mean": observed, "preferred_minimum": threshold},
            severity="WARN",
        )


def audit_candidate_pose_and_fusion(checks: list[Check], args: argparse.Namespace) -> None:
    if args.pose_identity_json and args.pose_identity_json.exists():
        pose_qc = load_json(args.pose_identity_json)
        identity_ok = (
            (pose_qc.get("status") == "PASS" and pose_qc.get("exact_identity") is True)
            or (
                int(pose_qc.get("verified_pose_proxy_rows", 0)) > 0
                and int(pose_qc.get("failed_validation_rows", 1)) == 0
                and "proxy" in clean(pose_qc.get("evidence_boundary")).lower()
            )
        )
        add_check(checks, "candidate_pose_index_exact_identity_qc_pass", identity_ok, pose_qc)
    elif args.candidate_csv and args.pose_index_csv and args.candidate_csv.exists() and args.pose_index_csv.exists():
        candidates = read_csv(args.candidate_csv)
        pose_index = read_csv(args.pose_index_csv)
        candidate_ids = extract_candidate_ids(candidates)
        pose_ids = extract_candidate_ids(pose_index)
        status_ok = "pose_index_status" not in pose_index.columns or set(pose_index["pose_index_status"].astype(str)) == {"verified_pose_proxy"}
        identity_columns_ok = all(
            column in pose_index.columns and pose_index[column].astype(str).str.lower().isin({"true", "1", "yes"}).all()
            for column in ("vhh_chain_a_exact_match", "pvrig_chain_b_exact_match")
        )
        add_check(
            checks,
            "candidate_pose_index_exact_identity_qc_pass",
            bool(pose_ids) and pose_ids <= candidate_ids and status_ok and identity_columns_ok,
            {"candidate_count": len(candidate_ids), "pose_index_count": len(pose_ids), "extra_in_pose": sorted(pose_ids - candidate_ids)[:10], "status_ok": status_ok, "identity_columns_ok": identity_columns_ok},
        )
    else:
        add_check(checks, "candidate_pose_index_exact_identity_qc_pass", False, "pose identity artifact not configured", severity="WARN")

    if args.fusion_json and args.fusion_json.exists():
        fusion = load_json(args.fusion_json)
        text = json.dumps(fusion, ensure_ascii=False).lower()
        provenance_ok = (
            fusion.get("status") in {"PASS", "COMPLETED", "PASS_WITH_WARNINGS"}
            or (int(fusion.get("rows", 0)) > 0 and clean(fusion.get("sequence_csv")) and clean(fusion.get("output")))
        ) and "proxy" in text
        add_check(checks, "fusion_provenance_is_explicit_and_proxy_bounded", provenance_ok, fusion)
    else:
        add_check(checks, "fusion_provenance_is_explicit_and_proxy_bounded", False, "fusion artifact not configured", severity="WARN")


def audit_checkpoint_portability(checks: list[Check], args: argparse.Namespace) -> None:
    if args.portable_checkpoint_audit and args.portable_checkpoint_audit.exists():
        portable = load_json(args.portable_checkpoint_audit)
        rows = portable.get("checkpoints", [])
        portable_ok = (
            portable.get("status") == "PASS"
            and {coerce_seed(row.get("seed")) for row in rows} == set(args.required_seeds)
            and all(row.get("model_state_roundtrip_equal") is True for row in rows)
            and portable.get("canonical_matches_selected_portable_sha256") is True
        )
        add_check(checks, "portable_checkpoint_set_preserves_model_state", portable_ok, portable)
    else:
        add_check(checks, "portable_checkpoint_set_preserves_model_state", False, "portable checkpoint audit missing")

    if args.portable_inference_equivalence and args.portable_inference_equivalence.exists():
        equivalence = load_json(args.portable_inference_equivalence)
        differences = equivalence.get("max_abs_differences", {})
        equivalence_ok = (
            equivalence.get("status") == "PASS"
            and equivalence.get("candidate_ids_equal") is True
            and equivalence.get("candidate_identity_hashes_equal") is True
            and equivalence.get("all_three_seeds_full50_exact") is True
            and {coerce_seed(seed) for seed in equivalence.get("seeds", [])} == set(args.required_seeds)
            and bool(differences)
            and all(float(value) == 0.0 for value in differences.values())
        )
        add_check(checks, "portable_checkpoint_inference_is_exactly_equivalent", equivalence_ok, equivalence)
    else:
        add_check(checks, "portable_checkpoint_inference_is_exactly_equivalent", False, "portable inference equivalence audit missing")


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[Check] = []
    args.exp_dir = args.exp_dir.resolve()
    args.required_seeds = tuple(args.required_seeds)
    audit_manifests(checks, args)
    runs = audit_runs(checks, args)
    audit_checkpoint_portability(checks, args)
    audit_aggregate(checks, runs, args)
    audit_candidate_pose_and_fusion(checks, args)

    failed = [check.name for check in checks if check.status == "FAIL"]
    warnings = [check.name for check in checks if check.status == "WARN"]
    ranking_limitations = {
        "ranking_mrr_preferred_threshold",
        "ranking_hit_at_1_preferred_threshold",
        "hard_negative_win_preferred_threshold",
    }
    if failed:
        overall_status = "FAIL"
    elif ranking_limitations & set(warnings):
        overall_status = "PASS_WITH_PAIR_RANKING_LIMITATION"
    elif warnings:
        overall_status = "PASS_WITH_WARNINGS"
    else:
        overall_status = "PASS"
    return {
        "status": overall_status,
        "schema_version": "phase2_v2_4_final_audit_v1",
        "failed_checks": failed,
        "warnings": warnings,
        "check_count": len(checks),
        "checks": [check.__dict__ for check in checks],
        "summary": {
            "required_seeds": list(args.required_seeds),
            "run_count": len(runs),
            "control_rows_expected": args.expected_control_rows,
            "boundary": PROXY_BOUNDARY,
            "threshold_policy": "Metric preference thresholds are PASS/WARN only and must not imply biological validation.",
        },
        "boundary": PROXY_BOUNDARY,
    }


def write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 2 V2.4 Final Audit V1",
        "",
        f"- Status: **{result['status']}**",
        f"- Checks: {result['check_count'] - len(result['failed_checks'])}/{result['check_count']} pass-or-warn",
        f"- Warnings: {len(result['warnings'])}",
        f"- Boundary: {result['boundary']}",
        "",
        "## Checks",
        "",
    ]
    for item in result["checks"]:
        lines.append(f"- [{item['status']}] `{item['name']}` ({item['severity']}) - {item['evidence']}")
    lines.extend([
        "",
        "## Threshold Policy",
        "",
        "Metric preference thresholds are advisory PASS/WARN checks only. They do not establish binding, IC50/Kd, PVRIG-PVRL2 blocking, or biological validation.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-dir", type=Path, default=EXP_DIR)
    parser.add_argument("--manifest-audit", type=Path, default=EXP_DIR / "audits/phase2_v2_4_manifest_build_v1.json")
    parser.add_argument("--ranking-csv", type=Path, default=EXP_DIR / "data_splits/pair_ranking_groups_v2_4.csv")
    parser.add_argument("--controls-csv", type=Path, default=EXP_DIR / "data_splits/pvrig_validation_controls_v2_4.csv")
    parser.add_argument("--pose-summary-csv", type=Path, default=EXP_DIR / "prepared/pvrig_pose_proxy_summary_v2_4.csv")
    parser.add_argument("--run-dir", type=Path, action="append", default=[])
    parser.add_argument("--aggregate-json", type=Path, default=EXP_DIR / "reports/phase2_v2_4_multiseed_summary_v1.json")
    parser.add_argument("--preregistration-json", type=Path, default=EXP_DIR / "audits/phase2_v2_4_preregistration_v1.json")
    parser.add_argument("--pose-identity-json", type=Path, default=EXP_DIR / "audits/phase2_v2_4_candidate_pose_index.json")
    parser.add_argument("--candidate-csv", type=Path, default=None)
    parser.add_argument("--pose-index-csv", type=Path, default=EXP_DIR / "data_splits/phase2_v2_4_candidate_pose_index.csv")
    parser.add_argument("--fusion-json", type=Path, default=EXP_DIR / "audits/phase2_v2_4_p3_pose_fusion.json")
    parser.add_argument("--canonical-checkpoint", type=Path, default=EXP_DIR / "checkpoints/phase2_v2_4_best_checkpoint.pt")
    parser.add_argument("--portable-checkpoint-audit", type=Path, default=EXP_DIR / "audits/phase2_v2_4_portable_checkpoints_v1.json")
    parser.add_argument("--portable-inference-equivalence", type=Path, default=EXP_DIR / "audits/phase2_v2_4_portable_inference_equivalence_v1.json")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--required-seed", type=int, dest="required_seeds", action="append", default=[])
    parser.add_argument("--expected-control-rows", type=int, default=47)
    parser.add_argument("--required-gpu-name", default="NVIDIA GeForce RTX 5080")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if not args.required_seeds:
        args.required_seeds = list(REQUIRED_SEEDS)
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = build_audit(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.no_write:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_markdown(result, args.markdown_out)
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
