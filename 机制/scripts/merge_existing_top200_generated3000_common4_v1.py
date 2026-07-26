#!/usr/bin/env python3
"""Build an auditable, non-destructive common4 merge for PVRIG candidates.

The frozen two-7500 Final50 is intentionally not edited.  This program makes
two *new* computational geometry rankings:

* all complete common4 candidates: current old/new Top200 + generated Top3000;
* QC-eligible subset: current old/new Top200 + generated Top3000 Top200 that
  passed the exact available QC gates.

It never treats docking as experimental binding, affinity, expression, purity,
or blocking evidence.  It also deliberately does not use model/sequence scores
that were calibrated separately in the two source campaigns as a cross-cohort
tie breaker.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EXPECTED_SEEDS = {"42", "917", "1931", "3047"}
EXPECTED_CONFORMATIONS = {"8x6b", "9e6y"}
EXPECTED_PROTOCOL = "8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
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


def number(row: dict[str, str], key: str, default: float = -math.inf) -> float:
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def truth(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "pass"}


def require_unique(rows: list[dict[str, str]], key: str, label: str) -> None:
    values = [row.get(key, "") for row in rows]
    if len(values) != len(set(values)) or not all(values):
        raise ValueError(f"{label}: {key} is missing or non-unique")


def protocol_summary(path: Path, candidate_key: str, require_common4_scope: bool) -> dict[str, Any]:
    rows = read_tsv(path)
    cores = {row.get("protocol_core_sha256", "") for row in rows}
    if cores != {EXPECTED_PROTOCOL}:
        raise ValueError(f"protocol mismatch in {path}: {cores}")
    seeds = {row.get("seed", "") for row in rows}
    conformations = {row.get("conformation", "").lower() for row in rows}
    if require_common4_scope and (
        not EXPECTED_SEEDS.issubset(seeds)
        or not EXPECTED_CONFORMATIONS.issubset(conformations)
    ):
        raise ValueError(f"incomplete seed/conformation scope in {path}")
    ids = {row.get(candidate_key, "") or row.get("entity_id", "") for row in rows}
    return {
        "rows": len(rows),
        "candidate_ids": len(ids - {""}),
        "protocol_core_sha256": sorted(cores),
        "seeds": sorted(seeds),
        "conformations": sorted(conformations),
        "sha256": sha256_file(path),
    }


def normalize_existing(row: dict[str, str], final50_by_id: dict[str, dict[str, str]]) -> dict[str, str]:
    candidate_id = row["candidate_id"]
    if row.get("common4_all_8_jobs_success") != "True":
        raise ValueError(f"existing candidate incomplete common4: {candidate_id}")
    seed_ids = {seed.strip() for seed in row.get("common4_seed_ids", "").split(",") if seed.strip()}
    if seed_ids != EXPECTED_SEEDS:
        raise ValueError(f"existing candidate seed mismatch: {candidate_id} {seed_ids}")
    if row.get("official_validator_pass") != "PASS" or row.get("pass_similarity_filter") != "PASS":
        raise ValueError(f"existing QC gate failed: {candidate_id}")
    if truth(row.get("hard_fail", "")):
        raise ValueError(f"existing hard fail: {candidate_id}")
    return {
        "candidate_id": candidate_id,
        "sequence": row["sequence"],
        "sequence_sha256": row["sequence_sha256"],
        "source_cohort": "existing_old_new7500_top200",
        "source_route": row.get("route", ""),
        "source_panel_membership": row.get("panel_membership", ""),
        "source_rank": row.get("top200_rank", ""),
        "independent_rank": "",
        "qc_eligibility": "PASS_FROZEN_FULL_QC",
        "strict_seed_count": row.get("common4_strict_a_seed_count", ""),
        "broad_seed_count": row.get("common4_broad_dual_reference_seed_count", ""),
        "pose_robustness_score": row.get("common4_pose_robustness_score", ""),
        "blocking_consensus_score": row.get("common4_blocking_consensus_score", ""),
        "seed_consistency_fraction": row.get("common4_seed_consistency_fraction", ""),
        "pose_pair_consensus_fraction": row.get("common4_pose_pair_consensus_fraction", ""),
        "dual_reference_agreement_fraction": row.get("common4_dual_reference_agreement_fraction", ""),
        "cdr3_occlusion_fraction": row.get("common4_cdr3_occlusion_fraction", ""),
        "blocker_class": row.get("common4_blocker_class", ""),
        "current_frozen_final50_rank": final50_by_id.get(candidate_id, {}).get("final_rank", ""),
        "current_frozen_final50_score": final50_by_id.get(candidate_id, {}).get("final_score", ""),
        "source_common4_status": row.get("common4_recomputed_status", ""),
        "dedup_status": "UNIQUE",
    }


def normalize_generated(row: dict[str, str], qc_ids: set[str]) -> dict[str, str]:
    candidate_id = row["candidate_id"]
    if not truth(row.get("common4_complete", "")):
        raise ValueError(f"generated candidate incomplete common4: {candidate_id}")
    if int(number(row, "successful_job_count", -1)) != 8 or int(number(row, "technical_na_jobs", -1)) != 0:
        raise ValueError(f"generated candidate is not 8/8: {candidate_id}")
    seed_ids = {seed.strip() for seed in row.get("seed_ids", "").split(",") if seed.strip()}
    if seed_ids != EXPECTED_SEEDS:
        raise ValueError(f"generated candidate seed mismatch: {candidate_id} {seed_ids}")
    if row.get("hard_fail", "").lower() == "true" or row.get("pass_similarity_filter") != "PASS":
        raise ValueError(f"unexpected generated hard gate failure: {candidate_id}")
    return {
        "candidate_id": candidate_id,
        "sequence": row["sequence"],
        "sequence_sha256": row["sequence_sha256"],
        "source_cohort": "generated_top3000",
        "source_route": row.get("structure_selection_route", ""),
        "source_panel_membership": row.get("structure_selection_lane", ""),
        "source_rank": row.get("provisional_top200_rank", ""),
        "independent_rank": row.get("independent_rank_2985", ""),
        "qc_eligibility": "PASS_INTEGRATED_FULL_QC" if candidate_id in qc_ids else "NOT_YET_FULL_QC",
        "strict_seed_count": row.get("strict_seed_passes", ""),
        "broad_seed_count": row.get("broad_seed_passes", ""),
        "pose_robustness_score": row.get("pose_robustness_score", ""),
        "blocking_consensus_score": row.get("blocking_consensus_score", ""),
        "seed_consistency_fraction": row.get("seed_consistency_fraction", ""),
        "pose_pair_consensus_fraction": row.get("pose_pair_consensus_fraction", ""),
        "dual_reference_agreement_fraction": row.get("dual_reference_agreement_fraction", ""),
        "cdr3_occlusion_fraction": row.get("cdr3_occlusion_fraction", ""),
        "blocker_class": row.get("blocker_class", ""),
        "current_frozen_final50_rank": "",
        "current_frozen_final50_score": "",
        "source_common4_status": row.get("common4_tier", ""),
        "dedup_status": "UNIQUE",
    }


def rank_key(row: dict[str, str]) -> tuple[float | str, ...]:
    # The first six evidence terms are the frozen common4 evidence hierarchy.
    # Do not import source-specific surrogate/model/sequence scores here.
    return (
        -number(row, "strict_seed_count"),
        -number(row, "broad_seed_count"),
        -number(row, "pose_robustness_score"),
        -number(row, "blocking_consensus_score"),
        -number(row, "seed_consistency_fraction"),
        -number(row, "pose_pair_consensus_fraction"),
        -number(row, "dual_reference_agreement_fraction"),
        -number(row, "cdr3_occlusion_fraction"),
        row["sequence_sha256"],
        row["candidate_id"],
    )


def exact_deduplicate(rows: Iterable[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_sequence: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_sequence.setdefault(row["sequence_sha256"], []).append(row)
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for sequence_sha, same in sorted(by_sequence.items()):
        # Preserve the frozen current cohort on an exact duplicate.  Within a
        # source cohort, keep the deterministic best common4 row.
        ordered = sorted(
            same,
            key=lambda r: (
                0 if r["source_cohort"].startswith("existing") else 1,
                rank_key(r),
            ),
        )
        keep = dict(ordered[0])
        keep["dedup_status"] = "UNIQUE" if len(ordered) == 1 else "KEPT_EXACT_SEQUENCE_DUPLICATE"
        kept.append(keep)
        for other in ordered[1:]:
            duplicate = dict(other)
            duplicate["dedup_status"] = "DROPPED_EXACT_SEQUENCE_DUPLICATE"
            duplicate["duplicate_of_candidate_id"] = keep["candidate_id"]
            duplicate["duplicate_sequence_sha256"] = sequence_sha
            dropped.append(duplicate)
    return kept, dropped


def rank(rows: list[dict[str, str]], rank_name: str) -> list[dict[str, str]]:
    ranked = [dict(row) for row in sorted(rows, key=rank_key)]
    for index, row in enumerate(ranked, start=1):
        row[rank_name] = str(index)
        current = row.get("current_frozen_final50_rank", "")
        row[f"{rank_name}_delta_vs_current_final50"] = str(index - int(current)) if current else ""
    return ranked


def top_counts(rows: list[dict[str, str]], cutoffs: tuple[int, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cutoff in cutoffs:
        subset = rows[:cutoff]
        result[str(cutoff)] = {
            "source_cohort": dict(Counter(row["source_cohort"] for row in subset)),
            "routes": dict(Counter(row["source_route"] for row in subset)),
            "current_final50_members": sum(bool(row.get("current_frozen_final50_rank")) for row in subset),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-common4", type=Path, required=True)
    parser.add_argument("--existing-final50", type=Path, required=True)
    parser.add_argument("--generated-ranked", type=Path, required=True)
    parser.add_argument("--generated-qc-eligible", type=Path, required=True)
    parser.add_argument("--generated-jobs", type=Path, required=True)
    parser.add_argument("--existing-c2-jobs", type=Path, required=True)
    parser.add_argument("--existing-old-jobs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    generated_protocol = protocol_summary(args.generated_jobs, "entity_id", True)
    # Historical two-7500 campaign files contain their original seed subsets.
    # The per-candidate frozen common4 table below verifies the actual four-seed
    # bridge used for the existing Top200, so do not reject these source ledgers.
    existing_c2_protocol = protocol_summary(args.existing_c2_jobs, "candidate_id", False)
    existing_old_protocol = protocol_summary(args.existing_old_jobs, "candidate_id", False)

    existing_common4 = read_tsv(args.existing_common4)
    generated = read_tsv(args.generated_ranked)
    generated_qc = read_tsv(args.generated_qc_eligible)
    final50 = read_tsv(args.existing_final50)
    if len(existing_common4) != 200:
        raise ValueError(f"expected frozen existing Top200, observed {len(existing_common4)}")
    if len(generated) != 2985:
        raise ValueError(f"expected generated common4 complete 2985, observed {len(generated)}")
    if len(generated_qc) != 197:
        raise ValueError(f"expected generated integrated QC eligible 197, observed {len(generated_qc)}")
    if len(final50) != 50:
        raise ValueError(f"expected frozen Final50, observed {len(final50)}")
    require_unique(existing_common4, "candidate_id", "existing common4")
    require_unique(generated, "candidate_id", "generated common4")
    require_unique(generated_qc, "candidate_id", "generated QC")
    require_unique(final50, "candidate_id", "frozen Final50")

    final50_by_id = {row["candidate_id"]: row for row in final50}
    generated_qc_ids = {row["candidate_id"] for row in generated_qc}
    if not generated_qc_ids.issubset({row["candidate_id"] for row in generated}):
        raise ValueError("generated QC set is not a subset of the common4 set")
    if not set(final50_by_id).issubset({row["candidate_id"] for row in existing_common4}):
        raise ValueError("frozen Final50 is not a subset of frozen common4 Top200")

    normalized_existing = [normalize_existing(row, final50_by_id) for row in existing_common4]
    normalized_generated = [normalize_generated(row, generated_qc_ids) for row in generated]
    all_rows, all_duplicates = exact_deduplicate(normalized_existing + normalized_generated)
    qc_rows, qc_duplicates = exact_deduplicate(
        normalized_existing
        + [row for row in normalized_generated if row["candidate_id"] in generated_qc_ids]
    )
    ranked_all = rank(all_rows, "merged_common4_geometry_rank")
    ranked_qc = rank(qc_rows, "merged_common4_qc_geometry_rank")
    rank_all_by_id = {row["candidate_id"]: row for row in ranked_all}
    rank_qc_by_id = {row["candidate_id"]: row for row in ranked_qc}

    deltas: list[dict[str, str]] = []
    for old in sorted(final50, key=lambda row: int(row["final_rank"])):
        candidate_id = old["candidate_id"]
        all_row = rank_all_by_id[candidate_id]
        qc_row = rank_qc_by_id[candidate_id]
        deltas.append(
            {
                "candidate_id": candidate_id,
                "current_frozen_final50_rank": old["final_rank"],
                "current_frozen_final50_score": old.get("final_score", ""),
                "merged_common4_geometry_rank": all_row["merged_common4_geometry_rank"],
                "merged_common4_geometry_rank_delta": str(int(all_row["merged_common4_geometry_rank"]) - int(old["final_rank"])),
                "merged_common4_qc_geometry_rank": qc_row["merged_common4_qc_geometry_rank"],
                "merged_common4_qc_geometry_rank_delta": str(int(qc_row["merged_common4_qc_geometry_rank"]) - int(old["final_rank"])),
                "strict_seed_count": qc_row["strict_seed_count"],
                "broad_seed_count": qc_row["broad_seed_count"],
                "pose_robustness_score": qc_row["pose_robustness_score"],
                "blocking_consensus_score": qc_row["blocking_consensus_score"],
                "claim_boundary": "Rank delta is from shared computational common4 geometry only; it does not replace frozen Final50 or predict experimental binding/blocking.",
            }
        )

    out = args.out
    tables = out / "tables"
    reports = out / "reports"
    write_tsv(tables / "combined_common4_complete_3185_geometry_ranked.tsv", ranked_all)
    write_tsv(tables / "combined_common4_qc397_geometry_ranked.tsv", ranked_qc)
    write_tsv(tables / "combined_common4_qc397_top50.tsv", ranked_qc[:50])
    write_tsv(tables / "current_final50_common4_rank_delta.tsv", deltas)
    if all_duplicates:
        write_tsv(tables / "combined_all_exact_sequence_duplicates.tsv", all_duplicates)
    if qc_duplicates:
        write_tsv(tables / "combined_qc_exact_sequence_duplicates.tsv", qc_duplicates)

    receipt = {
        "schema_version": "pvrig.generated3000_existing7500.common4_merge.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "COMPLETE_GEOMETRY_AND_QC_MERGE_NO_FROZEN_RANK_OVERWRITE",
        "protocol_compatibility": {
            "required_protocol_core_sha256": EXPECTED_PROTOCOL,
            "generated": generated_protocol,
            "existing_c2": existing_c2_protocol,
            "existing_old_priority": existing_old_protocol,
            "required_seeds": sorted(EXPECTED_SEEDS),
            "required_conformations": sorted(EXPECTED_CONFORMATIONS),
        },
        "counts": {
            "existing_common4_top200": len(normalized_existing),
            "generated_common4_complete": len(normalized_generated),
            "generated_integrated_qc_eligible": len(generated_qc_ids),
            "all_pool_before_exact_sequence_dedup": len(normalized_existing) + len(normalized_generated),
            "all_pool_after_exact_sequence_dedup": len(ranked_all),
            "qc_pool_before_exact_sequence_dedup": len(normalized_existing) + len(generated_qc_ids),
            "qc_pool_after_exact_sequence_dedup": len(ranked_qc),
            "all_exact_sequence_duplicates_dropped": len(all_duplicates),
            "qc_exact_sequence_duplicates_dropped": len(qc_duplicates),
            "frozen_final50": len(final50),
        },
        "ranking_order": [
            "strict_seed_count DESC",
            "broad_seed_count DESC",
            "pose_robustness_score DESC",
            "blocking_consensus_score DESC",
            "seed_consistency_fraction DESC",
            "pose_pair_consensus_fraction DESC",
            "dual_reference_agreement_fraction DESC",
            "cdr3_occlusion_fraction DESC",
            "sequence_sha256 ASC (deterministic tie break)",
        ],
        "ranking_policy": "source-specific surrogate/model/sequence scores are excluded from cross-cohort ranking; frozen Final50 remains unchanged.",
        "top_counts": {
            "all_complete_common4": top_counts(ranked_all, (10, 50, 80, 200)),
            "qc_eligible": top_counts(ranked_qc, (10, 50, 80, 200)),
        },
        "input_hashes": {
            str(path): sha256_file(path)
            for path in (
                args.existing_common4,
                args.existing_final50,
                args.generated_ranked,
                args.generated_qc_eligible,
                args.generated_jobs,
                args.existing_c2_jobs,
                args.existing_old_jobs,
            )
        },
        "output_hashes": {},
        "claim_boundary": "Computational docking geometry ranking only. It is not experimental evidence for binding, Kd, IC50, expression, purity, specificity, or PVRIG-PVRL2 blocking.",
        "next_required_bridge": "Run the same static-review/selection pipeline for the generated QC-eligible candidates before declaring a replacement competition Final50 or Top10.",
    }
    for path in sorted(tables.glob("*.tsv")):
        receipt["output_hashes"][str(path)] = sha256_file(path)
    (out / "COMBINED_COMMON4_GEOMETRY_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (reports / "README_ZH.md").parent.mkdir(parents=True, exist_ok=True)
    (reports / "README_ZH.md").write_text(
        "# PVRIG 旧/新两批7500 + 生成Top3000：common4 合并榜\n\n"
        "- 冻结的旧 Final50 未被修改。\n"
        "- `combined_common4_complete_3185_geometry_ranked.tsv`：200 条既有 common4 Top200 + 2,985 条生成候选完整 8/8 的合并几何榜。\n"
        "- `combined_common4_qc397_geometry_ranked.tsv`：上述中已有 200 条完整QC + 生成候选中 197 条整合QC合格者的可进入后续静态复核池。\n"
        "- 排序仅使用跨队列一致的 4 seed × 2 构象 docking 几何证据；不使用两路线各自训练/预筛模型分数进行跨队列比较。\n"
        "- 该表不是新的比赛 Final50：新增候选尚未走与旧 Top200 相同的 static-review → Top80 → Final50 选择桥接。\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
