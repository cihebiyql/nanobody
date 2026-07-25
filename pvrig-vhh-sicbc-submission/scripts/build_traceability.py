#!/usr/bin/env python3
"""Build one audit row per submitted candidate without copying bulk campaign data.

The script intentionally retains route-specific score semantics: the legacy
old-priority route has S0_R8/S0_R9/S0_Rdual values, while the C2 route has a
different label-free ensemble schema.  For every candidate, the table also
records directly observed 8X6B/9E6Y static-pose HADDOCK scores and their mean;
these must not be interpreted as experimental affinity or inhibition.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def index(path: Path, key: str = "candidate_id") -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows(path)}


def changed(label: str, before: str, after: str) -> str:
    return f"{label}:{before}>{after}" if before != after else f"{label}:unchanged"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-priority", type=Path, required=True)
    parser.add_argument("--c2-refined", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/submission/candidate_traceability.tsv",
    )
    args = parser.parse_args()

    final = rows(ROOT / "data/submission/final_top50_ranked.tsv")
    old = index(args.old_priority)
    c2 = index(args.c2_refined)
    parents = index(ROOT / "data/provenance/positive11_cdr_imgt.tsv", "record_id")
    static = defaultdict(list)
    for row in rows(ROOT / "data/qc/final_top50_static_pose_metrics.tsv"):
        static[row["candidate_id"]].append(row)

    result: list[dict[str, str]] = []
    for final_row in final:
        candidate_id = final_row["candidate_id"]
        parent_id = final_row["parent_id"]
        parent = parents[parent_id]
        poses = {row["conformation"].lower(): row for row in static[candidate_id]}
        r8 = poses.get("8x6b", {})
        r9 = poses.get("9e6y", {})
        if not r8 or not r9:
            raise RuntimeError(f"missing_dual_static_pose:{candidate_id}")
        route = final_row["route"]
        legacy = old.get(candidate_id, {})
        c2_row = c2.get(candidate_id, {})
        cdr_change = "; ".join(
            [
                changed("CDR1", parent["cdr1"], final_row["cdr1"]),
                changed("CDR2", parent["cdr2"], final_row["cdr2"]),
                changed("CDR3", parent["cdr3"], final_row["cdr3"]),
            ]
        )
        static_r8 = float(r8["haddock_score"])
        static_r9 = float(r9["haddock_score"])
        result.append(
            {
                "candidate_id": candidate_id,
                "final_rank": final_row["final_rank"],
                "sequence": final_row["sequence"],
                "sequence_sha256": final_row["sequence_sha256"],
                "parent_id": parent_id,
                "parent_cluster": final_row["parent_cluster"],
                "parent_cdr1": parent["cdr1"],
                "parent_cdr2": parent["cdr2"],
                "parent_cdr3": parent["cdr3"],
                "generation_method": "fixed_pose_proteinmpnn_cpu_sequence_only",
                "generation_seed": "42 (deterministic ProteinMPNN contract)",
                "generation_model_version": "fixed_pose_cpu500k_v4_20260722",
                "cdr_modifications": cdr_change,
                "screening_route": route,
                "legacy_S0_R8": legacy.get("S0_R8", ""),
                "legacy_S0_R9": legacy.get("S0_R9", ""),
                "legacy_S0_Rdual_exact_min": legacy.get("S0_Rdual_exact_min", ""),
                "c2_l1_utility": c2_row.get("l1_utility", ""),
                "c2_b_utility": c2_row.get("b_utility", ""),
                "c2_s0_utility": c2_row.get("s0_utility", ""),
                "c2_m2_utility": c2_row.get("m2_utility", ""),
                "c2_refined_utility": c2_row.get("c2_refined_utility", ""),
                "R8_static_haddock_score": f"{static_r8:.6f}",
                "R9_static_haddock_score": f"{static_r9:.6f}",
                "Rdual_static_mean_haddock_score": f"{(static_r8 + static_r9) / 2:.6f}",
                "Rdual_final_reference_agreement": final_row["dual_reference_agreement_fraction"],
                "qc_official_validator_pass": final_row["official_validator_pass"],
                "qc_anarci_status": final_row["ANARCI_status"],
                "qc_imgt_chain_type": final_row["imgt_chain_type"],
                "qc_positive_cdr_similarity_pass": final_row["pass_similarity_filter"],
                "qc_developability_hardpass": final_row["developability_hardpass"],
                "qc_hard_fail": final_row["hard_fail"],
                "monomer_structure": "NanoBodyBuilder2; status="
                + final_row["nbb2_status"]
                + "; sequence_match="
                + final_row["nbb2_pdb_sequence_match"],
                "docking_protocol_sha256": ";".join(
                    sorted({r8["source_protocol_sha256"], r9["source_protocol_sha256"]})
                ),
                "docking_seed_8X6B": r8["seed"],
                "docking_seed_9E6Y": r9["seed"],
                "pose_8X6B": r8["static_job_id"],
                "pose_9E6Y": r9["static_job_id"],
                "pose_8X6B_sha256": r8["frozen_pdb_sha256"],
                "pose_9E6Y_sha256": r9["frozen_pdb_sha256"],
                "manual_review_status": final_row["static_review_status"],
                "manual_review_evidence": "static_review; prodigy="
                + final_row["prodigy_status"]
                + "; foldx="
                + final_row["foldx_status"]
                + "; rosetta="
                + final_row["rosetta_status"],
                "final_selection_reason": final_row["final_selection_reason"],
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(result)
    print(f"wrote {len(result)} rows to {args.output}")


if __name__ == "__main__":
    main()
