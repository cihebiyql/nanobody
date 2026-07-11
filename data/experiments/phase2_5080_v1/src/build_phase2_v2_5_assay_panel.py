#!/usr/bin/env python3
"""Build the prospective 8x3 PVRIG assay panel required by V2.5."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_MUTANTS = WORKSPACE_ROOT / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
DEFAULT_POSITIVES = DATA_ROOT / "model_data/pvrig_blocker_positive_calibration_v0.csv"
DEFAULT_ENSEMBLE = EXP_DIR / "predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv"
DEFAULT_CANDIDATES = EXP_DIR / "data_splits/p3_optional_pose_manifest_v1.csv"
DEFAULT_CSV = EXP_DIR / "data_splits/pvrig_v2_5_prospective_assay_panel.csv"
DEFAULT_REPORT = EXP_DIR / "reports/PHASE2_V2_5_PROSPECTIVE_ASSAY_PANEL.md"

PANEL_VERSION = "pvrig_phase2_v2_5_prospective_assay_panel_v1"
TARGET_ID = "PVRIG_HUMAN_Q6DKI7"
TARGET_CONSTRUCT = "Q6DKI7_structural_ectodomain_proxy_39_171"
CLAIM_BOUNDARY = "prospective_unmeasured_panel_not_binding_or_blocker_validation"

FAMILY_GROUPS = [
    ("pvrig_family_20", "PVRIG-20", "mut_01_PVRIG-20_base_reference", "mut_02_PVRIG-20_cdr3_cons_F99Y", "mut_03_PVRIG-20_cdr3_arom_F99A"),
    ("pvrig_family_30", "PVRIG-30", "mut_07_PVRIG-30_base_reference", "mut_08_PVRIG-30_cdr3_cons_T101S", "mut_09_PVRIG-30_cdr3_arom_W100A"),
    ("pvrig_family_38", "PVRIG-38", "mut_12_PVRIG-38_base_reference", "mut_13_PVRIG-38_cdr3_cons_D99E", "mut_14_PVRIG-38_cdr3_arom_F100A"),
    ("pvrig_family_39", "PVRIG-39", "mut_17_PVRIG-39_base_reference", "mut_18_PVRIG-39_cdr3_cons_F99Y", "mut_19_PVRIG-39_cdr3_arom_F99A"),
]

NEGATIVE_VERIFICATION_IDS = [
    "mut_04_PVRIG-20_cdr3_center_ala_scan",
    "mut_10_PVRIG-30_cdr3_center_ala_scan",
    "mut_15_PVRIG-38_cdr3_center_ala_scan",
]

OUTPUT_COLUMNS = [
    "panel_version",
    "panel_order",
    "prospective_group_id",
    "group_type",
    "candidate_id",
    "candidate_role",
    "source_kind",
    "family_id",
    "mutation",
    "reference_sample_id",
    "vhh_sequence",
    "sequence_sha256",
    "target_id",
    "target_construct",
    "planned_binding_assay",
    "planned_blocking_assay",
    "planned_qc",
    "replicate_plan",
    "planned_evidence_level",
    "current_truth_status",
    "planned_comparison",
    "formal_use_if_pass",
    "exclusion_if_fail",
    "nonbinder_rule",
    "claim_boundary",
]


def normalize_sequence(value: object) -> str:
    sequence = "".join(str(value).split()).upper()
    if not sequence or any(residue not in "ACDEFGHIKLMNPQRSTVWY" for residue in sequence):
        raise ValueError(f"Invalid amino-acid sequence: {sequence[:40]!r}")
    return sequence


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


def mutate_1based(sequence: str, position: int, expected: str, replacement: str) -> str:
    sequence = normalize_sequence(sequence)
    index = position - 1
    if index < 0 or index >= len(sequence) or sequence[index] != expected:
        observed = sequence[index] if 0 <= index < len(sequence) else "OUT_OF_RANGE"
        raise ValueError(f"Mutation {expected}{position}{replacement} expected {expected}, observed {observed}")
    return sequence[:index] + replacement + sequence[index + 1 :]


def base_row(
    *,
    group_id: str,
    group_type: str,
    candidate_id: str,
    candidate_role: str,
    source_kind: str,
    family_id: str,
    sequence: str,
    mutation: str = "",
    reference_sample_id: str = "",
    current_truth_status: str = "PROSPECTIVE_UNMEASURED",
) -> dict[str, object]:
    sequence = normalize_sequence(sequence)
    comparison = {
        "paired_mutation_effect": "paired_delta_pKd_and_delta_pIC50_vs_same_group_reference",
        "binder_nonblocker_enrichment": "same_batch_binding_strength_and_competition_ranking",
        "verified_nonbinder_confirmation": "same_batch_no_binding_confirmation_after_expression_and_SEC_QC",
    }[group_type]
    return {
        "panel_version": PANEL_VERSION,
        "panel_order": 0,
        "prospective_group_id": group_id,
        "group_type": group_type,
        "candidate_id": candidate_id,
        "candidate_role": candidate_role,
        "source_kind": source_kind,
        "family_id": family_id,
        "mutation": mutation,
        "reference_sample_id": reference_sample_id,
        "vhh_sequence": sequence,
        "sequence_sha256": sequence_sha256(sequence),
        "target_id": TARGET_ID,
        "target_construct": TARGET_CONSTRUCT,
        "planned_binding_assay": "SPR_or_BLI_Kd_M_with_censoring_and_fit_QC",
        "planned_blocking_assay": "PVRIG_PVRL2_competition_IC50_nM_and_or_reporter_EC50_nM",
        "planned_qc": "sequence_hash|expression_yield|SEC_monomer_fraction|aggregation|target_construct_identity",
        "replicate_plan": ">=3_independent_runs_across_>=2_days_with_randomized_sample_order",
        "planned_evidence_level": "E6_PROSPECTIVE_BLINDED",
        "current_truth_status": current_truth_status,
        "planned_comparison": comparison,
        "formal_use_if_pass": "eligible_only_after_same_batch_complete_group_QC_and_prespecified_sealed_unblind",
        "exclusion_if_fail": "exclude_from_truth_lane_and_report_assay_or_expression_failure_reason",
        "nonbinder_rule": "no_concentration_dependent_binding_through_preregistered_max_analyte_in_all_replicates_after_expression_SEC_QC; assay_failure_is_not_negative",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _row_by_id(frame: pd.DataFrame, identifier: str) -> pd.Series:
    matches = frame[frame["mutant_name"].astype(str) == identifier]
    if len(matches) != 1:
        raise ValueError(f"Expected one mutant row for {identifier}, observed {len(matches)}")
    return matches.iloc[0]


def build_family_rows(mutants: pd.DataFrame, positives: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for group_id, family, reference_id, conservative_id, disruptive_id in FAMILY_GROUPS:
        reference = _row_by_id(mutants, reference_id)
        for source, role in [(reference, "known_positive_reference"), (_row_by_id(mutants, conservative_id), "conservative_mutant"), (_row_by_id(mutants, disruptive_id), "paratope_disruptive_mutant")]:
            rows.append(
                base_row(
                    group_id=group_id,
                    group_type="paired_mutation_effect",
                    candidate_id=str(source["mutant_name"]),
                    candidate_role=role,
                    source_kind="existing_mutant_panel",
                    family_id=family,
                    sequence=str(source["sequence"]),
                    mutation=str(source["mutations_1based"]),
                    reference_sample_id=reference_id,
                    current_truth_status="KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED" if role == "known_positive_reference" else "DESIGNED_MUTANT_UNMEASURED",
                )
            )

    hr151 = positives[positives["molecule_name"].astype(str) == "PVRIG-151_HR151"]
    if len(hr151) != 1:
        raise ValueError(f"Expected one PVRIG-151_HR151 calibration row, observed {len(hr151)}")
    base = normalize_sequence(hr151.iloc[0]["sequence"])
    reference_id = "case02_pos_01_PVRIG-151_HR151"
    variants = [
        (reference_id, "known_positive_reference", base, "none", "KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED"),
        ("prospective_HR151_cdr3_cons_Y116F", "conservative_mutant", mutate_1based(base, 116, "Y", "F"), "Y116F", "DESIGNED_MUTANT_UNMEASURED"),
        ("prospective_HR151_cdr3_arom_Y116A", "paratope_disruptive_mutant", mutate_1based(base, 116, "Y", "A"), "Y116A", "DESIGNED_MUTANT_UNMEASURED"),
    ]
    for candidate_id, role, sequence, mutation, truth in variants:
        rows.append(
            base_row(
                group_id="pvrig_family_151",
                group_type="paired_mutation_effect",
                candidate_id=candidate_id,
                candidate_role=role,
                source_kind="known_positive_plus_preregistered_mutation",
                family_id="151",
                sequence=sequence,
                mutation=mutation,
                reference_sample_id=reference_id,
                current_truth_status=truth,
            )
        )
    return rows


def build_binder_nonblocker_rows(ensemble: pd.DataFrame, candidates: pd.DataFrame) -> list[dict[str, object]]:
    candidate_columns = candidates[["candidate_id", "vhh_seq", "leakage_label"]].drop_duplicates("candidate_id")
    ranked = ensemble.merge(candidate_columns, on="candidate_id", how="left", validate="one_to_one")
    ranked = ranked.sort_values("consensus_rank")
    ranked = ranked[ranked["leakage_label"].astype(str) == "NO_KNOWN_POSITIVE_LEAKAGE"]
    ranked = ranked.dropna(subset=["vhh_seq"]).drop_duplicates("vhh_seq").head(6)
    if len(ranked) != 6:
        raise ValueError(f"Expected six de novo candidates for binder/nonblocker screening, observed {len(ranked)}")
    rows: list[dict[str, object]] = []
    for index, (_, source) in enumerate(ranked.iterrows()):
        group_suffix = "A" if index < 3 else "B"
        rows.append(
            base_row(
                group_id=f"pvrig_binder_nonblocker_screen_{group_suffix}",
                group_type="binder_nonblocker_enrichment",
                candidate_id=str(source["candidate_id"]),
                candidate_role="de_novo_binding_and_competition_screen",
                source_kind="v2_4_multiseed_candidate",
                family_id=f"de_novo_screen_{group_suffix}",
                sequence=str(source["vhh_seq"]),
            )
        )
    return rows


def build_negative_verification_rows(mutants: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for identifier in NEGATIVE_VERIFICATION_IDS:
        source = _row_by_id(mutants, identifier)
        rows.append(
            base_row(
                group_id="pvrig_verified_nonbinder_confirmation",
                group_type="verified_nonbinder_confirmation",
                candidate_id=identifier,
                candidate_role="negative_verification_candidate_not_current_negative",
                source_kind="existing_strong_cdr3_alanine_scan",
                family_id=str(source["family"]),
                sequence=str(source["sequence"]),
                mutation=str(source["mutations_1based"]),
                reference_sample_id=str(source["base_molecule"]),
                current_truth_status="DESIGNED_NEGATIVE_CONTROL_UNMEASURED_NOT_VERIFIED",
            )
        )
    return rows


def validate_panel(panel: pd.DataFrame) -> None:
    if list(panel.columns) != OUTPUT_COLUMNS:
        raise ValueError("Prospective panel columns do not match the V2.5 contract")
    if len(panel) != 24 or panel["prospective_group_id"].nunique() != 8:
        raise ValueError("V2.5 prospective panel must contain exactly 8 groups x 3 candidates")
    sizes = panel.groupby("prospective_group_id").size()
    if not sizes.eq(3).all():
        raise ValueError(f"Every prospective group must contain three candidates: {sizes.to_dict()}")
    if panel["candidate_id"].duplicated().any() or panel["sequence_sha256"].duplicated().any():
        raise ValueError("Prospective panel candidate IDs and sequences must be unique")
    if panel["claim_boundary"].ne(CLAIM_BOUNDARY).any():
        raise ValueError("Prospective panel claim boundary was weakened")
    forbidden_truth = panel["current_truth_status"].str.contains("VERIFIED_NONBINDER|VERIFIED_NON-BINDER", case=False, regex=True)
    if forbidden_truth.any():
        raise ValueError("Unmeasured negative-verification candidates cannot be labeled verified non-binders")


def write_report(panel: pd.DataFrame, path: Path) -> None:
    group_counts = panel.groupby("group_type")["prospective_group_id"].nunique().to_dict()
    lines = [
        "# Phase 2 V2.5 Prospective PVRIG Assay Panel",
        "",
        "Current target verdict: **DATA_NOT_READY_FOR_TARGET_MODEL**.",
        "",
        "This 24-pair panel is a preregistered acquisition plan, not experimental evidence. No row becomes E6 truth until binding, competition, and QC measurements are complete and the sealed labels are unblinded once.",
        "",
        "## Panel Shape",
        "",
        f"- Total: {len(panel)} VHH-PVRIG pairs in {panel['prospective_group_id'].nunique()} groups of three.",
        f"- Paired mutation-effect groups: {group_counts.get('paired_mutation_effect', 0)}.",
        f"- Binder/nonblocker enrichment groups: {group_counts.get('binder_nonblocker_enrichment', 0)}.",
        f"- Verified-nonbinder confirmation groups: {group_counts.get('verified_nonbinder_confirmation', 0)}.",
        "- Required measurements: SPR/BLI Kd, PVRIG-PVRL2 competition IC50 and/or reporter EC50, plus expression/SEC/aggregation QC.",
        "- Replication: at least three independent runs across at least two days with randomized sample order.",
        "",
        "## Gate Rule",
        "",
        "A designed disruptive or alanine-scan sequence is not a negative. It can become a verified nonbinder only after concentration-dependent binding is absent through the preregistered maximum analyte concentration in all replicates and expression/SEC QC passes. Assay or expression failure remains excluded, not relabeled.",
        "",
        "## Groups",
        "",
    ]
    for group_id, group in panel.groupby("prospective_group_id", sort=False):
        lines.append(f"### {group_id}")
        lines.append("")
        for _, row in group.iterrows():
            lines.append(f"- `{row['candidate_id']}` - {row['candidate_role']} - current status: `{row['current_truth_status']}`")
        lines.append("")
    lines.extend(["## Claim Boundary", "", f"`{CLAIM_BOUNDARY}`", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_panel(args: argparse.Namespace) -> pd.DataFrame:
    mutants = pd.read_csv(args.mutants)
    positives = pd.read_csv(args.positives)
    ensemble = pd.read_csv(args.ensemble)
    candidates = pd.read_csv(args.candidates)
    rows = build_family_rows(mutants, positives)
    rows.extend(build_binder_nonblocker_rows(ensemble, candidates))
    rows.extend(build_negative_verification_rows(mutants))
    for index, row in enumerate(rows, start=1):
        row["panel_order"] = index
    panel = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    validate_panel(panel)
    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.csv_out, index=False)
    write_report(panel, args.report_out)
    return panel


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutants", type=Path, default=DEFAULT_MUTANTS)
    parser.add_argument("--positives", type=Path, default=DEFAULT_POSITIVES)
    parser.add_argument("--ensemble", type=Path, default=DEFAULT_ENSEMBLE)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main() -> None:
    panel = build_panel(parse_args())
    print({"status": "PASS", "rows": len(panel), "groups": panel["prospective_group_id"].nunique(), "claim_boundary": CLAIM_BOUNDARY})


if __name__ == "__main__":
    main()
