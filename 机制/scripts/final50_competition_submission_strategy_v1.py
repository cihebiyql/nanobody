#!/usr/bin/env python3
"""Build an auditable competition-priority sidecar without changing mechanism rank.

Inputs are frozen Final50 geometry evidence plus previously completed
manufacturability, glycan-anchor and independent-control calibration sidecars.
The script refuses to convert uncalibrated static energy or co-folding values
into a false affinity rank.  ``competition_submission_priority`` is a
portfolio decision for the ten experimental slots, not an experimental score.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def mechanism_rank(row: dict[str, str]) -> int:
    return int(row["final_rank"])


def tier_sort(tier: str) -> int:
    return {"D1_LOWER_RISK_PROXY": 0, "D2_REVIEW": 1, "D3_HIGH_REVIEW": 2}.get(tier, 9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final50", type=Path, required=True)
    parser.add_argument("--manufacturability", type=Path, required=True)
    parser.add_argument("--glycan", type=Path, required=True)
    parser.add_argument("--control-summary", type=Path, required=True)
    parser.add_argument("--control-ranges", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    candidates = read_tsv(args.final50)
    manufacture = {row["candidate_id"]: row for row in read_tsv(args.manufacturability)}
    glycan = {row["candidate_id"]: row for row in read_tsv(args.glycan)}
    controls = read_tsv(args.control_summary)
    ranges = json.loads(args.control_ranges.read_text(encoding="utf-8"))
    if len(candidates) != 50 or len({row["candidate_id"] for row in candidates}) != 50:
        raise ValueError("expected exactly 50 unique Final50 candidates")
    if len(manufacture) != 50 or len(glycan) != 50:
        raise ValueError("manufacturability and glycan sidecars must each cover Final50")
    if len(controls) != 9:
        raise ValueError("expected 5 experimental positives plus 4 computational perturbation controls")

    # Calibration result: 1/5 true positives and 1/4 perturbation controls have
    # dual-tool support. Thus independent co-folding does not qualify to rank
    # Final50 candidates; record this explicitly rather than expanding it.
    positive = [r for r in controls if r["control_class"] == "EXPERIMENTAL_POSITIVE_BLOCKER"]
    disruptive = [r for r in controls if r["control_class"] == "COMPUTATIONAL_DISRUPTIVE_CONTROL"]
    positive_dual = sum(r["independent_complex_support"] == "DUAL_TOOL_SUPPORTED_AB" for r in positive)
    disruptive_dual = sum(r["independent_complex_support"] == "DUAL_TOOL_SUPPORTED_AB" for r in disruptive)
    control_decision = "NO_EXPANSION_UNCALIBRATED_CONTROL_SEPARATION"
    if len(positive) != 5 or len(disruptive) != 4:
        raise ValueError("control class counts changed unexpectedly")
    if positive_dual != 1 or disruptive_dual != 1:
        raise ValueError("frozen control calibration counts changed; require explicit new review")

    affinity_rows: list[dict[str, Any]] = []
    nonspecific_rows: list[dict[str, Any]] = []
    unconstrained_rows: list[dict[str, Any]] = []
    for row in sorted(candidates, key=mechanism_rank):
        candidate_id = row["candidate_id"]
        m = manufacture[candidate_id]
        g = glycan[candidate_id]
        affinity_rows.append({
            "candidate_id": candidate_id,
            "mechanism_rank": row["final_rank"],
            "top10_rank_prior": row.get("top10_rank", ""),
            "static_pose_count": row.get("static_pose_count", ""),
            "prodigy_status": row.get("prodigy_status", ""),
            "foldx_status": row.get("foldx_status", ""),
            "rosetta_status": row.get("rosetta_status", ""),
            "static_median_rosetta_dSASA_int": row.get("static_median_rosetta_dSASA_int", ""),
            "static_median_rosetta_delta_unsatHbonds": row.get("static_median_rosetta_delta_unsatHbonds", ""),
            "static_median_rosetta_hbonds_int": row.get("static_median_rosetta_hbonds_int", ""),
            "static_median_rosetta_sc_value": row.get("static_median_rosetta_sc_value", ""),
            "static_median_rosetta_dG_separated": row.get("static_median_rosetta_dG_separated", ""),
            "static_median_prodigy_predicted_dg_kcal_mol": row.get("static_median_prodigy_predicted_dg_kcal_mol", ""),
            "affinity_consensus_status": "NOT_ASSIGNED_NO_CALIBRATED_CROSS_CANDIDATE_METHOD",
            "affinity_consensus_rank": "",
            "rank_use": "DESCRIPTIVE_ONLY",
            "reason": "Positive/control calibration rejected PRODIGY, FoldX and Rosetta for cross-candidate affinity ranking; raw values retained for visual review only.",
            "claim_boundary": "No computed value is experimental Kd, BLI response, binding, or blocking proof.",
        })
        nonspecific_rows.append({
            "candidate_id": candidate_id,
            "mechanism_rank": row["final_rank"],
            "manufacturability_proxy_tier": m["manufacturability_proxy_tier"],
            "tnp_L": m.get("tnp_L", ""), "tnp_L3": m.get("tnp_L3", ""), "tnp_C": m.get("tnp_C", ""),
            "tnp_PSH": m.get("tnp_PSH", ""), "tnp_PPC": m.get("tnp_PPC", ""), "tnp_PNC": m.get("tnp_PNC", ""),
            "median_largest_hydrophobic_patch_residues": m.get("median_largest_hydrophobic_patch_residues", ""),
            "median_largest_hydrophobic_patch_free_sasa_a2": m.get("median_largest_hydrophobic_patch_free_sasa_a2", ""),
            "median_largest_positive_patch_residues": m.get("median_largest_positive_patch_residues", ""),
            "median_largest_negative_patch_residues": m.get("median_largest_negative_patch_residues", ""),
            "pI": row.get("pI", ""), "net_charge_pH7": row.get("net_charge_pH7", ""), "GRAVY": row.get("GRAVY", ""),
            "hydrophobic_5_count": row.get("hydrophobic_5_count", ""),
            "polyreactivity_model_status": "NOT_MODELED_NO_CALIBRATED_MODEL",
            "self_association_model_status": "NOT_MODELED_NO_CALIBRATED_MODEL",
            "rank_use": "RISK_REVIEW_ONLY",
            "claim_boundary": "Patch and TNP features are risk proxies, not measured HIC, self-association, polyreactivity, yield, purity, or aggregation.",
        })
        unconstrained_rows.append({
            "record_type": "FINAL50_CANDIDATE",
            "candidate_id": candidate_id,
            "mechanism_rank": row["final_rank"],
            "experimental_role": "CANDIDATE",
            "independent_complex_status": "NOT_RUN_FINAL50",
            "final50_expansion_decision": control_decision,
            "reason": "Do not expand an unconstrained Chai/Boltz candidate panel when the matched positive/perturbation control panel has no qualifying separation.",
            "claim_boundary": "No candidate has unconstrained independent-complex support in this audit.",
        })
    for r in controls:
        unconstrained_rows.append({
            "record_type": "CALIBRATION_CONTROL",
            "candidate_id": r["candidate_id"],
            "mechanism_rank": "",
            "experimental_role": r["control_class"],
            "base_molecule": r["base_molecule"],
            "mutation": r["mutation"],
            "independent_complex_status": r["independent_complex_support"],
            "boltz_pair_label": r["boltz_pair_label"], "boltz_iptm": r["boltz_iptm"],
            "chai_pair_label": r["chai_best_pair_label"], "chai_best_iptm": r["chai_best_iptm"],
            "final50_expansion_decision": control_decision,
            "reason": "Five experimental positives and four computational perturbation controls; perturbations are not experimentally confirmed negatives.",
            "claim_boundary": "Control calibration only; not experimental affinity/blocking inference for candidates.",
        })

    by_rank = {int(row["final_rank"]): row for row in candidates}
    # Portfolio order: D1 cores first; mechanism-leading D2s next; retain two
    # PVRIG-38 CDR3-diverse backups; keep exactly one D3 high-risk sentry.
    requested_ranks = [2, 6, 7, 1, 3, 4, 5, 28, 35, 21]
    if any(rank not in by_rank for rank in requested_ranks):
        raise ValueError("one or more frozen portfolio candidates are missing")
    if manufacture[by_rank[21]["candidate_id"]]["manufacturability_proxy_tier"] != "D3_HIGH_REVIEW":
        raise ValueError("rank 21 must remain the sole high-risk sentry")
    if any(manufacture[by_rank[rank]["candidate_id"]]["manufacturability_proxy_tier"] == "D3_HIGH_REVIEW" for rank in requested_ranks[:-1]):
        raise ValueError("only one D3 is permitted in provisional Top10")
    selected_ids = [by_rank[rank]["candidate_id"] for rank in requested_ranks]
    priority_reason = {
        2: "D1 core; mechanism rank 2.", 6: "D1 core; independent HR-151-derived CDR3 cluster.",
        7: "D1 core; distinct HR-151-derived CDR3 cluster.", 1: "Mechanism-leading D2; held below D1 cores for manufacturing review.",
        3: "Mechanism-leading D2; HR-151-derived portfolio coverage.", 4: "Mechanism-leading D2; distinct CDR3 cluster.",
        5: "Mechanism-leading D2; secondary mechanism backup.",
        28: "D1 PVRIG-38 parent diversity anchor.", 35: "D1 PVRIG-38 second CDR3 cluster; parent/CDR3 diversity backup.",
        21: "Only D3 high-risk 151H8-format sentry; not a primary manufacturing bet.",
    }
    remainder = [row for row in candidates if row["candidate_id"] not in selected_ids]
    remainder.sort(key=lambda row: (tier_sort(manufacture[row["candidate_id"]]["manufacturability_proxy_tier"]), mechanism_rank(row)))
    ordered = [by_rank[rank] for rank in requested_ranks] + remainder
    priority_rows: list[dict[str, Any]] = []
    for position, row in enumerate(ordered, 1):
        candidate_id = row["candidate_id"]
        m = manufacture[candidate_id]
        g = glycan[candidate_id]
        selected = position <= 10
        priority_rows.append({
            "competition_submission_priority": position,
            "portfolio_status": "PROVISIONAL_TOP10" if selected else "FINAL50_RESERVE",
            "candidate_id": candidate_id,
            "mechanism_rank": row["final_rank"],
            "previous_top10_rank": row.get("top10_rank", ""),
            "parent_id": row.get("parent_id", ""),
            "cdr3_diversity_cluster": row.get("cdr3_diversity_cluster", ""),
            "manufacturability_proxy_tier": m["manufacturability_proxy_tier"],
            "prior_proxy_risk_reasons": m.get("prior_proxy_risk_reasons", ""),
            "tnp_PSH": m.get("tnp_PSH", ""), "tnp_PPC": m.get("tnp_PPC", ""), "tnp_PNC": m.get("tnp_PNC", ""),
            "glycan_accessibility_status": g["glycan_accessibility_status"],
            "membrane_orientation_status": g["membrane_orientation_status"],
            "affinity_consensus_rank": "",
            "affinity_consensus_status": "NOT_ASSIGNED_NO_CALIBRATED_CROSS_CANDIDATE_METHOD",
            "unconstrained_independent_complex_decision": control_decision,
            "selection_reason": priority_reason.get(int(row["final_rank"]), "Reserve ordered by D tier then frozen mechanism rank; no new mechanism score applied."),
            "required_pre_submission_check": "Re-run official validator/CDR novelty/hash on the exact exported sequence file; do not submit this table as experimental evidence.",
            "claim_boundary": "Portfolio priority optimizes experimental-slot risk allocation; it is not a predicted BLI, Yield, purity, Kd, IC50, or experimental blocker score.",
        })

    args.out.mkdir(parents=True, exist_ok=True)
    affinity_path = args.out / "PVRIG_Final50_Affinity多模型共识侧车.tsv"
    unconstrained_path = args.out / "PVRIG_Final50_无约束重对接与Decoy校准.tsv"
    nonspecific_path = args.out / "PVRIG_Final50_非特异性与自相互作用.tsv"
    priority_path = args.out / "PVRIG_Final50_比赛提交优先级.tsv"
    write_tsv(affinity_path, affinity_rows)
    write_tsv(unconstrained_path, unconstrained_rows)
    write_tsv(nonspecific_path, nonspecific_rows)
    write_tsv(priority_path, priority_rows)
    receipt = {
        "schema_version": "pvrig.final50.competition_submission_strategy.v1",
        "state": "COMPLETE_PROVISIONAL_PRIORITY",
        "final50_count": len(candidates), "top10_count": 10,
        "mechanism_rank_changed": False,
        "affinity_consensus_rank_assigned": False,
        "unconstrained_candidate_expansion": "NO_EXPANSION_UNCALIBRATED_CONTROL_SEPARATION",
        "independent_control_panel": {
            "experimental_positive_count": len(positive), "disruptive_control_count": len(disruptive),
            "positive_dual_tool_supported_ab": positive_dual, "disruptive_dual_tool_supported_ab": disruptive_dual,
            "control_ranges_sha256": sha256_file(args.control_ranges),
        },
        "top10_final_ranks": requested_ranks,
        "input_sha256": {path.name: sha256_file(path) for path in (args.final50, args.manufacturability, args.glycan, args.control_summary, args.control_ranges)},
        "output_sha256": {},
        "claim_boundary": "No computational sidecar is experimental BLI, expression, purity, Kd, IC50, selectivity, glycan occupancy, or blocking proof.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for path in (affinity_path, unconstrained_path, nonspecific_path, priority_path):
        receipt["output_sha256"][path.name] = sha256_file(path)
    receipt_path = args.out / "COMPETITION_SUBMISSION_STRATEGY_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
