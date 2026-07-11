#!/usr/bin/env python3
"""Deterministic P3 candidate-level late fusion for ranking only.

This script fuses three evidence families without training a calibrator:

1. Phase 2 candidate ranking features.
2. External nanobody/antigen binding-site priors.
3. Optional pose/geometry evidence when a real pose row exists.

All normalizers are rank/quantile transforms fitted only on the current
non-leakage candidate pool. Output scores are ranking scores, not calibrated
probabilities and not experimental binding/blocker claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

EVIDENCE_BOUNDARY = "computational_candidate_ranking_not_experimental_binding_or_blocker_probability"
EXTERNAL_PRIOR_BOUNDARY = "external_nanobody_antigen_binding_and_site_priors_not_blocker_scores"
NO_LEAKAGE_LABEL = "NO_KNOWN_POSITIVE_LEAKAGE"

# Fixed, documented weights. Missing feature columns are ignored and the
# remaining weights inside that component are renormalized deterministically.
PHASE2_FEATURE_WEIGHTS: dict[str, float] = {
    "phase2_v2_3_combined_ranking_ai_prior": 0.30,
    "phase2_v2_3_pair_ranking_logit_norm": 0.18,
    "phase2_v2_3_sigmoid_pair_ranking_ai_prior_norm": 0.12,
    "phase2_v2_3_contact_top20_mean_ai_prior_norm": 0.12,
    "phase2_v2_3_cdr3_contact_top20_mean_ai_prior_norm": 0.18,
    "phase2_v2_3_cdr3_contact_mean_ai_prior": 0.10,
    "phase2_v2_combined_rank_score": 0.50,
    "phase2_v2_pair_binding_probability": 0.20,
    "phase2_v2_pvrig_target_epitope_mass": 0.15,
    "phase2_v2_cdr3_hotspot_contact_mean": 0.15,
}
EXTERNAL_FEATURE_WEIGHTS: dict[str, float] = {
    "nanobind_seq_raw_score": 0.20,
    "nanobind_pro_raw_score": 0.15,
    "deepnano_seq_raw_score": 0.20,
    "nanobind_site_target_minus_background": 0.15,
    "nanobind_site_target_weighted_mean": 0.10,
    "deepnano_site_target_minus_background": 0.10,
    "deepnano_site_target_weighted_mean": 0.10,
}
AI_COMPONENT_WEIGHTS: dict[str, float] = {"phase2": 0.55, "external_prior": 0.45}
P3_COMPONENT_WEIGHTS: dict[str, float] = {"ai_prior": 0.80, "pose_geometry": 0.20}

POSE_FEATURE_WEIGHTS: dict[str, float] = {
    "pose_interface_contact_count": 0.30,
    "pose_interface_confidence": 0.25,
    "pose_geometry_quality": 0.20,
    "pose_buried_sasa": 0.15,
    "pose_clash_count": 0.10,  # lower is better; direction is inferred by name.
    "heavy_atom_interface_contacts_le_4p5A": 0.30,
    "hotspot_weighted_contacts": 0.20,
    "hotspot_contact_count": 0.20,
    "cdr3_contacts": 0.15,
    "minimum_heavy_atom_distance_A": 0.10,
    "heavy_atom_clashes_lt_2p0A": 0.05,
}
LOWER_IS_BETTER_TOKENS = ("clash", "rmsd", "pae", "distance", "violation", "bad", "error")
ID_COLUMNS = {"candidate_id", "pose_id", "pose_path", "pose_file", "structure_path"}
VALID_NO_GEOMETRY_QC_STATUS = {"", "unchecked", "pass", "passed", "ok", "valid", "success"}
INVALID_STATUS_TOKENS = ("fail", "failed", "missing", "no_pose", "not_applicable", "parse_failed", "error")


@dataclass(frozen=True)
class FusionInputs:
    phase2_predictions: Path
    external_priors: Path
    output: Path
    audit_json: Path | None
    pose_manifest: Path | None = None
    geometry: Path | None = None
    leakage_manifest: Path | None = None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty CSV: {path}")
    return pd.read_csv(path)


def ensure_unique(df: pd.DataFrame, key: str, name: str) -> None:
    if key not in df.columns:
        raise ValueError(f"{name} is missing required column {key}")
    duplicates = df[key][df[key].duplicated()].astype(str).tolist()
    if duplicates:
        raise ValueError(f"{name} has duplicate {key} values: {duplicates[:5]}")


def normalize_sequence(seq: Any) -> str:
    return "".join(ch for ch in str(seq or "").upper() if ch.isalpha())


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."}:
        return ""
    return text


def sequence_sha256(seq: str) -> str:
    return hashlib.sha256(seq.encode("utf-8")).hexdigest()


def sequence_identity(a: str, b: str) -> float:
    a = normalize_sequence(a)
    b = normalize_sequence(b)
    if not a or not b:
        return 0.0
    max_len = max(len(a), len(b))
    matches = sum(x == y for x, y in zip(a, b))
    return matches / max_len


def load_known_positive_sequences(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    df = read_csv(path)
    if "sequence" not in df.columns:
        return []
    mask = pd.Series(True, index=df.index)
    if "role" in df.columns:
        mask &= df["role"].astype(str).str.contains("known_positive", case=False, na=False)
    if "leakage_policy" in df.columns:
        mask &= df["leakage_policy"].astype(str).str.contains("exclude", case=False, na=False)
    return [normalize_sequence(seq) for seq in df.loc[mask, "sequence"].tolist() if normalize_sequence(seq)]


def is_safe_leakage_value(value: Any) -> bool:
    text = str(value or "").strip()
    lower = text.lower()
    return (
        not text
        or lower in {"nan", "none", "false", "0"}
        or text == NO_LEAKAGE_LABEL
        or "no_known_positive_leakage" in lower
    )


def leakage_reason(row: pd.Series, known_positive_sequences: list[str]) -> str:
    leakage_cols = [col for col in row.index if "leakage" in col.lower()]
    for col in leakage_cols:
        value = str(row[col] or "").strip()
        if not is_safe_leakage_value(value):
            return f"leakage_field:{col}={value}"
    candidate_seq = normalize_sequence(row.get("candidate_sequence", ""))
    candidate_sha = str(row.get("candidate_sequence_sha256", "") or "").strip().lower()
    for known in known_positive_sequences:
        if candidate_sha and candidate_sha == sequence_sha256(known):
            return "exact_known_positive_sequence_sha256"
        if candidate_seq:
            if candidate_seq == known:
                return "exact_known_positive_sequence"
            if sequence_identity(candidate_seq, known) >= 0.90:
                return "near_known_positive_sequence_identity_ge_0_90"
    return ""


def quantile_normalize(values: pd.Series, *, lower_is_better: bool = False) -> pd.Series:
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


def weighted_component(df: pd.DataFrame, weights: dict[str, float], pool_mask: pd.Series) -> pd.Series:
    available = {col: weight for col, weight in weights.items() if col in df.columns}
    if not available:
        raise ValueError(f"None of the expected feature columns are present: {sorted(weights)}")
    normalized = []
    active_weights = []
    pool = df.loc[pool_mask]
    for col, weight in available.items():
        lower_is_better = any(token in col.lower() for token in LOWER_IS_BETTER_TOKENS)
        norm_pool = quantile_normalize(pool[col], lower_is_better=lower_is_better)
        full_norm = pd.Series(math.nan, index=df.index, dtype="float64")
        full_norm.loc[pool.index] = norm_pool
        normalized.append(full_norm)
        active_weights.append(weight)
    denom = sum(active_weights)
    component = sum(series.fillna(0.0) * weight for series, weight in zip(normalized, active_weights)) / denom
    component[~pool_mask] = math.nan
    return component.clip(0.0, 1.0)


def discover_pose_weights(df: pd.DataFrame) -> dict[str, float]:
    weights = {col: weight for col, weight in POSE_FEATURE_WEIGHTS.items() if col in df.columns}
    if weights:
        return weights
    numeric_cols: list[str] = []
    for col in df.columns:
        lower = col.lower()
        if col in ID_COLUMNS or lower.endswith("_source") or "leakage" in lower:
            continue
        if lower.startswith(("pose_", "geometry_")) and pd.to_numeric(df[col], errors="coerce").notna().any():
            numeric_cols.append(col)
    return {col: 1.0 for col in sorted(numeric_cols)}


def load_pose_table(pose_manifest: Path | None, geometry: Path | None) -> pd.DataFrame:
    tables: list[pd.DataFrame] = []
    if pose_manifest is not None:
        pose = read_csv(pose_manifest)
        ensure_unique(pose, "candidate_id", "pose manifest")
        tables.append(pose)
    if geometry is not None:
        geom = read_csv(geometry)
        ensure_unique(geom, "candidate_id", "geometry")
        tables.append(geom)
    if not tables:
        return pd.DataFrame(columns=["candidate_id"])
    pose_table = tables[0]
    for table in tables[1:]:
        overlap = [col for col in table.columns if col in pose_table.columns and col != "candidate_id"]
        if overlap:
            table = table.rename(columns={col: f"geometry_{col}" for col in overlap})
        pose_table = pose_table.merge(table, on="candidate_id", how="outer", validate="one_to_one")
    ensure_unique(pose_table, "candidate_id", "pose/geometry combined table")
    return pose_table


def first_present(row: pd.Series, columns: Iterable[str]) -> str:
    for col in columns:
        if col in row.index:
            value = clean_text(row.get(col))
            if value:
                return value
    return ""


def path_exists(path_text: str) -> bool:
    if not path_text:
        return False
    return Path(path_text).expanduser().exists()


def status_has_invalid_token(status: str) -> bool:
    lower = status.lower()
    return any(token in lower for token in INVALID_STATUS_TOKENS)


def pose_available_flags(df: pd.DataFrame, *, geometry_required: bool) -> pd.Series:
    available = pd.Series(False, index=df.index, dtype="bool")
    for idx, row in df.iterrows():
        pose_path = first_present(row, ("pose_path", "geometry_pose_path", "pose_file", "structure_path"))
        if not pose_path or not path_exists(pose_path):
            continue
        pose_status = first_present(row, ("pose_status", "geometry_pose_status")).lower()
        if pose_status != "pose_supplied":
            continue
        if geometry_required:
            if first_present(row, ("geometry_status",)).lower() == "ok":
                available.loc[idx] = True
            continue
        qc_status = first_present(row, ("qc_status", "geometry_qc_status")).lower()
        if qc_status in VALID_NO_GEOMETRY_QC_STATUS and not status_has_invalid_token(qc_status):
            available.loc[idx] = True
    return available


def fuse_candidates(inputs: FusionInputs) -> dict[str, Any]:
    phase2 = read_csv(inputs.phase2_predictions)
    priors = read_csv(inputs.external_priors)
    ensure_unique(phase2, "candidate_id", "phase2 predictions")
    ensure_unique(priors, "candidate_id", "external priors")

    prior_boundary_cols = [col for col in priors.columns if col.endswith("evidence_boundary")]
    for col in prior_boundary_cols:
        bad = priors[col].astype(str).ne(EXTERNAL_PRIOR_BOUNDARY)
        if bad.any():
            raise ValueError(f"External prior boundary mismatch in {col}: {priors.loc[bad, col].head().tolist()}")

    shared = [col for col in priors.columns if col in phase2.columns and col != "candidate_id"]
    priors_for_join = priors.drop(columns=shared)
    merged = phase2.merge(priors_for_join, on="candidate_id", how="left", validate="one_to_one", indicator="_external_join")
    missing_external = merged.loc[merged["_external_join"] != "both", "candidate_id"].astype(str).tolist()
    if missing_external:
        raise ValueError(f"Missing external prior rows for candidates: {missing_external[:10]}")
    merged = merged.drop(columns=["_external_join"])

    pose_table = load_pose_table(inputs.pose_manifest, inputs.geometry)
    pose_cols = [col for col in pose_table.columns if col != "candidate_id"]
    if pose_cols:
        merged = merged.merge(pose_table, on="candidate_id", how="left", validate="one_to_one", indicator="_pose_join")
        merged["p3_pose_available"] = merged["_pose_join"].eq("both") & pose_available_flags(merged, geometry_required=inputs.geometry is not None)
        merged = merged.drop(columns=["_pose_join"])
    else:
        merged["p3_pose_available"] = False

    known_positive_sequences = load_known_positive_sequences(inputs.leakage_manifest)
    reasons = [leakage_reason(row, known_positive_sequences) for _, row in merged.iterrows()]
    merged["p3_leakage_holdout"] = [bool(reason) for reason in reasons]
    merged["p3_leakage_holdout_reason"] = reasons
    pool_mask = ~merged["p3_leakage_holdout"]
    if not pool_mask.any():
        raise ValueError("No non-leakage candidates remain for P3 fusion")

    merged["p3_phase2_component_ranking_score"] = weighted_component(merged, PHASE2_FEATURE_WEIGHTS, pool_mask)
    merged["p3_external_prior_component_ranking_score"] = weighted_component(merged, EXTERNAL_FEATURE_WEIGHTS, pool_mask)
    merged["p3_ai_prior_ranking_score"] = (
        AI_COMPONENT_WEIGHTS["phase2"] * merged["p3_phase2_component_ranking_score"]
        + AI_COMPONENT_WEIGHTS["external_prior"] * merged["p3_external_prior_component_ranking_score"]
    ).clip(0.0, 1.0)

    pose_weights = discover_pose_weights(merged.loc[merged["p3_pose_available"]]) if merged["p3_pose_available"].any() else {}
    pose_pool_mask = pool_mask & merged["p3_pose_available"]
    if pose_weights and pose_pool_mask.any():
        merged["p3_pose_geometry_ranking_score"] = weighted_component(merged, pose_weights, pose_pool_mask)
    else:
        merged["p3_pose_geometry_ranking_score"] = math.nan

    merged["p3_fusion_uses_pose"] = pool_mask & merged["p3_pose_available"] & merged["p3_pose_geometry_ranking_score"].notna()
    merged["p3_fused_ranking_score"] = math.nan
    missing_pose_mask = pool_mask & ~merged["p3_fusion_uses_pose"]
    merged.loc[missing_pose_mask, "p3_fused_ranking_score"] = merged.loc[missing_pose_mask, "p3_ai_prior_ranking_score"]
    pose_mask = pool_mask & merged["p3_fusion_uses_pose"]
    merged.loc[pose_mask, "p3_fused_ranking_score"] = (
        P3_COMPONENT_WEIGHTS["ai_prior"] * merged.loc[pose_mask, "p3_ai_prior_ranking_score"]
        + P3_COMPONENT_WEIGHTS["pose_geometry"] * merged.loc[pose_mask, "p3_pose_geometry_ranking_score"]
    )
    merged.loc[merged["p3_leakage_holdout"], "p3_fused_ranking_score"] = math.nan

    rankable = merged["p3_fused_ranking_score"].notna()
    merged["p3_candidate_rank"] = pd.NA
    merged.loc[rankable, "p3_candidate_rank"] = merged.loc[rankable, "p3_fused_ranking_score"].rank(method="first", ascending=False).astype("Int64")
    merged["p3_missing_pose_policy"] = ""
    merged.loc[pool_mask & ~merged["p3_pose_available"], "p3_missing_pose_policy"] = "AI_PRIOR_ONLY"
    merged.loc[pool_mask & merged["p3_pose_available"], "p3_missing_pose_policy"] = "POSE_AUGMENTED_WHEN_REAL_ROW_PRESENT"
    merged.loc[merged["p3_leakage_holdout"], "p3_missing_pose_policy"] = "LEAKAGE_HOLDOUT_NOT_RANKED"
    merged["p3_label_policy"] = "ranking_only_no_calibrated_probability_no_experimental_claim"
    merged["p3_evidence_boundary"] = EVIDENCE_BOUNDARY
    merged["p3_weight_spec_json"] = json.dumps(
        {
            "phase2_feature_weights": PHASE2_FEATURE_WEIGHTS,
            "external_feature_weights": EXTERNAL_FEATURE_WEIGHTS,
            "ai_component_weights": AI_COMPONENT_WEIGHTS,
            "p3_component_weights_when_pose_present": P3_COMPONENT_WEIGHTS,
            "pose_feature_weights": pose_weights,
            "normalization": "rank_quantile_fit_on_current_non_leakage_candidate_pool_only",
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    score_cols = [
        "p3_phase2_component_ranking_score",
        "p3_external_prior_component_ranking_score",
        "p3_ai_prior_ranking_score",
        "p3_pose_geometry_ranking_score",
        "p3_fused_ranking_score",
    ]
    for col in score_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").round(8)

    first_cols = [
        "candidate_id",
        "p3_candidate_rank",
        "p3_fused_ranking_score",
        "p3_ai_prior_ranking_score",
        "p3_phase2_component_ranking_score",
        "p3_external_prior_component_ranking_score",
        "p3_pose_geometry_ranking_score",
        "p3_pose_available",
        "p3_fusion_uses_pose",
        "p3_missing_pose_policy",
        "p3_leakage_holdout",
        "p3_leakage_holdout_reason",
        "p3_label_policy",
        "p3_evidence_boundary",
        "p3_weight_spec_json",
    ]
    remaining_cols = [col for col in merged.columns if col not in first_cols]
    out_df = merged[first_cols + remaining_cols].sort_values(
        by=["p3_leakage_holdout", "p3_candidate_rank", "candidate_id"],
        ascending=[True, True, True],
        na_position="last",
    )
    inputs.output.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(inputs.output, index=False)

    audit = {
        "status": "PASS",
        "output": str(inputs.output),
        "candidate_rows": int(len(out_df)),
        "ranked_rows": int(out_df["p3_fused_ranking_score"].notna().sum()),
        "leakage_holdout_rows": int(out_df["p3_leakage_holdout"].sum()),
        "pose_available_rows": int(out_df["p3_pose_available"].sum()),
        "pose_used_rows": int(out_df["p3_fusion_uses_pose"].sum()),
        "missing_pose_ai_prior_only_rows": int((out_df["p3_missing_pose_policy"] == "AI_PRIOR_ONLY").sum()),
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "weight_spec": json.loads(out_df["p3_weight_spec_json"].iloc[0]),
    }
    if inputs.audit_json is not None:
        inputs.audit_json.parent.mkdir(parents=True, exist_ok=True)
        inputs.audit_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2-predictions", type=Path, default=Path("experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv"))
    parser.add_argument("--external-priors", type=Path, default=Path("experiments/phase2_5080_v1/external_priors/external_prior_features_full50_v1.csv"))
    parser.add_argument("--pose-manifest", type=Path)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--leakage-manifest", type=Path, default=Path("experiments/phase2_5080_v1/data_splits/pvrig_external_calibration_manifest_v1.csv"))
    parser.add_argument("--output", type=Path, default=Path("experiments/phase2_5080_v1/predictions/p3_late_fusion_rankings_v1.csv"))
    parser.add_argument("--audit-json", type=Path, default=Path("experiments/phase2_5080_v1/audits/p3_late_fusion_rankings_v1.json"))
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    audit = fuse_candidates(
        FusionInputs(
            phase2_predictions=args.phase2_predictions,
            external_priors=args.external_priors,
            pose_manifest=args.pose_manifest,
            geometry=args.geometry,
            leakage_manifest=args.leakage_manifest,
            output=args.output,
            audit_json=args.audit_json,
        )
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
