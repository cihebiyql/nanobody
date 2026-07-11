#!/usr/bin/env python3
"""Validate deterministic P3 late-fusion ranking outputs."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from score_p3_late_fusion import EVIDENCE_BOUNDARY, is_safe_leakage_value, pose_available_flags

SCORE_COLUMNS = [
    "p3_phase2_component_ranking_score",
    "p3_external_prior_component_ranking_score",
    "p3_ai_prior_ranking_score",
    "p3_pose_geometry_ranking_score",
    "p3_fused_ranking_score",
]
POSE_OUTPUT_COLUMNS = ["p3_pose_geometry_ranking_score"]
FORBIDDEN_OUTPUT_TOKENS = ("probability", "calibrated", "experimental_binding", "binding_claim")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty CSV: {path}")
    return pd.read_csv(path)


def unique_ids(df: pd.DataFrame, name: str) -> tuple[bool, str]:
    if "candidate_id" not in df.columns:
        return False, f"{name} missing candidate_id"
    dup = df["candidate_id"][df["candidate_id"].duplicated()].astype(str).tolist()
    return not dup, f"duplicates={dup[:5]}"


def score_range_ok(series: pd.Series, allow_na: bool = True) -> bool:
    numeric = pd.to_numeric(series, errors="coerce")
    if not allow_na and numeric.isna().any():
        return False
    present = numeric.dropna()
    return bool(((present >= 0.0) & (present <= 1.0)).all())


def leakage_expected(df: pd.DataFrame) -> pd.Series:
    leakage_cols = [col for col in df.columns if "leakage" in col.lower() and not col.startswith("p3_")]
    if not leakage_cols:
        return pd.Series(False, index=df.index)
    expected = pd.Series(False, index=df.index)
    for col in leakage_cols:
        expected |= ~df[col].map(is_safe_leakage_value)
    return expected


def combined_pose_table(pose: pd.DataFrame, geometry: pd.DataFrame) -> pd.DataFrame:
    tables = [df for df in (pose, geometry) if not df.empty]
    if not tables:
        return pd.DataFrame(columns=["candidate_id"])
    combined = tables[0].copy()
    for table in tables[1:]:
        table = table.copy()
        overlap = [col for col in table.columns if col in combined.columns and col != "candidate_id"]
        if overlap:
            table = table.rename(columns={col: f"geometry_{col}" for col in overlap})
        combined = combined.merge(table, on="candidate_id", how="outer", validate="one_to_one")
    return combined


def validate(args: argparse.Namespace) -> dict[str, Any]:
    output = read_csv(Path(args.output))
    phase2 = read_csv(Path(args.phase2_predictions))
    priors = read_csv(Path(args.external_priors))
    pose = read_csv(Path(args.pose_manifest)) if args.pose_manifest else pd.DataFrame(columns=["candidate_id"])
    geometry = read_csv(Path(args.geometry)) if args.geometry else pd.DataFrame(columns=["candidate_id"])

    checks: list[tuple[str, bool, str]] = []
    for name, df in (("output", output), ("phase2", phase2), ("external_priors", priors)):
        ok, evidence = unique_ids(df, name)
        checks.append((f"{name}_candidate_id_unique", ok, evidence))

    output_ids = set(output["candidate_id"].astype(str)) if "candidate_id" in output else set()
    phase2_ids = set(phase2["candidate_id"].astype(str)) if "candidate_id" in phase2 else set()
    prior_ids = set(priors["candidate_id"].astype(str)) if "candidate_id" in priors else set()
    checks.append(("output_matches_phase2_candidate_pool", output_ids == phase2_ids, f"output={len(output_ids)} phase2={len(phase2_ids)}"))
    checks.append(("external_prior_join_complete", phase2_ids.issubset(prior_ids), f"missing={sorted(phase2_ids - prior_ids)[:5]}"))

    if not pose.empty:
        ok, evidence = unique_ids(pose, "pose_manifest")
        checks.append(("pose_manifest_candidate_id_unique", ok, evidence))
    if not geometry.empty:
        ok, evidence = unique_ids(geometry, "geometry")
        checks.append(("geometry_candidate_id_unique", ok, evidence))
    pose_table = combined_pose_table(pose, geometry)
    if not pose_table.empty:
        usable_pose_ids = set(pose_table.loc[pose_available_flags(pose_table, geometry_required=not geometry.empty), "candidate_id"].astype(str))
        input_pose_ids = set(pose_table["candidate_id"].astype(str))
    else:
        usable_pose_ids = set()
        input_pose_ids = set()

    required_cols = {
        "candidate_id",
        "p3_fused_ranking_score",
        "p3_ai_prior_ranking_score",
        "p3_pose_geometry_ranking_score",
        "p3_pose_available",
        "p3_fusion_uses_pose",
        "p3_missing_pose_policy",
        "p3_leakage_holdout",
        "p3_evidence_boundary",
        "p3_label_policy",
    }
    missing_cols = sorted(required_cols - set(output.columns))
    checks.append(("required_output_columns_present", not missing_cols, f"missing={missing_cols}"))

    for col in SCORE_COLUMNS:
        if col in output.columns:
            checks.append((f"{col}_range_0_1", score_range_ok(output[col]), f"non_null={int(pd.to_numeric(output[col], errors='coerce').notna().sum())}"))

    boundary_ok = "p3_evidence_boundary" in output and output["p3_evidence_boundary"].astype(str).eq(EVIDENCE_BOUNDARY).all()
    checks.append(("evidence_boundary_exact", boundary_ok, EVIDENCE_BOUNDARY))
    p3_cols = [col for col in output.columns if col.startswith("p3_")]
    forbidden_cols = [col for col in p3_cols if any(token in col.lower() for token in FORBIDDEN_OUTPUT_TOKENS)]
    checks.append(("outputs_named_as_ranking_not_calibrated_probabilities", not forbidden_cols, f"forbidden_columns={forbidden_cols}"))

    if "p3_leakage_holdout" in output.columns:
        out_by_id = output.set_index(output["candidate_id"].astype(str), drop=False)
        phase2_expected = leakage_expected(phase2)
        output_expected = leakage_expected(output)
        expected_ids = set(phase2.loc[phase2_expected, "candidate_id"].astype(str))
        expected_ids |= set(output.loc[output_expected, "candidate_id"].astype(str))
        held_ids = set(out_by_id.loc[out_by_id["p3_leakage_holdout"].astype(str).str.lower().isin({"true", "1"}), "candidate_id"].astype(str))
        leak_scores = pd.to_numeric(out_by_id.loc[list(held_ids), "p3_fused_ranking_score"], errors="coerce") if held_ids else pd.Series(dtype="float64")
        leak_ranks = pd.to_numeric(out_by_id.loc[list(held_ids), "p3_candidate_rank"], errors="coerce") if held_ids and "p3_candidate_rank" in output.columns else pd.Series(dtype="float64")
        checks.append(("leakage_fields_are_held_out", expected_ids.issubset(held_ids), f"expected={sorted(expected_ids)} held={sorted(held_ids)}"))
        checks.append(("leakage_holdouts_not_ranked", leak_scores.isna().all() and leak_ranks.isna().all(), f"held={len(held_ids)}"))

    no_pose_expected = output["candidate_id"].astype(str).map(lambda cid: cid not in usable_pose_ids) if "candidate_id" in output else pd.Series(False)
    held = output["p3_leakage_holdout"].astype(str).str.lower().isin({"true", "1"}) if "p3_leakage_holdout" in output else pd.Series(False, index=output.index)
    no_pose_ranked = no_pose_expected & ~held
    if no_pose_ranked.any():
        no_pose_pose_scores = pd.to_numeric(output.loc[no_pose_ranked, "p3_pose_geometry_ranking_score"], errors="coerce")
        no_pose_fusion = pd.to_numeric(output.loc[no_pose_ranked, "p3_fused_ranking_score"], errors="coerce")
        no_pose_ai = pd.to_numeric(output.loc[no_pose_ranked, "p3_ai_prior_ranking_score"], errors="coerce")
        no_pose_diff = (no_pose_fusion - no_pose_ai).abs().fillna(math.inf)
        missing_policy_ok = output.loc[no_pose_ranked, "p3_missing_pose_policy"].astype(str).eq("AI_PRIOR_ONLY").all()
        missing_available_ok = ~output.loc[no_pose_ranked, "p3_pose_available"].astype(str).str.lower().isin({"true", "1"}).any()
        missing_uses_pose_ok = ~output.loc[no_pose_ranked, "p3_fusion_uses_pose"].astype(str).str.lower().isin({"true", "1"}).any()
        missing_label_text = " ".join(output.loc[no_pose_ranked, "p3_label_policy"].astype(str).str.lower().tolist())
        source_pose_cols = [col for col in output.columns if not col.startswith("p3_") and col.lower().startswith(("pose_", "geometry_"))]
        source_pose_blank = True
        if source_pose_cols and input_pose_ids:
            pure_missing = no_pose_ranked & output["candidate_id"].astype(str).map(lambda cid: cid not in input_pose_ids)
            if pure_missing.any():
                source_pose_blank = output.loc[pure_missing, source_pose_cols].isna().all().all()
        elif source_pose_cols:
            source_pose_blank = output.loc[no_pose_ranked, source_pose_cols].isna().all().all()
        checks.append(("missing_pose_has_no_fabricated_pose_score", no_pose_pose_scores.isna().all() and bool(source_pose_blank), f"rows={int(no_pose_ranked.sum())} source_pose_cols={source_pose_cols}"))
        checks.append(("missing_or_failed_geometry_is_ai_prior_only", bool((no_pose_diff <= 1e-8).all()) and missing_policy_ok and missing_available_ok and missing_uses_pose_ok, f"max_diff={float(no_pose_diff.max())}"))
        checks.append(("missing_pose_has_no_blocker_like_label", "blocker" not in missing_label_text, "label_policy checked"))

    pose_expected = output["candidate_id"].astype(str).map(lambda cid: cid in usable_pose_ids) if "candidate_id" in output else pd.Series(False)
    pose_ranked = pose_expected & ~held
    if pose_ranked.any():
        pose_scores = pd.to_numeric(output.loc[pose_ranked, "p3_pose_geometry_ranking_score"], errors="coerce")
        pose_available_ok = output.loc[pose_ranked, "p3_pose_available"].astype(str).str.lower().isin({"true", "1"}).all()
        pose_uses_ok = output.loc[pose_ranked, "p3_fusion_uses_pose"].astype(str).str.lower().isin({"true", "1"}).all()
        checks.append(("pose_rows_have_real_pose_scores", pose_scores.notna().all(), f"rows={int(pose_ranked.sum())}"))
        checks.append(("usable_pose_rows_are_marked_available", bool(pose_available_ok and pose_uses_ok), f"usable_pose_ids={sorted(usable_pose_ids)[:5]}"))
        checks.append(("pose_usage_requires_usable_pose_input", output.loc[output["p3_fusion_uses_pose"].astype(str).str.lower().isin({"true", "1"}), "candidate_id"].astype(str).map(lambda cid: cid in usable_pose_ids).all(), "usable pose ids checked"))

    failed = [name for name, ok, _ in checks if not ok]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": [{"name": name, "passed": bool(ok), "evidence": evidence} for name, ok, evidence in checks],
        "summary": {
            "output_rows": int(len(output)),
            "phase2_rows": int(len(phase2)),
            "external_prior_rows": int(len(priors)),
            "pose_manifest_rows": int(len(pose)),
            "geometry_rows": int(len(geometry)),
        },
    }
    if args.audit_json:
        Path(args.audit_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.audit_json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("experiments/phase2_5080_v1/predictions/p3_late_fusion_rankings_v1.csv"))
    parser.add_argument("--phase2-predictions", type=Path, default=Path("experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv"))
    parser.add_argument("--external-priors", type=Path, default=Path("experiments/phase2_5080_v1/external_priors/external_prior_features_full50_v1.csv"))
    parser.add_argument("--pose-manifest", type=Path)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--audit-json", type=Path, default=Path("experiments/phase2_5080_v1/audits/p3_late_fusion_validation_v1.json"))
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    result = validate(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
