#!/usr/bin/env python3
"""Close the QC397 Top20-plus-current-Top10 fusion/developability sidecar.

This audit proves membership, frozen-pose completeness, hashes, categorical
risk policy, and claim boundaries. It intentionally does not infer full
VHH-hFc compatibility because the organizer's exact fusion construct has not
been disclosed.
"""
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
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--structure-dir", type=Path, required=True)
    parser.add_argument("--prefusion-dir", type=Path, required=True)
    parser.add_argument("--abc-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    final50 = sorted(read_tsv(args.bridge_final50), key=lambda row: int(row["final_rank"]))
    original_top10 = read_tsv(args.bridge_top10)
    panel_path = args.bundle_dir / "fusion_panel_candidates.tsv"
    manifest_path = args.bundle_dir / "representative_models_manifest.tsv"
    bundle_receipt_path = args.bundle_dir / "BUNDLE_RECEIPT.json"
    structure_candidate_path = (
        args.structure_dir / "candidate_structure_manufacturability_sidecar.tsv"
    )
    structure_pose_path = args.structure_dir / "pose_surface_metrics.tsv"
    structure_ptm_path = args.structure_dir / "ptm_exposure_metrics.tsv"
    structure_receipt_path = args.structure_dir / "STRUCTURE_SIDECAR_RECEIPT.json"
    prefusion_candidate_path = args.prefusion_dir / "Top20_prefusion_candidate_audit.tsv"
    prefusion_pose_path = args.prefusion_dir / "Top20_prefusion_pose_audit.tsv"
    prefusion_receipt_path = args.prefusion_dir / "PREFUSION_RECEIPT.json"
    grades_path = args.abc_dir / "Top20_expression_purity_risk_grades.tsv"
    priority_path = (
        args.abc_dir / "Top10_competition_priority_after_fusion_developability.tsv"
    )
    abc_receipt_path = args.abc_dir / "ABC_PRIORITY_RECEIPT.json"

    panel = read_tsv(panel_path)
    manifest = read_tsv(manifest_path)
    structure_candidates = read_tsv(structure_candidate_path)
    structure_poses = read_tsv(structure_pose_path)
    structure_ptm = read_tsv(structure_ptm_path)
    prefusion_candidates = read_tsv(prefusion_candidate_path)
    prefusion_poses = read_tsv(prefusion_pose_path)
    grades = read_tsv(grades_path)
    priority = read_tsv(priority_path)
    bundle_receipt = read_json(bundle_receipt_path)
    structure_receipt = read_json(structure_receipt_path)
    prefusion_receipt = read_json(prefusion_receipt_path)
    abc_receipt = read_json(abc_receipt_path)

    final50_ids = {row["candidate_id"] for row in final50}
    original_top10_ids = {row["candidate_id"] for row in original_top10}
    expected_panel_ids = {
        row["candidate_id"] for row in final50[:20]
    } | original_top10_ids
    panel_ids = {row["candidate_id"] for row in panel}
    require(len(final50) == 50, "bridge Final50 is not 50 rows")
    require(len(original_top10) == 10, "bridge Top10 is not 10 rows")
    require(original_top10_ids <= final50_ids, "bridge Top10 is not a Final50 subset")
    require(len(panel) == 22, "fusion panel is not 22 rows")
    require(panel_ids == expected_panel_ids, "fusion panel membership mismatch")
    require(
        Counter(row["fusion_panel_membership"] for row in panel)
        == Counter({"FINAL_RANK_TOP20": 20, "CURRENT_TOP10_DIVERSITY_ADDON": 2}),
        "fusion panel membership labels mismatch",
    )
    require(
        {row["candidate_id"] for row in panel if row.get("top10_rank")}
        == original_top10_ids,
        "current Top10 is not fully marked in the fusion panel",
    )

    by_candidate: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in manifest:
        require(row["state"] == "SUCCESS", f"non-success manifest row: {row}")
        require(Path(row["pdb_path"]).is_file(), f"missing PDB: {row['pdb_path']}")
        require(
            sha256(Path(row["pdb_path"])) == row["pdb_sha256"],
            f"PDB hash mismatch: {row['pdb_path']}",
        )
        require(
            {"A", "T"} <= set(row["chain_set"]),
            f"required chains absent: {row['pdb_path']}",
        )
        by_candidate[row["candidate_id"]].add((row["seed"], row["conformation"]))
    require(len(manifest) == 176, "manifest is not 176 frozen poses")
    require(set(by_candidate) == panel_ids, "manifest candidate membership mismatch")
    require(
        all(
            combinations
            == {(seed, conformation) for seed in SEEDS for conformation in CONFORMATIONS}
            for combinations in by_candidate.values()
        ),
        "one or more candidates lack the exact 4-seed × 2-conformation matrix",
    )

    require(
        bundle_receipt["state"] == "COMPLETE"
        and bundle_receipt["candidates"] == 22
        and bundle_receipt["poses"] == 176
        and bundle_receipt["current_top10_covered"] == 10,
        "bundle receipt mismatch",
    )
    require(
        bundle_receipt["manifest_sha256"] == sha256(manifest_path)
        and bundle_receipt["panel_sha256"] == sha256(panel_path),
        "bundle output hash mismatch",
    )
    require(
        bundle_receipt["input_sha256"][str(args.bridge_final50)]
        == sha256(args.bridge_final50)
        and bundle_receipt["input_sha256"][str(args.bridge_top10)]
        == sha256(args.bridge_top10),
        "bundle input hash mismatch",
    )

    require(
        len(structure_candidates) == 22
        and len(structure_poses) == 176
        and len(structure_ptm) == 2464,
        "structure sidecar counts mismatch",
    )
    require(
        {row["candidate_id"] for row in structure_candidates} == panel_ids,
        "structure candidate membership mismatch",
    )
    require(
        structure_receipt["state"] == "COMPLETE"
        and structure_receipt["candidates"] == 22
        and structure_receipt["pose_models"] == 176
        and structure_receipt["ptm_rows"] == 2464,
        "structure receipt mismatch",
    )

    require(
        len(prefusion_candidates) == 22 and len(prefusion_poses) == 176,
        "prefusion sidecar counts mismatch",
    )
    require(
        {row["candidate_id"] for row in prefusion_candidates} == panel_ids,
        "prefusion candidate membership mismatch",
    )
    require(
        prefusion_receipt["state"] == "COMPLETE_WITH_FULL_CONSTRUCT_DEFERRED"
        and prefusion_receipt["full_construct_available"] is False,
        "prefusion full-construct boundary violated",
    )
    require(
        all(row["rank_use"] == "HARD_FAIL_PLUS_TIE_BREAKER_ONLY" for row in prefusion_candidates),
        "prefusion sidecar is not restricted to hard fail plus tie-breaker",
    )
    require(
        all(
            row["fc_target_collision_status"].startswith("DEFERRED_")
            and row["vhh_vhh_collision_status"].startswith("DEFERRED_")
            and row["bivalent_binding_geometry_status"].startswith("DEFERRED_")
            for row in prefusion_candidates
        ),
        "an unavailable full-format check was marked complete",
    )
    require(
        prefusion_receipt["output_sha256"]["Top20_prefusion_pose_audit.tsv"]
        == sha256(prefusion_pose_path)
        and prefusion_receipt["output_sha256"]["Top20_prefusion_candidate_audit.tsv"]
        == sha256(prefusion_candidate_path),
        "prefusion output hash mismatch",
    )

    require(len(grades) == 22 and len(priority) == 10, "A/B/C output counts mismatch")
    require({row["candidate_id"] for row in grades} == panel_ids, "A/B/C membership mismatch")
    require(
        all(row["mechanism_rank_immutable"] == row["final_rank"] for row in grades),
        "mechanism rank changed in the risk sidecar",
    )
    require(
        all(
            row["rank_use"]
            == "C_HARD_EXCLUDE; A_OVER_B_TIE_BREAK; DO_NOT_CHANGE_MECHANISM_RANK"
            for row in grades
        ),
        "A/B/C rank-use policy mismatch",
    )
    priority_grades = Counter(row["developability_grade"] for row in priority)
    require(priority_grades["A_LOWER_RISK"] >= 8, "Top10 does not contain at least 8 A")
    require(priority_grades["B_REVIEW"] <= 2, "Top10 contains more than 2 B")
    require(priority_grades["C_HIGH_RISK"] == 0, "Top10 contains a C")
    require(
        abc_receipt["state"] == "COMPLETE"
        and abc_receipt["mechanism_rank_changed"] is False
        and abc_receipt["full_hfc_construct_available"] is False,
        "A/B/C receipt boundary mismatch",
    )
    require(
        abc_receipt["output_sha256"]["Top20_expression_purity_risk_grades.tsv"]
        == sha256(grades_path)
        and abc_receipt["output_sha256"][
            "Top10_competition_priority_after_fusion_developability.tsv"
        ]
        == sha256(priority_path),
        "A/B/C output hash mismatch",
    )

    expected_final50_hash = "9ceb5734741a655e9c94c0b77aba293b054473718c9bd04787dfc6fa27590218"
    expected_legacy_hash = "d1026f93b547013366ff803ee0fe7f1864df1cd02d758a24d72c988edcb37008"
    require(
        sha256(args.bridge_final50) == expected_final50_hash,
        "bridge Final50 changed after sidecar execution",
    )
    require(
        sha256(args.legacy_final50) == expected_legacy_hash,
        "legacy frozen Final50 changed after sidecar execution",
    )

    grade_counts = Counter(row["developability_grade"] for row in grades)
    fusion_grade_counts = Counter(
        row["prefusion_compatibility_grade"] for row in prefusion_candidates
    )
    output_hashes = {
        path.name: sha256(path)
        for path in (
            panel_path,
            manifest_path,
            structure_candidate_path,
            structure_pose_path,
            structure_ptm_path,
            prefusion_candidate_path,
            prefusion_pose_path,
            grades_path,
            priority_path,
        )
    }
    receipt = {
        "schema_version": "pvrig.qc397.top20_plus_top10.fusion_developability.audit.v2",
        "state": "AUDIT_COMPLETE",
        "fusion_panel": {
            "candidates": 22,
            "primary_final_rank_top20": 20,
            "current_top10_covered": 10,
            "diversity_addons": 2,
            "frozen_poses": 176,
            "seeds": sorted(int(seed) for seed in SEEDS),
            "conformations": sorted(CONFORMATIONS),
        },
        "prefusion": {
            "grade_counts": dict(fusion_grade_counts),
            "hard_fail_count": sum(
                row["fusion_hard_fail"].lower() == "true"
                for row in prefusion_candidates
            ),
            "full_construct_available": False,
            "role": "HARD_FAIL_PLUS_TIE_BREAKER_ONLY",
            "deferred_checks": prefusion_receipt["deferred_checks"],
        },
        "developability": {
            "grade_counts": dict(grade_counts),
            "top10_grade_counts": dict(priority_grades),
            "top10_candidate_ids": [row["candidate_id"] for row in priority],
            "continuous_expression_or_purity_score_created": False,
            "mechanism_rank_changed": False,
        },
        "frozen_inputs": {
            "bridge_final50_sha256": sha256(args.bridge_final50),
            "legacy_final50_sha256": sha256(args.legacy_final50),
            "bridge_top10_sha256": sha256(args.bridge_top10),
        },
        "output_sha256": output_hashes,
        "claim_boundary": (
            "Computational hard-fail/tie-breaker and A/B/C risk sidecars only. "
            "No full VHH-hFc model was claimed because the exact organizer "
            "linker/hinge/Fc/dimer construct is not disclosed; no experimental "
            "yield, purity, SEC, Tm, BLI, Kd, IC50, avidity, or blocking claim."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
