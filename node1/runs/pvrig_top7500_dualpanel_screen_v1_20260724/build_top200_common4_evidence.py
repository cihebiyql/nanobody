#!/usr/bin/env python3
"""Build an exact common-four-seed, dual-conformation Top200 evidence panel.

This script deterministically combines route-specific frozen docking results:

* ``old_top7500`` candidates use the original seed 917/1931 rows plus the
  dedicated seed 42/3047 completion rows.
* ``c2_four_seed`` candidates use only the frozen C2 four-seed rows.

It never selects duplicate jobs by docking score.  The output is computational
pose-geometry evidence, not experimental binding or blocking evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any


SEEDS = ("42", "917", "1931", "3047")
CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "COMPLETE", "COMPLETED"}


def load_module(path: Path, name: str) -> ModuleType:
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def bool_text(value: bool) -> str:
    return str(value).lower()


def index_rows(
    rows: list[dict[str, str]], candidate_ids: set[str], source: str
) -> dict[str, dict[tuple[str, str], dict[str, str]]]:
    indexed: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id") or row.get("entity_id") or ""
        if candidate_id not in candidate_ids:
            continue
        seed = str(row.get("seed", "")).strip()
        conformation = str(row.get("conformation", "")).strip().lower()
        if seed not in SEEDS or conformation not in CONFORMATIONS:
            continue
        key = (seed, conformation)
        bucket = indexed.setdefault(candidate_id, {})
        if key in bucket:
            raise ValueError(
                f"duplicate {source} row for {candidate_id} {seed} {conformation}"
            )
        copied = dict(row)
        copied["source_table"] = source
        bucket[key] = copied
    return indexed


def strict_seed_count(rows: list[dict[str, str]], seeds: set[str]) -> int:
    grouped: dict[str, dict[str, bool]] = {}
    for row in rows:
        seed = str(row.get("seed", ""))
        conformation = str(row.get("conformation", "")).lower()
        if seed not in seeds or conformation not in CONFORMATIONS:
            continue
        label = str(row.get("representative_pair_label", "")).upper()
        strict_fraction = optional_float(row.get("model_strict_a_fraction"))
        grouped.setdefault(seed, {})[conformation] = (
            label == "STRICT_A"
            or (strict_fraction is not None and strict_fraction > 0)
        )
    return sum(
        set(values) == set(CONFORMATIONS) and all(values.values())
        for values in grouped.values()
    )


def stability_label(strict_passes: int, broad_passes: int) -> str:
    if strict_passes == 4:
        return "STABLE_STRICT_4_OF_4"
    if strict_passes == 3:
        return "SEED_SENSITIVE_STRICT_3_OF_4"
    if strict_passes == 2:
        return "SEED_SENSITIVE_STRICT_2_OF_4"
    if strict_passes == 1:
        return "HIGH_UNCERTAINTY_STRICT_1_OF_4"
    if broad_passes:
        return "BROAD_SUPPORT_ONLY_0_OF_4_STRICT"
    return "NO_DUAL_CONFORMATION_SUPPORT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top200", type=Path, required=True)
    parser.add_argument("--completion-candidates", type=Path, required=True)
    parser.add_argument("--old-jobs", type=Path, required=True)
    parser.add_argument("--c2-jobs", type=Path, required=True)
    parser.add_argument("--completion-jobs", type=Path, required=True)
    parser.add_argument("--candidate-evidence-module", type=Path, required=True)
    parser.add_argument("--competition-qc-module", type=Path, required=True)
    parser.add_argument("--final50", type=Path)
    parser.add_argument("--top10", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    top200_rows = read_tsv(args.top200)
    completion_candidates = read_tsv(args.completion_candidates)
    if len(top200_rows) != 200 or len(completion_candidates) != 200:
        raise ValueError(
            f"expected 200 Top200 rows, got {len(top200_rows)} and "
            f"{len(completion_candidates)}"
        )
    top200 = {row["candidate_id"]: row for row in top200_rows}
    completion = {row["candidate_id"]: row for row in completion_candidates}
    if set(top200) != set(completion):
        raise ValueError("Top200 and completion candidate ID sets differ")

    candidate_ids = set(top200)
    old = index_rows(read_tsv(args.old_jobs), candidate_ids, "old_frozen")
    c2 = index_rows(read_tsv(args.c2_jobs), candidate_ids, "c2_frozen")
    new_rows = read_tsv(args.completion_jobs)
    if len(new_rows) != 424:
        raise ValueError(f"completion rows {len(new_rows)} != 424")
    new = index_rows(new_rows, candidate_ids, "seed_completion_20260725")

    expected_keys = {(seed, conf) for seed in SEEDS for conf in CONFORMATIONS}
    combined: list[dict[str, str]] = []
    route_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for candidate_id, metadata in sorted(
        completion.items(), key=lambda item: int(item[1]["top200_rank"])
    ):
        route = metadata["route"]
        route_counts[route] += 1
        selected: dict[tuple[str, str], dict[str, str]] = {}
        if route == "old_top7500":
            for key in expected_keys:
                source = new if key[0] in {"42", "3047"} else old
                row = source.get(candidate_id, {}).get(key)
                if row is None:
                    raise ValueError(f"missing {route} row: {candidate_id} {key}")
                selected[key] = row
        elif route == "c2_four_seed":
            for key in expected_keys:
                row = c2.get(candidate_id, {}).get(key)
                if row is None:
                    raise ValueError(f"missing {route} row: {candidate_id} {key}")
                selected[key] = row
        else:
            raise ValueError(f"unsupported route for {candidate_id}: {route}")
        if set(selected) != expected_keys:
            raise AssertionError(f"incomplete selected key set: {candidate_id}")
        for key in sorted(selected, key=lambda item: (int(item[0]), item[1])):
            row = dict(selected[key])
            if str(row.get("state", "")).upper() not in SUCCESS_STATES:
                raise ValueError(f"non-success row selected: {row.get('job_id')}")
            row["top200_rank"] = metadata["top200_rank"]
            row["route"] = route
            source_counts[row["source_table"]] += 1
            combined.append(row)

    if len(combined) != 1600:
        raise ValueError(f"combined jobs {len(combined)} != 1600")
    job_ids = [row["job_id"] for row in combined]
    if len(set(job_ids)) != 1600:
        raise ValueError("combined job IDs are not unique")
    protocol_hashes = {row["protocol_core_sha256"] for row in combined}
    if len(protocol_hashes) != 1:
        raise ValueError(f"protocol core hashes differ: {sorted(protocol_hashes)}")

    evidence_module = load_module(
        args.candidate_evidence_module, "top200_candidate_evidence"
    )
    qc_module = load_module(args.competition_qc_module, "top200_competition_qc")
    seed_by_id = evidence_module.seed_evidence(combined)
    docking_by_id = qc_module.aggregate_docking_rows(combined)

    final50_ids = (
        {row["candidate_id"] for row in read_tsv(args.final50)}
        if args.final50
        else set()
    )
    top10_ids = (
        {row["candidate_id"] for row in read_tsv(args.top10)}
        if args.top10
        else set()
    )

    summary_rows: list[dict[str, Any]] = []
    rows_by_candidate: dict[str, list[dict[str, str]]] = {}
    for row in combined:
        rows_by_candidate.setdefault(row["candidate_id"], []).append(row)
    for candidate_id, original in top200.items():
        seed = seed_by_id[candidate_id]
        docking = docking_by_id[candidate_id]
        strict_passes = int(seed["strict_seed_passes"])
        broad_passes = int(seed["broad_seed_passes"])
        blocking = qc_module.score_blocking(docking)
        robustness = qc_module.score_pose_robustness(docking)
        old_blocking = optional_float(original.get("blocking_consensus_score"))
        old_robustness = optional_float(original.get("pose_robustness_score"))
        candidate_rows = rows_by_candidate[candidate_id]
        pair_counts = Counter(
            str(row.get("representative_pair_label", "")) for row in candidate_rows
        )
        summary_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence": original["sequence"],
                "top200_rank": original["top200_rank"],
                "route": original["route"],
                "in_final50": bool_text(candidate_id in final50_ids),
                "in_top10": bool_text(candidate_id in top10_ids),
                "common4_job_count": seed["job_count"],
                "common4_successful_job_count": seed["successful_job_count"],
                "common4_complete_seed_count": seed["complete_seed_count"],
                "common4_seed_ids": seed["seed_ids"],
                "common4_strict_seed_passes": strict_passes,
                "common4_broad_seed_passes": broad_passes,
                "common4_strict_seed_fraction": f"{strict_passes / 4:.6f}",
                "new_seed_42_3047_strict_passes": strict_seed_count(
                    candidate_rows, {"42", "3047"}
                ),
                "common4_stability_label": stability_label(
                    strict_passes, broad_passes
                ),
                "strict_a_representative_jobs": pair_counts["STRICT_A"],
                "supported_ab_representative_jobs": pair_counts["SUPPORTED_AB"],
                "other_representative_jobs": pair_counts["OTHER"],
                "strict_a_job_fraction": docking.get("strict_a_job_fraction", ""),
                "supported_ab_job_fraction": docking.get(
                    "supported_ab_job_fraction", ""
                ),
                "seed_consistency_fraction": docking.get(
                    "seed_consistency_fraction", ""
                ),
                "pose_pair_consensus_fraction": docking.get(
                    "pose_pair_consensus_fraction", ""
                ),
                "dual_reference_agreement_fraction": docking.get(
                    "dual_reference_agreement_fraction", ""
                ),
                "hotspot_overlap_count": docking.get("hotspot_overlap_count", ""),
                "total_pvrl2_occlusion": docking.get(
                    "total_vhh_pvrl2_residue_pair_occlusion", ""
                ),
                "cdr3_pvrl2_occlusion": docking.get(
                    "cdr3_pvrl2_residue_pair_occlusion", ""
                ),
                "cdr3_occlusion_fraction": docking.get(
                    "cdr3_occlusion_fraction", ""
                ),
                "common4_blocker_class": docking.get("blocker_class", ""),
                "common4_docking_evidence_status": docking.get(
                    "docking_evidence_status", ""
                ),
                "common4_blocking_consensus_score": (
                    f"{blocking:.6f}" if blocking is not None else ""
                ),
                "common4_pose_robustness_score": (
                    f"{robustness:.6f}" if robustness is not None else ""
                ),
                "prior_blocking_consensus_score": (
                    f"{old_blocking:.6f}" if old_blocking is not None else ""
                ),
                "prior_pose_robustness_score": (
                    f"{old_robustness:.6f}" if old_robustness is not None else ""
                ),
                "blocking_score_delta": (
                    f"{blocking - old_blocking:.6f}"
                    if blocking is not None and old_blocking is not None
                    else ""
                ),
                "pose_robustness_delta": (
                    f"{robustness - old_robustness:.6f}"
                    if robustness is not None and old_robustness is not None
                    else ""
                ),
                "claim_boundary": (
                    "common-four-seed dual-conformation computational pose geometry; "
                    "not binding, Kd, IC50, expression, purity, or experimental blocking"
                ),
            }
        )

    summary_rows.sort(
        key=lambda row: (
            -int(row["common4_strict_seed_passes"]),
            -int(row["common4_broad_seed_passes"]),
            -float(row["common4_pose_robustness_score"] or "-inf"),
            -float(row["common4_blocking_consensus_score"] or "-inf"),
            int(row["top200_rank"]),
        )
    )
    for rank, row in enumerate(summary_rows, 1):
        row["common4_docking_diagnostic_rank"] = rank
        row["diagnostic_rank_minus_top200_rank"] = rank - int(row["top200_rank"])
    summary_rows.sort(key=lambda row: int(row["top200_rank"]))

    args.out.mkdir(parents=True, exist_ok=True)
    combined_path = args.out / "TOP200_COMMON4_JOB_RESULTS_1600.tsv"
    summary_path = args.out / "TOP200_COMMON4_CANDIDATE_EVIDENCE_200.tsv"
    write_tsv(combined_path, combined)
    write_tsv(summary_path, summary_rows)

    def distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
        return dict(
            sorted(
                Counter(row["common4_stability_label"] for row in rows).items()
            )
        )

    receipt = {
        "schema_version": "pvrig.top200.common4_evidence.v1",
        "status": "PASS_EXACT_TOP200_COMMON4_PANEL",
        "counts": {
            "candidates": len(summary_rows),
            "jobs": len(combined),
            "success_jobs": sum(
                str(row["state"]).upper() in SUCCESS_STATES for row in combined
            ),
            "unique_job_ids": len(set(job_ids)),
            "seeds_per_candidate": 4,
            "conformations_per_seed": 2,
        },
        "route_counts": dict(sorted(route_counts.items())),
        "source_job_counts": dict(sorted(source_counts.items())),
        "stability_distribution": distribution(summary_rows),
        "old_route_stability_distribution": distribution(
            [row for row in summary_rows if row["route"] == "old_top7500"]
        ),
        "c2_route_stability_distribution": distribution(
            [row for row in summary_rows if row["route"] == "c2_four_seed"]
        ),
        "final50_stability_distribution": distribution(
            [row for row in summary_rows if row["in_final50"] == "true"]
        ),
        "top10_stability_distribution": distribution(
            [row for row in summary_rows if row["in_top10"] == "true"]
        ),
        "protocol_core_sha256": next(iter(protocol_hashes)),
        "input_hashes": {
            str(path): sha256_file(path)
            for path in (
                args.top200,
                args.completion_candidates,
                args.old_jobs,
                args.c2_jobs,
                args.completion_jobs,
                args.candidate_evidence_module,
                args.competition_qc_module,
            )
        },
        "output_hashes": {
            combined_path.name: sha256_file(combined_path),
            summary_path.name: sha256_file(summary_path),
        },
        "claim_boundary": (
            "Computational common-four-seed dual-conformation docking geometry only; "
            "not experimental binding, affinity, IC50, expression, purity, or blocking."
        ),
    }
    receipt_path = args.out / "TOP200_COMMON4_EVIDENCE_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
