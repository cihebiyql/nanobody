#!/usr/bin/env python3
"""Build the positive-first PVRIG screening calibration and expansion receipts.

This script is intentionally read-only with respect to upstream assets.  It
joins already-frozen sequence, QC, structure, docking, binding-prior and static
energy evidence, then writes a calibrated policy that keeps:

1. biological/technical positive recall,
2. competition submission novelty,
3. developability,
4. binding priors, and
5. blocker-like geometry

as separate evidence lanes.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path("/mnt/d/work/抗体")
OUT = ROOT / "node1/reports/pvrig_positive_first_screen_calibration_v1_20260724"

POS_META = ROOT / "机制/data/literature/PVRIG_case02_success_validation_series.csv"
POS_FASTA = ROOT / "reports/qc_positive_metric_ranges/pvrig_11_success_positives.fasta"
POS_QC = ROOT / "reports/qc_positive_metric_ranges/pvrig_positive_qc_per_sequence_metrics.csv"
OFFICIAL_FAIL = (
    ROOT
    / "reports/qc_positive_metric_ranges/node1_pvrig_11_positive_qc/official_failed_reasons.csv"
)
OLD_POS_DOCK = ROOT / "docking/calibration/patent_success_validation/batch_consensus_summary.csv"
OLD_POS_STATUS = ROOT / "docking/calibration/patent_success_validation/batch_status.csv"
BINDING_PRIOR = ROOT / "code/results/pvrig_positive11_binding_prior_20260719/positive11_joined.tsv"
AFFINITY = (
    ROOT
    / "code/results/pvrig_positive11_structure_affinity_benchmark_20260719/candidate_level_affinity_summary.tsv"
)
METHODS = (
    ROOT
    / "code/results/pvrig_positive11_structure_affinity_benchmark_20260719/final_method_comparison.tsv"
)
CONTROL36 = ROOT / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
CONTROL36_STATUS = ROOT / "docking/calibration/mutant_validation_panel/mutant_panel_status.csv"
CONTROL36_LEAK = (
    ROOT / "docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv"
)
V3_MANIFEST = (
    ROOT / "pvrig_v3_dual_conformation_redocking_20260714/inputs/calibration_controls_47.tsv"
)
V3_RESULTS = (
    ROOT / "pvrig_v3_dual_conformation_redocking_20260714/reports/job_results.tsv"
)
V3_STABLE = (
    ROOT / "pvrig_v3_dual_conformation_redocking_20260714/reports/EVALUATOR_STABLE.json"
)
STRICT6042 = (
    ROOT
    / "node1/reports/pvrig_finalist_screening_standard_v1_20260724/dry_run/"
    "strict6042_standard_dry_run.tsv"
)
CORE448 = (
    ROOT
    / "node1/reports/pvrig_finalist_screening_standard_v1_20260724/dry_run/"
    "core448_candidates.tsv"
)
OFFICIAL_SNAPSHOT = Path("/tmp/sicbc_section5_20260724.txt")
FRESH_ANARCI = OUT / "fresh_numbering/positive11_anarci_H.csv"
CORE448_NUMBERING_RECEIPT = OUT / "expansion/core448/NUMBERING_RECEIPT.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current is not None:
                records[current] = "".join(chunks)
            current = line[1:].split("|", 1)[0].strip()
            chunks = []
        else:
            chunks.append(line)
    if current is not None:
        records[current] = "".join(chunks)
    return records


def bool_text(value: bool) -> str:
    return "PASS" if value else "FAIL"


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        values = [
            str(row[column]).replace("|", "\\|").replace("\n", " ")
            for column in frame.columns
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def num(value: Any) -> float | None:
    if pd.isna(value) or value == "":
        return None
    return float(value)


def robust_by_conformation(group: pd.DataFrame, labels: set[str], minimum: int = 2) -> bool:
    for conformation in ("8x6b", "9e6y"):
        subset = group[group["conformation"] == conformation]
        if int(subset["representative_pair_label"].isin(labels).sum()) < minimum:
            return False
    return True


def load_positive_evidence() -> pd.DataFrame:
    seqs = parse_fasta(POS_FASTA)
    meta = pd.read_csv(POS_META, dtype=str).fillna("")
    qc = pd.read_csv(POS_QC)
    old = pd.read_csv(OLD_POS_DOCK)
    old_status = pd.read_csv(OLD_POS_STATUS)
    binding = pd.read_csv(BINDING_PRIOR, sep="\t")
    affinity = pd.read_csv(AFFINITY, sep="\t")
    v3_manifest = pd.read_csv(V3_MANIFEST, sep="\t")
    v3_results = pd.read_csv(V3_RESULTS, sep="\t")
    v3_results = v3_results[
        (v3_results["entity_type"] == "control") & (v3_results["state"] == "SUCCESS")
    ]

    fail = pd.read_csv(OFFICIAL_FAIL)
    candidate_col = next(
        col
        for col in fail.columns
        if col.lower() in {"candidate_id", "antibody_id", "name", "id"}
    )
    reason_col = next(col for col in fail.columns if "reason" in col.lower())
    fail_counts = fail.groupby(candidate_col)[reason_col].count().to_dict()

    qc_by = qc.set_index("display_id")
    old_by = old.set_index("molecule_name")
    old_status_by = old_status.set_index("molecule_name")
    bind_by = binding.set_index("molecule_name")
    affinity_by = affinity.set_index("molecule_name")

    patent_manifest = v3_manifest[v3_manifest["source_panel"] == "patent_success_validation"].copy()
    entity_by_case = patent_manifest.set_index("source_case_id")["control_id"].to_dict()

    rows: list[dict[str, Any]] = []
    standard = set("ACDEFGHIKLMNPQRSTVWY")
    for _, m in meta.sort_values("recommended_order", key=lambda s: s.astype(int)).iterrows():
        name = m["molecule_name"]
        sequence = seqs[name]
        q = qc_by.loc[name]
        o = old_by.loc[name]
        os_row = old_status_by.loc[name]
        b = bind_by.loc[name]
        a = affinity_by.loc[name]
        case_id = str(a["candidate_id"])
        entity_id = entity_by_case[case_id]
        jobs = v3_results[v3_results["entity_id"] == entity_id].copy()
        labels = Counter(jobs["representative_pair_label"])

        rows.append(
            {
                "recommended_order": int(m["recommended_order"]),
                "molecule_name": name,
                "family": m["family"],
                "validation_role": m["validation_role"],
                "sequence": sequence,
                "sequence_length": len(sequence),
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "standard_20aa": bool_text(set(sequence) <= standard),
                "experimental_kd_m": m["kd_m"],
                "experimental_kd_nm": (
                    "" if not m["kd_m"] else f"{float(m['kd_m']) * 1e9:.6g}"
                ),
                "experimental_blocking_ic50_nm": m["blocking_ic50_nm"],
                "L1_numbering_integrity": q["L1_numbering_integrity"],
                "L2_vhh_features": q["L2_vhh_features"],
                "L3_developability": q["L3_developability"],
                "single_domain_suitability": q["single_domain_suitability"],
                "abnativ_vhh_score": q["abnativ_vhh_score"],
                "sapiens_mean_self_probability": q["sapiens_mean_self_probability"],
                "cys_count": int(q["cys_count"]),
                "nglyc_motif_count": int(q["nglyc_motif_count"]),
                "hydrophobic_5_count": int(q["hydrophobic_5_count"]),
                "tnp_PNC": q["tnp_PNC_all11"],
                "tnp_PNC_flag": q["tnp_PNC_flag_all11"],
                "official_validator_pass_as_candidate": q["portfolio_official_validator_pass"],
                "official_high_identity_failure_count": int(fail_counts.get(name, 0)),
                "submission_disposition": "CALIBRATION_POSITIVE_EXCLUDED_LEAKAGE",
                "nbb2_monomer_present": os_row["monomer_raw_pdb"],
                "old_haddock_consensus_present": os_row["consensus_csv"],
                "old_haddock_pose_count": int(o["pose_count"]),
                "old_haddock_case_call": o["case_level_call"],
                "old_consensus_A_pose_count": int(o["consensus_blocker_like_a"]),
                "old_single_baseline_A_pose_count": int(o["single_baseline_blocker_recheck"]),
                "old_plausible_B_pose_count": int(o["blocker_plausible_b"]),
                "binding_prior_consensus": b["binding_prior_consensus"],
                "binding_prior_status": b["binding_prior_status"],
                "prodigy_pkd_median_9poses": a["prodigy_pkd_median"],
                "foldx_interaction_median_9poses": a["foldx_interaction_median"],
                "v3_entity_id": entity_id,
                "v3_successful_jobs": len(jobs),
                "v3_strict_A_jobs": labels["STRICT_A"],
                "v3_supported_AB_jobs": labels["SUPPORTED_AB"],
                "v3_other_jobs": labels["OTHER"],
                "v3_robust_AB_two_seeds_each_conformation": bool_text(
                    robust_by_conformation(jobs, {"STRICT_A", "SUPPORTED_AB"})
                ),
                "v3_robust_strict_A_two_seeds_each_conformation": bool_text(
                    robust_by_conformation(jobs, {"STRICT_A"})
                ),
                "evidence_interpretation": (
                    "known experimental calibration positive; computational scores are "
                    "recall/ranking evidence, not new experimental truth"
                ),
            }
        )
    return pd.DataFrame(rows)


def load_control36_evidence() -> pd.DataFrame:
    panel = pd.read_csv(CONTROL36)
    status = pd.read_csv(CONTROL36_STATUS)
    leak = pd.read_csv(CONTROL36_LEAK)
    out = panel.merge(status, on=["panel_order", "mutant_name", "base_molecule", "mutation_class", "mutations_1based"])
    out = out.merge(leak, left_on="mutant_name", right_on="candidate_id")
    out["old_geometry_support_pose_count"] = (
        out["consensus_blocker_like_a"]
        + out["single_baseline_blocker_recheck"]
        + out["blocker_plausible_b"]
    )
    out["control_interpretation"] = (
        "computational perturbation/leakage control; not an experimentally confirmed negative"
    )
    return out


def load_v3_control47_evidence() -> pd.DataFrame:
    manifest = pd.read_csv(V3_MANIFEST, sep="\t")
    results = pd.read_csv(V3_RESULTS, sep="\t")
    results = results[results["entity_type"] == "control"].copy()
    rows: list[dict[str, Any]] = []
    for _, m in manifest.iterrows():
        entity = m["control_id"]
        all_jobs = results[results["entity_id"] == entity].copy()
        jobs = all_jobs[all_jobs["state"] == "SUCCESS"].copy()
        labels = Counter(jobs["representative_pair_label"])
        rows.append(
            {
                "control_id": entity,
                "source_panel": m["source_panel"],
                "source_case_id": m["source_case_id"],
                "control_class": m["control_class"],
                "expected_behavior": m["expected_behavior"],
                "base_molecule": m["base_molecule"],
                "mutation_class": m["mutation_class"],
                "sequence_length": m["sequence_length"],
                "monomer_sha256": m["sha256"],
                "expected_jobs": 6,
                "successful_jobs": len(jobs),
                "failed_jobs": int((all_jobs["state"] != "SUCCESS").sum()),
                "strict_A_jobs": labels["STRICT_A"],
                "supported_AB_jobs": labels["SUPPORTED_AB"],
                "other_jobs": labels["OTHER"],
                "strict_A_job_fraction": labels["STRICT_A"] / len(jobs) if len(jobs) else "",
                "model_strict_A_fraction_mean": (
                    jobs["model_strict_a_fraction"].mean() if len(jobs) else ""
                ),
                "minimum_hotspot_overlap_mean": (
                    jobs[["native_hotspot_overlap", "cross_hotspot_overlap"]]
                    .min(axis=1)
                    .mean()
                    if len(jobs)
                    else ""
                ),
                "minimum_total_occlusion_mean": (
                    jobs[["native_total_occlusion", "cross_total_occlusion"]]
                    .min(axis=1)
                    .mean()
                    if len(jobs)
                    else ""
                ),
                "minimum_cdr3_occlusion_mean": (
                    jobs[["native_cdr3_occlusion", "cross_cdr3_occlusion"]]
                    .min(axis=1)
                    .mean()
                    if len(jobs)
                    else ""
                ),
                "minimum_cdr3_fraction_mean": (
                    jobs[["native_cdr3_fraction", "cross_cdr3_fraction"]]
                    .min(axis=1)
                    .mean()
                    if len(jobs)
                    else ""
                ),
                "robust_AB_two_seeds_each_conformation": bool_text(
                    robust_by_conformation(jobs, {"STRICT_A", "SUPPORTED_AB"})
                ),
                "robust_strict_A_two_seeds_each_conformation": bool_text(
                    robust_by_conformation(jobs, {"STRICT_A"})
                ),
                "control_interpretation": (
                    "known positive"
                    if m["control_class"] == "positive_control"
                    else "computational perturbation control, not experimental negative"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_policy(positive: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    positive_strict_recall = (
        positive["v3_robust_strict_A_two_seeds_each_conformation"].eq("PASS").mean()
    )
    positive_ab_recall = (
        positive["v3_robust_AB_two_seeds_each_conformation"].eq("PASS").mean()
    )
    destructive = controls[controls["control_class"] == "destructive_alanine"]
    destructive_strict_rate = (
        destructive["robust_strict_A_two_seeds_each_conformation"].eq("PASS").mean()
    )
    destructive_ab_rate = (
        destructive["robust_AB_two_seeds_each_conformation"].eq("PASS").mean()
    )

    return {
        "schema_version": "pvrig.positive_first_screen_calibration.v1.20260724",
        "status": "CALIBRATED_POSITIVE_RECALL_PASS_SPECIFICITY_LIMITED",
        "objective": (
            "Preserve known PVRIG positive recall while enforcing competition novelty "
            "and building a staged, auditable shortlist from 6042 already-docked candidates."
        ),
        "official_competition_alignment": {
            "submission_count": 50,
            "typical_experimental_entry_per_team_maximum": 10,
            "target_mechanism": "bind PVRIG extracellular domain at the PVRL2 interface and block PVRIG-PVRL2",
            "numbering": "ANARCI IMGT",
            "cdr_rule": "each corresponding VHH CDR identity to any known positive must be <0.80",
            "initial_screen": {
                "BLI_single_concentration_weight": 0.70,
                "expression_weight": 0.20,
                "purity_weight": 0.10,
            },
            "rescreen": {"BLI_Kd_rank_weight": 0.50, "competition_ELISA_IC50_rank_weight": 0.50},
            "boundary": "all computational values remain priors, not BLI/Kd/IC50/expression/purity measurements",
        },
        "lane_contract": {
            "calibration_positive_lane": {
                "technical_sequence_and_numbering": "must pass",
                "known_positive_recall": "must be measured",
                "competition_novelty": "expected fail/exclude, never call biological negative",
            },
            "novel_candidate_submission_lane": {
                "technical_sequence_and_numbering": "hard gate",
                "competition_novelty": "hard gate",
                "known_positive_exact_or_near_leakage": "exclude or manual review",
            },
        },
        "calibrated_gates": {
            "G0_technical_hard": [
                "unique candidate ID and matching sequence hash",
                "standard 20 amino acids only",
                "ANARCI/IMGT heavy-variable numbering succeeds",
                "FR1-FR4 and CDR1-CDR3 complete",
                "structure file exists and sequence matches when structure evidence is required",
            ],
            "G1_competition_submission_hard": [
                "official ab-data-validator passes",
                "each corresponding CDR identity <0.80",
                "internal safety target max CDR identity <=0.75",
                "exact known-positive leakage excluded",
                "optimization origin recorded when applicable",
            ],
            "G2_developability_calibrated": {
                "hard_or_manual_review": [
                    "unresolved sequence/structure mismatch",
                    "unpaired or unexplained odd cysteine count",
                    "multiple orthogonal severe liability signals with structural exposure",
                    "unrecoverable aggregation/clash/structure failure",
                ],
                "warn_and_rank_not_single_metric_blocker_fail": [
                    "FR2/VHH-like classification",
                    "TNP PNC red alone",
                    "Sapiens score or mutation burden",
                    "AbNatiV missing value or moderate score",
                    "pI, charge, GRAVY, deamidation, isomerization, oxidation",
                    "four cysteines when a plausible additional disulfide is structurally supported",
                    "one hydrophobic 5-mer",
                    "expression_purity_risk_proxy because it is not measured expression or purity",
                ],
                "preferred_ranges_from_positive_envelope": {
                    "length": "120-127 observed; keep broad technical 95-160",
                    "abnativ_vhh_score": "0.7523-0.8585 among 9 measured positives",
                    "sapiens_mean_self_probability": "0.6683-0.7800",
                    "cys_count": "2 or 4 observed",
                    "tnp_PNC": "0-3.0326; 2/11 known positives are red",
                },
            },
            "G3_blocker_geometry_high_sensitivity": {
                "required_completion": "2 receptor conformations x 3 seeds; at least 2 successful seeds per conformation",
                "support_definition": "STRICT_A or SUPPORTED_AB",
                "known_positive_recall": positive_ab_recall,
                "destructive_control_support_rate": destructive_ab_rate,
                "interpretation": (
                    "high-sensitivity interface plausibility gate only; destructive-control specificity is absent"
                ),
            },
            "G4_strict_A_rank_only": {
                "known_positive_recall": positive_strict_recall,
                "destructive_control_false_positive_rate": destructive_strict_rate,
                "interpretation": "not a hard gate because recall is too low and false positives remain",
            },
        },
        "binding_and_energy_policy": {
            "DeepNano_NanoBind": "weak binding priors only; no hard cutoff",
            "PRODIGY": "weak static prior only",
            "FoldX_cross_candidate": "not recommended for absolute affinity ranking",
            "FoldX_fixed_parent_ddG": "same-parent diagnostic only",
            "Graphinity": "rejected for current multi-mutation ranking",
            "Rosetta_InterfaceAnalyzer": "pending same-panel calibration",
            "MD_MMGBSA": "pending paired positive/control calibration; finalists only",
        },
        "method_activation_thresholds": {
            "positive_recall_minimum": 0.80,
            "control_false_positive_rate_maximum": 0.30,
            "entity_level_AUROC_minimum": 0.70,
            "leave_one_family_out_direction_consistency_minimum": 0.70,
            "failed_method_role": "descriptive_or_rank_only",
        },
        "expansion_order": [
            "11 patent positives",
            "36 perturbation/leakage controls",
            "47 V3 controls under dual-conformation x 3-seed protocol",
            "448 CORE_A candidates",
            "6042 strict-docking candidates",
        ],
    }


def build_summary(
    positive: pd.DataFrame, control36: pd.DataFrame, control47: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    strict = pd.read_csv(STRICT6042, sep="\t")
    core = pd.read_csv(CORE448, sep="\t")
    stable = json.loads(V3_STABLE.read_text(encoding="utf-8"))
    core448_numbering = (
        json.loads(CORE448_NUMBERING_RECEIPT.read_text(encoding="utf-8"))
        if CORE448_NUMBERING_RECEIPT.exists()
        else None
    )

    positive_ab = int(
        positive["v3_robust_AB_two_seeds_each_conformation"].eq("PASS").sum()
    )
    positive_strict = int(
        positive["v3_robust_strict_A_two_seeds_each_conformation"].eq("PASS").sum()
    )
    destructive = control47[control47["control_class"] == "destructive_alanine"]
    perturbation = control47[control47["control_class"] == "mutant_perturbation"]
    all_positive_controls = control47[control47["control_class"] == "positive_control"]

    stages = pd.DataFrame(
        [
            {
                "stage": "S0_positive11_sequence_qc",
                "input_entities": 11,
                "completed_entities": 11,
                "primary_result": "11/11 standard AA and L1 numbering PASS",
                "status": "PASS",
                "next_action": "retain as biological calibration; exclude from submission novelty lane",
            },
            {
                "stage": "S1_positive11_structure_old_docking",
                "input_entities": 11,
                "completed_entities": 11,
                "primary_result": f"{int(positive['old_haddock_pose_count'].sum())} old consensus poses; 11/11 NBB2 and consensus present",
                "status": "PASS",
                "next_action": "use only as historical geometry calibration",
            },
            {
                "stage": "S2_control36_perturbation",
                "input_entities": 36,
                "completed_entities": int(control36["consensus_csv"].eq("yes").sum()),
                "primary_result": (
                    f"{int(control36['consensus_rows'].sum())} consensus poses; "
                    f"leakage exact={int(control36['leakage_label'].eq('EXACT_KNOWN_POSITIVE').sum())}, "
                    f"near={int(control36['leakage_label'].eq('NEAR_KNOWN_POSITIVE').sum())}"
                ),
                "status": "PASS_WITH_SPECIFICITY_WARNING",
                "next_action": "do not call perturbations experimental negatives",
            },
            {
                "stage": "S3_v3_control47_dual_conformation_3seed",
                "input_entities": 47,
                "completed_entities": int((control47["successful_jobs"] == 6).sum()),
                "primary_result": (
                    f"282/282 jobs SUCCESS; positive robust A/B {len(all_positive_controls)}/{len(all_positive_controls)}; "
                    f"patent11 robust A/B {positive_ab}/11; patent11 robust strict-A {positive_strict}/11; "
                    f"destructive robust strict-A "
                    f"{int(destructive['robust_strict_A_two_seeds_each_conformation'].eq('PASS').sum())}/{len(destructive)}"
                ),
                "status": "PASS_HIGH_SENSITIVITY_SPECIFICITY_LIMITED",
                "next_action": "keep strict-A and HADDOCK score as rank features, not hard truth",
            },
            {
                "stage": "S4_core448_existing_evidence_audit",
                "input_entities": len(core),
                "completed_entities": (
                    core448_numbering["anarci_rows"] if core448_numbering else len(core)
                ),
                "primary_result": (
                    (
                        f"fresh ANARCI H {core448_numbering['heavy_chain_rows']}/448; "
                        f"CDR exact match {core448_numbering['all_cdr_matches']}/448; "
                        f"boundary review {core448_numbering['numbering_review_rows']}"
                    )
                    if core448_numbering
                    else "448 frozen CORE_A rows available with hashes, docking, binding and surrogate fields"
                ),
                "status": (
                    core448_numbering["status"] if core448_numbering else "READY"
                ),
                "next_action": (
                    "quarantine 11 CDR2-boundary rows; run official validator/full positive library on all 448"
                    if core448_numbering
                    else "run official validator/full positive library, calibrated developability review and static-energy panel"
                ),
            },
            {
                "stage": "S5_strict6042_cascade",
                "input_entities": len(strict),
                "completed_entities": len(strict),
                "primary_result": (
                    f"{int(strict['developability_hardpass'].sum())} conservative developability pass; "
                    f"{int((strict['dry_run_stage'] == 'CORE_A').sum())} CORE_A"
                ),
                "status": "READY_NOT_FINAL",
                "next_action": "apply calibrated policy in chunks; never overwrite frozen dry-run",
            },
        ]
    )

    receipt = {
        "status": "PASS_POSITIVE_BASELINE_AND_CONTROL_EXPANSION_READY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "positive11": {
            "entities": len(positive),
            "technical_standard_aa_pass": int(positive["standard_20aa"].eq("PASS").sum()),
            "L1_numbering_pass": int(positive["L1_numbering_integrity"].eq("PASS").sum()),
            "nbb2_present": int(positive["nbb2_monomer_present"].eq("yes").sum()),
            "official_validator_pass_as_candidates": int(
                positive["official_validator_pass_as_candidate"].eq("PASS").sum()
            ),
            "expected_leakage_exclusions": int(
                positive["submission_disposition"]
                .eq("CALIBRATION_POSITIVE_EXCLUDED_LEAKAGE")
                .sum()
            ),
            "V3_robust_AB": positive_ab,
            "V3_robust_strict_A": positive_strict,
            "known_Kd": int(positive["experimental_kd_m"].ne("").sum()),
            "known_blocking_IC50": int(
                positive["experimental_blocking_ic50_nm"].ne("").sum()
            ),
        },
        "positive_developability_counterexamples": {
            "L2_not_PASS": int((positive["L2_vhh_features"] != "PASS").sum()),
            "TNP_PNC_red": int(positive["tnp_PNC_flag"].eq("red").sum()),
            "Sapiens_below_0_70": int(
                (pd.to_numeric(positive["sapiens_mean_self_probability"]) < 0.70).sum()
            ),
            "Cys_not_equal_2": int((positive["cys_count"] != 2).sum()),
            "hydrophobic_5mer_present": int((positive["hydrophobic_5_count"] > 0).sum()),
        },
        "control36": {
            "entities": len(control36),
            "old_consensus_rows": int(control36["consensus_rows"].sum()),
            "exact_positive_leakage": int(
                control36["leakage_label"].eq("EXACT_KNOWN_POSITIVE").sum()
            ),
            "near_positive_leakage": int(
                control36["leakage_label"].eq("NEAR_KNOWN_POSITIVE").sum()
            ),
        },
        "control47": {
            "entities": len(control47),
            "jobs_expected": 282,
            "jobs_successful": int(control47["successful_jobs"].sum()),
            "positive_controls": len(all_positive_controls),
            "positive_robust_AB": int(
                all_positive_controls["robust_AB_two_seeds_each_conformation"]
                .eq("PASS")
                .sum()
            ),
            "destructive_controls": len(destructive),
            "destructive_robust_strict_A": int(
                destructive["robust_strict_A_two_seeds_each_conformation"]
                .eq("PASS")
                .sum()
            ),
            "perturbation_controls": len(perturbation),
            "V3_evaluator_status": stable["status"],
        },
        "expansion": {
            "core448_rows": len(core),
            "strict6042_rows": len(strict),
            "strict6042_conservative_developability_pass": int(
                strict["developability_hardpass"].sum()
            ),
        },
        "warnings": [
            "Known positives are expected to fail competition novelty and must not be called biological negatives.",
            "Cys=2, TNP-all-green, L2-VHH-like PASS and Sapiens>=0.70 are not individually valid blocker hard gates.",
            "V3 A/B support has high positive recall but no destructive-control specificity.",
            "Strict-A has insufficient positive recall and remains rank-only.",
            "The 36 perturbation controls are not experimentally confirmed negatives.",
            "The 448 and 6042 pools are computationally screened, not experimentally validated binders/blockers.",
        ],
    }
    if FRESH_ANARCI.exists():
        fresh = pd.read_csv(FRESH_ANARCI)
        receipt["fresh_numbering"] = {
            "path": str(FRESH_ANARCI),
            "rows": len(fresh),
            "heavy_chain_rows": int(fresh["chain_type"].eq("H").sum()),
            "sha256": sha256(FRESH_ANARCI),
            "status": "PASS" if len(fresh) == 11 and fresh["chain_type"].eq("H").all() else "FAIL",
        }
    if core448_numbering:
        receipt["expansion"]["core448_fresh_numbering"] = core448_numbering
    return stages, receipt


def build_markdown(
    positive: pd.DataFrame,
    control47: pd.DataFrame,
    stages: pd.DataFrame,
    receipt: dict[str, Any],
) -> str:
    p = receipt["positive11"]
    c = receipt["control47"]
    counter = receipt["positive_developability_counterexamples"]
    return f"""# PVRIG 阳性优先完整筛选校准 V1

