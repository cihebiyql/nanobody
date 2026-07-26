#!/usr/bin/env python3
"""Build a complete competition-priority ranking for the QC397 V2 Final50.

The frozen mechanism rank remains immutable.  The first ten positions use the
predefined 8A + at-most-2B portfolio policy; unselected non-C reserves then
retain mechanism order, followed by any C hard-risk records in mechanism order.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final50", type=Path, required=True)
    parser.add_argument("--grades", type=Path, required=True)
    parser.add_argument("--selected-top10", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"output exists: {args.out}")
    args.out.mkdir(parents=True)

    final50 = sorted(read_tsv(args.final50), key=lambda row: int(row["final_rank"]))
    grades = {row["candidate_id"]: row for row in read_tsv(args.grades)}
    selected = sorted(
        read_tsv(args.selected_top10),
        key=lambda row: int(row["competition_submission_priority"]),
    )
    final_ids = {row["candidate_id"] for row in final50}
    selected_ids = {row["candidate_id"] for row in selected}
    if (
        len(final50) != 50
        or len(final_ids) != 50
        or set(grades) != final_ids
        or len(selected) != 10
        or len(selected_ids) != 10
        or not selected_ids <= final_ids
    ):
        raise ValueError("Final50/grade/Top10 membership mismatch")

    top10_grade_counts = Counter(
        grades[row["candidate_id"]]["developability_grade"] for row in selected
    )
    if (
        top10_grade_counts["A_LOWER_RISK"] < 8
        or top10_grade_counts["B_REVIEW"] > 2
        or top10_grade_counts["C_HIGH_RISK"] != 0
    ):
        raise ValueError(f"Top10 portfolio policy violated: {top10_grade_counts}")

    by_id = {row["candidate_id"]: row for row in final50}
    ordered = [by_id[row["candidate_id"]] for row in selected]
    remaining = [row for row in final50 if row["candidate_id"] not in selected_ids]
    non_c = [
        row
        for row in remaining
        if grades[row["candidate_id"]]["developability_grade"] != "C_HIGH_RISK"
    ]
    c_risk = [
        row
        for row in remaining
        if grades[row["candidate_id"]]["developability_grade"] == "C_HIGH_RISK"
    ]
    non_c.sort(key=lambda row: int(row["final_rank"]))
    c_risk.sort(key=lambda row: int(row["final_rank"]))
    ordered.extend(non_c)
    ordered.extend(c_risk)
    if len(ordered) != 50 or len({row["candidate_id"] for row in ordered}) != 50:
        raise ValueError("competition order is not an exact Final50 permutation")

    compact: list[dict[str, Any]] = []
    for competition_rank, row in enumerate(ordered, 1):
        grade = grades[row["candidate_id"]]
        mechanism_rank = int(row["final_rank"])
        selected_row = next(
            (item for item in selected if item["candidate_id"] == row["candidate_id"]),
            None,
        )
        if competition_rank <= 10:
            role = selected_row["competition_top10_role"]
        elif grade["developability_grade"] == "C_HIGH_RISK":
            role = "C_HARD_RISK_TAIL"
        else:
            role = "RESERVE_MECHANISM_ORDER"
        compact.append(
            {
                "competition_rank_1_50": competition_rank,
                "mechanism_rank_immutable": mechanism_rank,
                "competition_rank_minus_mechanism_rank": competition_rank
                - mechanism_rank,
                "candidate_id": row["candidate_id"],
                "sequence": row["sequence"],
                "sequence_sha256": row["sequence_sha256"],
                "cdr1": row["cdr1"],
                "cdr2": row["cdr2"],
                "cdr3": row["cdr3"],
                "parent_cluster": row["parent_cluster"],
                "route": row["route"],
                "source_cohort": row["source_cohort"],
                "original_top10_rank": row.get("top10_rank", ""),
                "competition_role": role,
                "developability_grade": grade["developability_grade"],
                "developability_hard_fail": grade["developability_hard_fail"],
                "hard_fail_reasons": grade["hard_fail_reasons"],
                "review_reasons": grade["review_reasons"],
                "prefusion_compatibility_grade": grade[
                    "prefusion_compatibility_grade"
                ],
                "fusion_hard_fail": grade["fusion_hard_fail"],
                "blocker_class": row.get("blocker_class", ""),
                "strict_seed_count": row.get("strict_seed_count", ""),
                "broad_seed_count": row.get("broad_seed_count", ""),
                "pose_robustness_score": row.get("pose_robustness_score", ""),
                "blocking_consensus_score": row.get(
                    "blocking_consensus_score", ""
                ),
                "seed_consistency_fraction": row.get(
                    "seed_consistency_fraction", ""
                ),
                "dual_reference_agreement_fraction": row.get(
                    "dual_reference_agreement_fraction", ""
                ),
                "ranking_policy": (
                    "Top10=8A+max2B portfolio; ranks11-50 preserve mechanism order "
                    "among non-C reserves; C hard-risk records move to tail"
                ),
                "claim_boundary": (
                    "Competition-priority sequence queue only; mechanism rank remains "
                    "immutable and no experimental expression, purity, BLI, Kd, IC50 "
                    "or blocking claim is made."
                ),
            }
        )

    tsv_path = args.out / "Final50_competition_ranked.tsv"
    fasta_path = args.out / "Final50_competition_ranked.fasta"
    write_tsv(tsv_path, compact)
    with fasta_path.open("w", encoding="utf-8") as handle:
        for row in compact:
            short_id = (
                row["candidate_id"]
                if len(row["candidate_id"]) <= 80
                else row["candidate_id"].split("_source_", 1)[0]
            )
            handle.write(
                f">competition_rank={row['competition_rank_1_50']}|"
                f"mechanism_rank={row['mechanism_rank_immutable']}|"
                f"grade={row['developability_grade']}|{short_id}\n"
                f"{row['sequence']}\n"
            )

    receipt = {
        "schema_version": "pvrig.qc397.final50.competition_ranking.v1",
        "state": "COMPLETE",
        "candidates": 50,
        "exact_sequence_count": len({row["sequence"] for row in compact}),
        "grade_counts": dict(
            Counter(row["developability_grade"] for row in compact)
        ),
        "top10_grade_counts": dict(top10_grade_counts),
        "c_hard_risk_tail_count": len(c_risk),
        "mechanism_rank_changed": False,
        "policy": (
            "Top10 uses 8 A primary plus at most 2 high-mechanism B under diversity "
            "caps; ranks 11-50 preserve mechanism order among non-C reserves; C "
            "hard-risk candidates are placed last without deleting their records."
        ),
        "input_sha256": {
            str(path): sha256(path)
            for path in (args.final50, args.grades, args.selected_top10)
        },
        "output_sha256": {
            tsv_path.name: sha256(tsv_path),
            fasta_path.name: sha256(fasta_path),
        },
        "claim_boundary": (
            "Computational competition-priority sequence ranking only; not a new "
            "docking rank and not experimental expression, purity, affinity or "
            "blocking evidence."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (args.out / "RANKING_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
