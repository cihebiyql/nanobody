#!/usr/bin/env python3
"""Conservative V2.4 sequence-plus-geometry late fusion for candidate ranking.

The fused score is a deterministic computational proxy only. Missing or failed
candidate-specific geometry never boosts a sequence ensemble score: rows without
verified geometry keep their sequence score unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEQUENCE_ENSEMBLE = ROOT / "experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_3_multiseed_ensemble.csv"
DEFAULT_POSE_INDEX = ROOT / "experiments/phase2_5080_v1/data_splits/phase2_v2_4_candidate_pose_index.csv"
DEFAULT_OUTPUT = ROOT / "experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_v2_4_p3_pose_fusion.csv"
DEFAULT_AUDIT = ROOT / "experiments/phase2_5080_v1/audits/phase2_v2_4_p3_pose_fusion.json"

SCHEMA_VERSION = "pvrig_vhh_phase2_v2_4_p3_pose_fusion_v1"
EVIDENCE_BOUNDARY = "computational_candidate_ranking_proxy_not_binding_or_blocker_probability"
SEQUENCE_SCORE_COLUMNS = [
    "phase2_v2_4_sequence_ensemble_score",
    "ai_prior_mean",
    "phase2_v2_4_combined_ranking_ai_prior",
    "phase2_v2_3_combined_ranking_ai_prior",
    "phase2_v2_combined_rank_score",
]
GEOMETRY_WEIGHT = 0.15
MIN_GLOBAL_GEOMETRY_COVERAGE = 0.80
GEOMETRY_FEATURE_WEIGHTS = {
    "top_pose_pdb_gz_count_verified": 0.30,
    "haddock_best_score": 0.35,
    "haddock_consensus_sum_of_ranks": 0.20,
    "monomer_ca_count": 0.15,
}
LOWER_IS_BETTER = {"haddock_best_score", "haddock_consensus_sum_of_ranks"}
OUTPUT_FRONT_COLUMNS = [
    "v2_4_p3_rank",
    "candidate_id",
    "v2_4_p3_fused_proxy_score",
    "v2_4_sequence_ensemble_proxy_score",
    "v2_4_geometry_proxy_score",
    "v2_4_geometry_boost",
    "v2_4_pose_supported_fused_proxy_score",
    "v2_4_pose_supported_rank",
    "v2_4_geometry_available",
    "v2_4_global_fusion_policy",
    "v2_4_missing_geometry_policy",
    "v2_4_p3_evidence_boundary",
]


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."} else text


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty CSV: {path}")
    return pd.read_csv(path)


def ensure_unique(df: pd.DataFrame, key: str, label: str) -> None:
    if key not in df.columns:
        raise ValueError(f"{label} is missing required column {key}")
    duplicates = df.loc[df[key].astype(str).duplicated(), key].astype(str).tolist()
    if duplicates:
        raise ValueError(f"{label} has duplicate {key}: {duplicates[:5]}")


def choose_sequence_score_column(df: pd.DataFrame) -> str:
    for column in SEQUENCE_SCORE_COLUMNS:
        if column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any():
            return column
    raise ValueError(f"No usable sequence ensemble score column found; tried {SEQUENCE_SCORE_COLUMNS}")


def quantile_score(values: pd.Series, *, lower_is_better: bool = False) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    out = pd.Series(math.nan, index=values.index, dtype="float64")
    present = numeric.dropna()
    if present.empty:
        return out
    if len(present) == 1:
        out.loc[present.index] = 1.0
        return out
    ranks = present.rank(method="average", ascending=not lower_is_better)
    out.loc[present.index] = (ranks - 1.0) / (len(present) - 1.0)
    return out.clip(0.0, 1.0)


def verified_geometry_mask(df: pd.DataFrame) -> pd.Series:
    required = {"pose_index_status", "vhh_chain_a_exact_match", "pvrig_chain_b_exact_match", "top_pose_pdb_gz_count_verified"}
    missing = required - set(df.columns)
    if missing:
        return pd.Series(False, index=df.index)
    return (
        df["pose_index_status"].astype(str).eq("verified_pose_proxy")
        & df["vhh_chain_a_exact_match"].astype(str).str.lower().isin({"true", "1", "yes"})
        & df["pvrig_chain_b_exact_match"].astype(str).str.lower().isin({"true", "1", "yes"})
        & (pd.to_numeric(df["top_pose_pdb_gz_count_verified"], errors="coerce").fillna(0) > 0)
    )


def geometry_scores(merged: pd.DataFrame, mask: pd.Series) -> pd.Series:
    out = pd.Series(math.nan, index=merged.index, dtype="float64")
    if not mask.any():
        return out
    available_weights = {col: weight for col, weight in GEOMETRY_FEATURE_WEIGHTS.items() if col in merged.columns}
    if not available_weights:
        return out
    weighted = pd.Series(0.0, index=merged.index, dtype="float64")
    total_weight = 0.0
    for column, weight in available_weights.items():
        pool_values = merged.loc[mask, column]
        if pd.to_numeric(pool_values, errors="coerce").notna().sum() == 0:
            continue
        scored = quantile_score(pool_values, lower_is_better=column in LOWER_IS_BETTER)
        full = pd.Series(math.nan, index=merged.index, dtype="float64")
        full.loc[mask] = scored
        weighted = weighted + full.fillna(0.0) * weight
        total_weight += weight
    if total_weight > 0:
        out.loc[mask] = (weighted.loc[mask] / total_weight).clip(0.0, 1.0)
    return out


def fuse_tables(sequence_ensemble: pd.DataFrame, pose_index: pd.DataFrame) -> pd.DataFrame:
    ensure_unique(sequence_ensemble, "candidate_id", "sequence ensemble")
    if not pose_index.empty:
        ensure_unique(pose_index, "candidate_id", "pose index")
    score_column = choose_sequence_score_column(sequence_ensemble)
    merged = sequence_ensemble.copy()
    merged["candidate_id"] = merged["candidate_id"].astype(str)
    merged["v2_4_sequence_ensemble_proxy_score"] = pd.to_numeric(merged[score_column], errors="coerce")
    if merged["v2_4_sequence_ensemble_proxy_score"].isna().any():
        raise ValueError(f"Sequence score column {score_column} contains non-numeric values")

    if pose_index.empty:
        merged["v2_4_geometry_available"] = False
    else:
        merged = merged.merge(pose_index, on="candidate_id", how="left", validate="one_to_one", suffixes=("", "_pose"))
        merged["v2_4_geometry_available"] = verified_geometry_mask(merged)

    merged["v2_4_geometry_proxy_score"] = geometry_scores(merged, merged["v2_4_geometry_available"])
    available = merged["v2_4_geometry_available"] & merged["v2_4_geometry_proxy_score"].notna()
    geometry_coverage = float(available.mean()) if len(merged) else 0.0
    global_fusion_applied = geometry_coverage >= MIN_GLOBAL_GEOMETRY_COVERAGE
    raw_geometry_boost = GEOMETRY_WEIGHT * merged["v2_4_geometry_proxy_score"].fillna(0.0)
    merged["v2_4_pose_supported_fused_proxy_score"] = math.nan
    merged.loc[available, "v2_4_pose_supported_fused_proxy_score"] = (
        merged.loc[available, "v2_4_sequence_ensemble_proxy_score"] + raw_geometry_boost.loc[available]
    ).clip(upper=1.0)
    merged["v2_4_pose_supported_rank"] = pd.NA
    if available.any():
        merged.loc[available, "v2_4_pose_supported_rank"] = (
            merged.loc[available, "v2_4_pose_supported_fused_proxy_score"].rank(method="first", ascending=False).astype("Int64")
        )
    merged["v2_4_geometry_boost"] = 0.0
    if global_fusion_applied:
        merged.loc[available, "v2_4_geometry_boost"] = raw_geometry_boost.loc[available]
    merged["v2_4_p3_fused_proxy_score"] = (merged["v2_4_sequence_ensemble_proxy_score"] + merged["v2_4_geometry_boost"]).clip(upper=1.0)
    missing = ~available
    merged.loc[missing, "v2_4_p3_fused_proxy_score"] = merged.loc[missing, "v2_4_sequence_ensemble_proxy_score"]
    merged["v2_4_missing_geometry_policy"] = "AI_SEQUENCE_ONLY_NO_GEOMETRY_BOOST"
    merged.loc[available, "v2_4_missing_geometry_policy"] = (
        "SEQUENCE_PLUS_VERIFIED_CANDIDATE_POSE_PROXY"
        if global_fusion_applied
        else "POSE_PROXY_USED_IN_SUPPORTED_SUBSET_ONLY"
    )
    merged["v2_4_global_fusion_policy"] = (
        "GLOBAL_POSE_FUSION_APPLIED_SUFFICIENT_COVERAGE"
        if global_fusion_applied
        else "SEQUENCE_ONLY_GLOBAL_RANK_INCOMPLETE_POSE_COVERAGE"
    )
    merged["v2_4_p3_evidence_boundary"] = EVIDENCE_BOUNDARY
    merged["v2_4_p3_sequence_score_column"] = score_column
    merged["schema_version"] = SCHEMA_VERSION
    merged = merged.sort_values(["v2_4_p3_fused_proxy_score", "v2_4_sequence_ensemble_proxy_score", "candidate_id"], ascending=[False, False, True]).reset_index(drop=True)
    merged.insert(0, "v2_4_p3_rank", range(1, len(merged) + 1))
    front = [col for col in OUTPUT_FRONT_COLUMNS if col in merged.columns]
    rest = [col for col in merged.columns if col not in front]
    return merged[front + rest]


def run_fusion(sequence_csv: Path, pose_index_csv: Path | None, output: Path, audit_json: Path | None = None) -> dict[str, Any]:
    sequence = read_csv(sequence_csv)
    pose = read_csv(pose_index_csv) if pose_index_csv is not None and pose_index_csv.exists() else pd.DataFrame(columns=["candidate_id"])
    fused = fuse_tables(sequence, pose)
    output.parent.mkdir(parents=True, exist_ok=True)
    fused.to_csv(output, index=False)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "sequence_csv": str(sequence_csv),
        "pose_index_csv": str(pose_index_csv) if pose_index_csv is not None else "",
        "output": str(output),
        "rows": int(len(fused)),
        "geometry_available_rows": int(fused["v2_4_geometry_available"].sum()),
        "geometry_coverage_fraction": float(fused["v2_4_geometry_available"].mean()) if len(fused) else 0.0,
        "minimum_global_geometry_coverage": MIN_GLOBAL_GEOMETRY_COVERAGE,
        "global_geometry_fusion_applied": bool((fused["v2_4_global_fusion_policy"] == "GLOBAL_POSE_FUSION_APPLIED_SUFFICIENT_COVERAGE").all()),
        "pose_supported_rows_ranked": int(fused["v2_4_pose_supported_rank"].notna().sum()),
        "sequence_only_rows": int((fused["v2_4_missing_geometry_policy"] == "AI_SEQUENCE_ONLY_NO_GEOMETRY_BOOST").sum()),
        "evidence_boundary": EVIDENCE_BOUNDARY,
    }
    if audit_json is not None:
        audit_json.parent.mkdir(parents=True, exist_ok=True)
        audit_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-ensemble", type=Path, default=DEFAULT_SEQUENCE_ENSEMBLE)
    parser.add_argument("--pose-index", type=Path, default=DEFAULT_POSE_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    summary = run_fusion(args.sequence_ensemble, args.pose_index, args.output, args.audit_json)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