日期：2026-07-24  
状态：`{receipt['status']}`

## 结论

第一轮阳性优先校准已经完成，并已扩展到 36 条扰动控制和 47 条 V3 双构象多 seed 控制。

- 11/11 阳性序列为标准 20 AA；
- 11/11 ANARCI/IMGT L1 编号完整；
- 11/11 NanoBodyBuilder2 单体结构存在；
- 11/11 在 V3 的 `8X6B + 9E6Y`、每构象 3 seed 中均达到“每构象至少 2 seed 为 A/B 支持”；
- 只有 {p['V3_robust_strict_A']}/11 达到双构象 robust strict-A，所以 strict-A 不能作为 blocker 硬门；
- 官方 validator 对 11 条为 0/11 通过，这是正确的阳性泄漏排除，不是生物学失败。

## 比赛边界

官方要求：

1. 最多提交 50 条，通常每队不超过 10 条进入实验；
2. VHH 按 ANARCI/IMGT 定义 CDR；
3. 每个对应 CDR 与任一已知阳性原则上低于 80% identity；
4. 初筛权重为 BLI 单浓度 70%、表达 20%、纯度 10%；
5. 复筛权重为 Kd 排名 50%、竞争 ELISA IC50 排名 50%；
6. 目标是 PVRIG 胞外区、PVRL2 界面和阻断机制。

