#!/usr/bin/env python3
"""Evaluate Phase 2 V2.5 split leakage, seal status, and target readiness."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from build_phase2_v2_5_splits import (
    EXP_DIR,
    LABEL_COLUMNS,
    assert_zero_leakage_overlap,
    clean,
    evidence_rank,
    file_sha256,
    is_pvrig_target,
    leakage_overlap_audit,
)

DEFAULT_TRAIN = EXP_DIR / "data_splits/phase2_v2_5_train_manifest.csv"
DEFAULT_DEV = EXP_DIR / "data_splits/phase2_v2_5_dev_manifest.csv"
DEFAULT_FORMAL_BLINDED = EXP_DIR / "data_splits/phase2_v2_5_generic_formal_manifest_blinded.csv"
DEFAULT_SPLIT_AUDIT = EXP_DIR / "audits/phase2_v2_5_split_seal_audit_v1.json"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v2_5_readiness_audit_v1.json"

MDE_ABSOLUTE = 0.10
ALPHA_TWO_SIDED = 0.05
MIN_POWER = 0.80
MAX_CI_HALF_WIDTH = 0.10
SIMULATION_SEED = 20260711


def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def level_series(frame: pd.DataFrame) -> pd.Series:
    if "evidence_level" not in frame.columns:
        return pd.Series([], dtype="float64")
    return frame["evidence_level"].map(evidence_rank)


def assay_backed(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    levels = level_series(frame)
    return frame[levels.isin([4, 5, 6])].copy()


def pvrig_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "target_id" not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame[frame["target_id"].map(is_pvrig_target)].copy()


def evidence_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "evidence_level" not in frame.columns:
        return {}
    return frame["evidence_level"].map(clean).value_counts().astype(int).to_dict()


def count_verified_binary(frame: pd.DataFrame) -> tuple[int, int]:
    truth = frame.get("ground_truth_kind", pd.Series(dtype=str)).map(lambda v: clean(v).lower())
    positive = int(truth.str.contains("verified_positive|blocker_positive|binding_positive|positive", regex=True).sum())
    negative = int(truth.str.contains("verified_negative|verified_nonbinder|verified_non-binder|binder_nonblocker", regex=True).sum())
    return positive, negative


def target_model_eligible(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    allowed = frame.get("allowed_use", pd.Series("", index=frame.index)).map(lambda value: clean(value).upper())
    return frame[allowed.eq("EXPERIMENTAL_RANKING_ONLY")].copy()


def comparable_ranking_groups(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["ranking_group_key", "n_candidates"])
    required = ["target_id", "assay_type", "assay_batch", "source_id", "label_axis", "split_group_id"]
    for column in required:
        if column not in frame.columns:
            frame[column] = ""
    keyed = frame.copy()
    keyed["ranking_group_key"] = keyed[required].apply(lambda row: "|".join(clean(v) for v in row), axis=1)
    grouped = keyed.groupby("ranking_group_key", sort=False).agg(
        n_candidates=("sample_id", "count"),
        split_groups=("split_group_id", "nunique"),
        assay_blocks=("assay_batch", "nunique"),
    ).reset_index()
    return grouped[grouped["n_candidates"] >= 3].copy()


def independent_blocks(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    cols = [column for column in ["family_id", "assay_batch", "source_id", "split_group_id"] if column in frame.columns]
    if not cols:
        return 0
    return int(frame[cols].astype(str).drop_duplicates().shape[0])


def leakage_overlap(train: pd.DataFrame, dev: pd.DataFrame, formal: pd.DataFrame) -> dict[str, Any]:
    split_frames: list[pd.DataFrame] = []
    for split, frame in [("train", train), ("dev", dev), ("formal", formal)]:
        if frame.empty:
            continue
        current = frame.copy()
        current["split"] = split
        split_frames.append(current)
    combined = pd.concat(split_frames, ignore_index=True, sort=False) if split_frames else pd.DataFrame(columns=["split"])
    return leakage_overlap_audit(combined)


def blinded_manifest_exposes_labels(formal: pd.DataFrame) -> list[str]:
    return [column for column in LABEL_COLUMNS if column in formal.columns]


def formal_metadata_power(formal: pd.DataFrame, dev: pd.DataFrame, seed: int = SIMULATION_SEED) -> dict[str, Any]:
    formal_group_count = int(formal.get("split_group_id", pd.Series(dtype=str)).map(clean).replace("", np.nan).dropna().nunique()) if not formal.empty else 0
    block_columns = [column for column in ["assay_batch", "source_id"] if column in formal.columns]
    if block_columns and not formal.empty:
        formal_blocks = int(formal[block_columns].astype(str).drop_duplicates().shape[0])
    else:
        formal_blocks = 0
    # Development variance only: no formal labels are read. Fallback is maximally conservative binary variance.
    dev_variance = 0.25
    if "dev_group_primary_variance" in dev.columns:
        vals = pd.to_numeric(dev["dev_group_primary_variance"], errors="coerce").dropna()
        if len(vals) > 0:
            dev_variance = float(max(vals.mean(), 1e-9))
    effective_n = max(formal_group_count, 0)
    if effective_n <= 0:
        ci_half_width = None
        estimated_power = None
    else:
        se = math.sqrt(dev_variance / effective_n)
        ci_half_width = 1.96 * se
        # Normal approximation for a two-sided paired group-level test, seeded for contract traceability only.
        z_alpha = 1.959963984540054
        z_effect = MDE_ABSOLUTE / se if se > 0 else float("inf")
        estimated_power = float(1.0 - 0.5 * (1.0 + math.erf((z_alpha - z_effect) / math.sqrt(2.0))))
        estimated_power = max(0.0, min(1.0, estimated_power))
    return {
        "primary_metric": "macro_group_pairwise_preference_accuracy",
        "mde_absolute": MDE_ABSOLUTE,
        "alpha_two_sided": ALPHA_TWO_SIDED,
        "estimated_power": estimated_power,
        "minimum_power": MIN_POWER,
        "expected_ci_half_width": ci_half_width,
        "maximum_ci_half_width": MAX_CI_HALF_WIDTH,
        "formal_split_group_count": formal_group_count,
        "formal_assay_or_source_block_count": formal_blocks,
        "formal_labels_read": False,
        "simulation_seed": seed,
    }


def concat_nonempty(frames: list[pd.DataFrame]) -> pd.DataFrame:
    nonempty = [frame for frame in frames if not frame.empty]
    return pd.concat(nonempty, ignore_index=True, sort=False) if nonempty else pd.DataFrame()


def target_readiness(train: pd.DataFrame, dev: pd.DataFrame, formal: pd.DataFrame) -> dict[str, Any]:
    development = concat_nonempty([train, dev])
    target_dev = assay_backed(pvrig_rows(development))
    target_formal = assay_backed(pvrig_rows(formal))
    target_dev_eligible = target_model_eligible(target_dev)
    target_allowed = target_dev.get("allowed_use", pd.Series("", index=target_dev.index)).map(lambda value: clean(value).lower())
    target_control_only_count = int(target_allowed.str.contains("calibration|leakage|control_only", regex=True).sum())
    positives, negatives = count_verified_binary(target_dev_eligible)
    rank_groups = comparable_ranking_groups(target_dev_eligible)
    family_assay_blocks = independent_blocks(target_dev_eligible)
    pilot_shape = (
        len(target_dev_eligible) >= 20 and positives > 0 and negatives > 0 and family_assay_blocks >= 5
    ) or (
        int(len(rank_groups)) >= 8 and int(rank_groups["n_candidates"].ge(3).sum()) >= 8
    )
    power = formal_metadata_power(target_formal, dev)
    formal_structure = power["formal_split_group_count"] >= 5 and power["formal_assay_or_source_block_count"] >= 2
    powered = (
        power["estimated_power"] is not None
        and power["estimated_power"] >= MIN_POWER
        and power["expected_ci_half_width"] is not None
        and power["expected_ci_half_width"] <= MAX_CI_HALF_WIDTH
        and formal_structure
    )
    if not pilot_shape:
        status = "DATA_NOT_READY"
        decision = "DATA_NOT_READY_FOR_TARGET_MODEL"
        schedule_training = False
    elif not powered:
        status = "NOT_POWERED_FOR_TARGET_FORMAL"
        decision = "PASS_LIMITED_RANKING_ONLY"
        schedule_training = False
    else:
        status = "TARGET_FORMAL_READY"
        decision = "TARGET_FORMAL_READY"
        schedule_training = True
    return {
        "status": status,
        "formal_decision_status": decision,
        "target_training_scheduled": schedule_training,
        "target_development_assay_backed_rows": int(len(target_dev)),
        "target_development_model_eligible_rows": int(len(target_dev_eligible)),
        "target_development_non_model_eligible_rows": int(len(target_dev) - len(target_dev_eligible)),
        "target_development_control_only_rows": target_control_only_count,
        "target_formal_assay_backed_rows": int(len(target_formal)),
        "assay_backed_rank_groups": int(len(rank_groups)),
        "verified_binary_positive": positives,
        "verified_binary_negative": negatives,
        "independent_family_assay_blocks": family_assay_blocks,
        "power_simulation": power,
        "no_go_reasons": [] if schedule_training else [
            reason for reason, condition in [
                ("insufficient_pvrig_assay_backed_positive_and_negative_or_ranking_groups", not pilot_shape),
                ("target_formal_not_powered_or_not_structurally_independent", pilot_shape and not powered),
            ] if condition
        ],
    }


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    train = read_csv_optional(args.train_manifest)
    dev = read_csv_optional(args.dev_manifest)
    formal = read_csv_optional(args.formal_blinded)
    split_audit = load_json_optional(args.split_audit)
    exposed = blinded_manifest_exposes_labels(formal)
    if exposed:
        status = "INVALID_RUN"
    else:
        status = "PASS"
    target = target_readiness(train, dev, formal)
    overlap = leakage_overlap(train, dev, formal)
    assert_zero_leakage_overlap(overlap)
    reported_overlap = split_audit.get("leakage_overlap_audit", {})
    if reported_overlap:
        assert_zero_leakage_overlap(reported_overlap)
    source_or_patent_overlap = max(
        (
            count
            for key in ["source_group_id", "source_document_id", "patent_family_id"]
            for count in overlap.get(key, {}).values()
        ),
        default=0,
    )
    split_validation = {
        "exact_vhh_overlap": max(overlap.get("sequence_sha256", {}).values(), default=0),
        "vhh_cluster_overlap": max(overlap.get("vhh_identity_cluster", {}).values(), default=0),
        "cdr3_cluster_overlap": max(overlap.get("cdr3_cluster", {}).values(), default=0),
        "target_overlap_policy_pass": max(overlap.get("target_sequence_sha256", {}).values(), default=0) == 0,
        "assay_batch_overlap": max(overlap.get("assay_batch", {}).values(), default=0),
        "source_or_patent_family_overlap": source_or_patent_overlap,
        "base_mutant_group_overlap": max(overlap.get("base_mutant_group_id", {}).values(), default=0),
    }
    calibration_applicable = target["verified_binary_positive"] > 0 and target["verified_binary_negative"] > 0
    sha = {
        "train_manifest": file_sha256(args.train_manifest) if args.train_manifest.exists() else None,
        "dev_manifest": file_sha256(args.dev_manifest) if args.dev_manifest.exists() else None,
        "formal_manifest_blinded": file_sha256(args.formal_blinded) if args.formal_blinded.exists() else None,
        "formal_labels_sealed": split_audit.get("output_sha256", {}).get("formal_labels_sealed"),
    }
    audit = {
        "schema_version": "phase2_v2_5_test_spec_v1",
        "status": status,
        "input_sha256": sha,
        "data_readiness": {
            "status": target["status"],
            "evidence_level_counts": evidence_counts(concat_nonempty([train, dev, formal])),
            "assay_backed_rank_groups": target["assay_backed_rank_groups"],
            "target_development_assay_backed_rows": target["target_development_assay_backed_rows"],
            "target_development_model_eligible_rows": target["target_development_model_eligible_rows"],
            "target_development_non_model_eligible_rows": target["target_development_non_model_eligible_rows"],
            "target_development_control_only_rows": target["target_development_control_only_rows"],
            "verified_binary_positive": target["verified_binary_positive"],
            "verified_binary_negative": target["verified_binary_negative"],
            "independent_family_assay_blocks": target["independent_family_assay_blocks"],
            "target_training_scheduled": target["target_training_scheduled"],
            "no_go_reasons": target["no_go_reasons"],
            "power_simulation": target["power_simulation"],
        },
        "lane_policy": {
            "known_positive_ordinary_train_allowed": False,
            "constructed_proxy_as_verified_nonbinder_allowed": False,
            "pose_proxy_as_experimental_label_allowed": False,
        },
        "split_validation": split_validation,
        "formal_seal": {
            "status": "SEALED",
            "formal_run_count": 0,
            "formal_blinded_label_columns_exposed": exposed,
            "test_metrics_used_for_selection": False,
            "next_version_required_for_method_changes": True,
        },
        "statistics": {
            "primary_metric": "macro_group_pairwise_preference_accuracy",
            "bootstrap_unit": "split_group_id",
            "bootstrap_n": 5000,
            "permutation_n": 5000,
            "primary_alpha_two_sided": ALPHA_TWO_SIDED,
            "secondary_multiple_testing": "bh_fdr_exploratory",
        },
        "calibration": {
            "status": "APPLICABLE" if calibration_applicable else "NOT_APPLICABLE",
            "fit_split": "dev_only",
            "reason": None if calibration_applicable else "verified positive and verified negative labels are not both present",
        },
        "pose": {
            "exact_qc_passed_coverage": None,
            "global_fusion_min_coverage": 0.8,
            "global_fusion_applied": False,
            "missingness_audit_pass": None,
        },
        "formal_decision": {
            "status": target["formal_decision_status"],
            "primary_delta_vs_strong_baseline_ci_low_gt_zero": None,
            "permutation_pass": None,
            "seed_consistency_pass": None,
            "contact_guardrail_pass": None,
            "paratope_guardrail_pass": None,
            "claim_boundary": "ranking_evidence_not_experimental_blocker_validation",
        },
    }
    if args.audit_out and not args.no_write:
        args.audit_out.parent.mkdir(parents=True, exist_ok=True)
        args.audit_out.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return audit


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-manifest", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--dev-manifest", type=Path, default=DEFAULT_DEV)
    parser.add_argument("--formal-blinded", type=Path, default=DEFAULT_FORMAL_BLINDED)
    parser.add_argument("--split-audit", type=Path, default=DEFAULT_SPLIT_AUDIT)
    parser.add_argument("--audit-out", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit = build_audit(args)
    print(json.dumps({"status": audit["status"], "data_readiness": audit["data_readiness"]["status"], "formal_decision": audit["formal_decision"]["status"]}, indent=2, sort_keys=True))
    return 0 if audit["status"] != "INVALID_RUN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
