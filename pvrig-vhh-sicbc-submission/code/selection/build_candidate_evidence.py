#!/usr/bin/env python3
"""Build the auditable 13,720-candidate evidence table and full-QC input.

This stage consumes the frozen two-panel membership, fast sequence QC, the two
completed job-level docking tables, the frozen 150k multimetric table and the
route-specific high-support snapshot.  It does not run docking or claim wet-lab
binding/blocking.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


BINDING_WEAK_PRIOR_MIN = 0.6783883333333334
EXPECTED_UNION = 13_720
EXPECTED_OLD_JOBS = 25_000
EXPECTED_C2_JOBS = 41_760


def load_module(path: Path) -> ModuleType:
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("pvrig_competition_qc", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import competition QC module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def iter_tsv_gz(path: Path) -> Iterable[dict[str, str]]:
    with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle, delimiter="\t")


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_fasta(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


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


def optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "pass", "yes"}


def numeric_at_least(value: Any, threshold: float) -> bool:
    parsed = optional_float(value)
    return parsed is not None and parsed >= threshold


def numeric_at_most(value: Any, threshold: float) -> bool:
    parsed = optional_float(value)
    return parsed is not None and parsed <= threshold


def developability_conservative_pass(row: dict[str, str]) -> bool:
    return all(
        [
            row.get("tnp_status") == "PASS",
            row.get("tnp_review_tier") == "CLEAR",
            optional_int(row.get("tnp_red_flag_count")) == 0,
            row.get("abnativ_status") == "PASS",
            numeric_at_least(row.get("AbNatiV VHH Score"), 0.70),
            numeric_at_least(row.get("mean_self_probability"), 0.70),
            numeric_at_least(row.get("expression_purity_risk_proxy_partial"), 85.0),
            optional_int(row.get("cys_count")) == 2,
            optional_int(row.get("nglyc_motif_count")) == 0,
            optional_int(row.get("hydrophobic_5_count")) == 0,
            numeric_at_most(row.get("max_positive_cdr_identity"), 0.75),
            row.get("anarci_qc_status") == "PASS",
            row.get("nbb2_status") == "SUCCESS",
            bool_value(row.get("nbb2_pdb_sequence_match")),
        ]
    )


def developability_calibrated(row: dict[str, str]) -> tuple[bool, int, list[str]]:
    """Apply the positive-control-calibrated developability policy.

    Single proxy warnings do not reject a candidate. Technical failures,
    unexplained cysteine states, or at least two orthogonal severe liabilities
    do.
    """
    technical = all(
        [
            numeric_at_most(row.get("max_positive_cdr_identity"), 0.75),
            row.get("anarci_qc_status") == "PASS",
            row.get("nbb2_status") == "SUCCESS",
            bool_value(row.get("nbb2_pdb_sequence_match")),
        ]
    )
    if not technical:
        return False, 0, ["technical_or_novelty_failure"]
    cys_count = optional_int(row.get("cys_count"))
    if cys_count not in {2, 4}:
        return False, 0, [f"unexplained_cysteine_count:{cys_count}"]
    warnings: list[str] = []
    severe: list[str] = []
    if (
        row.get("tnp_status") != "PASS"
        or row.get("tnp_review_tier") != "CLEAR"
        or (optional_int(row.get("tnp_red_flag_count")) or 0) > 0
    ):
        warnings.append("tnp_warning")
    abnativ = optional_float(row.get("AbNatiV VHH Score"))
    if abnativ is None or abnativ < 0.70:
        warnings.append("abnativ_below_preferred")
    if abnativ is not None and abnativ < 0.55:
        severe.append("abnativ_severe")
    sapiens = optional_float(row.get("mean_self_probability"))
    if sapiens is None or sapiens < 0.70:
        warnings.append("sapiens_below_preferred")
    if sapiens is not None and sapiens < 0.55:
        severe.append("sapiens_severe")
    expression = optional_float(row.get("expression_purity_risk_proxy_partial"))
    if expression is None or expression < 85:
        warnings.append("expression_purity_proxy_below_preferred")
    if expression is not None and expression < 60:
        severe.append("expression_purity_proxy_severe")
    nglyc = optional_int(row.get("nglyc_motif_count")) or 0
    if nglyc:
        warnings.append("nglyc_motif")
        severe.append("nglyc_motif")
    hydrophobic = optional_int(row.get("hydrophobic_5_count")) or 0
    if hydrophobic:
        warnings.append("hydrophobic_5mer")
    if hydrophobic > 1:
        severe.append("multiple_hydrophobic_5mers")
    if cys_count == 4:
        warnings.append("four_cysteines_requires_structural_disulfide_review")
    return len(set(severe)) < 2, len(set(warnings)), sorted(set(warnings + severe))


def seed_evidence(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    success_states = {"SUCCESS", "PASS", "COMPLETE", "COMPLETED"}
    grouped: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    all_jobs = Counter()
    success_jobs = Counter()
    seeds_seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        candidate_id = row.get("candidate_id") or row.get("entity_id") or ""
        if not candidate_id:
            continue
        all_jobs[candidate_id] += 1
        seed = str(row.get("seed", "")).strip()
        conformation = str(
            row.get("conformation") or row.get("dock_conformation") or ""
        ).lower()
        if seed:
            seeds_seen[candidate_id].add(seed)
        if (
            str(row.get("state", "")).upper() in success_states
            and seed
            and conformation in {"8x6b", "9e6y"}
        ):
            success_jobs[candidate_id] += 1
            label = str(row.get("representative_pair_label", "")).upper()
            strict_fraction = optional_float(row.get("model_strict_a_fraction"))
            grouped[candidate_id][seed][conformation] = {
                "representative_label": label,
                # The frozen mechanism contract is "at least one selected pose
                # passes both references", not "the lowest-HADDOCK pose passes".
                "any_strict_pose": (
                    strict_fraction is not None and strict_fraction > 0
                )
                or label == "STRICT_A",
                "any_broad_pose": label in {"STRICT_A", "SUPPORTED_AB"}
                or (strict_fraction is not None and strict_fraction > 0),
            }
    output: dict[str, dict[str, Any]] = {}
    for candidate_id in set(all_jobs) | set(grouped):
        complete = 0
        strict = 0
        broad = 0
        for conformation_evidence in grouped[candidate_id].values():
            if set(conformation_evidence) != {"8x6b", "9e6y"}:
                continue
            complete += 1
            if all(
                evidence["any_strict_pose"]
                for evidence in conformation_evidence.values()
            ):
                strict += 1
            if all(
                evidence["any_broad_pose"]
                for evidence in conformation_evidence.values()
            ):
                broad += 1
        output[candidate_id] = {
            "job_count": all_jobs[candidate_id],
            "successful_job_count": success_jobs[candidate_id],
            "seed_count": len(seeds_seen[candidate_id]),
            "complete_seed_count": complete,
            "strict_seed_passes": strict,
            "broad_seed_passes": broad,
            "strict_seed_fraction": strict / complete if complete else None,
            "seed_ids": ",".join(sorted(seeds_seen[candidate_id], key=lambda x: int(x))),
        }
    return output


def percentile(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted((value, candidate_id) for candidate_id, value in values.items())
    if not ordered:
        return {}
    denominator = max(1, len(ordered) - 1)
    output: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        rank = ((index + end - 1) / 2) / denominator
        for _, candidate_id in ordered[index:end]:
            output[candidate_id] = rank
        index = end
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--membership", type=Path, required=True)
    parser.add_argument("--fast", type=Path, required=True)
    parser.add_argument("--old-jobs", type=Path, required=True)
    parser.add_argument("--c2-jobs", type=Path, required=True)
    parser.add_argument("--multimetric", type=Path, required=True)
    parser.add_argument("--surrogate", type=Path, required=True)
    parser.add_argument("--competition-qc-module", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full-qc-limit", type=int, default=2000)
    parser.add_argument("--enforce-frozen-strict-counts", action="store_true")
    args = parser.parse_args()

    membership_rows = read_tsv(args.membership)
    fast_rows = read_tsv(args.fast)
    old_jobs = read_tsv(args.old_jobs)
    c2_jobs = read_tsv(args.c2_jobs)
    surrogate_rows = read_tsv(args.surrogate)
    if len(membership_rows) != EXPECTED_UNION:
        raise ValueError(f"membership rows {len(membership_rows)} != {EXPECTED_UNION}")
    if len(fast_rows) != EXPECTED_UNION:
        raise ValueError(f"fast rows {len(fast_rows)} != {EXPECTED_UNION}")
    if len(old_jobs) != EXPECTED_OLD_JOBS:
        raise ValueError(f"old job rows {len(old_jobs)} != {EXPECTED_OLD_JOBS}")
    if len(c2_jobs) != EXPECTED_C2_JOBS:
        raise ValueError(f"C2 job rows {len(c2_jobs)} != {EXPECTED_C2_JOBS}")

    membership = {row["candidate_id"]: row for row in membership_rows}
    fast = {row["candidate_id"]: row for row in fast_rows}
    if set(membership) != set(fast):
        raise ValueError("membership and fast candidate ID sets differ")
    all_job_rows = old_jobs + c2_jobs
    if len({row["job_id"] for row in all_job_rows}) != len(all_job_rows):
        raise ValueError("duplicate job_id across old/C2 job tables")

    qc = load_module(args.competition_qc_module)
    docking_by_id = qc.aggregate_docking_rows(all_job_rows)
    seed_by_id = seed_evidence(all_job_rows)
    surrogate = {
        (row["route"], row["candidate_id"]): row for row in surrogate_rows
    }

    multimetric: dict[str, dict[str, str]] = {}
    wanted = set(membership)
    for row in iter_tsv_gz(args.multimetric):
        if row.get("candidate_id") in wanted:
            multimetric[row["candidate_id"]] = row
    missing_multimetric = sorted(wanted - set(multimetric))
    if missing_multimetric:
        raise ValueError(f"{len(missing_multimetric)} candidates lack multimetric rows")

    c2_four_ids = {
        candidate_id
        for candidate_id, evidence in seed_by_id.items()
        if {"42", "3047"} & set(str(evidence.get("seed_ids", "")).split(","))
    }
    evidence_rows: list[dict[str, Any]] = []
    for candidate_id in membership:
        member = membership[candidate_id]
        fast_row = fast[candidate_id]
        metric = multimetric[candidate_id]
        docking = docking_by_id.get(candidate_id, {})
        seed = seed_by_id.get(candidate_id, {})
        if member["panel_membership"] in {"OLD_ONLY", "OLD_AND_C2"}:
            route = "old_top7500"
            g3_pass = (
                int(seed.get("complete_seed_count", 0)) >= 2
                and int(seed.get("strict_seed_passes", 0)) >= 2
            )
        elif candidate_id in c2_four_ids:
            route = "c2_four_seed"
            g3_pass = (
                int(seed.get("complete_seed_count", 0)) == 4
                and int(seed.get("strict_seed_passes", 0)) == 4
            )
        else:
            route = "c2_two_seed"
            g3_pass = False
        conservative_development = developability_conservative_pass(metric)
        development, development_warning_count, development_reasons = (
            developability_calibrated(metric)
        )
        binding_prior = optional_float(metric.get("binding_consensus_weak_prior"))
        binding_high = (
            binding_prior is not None and binding_prior >= BINDING_WEAK_PRIOR_MIN
        )
        support = surrogate.get((route, candidate_id))
        high_support = support is not None
        fast_hard_fail = bool_value(fast_row.get("hard_fail"))
        if fast_hard_fail:
            tier = "HARD_FAIL"
        elif g3_pass and development and binding_high and high_support:
            tier = "CORE_A"
        elif g3_pass and development and binding_high:
            tier = "DIVERSITY_B"
        elif g3_pass and development:
            tier = "DISAGREEMENT_C"
        elif g3_pass:
            tier = "RESERVE_D"
        else:
            tier = "NOT_G3_READY"
        blocking_score = qc.score_blocking(docking)
        robustness_score = qc.score_pose_robustness(docking)
        sequence = member["sequence"]
        observed_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if observed_hash != member["sequence_sha256"]:
            raise ValueError(f"sequence hash mismatch: {candidate_id}")
        evidence_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence": sequence,
                "sequence_sha256": observed_hash,
                "panel_membership": member["panel_membership"],
                "route": route,
                "old_priority_rank": member.get("old_priority_rank", ""),
                "c2_refined_rank": member.get("c2_refined_rank", ""),
                "parent_cluster": metric.get("parent_cluster", ""),
                "parent_id": metric.get("parent_id", ""),
                "cdr1": metric.get("anarci_cdr1", ""),
                "cdr2": metric.get("anarci_cdr2", ""),
                "cdr3": metric.get("anarci_cdr3", ""),
                "fast_hard_fail": str(fast_hard_fail).lower(),
                "fast_reason_summary": fast_row.get("reason_summary", ""),
                "max_positive_cdr_identity": metric.get(
                    "max_positive_cdr_identity", ""
                ),
                "developability_hardpass": str(development).lower(),
                "developability_conservative_pass": str(
                    conservative_development
                ).lower(),
                "developability_warning_count": development_warning_count,
                "developability_calibrated_reasons": ",".join(development_reasons),
                "binding_consensus_weak_prior": (
                    f"{binding_prior:.12g}" if binding_prior is not None else ""
                ),
                "binding_weak_prior_high": str(binding_high).lower(),
                "surrogate_high_support": str(high_support).lower(),
                "surrogate_support_label": (
                    support.get("surrogate_support_label", "") if support else ""
                ),
                "surrogate_utility": (
                    support.get("surrogate_utility", "") if support else ""
                ),
                "job_count": seed.get("job_count", 0),
                "successful_job_count": seed.get("successful_job_count", 0),
                "seed_ids": seed.get("seed_ids", ""),
                "complete_seed_count": seed.get("complete_seed_count", 0),
                "strict_seed_passes": seed.get("strict_seed_passes", 0),
                "broad_seed_passes": seed.get("broad_seed_passes", 0),
                "strict_seed_fraction": (
                    f"{seed['strict_seed_fraction']:.6f}"
                    if seed.get("strict_seed_fraction") is not None
                    else ""
                ),
                "g3_docking_hardpass": str(g3_pass).lower(),
                "docking_evidence_status": docking.get(
                    "docking_evidence_status", "TECHNICAL_NA"
                ),
                "blocker_class": docking.get("blocker_class", ""),
                "strict_a_job_fraction": docking.get("strict_a_job_fraction", ""),
                "supported_ab_job_fraction": docking.get(
                    "supported_ab_job_fraction", ""
                ),
                "valid_docking_job_fraction": docking.get(
                    "valid_docking_job_fraction", ""
                ),
                "dual_conformation_coverage": docking.get(
                    "dual_conformation_coverage", ""
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
                "blocking_consensus_score": (
                    f"{blocking_score:.6f}" if blocking_score is not None else ""
                ),
                "pose_robustness_score": (
                    f"{robustness_score:.6f}" if robustness_score is not None else ""
                ),
                "abnativ_vhh_score": metric.get("AbNatiV VHH Score", ""),
                "sapiens_mean_self_probability": metric.get(
                    "mean_self_probability", ""
                ),
                "expression_purity_risk_proxy": metric.get(
                    "expression_purity_risk_proxy_partial", ""
                ),
                "developability_risk_proxy": metric.get(
                    "developability_risk_proxy_partial", ""
                ),
                "tnp_status": metric.get("tnp_status", ""),
                "tnp_review_tier": metric.get("tnp_review_tier", ""),
                "cys_count": metric.get("cys_count", ""),
                "nglyc_motif_count": metric.get("nglyc_motif_count", ""),
                "hydrophobic_5_count": metric.get("hydrophobic_5_count", ""),
                "nbb2_status": metric.get("nbb2_status", ""),
                "nbb2_pdb_sequence_match": metric.get(
                    "nbb2_pdb_sequence_match", ""
                ),
                "candidate_tier": tier,
                "evidence_boundary": (
                    "computational sequence, binding-prior and blocker-like geometry; "
                    "not BLI/Kd/IC50/expression/purity"
                ),
            }
        )

    old_strict = sum(
        row["route"] == "old_top7500" and row["g3_docking_hardpass"] == "true"
        for row in evidence_rows
    )
    c2_four_strict = sum(
        row["route"] == "c2_four_seed" and row["g3_docking_hardpass"] == "true"
        for row in evidence_rows
    )
    strict_regression_pass = old_strict == 1923 and c2_four_strict == 4119
    if args.enforce_frozen_strict_counts and not strict_regression_pass:
        raise ValueError(
            "strict docking regression: "
            f"old={old_strict} expected=1923, "
            f"c2_four={c2_four_strict} expected=4119"
        )

    eligible = [
        row
        for row in evidence_rows
        if row["fast_hard_fail"] == "false"
        and row["g3_docking_hardpass"] == "true"
        and row["developability_hardpass"] == "true"
    ]
    binding_percentiles = percentile(
        {
            row["candidate_id"]: float(row["binding_consensus_weak_prior"])
            for row in eligible
            if row["binding_consensus_weak_prior"] != ""
        }
    )
    blocking_percentiles = percentile(
        {
            row["candidate_id"]: float(row["blocking_consensus_score"])
            for row in eligible
            if row["blocking_consensus_score"] != ""
        }
    )
    tier_priority = {"CORE_A": 0, "DIVERSITY_B": 1, "DISAGREEMENT_C": 2, "RESERVE_D": 3}
    for row in evidence_rows:
        candidate_id = row["candidate_id"]
        binding_rank = binding_percentiles.get(candidate_id)
        blocking_rank = blocking_percentiles.get(candidate_id)
        row["binding_rank_percentile"] = (
            f"{binding_rank:.9f}" if binding_rank is not None else ""
        )
        row["blocking_rank_percentile"] = (
            f"{blocking_rank:.9f}" if blocking_rank is not None else ""
        )
        row["rescreen_competition_proxy"] = (
            f"{0.5 * binding_rank + 0.5 * blocking_rank:.9f}"
            if binding_rank is not None and blocking_rank is not None
            else ""
        )
    eligible.sort(
        key=lambda row: (
            tier_priority.get(str(row["candidate_tier"]), 9),
            -float(row["rescreen_competition_proxy"] or -1),
            -float(row["binding_consensus_weak_prior"] or -1),
            str(row["candidate_id"]),
        )
    )
    full_qc_rows = eligible[: args.full_qc_limit]
    full_qc_ids = {row["candidate_id"] for row in full_qc_rows}
    for row in evidence_rows:
        row["selected_for_full_qc"] = str(row["candidate_id"] in full_qc_ids).lower()
    evidence_rows.sort(key=lambda row: str(row["candidate_id"]))

    args.out.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out / "candidate_evidence_table.tsv"
    docking_path = args.out / "candidate_docking_summary.tsv"
    full_qc_tsv = args.out / "full_qc_input_2000.tsv"
    full_qc_fasta = args.out / "full_qc_input_2000.fasta"
    failures_path = args.out / "hard_gate_failures.tsv"
    funnel_path = args.out / "funnel_counts.tsv"
    write_tsv(evidence_path, evidence_rows)
    docking_rows = []
    for row in evidence_rows:
        docking_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "binding_score": (
                    f"{100 * float(row['binding_consensus_weak_prior']):.6f}"
                    if row["binding_consensus_weak_prior"] != ""
                    else ""
                ),
                "binding_prior_consensus": row["binding_consensus_weak_prior"],
                "blocking_consensus_score": row["blocking_consensus_score"],
                "pose_robustness_score": row["pose_robustness_score"],
                "docking_evidence_status": row["docking_evidence_status"],
                "blocker_class": row["blocker_class"],
                "strict_a_job_fraction": row["strict_a_job_fraction"],
                "supported_ab_job_fraction": row["supported_ab_job_fraction"],
                "valid_docking_job_fraction": row["valid_docking_job_fraction"],
                "dual_conformation_coverage": row["dual_conformation_coverage"],
                "seed_consistency_fraction": row["seed_consistency_fraction"],
                "pose_pair_consensus_fraction": row["pose_pair_consensus_fraction"],
                "dual_reference_agreement_fraction": row[
                    "dual_reference_agreement_fraction"
                ],
                "hotspot_overlap_count": row["hotspot_overlap_count"],
                "total_vhh_pvrl2_residue_pair_occlusion": row[
                    "total_pvrl2_occlusion"
                ],
                "cdr3_pvrl2_residue_pair_occlusion": row[
                    "cdr3_pvrl2_occlusion"
                ],
                "cdr3_occlusion_fraction": row["cdr3_occlusion_fraction"],
            }
        )
    write_tsv(docking_path, docking_rows)
    write_tsv(full_qc_tsv, full_qc_rows)
    write_fasta(full_qc_fasta, full_qc_rows)
    failures = [
        row
        for row in evidence_rows
        if row["fast_hard_fail"] == "true"
        or row["g3_docking_hardpass"] == "false"
        or row["developability_hardpass"] == "false"
    ]
    write_tsv(failures_path, failures)
    funnel = [
        {"stage": "union", "count": len(evidence_rows)},
        {
            "stage": "fast_hardpass",
            "count": sum(row["fast_hard_fail"] == "false" for row in evidence_rows),
        },
        {
            "stage": "g3_strict_docking",
            "count": sum(row["g3_docking_hardpass"] == "true" for row in evidence_rows),
        },
        {"stage": "developability_hardpass", "count": len(eligible)},
        {
            "stage": "core_A",
            "count": sum(row["candidate_tier"] == "CORE_A" for row in evidence_rows),
        },
        {"stage": "full_qc_input", "count": len(full_qc_rows)},
    ]
    write_tsv(funnel_path, funnel)
    outputs = [
        evidence_path,
        docking_path,
        full_qc_tsv,
        full_qc_fasta,
        failures_path,
        funnel_path,
    ]
    receipt = {
        "schema_version": "pvrig.top7500.candidate_evidence.v1",
        "status": "PASS_CANDIDATE_EVIDENCE_BUILT",
        "counts": {
            "union": len(evidence_rows),
            "old_strict": old_strict,
            "c2_four_seed_strict": c2_four_strict,
            "g3_strict_total": sum(
                row["g3_docking_hardpass"] == "true" for row in evidence_rows
            ),
            "developability_hardpass": len(eligible),
            "core_A": sum(
                row["candidate_tier"] == "CORE_A" for row in evidence_rows
            ),
            "full_qc_input": len(full_qc_rows),
        },
        "strict_regression_pass": strict_regression_pass,
        "expected_strict_counts": {"old": 1923, "c2_four_seed": 4119},
        "input_hashes": {
            str(path): sha256_file(path)
            for path in [
                args.membership,
                args.fast,
                args.old_jobs,
                args.c2_jobs,
                args.multimetric,
                args.surrogate,
                args.competition_qc_module,
            ]
        },
        "output_hashes": {path.name: sha256_file(path) for path in outputs},
        "claim_boundary": (
            "Computational evidence and screening proxies only; not experimental "
            "binding, Kd, IC50, expression or purity."
        ),
    }
    receipt_path = args.out / "CANDIDATE_EVIDENCE_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in outputs + [receipt_path]),
        encoding="ascii",
    )
    print(json.dumps(receipt["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
