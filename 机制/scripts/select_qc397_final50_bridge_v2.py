#!/usr/bin/env python3
"""Freeze a QC397-bridged Final50 and Top10 computational portfolio."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


FINAL_CHANNELS = [
    ("EXPLOITATION", 30),
    ("PARENT_MECHANISM_DIVERSITY", 10),
    ("MODEL_DISAGREEMENT_RESCUE", 5),
    ("STRUCTURAL_DIVERSITY_RESERVE", 5),
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_fasta(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def score(row: dict[str, str]) -> float:
    for key, scale in (
        ("post_static_selection_score", 1.0),
        ("selection_score", 1.0),
        ("rescreen_competition_proxy", 100.0),
    ):
        try:
            value = float(row.get(key, "")) * scale
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return -math.inf


def final_channel(row: dict[str, str]) -> str:
    channel = row.get("top80_selection_channel", "")
    if channel == "CORE_EXPLOITATION":
        return "EXPLOITATION"
    if channel == "PARENT_CDR3_DIVERSITY":
        return "PARENT_MECHANISM_DIVERSITY"
    if channel == "MODEL_DISAGREEMENT_RESCUE":
        return "MODEL_DISAGREEMENT_RESCUE"
    return "STRUCTURAL_DIVERSITY_RESERVE"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top80", type=Path, required=True)
    parser.add_argument("--top80-receipt", type=Path, required=True)
    parser.add_argument("--md-manifest", type=Path, required=True)
    parser.add_argument("--md-summary", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    top80_receipt = json.loads(args.top80_receipt.read_text(encoding="utf-8"))
    if top80_receipt.get("state") != "TOP80_COMPLETE" or top80_receipt.get("count") != 80:
        raise ValueError("Top80 receipt is not complete")
    rows = read_tsv(args.top80)
    if len(rows) != 80 or len({row["candidate_id"] for row in rows}) != 80:
        raise ValueError("Top80 must contain 80 unique candidates")
    md_rows = read_tsv(args.md_manifest)
    md_candidates = {row["candidate_id"] for row in md_rows}
    md_summary: dict[str, dict[str, str]] = {}
    if args.md_summary and args.md_summary.is_file():
        md_summary = {
            row["candidate_id"]: row for row in read_tsv(args.md_summary)
        }
    for row in rows:
        row["md_selection_status"] = (
            "SELECTED_MD_PANEL" if row["candidate_id"] in md_candidates else "NOT_RUN_RESERVE"
        )
        row["md_evidence_role"] = "DESCRIPTIVE_ONLY"
        if row["candidate_id"] in md_summary:
            for key, value in md_summary[row["candidate_id"]].items():
                if key != "candidate_id":
                    row[f"md_{key}"] = value
        row["final_channel"] = final_channel(row)
    missing_cdr3 = [row["candidate_id"] for row in rows if not row.get("cdr3", "")]
    if missing_cdr3:
        raise ValueError(f"{len(missing_cdr3)} Top80 candidates lack CDR3 sequences")
    ranked = sorted(rows, key=lambda row: (-score(row), row["candidate_id"]))
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    sequences: set[str] = set()
    cdr3s: set[str] = set()
    parent_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    cluster_counts: Counter[str] = Counter()

    def direct_cdr3_identity(left: dict[str, str], right: dict[str, str]) -> float:
        left_cdr3 = left.get("cdr3", "")
        right_cdr3 = right.get("cdr3", "")
        if not left_cdr3 or len(left_cdr3) != len(right_cdr3):
            return 0.0
        return sum(a == b for a, b in zip(left_cdr3, right_cdr3)) / len(left_cdr3)

    def allowed(row: dict[str, str]) -> bool:
        return (
            row["candidate_id"] not in selected_ids
            and row["sequence"] not in sequences
            and row.get("cdr3", "") not in cdr3s
            and parent_counts[row.get("parent_cluster", "")] < 15
            and route_counts[row.get("route", "")] < 35
            and all(
                direct_cdr3_identity(row, chosen) < 0.80
                for chosen in selected
            )
        )

    def add(row: dict[str, str], channel: str) -> None:
        copied = dict(row)
        copied["final_selection_channel"] = channel
        copied["final_selection_reason"] = (
            "all required hard gates complete; selected by shared common4 geometry ordinal "
            "under final diversity constraints"
        )
        selected.append(copied)
        selected_ids.add(row["candidate_id"])
        sequences.add(row["sequence"])
        cdr3s.add(row.get("cdr3", ""))
        parent_counts[row.get("parent_cluster", "")] += 1
        route_counts[row.get("route", "")] += 1
        cluster_counts[row.get("cdr3_diversity_cluster", "")] += 1

    for channel, target in FINAL_CHANNELS:
        before = len(selected)
        for row in ranked:
            if len(selected) - before >= target:
                break
            if row["final_channel"] == channel and allowed(row):
                add(row, channel)
    for row in ranked:
        if len(selected) >= 50:
            break
        if allowed(row):
            add(row, "QUOTA_SAFE_BACKFILL")
    if len(selected) != 50:
        raise ValueError(f"final selection produced {len(selected)} candidates")
    if len(parent_counts) < 4:
        raise ValueError(f"final50 uses only {len(parent_counts)} parent clusters")
    for rank, row in enumerate(selected, start=1):
        row["final_rank"] = str(rank)
    max_pairwise_cdr3_identity = max(
        (
            direct_cdr3_identity(left, right)
            for index, left in enumerate(selected)
            for right in selected[index + 1 :]
        ),
        default=0.0,
    )

    # Top10: seven highest-confidence exploitation candidates and three candidates
    # chosen to add independent parent/mechanism coverage.
    exploitation = [
        row for row in selected if row["final_selection_channel"] == "EXPLOITATION"
    ]
    top10: list[dict[str, str]] = []
    top10_parent: Counter[str] = Counter()
    top10_route: Counter[str] = Counter()
    for row in exploitation:
        if len(top10) >= 7:
            break
        if (
            top10_parent[row.get("parent_cluster", "")] < 4
            and top10_route[row.get("route", "")] < 7
        ):
            top10.append(dict(row))
            top10_parent[row.get("parent_cluster", "")] += 1
            top10_route[row.get("route", "")] += 1
    top10_ids = {row["candidate_id"] for row in top10}
    for row in selected:
        if len(top10) >= 10:
            break
        parent = row.get("parent_cluster", "")
        route = row.get("route", "")
        independent = parent not in top10_parent or row["final_selection_channel"] != "EXPLOITATION"
        if (
            row["candidate_id"] not in top10_ids
            and independent
            and top10_parent[parent] < 4
            and top10_route[route] < 7
        ):
            top10.append(dict(row))
            top10_ids.add(row["candidate_id"])
            top10_parent[parent] += 1
            top10_route[route] += 1
    for row in selected:
        if len(top10) >= 10:
            break
        parent = row.get("parent_cluster", "")
        route = row.get("route", "")
        if (
            row["candidate_id"] not in top10_ids
            and top10_parent[parent] < 4
            and top10_route[route] < 7
        ):
            top10.append(dict(row))
            top10_ids.add(row["candidate_id"])
            top10_parent[parent] += 1
            top10_route[route] += 1
    if len(top10) != 10:
        raise ValueError("could not build constrained Top10")
    for rank, row in enumerate(top10, start=1):
        row["top10_rank"] = str(rank)
        row["top10_role"] = (
            "HIGHEST_CONFIDENCE_CORE" if rank <= 7 else "INDEPENDENT_PARENT_OR_MECHANISM"
        )

    args.out.mkdir(parents=True, exist_ok=True)
    final_tsv = args.out / "final50_ranked.tsv"
    final_fasta = args.out / "final50_ranked.fasta"
    top10_tsv = args.out / "top10_priority.tsv"
    top10_fasta = args.out / "top10_priority.fasta"
    write_tsv(final_tsv, selected)
    write_fasta(final_fasta, selected)
    write_tsv(top10_tsv, top10)
    write_fasta(top10_fasta, top10)
    receipt = {
        "schema_version": "pvrig.qc397.final50.portfolio.v2",
        "state": "FINAL50_PREAUDIT_COMPLETE",
        "count": 50,
        "top10_count": 10,
        "channel_counts": dict(
            Counter(row["final_selection_channel"] for row in selected)
        ),
        "parent_counts": dict(parent_counts),
        "route_counts": dict(route_counts),
        "max_cdr3_cluster_count": max(cluster_counts.values(), default=0),
        "single_linkage_cdr3_clusters_reporting_only": True,
        "direct_pairwise_cdr3_identity_threshold": 0.80,
        "max_direct_pairwise_cdr3_identity": max_pairwise_cdr3_identity,
        "exact_sequence_duplicates": len(selected) - len(sequences),
        "exact_cdr3_duplicates": len(selected) - len(cdr3s),
        "md_selected_candidates": len(md_candidates),
        "md_completed_candidates": len(md_summary),
        "md_role": "DESCRIPTIVE_ONLY",
        "input_hashes": {
            str(args.top80): sha256_file(args.top80),
            str(args.top80_receipt): sha256_file(args.top80_receipt),
            str(args.md_manifest): sha256_file(args.md_manifest),
            **(
                {str(args.md_summary): sha256_file(args.md_summary)}
                if args.md_summary and args.md_summary.is_file()
                else {}
            ),
        },
        "claim_boundary": (
            "QC397-bridged computational portfolio; no experimental BLI, Kd, IC50, expression "
            "or purity claim."
        ),
    }
    receipt_path = args.out / "FINAL50_PREAUDIT.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = [final_tsv, final_fasta, top10_tsv, top10_fasta, receipt_path]
    (args.out / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in outputs),
        encoding="ascii",
    )
    print(json.dumps(receipt["channel_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
