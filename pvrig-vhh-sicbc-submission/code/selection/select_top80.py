#!/usr/bin/env python3
"""Select the diversity-constrained Top80 after complete static review.

Rosetta and PRODIGY values are retained as descriptive/weak-prior fields but do
not alter rank because the positive/control calibration did not authorize them
as cross-candidate ranking metrics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CHANNEL_TARGETS = [
    ("CORE_EXPLOITATION", 48),
    ("PARENT_CDR3_DIVERSITY", 16),
    ("MODEL_DISAGREEMENT_RESCUE", 8),
    ("STRUCTURAL_RESERVE", 8),
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


def numeric(row: dict[str, str], key: str, default: float = -math.inf) -> float:
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def candidate_score(row: dict[str, str]) -> float:
    for key, scale in (
        ("selection_score", 1.0),
        ("production_final_score", 1.0),
        ("rescreen_proxy_score", 1.0),
        ("rescreen_competition_proxy", 100.0),
        ("final_score", 1.0),
    ):
        value = numeric(row, key)
        if value != -math.inf:
            return value * scale
    return -math.inf


def aggregate_static(rows: list[dict[str, str]]) -> dict[str, str]:
    if len(rows) != 2 or {row["conformation"] for row in rows} != {"8x6b", "9e6y"}:
        raise ValueError("candidate static evidence must contain 8X6B and 9E6Y")
    output: dict[str, str] = {
        "static_pose_count": "2",
        "static_conformation_count": "2",
        "static_review_status": "PASS_DESCRIPTIVE_COMPLETE",
        "rosetta_status": "DESCRIPTIVE_ONLY_COMPLETE",
        "prodigy_status": "WEAK_PRIOR_ONLY_COMPLETE",
        "foldx_status": "NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED",
        "static_rank_contribution": "0",
    }
    metric_names = [
        "interface_atom_contacts_4p5a",
        "interface_residue_pairs_5a",
        "interface_contact_density_proxy",
        "physical_clash_atom_pairs_2a",
        "hbond_donor_acceptor_distance_proxy_3p5a",
        "salt_bridge_distance_proxy_4a",
        "hydrophobic_interface_residue_pairs_5a",
        "cdr_contact_fraction",
        "cdr3_contact_fraction",
        "exposed_hydrophobic_residue_count_proxy",
        "ptm_motif_residue_exposed_count_proxy",
        "rosetta_dSASA_int",
        "rosetta_delta_unsatHbonds",
        "rosetta_hbonds_int",
        "rosetta_sc_value",
        "rosetta_dG_separated",
        "rosetta_per_residue_energy_int",
        "prodigy_predicted_dg_kcal_mol",
    ]
    for name in metric_names:
        values = [numeric(row, name, math.nan) for row in rows]
        finite = [value for value in values if math.isfinite(value)]
        output[f"static_median_{name}"] = (
            f"{statistics.median(finite):.9g}" if finite else ""
        )
        output[f"static_range_{name}"] = (
            f"{min(finite):.9g},{max(finite):.9g}" if finite else ""
        )
    output["static_pose_ids"] = ",".join(
        row["static_job_id"] for row in sorted(rows, key=lambda item: item["conformation"])
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top200", type=Path, required=True)
    parser.add_argument("--static-metrics", type=Path, required=True)
    parser.add_argument("--static-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    receipt = json.loads(args.static_receipt.read_text(encoding="utf-8"))
    if (
        receipt.get("state") != "STATIC_COMPLETE"
        or receipt.get("candidates") != 200
        or receipt.get("jobs") != 400
    ):
        raise ValueError("static receipt does not prove a complete 200 x 2 panel")
    top = read_tsv(args.top200)
    metrics = read_tsv(args.static_metrics)
    if len(top) != 200 or len(metrics) != 400:
        raise ValueError("expected Top200 and 400 static metric rows")
    by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in metrics:
        by_candidate[row["candidate_id"]].append(row)
    merged: list[dict[str, str]] = []
    for row in top:
        candidate_id = row["candidate_id"]
        if candidate_id not in by_candidate:
            raise ValueError(f"missing static evidence: {candidate_id}")
        copied = dict(row)
        copied.update(aggregate_static(by_candidate[candidate_id]))
        copied["post_static_selection_score"] = f"{candidate_score(row):.9f}"
        copied["static_selection_policy"] = (
            "technical completeness plus pre-static evidence rank; "
            "Rosetta/PRODIGY values are not cross-candidate rank inputs"
        )
        merged.append(copied)
    missing_cdr3 = [
        row["candidate_id"] for row in merged if not row.get("cdr3", "")
    ]
    if missing_cdr3:
        raise ValueError(
            f"{len(missing_cdr3)} Top200 candidates lack CDR3 sequences"
        )

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
            and parent_counts[row.get("parent_cluster", "")] < 30
            and route_counts[row.get("route", "")] < 60
            and exact_cdr3_counts[row.get("cdr3", "")] < 1
            and all(
                direct_cdr3_identity(row, chosen) < 0.80
                for chosen in selected
            )
        )

    def add(row: dict[str, str], channel: str) -> None:
        copied = dict(row)
        copied["top80_selection_channel"] = channel
        copied["top80_selection_reason"] = (
            "all hard gates and two-conformation static technical review complete; "
            "selected by pre-static evidence rank under diversity quotas"
        )
        selected.append(copied)
        selected_ids.add(row["candidate_id"])
        parent_counts[row.get("parent_cluster", "")] += 1
        route_counts[row.get("route", "")] += 1
        cluster_counts[row.get("cdr3_diversity_cluster", "")] += 1
        exact_cdr3_counts[row.get("cdr3", "")] += 1

    ranked = sorted(merged, key=lambda row: (-candidate_score(row), row["candidate_id"]))
    for channel, target_count in CHANNEL_TARGETS:
        pool = [
            row
            for row in ranked
            if row.get("selection_channel") == channel
            or (
                channel == "STRUCTURAL_RESERVE"
                and row.get("selection_channel") == "QUOTA_SAFE_BACKFILL"
            )
        ]
        before = len(selected)
        for row in pool:
            if len(selected) - before >= target_count:
                break
            if allowed(row):
                add(row, channel)
    for row in ranked:
        if len(selected) >= 80:
            break
        if allowed(row):
            add(row, "QUOTA_SAFE_BACKFILL")
    if len(selected) != 80:
        raise ValueError(f"Top80 selection produced {len(selected)} candidates")
    for rank, row in enumerate(selected, start=1):
        row["top80_rank"] = str(rank)
    max_pairwise_cdr3_identity = max(
        (
            direct_cdr3_identity(left, right)
            for index, left in enumerate(selected)
            for right in selected[index + 1 :]
        ),
        default=0.0,
    )

    selected_set = {row["candidate_id"] for row in selected}
    exclusions = []
    for row in merged:
        if row["candidate_id"] in selected_set:
            continue
        exclusions.append(
            {
                "candidate_id": row["candidate_id"],
                "top200_rank": row.get("top200_rank", ""),
                "selection_channel": row.get("selection_channel", ""),
                "reason": "lower_rank_or_diversity_quota_after_complete_static_review",
                "static_review_status": row["static_review_status"],
            }
        )
    args.out.mkdir(parents=True, exist_ok=True)
    tsv_path = args.out / "top80_post_static.tsv"
    fasta_path = args.out / "top80_post_static.fasta"
    exclusions_path = args.out / "top200_to_top80_exclusions.tsv"
    write_tsv(tsv_path, selected)
    write_fasta(fasta_path, selected)
    write_tsv(exclusions_path, exclusions)
    top80_receipt = {
        "schema_version": "pvrig.top80.post_static.v1",
        "state": "TOP80_COMPLETE",
        "count": 80,
        "channel_counts": dict(
            Counter(row["top80_selection_channel"] for row in selected)
        ),
        "parent_counts": dict(parent_counts),
        "route_counts": dict(route_counts),
        "max_cdr3_cluster_count": max(cluster_counts.values(), default=0),
        "single_linkage_cdr3_clusters_reporting_only": True,
        "direct_pairwise_cdr3_identity_threshold": 0.80,
        "max_direct_pairwise_cdr3_identity": max_pairwise_cdr3_identity,
        "exact_cdr3_duplicate_count": len(selected) - len(exact_cdr3_counts),
        "static_method_roles": receipt["method_roles"],
        "rank_policy": "calibrated static methods do not change cross-candidate rank",
        "input_hashes": {
            str(args.top200): sha256_file(args.top200),
            str(args.static_metrics): sha256_file(args.static_metrics),
            str(args.static_receipt): sha256_file(args.static_receipt),
        },
        "output_hashes": {
            tsv_path.name: sha256_file(tsv_path),
            fasta_path.name: sha256_file(fasta_path),
            exclusions_path.name: sha256_file(exclusions_path),
        },
        "claim_boundary": (
            "Computational shortlist only; static values are not experimental "
            "binding, Kd, IC50, expression or purity."
        ),
    }
    receipt_path = args.out / "TOP80_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(top80_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.name}\n"
            for path in [tsv_path, fasta_path, exclusions_path, receipt_path]
        ),
        encoding="ascii",
    )
    print(json.dumps(top80_receipt["channel_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
