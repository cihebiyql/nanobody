#!/usr/bin/env python3
"""Build leakage-safe Phase 2 V2.4 ranking and PVRIG control manifests."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/phase2_5080_v1"
DEFAULT_TRIPLETS = EXP / "data_splits/pair_ranking_triplets_v2_clustered.csv"
DEFAULT_POSITIVE = ROOT / "model_data/pvrig_blocker_positive_calibration_v0.csv"
DEFAULT_MUTANT = ROOT / "model_data/pvrig_blocker_mutant_control_calibration_v0.csv"
DEFAULT_POSITIVE_POSES = ROOT / "model_data/pvrig_blocker_positive_pose_labels_v0.csv"
DEFAULT_MUTANT_POSES = ROOT / "model_data/pvrig_blocker_mutant_pose_labels_v0.csv"
DEFAULT_RANKING = EXP / "data_splits/pair_ranking_groups_v2_4.csv"
DEFAULT_CONTROLS = EXP / "data_splits/pvrig_validation_controls_v2_4.csv"
DEFAULT_POSE_SUMMARY = EXP / "prepared/pvrig_pose_proxy_summary_v2_4.csv"
DEFAULT_AUDIT = EXP / "audits/phase2_v2_4_manifest_build_v1.json"

RANKING_TYPE_POLICY = {
    "N1": {"weight": 0.50, "margin": 0.15},
    "N2": {"weight": 1.00, "margin": 0.25},
    "N3": {"weight": 1.25, "margin": 0.35},
}
RANKING_COLUMNS = [
    "ranking_group_id", "split", "positive_pair_id", "candidate_pair_id", "candidate_role",
    "negative_type", "vhh_seq", "antigen_seq", "preference_label", "label_source",
    "proxy_label_policy", "ranking_weight", "ranking_margin", "ordinary_bce_eligible",
]
CONTROL_COLUMNS = [
    "sample_id", "molecule_name", "sequence_sha256", "sequence", "family", "control_role",
    "label_hint", "leakage_policy", "assay_ic50_nm", "kd_m", "reporter_ec50_nm", "pose_count",
    "ordinary_train_allowed", "ordinary_test_allowed", "candidate_ranking_allowed",
    "ground_truth_kind", "source_table",
]
POSE_COLUMNS = [
    "sample_id", "source_lane", "pose_rows", "consensus_blocker_like_a_count",
    "single_baseline_recheck_count", "blocker_plausible_b_count", "evidence_inference_only_e_count",
    "other_class_count", "any_blocker_like_a", "manual_review_required", "proxy_semantics",
]


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."} else text


def normalize_sequence(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper() if "A" <= ch <= "Z")


def sequence_hash(sequence: Any) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


def negative_policy(negative_type: str) -> dict[str, float]:
    prefix = clean(negative_type).split("_", 1)[0]
    if prefix not in RANKING_TYPE_POLICY:
        raise ValueError(f"Unsupported V2.4 negative type: {negative_type}")
    return RANKING_TYPE_POLICY[prefix]


def build_ranking_groups(triplets_path: Path, output_path: Path) -> dict[str, Any]:
    triplets = pd.read_csv(triplets_path)
    required = {
        "ranking_group_id", "split", "positive_pair_id", "negative_pair_id", "negative_type",
        "positive_vhh_seq", "positive_antigen_seq", "negative_vhh_seq", "negative_antigen_seq",
        "preference_label", "label_source",
    }
    missing = required - set(triplets.columns)
    if missing:
        raise ValueError(f"Triplet manifest missing columns: {sorted(missing)}")
    if triplets.empty:
        raise ValueError("Triplet manifest is empty")

    output_rows: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for group_id, group in triplets.groupby("ranking_group_id", sort=False):
        invariant_columns = ["split", "positive_pair_id", "positive_vhh_seq", "positive_antigen_seq"]
        for column in invariant_columns:
            if group[column].astype(str).nunique(dropna=False) != 1:
                raise ValueError(f"Ranking group {group_id} has inconsistent {column}")
        first = group.iloc[0]
        output_rows.append(
            {
                "ranking_group_id": clean(group_id),
                "split": clean(first["split"]),
                "positive_pair_id": clean(first["positive_pair_id"]),
                "candidate_pair_id": clean(first["positive_pair_id"]),
                "candidate_role": "observed_cognate_positive",
                "negative_type": "positive_anchor",
                "vhh_seq": normalize_sequence(first["positive_vhh_seq"]),
                "antigen_seq": normalize_sequence(first["positive_antigen_seq"]),
                "preference_label": 1,
                "label_source": "cognate_structure_pair",
                "proxy_label_policy": "observed_cognate_positive_rank_anchor",
                "ranking_weight": 1.0,
                "ranking_margin": 0.0,
                "ordinary_bce_eligible": "yes",
            }
        )
        seen_negative_ids: set[str] = set()
        for _, row in group.iterrows():
            negative_id = clean(row["negative_pair_id"])
            if not negative_id or negative_id in seen_negative_ids:
                continue
            seen_negative_ids.add(negative_id)
            negative_type = clean(row["negative_type"])
            policy = negative_policy(negative_type)
            type_counts[negative_type] = type_counts.get(negative_type, 0) + 1
            output_rows.append(
                {
                    "ranking_group_id": clean(group_id),
                    "split": clean(row["split"]),
                    "positive_pair_id": clean(row["positive_pair_id"]),
                    "candidate_pair_id": negative_id,
                    "candidate_role": "constructed_contrastive_candidate",
                    "negative_type": negative_type,
                    "vhh_seq": normalize_sequence(row["negative_vhh_seq"]),
                    "antigen_seq": normalize_sequence(row["negative_antigen_seq"]),
                    "preference_label": 0,
                    "label_source": clean(row["label_source"]),
                    "proxy_label_policy": "constructed_preference_not_verified_nonbinder",
                    "ranking_weight": policy["weight"],
                    "ranking_margin": policy["margin"],
                    "ordinary_bce_eligible": "no",
                }
            )

    ranking = pd.DataFrame(output_rows, columns=RANKING_COLUMNS)
    counts = ranking.groupby("ranking_group_id")["candidate_role"].value_counts().unstack(fill_value=0)
    if not (counts.get("observed_cognate_positive", 0) == 1).all():
        raise ValueError("Every V2.4 ranking group must have exactly one positive anchor")
    if ranking["candidate_pair_id"].eq("").any():
        raise ValueError("V2.4 ranking manifest contains an empty candidate_pair_id")
    if ranking.duplicated(["ranking_group_id", "candidate_pair_id"]).any():
        raise ValueError("V2.4 ranking manifest contains duplicate candidates within a group")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(output_path, index=False)
    return {
        "ranking_groups": int(ranking["ranking_group_id"].nunique()),
        "ranking_rows": int(len(ranking)),
        "positive_anchor_rows": int((ranking["candidate_role"] == "observed_cognate_positive").sum()),
        "constructed_candidate_rows": int((ranking["candidate_role"] == "constructed_contrastive_candidate").sum()),
        "split_counts": ranking.groupby("split")["ranking_group_id"].nunique().astype(int).to_dict(),
        "negative_type_counts": type_counts,
    }


def build_validation_controls(positive_path: Path, mutant_path: Path, output_path: Path) -> dict[str, Any]:
    positives = pd.read_csv(positive_path)
    mutants = pd.read_csv(mutant_path)
    rows: list[dict[str, Any]] = []
    for _, row in positives.iterrows():
        sequence = normalize_sequence(row.get("sequence"))
        rows.append(
            {
                "sample_id": clean(row.get("calibration_id")) or clean(row.get("molecule_name")),
                "molecule_name": clean(row.get("molecule_name")),
                "sequence_sha256": sequence_hash(sequence),
                "sequence": sequence,
                "family": clean(row.get("family")),
                "control_role": "known_positive_calibration",
                "label_hint": clean(row.get("label_role")),
                "leakage_policy": "exact_known_positive_calibration_only",
                "assay_ic50_nm": clean(row.get("blocking_ic50_nm")),
                "kd_m": clean(row.get("kd_m")),
                "reporter_ec50_nm": clean(row.get("reporter_ec50_nm")),
                "pose_count": clean(row.get("pose_count")),
                "ordinary_train_allowed": False,
                "ordinary_test_allowed": False,
                "candidate_ranking_allowed": False,
                "ground_truth_kind": "assay_backed_positive_calibration",
                "source_table": str(positive_path),
            }
        )
    for _, row in mutants.iterrows():
        sequence = normalize_sequence(row.get("sequence"))
        rows.append(
            {
                "sample_id": clean(row.get("control_id")) or clean(row.get("base_molecule")),
                "molecule_name": clean(row.get("base_molecule")),
                "sequence_sha256": sequence_hash(sequence),
                "sequence": sequence,
                "family": clean(row.get("family")),
                "control_role": clean(row.get("control_type")) or "mutant_control",
                "label_hint": clean(row.get("label_role")),
                "leakage_policy": clean(row.get("leakage_label")) or "mutant_or_leakage_control",
                "assay_ic50_nm": "",
                "kd_m": "",
                "reporter_ec50_nm": "",
                "pose_count": clean(row.get("consensus_rows")),
                "ordinary_train_allowed": False,
                "ordinary_test_allowed": False,
                "candidate_ranking_allowed": False,
                "ground_truth_kind": "constructed_mutant_or_leakage_control",
                "source_table": str(mutant_path),
            }
        )
    controls = pd.DataFrame(rows, columns=CONTROL_COLUMNS)
    if controls["sample_id"].eq("").any() or controls["sample_id"].duplicated().any():
        raise ValueError("PVRIG V2.4 control manifest requires unique non-empty sample IDs")
    if controls["sequence"].eq("").any():
        raise ValueError("PVRIG V2.4 control manifest requires non-empty sequences")
    for column in ("ordinary_train_allowed", "ordinary_test_allowed", "candidate_ranking_allowed"):
        if controls[column].any():
            raise ValueError(f"Control isolation violated: {column}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    controls.to_csv(output_path, index=False)
    return {
        "control_rows": int(len(controls)),
        "unique_control_sequence_hashes": int(controls["sequence_sha256"].nunique()),
        "duplicate_role_rows": int(controls["sequence_sha256"].duplicated().sum()),
        "positive_controls": int((controls["control_role"] == "known_positive_calibration").sum()),
        "mutant_or_reference_controls": int((controls["control_role"] != "known_positive_calibration").sum()),
        "ground_truth_kind_counts": controls["ground_truth_kind"].value_counts().to_dict(),
    }


def _pose_summary_rows(path: Path, source_lane: str, id_column: str) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    if id_column not in frame.columns or "consensus_class" not in frame.columns:
        raise ValueError(f"Pose table {path} lacks {id_column}/consensus_class")
    rows: list[dict[str, Any]] = []
    for sample_id, group in frame.groupby(id_column, sort=False):
        counts = group["consensus_class"].fillna("").astype(str).value_counts()
        known = sum(int(counts.get(name, 0)) for name in (
            "CONSENSUS_BLOCKER_LIKE_A", "SINGLE_BASELINE_BLOCKER_RECHECK",
            "BLOCKER_PLAUSIBLE_B", "EVIDENCE_INFERENCE_ONLY_E",
        ))
        rows.append(
            {
                "sample_id": clean(sample_id),
                "source_lane": source_lane,
                "pose_rows": int(len(group)),
                "consensus_blocker_like_a_count": int(counts.get("CONSENSUS_BLOCKER_LIKE_A", 0)),
                "single_baseline_recheck_count": int(counts.get("SINGLE_BASELINE_BLOCKER_RECHECK", 0)),
                "blocker_plausible_b_count": int(counts.get("BLOCKER_PLAUSIBLE_B", 0)),
                "evidence_inference_only_e_count": int(counts.get("EVIDENCE_INFERENCE_ONLY_E", 0)),
                "other_class_count": int(len(group) - known),
                "any_blocker_like_a": bool(counts.get("CONSENSUS_BLOCKER_LIKE_A", 0) > 0),
                "manual_review_required": True,
                "proxy_semantics": "docking_proxy_not_experimental_label",
            }
        )
    return rows


def build_pose_proxy_summary(positive_pose_path: Path, mutant_pose_path: Path, output_path: Path) -> dict[str, Any]:
    positive = pd.read_csv(positive_pose_path)
    mutant = pd.read_csv(mutant_pose_path)
    rows = _pose_summary_rows(positive_pose_path, "known_positive_pose_calibration", "calibration_name")
    rows.extend(_pose_summary_rows(mutant_pose_path, "mutant_or_leakage_pose_control", "mutant_name"))
    summary = pd.DataFrame(rows, columns=POSE_COLUMNS)
    if summary["sample_id"].eq("").any() or summary.duplicated(["source_lane", "sample_id"]).any():
        raise ValueError("Pose proxy summary contains invalid sample IDs")
    if set(summary["proxy_semantics"]) != {"docking_proxy_not_experimental_label"}:
        raise ValueError("Pose proxy semantics drifted")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_path, index=False)
    return {
        "source_pose_rows": int(len(positive) + len(mutant)),
        "positive_pose_rows": int(len(positive)),
        "mutant_pose_rows": int(len(mutant)),
        "summary_rows": int(len(summary)),
    }


def validate_control_isolation(ranking: pd.DataFrame, controls: pd.DataFrame) -> dict[str, int]:
    control_hashes = set(controls["sequence_sha256"].astype(str))
    ranking_hashes = {sequence_hash(value) for value in ranking["vhh_seq"]}
    overlap = ranking_hashes & control_hashes
    if overlap:
        raise ValueError(f"PVRIG controls overlap ordinary V2.4 ranking sequences: {len(overlap)} hashes")
    return {"ranking_unique_vhh_hashes": len(ranking_hashes), "control_unique_vhh_hashes": len(control_hashes), "hash_overlap": 0}


def build_all(args: argparse.Namespace) -> dict[str, Any]:
    ranking_summary = build_ranking_groups(args.triplets, args.ranking_output)
    control_summary = build_validation_controls(args.positive_controls, args.mutant_controls, args.controls_output)
    pose_summary = build_pose_proxy_summary(args.positive_poses, args.mutant_poses, args.pose_summary_output)
    isolation = validate_control_isolation(pd.read_csv(args.ranking_output), pd.read_csv(args.controls_output))
    result = {
        "status": "PASS",
        "schema_version": "phase2_v2_4_manifest_contract_v1",
        "ranking": ranking_summary,
        "controls": control_summary,
        "pose_proxy": pose_summary,
        "isolation": isolation,
        "boundaries": {
            "constructed_negatives": "ranking proxies, not verified non-binders",
            "pvrig_controls": "calibration/leakage controls, never ordinary train/test/candidate rows",
            "pose_labels": "docking proxies, not experimental binding or blocker labels",
        },
        "outputs": {
            "ranking_groups": str(args.ranking_output),
            "validation_controls": str(args.controls_output),
            "pose_proxy_summary": str(args.pose_summary_output),
        },
    }
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triplets", type=Path, default=DEFAULT_TRIPLETS)
    parser.add_argument("--positive-controls", type=Path, default=DEFAULT_POSITIVE)
    parser.add_argument("--mutant-controls", type=Path, default=DEFAULT_MUTANT)
    parser.add_argument("--positive-poses", type=Path, default=DEFAULT_POSITIVE_POSES)
    parser.add_argument("--mutant-poses", type=Path, default=DEFAULT_MUTANT_POSES)
    parser.add_argument("--ranking-output", type=Path, default=DEFAULT_RANKING)
    parser.add_argument("--controls-output", type=Path, default=DEFAULT_CONTROLS)
    parser.add_argument("--pose-summary-output", type=Path, default=DEFAULT_POSE_SUMMARY)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT)
    return parser.parse_args()


def main() -> None:
    result = build_all(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
