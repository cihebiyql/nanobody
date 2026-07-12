#!/usr/bin/env python3
"""Join V3 front-screen scores to existing blinded geometry evidence without relabeling truth."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from phase2_v3_contracts import sha256_file

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_SCORE = EXP_DIR / "predictions" / "pvrig_candidate_ranking_v3.csv"
DEFAULT_KEY = EXP_DIR / "assays" / "pvrig_v2_5_prospective_v1" / "blinding_key.csv"
DEFAULT_GEOMETRY = EXP_DIR / "assays" / "pvrig_v2_5_prospective_v1" / "computational_preqc" / "large_scale_cascade_20260711" / "cascade" / "final_blocker_screen.tsv"
DEFAULT_OUTPUT = EXP_DIR / "predictions" / "pvrig_candidate_ranking_v3_structure_fusion.csv"

GEOMETRY_TIER = {
    "FINAL_POSITIVE_HIGH": 3,
    "FINAL_RECHECK_SINGLE_BASELINE": 2,
    "FINAL_POSITIVE_PLAUSIBLE": 1,
}


def fuse(score_path: Path, key_path: Path, geometry_path: Path, output_path: Path) -> dict:
    scores = pd.read_csv(score_path)
    scores = scores.loc[scores["screening_lane"].astype(str).eq("PROSPECTIVE_SCREENING")].copy()
    key = pd.read_csv(key_path, usecols=["assay_sample_id", "candidate_id", "sequence_sha256"])
    geometry = pd.read_csv(geometry_path, sep="\t")
    geometry_columns = [
        "candidate_id",
        "final_blocker_label",
        "docking_evidence_status",
        "hotspot_overlap_count",
        "total_vhh_pvrl2_residue_pair_occlusion",
        "cdr3_pvrl2_residue_pair_occlusion",
        "cdr3_occlusion_fraction",
        "final_rank",
    ]
    missing = set(geometry_columns) - set(geometry.columns)
    if missing:
        raise ValueError(f"Geometry table missing columns: {sorted(missing)}")
    mapped = geometry[geometry_columns].merge(
        key,
        left_on="candidate_id",
        right_on="assay_sample_id",
        how="left",
        validate="one_to_one",
        suffixes=("_blinded", ""),
    )
    mapped = mapped.drop(columns=["candidate_id_blinded", "assay_sample_id"])
    if mapped["candidate_id"].isna().any():
        raise ValueError("Geometry evidence contains an unmapped blinded candidate ID")
    fused = scores.merge(mapped, on=["candidate_id", "sequence_sha256"], how="left", validate="one_to_one")
    fused["structure_evidence_status"] = fused["docking_evidence_status"].fillna("NOT_AVAILABLE")
    fused["geometry_priority_tier"] = fused["final_blocker_label"].map(GEOMETRY_TIER).fillna(0).astype(int)
    fused["combined_priority_rank"] = (
        fused.sort_values(["geometry_priority_tier", "deployment_score"], ascending=[False, False])
        .reset_index()
        .reset_index()
        .set_index("index")["level_0"]
        .add(1)
        .reindex(fused.index)
        .astype(int)
    )
    fused["fusion_semantics"] = "geometry_tier_then_binding_prior_not_probability"
    fused["claim_boundary"] = "computational_triage_not_measured_pvrig_binding_or_blocking"
    fused = fused.sort_values("combined_priority_rank")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fused.to_csv(output_path, index=False)
    summary = {
        "schema_version": "phase2_v3_structure_fusion_v1",
        "input_score": str(score_path),
        "input_score_sha256": sha256_file(score_path),
        "geometry_source": str(geometry_path),
        "geometry_source_sha256": sha256_file(geometry_path),
        "candidate_count": len(fused),
        "with_geometry_count": int(fused["final_blocker_label"].notna().sum()),
        "without_geometry_count": int(fused["final_blocker_label"].isna().sum()),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "claim_boundary": "triage_only_no_experimental_truth",
    }
    output_path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, default=DEFAULT_SCORE)
    parser.add_argument("--blinding-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    fuse(args.score, args.blinding_key, args.geometry, args.output)