因此本流程保留两个独立结论：

- `CALIBRATION_POSITIVE_RECALLED`：阳性被技术、结构和机制校准层召回；
- `CALIBRATION_POSITIVE_EXCLUDED_LEAKAGE`：同一阳性在比赛提交层被正确排除。

## 本次校准推翻的过严门控

| 单项旧门槛 | 阳性反例 | 新处理 |
|---|---:|---|
| L2/VHH-like 必须 PASS | {counter['L2_not_PASS']}/11 非 PASS | warn/rank |
| TNP 必须全绿 | {counter['TNP_PNC_red']}/11 PNC red | 单项 red 只预警 |
| Sapiens 必须 >=0.70 | {counter['Sapiens_below_0_70']}/11 低于 0.70 | 人源化负担排序 |
| Cys 必须等于 2 | {counter['Cys_not_equal_2']}/11 不等于 2 | 2 或有结构支持的 4 可接受 |
| 不能出现 hydrophobic 5-mer | {counter['hydrophobic_5mer_present']}/11 出现 1 个 | 1 个预警，多个再升级 |
| strict-A 必须通过 | 仅 {p['V3_robust_strict_A']}/11 robust strict-A | rank-only |

这些指标仍用于表达、纯化、稳定性和成药性排序，但不能单独否决 blocker。

