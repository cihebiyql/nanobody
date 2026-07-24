#!/usr/bin/env python3
"""Dry-run PVRIG finalist screening standard v1 on the frozen 6,042 set."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


DEFAULT_OLD_DOCKING = Path(
    "/mnt/d/work/抗体/node1/reports/pvrig_top7500_mechanism_count_20260724/"
    "old_top7500_candidate_summary.tsv"
)
DEFAULT_C2_DOCKING = Path(
    "/mnt/d/work/抗体/node1/reports/pvrig_top7500_mechanism_count_20260724/"
    "c2_new4220_four_seed_candidate_summary.tsv"
)
DEFAULT_MULTIMETRIC = Path(
    "/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/"
    "pvrig_1m_fixed_pose_top150k_multimetric_v2_20260722/"
    "fixed_pose_top150k_multimetric.tsv.gz"
)
DEFAULT_SURROGATE = Path(__file__).resolve().parent / "surrogate_high_support_snapshot.tsv"
DEFAULT_OUT = Path(__file__).resolve().parent / "dry_run"

BINDING_WEAK_PRIOR_MIN = 0.6783883333333334


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def as_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return math.nan


def as_int(row: dict[str, str], key: str) -> int:
    try:
        return int(row[key])
    except (KeyError, TypeError, ValueError):
        return -1


def percentile_higher_is_better(values: dict[str, float]) -> dict[str, float]:
    """Return average-rank percentiles in [0,1], with ties sharing a rank."""
    finite = sorted((value, key) for key, value in values.items() if math.isfinite(value))
    if not finite:
        return {}
    result: dict[str, float] = {}
    denominator = max(1, len(finite) - 1)
    index = 0
    while index < len(finite):
        end = index + 1
        while end < len(finite) and finite[end][0] == finite[index][0]:
            end += 1
        average_position = (index + end - 1) / 2
        percentile = average_position / denominator
        for _, key in finite[index:end]:
            result[key] = percentile
        index = end
    return result


def developability_pass(row: dict[str, str]) -> bool:
    return all(
        [
            row.get("tnp_status") == "PASS",
            row.get("tnp_review_tier") == "CLEAR",
            as_int(row, "tnp_red_flag_count") == 0,
            row.get("abnativ_status") == "PASS",
            as_float(row, "AbNatiV VHH Score") >= 0.70,
            as_float(row, "mean_self_probability") >= 0.70,
            as_float(row, "expression_purity_risk_proxy_partial") >= 85.0,
            as_int(row, "cys_count") == 2,
            as_int(row, "nglyc_motif_count") == 0,
            as_int(row, "hydrophobic_5_count") == 0,
            as_float(row, "max_positive_cdr_identity") <= 0.75,
            row.get("anarci_qc_status") == "PASS",
            row.get("nbb2_status") == "SUCCESS",
            row.get("nbb2_pdb_sequence_match", "").lower() == "true",
        ]
    )


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty output: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def cdr3_clusters(
    rows: list[dict[str, object]], identity_threshold: float = 0.80
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Cluster same-length CDR3s by single-linkage Hamming identity."""
    parent = {str(row["candidate_id"]): str(row["candidate_id"]) for row in rows}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        keep, merge = sorted((left_root, right_root))
        parent[merge] = keep

    by_length: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        by_length.setdefault(int(row["cdr3_length"]), []).append(row)
    for length_rows in by_length.values():
        for left_index, left in enumerate(length_rows):
            left_cdr3 = str(left["cdr3"])
            for right in length_rows[left_index + 1 :]:
                right_cdr3 = str(right["cdr3"])
                matches = sum(
                    left_residue == right_residue
                    for left_residue, right_residue in zip(left_cdr3, right_cdr3)
                )
                if matches / len(left_cdr3) >= identity_threshold:
                    union(
                        str(left["candidate_id"]),
                        str(right["candidate_id"]),
                    )

    members: dict[str, list[str]] = {}
    for candidate_id in parent:
        members.setdefault(find(candidate_id), []).append(candidate_id)
    ordered_roots = sorted(
        members,
        key=lambda root: (-len(members[root]), min(members[root])),
    )
    cluster_id = {
        root: f"CDR3CL_{index:04d}"
        for index, root in enumerate(ordered_roots, start=1)
    }
    by_candidate = {str(row["candidate_id"]): row for row in rows}
    output = []
    for root in ordered_roots:
        for candidate_id in sorted(members[root]):
            row = by_candidate[candidate_id]
            output.append(
                {
                    "candidate_id": candidate_id,
                    "cdr3": row["cdr3"],
                    "cdr3_length": row["cdr3_length"],
                    "cdr3_cluster_id": cluster_id[root],
                    "cdr3_cluster_size": len(members[root]),
                    "same_length_identity_threshold": identity_threshold,
                }
            )
    exact_counts = Counter(str(row["cdr3"]) for row in rows)
    summary = {
        "cluster_count": len(members),
        "largest_cluster_size": max(map(len, members.values()), default=0),
        "multi_member_cluster_count": sum(
            len(cluster_members) > 1 for cluster_members in members.values()
        ),
        "exact_cdr3_duplicate_group_count": sum(
            count > 1 for count in exact_counts.values()
        ),
        "exact_cdr3_duplicate_candidate_count": sum(
            count for count in exact_counts.values() if count > 1
        ),
    }
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-docking", type=Path, default=DEFAULT_OLD_DOCKING)
    parser.add_argument("--c2-docking", type=Path, default=DEFAULT_C2_DOCKING)
    parser.add_argument("--multimetric", type=Path, default=DEFAULT_MULTIMETRIC)
    parser.add_argument("--surrogate", type=Path, default=DEFAULT_SURROGATE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    old_rows = read_tsv(args.old_docking)
    c2_rows = read_tsv(args.c2_docking)
    surrogate_rows = read_tsv(args.surrogate)

    old_strict_rows = {
        row["candidate_id"]: row
        for row in old_rows
        if row["stage3_two_seed_dual_conformation_strict"] == "True"
        and as_int(row, "complete_seed_count") >= 2
        and as_int(row, "strict_seed_passes") >= 2
    }
    c2_strict_rows = {
        row["candidate_id"]: row
        for row in c2_rows
        if as_int(row, "complete_seed_count_total") == 4
        and as_int(row, "strict_seed_passes_total") == 4
    }
    if set(old_strict_rows) & set(c2_strict_rows):
        raise ValueError("old and C2 strict sets are expected to be disjoint")
    strict_ids = set(old_strict_rows) | set(c2_strict_rows)

    surrogate = {
        (row["route"], row["candidate_id"]): row for row in surrogate_rows
    }
    multimetric: dict[str, dict[str, str]] = {}
    with gzip.open(args.multimetric, "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["candidate_id"] in strict_ids:
                multimetric[row["candidate_id"]] = row
    missing_multimetric = sorted(strict_ids - set(multimetric))
    if missing_multimetric:
        raise ValueError(
            f"{len(missing_multimetric)} strict candidates lack multimetric rows"
        )

    candidate_rows: list[dict[str, object]] = []
    for candidate_id in sorted(strict_ids):
        route = "old_top7500" if candidate_id in old_strict_rows else "c2_four_seed"
        docking = (
            old_strict_rows[candidate_id]
            if route == "old_top7500"
            else c2_strict_rows[candidate_id]
        )
        metric = multimetric[candidate_id]
        support = surrogate.get((route, candidate_id))
        development = developability_pass(metric)
        binding = (
            as_float(metric, "binding_consensus_weak_prior")
            >= BINDING_WEAK_PRIOR_MIN
        )
        high_support = support is not None
        strict_seed_count = (
            as_int(docking, "strict_seed_passes")
            if route == "old_top7500"
            else as_int(docking, "strict_seed_passes_total")
        )
        expected_seed_count = (
            as_int(docking, "complete_seed_count")
            if route == "old_top7500"
            else 4
        )
        core = development and binding and high_support
        stage = (
            "CORE_A"
            if core
            else "DEV_BINDING"
            if development and binding
            else "DEV_SURROGATE"
            if development and high_support
            else "DEV_ONLY"
            if development
            else "STRICT_DOCKING_ONLY"
        )
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "route": route,
                "sequence": metric["sequence"],
                "sequence_sha256": metric["sequence_sha256"],
                "parent_id": metric["parent_id"],
                "parent_cluster": metric["parent_cluster"],
                "cdr1": metric["anarci_cdr1"],
                "cdr2": metric["anarci_cdr2"],
                "cdr3": metric["anarci_cdr3"],
                "cdr3_length": len(metric["anarci_cdr3"]),
                "strict_seed_passes": strict_seed_count,
                "expected_seed_count": expected_seed_count,
                "strict_seed_fraction": strict_seed_count / expected_seed_count,
                "developability_hardpass": str(development).lower(),
                "binding_weak_prior_high": str(binding).lower(),
                "surrogate_high_support": str(high_support).lower(),
                "max_positive_cdr_identity": metric["max_positive_cdr_identity"],
                "tnp_review_tier": metric["tnp_review_tier"],
                "abnativ_vhh_score": metric["AbNatiV VHH Score"],
                "sapiens_mean_self_probability": metric["mean_self_probability"],
                "expression_purity_risk_proxy": metric[
                    "expression_purity_risk_proxy_partial"
                ],
                "developability_risk_proxy": metric[
                    "developability_risk_proxy_partial"
                ],
                "binding_consensus_weak_prior": metric[
                    "binding_consensus_weak_prior"
                ],
                "surrogate_support_label": (
                    support["surrogate_support_label"] if support else ""
                ),
                "surrogate_utility": support["surrogate_utility"] if support else "",
                "surrogate_source_rank": (
                    support["surrogate_source_rank"] if support else ""
                ),
                "dry_run_stage": stage,
            }
        )

    by_id = {str(row["candidate_id"]): row for row in candidate_rows}
    binding_rank = percentile_higher_is_better(
        {
            candidate_id: float(row["binding_consensus_weak_prior"])
            for candidate_id, row in by_id.items()
        }
    )
    expression_rank = percentile_higher_is_better(
        {
            candidate_id: float(row["expression_purity_risk_proxy"])
            for candidate_id, row in by_id.items()
        }
    )
    developability_rank = percentile_higher_is_better(
        {
            candidate_id: (
                float(row["developability_risk_proxy"])
                + 100 * float(row["abnativ_vhh_score"])
                + 100 * float(row["sapiens_mean_self_probability"])
            )
            / 3
            for candidate_id, row in by_id.items()
        }
    )
    mechanism_rank: dict[str, float] = {}
    for route in ("old_top7500", "c2_four_seed"):
        route_values = {
            candidate_id: float(row["surrogate_utility"])
            for candidate_id, row in by_id.items()
            if row["route"] == route and row["surrogate_utility"] != ""
        }
        mechanism_rank.update(percentile_higher_is_better(route_values))

    for candidate_id, row in by_id.items():
        row["binding_rank_percentile"] = f"{binding_rank[candidate_id]:.9f}"
        row["expression_rank_percentile"] = f"{expression_rank[candidate_id]:.9f}"
        row["developability_rank_percentile"] = (
            f"{developability_rank[candidate_id]:.9f}"
        )
        row["mechanism_rank_percentile_within_route"] = (
            f"{mechanism_rank[candidate_id]:.9f}"
            if candidate_id in mechanism_rank
            else ""
        )
        initial = (
            0.70 * binding_rank[candidate_id]
            + 0.20 * expression_rank[candidate_id]
            + 0.10 * developability_rank[candidate_id]
        )
        row["initial_survival_proxy"] = f"{initial:.9f}"
        if candidate_id in mechanism_rank:
            rescreen = (
                0.50 * binding_rank[candidate_id]
                + 0.50 * mechanism_rank[candidate_id]
            )
            row["rescreen_competition_proxy"] = f"{rescreen:.9f}"
        else:
            row["rescreen_competition_proxy"] = ""
        row["proxy_semantics"] = (
            "rank-only computational proxies; not BLI response, expression "
            "yield, purity, Kd, IC50, or experimental blocking"
        )

    core_rows = [row for row in candidate_rows if row["dry_run_stage"] == "CORE_A"]
    write_tsv(args.out / "strict6042_standard_dry_run.tsv", candidate_rows)
    write_tsv(args.out / "core448_candidates.tsv", core_rows)
    cluster_rows, cluster_summary = cdr3_clusters(core_rows)
    write_tsv(args.out / "core448_cdr3_clusters.tsv", cluster_rows)

    funnel_rows = []
    for route, expected_strict in (("old_top7500", 1923), ("c2_four_seed", 4119)):
        route_rows = [row for row in candidate_rows if row["route"] == route]
        counts = {
            "route": route,
            "strict_docking": len(route_rows),
            "developability_hardpass": sum(
                row["developability_hardpass"] == "true" for row in route_rows
            ),
            "binding_weak_prior_high": sum(
                row["binding_weak_prior_high"] == "true" for row in route_rows
            ),
            "surrogate_high_support": sum(
                row["surrogate_high_support"] == "true" for row in route_rows
            ),
            "core_intersection": sum(
                row["dry_run_stage"] == "CORE_A" for row in route_rows
            ),
        }
        if counts["strict_docking"] != expected_strict:
            raise ValueError(f"strict count drift for {route}: {counts}")
        funnel_rows.append(counts)
    funnel_rows.append(
        {
            key: (
                "total"
                if key == "route"
                else sum(int(row[key]) for row in funnel_rows)
            )
            for key in funnel_rows[0]
        }
    )
    write_tsv(args.out / "funnel_counts.tsv", funnel_rows)

    expected_funnel = {
        "old_top7500": {
            "strict_docking": 1923,
            "developability_hardpass": 1837,
            "binding_weak_prior_high": 1036,
            "surrogate_high_support": 127,
            "core_intersection": 103,
        },
        "c2_four_seed": {
            "strict_docking": 4119,
            "developability_hardpass": 3139,
            "binding_weak_prior_high": 976,
            "surrogate_high_support": 2498,
            "core_intersection": 345,
        },
    }
    observed_funnel = {
        str(row["route"]): {
            key: int(row[key])
            for key in expected_funnel[str(row["route"])]
        }
        for row in funnel_rows[:-1]
    }
    if observed_funnel != expected_funnel:
        raise ValueError(
            f"frozen funnel regression: expected={expected_funnel}, "
            f"observed={observed_funnel}"
        )

    receipt = {
        "status": "PASS",
        "standard": "pvrig.finalist_screening.v1.20260724",
        "strict_candidate_count": len(candidate_rows),
        "core_candidate_count": len(core_rows),
        "strict_sets_disjoint": True,
        "multimetric_join_missing": 0,
        "core_parent_counts": Counter(
            str(row["parent_cluster"]) for row in core_rows
        ),
        "core_cdr3_diversity": cluster_summary,
        "input_hashes": {
            str(args.old_docking): sha256(args.old_docking),
            str(args.c2_docking): sha256(args.c2_docking),
            str(args.multimetric): sha256(args.multimetric),
            str(args.surrogate): sha256(args.surrogate),
        },
        "output_hashes": {
            "strict6042_standard_dry_run.tsv": sha256(
                args.out / "strict6042_standard_dry_run.tsv"
            ),
            "core448_candidates.tsv": sha256(args.out / "core448_candidates.tsv"),
            "core448_cdr3_clusters.tsv": sha256(
                args.out / "core448_cdr3_clusters.tsv"
            ),
            "funnel_counts.tsv": sha256(args.out / "funnel_counts.tsv"),
        },
        "boundary": (
            "Dry-run reproduces internal computational gates only. Official "
            "validator, full known-positive similarity audit and wet-lab "
            "BLI/expression/purity/Kd/IC50 remain separate."
        ),
    }
    (args.out / "DRY_RUN_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, default=dict) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, default=dict))


if __name__ == "__main__":
    main()
