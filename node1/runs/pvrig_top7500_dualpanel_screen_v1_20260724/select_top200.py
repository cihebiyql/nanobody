#!/usr/bin/env python3
"""Select the diversity-constrained Top200 static-review pool."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CHANNEL_TARGETS = [
    ("CORE_EXPLOITATION", 120),
    ("PARENT_CDR3_DIVERSITY", 40),
    ("MODEL_DISAGREEMENT_RESCUE", 20),
    ("STRUCTURAL_RESERVE", 20),
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("refusing to write empty Top200")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
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
        ("production_final_score", 1.0),
        ("rescreen_proxy_score", 1.0),
        ("rescreen_competition_proxy", 100.0),
        ("final_score", 1.0),
    ):
        try:
            value = float(row.get(key, "")) * scale
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return -math.inf


def cdr3_clusters(rows: list[dict[str, str]], threshold: float = 0.80) -> dict[str, str]:
    parent = {row["candidate_id"]: row["candidate_id"] for row in rows}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a == b:
            return
        keep, merge = sorted((a, b))
        parent[merge] = keep

    by_length: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_length[len(row.get("cdr3", ""))].append(row)
    for length, group in by_length.items():
        if length == 0:
            continue
        for index, left in enumerate(group):
            left_cdr3 = left["cdr3"]
            for right in group[index + 1 :]:
                matches = sum(a == b for a, b in zip(left_cdr3, right["cdr3"]))
                if matches / length >= threshold:
                    union(left["candidate_id"], right["candidate_id"])
    members: dict[str, list[str]] = defaultdict(list)
    for candidate_id in parent:
        members[find(candidate_id)].append(candidate_id)
    ordered = sorted(members, key=lambda root: (-len(members[root]), root))
    cluster_name = {
        root: f"CDR3CL_{index:04d}" for index, root in enumerate(ordered, start=1)
    }
    return {candidate_id: cluster_name[find(candidate_id)] for candidate_id in parent}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--full-qc", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    evidence_rows = read_tsv(args.evidence)
    qc_rows = read_tsv(args.full_qc)
    evidence = {row["candidate_id"]: row for row in evidence_rows}
    qc = {row["candidate_id"]: row for row in qc_rows}
    missing = sorted(set(qc) - set(evidence))
    if missing:
        raise ValueError(f"{len(missing)} full-QC candidates missing evidence rows")

    merged: list[dict[str, str]] = []
    for candidate_id, qc_row in qc.items():
        source = evidence[candidate_id]
        official = qc_row.get("official_validator_pass", "") == "PASS"
        novelty = qc_row.get("pass_similarity_filter", "") == "PASS"
        hard_fail = qc_row.get("hard_fail", "").lower() == "true"
        if (
            not official
            or not novelty
            or hard_fail
            or source.get("g3_docking_hardpass") != "true"
            or source.get("developability_hardpass") != "true"
        ):
            continue
        row = dict(source)
        for key, value in qc_row.items():
            row[f"qc_{key}" if key in row and key != "candidate_id" else key] = value
        row["selection_score"] = f"{score({**source, **qc_row}):.9f}"
        merged.append(row)
    if len(merged) < 200:
        raise ValueError(f"only {len(merged)} hard-pass candidates available for Top200")

    cluster_map = cdr3_clusters(merged)
    for row in merged:
        row["cdr3_diversity_cluster"] = cluster_map[row["candidate_id"]]
    by_id = {row["candidate_id"]: row for row in merged}
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    parent_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    cluster_counts: Counter[str] = Counter()
    exact_cdr3_counts: Counter[str] = Counter()

    def direct_cdr3_identity(left: dict[str, str], right: dict[str, str]) -> float:
        left_cdr3 = left.get("cdr3", "")
        right_cdr3 = right.get("cdr3", "")
        if not left_cdr3 or len(left_cdr3) != len(right_cdr3):
            return 0.0
        return sum(a == b for a, b in zip(left_cdr3, right_cdr3)) / len(left_cdr3)

    def allowed(row: dict[str, str]) -> bool:
        return (
            row["candidate_id"] not in selected_ids
            and parent_counts[row.get("parent_cluster", "")] < 60
            and route_counts[row.get("route", "")] < 140
            and exact_cdr3_counts[row.get("cdr3", "")] < 1
            and all(
                direct_cdr3_identity(row, chosen) < 0.80
                for chosen in selected
            )
        )

    def add(row: dict[str, str], channel: str) -> None:
        copied = dict(row)
        copied["selection_channel"] = channel
        copied["static_review_status"] = "NOT_RUN"
        copied["prodigy_status"] = "NOT_RUN"
        copied["foldx_status"] = "NOT_RUN"
        copied["rosetta_status"] = "NOT_RUN"
        selected.append(copied)
        selected_ids.add(row["candidate_id"])
        parent_counts[row.get("parent_cluster", "")] += 1
        route_counts[row.get("route", "")] += 1
        cluster_counts[row["cdr3_diversity_cluster"]] += 1
        exact_cdr3_counts[row.get("cdr3", "")] += 1

    def ranked(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(rows, key=lambda row: (-score(row), row["candidate_id"]))

    core = ranked([row for row in merged if row.get("candidate_tier") == "CORE_A"])
    for row in core:
        if len(selected) >= 120:
            break
        if allowed(row):
            add(row, "CORE_EXPLOITATION")

    diversity_candidates = sorted(
        [row for row in merged if row["candidate_id"] not in selected_ids],
        key=lambda row: (
            parent_counts[row.get("parent_cluster", "")],
            cluster_counts[row["cdr3_diversity_cluster"]],
            -score(row),
            row["candidate_id"],
        ),
    )
    diversity_target = len(selected) + 40
    for row in diversity_candidates:
        if len(selected) >= diversity_target:
            break
        if allowed(row):
            add(row, "PARENT_CDR3_DIVERSITY")

    disagreement = ranked(
        [
            row
            for row in merged
            if row["candidate_id"] not in selected_ids
            and row.get("candidate_tier") == "DISAGREEMENT_C"
        ]
    )
    disagreement_target = len(selected) + 20
    for row in disagreement:
        if len(selected) >= disagreement_target:
            break
        if allowed(row):
            add(row, "MODEL_DISAGREEMENT_RESCUE")

    reserve_target = min(200, len(selected) + 20)
    for row in ranked([row for row in merged if row["candidate_id"] not in selected_ids]):
        if len(selected) >= reserve_target:
            break
        if allowed(row):
            add(row, "STRUCTURAL_RESERVE")

    if len(selected) < 200:
        for row in ranked([row for row in merged if row["candidate_id"] not in selected_ids]):
            if len(selected) >= 200:
                break
            if allowed(row):
                add(row, "QUOTA_SAFE_BACKFILL")
    if len(selected) != 200:
        raise ValueError(f"Top200 selection produced {len(selected)} rows")
    for rank, row in enumerate(selected, start=1):
        row["top200_rank"] = str(rank)
    max_pairwise_cdr3_identity = max(
        (
            direct_cdr3_identity(left, right)
            for index, left in enumerate(selected)
            for right in selected[index + 1 :]
        ),
        default=0.0,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    tsv_path = args.out / "top200_pre_static.tsv"
    fasta_path = args.out / "top200_pre_static.fasta"
    write_tsv(tsv_path, selected)
    write_fasta(fasta_path, selected)
    receipt = {
        "schema_version": "pvrig.top200.static_pool.v1",
        "status": "PASS_TOP200_FROZEN",
        "count": len(selected),
        "channel_counts": dict(Counter(row["selection_channel"] for row in selected)),
        "parent_counts": dict(parent_counts),
        "route_counts": dict(route_counts),
        "cdr3_cluster_count": len(set(row["cdr3_diversity_cluster"] for row in selected)),
        "max_cdr3_cluster_count": max(cluster_counts.values(), default=0),
        "single_linkage_cdr3_clusters_reporting_only": True,
        "direct_pairwise_cdr3_identity_threshold": 0.80,
        "max_direct_pairwise_cdr3_identity": max_pairwise_cdr3_identity,
        "exact_cdr3_duplicate_count": len(selected) - len(exact_cdr3_counts),
        "input_hashes": {
            str(args.evidence): sha256_file(args.evidence),
            str(args.full_qc): sha256_file(args.full_qc),
        },
        "output_hashes": {
            tsv_path.name: sha256_file(tsv_path),
            fasta_path.name: sha256_file(fasta_path),
        },
        "claim_boundary": "Top200 computational static-review pool; not experimental binder/blocker ranking.",
    }
    receipt_path = args.out / "TOP200_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.name}\n"
            for path in (tsv_path, fasta_path, receipt_path)
        ),
        encoding="ascii",
    )
    print(json.dumps({"count": len(selected), "channels": receipt["channel_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