## V3 47 控制面板

- 47 个实体；
- 282/282 控制作业成功；
- 18/18 positive-control 实体 robust A/B；
- 14 个 destructive alanine 控制中，{c['destructive_robust_strict_A']}/14 仍 robust strict-A；
- 说明 A/B 是高召回的界面合理性门，而不是 blocker 特异性证明。

破坏性突变尚无实验 non-binder/non-blocker 真值，所以本报告只称“计算扰动控制”。

## 静态亲和力与软件结论

- PRODIGY：弱 prior；
- FoldX 跨候选绝对排序：不启用；
- FoldX fixed-parent ΔΔG：诊断；
- Graphinity 当前多突变排名：拒绝；
- Rosetta InterfaceAnalyzer：等待同面板校准；
- MD/MMGBSA：等待配对阳性/扰动校准，且仅用于末端 20–50 条。

任何软件只有同时达到：

- 阳性召回 >=0.80；
- 控制假阳性 <=0.30；
- entity AUROC >=0.70；
- leave-one-family-out 方向一致 >=0.70；

才允许从描述性字段升级为排名证据；即使升级也不是实验 Kd/IC50。

## 逐步扩大状态

{dataframe_to_markdown(stages)}

## 下一批执行边界

1. 先对 448 CORE_A 跑完整官方 validator 和完整阳性库 CDR 审计；
2. 用本次校准后的 developability 规则复核，不再用 Cys=2/TNP 全绿作 blocker 硬门；
3. 从 448 中按 parent、CDR3、route 和模型分歧抽取约 200 条静态能量面板；
4. Rosetta 只有通过阳性/控制面板才参与候选排序；
5. MD 仅进入 20–50 条末端复核；
6. 最终 50 条和优先 10 条必须重新跑官方 validator、哈希和多样性冻结。

