#!/usr/bin/env python3
"""Freeze preliminary pose evidence and build ProteinMPNN-ranked RF2 pre-shortlists."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def build(
    pose_json: Path,
    raw_candidates_tsv: Path,
    final_candidates_tsv: Path,
    mpnn_scores_all_tsv: Path,
    output_dir: Path,
    *,
    per_backbone: int,
) -> dict[str, object]:
    pose = json.loads(pose_json.read_text(encoding="utf-8"))
    pose_rows = pose.get("rows", [])
    if len(pose_rows) != 200:
        raise ValueError(f"expected 200 backbone pose rows, found {len(pose_rows)}")
    pose_keys = [(str(row["set"]), int(row["backbone_index"])) for row in pose_rows]
    if len(set(pose_keys)) != len(pose_keys):
        raise ValueError("duplicate set/backbone key in pose audit")

    raw_rows = read_tsv(raw_candidates_tsv)
    final_rows = read_tsv(final_candidates_tsv)
    score_rows = read_tsv(mpnn_scores_all_tsv)
    final_ids = {row["candidate_id"] for row in final_rows}
    if len(final_ids) != len(final_rows):
        raise ValueError("duplicate candidate ID in final TSV")

    score_by_key: dict[tuple[str, int, int], float] = {}
    for row in score_rows:
        key = (row["hotspot_set"], int(row["backbone_index"]), int(row["mpnn_index"]))
        if key in score_by_key:
            raise ValueError(f"duplicate ProteinMPNN score key: {key}")
        score_by_key[key] = float(row["mpnn_nll_score"])

    candidates_by_backbone: defaultdict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in raw_rows:
        key = (row["hotspot_set"], int(row["backbone_index"]), int(row["mpnn_index"]))
        if key not in score_by_key:
            raise ValueError(f"raw candidate missing ProteinMPNN score: {row['candidate_id']}")
        candidates_by_backbone[key[:2]].append(
            {
                **row,
                "backbone_index": int(row["backbone_index"]),
                "mpnn_index": int(row["mpnn_index"]),
                "mpnn_nll_score": score_by_key[key],
                "in_final_1000": row["candidate_id"] in final_ids,
            }
        )

    audit_fields = [
        "hotspot_set",
        "backbone_index",
        "rfd_mindist",
        "rfd_averagemin",
        "hotspot_overlap_count",
        "total_vhh_pvrl2_residue_pair_occlusion",
        "cdr3_pvrl2_residue_pair_occlusion",
        "cdr3_occlusion_fraction",
        "passes_all_four_default_A_metrics",
        "passes_three_occlusion_metrics",
    ]
    normalized_pose_rows: list[dict[str, object]] = []
    primary: list[dict[str, object]] = []
    rescue: list[dict[str, object]] = []
    missing_backbones: list[dict[str, object]] = []
    used_sequences: set[str] = set()

    for pose_row in sorted(pose_rows, key=lambda row: (str(row["set"]), int(row["backbone_index"]))):
        normalized = {"hotspot_set": pose_row["set"], **{k: v for k, v in pose_row.items() if k != "set"}}
        normalized_pose_rows.append(normalized)
        if not pose_row.get("passes_three_occlusion_metrics"):
            continue
        backbone_key = (str(pose_row["set"]), int(pose_row["backbone_index"]))
        ranked = sorted(
            candidates_by_backbone.get(backbone_key, []),
            key=lambda row: (float(row["mpnn_nll_score"]), int(row["mpnn_index"])),
        )
        selected_ranked = [row for row in ranked if row["in_final_1000"]]
        target = primary if selected_ranked else rescue
        pool = selected_ranked if selected_ranked else ranked
        if not selected_ranked:
            missing_backbones.append(
                {
                    "hotspot_set": backbone_key[0],
                    "backbone_index": backbone_key[1],
                    "reason": "POSE_PASS_BACKBONE_NOT_REPRESENTED_IN_FINAL_1000",
                    "raw_candidate_count": len(ranked),
                }
            )
        picked = 0
        for candidate in pool:
            sequence = str(candidate["sequence"])
            if sequence in used_sequences:
                continue
            used_sequences.add(sequence)
            picked += 1
            target.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "hotspot_set": candidate["hotspot_set"],
                    "backbone_index": candidate["backbone_index"],
                    "mpnn_index": candidate["mpnn_index"],
                    "sequence": sequence,
                    "cdr1": candidate.get("cdr1", ""),
                    "cdr2": candidate.get("cdr2", ""),
                    "cdr3": candidate.get("cdr3", ""),
                    "mpnn_nll_score": candidate["mpnn_nll_score"],
                    "selection_rank_within_backbone": picked,
                    "in_final_1000": candidate["in_final_1000"],
                    "rfd_mindist": pose_row["rfd_mindist"],
                    "rfd_averagemin": pose_row["rfd_averagemin"],
                    "hotspot_overlap_count": pose_row["hotspot_overlap_count"],
                    "total_vhh_pvrl2_residue_pair_occlusion": pose_row[
                        "total_vhh_pvrl2_residue_pair_occlusion"
                    ],
                    "cdr3_pvrl2_residue_pair_occlusion": pose_row[
                        "cdr3_pvrl2_residue_pair_occlusion"
                    ],
                    "cdr3_occlusion_fraction": pose_row["cdr3_occlusion_fraction"],
                    "mpnn_pdb": candidate.get("mpnn_pdb", ""),
                    "selection_status": (
                        "PRIMARY_FINAL1000_NEEDS_SEQUENCE_QC_AND_RF2"
                        if selected_ranked
                        else "RESCUE_RAW_NOT_IN_FINAL1000_NEEDS_SEQUENCE_QC"
                    ),
                }
            )
            if picked == per_backbone:
                break

    shortlist_fields = [
        "candidate_id",
        "hotspot_set",
        "backbone_index",
        "mpnn_index",
        "sequence",
        "cdr1",
        "cdr2",
        "cdr3",
        "mpnn_nll_score",
        "selection_rank_within_backbone",
        "in_final_1000",
        "rfd_mindist",
        "rfd_averagemin",
        "hotspot_overlap_count",
        "total_vhh_pvrl2_residue_pair_occlusion",
        "cdr3_pvrl2_residue_pair_occlusion",
        "cdr3_occlusion_fraction",
        "mpnn_pdb",
        "selection_status",
    ]
    write_tsv(output_dir / "backbone_pose_audit_8x6b_preliminary.tsv", normalized_pose_rows, audit_fields)
    write_tsv(output_dir / "rf2_pre_shortlist_primary.tsv", primary, shortlist_fields)
    write_tsv(output_dir / "rf2_rescue_candidates_needing_qc.tsv", rescue, shortlist_fields)
    write_tsv(
        output_dir / "pose_pass_backbones_missing_from_final1000.tsv",
        missing_backbones,
        ["hotspot_set", "backbone_index", "reason", "raw_candidate_count"],
    )

    with (output_dir / "rf2_pre_shortlist_primary.fasta").open("w", encoding="ascii", newline="\n") as handle:
        for row in primary:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")
    with (output_dir / "rf2_rescue_candidates_needing_qc.fasta").open(
        "w", encoding="ascii", newline="\n"
    ) as handle:
        for row in rescue:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    pass_rows = [row for row in pose_rows if row.get("passes_three_occlusion_metrics")]
    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_pose_json": str(pose_json),
        "source_pose_json_sha256": sha256_file(pose_json),
        "source_status": pose.get("status"),
        "source_limitations": pose.get("limitations", []),
        "audited_backbones": len(pose_rows),
        "pose_pass_backbones": len(pass_rows),
        "pose_pass_backbones_by_set": dict(sorted(Counter(str(row["set"]) for row in pass_rows).items())),
        "primary_backbones_represented_in_final1000": len(
            {(str(row["hotspot_set"]), int(row["backbone_index"])) for row in primary}
        ),
        "primary_candidates": len(primary),
        "rescue_backbones_not_in_final1000": len(missing_backbones),
        "rescue_candidates_needing_sequence_qc": len(rescue),
        "per_backbone": per_backbone,
        "all_checks_passed": True,
        "scientific_boundary": (
            "This is an 8X6B-only preliminary design-pose triage. Primary candidates still require "
            "sequence QC and blind RF2 pose recovery; rescue candidates are outside the frozen final 1000."
        ),
    }
    summary_path = output_dir / "preliminary_pose_shortlist_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose_json", type=Path)
    parser.add_argument("raw_candidates_tsv", type=Path)
    parser.add_argument("final_candidates_tsv", type=Path)
    parser.add_argument("mpnn_scores_all_tsv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--per-backbone", type=int, default=2)
    args = parser.parse_args()
    if args.per_backbone < 1:
        parser.error("--per-backbone must be >= 1")
    summary = build(
        args.pose_json,
        args.raw_candidates_tsv,
        args.final_candidates_tsv,
        args.mpnn_scores_all_tsv,
        args.output_dir,
        per_backbone=args.per_backbone,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
