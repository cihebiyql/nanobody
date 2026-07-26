#!/usr/bin/env python3
"""Integrate uniform Final50 QC, categorical sensitivity, and portfolio evidence.

This script never changes the frozen mechanism rank or the frozen 50 sequences.
Its Top10 is an auditable competition-priority sidecar, not a new docking rank.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROFILES = {
    "STRICT": {
        "abnativ_warn_below": 0.75,
        "sapiens_warn_below": 0.75,
        "patch_warn_residues": 12,
        "patch_warn_area_a2": 800,
        "patch_hard_residues": 18,
        "patch_hard_area_a2": 900,
        "instability_warn_at": 35,
        "acid_exposure_warn_rows": 3,
        "tnp_red_hard_at": 1,
    },
    "PRIMARY": {
        "abnativ_warn_below": 0.70,
        "sapiens_warn_below": 0.70,
        "patch_warn_residues": 15,
        "patch_warn_area_a2": 900,
        "patch_hard_residues": 20,
        "patch_hard_area_a2": 1000,
        "instability_warn_at": 40,
        "acid_exposure_warn_rows": 4,
        "tnp_red_hard_at": 2,
    },
    "PERMISSIVE": {
        "abnativ_warn_below": 0.65,
        "sapiens_warn_below": 0.65,
        "patch_warn_residues": 18,
        "patch_warn_area_a2": 1000,
        "patch_hard_residues": 22,
        "patch_hard_area_a2": 1100,
        "instability_warn_at": 45,
        "acid_exposure_warn_rows": 6,
        "tnp_red_hard_at": 2,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-tsv", required=True, type=Path)
    parser.add_argument("--ranked-tsv", required=True, type=Path)
    parser.add_argument("--screen-summary", required=True, type=Path)
    parser.add_argument("--vhh-eval-tsv", required=True, type=Path)
    parser.add_argument("--official-failed-reasons", required=True, type=Path)
    parser.add_argument("--positive-summary", required=True, type=Path)
    parser.add_argument("--team-pairs", required=True, type=Path)
    parser.add_argument("--team-nearest", required=True, type=Path)
    parser.add_argument("--structure-tsv", required=True, type=Path)
    parser.add_argument("--prefusion-tsv", required=True, type=Path)
    parser.add_argument("--epitope-tsv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def keyed(path: Path, key: str) -> dict[str, dict[str, str]]:
    rows = read_tsv(path)
    output = {row[key]: row for row in rows}
    if len(output) != len(rows):
        raise ValueError(f"duplicate {key} in {path}")
    return output


def write_tsv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise ValueError(f"refusing empty TSV: {path}")
    fields: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(materialized)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "pass", "passed"}


def as_float(value: object, default: float | None = None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def patent_success_parent(parent_cluster: str) -> bool:
    return parent_cluster.startswith("positive_pose_source_case02_")


def poor_split(single_domain: str, parent_cluster: str) -> str:
    if single_domain not in {"poor", "not_vhh_like"}:
        return "NOT_POOR_SINGLE_DOMAIN"
    if patent_success_parent(parent_cluster):
        return "PATENT_SUCCESS_SCAFFOLD_REVIEW"
    return "UNSUPPORTED_POOR_VHH_HARD_RISK"


def grade_candidate(
    *,
    official_pass: bool,
    freeze: dict[str, str],
    screen: dict[str, str],
    vhh_eval: dict[str, str],
    structure: dict[str, str],
    prefusion: dict[str, str],
    profile_name: str,
) -> dict[str, Any]:
    profile = PROFILES[profile_name]
    hard: list[str] = []
    warn: list[str] = []
    parent = freeze["parent_cluster"]
    suitability = screen.get("single_domain_suitability", "").strip().lower()
    split = poor_split(suitability, parent)
    abnativ = as_float(screen.get("abnativ_vhh_score"))
    sapiens = as_float(screen.get("sapiens_mean_self_probability"))
    cys = as_int(screen.get("cys_count"), freeze["sequence"].count("C"))
    cdr_nglyc = bool(
        re.search(r"N[^P][ST]", freeze["cdr1"] + freeze["cdr2"] + freeze["cdr3"])
    )
    whole_nglyc = as_int(screen.get("nglyc_motif_count"))
    hydro5 = as_int(screen.get("hydrophobic_5_count"))
    patch_n = as_float(structure.get("median_largest_hydrophobic_patch_residues"), 0) or 0
    patch_area = (
        as_float(structure.get("median_largest_hydrophobic_patch_free_sasa_a2"), 0)
        or 0
    )
    exposed_unpaired_cys = as_int(prefusion.get("max_exposed_unpaired_cys_count"))
    instability = as_float(vhh_eval.get("instability_index"))
    charge = as_float(screen.get("charge_pH7_4"))
    pi_value = as_float(screen.get("pI"))
    acid_rows = as_int(structure.get("exposed_noncontact_acid_clipping_rows"))
    tnp_flags = [
        screen.get(f"tnp_{name}_flag", "").strip().lower()
        for name in ("L", "L3", "C", "PSH", "PPC", "PNC")
    ]
    red_count = sum(value in {"red", "fail", "failed"} for value in tnp_flags)
    amber_count = sum(
        value in {"amber", "yellow", "orange", "warn"} for value in tnp_flags
    )

    if not official_pass:
        hard.append("OFFICIAL_VALIDATOR_FAIL")
    if screen.get("L1_numbering_integrity") == "FAIL":
        hard.append("UNIFORM_L1_NUMBERING_FAIL")
    if screen.get("imgt_chain_type") not in {"H", "heavy"}:
        hard.append("NOT_HEAVY_VARIABLE_DOMAIN")
    if as_bool(prefusion.get("fusion_hard_fail")) or prefusion.get(
        "prefusion_compatibility_grade"
    ) == "F3_HARD_FAIL":
        hard.append(
            "PREFUSION_HARD_FAIL:" + prefusion.get("fusion_hard_fail_reasons", "")
        )
    if split == "UNSUPPORTED_POOR_VHH_HARD_RISK":
        hard.append("UNSUPPORTED_POOR_SINGLE_DOMAIN")
    elif split == "PATENT_SUCCESS_SCAFFOLD_REVIEW":
        warn.append("PATENT_SUCCESS_SCAFFOLD_POOR_SINGLE_DOMAIN_REVIEW")
    elif suitability == "borderline":
        warn.append("BORDERLINE_SINGLE_DOMAIN")
    if cys % 2:
        hard.append("ODD_CYS_COUNT")
    if exposed_unpaired_cys > 0:
        hard.append("STRUCTURALLY_EXPOSED_UNPAIRED_CYS")
    if cys != 2:
        warn.append(f"NONCANONICAL_CYS_COUNT_{cys}")
    if cdr_nglyc:
        hard.append("CDR_N_GLYCOSYLATION_MOTIF")
    elif whole_nglyc:
        warn.append("NON_CDR_N_GLYCOSYLATION_MOTIF")
    if hydro5 > 0:
        hard.append("HYDROPHOBIC_RUN_5")
    if (
        patch_n >= profile["patch_hard_residues"]
        and patch_area >= profile["patch_hard_area_a2"]
    ):
        hard.append("EXTREME_SURFACE_HYDROPHOBIC_PATCH")
    elif (
        patch_n >= profile["patch_warn_residues"]
        or patch_area >= profile["patch_warn_area_a2"]
    ):
        warn.append("ELEVATED_SURFACE_HYDROPHOBIC_PATCH")
    if red_count >= profile["tnp_red_hard_at"]:
        hard.append(f"TNP_RED_FLAGS_{red_count}")
    elif red_count:
        warn.append(f"TNP_RED_FLAG_{red_count}")
    if amber_count:
        warn.append(f"TNP_AMBER_FLAGS_{amber_count}")
    if not any(tnp_flags):
        warn.append("TNP_FLAGS_MISSING")
    if abnativ is None:
        warn.append("ABNATIV_MISSING")
    elif abnativ < profile["abnativ_warn_below"]:
        warn.append(f"ABNATIV_BELOW_{profile['abnativ_warn_below']:.2f}")
    if sapiens is None:
        warn.append("SAPIENS_MISSING")
    elif sapiens < profile["sapiens_warn_below"]:
        warn.append(f"SAPIENS_BELOW_{profile['sapiens_warn_below']:.2f}")
    if instability is not None and instability >= profile["instability_warn_at"]:
        warn.append(
            f"INSTABILITY_INDEX_GE_{profile['instability_warn_at']:.0f}"
        )
    if acid_rows >= profile["acid_exposure_warn_rows"]:
        warn.append(
            f"EXPOSED_ACID_CLIPPING_ROWS_GE_{profile['acid_exposure_warn_rows']}"
        )
    if charge is not None:
        if abs(charge) > 12:
            hard.append("EXTREME_NET_CHARGE_PH7P4")
        elif abs(charge) > 8:
            warn.append("HIGH_NET_CHARGE_PH7P4")
    if pi_value is not None:
        if pi_value < 4.5 or pi_value > 10.5:
            hard.append("EXTREME_PI")
        elif pi_value < 5.0 or pi_value > 9.5:
            warn.append("UNUSUAL_PI")
    if prefusion.get("prefusion_compatibility_grade") == "F2_REVIEW":
        warn.append(
            "PREFUSION_REVIEW:"
            + prefusion.get("fusion_tie_breaker_warnings", "")
        )

    hard = list(dict.fromkeys(item for item in hard if item))
    warn = list(dict.fromkeys(item for item in warn if item))
    grade = "C_HIGH_RISK" if hard else ("B_REVIEW" if warn else "A_LOWER_RISK")
    return {
        "profile": profile_name,
        "developability_grade": grade,
        "developability_hard_fail": str(bool(hard)).lower(),
        "hard_fail_reasons": ";".join(hard),
        "review_reasons": ";".join(warn),
        "poor_single_domain_split": split,
        "single_domain_suitability": suitability,
        "patent_success_parent_support": str(
            patent_success_parent(parent)
        ).lower(),
        "abnativ_vhh_score": "" if abnativ is None else f"{abnativ:.6f}",
        "sapiens_mean_self_probability": ""
        if sapiens is None
        else f"{sapiens:.6f}",
        "tnp_red_count": red_count,
        "tnp_amber_count": amber_count,
        "cdr_nglyc_motif": str(cdr_nglyc).lower(),
        "sequence_cys_count": cys,
        "structurally_exposed_unpaired_cys_count": exposed_unpaired_cys,
        "hydrophobic_5_count": hydro5,
        "median_largest_hydrophobic_patch_residues": f"{patch_n:.6f}",
        "median_largest_hydrophobic_patch_free_sasa_a2": f"{patch_area:.6f}",
        "instability_index": "" if instability is None else f"{instability:.6f}",
        "instability_index_source": "vhh_eval.tsv",
        "profile_thresholds_json": json.dumps(
            profile, sort_keys=True, separators=(",", ":")
        ),
    }


def prefixed(row: dict[str, str], prefix: str, skip: set[str]) -> dict[str, str]:
    return {f"{prefix}{key}": value for key, value in row.items() if key not in skip}


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frozen_rows = read_tsv(args.freeze_tsv)
    assert len(frozen_rows) == 50
    assert [int(row["competition_rank_1_50"]) for row in frozen_rows] == list(
        range(1, 51)
    )
    ranked_by_id = keyed(args.ranked_tsv, "candidate_id")
    screen_by_sid = keyed(args.screen_summary, "id")
    vhh_by_sid = keyed(args.vhh_eval_tsv, "id")
    positive_by_sid = keyed(args.positive_summary, "submission_id")
    nearest_by_sid = keyed(args.team_nearest, "submission_id")
    structure_by_id = keyed(args.structure_tsv, "candidate_id")
    prefusion_by_id = keyed(args.prefusion_tsv, "candidate_id")
    epitope_by_sid = keyed(args.epitope_tsv, "submission_id")
    failed_rows = read_csv(args.official_failed_reasons)
    failed_by_sid: dict[str, list[dict[str, str]]] = {}
    for row in failed_rows:
        failed_by_sid.setdefault(row["name"], []).append(row)

    candidate_ids = {row["candidate_id"] for row in frozen_rows}
    submission_ids = {row["submission_id"] for row in frozen_rows}
    for name, mapping, expected in (
        ("ranked", ranked_by_id, candidate_ids),
        ("structure", structure_by_id, candidate_ids),
        ("prefusion", prefusion_by_id, candidate_ids),
        ("screen", screen_by_sid, submission_ids),
        ("vhh", vhh_by_sid, submission_ids),
        ("positive", positive_by_sid, submission_ids),
        ("nearest", nearest_by_sid, submission_ids),
        ("epitope", epitope_by_sid, submission_ids),
    ):
        assert set(mapping) == expected, f"{name} membership mismatch"

    enriched_freeze: list[dict[str, str]] = []
    for freeze in frozen_rows:
        ranked = ranked_by_id[freeze["candidate_id"]]
        assert freeze["sequence"] == ranked["sequence"]
        assert freeze["sequence_sha256"] == ranked["sequence_sha256"]
        assert freeze["mechanism_rank_immutable"] == ranked["mechanism_rank_immutable"]
        item = dict(freeze)
        item["parent_cluster"] = ranked["parent_cluster"]
        item["route"] = ranked["route"]
        item["source_cohort"] = ranked["source_cohort"]
        enriched_freeze.append(item)

    sensitivity_rows: list[dict[str, Any]] = []
    grade_by_sid_profile: dict[tuple[str, str], dict[str, Any]] = {}
    for freeze in enriched_freeze:
        sid = freeze["submission_id"]
        assert vhh_by_sid[sid]["sequence"] == freeze["sequence"]
        instability_index = as_float(vhh_by_sid[sid].get("instability_index"))
        assert instability_index is not None and math.isfinite(instability_index), (
            f"missing/non-finite instability_index in vhh_eval.tsv for {sid}"
        )
        for profile_name in PROFILES:
            grade = grade_candidate(
                official_pass=sid not in failed_by_sid,
                freeze=freeze,
                screen=screen_by_sid[sid],
                vhh_eval=vhh_by_sid[sid],
                structure=structure_by_id[freeze["candidate_id"]],
                prefusion=prefusion_by_id[freeze["candidate_id"]],
                profile_name=profile_name,
            )
            row = {
                "submission_id": sid,
                "competition_rank_1_50": freeze["competition_rank_1_50"],
                "mechanism_rank_immutable": freeze["mechanism_rank_immutable"],
                "candidate_id": freeze["candidate_id"],
                "parent_cluster": freeze["parent_cluster"],
                "route": freeze["route"],
                **grade,
            }
            sensitivity_rows.append(row)
            grade_by_sid_profile[(sid, profile_name)] = row

    sensitivity_path = args.output_dir / "Final50_ABC_threshold_sensitivity.tsv"
    write_tsv(sensitivity_path, sensitivity_rows)
    sensitivity_summary_rows: list[dict[str, Any]] = []
    for profile_name in PROFILES:
        rows = [row for row in sensitivity_rows if row["profile"] == profile_name]
        counts = Counter(row["developability_grade"] for row in rows)
        sensitivity_summary_rows.append(
            {
                "profile": profile_name,
                "A_LOWER_RISK": counts["A_LOWER_RISK"],
                "B_REVIEW": counts["B_REVIEW"],
                "C_HIGH_RISK": counts["C_HIGH_RISK"],
                "thresholds_json": json.dumps(
                    PROFILES[profile_name], sort_keys=True, separators=(",", ":")
                ),
            }
        )
    transitions = Counter(
        (
            grade_by_sid_profile[(sid, "STRICT")]["developability_grade"],
            grade_by_sid_profile[(sid, "PRIMARY")]["developability_grade"],
            grade_by_sid_profile[(sid, "PERMISSIVE")]["developability_grade"],
        )
        for sid in sorted(submission_ids)
    )
    for key, count in sorted(transitions.items()):
        sensitivity_summary_rows.append(
            {
                "profile": "TRANSITION",
                "A_LOWER_RISK": "",
                "B_REVIEW": "",
                "C_HIGH_RISK": "",
                "thresholds_json": "",
                "strict_to_primary_to_permissive": ">".join(key),
                "candidate_count": count,
            }
        )
    sensitivity_summary_path = (
        args.output_dir / "Final50_ABC_threshold_sensitivity_summary.tsv"
    )
    write_tsv(sensitivity_summary_path, sensitivity_summary_rows)

    primary_rows = [
        grade_by_sid_profile[(row["submission_id"], "PRIMARY")]
        for row in enriched_freeze
    ]
    primary_path = args.output_dir / "Final50_revised_primary_ABC_grade.tsv"
    write_tsv(primary_path, primary_rows)
    poor_rows = [
        {
            "submission_id": row["submission_id"],
            "competition_rank_1_50": row["competition_rank_1_50"],
            "mechanism_rank_immutable": row["mechanism_rank_immutable"],
            "candidate_id": row["candidate_id"],
            "parent_cluster": row["parent_cluster"],
            "single_domain_suitability": grade_by_sid_profile[
                (row["submission_id"], "PRIMARY")
            ]["single_domain_suitability"],
            "poor_single_domain_split": grade_by_sid_profile[
                (row["submission_id"], "PRIMARY")
            ]["poor_single_domain_split"],
            "primary_grade": grade_by_sid_profile[
                (row["submission_id"], "PRIMARY")
            ]["developability_grade"],
            "primary_hard_fail_reasons": grade_by_sid_profile[
                (row["submission_id"], "PRIMARY")
            ]["hard_fail_reasons"],
            "primary_review_reasons": grade_by_sid_profile[
                (row["submission_id"], "PRIMARY")
            ]["review_reasons"],
            "policy": (
                "Poor/not-VHH-like on a documented patent-success Case02 scaffold "
                "is B review unless an independent hard risk is present; unsupported "
                "poor single-domain status is a C hard risk."
            ),
        }
        for row in enriched_freeze
    ]
    poor_path = args.output_dir / "Final50_poor_single_domain_split.tsv"
    write_tsv(poor_path, poor_rows)

    team_pair_rows = read_tsv(args.team_pairs)
    assert len(team_pair_rows) == 1225
    cdr3_identity: dict[frozenset[str], float] = {}
    for row in team_pair_rows:
        key = frozenset(
            (row["left_submission_id"], row["right_submission_id"])
        )
        cdr3_identity[key] = float(row["cdr3_identity"])

    by_sid = {row["submission_id"]: row for row in enriched_freeze}
    primary_a = sorted(
        (
            row
            for row in primary_rows
            if row["developability_grade"] == "A_LOWER_RISK"
        ),
        key=lambda row: int(row["mechanism_rank_immutable"]),
    )
    primary_b = sorted(
        (row for row in primary_rows if row["developability_grade"] == "B_REVIEW"),
        key=lambda row: int(row["mechanism_rank_immutable"]),
    )
    selected: list[dict[str, Any]] = []
    parent_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    attempted_reasons: dict[str, list[str]] = {}

    def allowed(row: dict[str, Any]) -> tuple[bool, list[str]]:
        freeze = by_sid[row["submission_id"]]
        reasons: list[str] = []
        if parent_counts[freeze["parent_cluster"]] >= 4:
            reasons.append("PARENT_CAP_4")
        if route_counts[freeze["route"]] >= 7:
            reasons.append("ROUTE_CAP_7")
        for chosen in selected:
            identity = cdr3_identity[
                frozenset((row["submission_id"], chosen["submission_id"]))
            ]
            if identity >= 0.80:
                reasons.append(
                    f"CDR3_MUSCLE_IDENTITY_GE_0P80_WITH_{chosen['submission_id']}"
                    f"({identity:.6f})"
                )
        return not reasons, reasons

    def add(row: dict[str, Any], role: str) -> None:
        freeze = by_sid[row["submission_id"]]
        selected.append({**row, "competition_top10_role": role})
        parent_counts[freeze["parent_cluster"]] += 1
        route_counts[freeze["route"]] += 1

    for row in primary_a:
        if len(selected) >= 8:
            break
        ok, reasons = allowed(row)
        attempted_reasons[row["submission_id"]] = reasons
        if ok:
            add(row, "A_PRIMARY_UNIFORM_QC")
    for row in primary_b:
        if len(selected) >= 10:
            break
        ok, reasons = allowed(row)
        attempted_reasons[row["submission_id"]] = reasons
        if ok:
            add(row, "B_HIGH_MECHANISM_LIMITED_UNIFORM_QC")
    selected_ids = {row["submission_id"] for row in selected}
    for row in primary_a:
        if len(selected) >= 10:
            break
        if row["submission_id"] in selected_ids:
            continue
        ok, reasons = allowed(row)
        attempted_reasons[row["submission_id"]] = reasons
        if ok:
            add(row, "A_DIVERSITY_BACKFILL_UNIFORM_QC")
            selected_ids.add(row["submission_id"])
    for row in primary_b:
        if len(selected) >= 10:
            break
        if row["submission_id"] in selected_ids:
            continue
        ok, reasons = allowed(row)
        attempted_reasons[row["submission_id"]] = reasons
        if ok:
            add(row, "B_LIMITED_BACKFILL_UNIFORM_QC")
            selected_ids.add(row["submission_id"])
    assert len(selected) == 10, f"could select only {len(selected)} Top10 candidates"
    selected_ids = {row["submission_id"] for row in selected}
    assert selected_ids == {
        f"PVRIG_CAND_{index:03d}" for index in range(1, 11)
    }, f"unexpected corrected Top10 membership: {sorted(selected_ids)}"

    top10_rows: list[dict[str, Any]] = []
    for priority, row in enumerate(selected, 1):
        freeze = by_sid[row["submission_id"]]
        top10_rows.append(
            {
                "competition_submission_priority": priority,
                "submission_id": row["submission_id"],
                "frozen_competition_rank_1_50": freeze["competition_rank_1_50"],
                "mechanism_rank_immutable": row["mechanism_rank_immutable"],
                "candidate_id": row["candidate_id"],
                "developability_grade": row["developability_grade"],
                "competition_top10_role": row["competition_top10_role"],
                "parent_cluster": freeze["parent_cluster"],
                "route": freeze["route"],
                "epitope_cluster_id": epitope_by_sid[row["submission_id"]][
                    "epitope_cluster_id"
                ],
                "selection_policy": (
                    "8 A first, then at most 2 B; C excluded; parent cap 4; "
                    "route cap 7; pairwise MUSCLE CDR3 identity <0.80"
                ),
                "claim_boundary": (
                    "Computational experiment-slot priority only; not measured "
                    "expression, purity, BLI, Kd, IC50, or blocking."
                ),
            }
        )
    top10_path = args.output_dir / "Final50_revised_Top10_priority.tsv"
    write_tsv(top10_path, top10_rows)

    exclusion_rows: list[dict[str, Any]] = []
    for row in primary_a:
        if row["submission_id"] in selected_ids:
            continue
        reasons = attempted_reasons.get(row["submission_id"], [])
        if reasons:
            exclusion = ";".join(reasons)
        else:
            exclusion = "TOP10_A_QUOTA_FILLED;LOWER_MECHANISM_PRIORITY"
        exclusion_rows.append(
            {
                "submission_id": row["submission_id"],
                "frozen_competition_rank_1_50": by_sid[row["submission_id"]][
                    "competition_rank_1_50"
                ],
                "mechanism_rank_immutable": row["mechanism_rank_immutable"],
                "candidate_id": row["candidate_id"],
                "primary_grade": row["developability_grade"],
                "explicit_exclusion_reason": exclusion,
                "selected_top10_count": 10,
                "selected_A_count": sum(
                    item["developability_grade"] == "A_LOWER_RISK"
                    for item in selected
                ),
                "policy": (
                    "Every primary-profile A candidate outside Top10 receives an "
                    "explicit quota/diversity exclusion reason."
                ),
            }
        )
    exclusion_path = args.output_dir / "Final50_A_not_Top10_exclusion_reasons.tsv"
    if exclusion_rows:
        write_tsv(exclusion_path, exclusion_rows)
    else:
        # Preserve a machine-readable header even if every A is selected.
        write_tsv(
            exclusion_path,
            [
                {
                    "submission_id": "",
                    "explicit_exclusion_reason": "NO_UNSELECTED_A_CANDIDATES",
                }
            ],
        )

    uniform_rows: list[dict[str, Any]] = []
    for freeze in enriched_freeze:
        sid = freeze["submission_id"]
        uniform_rows.append(
            {
                "submission_id": sid,
                "competition_rank_1_50": freeze["competition_rank_1_50"],
                "mechanism_rank_immutable": freeze["mechanism_rank_immutable"],
                "candidate_id": freeze["candidate_id"],
                "official_validator_pass": str(sid not in failed_by_sid).lower(),
                "official_validator_failure_details": json.dumps(
                    failed_by_sid.get(sid, []),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                **prefixed(screen_by_sid[sid], "uniform_", {"id"}),
                **prefixed(vhh_by_sid[sid], "uniform_seq_", {"id", "sequence"}),
            }
        )
    uniform_path = args.output_dir / "Final50_uniform_developability_evidence.tsv"
    write_tsv(uniform_path, uniform_rows)

    exclusion_by_sid = {
        row["submission_id"]: row["explicit_exclusion_reason"]
        for row in exclusion_rows
        if row.get("submission_id")
    }
    selected_by_sid = {row["submission_id"]: row for row in top10_rows}
    joined_rows: list[dict[str, Any]] = []
    for freeze in enriched_freeze:
        sid = freeze["submission_id"]
        cid = freeze["candidate_id"]
        joined_rows.append(
            {
                **freeze,
                "frozen_sequence_sha256_recomputed": hashlib.sha256(
                    freeze["sequence"].encode()
                ).hexdigest(),
                "official_validator_pass": str(sid not in failed_by_sid).lower(),
                "official_validator_failure_details": json.dumps(
                    failed_by_sid.get(sid, []),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                **prefixed(ranked_by_id[cid], "source_ranked_", {"candidate_id", "sequence"}),
                **prefixed(screen_by_sid[sid], "uniform_", {"id"}),
                **prefixed(vhh_by_sid[sid], "uniform_seq_", {"id", "sequence"}),
                **prefixed(positive_by_sid[sid], "positive_", {"submission_id", "candidate_id"}),
                **prefixed(nearest_by_sid[sid], "team_", {"submission_id", "candidate_id"}),
                **prefixed(structure_by_id[cid], "structure_", {"candidate_id"}),
                **prefixed(prefusion_by_id[cid], "prefusion_", {"candidate_id"}),
                **prefixed(epitope_by_sid[sid], "epitope_", {"submission_id", "candidate_id"}),
                "strict_developability_grade": grade_by_sid_profile[
                    (sid, "STRICT")
                ]["developability_grade"],
                "primary_developability_grade": grade_by_sid_profile[
                    (sid, "PRIMARY")
                ]["developability_grade"],
                "permissive_developability_grade": grade_by_sid_profile[
                    (sid, "PERMISSIVE")
                ]["developability_grade"],
                "primary_hard_fail_reasons": grade_by_sid_profile[
                    (sid, "PRIMARY")
                ]["hard_fail_reasons"],
                "primary_review_reasons": grade_by_sid_profile[
                    (sid, "PRIMARY")
                ]["review_reasons"],
                "poor_single_domain_split": grade_by_sid_profile[
                    (sid, "PRIMARY")
                ]["poor_single_domain_split"],
                "revised_top10_selected": str(sid in selected_by_sid).lower(),
                "revised_competition_submission_priority": selected_by_sid.get(
                    sid, {}
                ).get("competition_submission_priority", ""),
                "revised_top10_role": selected_by_sid.get(sid, {}).get(
                    "competition_top10_role", ""
                ),
                "A_not_Top10_exclusion_reason": exclusion_by_sid.get(sid, ""),
                "claim_boundary": (
                    "Joined computational evidence only. Mechanism rank and exact "
                    "sequences are frozen; no field is measured CHO yield, purity, "
                    "BLI response, Kd, IC50, avidity, or experimental blocking."
                ),
            }
        )
    joined_path = args.output_dir / "Final50_joined_evidence.tsv"
    write_tsv(joined_path, joined_rows)

    assert len(joined_rows) == 50
    assert all(
        row["sequence_sha256"] == row["frozen_sequence_sha256_recomputed"]
        for row in joined_rows
    )
    assert all(
        row["mechanism_rank_immutable"]
        == ranked_by_id[row["candidate_id"]]["mechanism_rank_immutable"]
        for row in joined_rows
    )
    assert len(uniform_rows) == 50
    assert len(sensitivity_rows) == 150
    assert len(poor_rows) == 50
    assert len(top10_rows) == 10
    assert len(exclusion_rows) == len(primary_a) - sum(
        row["developability_grade"] == "A_LOWER_RISK" for row in selected
    )

    outputs = [
        uniform_path,
        sensitivity_path,
        sensitivity_summary_path,
        primary_path,
        poor_path,
        top10_path,
        exclusion_path,
        joined_path,
    ]
    grade_counts = {
        profile: dict(
            Counter(
                row["developability_grade"]
                for row in sensitivity_rows
                if row["profile"] == profile
            )
        )
        for profile in PROFILES
    }
    receipt = {
        "schema_version": "qc397_final50_p0p1_joined_evidence_v1_1",
        "state": "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": 50,
        "official_validator_pass_count": 50 - len(failed_by_sid),
        "official_validator_fail_count": len(failed_by_sid),
        "uniform_pipeline_rows": len(uniform_rows),
        "instability_index_source": "vhh_eval.tsv",
        "instability_index_complete_count": sum(
            as_float(vhh_by_sid[sid].get("instability_index")) is not None
            for sid in submission_ids
        ),
        "sensitivity_rows": len(sensitivity_rows),
        "grade_counts": grade_counts,
        "poor_single_domain_split_counts": dict(
            Counter(row["poor_single_domain_split"] for row in poor_rows)
        ),
        "revised_top10_count": len(top10_rows),
        "revised_top10_grade_counts": dict(
            Counter(row["developability_grade"] for row in top10_rows)
        ),
        "A_not_Top10_exclusion_count": len(exclusion_rows),
        "mechanism_rank_changed": False,
        "full_hfc_construct_available": False,
        "profile_thresholds": PROFILES,
        "inputs": {
            str(path): sha256(path)
            for path in (
                args.freeze_tsv,
                args.ranked_tsv,
                args.screen_summary,
                args.vhh_eval_tsv,
                args.official_failed_reasons,
                args.positive_summary,
                args.team_pairs,
                args.team_nearest,
                args.structure_tsv,
                args.prefusion_tsv,
                args.epitope_tsv,
            )
        },
        "outputs": {path.name: sha256(path) for path in outputs},
        "claim_boundary": (
            "Categorical computational risk and experiment-slot prioritization; "
            "not experimental expression, purity, BLI, Kd, IC50, or blocking."
        ),
    }
    receipt_path = args.output_dir / "P0P1_JOINED_EVIDENCE_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
