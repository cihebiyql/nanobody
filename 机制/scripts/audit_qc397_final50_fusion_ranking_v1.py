#!/usr/bin/env python3
"""Audit the expanded QC397 Final50 fusion/developability ranking."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SEEDS = {"42", "917", "1931", "3047"}
CONFORMATIONS = {"8x6b", "9e6y"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-final50", type=Path, required=True)
    parser.add_argument("--bridge-top10", type=Path, required=True)
    parser.add_argument("--legacy-final50", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    bundle = args.root / "final50_common4_bundle"
    structure = args.root / "final50_structure_sidecar"
    prefusion = args.root / "final50_prefusion"
    abc = args.root / "final50_abc_priority"
    ranking = args.root / "final50_competition_ranking"
    panel_path = bundle / "final50_candidates.tsv"
    manifest_path = bundle / "representative_models_manifest.tsv"
    structure_candidates_path = (
        structure / "candidate_structure_manufacturability_sidecar.tsv"
    )
    structure_poses_path = structure / "pose_surface_metrics.tsv"
    structure_ptm_path = structure / "ptm_exposure_metrics.tsv"
    prefusion_candidates_path = prefusion / "Top20_prefusion_candidate_audit.tsv"
    prefusion_poses_path = prefusion / "Top20_prefusion_pose_audit.tsv"
    grades_path = abc / "Top20_expression_purity_risk_grades.tsv"
    selected_top10_path = (
        abc / "Top10_competition_priority_after_fusion_developability.tsv"
    )
    ranked_path = ranking / "Final50_competition_ranked.tsv"
    fasta_path = ranking / "Final50_competition_ranked.fasta"

    bridge_final50 = sorted(
        read_tsv(args.bridge_final50), key=lambda row: int(row["final_rank"])
    )
    bridge_top10 = read_tsv(args.bridge_top10)
    panel = read_tsv(panel_path)
    manifest = read_tsv(manifest_path)
    structure_candidates = read_tsv(structure_candidates_path)
    structure_poses = read_tsv(structure_poses_path)
    structure_ptm = read_tsv(structure_ptm_path)
    prefusion_candidates = read_tsv(prefusion_candidates_path)
    prefusion_poses = read_tsv(prefusion_poses_path)
    grades = read_tsv(grades_path)
    selected_top10 = read_tsv(selected_top10_path)
    ranked = read_tsv(ranked_path)

    ids = {row["candidate_id"] for row in bridge_final50}
    top10_ids = {row["candidate_id"] for row in bridge_top10}
    require(len(bridge_final50) == 50 and len(ids) == 50, "invalid bridge Final50")
    require(len(bridge_top10) == 10 and top10_ids <= ids, "invalid bridge Top10")
    require(
        len(panel) == 50 and {row["candidate_id"] for row in panel} == ids,
        "Final50 panel mismatch",
    )
    require(
        Counter(row["fusion_panel_membership"] for row in panel)
        == Counter({"FINAL_RANK_TOP20": 20, "FINAL50_EXPANSION": 30}),
        "Final50 membership labels mismatch",
    )
    require(
        {row["candidate_id"] for row in panel if row.get("top10_rank")} == top10_ids,
        "current Top10 not fully marked",
    )

    expected_combinations = {
        (seed, conformation)
        for seed in SEEDS
        for conformation in CONFORMATIONS
    }
    combinations: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in manifest:
        path = Path(row["pdb_path"])
        require(row["state"] == "SUCCESS" and path.is_file(), f"bad PDB row: {row}")
        require(sha256(path) == row["pdb_sha256"], f"PDB hash mismatch: {path}")
        require({"A", "T"} <= set(row["chain_set"]), f"missing chains: {path}")
        combinations[row["candidate_id"]].add((row["seed"], row["conformation"]))
    require(len(manifest) == 400 and set(combinations) == ids, "manifest mismatch")
    require(
        all(value == expected_combinations for value in combinations.values()),
        "one or more candidates lack 4-seed × 2-conformation poses",
    )

    bundle_receipt = read_json(bundle / "BUNDLE_RECEIPT.json")
    require(
        bundle_receipt["state"] == "COMPLETE"
        and bundle_receipt["candidates"] == 50
        and bundle_receipt["poses"] == 400
        and bundle_receipt["manifest_sha256"] == sha256(manifest_path)
        and bundle_receipt["panel_sha256"] == sha256(panel_path),
        "bundle receipt mismatch",
    )

    structure_receipt = read_json(structure / "STRUCTURE_SIDECAR_RECEIPT.json")
    require(
        len(structure_candidates) == 50
        and len(structure_poses) == 400
        and len(structure_ptm) == structure_receipt["ptm_rows"]
        and structure_receipt["state"] == "COMPLETE"
        and structure_receipt["candidates"] == 50
        and structure_receipt["pose_models"] == 400,
        "structure sidecar mismatch",
    )
    require(
        {row["candidate_id"] for row in structure_candidates} == ids,
        "structure candidate membership mismatch",
    )

    prefusion_receipt = read_json(prefusion / "PREFUSION_RECEIPT.json")
    require(
        len(prefusion_candidates) == 50
        and len(prefusion_poses) == 400
        and prefusion_receipt["candidates"] == 50
        and prefusion_receipt["poses"] == 400
        and prefusion_receipt["full_construct_available"] is False,
        "prefusion sidecar mismatch",
    )
    require(
        all(
            row["rank_use"] == "HARD_FAIL_PLUS_TIE_BREAKER_ONLY"
            and row["fc_target_collision_status"].startswith("DEFERRED_")
            and row["bivalent_binding_geometry_status"].startswith("DEFERRED_")
            for row in prefusion_candidates
        ),
        "prefusion boundary violation",
    )

    grade_by_id = {row["candidate_id"]: row for row in grades}
    require(len(grades) == 50 and set(grade_by_id) == ids, "grade membership mismatch")
    require(
        all(row["mechanism_rank_immutable"] == row["final_rank"] for row in grades),
        "mechanism rank changed in grade sidecar",
    )
    abc_receipt = read_json(abc / "ABC_PRIORITY_RECEIPT.json")
    require(
        abc_receipt["state"] == "COMPLETE"
        and abc_receipt["fusion_panel_count"] == 50
        and abc_receipt["mechanism_rank_changed"] is False,
        "A/B/C receipt mismatch",
    )
    top10_grades = Counter(row["developability_grade"] for row in selected_top10)
    require(
        len(selected_top10) == 10
        and top10_grades["A_LOWER_RISK"] >= 8
        and top10_grades["B_REVIEW"] <= 2
        and top10_grades["C_HIGH_RISK"] == 0,
        "selected Top10 policy mismatch",
    )

    rank_values = [int(row["competition_rank_1_50"]) for row in ranked]
    require(len(ranked) == 50 and rank_values == list(range(1, 51)), "ranking gap")
    require({row["candidate_id"] for row in ranked} == ids, "ranking membership mismatch")
    final_rank_by_id = {
        row["candidate_id"]: int(row["final_rank"]) for row in bridge_final50
    }
    require(
        all(
            int(row["mechanism_rank_immutable"])
            == final_rank_by_id[row["candidate_id"]]
            for row in ranked
        ),
        "ranked table changed mechanism ranks",
    )
    c_rows = [row for row in ranked if row["developability_grade"] == "C_HIGH_RISK"]
    require(
        not c_rows
        or [int(row["competition_rank_1_50"]) for row in c_rows]
        == list(range(51 - len(c_rows), 51)),
        "C-risk records are not a contiguous tail",
    )
    require(
        all(row["developability_grade"] != "C_HIGH_RISK" for row in ranked[:10]),
        "C-risk record entered Top10",
    )
    fasta_records = [
        line.strip()
        for line in fasta_path.read_text(encoding="utf-8").splitlines()
        if line.startswith(">")
    ]
    require(len(fasta_records) == 50, "FASTA does not contain 50 records")
    ranking_receipt = read_json(ranking / "RANKING_RECEIPT.json")
    require(
        ranking_receipt["state"] == "COMPLETE"
        and ranking_receipt["candidates"] == 50
        and ranking_receipt["exact_sequence_count"] == 50
        and ranking_receipt["mechanism_rank_changed"] is False
        and ranking_receipt["output_sha256"]["Final50_competition_ranked.tsv"]
        == sha256(ranked_path)
        and ranking_receipt["output_sha256"]["Final50_competition_ranked.fasta"]
        == sha256(fasta_path),
        "ranking receipt mismatch",
    )

    expected_bridge_hash = "9ceb5734741a655e9c94c0b77aba293b054473718c9bd04787dfc6fa27590218"
    expected_legacy_hash = "d1026f93b547013366ff803ee0fe7f1864df1cd02d758a24d72c988edcb37008"
    require(sha256(args.bridge_final50) == expected_bridge_hash, "bridge Final50 changed")
    require(sha256(args.legacy_final50) == expected_legacy_hash, "legacy Final50 changed")

    c_details = [
        {
            "competition_rank": int(row["competition_rank_1_50"]),
            "mechanism_rank": int(row["mechanism_rank_immutable"]),
            "candidate_id": row["candidate_id"],
            "hard_fail_reasons": row["hard_fail_reasons"],
        }
        for row in c_rows
    ]
    output_paths = [
        panel_path,
        manifest_path,
        structure_candidates_path,
        structure_poses_path,
        structure_ptm_path,
        prefusion_candidates_path,
        prefusion_poses_path,
        grades_path,
        selected_top10_path,
        ranked_path,
        fasta_path,
    ]
    receipt = {
        "schema_version": "pvrig.qc397.final50.fusion_ranking.audit.v1",
        "state": "AUDIT_COMPLETE",
        "candidates": 50,
        "frozen_poses": 400,
        "seeds": sorted(int(seed) for seed in SEEDS),
        "conformations": sorted(CONFORMATIONS),
        "structure_ptm_rows": len(structure_ptm),
        "prefusion_grade_counts": dict(
            Counter(
                row["prefusion_compatibility_grade"]
                for row in prefusion_candidates
            )
        ),
        "fusion_hard_fail_count": sum(
            row["fusion_hard_fail"].lower() == "true"
            for row in prefusion_candidates
        ),
        "developability_grade_counts": dict(
            Counter(row["developability_grade"] for row in grades)
        ),
        "top10_grade_counts": dict(top10_grades),
        "c_hard_risk_tail": c_details,
        "mechanism_rank_changed": False,
        "full_hfc_construct_available": False,
        "frozen_inputs": {
            "bridge_final50_sha256": sha256(args.bridge_final50),
            "bridge_top10_sha256": sha256(args.bridge_top10),
            "legacy_final50_sha256": sha256(args.legacy_final50),
        },
        "output_sha256": {path.name: sha256(path) for path in output_paths},
        "claim_boundary": (
            "Expanded computational fusion hard-fail/tie-breaker and A/B/C risk "
            "ranking only. Exact full VHH-hFc geometry and experimental Yield, "
            "purity, SEC, Tm, BLI, Kd, IC50 and blocking remain unproven."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
