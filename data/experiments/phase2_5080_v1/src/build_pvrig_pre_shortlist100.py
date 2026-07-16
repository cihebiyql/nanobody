#!/usr/bin/env python3
"""Build a QC/diversity-first 100-candidate pre-shortlist before V4-D geometry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_MASTER = EXP_DIR / "prepared/pvrig_candidate_evidence_master_v1/candidate_evidence_master.tsv"
DEFAULT_OUT = EXP_DIR / "prepared/pvrig_portfolio_pre_shortlist100_v1"

TARGET_COUNT = 100
EXPLOIT_COUNT = 82
EXPLORE_COUNT = 18
PARENT_CAP = 4
PARENT_PATCH_MODE_CAP = 2
CDR3_CLUSTER_CAP = 2
PATCH_CAP = 40

EXPLOIT_WEIGHTS = {
    "developability": 0.25,
    "expression_purity": 0.25,
    "abnativ": 0.20,
    "novelty": 0.15,
    "generic_prior": 0.10,
    "inverse_generic_uncertainty": 0.05,
}
EXPLORE_WEIGHTS = {
    "developability": 0.45,
    "expression_purity": 0.25,
    "abnativ": 0.10,
    "novelty": 0.10,
    "generic_uncertainty": 0.10,
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
        if not reader.fieldnames:
            raise ValueError("evidence master has no header")
        return list(reader.fieldnames), list(reader)


def percentiles(rows: list[dict[str, str]], field: str, reverse: bool = False) -> dict[str, float]:
    ordered = sorted((float(row[field]), row["candidate_id"]) for row in rows)
    denominator = max(len(ordered) - 1, 1)
    result = {candidate_id: index / denominator for index, (_value, candidate_id) in enumerate(ordered)}
    return {key: 1.0 - value for key, value in result.items()} if reverse else result


def add_scores(rows: list[dict[str, str]]) -> None:
    pct = {
        "developability": percentiles(rows, "developability_score"),
        "expression_purity": percentiles(rows, "expression_purity_risk_score"),
        "abnativ": percentiles(rows, "abnativ_vhh_score"),
        "novelty": percentiles(rows, "max_positive_cdr_identity", reverse=True),
        "generic_prior": percentiles(rows, "generic_binding_prior"),
        "generic_uncertainty": percentiles(rows, "generic_prior_uncertainty"),
    }
    for row in rows:
        candidate_id = row["candidate_id"]
        row["pct_developability"] = f"{pct['developability'][candidate_id]:.9f}"
        row["pct_expression_purity"] = f"{pct['expression_purity'][candidate_id]:.9f}"
        row["pct_abnativ"] = f"{pct['abnativ'][candidate_id]:.9f}"
        row["pct_novelty"] = f"{pct['novelty'][candidate_id]:.9f}"
        row["pct_generic_prior"] = f"{pct['generic_prior'][candidate_id]:.9f}"
        row["pct_generic_uncertainty"] = f"{pct['generic_uncertainty'][candidate_id]:.9f}"
        exploit_score = sum([
            EXPLOIT_WEIGHTS['developability'] * pct['developability'][candidate_id],
            EXPLOIT_WEIGHTS['expression_purity'] * pct['expression_purity'][candidate_id],
            EXPLOIT_WEIGHTS['abnativ'] * pct['abnativ'][candidate_id],
            EXPLOIT_WEIGHTS['novelty'] * pct['novelty'][candidate_id],
            EXPLOIT_WEIGHTS['generic_prior'] * pct['generic_prior'][candidate_id],
            EXPLOIT_WEIGHTS['inverse_generic_uncertainty'] * (1.0 - pct['generic_uncertainty'][candidate_id]),
        ])
        explore_score = sum([
            EXPLORE_WEIGHTS['developability'] * pct['developability'][candidate_id],
            EXPLORE_WEIGHTS['expression_purity'] * pct['expression_purity'][candidate_id],
            EXPLORE_WEIGHTS['abnativ'] * pct['abnativ'][candidate_id],
            EXPLORE_WEIGHTS['novelty'] * pct['novelty'][candidate_id],
            EXPLORE_WEIGHTS['generic_uncertainty'] * pct['generic_uncertainty'][candidate_id],
        ])
        row["exploit_score"] = f"{exploit_score:.9f}"
        row["explore_score"] = f"{explore_score:.9f}"
        row["exploration_pool"] = str(
            pct["generic_prior"][candidate_id] <= 0.5
            or pct["generic_uncertainty"][candidate_id] >= 0.75
        ).lower()


def select(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    counts: Counter[tuple[str, ...]] = Counter()
    selected: list[dict[str, str]] = []

    def can_add(row: dict[str, str]) -> bool:
        return (
            counts[("parent", row["parent_id"])] < PARENT_CAP
            and counts[("combo", row["parent_id"], row["target_patch_id"], row["design_mode"])] < PARENT_PATCH_MODE_CAP
            and counts[("cdr3", row["cdr3_cluster"])] < CDR3_CLUSTER_CAP
            and counts[("patch", row["target_patch_id"])] < PATCH_CAP
        )

    def add(row: dict[str, str], lane: str) -> None:
        chosen = dict(row)
        chosen["selection_lane"] = lane
        chosen["selection_score"] = row["exploit_score"] if lane == "EXPLOIT" else row["explore_score"]
        chosen["selection_reason"] = (
            "QC_DEVELOPABILITY_NOVELTY_WITH_WEAK_PRIOR_TIEBREAKER"
            if lane == "EXPLOIT"
            else "QC_PASS_DIVERSITY_HEDGE_LOW_PRIOR_OR_HIGH_UNCERTAINTY"
        )
        selected.append(chosen)
        counts[("parent", row["parent_id"])] += 1
        counts[("combo", row["parent_id"], row["target_patch_id"], row["design_mode"])] += 1
        counts[("cdr3", row["cdr3_cluster"])] += 1
        counts[("patch", row["target_patch_id"])] += 1

    for row in sorted(rows, key=lambda item: (-float(item["exploit_score"]), item["candidate_id"])):
        if len(selected) == EXPLOIT_COUNT:
            break
        if can_add(row):
            add(row, "EXPLOIT")
    if len(selected) != EXPLOIT_COUNT:
        raise RuntimeError(f"could select only {len(selected)} exploitation candidates")

    selected_ids = {row["candidate_id"] for row in selected}
    explore_pool = [
        row for row in rows
        if row["candidate_id"] not in selected_ids and row["exploration_pool"] == "true"
    ]
    for row in sorted(explore_pool, key=lambda item: (-float(item["explore_score"]), item["candidate_id"])):
        if len(selected) == TARGET_COUNT:
            break
        if can_add(row):
            add(row, "EXPLORE")
    if len(selected) != TARGET_COUNT:
        raise RuntimeError(f"could select only {len(selected)} total candidates")

    lane_counts: Counter[str] = Counter()
    for rank, row in enumerate(selected, start=1):
        lane_counts[row["selection_lane"]] += 1
        row["pre_shortlist_rank"] = str(rank)
        row["lane_rank"] = str(lane_counts[row["selection_lane"]])
    return selected


def write_outputs(
    outdir: Path,
    master_fields: list[str],
    selected: list[dict[str, str]],
    master_path: Path,
) -> dict[str, object]:
    outdir.mkdir(parents=True, exist_ok=True)
    metadata_fields = [
        "pre_shortlist_rank", "selection_lane", "lane_rank", "selection_score",
        "selection_reason", "exploration_pool", "pct_developability",
        "pct_expression_purity", "pct_abnativ", "pct_novelty", "pct_generic_prior",
        "pct_generic_uncertainty", "exploit_score", "explore_score",
    ]
    tsv_path = outdir / "pre_shortlist100.tsv"
    with tsv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=metadata_fields + master_fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(selected)
    fasta_path = outdir / "pre_shortlist100.fasta"
    fasta_path.write_text(
        "".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in selected),
        encoding="utf-8",
    )
    config = {
        "schema_version": "pvrig_pre_shortlist100_config_v1",
        "status": "FROZEN_QC_DIVERSITY_PRE_SHORTLIST_GEOMETRY_PENDING",
        "source_master_sha256": sha256_file(master_path),
        "target_count": TARGET_COUNT,
        "lane_counts": {"EXPLOIT": EXPLOIT_COUNT, "EXPLORE": EXPLORE_COUNT},
        "score_semantics": "within-lane operational priority, not calibrated probability",
        "exploit_weights": EXPLOIT_WEIGHTS,
        "explore_weights": EXPLORE_WEIGHTS,
        "exploration_pool": "generic prior percentile <=0.5 OR generic uncertainty percentile >=0.75",
        "constraints": {
            "maximum_per_parent": PARENT_CAP,
            "maximum_per_parent_patch_mode": PARENT_PATCH_MODE_CAP,
            "maximum_per_cdr3_cluster": CDR3_CLUSTER_CAP,
            "maximum_per_patch": PATCH_CAP,
        },
        "excluded_cohort": "DUAL128_SECONDARY until equivalent Full-QC and lineage are complete",
        "geometry_policy": "No V4-D geometry is used in v1; rerank only after fresh terminal aggregate without changing these QC/diversity facts.",
        "claim_boundary": (
            "Pre-shortlist for compute allocation only; generic prior is weak evidence and no row "
            "is asserted to bind or block PVRIG."
        ),
    }
    config_path = outdir / "pre_shortlist100_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    parent_counts = Counter(row["parent_id"] for row in selected)
    combo_counts = Counter((row["parent_id"], row["target_patch_id"], row["design_mode"]) for row in selected)
    cdr3_counts = Counter(row["cdr3_cluster"] for row in selected)
    patch_counts = Counter(row["target_patch_id"] for row in selected)
    mode_counts = Counter(row["design_mode"] for row in selected)
    audit = {
        "schema_version": "pvrig_pre_shortlist100_audit_v1",
        "status": "PASS_PRE_SHORTLIST_GEOMETRY_PENDING_NOT_FINAL",
        "selected_count": len(selected),
        "unique_candidate_count": len({row["candidate_id"] for row in selected}),
        "unique_sequence_count": len({row["sequence_sha256"] for row in selected}),
        "lane_counts": dict(Counter(row["selection_lane"] for row in selected)),
        "exploration_fraction": sum(row["selection_lane"] == "EXPLORE" for row in selected) / len(selected),
        "parent_count": len(parent_counts),
        "maximum_parent_count": max(parent_counts.values()),
        "maximum_parent_patch_mode_count": max(combo_counts.values()),
        "cdr3_cluster_count": len(cdr3_counts),
        "maximum_cdr3_cluster_count": max(cdr3_counts.values()),
        "patch_counts": dict(patch_counts),
        "mode_counts": dict(mode_counts),
        "all_fullqc290_primary": all(row["source_cohort"] == "FULLQC290_PRIMARY" for row in selected),
        "all_full_qc_complete": all(row["full_qc_status"] == "COMPLETE_HARD_PASS_ABNATIV_COMPLETE" for row in selected),
        "all_exact_positive_ids_empty": all(not row["exact_positive_id"] for row in selected),
        "all_v4d_geometry_pending": all(row["geometry_status"].startswith("RUNNING_PENDING") for row in selected),
        "outputs": {
            "tsv": {"path": str(tsv_path), "sha256": sha256_file(tsv_path)},
            "fasta": {"path": str(fasta_path), "sha256": sha256_file(fasta_path)},
            "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
        },
        "claim_boundary": config["claim_boundary"],
    }
    if not (
        len(selected) == TARGET_COUNT
        and audit["lane_counts"] == {"EXPLOIT": EXPLOIT_COUNT, "EXPLORE": EXPLORE_COUNT}
        and audit["maximum_parent_count"] <= PARENT_CAP
        and audit["maximum_parent_patch_mode_count"] <= PARENT_PATCH_MODE_CAP
        and audit["maximum_cdr3_cluster_count"] <= CDR3_CLUSTER_CAP
        and all(25 <= count <= PATCH_CAP for count in patch_counts.values())
        and set(mode_counts) == {"H1H3", "H3"}
        and audit["all_full_qc_complete"]
        and audit["all_exact_positive_ids_empty"]
    ):
        raise RuntimeError(json.dumps(audit, ensure_ascii=False, indent=2))
    audit_path = outdir / "pre_shortlist100_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return audit


def run(args: argparse.Namespace) -> dict[str, object]:
    master_fields, all_rows = read_master(args.master)
    rows = [
        row for row in all_rows
        if row["source_cohort"] == "FULLQC290_PRIMARY"
        and row["shortlist_eligibility"].startswith("ELIGIBLE")
    ]
    if len(rows) != 290:
        raise ValueError(f"expected 290 eligible FullQC rows, found {len(rows)}")
    add_scores(rows)
    selected = select(rows)
    return write_outputs(args.outdir, master_fields, selected, args.master)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main() -> int:
    audit = run(parse_args())
    print(json.dumps({"status": audit["status"], "selected": audit["selected_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
