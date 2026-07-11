#!/usr/bin/env python3
"""Build a portable multi-seed V2.3 candidate table for downstream P3 fusion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ENSEMBLE_SCHEMA = "pvrig_vhh_phase2_v2_3_multiseed_candidate_ensemble_v1"
BOUNDARY_TOKEN = "not calibrated blocker probability"
CORE_STD_COLUMNS = (
    "phase2_v2_3_pair_ranking_logit",
    "phase2_v2_3_sigmoid_pair_ranking_ai_prior",
    "phase2_v2_3_contact_top20_mean_ai_prior",
    "phase2_v2_3_cdr3_contact_top20_mean_ai_prior",
    "phase2_v2_3_cdr3_contact_mean_ai_prior",
    "phase2_v2_3_combined_ranking_ai_prior",
)
RECOMPUTED_NORMS = {
    "phase2_v2_3_pair_ranking_logit": "phase2_v2_3_pair_ranking_logit_norm",
    "phase2_v2_3_sigmoid_pair_ranking_ai_prior": "phase2_v2_3_sigmoid_pair_ranking_ai_prior_norm",
    "phase2_v2_3_contact_top20_mean_ai_prior": "phase2_v2_3_contact_top20_mean_ai_prior_norm",
    "phase2_v2_3_cdr3_contact_top20_mean_ai_prior": "phase2_v2_3_cdr3_contact_top20_mean_ai_prior_norm",
}


def minmax(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    lo = float(numeric.min())
    hi = float(numeric.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-12:
        return pd.Series(0.0, index=values.index)
    return (numeric - lo) / (hi - lo)


def _read_member(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing V2.3 candidate member: {path}")
    df = pd.read_csv(path)
    required = {"candidate_id", "rank", "schema_version", "phase2_v2_3_boundary_note"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    if df["candidate_id"].duplicated().any():
        raise ValueError(f"{path} contains duplicate candidate_id values")
    if not df["phase2_v2_3_boundary_note"].astype(str).str.contains(BOUNDARY_TOKEN, regex=False).all():
        raise ValueError(f"{path} has an incompatible evidence boundary")
    return df


def build_ensemble(paths: list[Path]) -> pd.DataFrame:
    if len(paths) < 2:
        raise ValueError("At least two seed candidate files are required")
    members = [_read_member(path) for path in paths]
    expected_ids = set(members[0]["candidate_id"].astype(str))
    schemas = set()
    seeds = set()
    for path, member in zip(paths, members):
        if set(member["candidate_id"].astype(str)) != expected_ids:
            raise ValueError(f"Candidate set mismatch: {path}")
        schemas.update(member["schema_version"].astype(str).unique())
        if "phase2_v2_3_seed" not in member.columns:
            raise ValueError(f"{path} is missing phase2_v2_3_seed")
        seeds.update(str(int(value)) for value in pd.to_numeric(member["phase2_v2_3_seed"], errors="raise").unique())
    if len(schemas) != 1:
        raise ValueError(f"Member schema mismatch: {sorted(schemas)}")
    if len(seeds) != len(paths):
        raise ValueError(f"Expected one unique seed per input, got {sorted(seeds)}")

    stacked = pd.concat(members, ignore_index=True, sort=False)
    first = members[0].set_index("candidate_id")
    passthrough_columns = [
        column
        for column in first.columns
        if column not in {"rank", "schema_version"}
        and not column.startswith("phase2_v2_3_")
        and not column.endswith("_json")
    ]
    out = first[passthrough_columns].copy()

    numeric_v23: list[str] = []
    for column in stacked.columns:
        if not column.startswith("phase2_v2_3_") or column.endswith("_norm"):
            continue
        if column in {"phase2_v2_3_seed", "phase2_v2_3_checkpoint_epoch", "phase2_v2_3_checkpoint_best_score"}:
            continue
        numeric = pd.to_numeric(stacked[column], errors="coerce")
        if numeric.notna().all():
            stacked[column] = numeric
            numeric_v23.append(column)
    grouped = stacked.groupby("candidate_id", sort=False)
    for column in numeric_v23:
        out[column] = grouped[column].mean().reindex(out.index)
        if column in CORE_STD_COLUMNS:
            out[f"{column}_seed_std"] = grouped[column].std(ddof=1).fillna(0.0).reindex(out.index)

    ranks = grouped["rank"]
    out["phase2_v2_3_rank_mean"] = ranks.mean().reindex(out.index)
    out["phase2_v2_3_rank_std"] = ranks.std(ddof=1).fillna(0.0).reindex(out.index)
    out["phase2_v2_3_rank_min"] = ranks.min().reindex(out.index)
    out["phase2_v2_3_rank_max"] = ranks.max().reindex(out.index)
    for raw, normalized in RECOMPUTED_NORMS.items():
        if raw in out.columns:
            out[normalized] = minmax(out[raw])

    out["phase2_v2_3_seed_count"] = len(seeds)
    out["phase2_v2_3_member_seeds"] = ";".join(sorted(seeds, key=int))
    out["phase2_v2_3_boundary_note"] = members[0]["phase2_v2_3_boundary_note"].iloc[0]
    out["phase2_v2_3_ensemble_policy"] = "mean_numeric_ai_priors_then_rank_by_mean_member_rank_v1"
    out["schema_version"] = ENSEMBLE_SCHEMA
    out = out.reset_index()
    out = out.sort_values(
        ["phase2_v2_3_rank_mean", "phase2_v2_3_combined_ranking_ai_prior", "candidate_id"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1, dtype=int))
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = build_ensemble(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    metadata = {
        "status": "PASS",
        "schema_version": ENSEMBLE_SCHEMA,
        "inputs": [str(path.resolve()) for path in args.input],
        "candidate_rows": len(out),
        "seed_count": int(out["phase2_v2_3_seed_count"].iloc[0]),
        "boundary": out["phase2_v2_3_boundary_note"].iloc[0],
        "output": str(args.output.resolve()),
    }
    metadata_path = args.metadata or args.output.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
