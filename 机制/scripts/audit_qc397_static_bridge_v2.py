#!/usr/bin/env python3
"""Audit the generated197 + legacy200 static-review→Top80→Final50 bridge."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

EXPECTED_FROZEN_FINAL50_SHA256 = "d1026f93b547013366ff803ee0fe7f1864df1cd02d758a24d72c988edcb37008"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def direct_cdr3_identity(left: str, right: str) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(a == b for a, b in zip(left, right)) / len(left)


def assert_subset(subset: list[dict[str, str]], parent: set[str], name: str) -> None:
    identifiers = [row["candidate_id"] for row in subset]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{name} has duplicate candidate IDs")
    if not set(identifiers).issubset(parent):
        raise ValueError(f"{name} contains candidates outside QC397")


def verify_two_pose_panel(rows: list[dict[str, str]], ids: set[str], expected: int) -> None:
    if len(rows) != expected:
        raise ValueError(f"static metric rows {len(rows)} != {expected}")
    by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_id[row["candidate_id"]].append(row)
    if set(by_id) != ids:
        raise ValueError("static metric candidates do not match QC397")
    for candidate_id, poses in by_id.items():
        if len(poses) != 2 or {pose["conformation"] for pose in poses} != {"8x6b", "9e6y"}:
            raise ValueError(f"{candidate_id} lacks exactly two reference conformations")


def verify_output_hashes(receipt: dict[str, Any], directory: Path) -> None:
    for filename, expected in receipt.get("output_hashes", {}).items():
        path = directory / filename
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"output hash mismatch: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-root", type=Path, required=True)
    parser.add_argument("--old-frozen-final50", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.bridge_root
    unified_dir = root / "unified_qc397"
    top80_dir = root / "top80"
    final_dir = root / "final50"

    old_sha = sha256_file(args.old_frozen_final50)
    if old_sha != EXPECTED_FROZEN_FINAL50_SHA256:
        raise ValueError("frozen legacy Final50 hash changed; refusing audit")
    old_final = read_tsv(args.old_frozen_final50)
    if len(old_final) != 50:
        raise ValueError("frozen legacy Final50 row count is not 50")

    unified = read_tsv(unified_dir / "unified_qc397_static_input.tsv")
    metrics = read_tsv(unified_dir / "unified_qc397_static_metrics_794.tsv")
    static_receipt = json.loads((unified_dir / "QC397_STATIC_COMPLETE.json").read_text(encoding="utf-8"))
    bridge_receipt = json.loads((unified_dir / "QC397_STATIC_BRIDGE_INPUT_RECEIPT.json").read_text(encoding="utf-8"))
    if static_receipt.get("state") != "STATIC_COMPLETE" or static_receipt.get("candidates") != 397 or static_receipt.get("jobs") != 794:
        raise ValueError("QC397 static receipt count/state failure")
    if static_receipt.get("metrics_sha256") != sha256_file(unified_dir / "unified_qc397_static_metrics_794.tsv"):
        raise ValueError("QC397 static metric receipt hash mismatch")
    if bridge_receipt.get("state") != "QC397_STATIC_BRIDGE_INPUT_COMPLETE":
        raise ValueError("bridge input receipt incomplete")
    if len(unified) != 397 or len({row["candidate_id"] for row in unified}) != 397:
        raise ValueError("QC397 unified candidate count/identity failure")
    if Counter(row["source_cohort"] for row in unified) != Counter({"existing_old_new7500_top200": 200, "generated_top3000": 197}):
        raise ValueError("QC397 cohort composition mismatch")
    for row in unified:
        seq = row["sequence"]
        if not seq or set(seq) - set("ACDEFGHIKLMNPQRSTVWY"):
            raise ValueError(f"non-standard sequence in QC397: {row['candidate_id']}")
        if hashlib.sha256(seq.encode("ascii")).hexdigest() != row["sequence_sha256"]:
            raise ValueError(f"sequence hash mismatch: {row['candidate_id']}")
        if row.get("official_validator_pass") != "PASS" or row.get("pass_similarity_filter") != "PASS":
            raise ValueError(f"hard-gate pass absent: {row['candidate_id']}")
        if row.get("hard_fail", "").lower() == "true":
            raise ValueError(f"hard fail present: {row['candidate_id']}")
        if row["source_cohort"] == "generated_top3000":
            if row["route"] == "rfantibody":
                if not row["parent_cluster"].startswith("GENERATED_RFANTIBODY_"):
                    raise ValueError(f"RFantibody parent mapping failure: {row['candidate_id']}")
            elif row["route"] == "fixed_pose_mpnn":
                if row["parent_cluster"] != "GENERATED_FIXED_POSE_MPNN":
                    raise ValueError(f"fixed-pose parent mapping failure: {row['candidate_id']}")
            else:
                raise ValueError(f"unknown generated route: {row['candidate_id']}")
    ids = {row["candidate_id"] for row in unified}
    verify_two_pose_panel(metrics, ids, 794)

    top80 = read_tsv(top80_dir / "top80_post_static.tsv")
    top80_receipt = json.loads((top80_dir / "TOP80_COMPLETE.json").read_text(encoding="utf-8"))
    if top80_receipt.get("state") != "TOP80_COMPLETE" or top80_receipt.get("count") != 80:
        raise ValueError("Top80 receipt count/state failure")
    verify_output_hashes(top80_receipt, top80_dir)
    assert_subset(top80, ids, "Top80")
    if len(top80) != 80 or top80_receipt.get("exact_cdr3_duplicate_count") != 0:
        raise ValueError("Top80 size/CDR3 duplicate failure")

    final50 = read_tsv(final_dir / "final50_ranked.tsv")
    top10 = read_tsv(final_dir / "top10_priority.tsv")
    final_receipt = json.loads((final_dir / "FINAL50_PREAUDIT.json").read_text(encoding="utf-8"))
    if final_receipt.get("state") != "FINAL50_PREAUDIT_COMPLETE" or final_receipt.get("count") != 50 or final_receipt.get("top10_count") != 10:
        raise ValueError("Final50 receipt count/state failure")
    assert_subset(final50, {row["candidate_id"] for row in top80}, "Final50")
    assert_subset(top10, {row["candidate_id"] for row in final50}, "Top10")
    if len(final50) != 50 or len(top10) != 10:
        raise ValueError("Final50/Top10 size failure")
    if len({row["sequence"] for row in final50}) != 50 or len({row["cdr3"] for row in final50}) != 50:
        raise ValueError("Final50 exact sequence/CDR3 duplicate")
    max_identity = max(
        (direct_cdr3_identity(left["cdr3"], right["cdr3"])
         for index, left in enumerate(final50) for right in final50[index + 1 :]),
        default=0.0,
    )
    if max_identity >= 0.80:
        raise ValueError(f"Final50 direct CDR3 identity too high: {max_identity}")
    if final_receipt.get("md_selected_candidates") != 0 or final_receipt.get("md_completed_candidates") != 0:
        raise ValueError("bridge Final50 must not represent MD as completed evidence")

    old_ids = {row["candidate_id"] for row in old_final}
    final_ids = {row["candidate_id"] for row in final50}
    top80_ids = {row["candidate_id"] for row in top80}
    top10_ids = {row["candidate_id"] for row in top10}
    def cohort_counts(rows: list[dict[str, str]]) -> dict[str, int]:
        return dict(Counter(row["source_cohort"] for row in rows))
    payload = {
        "schema_version": "pvrig.qc397.static_top80_final50_bridge.audit.v2",
        "state": "BRIDGE_AUDIT_COMPLETE",
        "frozen_legacy_final50": {
            "path": str(args.old_frozen_final50),
            "rows": 50,
            "sha256": old_sha,
            "verified_unchanged": True,
        },
        "static_review": {
            "qc397_candidates": 397,
            "qc397_pose_metrics": 794,
            "per_candidate": "one frozen representative pose per 8X6B and 9E6Y",
            "cohort_counts": cohort_counts(unified),
            "method_roles": static_receipt["method_roles"],
            "static_rank_contribution": 0,
        },
        "top80": {
            "count": 80,
            "cohort_counts": cohort_counts(top80),
            "channel_counts": dict(Counter(row["top80_selection_channel"] for row in top80)),
            "generated_top3000_count": sum(row["source_cohort"] == "generated_top3000" for row in top80),
            "legacy_frozen_final50_members_retained": len(top80_ids & old_ids),
            "max_direct_pairwise_cdr3_identity": max(
                (direct_cdr3_identity(left["cdr3"], right["cdr3"])
                 for index, left in enumerate(top80) for right in top80[index + 1 :]), default=0.0),
        },
        "final50": {
            "count": 50,
            "cohort_counts": cohort_counts(final50),
            "channel_counts": dict(Counter(row["final_selection_channel"] for row in final50)),
            "generated_top3000_count": sum(row["source_cohort"] == "generated_top3000" for row in final50),
            "legacy_frozen_final50_members_retained": len(final_ids & old_ids),
            "legacy_frozen_final50_members_replaced": len(old_ids - final_ids),
            "max_direct_pairwise_cdr3_identity": max_identity,
            "md_status": "not run; MD remains descriptive only and does not influence this bridge",
        },
        "top10": {
            "count": 10,
            "cohort_counts": cohort_counts(top10),
            "generated_top3000_count": sum(row["source_cohort"] == "generated_top3000" for row in top10),
            "candidate_ids": [row["candidate_id"] for row in top10],
        },
        "rank_policy": "shared QC397 common4 geometry ordinal only; static Rosetta/PRODIGY are descriptive/weak-prior only and add zero rank contribution",
        "claim_boundary": "This bridge is computational prioritization only. It does not establish experimental binding, affinity/Kd, blocking/IC50, CHO expression, yield or purity.",
        "input_hashes": {
            "qc397_input": sha256_file(unified_dir / "unified_qc397_static_input.tsv"),
            "qc397_metrics": sha256_file(unified_dir / "unified_qc397_static_metrics_794.tsv"),
            "top80": sha256_file(top80_dir / "top80_post_static.tsv"),
            "final50": sha256_file(final_dir / "final50_ranked.tsv"),
            "top10": sha256_file(final_dir / "top10_priority.tsv"),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": payload["state"], "top80_generated": payload["top80"]["generated_top3000_count"], "final50_generated": payload["final50"]["generated_top3000_count"], "top10_generated": payload["top10"]["generated_top3000_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
