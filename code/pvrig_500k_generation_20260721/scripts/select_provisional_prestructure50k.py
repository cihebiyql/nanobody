#!/usr/bin/env python3
"""Freeze a diverse reusable 50k structure pool before the final surrogate is ready."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


LANES = {
    "binding_consensus": 20_000,
    "developability": 10_000,
    "binding_disagreement": 7_500,
    "family_parent_diversity": 7_500,
    "stratified_random_control": 5_000,
}
PATCH_WEIGHTS = {"C_CROSS": 0.40, "B_LOWER": 0.35, "A_CENTER": 0.25}
MODE_WEIGHTS = {"H1H2H3": 0.45, "H1H3": 0.35, "H3": 0.20}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_random(candidate_id: str, seed: int) -> float:
    raw = hashlib.sha256(f"{seed}:{candidate_id}".encode()).digest()[:8]
    return int.from_bytes(raw, "big") / 2**64


def allocate_cells(total: int) -> dict[tuple[str, str], int]:
    raw = {
        (patch, mode): total * patch_weight * mode_weight
        for patch, patch_weight in PATCH_WEIGHTS.items()
        for mode, mode_weight in MODE_WEIGHTS.items()
    }
    out = {key: int(np.floor(value)) for key, value in raw.items()}
    remainder = total - sum(out.values())
    order = sorted(raw, key=lambda key: (raw[key] - out[key], key), reverse=True)
    for key in order[:remainder]:
        out[key] += 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefilter", type=Path, required=True)
    parser.add_argument("--families", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--family-cap", type=int, default=100)
    parser.add_argument("--parent-cap", type=int, default=750)
    parser.add_argument("--seed", type=int, default=20260722)
    args = parser.parse_args()

    prefilter = pd.read_csv(args.prefilter, sep="\t", low_memory=False)
    families = pd.read_csv(
        args.families,
        sep="\t",
        usecols=["candidate_id", "cdr3_family_id", "cdr3_family_candidate_size"],
    )
    if prefilter["candidate_id"].duplicated().any() or families["candidate_id"].duplicated().any():
        raise ValueError("candidate IDs must be unique")
    frame = prefilter.merge(families, on="candidate_id", how="inner", validate="one_to_one")
    if len(frame) != len(prefilter):
        raise ValueError("family ID set does not match prefilter")
    frame = frame[frame["anarci_qc_status"] == "PASS"].copy()

    frame["deepnano_rank"] = frame["deepnano_binding_prior"].rank(pct=True, method="average")
    frame["nanobind_rank"] = frame["nanobind_binding_prior"].rank(pct=True, method="average")
    frame["binding_consensus_score"] = (frame["deepnano_rank"] + frame["nanobind_rank"]) / 2
    frame["binding_disagreement_score"] = (
        frame["deepnano_rank"] - frame["nanobind_rank"]
    ).abs()
    frame["sapiens_rank"] = frame["mean_self_probability"].rank(pct=True, method="average")
    abnativ = pd.to_numeric(frame["AbNatiV VHH Score"], errors="coerce")
    frame["abnativ_rank"] = abnativ.rank(pct=True, method="average").fillna(0.25)
    frame["risk_benefit"] = frame["risk_tier"].map(
        {"LOW": 1.0, "MODERATE": 0.5, "HIGH": 0.0}
    ).fillna(0.0)
    frame["developability_score_v1"] = (
        0.35 * frame["sapiens_rank"]
        + 0.35 * frame["abnativ_rank"]
        + 0.30 * frame["risk_benefit"]
    )
    family_rarity = 1 / np.sqrt(frame["cdr3_family_candidate_size"].clip(lower=1))
    parent_size = frame.groupby("parent_cluster")["candidate_id"].transform("size")
    parent_rarity = 1 / np.sqrt(parent_size.clip(lower=1))
    frame["diversity_score_v1"] = (
        0.55 * family_rarity.rank(pct=True)
        + 0.30 * parent_rarity.rank(pct=True)
        + 0.15 * frame["candidate_id"].map(lambda value: stable_random(value, args.seed))
    )
    frame["random_control_score_v1"] = frame["candidate_id"].map(
        lambda value: stable_random(value, args.seed + 1)
    )

    lane_score = {
        "binding_consensus": "binding_consensus_score",
        "developability": "developability_score_v1",
        "binding_disagreement": "binding_disagreement_score",
        "family_parent_diversity": "diversity_score_v1",
        "stratified_random_control": "random_control_score_v1",
    }
    selected: list[int] = []
    selected_set: set[int] = set()
    selected_lane: dict[int, str] = {}
    family_counts: Counter[str] = Counter()
    parent_counts: Counter[str] = Counter()

    for lane, target in LANES.items():
        allocations = allocate_cells(target)
        for (patch, mode), count in sorted(allocations.items()):
            subset = frame[
                (frame["target_patch_assignment"] == patch)
                & (frame["design_mode"] == mode)
            ].sort_values(
                [lane_score[lane], "candidate_id"], ascending=[False, True]
            )
            taken = 0
            for index, row in subset.iterrows():
                if index in selected_set:
                    continue
                family = str(row["cdr3_family_id"])
                parent = str(row["parent_cluster"])
                if family_counts[family] >= args.family_cap or parent_counts[parent] >= args.parent_cap:
                    continue
                selected.append(index)
                selected_set.add(index)
                selected_lane[index] = lane
                family_counts[family] += 1
                parent_counts[parent] += 1
                taken += 1
                if taken == count:
                    break
            if taken != count:
                raise RuntimeError(
                    f"unable to fill lane={lane} patch={patch} mode={mode}: {taken}/{count}"
                )

    out = frame.loc[selected].copy()
    out["selection_lane"] = [selected_lane[index] for index in selected]
    out["selection_status"] = "PROVISIONAL_PRESTRUCTURE_REUSE_POOL"
    out["selection_seed"] = args.seed
    out["family_cap"] = args.family_cap
    out["parent_cap"] = args.parent_cap
    if len(out) != sum(LANES.values()) or out["candidate_id"].duplicated().any():
        raise RuntimeError("selection size or uniqueness invariant failed")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    table = args.output_dir / "provisional_prestructure50000.tsv.gz"
    fasta = args.output_dir / "provisional_prestructure50000.fasta"
    out.to_csv(table, sep="\t", index=False, compression="gzip")
    with fasta.open("w") as handle:
        for row in out[["candidate_id", "sequence"]].itertuples(index=False):
            handle.write(f">{row.candidate_id}\n{row.sequence}\n")

    summary = {
        "status": "PASS",
        "selection_status": "PROVISIONAL_PRESTRUCTURE_REUSE_POOL",
        "records": len(out),
        "lane_counts": out["selection_lane"].value_counts().sort_index().to_dict(),
        "patch_counts": out["target_patch_assignment"].value_counts().sort_index().to_dict(),
        "mode_counts": out["design_mode"].value_counts().sort_index().to_dict(),
        "route_counts": out["route_id"].value_counts().sort_index().to_dict(),
        "risk_counts": out["risk_tier"].value_counts().sort_index().to_dict(),
        "family_count": out["cdr3_family_id"].nunique(),
        "max_selected_per_family": max(family_counts.values(), default=0),
        "max_selected_per_parent": max(parent_counts.values(), default=0),
        "family_cap": args.family_cap,
        "parent_cap": args.parent_cap,
        "table_sha256": sha256(table),
        "fasta_sha256": sha256(fasta),
        "scientific_boundary": (
            "Reusable structure-compute pool selected before the final Docking surrogate; "
            "not a final blocker ranking and not binding, Kd, IC50, or purity evidence"
        ),
    }
    (args.output_dir / "READY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
