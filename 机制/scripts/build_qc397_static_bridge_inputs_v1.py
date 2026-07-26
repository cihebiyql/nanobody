#!/usr/bin/env python3
"""Assemble one fair Top80 input from existing common4 Top200 and generated QC197.

The 397 rows are ordered by the already frozen shared common4 geometry rank.
Static metrics are joined only after both cohorts complete the same two-pose
static panel; they remain diagnostic and do not change the cross-cohort score.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


TARGET_CHANNELS = {
    "EXPLOITATION": "CORE_EXPLOITATION",
    "DIVERSITY": "PARENT_CDR3_DIVERSITY",
    "MODEL_DISAGREEMENT": "MODEL_DISAGREEMENT_RESCUE",
    "MODEL_DISAGREEMENT_RESCUE": "MODEL_DISAGREEMENT_RESCUE",
    "SPECIAL_COVERAGE": "STRUCTURAL_RESERVE",
    "STRUCTURAL_RESERVE": "STRUCTURAL_RESERVE",
    "QUOTA_SAFE_BACKFILL": "STRUCTURAL_RESERVE",
    "CORE_EXPLOITATION": "CORE_EXPLOITATION",
    "PARENT_CDR3_DIVERSITY": "PARENT_CDR3_DIVERSITY",
}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_generated_parent(row: dict[str, str]) -> str:
    # The integrated QC table exposes the actual generation route as
    # ``structure_selection_route``.  ``source_route`` is absent there; using it
    # would incorrectly collapse RFantibody and fixed-pose MPNN designs into one
    # parent and distort the frozen diversity caps.
    route = row.get("structure_selection_route", "")
    if route == "rfantibody":
        identifier = row.get("rfantibody_patch", "") or "UNKNOWN_PATCH"
        return f"GENERATED_RFANTIBODY_{identifier}"
    return "GENERATED_FIXED_POSE_MPNN"


def require_static_receipt(
    path: Path, candidates: int, jobs: int, metrics_path: Path
) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("state") != "STATIC_COMPLETE":
        raise ValueError(f"static receipt incomplete: {path}")
    if receipt.get("candidates") != candidates or receipt.get("jobs") != jobs:
        raise ValueError(f"unexpected static receipt counts: {path}")
    expected_roles = {
        "rosetta": "DESCRIPTIVE_ONLY",
        "prodigy": "WEAK_PRIOR_ONLY",
        "foldx": "NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED",
    }
    if receipt.get("method_roles") != expected_roles:
        raise ValueError(f"method role mismatch: {path}")
    recorded_metrics_sha = receipt.get("metrics_sha256")
    if recorded_metrics_sha and recorded_metrics_sha != sha256_file(metrics_path):
        raise ValueError(f"static metric hash mismatch: {path}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-qc-rank", type=Path, required=True)
    parser.add_argument("--existing-common4", type=Path, required=True)
    parser.add_argument("--generated-qc", type=Path, required=True)
    parser.add_argument("--vhh-eval", type=Path, required=True)
    parser.add_argument("--existing-static-metrics", type=Path, required=True)
    parser.add_argument("--existing-static-receipt", type=Path, required=True)
    parser.add_argument("--generated-static-metrics", type=Path, required=True)
    parser.add_argument("--generated-static-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    combined = read_tsv(args.combined_qc_rank)
    existing = read_tsv(args.existing_common4)
    generated = read_tsv(args.generated_qc)
    if len(combined) != 397 or len(existing) != 200 or len(generated) != 197:
        raise ValueError((len(combined), len(existing), len(generated)))
    combined_by_id = {row["candidate_id"]: row for row in combined}
    existing_by_id = {row["candidate_id"]: row for row in existing}
    generated_by_id = {row["candidate_id"]: row for row in generated}
    if len(combined_by_id) != 397 or set(existing_by_id) | set(generated_by_id) != set(combined_by_id):
        raise ValueError("source candidate sets do not make the combined QC397 set")
    if set(existing_by_id) & set(generated_by_id):
        raise ValueError("candidate ID collision across cohorts")
    vhh_by_id = {row["id"]: row for row in read_tsv(args.vhh_eval)}
    if not set(generated_by_id).issubset(vhh_by_id):
        raise ValueError("generated VHH evaluation is incomplete")
    existing_metrics = read_tsv(args.existing_static_metrics)
    generated_metrics = read_tsv(args.generated_static_metrics)
    if len(existing_metrics) != 400 or len(generated_metrics) != 394:
        raise ValueError("static metric count mismatch")
    existing_receipt = require_static_receipt(
        args.existing_static_receipt, 200, 400, args.existing_static_metrics
    )
    generated_receipt = require_static_receipt(
        args.generated_static_receipt, 197, 394, args.generated_static_metrics
    )
    metrics = existing_metrics + generated_metrics
    metric_counts = Counter(row["candidate_id"] for row in metrics)
    if set(metric_counts) != set(combined_by_id) or set(metric_counts.values()) != {2}:
        raise ValueError("static metrics do not supply exactly two poses per QC397 candidate")
    for candidate_id in metric_counts:
        conformations = {row["conformation"] for row in metrics if row["candidate_id"] == candidate_id}
        if conformations != {"8x6b", "9e6y"}:
            raise ValueError(f"static conformation mismatch: {candidate_id}")

    bridge_rows: list[dict[str, str]] = []
    for candidate_id, combined_row in combined_by_id.items():
        rank = int(combined_row["merged_common4_qc_geometry_rank"])
        if candidate_id in existing_by_id:
            source = existing_by_id[candidate_id]
            channel = TARGET_CHANNELS.get(source.get("selection_channel", ""), "CORE_EXPLOITATION")
            row = {
                "candidate_id": candidate_id,
                "sequence": source["sequence"],
                "sequence_sha256": source["sequence_sha256"],
                "cdr1": source.get("cdr1", ""),
                "cdr2": source.get("cdr2", ""),
                "cdr3": source.get("cdr3", ""),
                "parent_cluster": source.get("parent_cluster", ""),
                "route": source.get("route", ""),
                "cdr3_diversity_cluster": source.get("intra_team_cluster_id", "") or source.get("parent_cluster", ""),
                "source_cohort": "existing_old_new7500_top200",
                "source_lane": source.get("selection_channel", ""),
                "official_validator_pass": source.get("official_validator_pass", ""),
                "pass_similarity_filter": source.get("pass_similarity_filter", ""),
                "hard_fail": source.get("hard_fail", ""),
                "current_frozen_final50_rank": combined_row.get("current_frozen_final50_rank", ""),
            }
        else:
            source = generated_by_id[candidate_id]
            vhh = vhh_by_id[candidate_id]
            lane = source.get("structure_selection_lane", "")
            channel = TARGET_CHANNELS.get(lane, "STRUCTURAL_RESERVE")
            row = {
                "candidate_id": candidate_id,
                "sequence": source["sequence"],
                "sequence_sha256": source["sequence_sha256"],
                "cdr1": vhh.get("imgt_cdr1", ""),
                "cdr2": vhh.get("imgt_cdr2", ""),
                "cdr3": vhh.get("imgt_cdr3", ""),
                "parent_cluster": normalized_generated_parent(source),
                "route": source.get("structure_selection_route", ""),
                "cdr3_diversity_cluster": source.get("cdr3_near_family_id", ""),
                "source_cohort": "generated_top3000",
                "source_lane": lane,
                "official_validator_pass": "PASS",
                "pass_similarity_filter": source.get("pass_similarity_filter", ""),
                "hard_fail": source.get("integrated_hard_fail", ""),
                "current_frozen_final50_rank": "",
            }
        if not all(row[key] for key in ("sequence", "cdr1", "cdr2", "cdr3", "parent_cluster", "route")):
            raise ValueError(f"bridge row lacks required identity fields: {candidate_id}")
        if row["official_validator_pass"] != "PASS" or row["pass_similarity_filter"] != "PASS" or row["hard_fail"].lower() == "true":
            raise ValueError(f"hard gate unexpectedly fails: {candidate_id}")
        row.update(
            {
                "top200_rank": str(rank),
                "unified_qc397_geometry_rank": str(rank),
                "selection_score": str(1_000_000 - rank),
                "selection_channel": channel,
                "strict_seed_count": combined_row.get("strict_seed_count", ""),
                "broad_seed_count": combined_row.get("broad_seed_count", ""),
                "pose_robustness_score": combined_row.get("pose_robustness_score", ""),
                "blocking_consensus_score": combined_row.get("blocking_consensus_score", ""),
                "seed_consistency_fraction": combined_row.get("seed_consistency_fraction", ""),
                "pose_pair_consensus_fraction": combined_row.get("pose_pair_consensus_fraction", ""),
                "dual_reference_agreement_fraction": combined_row.get("dual_reference_agreement_fraction", ""),
                "cdr3_occlusion_fraction": combined_row.get("cdr3_occlusion_fraction", ""),
                "blocker_class": combined_row.get("blocker_class", ""),
                "common4_rank_policy": "shared cross-cohort common4 geometry ordinal; static values are diagnostic only",
            }
        )
        bridge_rows.append(row)
    bridge_rows.sort(key=lambda row: int(row["unified_qc397_geometry_rank"]))
    if [row["unified_qc397_geometry_rank"] for row in bridge_rows] != [str(i) for i in range(1, 398)]:
        raise ValueError("combined QC397 ranks are not contiguous")
    args.out.mkdir(parents=True, exist_ok=True)
    bridge_path = args.out / "unified_qc397_static_input.tsv"
    metrics_path = args.out / "unified_qc397_static_metrics_794.tsv"
    write_tsv(bridge_path, bridge_rows)
    write_tsv(metrics_path, metrics)
    complete_receipt_path = args.out / "QC397_STATIC_COMPLETE.json"
    complete_receipt = {
        "schema_version": "pvrig.qc397.static_bridge.v2",
        "state": "STATIC_COMPLETE",
        "candidates": 397,
        "jobs": 794,
        "method_roles": existing_receipt["method_roles"],
        "metrics_sha256": sha256_file(metrics_path),
        "source_static_receipts": {
            str(args.existing_static_receipt): sha256_file(args.existing_static_receipt),
            str(args.generated_static_receipt): sha256_file(args.generated_static_receipt),
        },
        "claim_boundary": "A merged two-conformation static diagnostics panel; not experimental binding, affinity, expression, purity, or blocking evidence.",
    }
    complete_receipt_path.write_text(
        json.dumps(complete_receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "pvrig.qc397.static_bridge_input.v2",
        "state": "QC397_STATIC_BRIDGE_INPUT_COMPLETE",
        "candidates": 397,
        "jobs": 794,
        "source_counts": {"existing_common4_top200": 200, "generated_integrated_qc": 197},
        "method_roles": existing_receipt["method_roles"],
        "selection_score_semantics": "1000000 - unified_qc397_geometry_rank; no source-specific pre-screen model score used",
        "selection_channel_mapping": TARGET_CHANNELS,
        "input_hashes": {
            str(path): sha256_file(path)
            for path in (
                args.combined_qc_rank, args.existing_common4, args.generated_qc, args.vhh_eval,
                args.existing_static_metrics, args.existing_static_receipt,
                args.generated_static_metrics, args.generated_static_receipt,
            )
        },
        "output_hashes": {
            str(bridge_path): sha256_file(bridge_path),
            str(metrics_path): sha256_file(metrics_path),
            str(complete_receipt_path): sha256_file(complete_receipt_path),
        },
        "claim_boundary": "Static bridge is computational evidence only; it does not establish experimental binding, affinity, expression, purity, or blocking.",
    }
    (args.out / "QC397_STATIC_BRIDGE_INPUT_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidates": 397, "jobs": 794, "channels": dict(Counter(row['selection_channel'] for row in bridge_rows))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
