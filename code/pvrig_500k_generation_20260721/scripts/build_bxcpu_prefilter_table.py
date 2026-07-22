#!/usr/bin/env python3
"""Merge the 394k bxcpu prefilter outputs with frozen candidate provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_unique(frame: pd.DataFrame, key: str, source: str) -> None:
    if frame[key].isna().any():
        raise ValueError(f"{source}: missing {key}")
    duplicated = int(frame[key].duplicated().sum())
    if duplicated:
        raise ValueError(f"{source}: {duplicated} duplicate {key} values")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--risk", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--sapiens", type=Path, required=True)
    parser.add_argument("--abnativ", type=Path, required=True)
    parser.add_argument("--anarci", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    candidate_columns = [
        "candidate_id", "sequence", "sequence_sha256", "sequence_length",
        "route_id", "generation_seed", "target_patch_assignment", "design_mode",
        "parent_id", "parent_cluster", "cdr1_after", "cdr2_after", "cdr3_after",
        "designed_regions", "generator", "generator_version", "generation_batch",
        "max_positive_cdr_identity", "max_positive_cdr_identity_detail",
    ]
    risk_columns = [
        "candidate_id", "descriptor_status", "molecular_weight_da", "pI_proxy",
        "net_charge_pH7_4_proxy", "gravy", "cys_count", "nglyc_motif_count",
        "deamidation_risk_count", "isomerization_risk_count",
        "acid_cleavage_DP_count", "hydrophobic_5_count", "poly_basic_4_count",
        "poly_acidic_4_count", "polyreactivity_proxy",
        "expression_purity_risk_proxy_partial", "developability_risk_proxy_partial",
        "risk_tier", "model_coverage",
    ]
    binding_columns = [
        "candidate_id", "antigen_id", "deepnano_binding_prior",
        "nanobind_binding_prior", "nanobind_binary_prediction",
        "deepnano_inference_semantics",
    ]
    sapiens_columns = [
        "seq_id", "mean_self_probability", "num_suggested_mutations",
    ]
    abnativ_columns = [
        "seq_id", "AbNatiV VHH Score", "AbNatiV CDR1-VHH Score",
        "AbNatiV CDR2-VHH Score", "AbNatiV CDR3-VHH Score",
        "AbNatiV FR-VHH Score", "abnativ_status", "abnativ_failure_reason",
    ]
    anarci_columns = [
        "candidate_id", "anarci_qc_status", "anarci_qc_reasons", "anarci_species",
        "anarci_score", "numbered_sequence_matches_input_slice", "fr1", "cdr1",
        "fr2", "cdr2", "fr3", "cdr3", "fr4", "imgt_cys23", "imgt_cys104",
    ]

    frames = {
        "candidates": pd.read_csv(
            args.candidates, sep="\t", usecols=candidate_columns, low_memory=False
        ),
        "risk": pd.read_csv(args.risk, sep="\t", usecols=risk_columns, low_memory=False),
        "binding": pd.read_csv(
            args.binding, sep="\t", usecols=binding_columns, low_memory=False
        ),
        "sapiens": pd.read_csv(
            args.sapiens, sep="\t", usecols=sapiens_columns, low_memory=False
        ).rename(
            columns={"seq_id": "candidate_id"}
        ),
        "abnativ": pd.read_csv(
            args.abnativ,
            sep="\t",
            usecols=abnativ_columns,
            low_memory=False,
            keep_default_na=False,
        ).rename(
            columns={"seq_id": "candidate_id"}
        ),
    }
    if args.anarci:
        frames["anarci"] = pd.read_csv(
            args.anarci,
            sep="\t",
            usecols=anarci_columns,
            low_memory=False,
            keep_default_na=False,
        ).rename(
            columns={
                "fr1": "anarci_fr1", "cdr1": "anarci_cdr1", "fr2": "anarci_fr2",
                "cdr2": "anarci_cdr2", "fr3": "anarci_fr3", "cdr3": "anarci_cdr3",
                "fr4": "anarci_fr4",
            }
        )
    for name, frame in frames.items():
        require_unique(frame, "candidate_id", name)

    expected_ids = set(frames["candidates"]["candidate_id"])
    id_checks = {}
    for name, frame in frames.items():
        ids = set(frame["candidate_id"])
        id_checks[name] = {
            "records": len(frame),
            "missing_vs_candidates": len(expected_ids - ids),
            "extra_vs_candidates": len(ids - expected_ids),
        }
        if ids != expected_ids:
            raise ValueError(f"{name}: candidate ID set does not match frozen candidates")

    merged = frames["candidates"]
    merge_order = ["risk", "binding", "sapiens", "abnativ"]
    if "anarci" in frames:
        merge_order.append("anarci")
    for name in merge_order:
        merged = merged.merge(frames[name], on="candidate_id", how="left", validate="one_to_one")
    merged["binding_model_raw_disagreement"] = (
        merged["deepnano_binding_prior"] - merged["nanobind_binding_prior"]
    ).abs()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, sep="\t", index=False, compression="gzip")

    summary = {
        "status": "PASS",
        "records": len(merged),
        "id_checks": id_checks,
        "abnativ_status_counts": {
            str(key): int(value)
            for key, value in merged["abnativ_status"].value_counts(dropna=False).items()
        },
        "risk_tier_counts": {
            str(key): int(value)
            for key, value in merged["risk_tier"].value_counts(dropna=False).items()
        },
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "scientific_boundaries": {
            "binding": "weak binding priors; not Kd, IC50, or blocking evidence",
            "sapiens": "human-likeness proxy; not measured purity or expression",
            "abnativ": "VHH nativeness proxy; NA denotes model incompatibility, not negative biology",
            "sequence_risk": "partial sequence-only developability proxy; not measured purity or expression",
        },
    }
    if "anarci_qc_status" in merged:
        summary["anarci_qc_status_counts"] = {
            str(key): int(value)
            for key, value in merged["anarci_qc_status"].value_counts(dropna=False).items()
        }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
