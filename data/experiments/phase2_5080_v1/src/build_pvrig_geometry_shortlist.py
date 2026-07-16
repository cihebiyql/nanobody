#!/usr/bin/env python3
"""Build a fail-closed, geometry-led open FullQC290 PVRIG shortlist.

This is a computational pose-review priority list.  It intentionally does not
make binding, affinity, competition, or experimental-blocking claims.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_MASTER = (
    EXP_DIR / "prepared/pvrig_candidate_evidence_master_v2/candidate_evidence_master.tsv"
)
DEFAULT_OUTDIR = EXP_DIR / "prepared/pvrig_geometry_shortlist_v1"

CLAIM_BOUNDARY = (
    "Computational dual-conformation geometry priority and pose-review routing only; "
    "not binder probability, affinity/Kd, competition, or experimental blocking."
)
DEEPQC_POLICY = (
    "TNP and IgFold/deepQC fields are annotation-only risk-review metadata. "
    "They are not eligibility gates or ranking features, so incomplete deepQC "
    "coverage cannot create pre-screen selection bias."
)
OPEN_GEOMETRY_STATUSES = {
    "OPEN_USABLE",
    "OPEN_AVAILABLE",
    "OPEN_GEOMETRY_AVAILABLE",
    "OPEN_COMPLETE",
    "OPEN_PASS",
    "OPEN_AVAILABLE_V4D_COMPUTATIONAL_GEOMETRY",
}
REQUIRED_FIELDS = {
    "candidate_id", "sequence", "source_cohort", "geometry_status",
    "r_dual_min", "r_dual_gap", "geometry_uncertainty",
    "successful_seeds_8x6b", "successful_seeds_9e6y", "parent_id",
    "target_patch_id", "design_mode", "cdr3_cluster", "full_qc_status",
    "official_validator_pass", "leakage_status", "developability_score",
    "abnativ_vhh_score", "max_positive_cdr_identity", "generic_binding_prior",
    "generic_prior_uncertainty",
}
WEIGHTS = {
    "r_dual_min": 0.70,
    "r_dual_gap_penalty": -0.10,
    "geometry_uncertainty_penalty": -0.08,
    "seed_uncertainty_penalty": -0.05,
    "qc": 0.025,
    "developability": 0.025,
    "naturalness": 0.015,
    "novelty": 0.015,
    # The generic model is explicitly a weak, non-target prior.
    "generic_prior_weak": 0.02,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_master(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        missing = sorted(REQUIRED_FIELDS - set(fields))
        if missing:
            raise ValueError("evidence master missing required fields: " + ", ".join(missing))
        if "v4d_teacher_model_split" not in fields and "model_split" not in fields:
            raise ValueError("evidence master missing V4-D model split field")
        rows = list(reader)
    identifiers = [row["candidate_id"] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("evidence master has duplicate candidate_id values")
    return fields, rows


def as_float(row: dict[str, str], field: str) -> float:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"{row.get('candidate_id', '<unknown>')} missing {field}")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{row.get('candidate_id', '<unknown>')} invalid {field}: {value}") from exc


def is_true(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "pass"}


def open_geometry_usable(status: str) -> bool:
    normalized = status.strip().upper()
    return normalized in OPEN_GEOMETRY_STATUSES or (
        normalized.startswith("OPEN_")
        and any(token in normalized for token in ("USABLE", "AVAILABLE", "COMPLETE", "PASS"))
        and "SEALED" not in normalized
    )


def model_split(row: dict[str, str]) -> str:
    return (row.get("v4d_teacher_model_split") or row.get("model_split") or "").strip().upper()


def is_fullqc_open_row(row: dict[str, str]) -> bool:
    """Apply cohort/split/state gates before examining ranking features."""
    split = model_split(row)
    return (
        row["source_cohort"].strip().upper() == "FULLQC290_PRIMARY"
        and "SEALED" not in split
        and "TEST" not in split
        and open_geometry_usable(row["geometry_status"])
        and row["full_qc_status"].strip().upper().startswith("COMPLETE_HARD_PASS")
        and is_true(row["official_validator_pass"])
        and row["leakage_status"].strip().upper() not in {"", "KNOWN_POSITIVE", "LEAKAGE", "FAIL"}
    )


def eligible_rows(rows: list[dict[str, str]], seed_count: int) -> tuple[list[dict[str, str]], Counter[str]]:
    exclusions: Counter[str] = Counter()
    accepted: list[dict[str, str]] = []
    for row in rows:
        if row["source_cohort"].strip().upper() != "FULLQC290_PRIMARY":
            exclusions["NON_FULLQC290"] += 1
            continue
        split = model_split(row)
        if "SEALED" in split or "TEST" in split:
            exclusions["SEALED_OR_TEST_SPLIT"] += 1
            continue
        if not open_geometry_usable(row["geometry_status"]):
            exclusions["GEOMETRY_NOT_OPEN_USABLE"] += 1
            continue
        if not is_fullqc_open_row(row):
            exclusions["QC_OR_LEAKAGE_GATE"] += 1
            continue
        # Missing or malformed geometry is never imputed for a geometry-led rank.
        for field in (
            "r_dual_min", "r_dual_gap", "geometry_uncertainty",
            "successful_seeds_8x6b", "successful_seeds_9e6y",
        ):
            as_float(row, field)
        minimum_success = min(
            as_float(row, "successful_seeds_8x6b"),
            as_float(row, "successful_seeds_9e6y"),
        )
        if minimum_success < 2:
            exclusions["INSUFFICIENT_SUCCESSFUL_SEEDS"] += 1
            continue
        if seed_count <= 0:
            raise ValueError("seed_count must be positive")
        accepted.append(dict(row))
    return accepted, exclusions


def percentiles(rows: list[dict[str, str]], field: str, reverse: bool = False) -> dict[str, float]:
    ordered = sorted((as_float(row, field), row["candidate_id"]) for row in rows)
    denominator = max(len(ordered) - 1, 1)
    scores: dict[str, float] = {}
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][0] == ordered[start][0]:
            end += 1
        midrank = ((start + end - 1) / 2.0) / denominator
        for _value, candidate_id in ordered[start:end]:
            scores[candidate_id] = midrank
        start = end
    return {key: 1.0 - value for key, value in scores.items()} if reverse else scores


def add_scores(rows: list[dict[str, str]], seed_count: int) -> None:
    derived = []
    for row in rows:
        minimum_success = min(
            as_float(row, "successful_seeds_8x6b"), as_float(row, "successful_seeds_9e6y")
        )
        row["seed_uncertainty"] = f"{max(0.0, 1.0 - minimum_success / seed_count):.9f}"
        # QC is a gated auxiliary tie-breaker, not a substitute for geometry.
        row["qc_auxiliary"] = "1.0"
        derived.append(row)
    pct = {
        "r_dual_min": percentiles(derived, "r_dual_min"),
        "r_dual_gap": percentiles(derived, "r_dual_gap"),
        "geometry_uncertainty": percentiles(derived, "geometry_uncertainty"),
        "seed_uncertainty": percentiles(derived, "seed_uncertainty"),
        "developability": percentiles(derived, "developability_score"),
        "naturalness": percentiles(derived, "abnativ_vhh_score"),
        "novelty": percentiles(derived, "max_positive_cdr_identity", reverse=True),
        "generic": percentiles(derived, "generic_binding_prior"),
    }
    for row in derived:
        candidate_id = row["candidate_id"]
        score = (
            WEIGHTS["r_dual_min"] * pct["r_dual_min"][candidate_id]
            + WEIGHTS["r_dual_gap_penalty"] * pct["r_dual_gap"][candidate_id]
            + WEIGHTS["geometry_uncertainty_penalty"] * pct["geometry_uncertainty"][candidate_id]
            + WEIGHTS["seed_uncertainty_penalty"] * pct["seed_uncertainty"][candidate_id]
            + WEIGHTS["qc"]
            + WEIGHTS["developability"] * pct["developability"][candidate_id]
            + WEIGHTS["naturalness"] * pct["naturalness"][candidate_id]
            + WEIGHTS["novelty"] * pct["novelty"][candidate_id]
            + WEIGHTS["generic_prior_weak"] * pct["generic"][candidate_id]
        )
        row.update({
            "pct_r_dual_min": f"{pct['r_dual_min'][candidate_id]:.9f}",
            "pct_r_dual_gap": f"{pct['r_dual_gap'][candidate_id]:.9f}",
            "pct_geometry_uncertainty": f"{pct['geometry_uncertainty'][candidate_id]:.9f}",
            "pct_seed_uncertainty": f"{pct['seed_uncertainty'][candidate_id]:.9f}",
            "geometry_rank_score": f"{score:.9f}",
            "generic_prior_role": "WEAK_PRIOR_WEIGHT_0.02",
            "deepqc_policy": DEEPQC_POLICY,
            "ranking_claim_boundary": CLAIM_BOUNDARY,
        })


def select_diverse(
    rows: list[dict[str, str]], target_count: int, parent_cap: int,
    parent_patch_mode_cap: int, cdr3_cluster_cap: int,
) -> list[dict[str, str]]:
    counts: Counter[tuple[str, ...]] = Counter()
    selected: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: (-float(item["geometry_rank_score"]), item["candidate_id"])):
        parent = row["parent_id"]
        combo = (parent, row["target_patch_id"], row["design_mode"])
        cluster = row["cdr3_cluster"]
        if not parent or not all(combo[1:]) or not cluster:
            raise ValueError(f"{row['candidate_id']} lacks diversity metadata")
        if (
            counts[("parent", parent)] >= parent_cap
            or counts[("combo",) + combo] >= parent_patch_mode_cap
            or counts[("cdr3", cluster)] >= cdr3_cluster_cap
        ):
            continue
        chosen = dict(row)
        chosen["rank"] = str(len(selected) + 1)
        chosen["selection_reason"] = "R_DUAL_MIN_PRIMARY_GEOMETRY_WITH_DIVERSITY_CAPS"
        selected.append(chosen)
        counts[("parent", parent)] += 1
        counts[("combo",) + combo] += 1
        counts[("cdr3", cluster)] += 1
        if len(selected) == target_count:
            return selected
    raise RuntimeError(
        f"fail-closed: only {len(selected)} candidates meet diversity caps; need {target_count}"
    )


def bundle_value(row: dict[str, str], conformation: str) -> tuple[str, str]:
    suffix = conformation.lower()
    for field in (f"pose_bundle_{suffix}", f"job_bundle_{suffix}", f"sync_key_{suffix}"):
        if row.get(field, "").strip():
            return "AVAILABLE", row[field].strip()
    return "PENDING_SYNC", f"PVRIG_GEOMETRY_REVIEW::{row['candidate_id']}::{conformation}"


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']} rank={row['rank']} geometry_score={row['geometry_rank_score']}\n")
            handle.write(f"{row['sequence']}\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--expected-open-count", type=int, default=258,
                        help="Exact expected eligible open count; set 0 to disable exact-count lock.")
    parser.add_argument("--expected-sealed-count", type=int, default=32,
                        help="Exact FullQC290 SEALED/TEST count; set 0 to disable this lock.")
    parser.add_argument("--shortlist-size", type=int, default=50)
    parser.add_argument("--pose-review-size", type=int, default=20)
    parser.add_argument("--seed-count-per-conformation", type=int, default=3)
    parser.add_argument("--parent-cap", type=int, default=3)
    parser.add_argument("--parent-patch-mode-cap", type=int, default=2)
    parser.add_argument("--cdr3-cluster-cap", type=int, default=2)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.pose_review_size > args.shortlist_size:
        raise ValueError("pose_review_size cannot exceed shortlist_size")
    if args.shortlist_size <= 0 or args.pose_review_size <= 0:
        raise ValueError("shortlist_size and pose_review_size must be positive")
    fields, rows = read_master(args.master)
    sealed_fullqc_count = sum(
        row["source_cohort"].strip().upper() == "FULLQC290_PRIMARY"
        and ("SEALED" in model_split(row) or "TEST" in model_split(row))
        for row in rows
    )
    if args.expected_sealed_count and sealed_fullqc_count != args.expected_sealed_count:
        raise RuntimeError(
            f"fail-closed: expected {args.expected_sealed_count} FullQC290 SEALED/TEST rows, "
            f"found {sealed_fullqc_count}"
        )
    eligible, exclusions = eligible_rows(rows, args.seed_count_per_conformation)
    if args.expected_open_count and len(eligible) != args.expected_open_count:
        raise RuntimeError(
            f"fail-closed: expected {args.expected_open_count} open eligible rows, found {len(eligible)}"
        )
    if len(eligible) < args.shortlist_size:
        raise RuntimeError(f"fail-closed: only {len(eligible)} open eligible rows, need {args.shortlist_size}")
    add_scores(eligible, args.seed_count_per_conformation)
    ranked = sorted(eligible, key=lambda item: (-float(item["geometry_rank_score"]), item["candidate_id"]))
    for index, row in enumerate(ranked, start=1):
        row["open_rank"] = str(index)
    shortlist = select_diverse(
        ranked, args.shortlist_size, args.parent_cap,
        args.parent_patch_mode_cap, args.cdr3_cluster_cap,
    )
    pose_rows: list[dict[str, str]] = []
    for row in shortlist[:args.pose_review_size]:
        for conformation in ("8X6B", "9E6Y"):
            bundle_status, sync_key = bundle_value(row, conformation)
            pose_rows.append({
                "candidate_id": row["candidate_id"], "rank": row["rank"],
                "conformation": conformation, "job_or_pose_bundle_status": bundle_status,
                "job_or_pose_bundle_or_sync_key": sync_key,
                "geometry_status": row["geometry_status"], "claim_boundary": CLAIM_BOUNDARY,
            })
    args.outdir.mkdir(parents=True, exist_ok=True)
    rank_fields = fields + [
        "seed_uncertainty", "qc_auxiliary", "pct_r_dual_min", "pct_r_dual_gap",
        "pct_geometry_uncertainty", "pct_seed_uncertainty", "geometry_rank_score",
        "generic_prior_role", "deepqc_policy", "ranking_claim_boundary", "open_rank",
    ]
    shortlist_fields = rank_fields + ["rank", "selection_reason"]
    outputs = {
        "ranked_open258": args.outdir / "ranked_open258.tsv",
        "shortlist50": args.outdir / "shortlist50.tsv",
        "shortlist50_fasta": args.outdir / "shortlist50.fasta",
        "top20_pose_review_manifest": args.outdir / "top20_pose_review_manifest.tsv",
        "config": args.outdir / "geometry_shortlist_config.json",
        "audit": args.outdir / "geometry_shortlist_audit.json",
    }
    write_tsv(outputs["ranked_open258"], ranked, rank_fields)
    write_tsv(outputs["shortlist50"], shortlist, shortlist_fields)
    write_fasta(outputs["shortlist50_fasta"], shortlist)
    write_tsv(outputs["top20_pose_review_manifest"], pose_rows, list(pose_rows[0]))
    config = {
        "schema_version": "pvrig_geometry_shortlist_v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "input": {"path": str(args.master.resolve()), "sha256": sha256_file(args.master)},
        "open_geometry_statuses": sorted(OPEN_GEOMETRY_STATUSES), "weights": WEIGHTS,
        "generic_prior": "WEAK_PRIOR_WEIGHT_0.02_LE_0.05",
        "deepqc_policy": DEEPQC_POLICY,
        "diversity_caps": {"parent": args.parent_cap, "parent_patch_mode": args.parent_patch_mode_cap,
                           "cdr3_cluster": args.cdr3_cluster_cap},
        "seed_count_per_conformation": args.seed_count_per_conformation,
    }
    audit = {
        "schema_version": "pvrig_geometry_shortlist_audit_v1", "status": "PASS_OPEN_GEOMETRY_SHORTLIST",
        "claim_boundary": CLAIM_BOUNDARY, "input_rows": len(rows), "eligible_open_rows": len(eligible),
        "deepqc_policy": DEEPQC_POLICY,
        "expected_open_count": args.expected_open_count, "expected_sealed_count": args.expected_sealed_count,
        "sealed_fullqc_excluded_count": sealed_fullqc_count, "exclusions": dict(sorted(exclusions.items())),
        "shortlist_count": len(shortlist), "pose_review_candidate_count": args.pose_review_size,
        "pose_review_manifest_rows": len(pose_rows), "outputs": {key: str(value.resolve()) for key, value in outputs.items()},
        "output_sha256": {
            "ranked_open258": sha256_file(outputs["ranked_open258"]),
            "shortlist50": sha256_file(outputs["shortlist50"]),
            "shortlist50_fasta": sha256_file(outputs["shortlist50_fasta"]),
            "top20_pose_review_manifest": sha256_file(outputs["top20_pose_review_manifest"]),
        },
        "shortlist_parent_max": max(Counter(row["parent_id"] for row in shortlist).values()),
        "shortlist_parent_patch_mode_max": max(Counter((row["parent_id"], row["target_patch_id"], row["design_mode"]) for row in shortlist).values()),
        "shortlist_cdr3_cluster_max": max(Counter(row["cdr3_cluster"] for row in shortlist).values()),
    }
    outputs["config"].write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outputs["audit"].write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    audit = run(args)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