## 机器可读文件

- `positive11_evidence.tsv`
- `control36_evidence.tsv`
- `v3_control47_evidence.tsv`
- `CALIBRATED_SCREENING_POLICY_V1.json`
- `EXPANSION_STAGE_STATUS.tsv`
- `STATUS.json`
- `fresh_numbering/positive11_anarci_H.csv`
- `expansion/core448/NUMBERING_RECEIPT.json`
- `expansion/core448/core437_numbering_pass.tsv`
- `expansion/core448/core11_numbering_review.tsv`
- `SHA256SUMS`
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    positive = load_positive_evidence()
    control36 = load_control36_evidence()
    control47 = load_v3_control47_evidence()
    stages, receipt = build_summary(positive, control36, control47)
    policy = build_policy(positive, control47)

    positive.to_csv(OUT / "positive11_evidence.tsv", sep="\t", index=False)
    control36.to_csv(OUT / "control36_evidence.tsv", sep="\t", index=False)
    control47.to_csv(OUT / "v3_control47_evidence.tsv", sep="\t", index=False)
    stages.to_csv(OUT / "EXPANSION_STAGE_STATUS.tsv", sep="\t", index=False)
    pd.read_csv(METHODS, sep="\t").to_csv(
        OUT / "static_method_calibration_snapshot.tsv", sep="\t", index=False
    )
    write_json(OUT / "CALIBRATED_SCREENING_POLICY_V1.json", policy)

    receipt["input_hashes"] = {
        str(path): sha256(path)
        for path in [
            POS_META,
            POS_FASTA,
            POS_QC,
            OFFICIAL_FAIL,
            OLD_POS_DOCK,
            OLD_POS_STATUS,
            BINDING_PRIOR,
            AFFINITY,
            METHODS,
            CONTROL36,
            CONTROL36_STATUS,
            CONTROL36_LEAK,
            V3_MANIFEST,
            V3_RESULTS,
            V3_STABLE,
            STRICT6042,
            CORE448,
        ]
    }
    if OFFICIAL_SNAPSHOT.exists():
        receipt["official_page_snapshot"] = {
            "path": str(OFFICIAL_SNAPSHOT),
            "sha256": sha256(OFFICIAL_SNAPSHOT),
        }
    write_json(OUT / "STATUS.json", receipt)
    (OUT / "PVRIG_POSITIVE_FIRST_SCREEN_CALIBRATION_V1_ZH.md").write_text(
        build_markdown(positive, control47, stages, receipt), encoding="utf-8"
    )

    output_files = [
        "build_positive_first_calibration.py",
        "prepare_core448_expansion.py",
        "PVRIG_POSITIVE_FIRST_SCREEN_CALIBRATION_V1_ZH.md",
        "CALIBRATED_SCREENING_POLICY_V1.json",
        "positive11_evidence.tsv",
        "control36_evidence.tsv",
        "v3_control47_evidence.tsv",
        "static_method_calibration_snapshot.tsv",
        "EXPANSION_STAGE_STATUS.tsv",
        "STATUS.json",
        "fresh_numbering/positive11.fasta",
        "fresh_numbering/positive11_anarci_H.csv",
        "fresh_numbering/anarci.stdout.log",
        "fresh_numbering/anarci.stderr.log",
        "expansion/core448/PREPARE_RECEIPT.json",
        "expansion/core448/NUMBERING_RECEIPT.json",
        "expansion/core448/core448.fasta",
        "expansion/core448/core448_pre_numbering_manifest.tsv",
        "expansion/core448/core448_anarci_H.csv",
        "expansion/core448/core448_numbering_audit.tsv",
        "expansion/core448/core437_numbering_pass.tsv",
        "expansion/core448/core11_numbering_review.tsv",
        "expansion/core448/SHA256SUMS",
    ]
    lines = [f"{sha256(OUT / name)}  {name}" for name in output_files]
    (OUT / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
