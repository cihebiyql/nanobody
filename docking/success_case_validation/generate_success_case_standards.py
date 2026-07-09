#!/usr/bin/env python3
"""Generate success-case-derived PVRIG blocker judgment standards."""
from __future__ import annotations

import csv
import json
from pathlib import Path

OUT = Path("docking/success_case_validation")
DATE = "2026-07-07"

ROWS = [
    {
        "criterion_id": "C01_BINDER_NOT_BLOCKER",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "experimental_panel",
        "evidence_grade": "HIGH",
        "criterion_layer": "hard_negative_control",
        "judgment_standard": "Binding to PVRIG is not sufficient; require blocking-oriented evidence or geometry that competes with PVRL2.",
        "positive_signal": "PVRIG binder also blocks PVRIG-PVRL2 under competition assay or has PVRL2-occluding pose.",
        "negative_or_caution_signal": "Good Kd/BLI or docking energy without IC50/competition/occlusion is binder-like, not blocker-like.",
        "future_candidate_use": "Hard gate before ranking; do not advance binder-only candidates as blocker leads.",
        "computational_status": "Can be checked with PVRL2 overlay occlusion plus any available blocking IC50.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:110-133; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:2",
    },
    {
        "criterion_id": "C01_KD_AND_IC50_SPLIT",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "assay_interpretation",
        "evidence_grade": "HIGH",
        "criterion_layer": "binding_vs_blocking",
        "judgment_standard": "Treat Kd as binding evidence and IC50/competition as blocking evidence; never collapse them into one docking score.",
        "positive_signal": "Both binding and ligand-blocking measurements or proxies are present.",
        "negative_or_caution_signal": "Only Kd/EC50/binding score is reported.",
        "future_candidate_use": "Report binding_score and blocking_score as separate columns for every candidate.",
        "computational_status": "Binding is not directly validated by current docking; blocking geometry is approximated by PVRL2 occlusion.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:101-107",
    },
    {
        "criterion_id": "C01_R95_I97_S67_WEIGHTING",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "epitope_mapping_plus_structure",
        "evidence_grade": "HIGH",
        "criterion_layer": "soft_hotspot",
        "judgment_standard": "Use R95 as high-weight soft hotspot, I97 as low/medium hint, and S67 as advisory epitope/cross-reactivity clue only.",
        "positive_signal": "Pose covers consensus interface and can include R95/I97 neighborhood without needing to copy Tab5.",
        "negative_or_caution_signal": "Candidate is designed mainly around S67 while losing PVRL2-interface coverage.",
        "future_candidate_use": "Weight R95/interface coverage; do not make S67 a hard objective.",
        "computational_status": "Directly mappable onto 8X6B/9E6Y hotspot table; still a soft hint, not proof.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:193-243; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:2",
    },
    {
        "criterion_id": "C01_POSITIVE_CONTROL_LEAKAGE",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "positive_control_and_design_safety",
        "evidence_grade": "HIGH",
        "criterion_layer": "leakage_guard",
        "judgment_standard": "Use Tab5/CPA.7.021 as positive-control mechanism references and sequence leakage exclusions, not as templates to copy.",
        "positive_signal": "Different CDR/paratope reaches the same functional interface.",
        "negative_or_caution_signal": "High CDR similarity to Tab5/CPA.7.021/HR-151 or light mutation of known positives.",
        "future_candidate_use": "Add positive_CDR_leakage_penalty before final ranking.",
        "computational_status": "Requires ANARCI/IMGT-normalized sequence comparison outside docking.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:62-67; 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:299-304",
    },
    {
        "criterion_id": "C01_FC_FORMAT_IS_INDEPENDENT",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "format_mechanism",
        "evidence_grade": "MEDIUM",
        "criterion_layer": "format_context",
        "judgment_standard": "Fc-reduced/IgG4 checkpoint-blocking logic is a format choice, not the same variable as epitope blocking.",
        "positive_signal": "Candidate report states whether it is naked VHH, VHH-Fc, IgG4, IgG1, or bispecific.",
        "negative_or_caution_signal": "Docking result is used to claim Fc-mediated or in-vivo activity.",
        "future_candidate_use": "Keep format_compatibility_score separate from paratope docking score.",
        "computational_status": "Not inferable from static VHH/PVRIG docking.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:248-276",
    },
    {
        "criterion_id": "C01_COMBINATION_CONTEXT",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "functional_context",
        "evidence_grade": "MEDIUM",
        "criterion_layer": "combo_context",
        "judgment_standard": "PVRIG blockade may be nonredundant and combination-sensitive; do not reject a blocker only because one isolated T-cell readout is weak.",
        "positive_signal": "Mechanism can be tested with PD-1/TIGIT combination or PVRL2-high tumor context labels.",
        "negative_or_caution_signal": "Single-assay failure is overinterpreted as no PVRIG mechanism.",
        "future_candidate_use": "Add TIGIT_PD1_combination_context and PVRL2_high_tumor_context annotations.",
        "computational_status": "Requires downstream biology; docking only checks ligand competition.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:169-187",
    },
    {
        "criterion_id": "C01_NO_COMPLEX_CAVEAT",
        "case_id": "COM701_CPA7021_Tab5",
        "case_name": "COM701 / CPA.7.021 / Tab5",
        "evidence_type": "evidence_gap",
        "evidence_grade": "CAUTION",
        "criterion_layer": "claim_boundary",
        "judgment_standard": "Do not state COM701/Tab5 contact residues as experimentally proven without a public complex structure or verified patent figures.",
        "positive_signal": "Claims are labeled as patent mapping, structure baseline, or docking inference.",
        "negative_or_caution_signal": "Residue contacts are stated as direct complex facts.",
        "future_candidate_use": "Keep evidence_level and inference_level fields in reports.",
        "computational_status": "Local structure maps can support inference only.",
        "source_refs": "机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:320-330",
    },
    {
        "criterion_id": "C02_VHH_BLOCKING_VALUES",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "patent_assay_and_official_positive",
        "evidence_grade": "HIGH",
        "criterion_layer": "positive_family",
        "judgment_standard": "Multiple VHH families show nM-level PVRIG-PVRL2 blocking; do not calibrate only to PVRIG-151/HR-151.",
        "positive_signal": "Candidate resembles a new functional solution among several VHH families and passes blocking geometry.",
        "negative_or_caution_signal": "Ranking treats 151/HR-151 as the only useful positive center.",
        "future_candidate_use": "Use multiple VHH families as success-case anchors and positive-leakage controls.",
        "computational_status": "Assay values support family-level calibration; residue epitope remains inferred.",
        "source_refs": "机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md:96-117; 机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_evidence_table.csv:2-7",
    },
    {
        "criterion_id": "C02_BINDING_VALUES",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "patent_binding_assay",
        "evidence_grade": "HIGH",
        "criterion_layer": "binding_support",
        "judgment_standard": "Successful VHH blockers also have sub-nM to low-nM binding, but binding strength does not replace blocking assessment.",
        "positive_signal": "Candidate has plausible affinity support and independent PVRL2-competition support.",
        "negative_or_caution_signal": "Candidate has high predicted binding but no PVRL2 occlusion or blocking assay.",
        "future_candidate_use": "Use binding as prerequisite/support, then apply occlusion and interface gates.",
        "computational_status": "Docking energy is only a weak proxy for binding.",
        "source_refs": "机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md:121-149; 机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_evidence_table.csv:2-7",
    },
    {
        "criterion_id": "C02_HR151_OCCLUSION_THRESHOLDS",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "local_computational_positive_control",
        "evidence_grade": "HIGH_FOR_SCREENING",
        "criterion_layer": "hard_computational_gate",
        "judgment_standard": "First-pass BLOCKER_LIKE_A requires hotspot overlap >=14, total VHH-PVRL2 residue-pair occlusion >=500, CDR3-PVRL2 residue-pair occlusion >=100, and CDR3 occlusion fraction >=0.15.",
        "positive_signal": "Pose passes all HR-151-calibrated occlusion thresholds.",
        "negative_or_caution_signal": "Pose fails PVRL2 overlay occlusion even if HADDOCK score or hotspot overlap is strong.",
        "future_candidate_use": "Use as the current executable screen for VHH blocker-like docking poses.",
        "computational_status": "Validated as screening criterion, not experimental proof.",
        "source_refs": "docking/case02_hr151_pvrig/reports/blocker_validation_protocol_v1.md:29-49",
    },
    {
        "criterion_id": "C02_HOTSPOT_ONLY_NEGATIVE_CONTROL",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "local_negative_control",
        "evidence_grade": "HIGH_FOR_SCREENING",
        "criterion_layer": "hard_negative_control",
        "judgment_standard": "Hotspot/interface contact with total PVRL2 occlusion <50 is BINDER_LIKE_C and should be downgraded.",
        "positive_signal": "High hotspot overlap plus substantial total and CDR3 occlusion.",
        "negative_or_caution_signal": "HR-151 cluster_2 pattern: hotspot overlap 20 but total and CDR3 occlusion 0.",
        "future_candidate_use": "Reject hotspot-only non-occluding poses before final ranking.",
        "computational_status": "Directly executable with existing scoring scripts.",
        "source_refs": "docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md:62-68; docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md:99-114",
    },
    {
        "criterion_id": "C02_CDR3_WEDGE_NOT_ONLY_FACTOR",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "local_computational_interpretation",
        "evidence_grade": "MEDIUM_HIGH_FOR_SCREENING",
        "criterion_layer": "paratope_geometry",
        "judgment_standard": "CDR3 should provide nontrivial PVRL2 occlusion, but requiring CDR3 to explain >50% of occlusion is too strict.",
        "positive_signal": "CDR3 contributes a focused wedge while framework provides supporting steric wall outside the interface.",
        "negative_or_caution_signal": "Rules force long-CDR3 dominance and reject compact or framework-supported blockers.",
        "future_candidate_use": "Keep CDR3-specific occlusion threshold modest and combine with total occlusion.",
        "computational_status": "Local HR-151 result supports this as screening logic only.",
        "source_refs": "docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md:75-96",
    },
    {
        "criterion_id": "C02_CDR_NUMBERING_NORMALIZATION",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "sequence_processing_caveat",
        "evidence_grade": "HIGH",
        "criterion_layer": "leakage_guard",
        "judgment_standard": "Normalize Kabat/IMGT CDR definitions with ANARCI before similarity or contact comparisons.",
        "positive_signal": "All candidate and positive-control CDRs are compared under one numbering convention.",
        "negative_or_caution_signal": "Mixed Kabat and IMGT CDRs create false similarity or false novelty.",
        "future_candidate_use": "Run ANARCI/IMGT before CDR leakage exclusion and CDR-specific scoring.",
        "computational_status": "Required outside pose scoring.",
        "source_refs": "机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md:184-211; 机制/data/literature/PVRIG_case02_vhh_docking_calibration_tags.csv:12-13",
    },
    {
        "criterion_id": "C02_FORMAT_DEPENDENCE",
        "case_id": "PVRIG_VHH_20_30_38_39_151_HR151",
        "case_name": "PVRIG-20/30/38/39/151 and HR-151",
        "evidence_type": "format_context",
        "evidence_grade": "MEDIUM_HIGH",
        "criterion_layer": "format_context",
        "judgment_standard": "Single VHH blocking can be strong, but VHH-Fc, bivalent, or TIGIT-PVRIG bispecific format may determine in-vivo strength.",
        "positive_signal": "Candidate remains geometrically compatible with Fc fusion or bispecific architecture if that is the development route.",
        "negative_or_caution_signal": "Naked VHH docking is used to infer in-vivo efficacy or bispecific coengagement.",
        "future_candidate_use": "Add VHH_fusion_compatibility_score and TIGIT_combination_potential.",
        "computational_status": "Requires format modeling beyond Fv/PVRIG pose.",
        "source_refs": "机制/data/literature/PVRIG_case02_vhh_docking_calibration_tags.csv:9-11; 机制/success_cases/PVRIG成功案例机制研究_v1.md:379-386",
    },
    {
        "criterion_id": "C03_BLOCKING_FIRST",
        "case_id": "IBI352g4a",
        "case_name": "IBI352g4a Fc-competent anti-PVRIG",
        "evidence_type": "peer_reviewed_assay",
        "evidence_grade": "HIGH",
        "criterion_layer": "hard_functional_gate",
        "judgment_standard": "Even Fc/NK-enhanced antibodies must first satisfy PVRIG binding and PVRIG-PVRL2 blocking.",
        "positive_signal": "Binding Kd/EC50 and PVRIG-PVRL2 blocking IC50 are both in the nM range or better.",
        "negative_or_caution_signal": "Fc/NK mechanism is invoked without showing ligand blocking.",
        "future_candidate_use": "Do not let format biology bypass ligand-blocking gate.",
        "computational_status": "Blocking can be approximated by occlusion if assay is unavailable.",
        "source_refs": "机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:64-83; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:4-8",
    },
    {
        "criterion_id": "C03_NK_PRIMARY_READOUT",
        "case_id": "IBI352g4a",
        "case_name": "IBI352g4a Fc-competent anti-PVRIG",
        "evidence_type": "peer_reviewed_function",
        "evidence_grade": "HIGH",
        "criterion_layer": "cell_context",
        "judgment_standard": "For Fc-competent PVRIG antibodies, NK activation/killing is a primary success readout, not an optional afterthought.",
        "positive_signal": "CD107a/CD137 or NK killing rises in PVRL2-high tumor/NK coculture or analogous setting.",
        "negative_or_caution_signal": "Only immediate T-cell activation is measured and NK is absent.",
        "future_candidate_use": "Add NK_activation_support and PVRL2_high_tumor_context labels.",
        "computational_status": "Not visible in docking; annotate for downstream assays.",
        "source_refs": "机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:92-142; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:9-11",
    },
    {
        "criterion_id": "C03_MODEL_CONTEXT_REQUIRED",
        "case_id": "IBI352g4a",
        "case_name": "IBI352g4a Fc-competent anti-PVRIG",
        "evidence_type": "preclinical_model_comparison",
        "evidence_grade": "HIGH",
        "criterion_layer": "cell_context",
        "judgment_standard": "In-vivo interpretation must record NK-supporting vs T-cell-skewed model context.",
        "positive_signal": "Candidate is evaluated in a model with NK, Fc receptor, and PVRL2 context when claiming Fc-competent efficacy.",
        "negative_or_caution_signal": "A weak NK-poor model is used to reject the mechanism globally.",
        "future_candidate_use": "Store model_context and immune_compartment fields with efficacy data.",
        "computational_status": "External to docking; affects evidence interpretation.",
        "source_refs": "机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:147-171; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:12",
    },
    {
        "criterion_id": "C03_FC_CD16A_INDEPENDENT_SCORE",
        "case_id": "IBI352g4a",
        "case_name": "IBI352g4a Fc-competent anti-PVRIG",
        "evidence_type": "peer_reviewed_format_comparison",
        "evidence_grade": "HIGH",
        "criterion_layer": "format_context",
        "judgment_standard": "Fc/CD16a coengagement is a separate efficacy amplifier for IgG1/VHH-Fc/bispecific formats.",
        "positive_signal": "Format can engage Fc receptors when desired and does not block the paratope geometry.",
        "negative_or_caution_signal": "All anti-PVRIG designs are forced to IgG1, or naked VHH is expected to reproduce Fc effects.",
        "future_candidate_use": "Add format_score and Fc_engagement_required_or_not; keep them separate from docking.",
        "computational_status": "Requires format and biology annotation, not Fv docking.",
        "source_refs": "机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:215-243; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:15-16",
    },
    {
        "criterion_id": "C03_LAYERED_SCORING",
        "case_id": "IBI352g4a",
        "case_name": "IBI352g4a Fc-competent anti-PVRIG",
        "evidence_type": "modeling_guidance",
        "evidence_grade": "HIGH",
        "criterion_layer": "scoring_architecture",
        "judgment_standard": "Keep antigen binding, ligand blocking, epitope competition, format compatibility, cell-context, and developability as separate scores.",
        "positive_signal": "Candidate has a multi-column evidence profile rather than one blended docking number.",
        "negative_or_caution_signal": "Binding/docking score is treated as final drug-efficacy score.",
        "future_candidate_use": "Use this as the schema for future candidate scorecards.",
        "computational_status": "Partly executable, partly annotation-based.",
        "source_refs": "机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:254-279",
    },
    {
        "criterion_id": "C03_NO_CDR_TEMPLATE",
        "case_id": "IBI352g4a",
        "case_name": "IBI352g4a Fc-competent anti-PVRIG",
        "evidence_type": "evidence_gap",
        "evidence_grade": "CAUTION",
        "criterion_layer": "claim_boundary",
        "judgment_standard": "Use IBI352g4a as Fc/NK mechanism constraint, not as a CDR or residue-contact template.",
        "positive_signal": "Reports cite it for blocking plus Fc/NK biology only.",
        "negative_or_caution_signal": "Residue epitope or sequence-derived CDR lessons are inferred without public sequence/complex evidence.",
        "future_candidate_use": "Mark residue-level conclusions as unavailable.",
        "computational_status": "No public complex or direct residue map for local docking calibration.",
        "source_refs": "机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:307-313",
    },
    {
        "criterion_id": "C04_DISTINCT_EPITOPE_ALLOWED",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "public_preclinical_mechanism",
        "evidence_grade": "HIGH_FOR_ANTI_OVERFIT",
        "criterion_layer": "anti_overfit",
        "judgment_standard": "Allow blocker poses that do not mimic HR-151/Tab5/R95-I97, provided they still block or occlude the functional PVRIG-PVRL2 interface.",
        "positive_signal": "Alternative epitope/angle still creates PVRL2 steric occlusion or credible allosteric ligand interference.",
        "negative_or_caution_signal": "Remote binder is accepted merely because distinct epitopes are allowed.",
        "future_candidate_use": "Use as anti-overfit control family in ranking and model training.",
        "computational_status": "Alternative poses need PVRL2 occlusion or experimental blocking evidence.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:24-30; 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:74-106; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:2-4",
    },
    {
        "criterion_id": "C04_BLOCKING_STILL_REQUIRED",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "public_preclinical_mechanism",
        "evidence_grade": "HIGH",
        "criterion_layer": "hard_functional_gate",
        "judgment_standard": "Distinct epitope does not relax the core blocking requirement against CD112/PVRL2.",
        "positive_signal": "Candidate has PVRL2 occlusion, competition assay, or ligand-interference evidence.",
        "negative_or_caution_signal": "Nonblocking remote-surface binder is scored high as distinct.",
        "future_candidate_use": "Keep BLOCKING_STILL_REQUIRED as a hard gate in every epitope bin.",
        "computational_status": "Use overlay occlusion or assay evidence; no public SRF813 complex.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:115-127; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:3",
    },
    {
        "criterion_id": "C04_IGG1_FORMAT_CONTEXT",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "format_context",
        "evidence_grade": "MEDIUM_HIGH",
        "criterion_layer": "format_context",
        "judgment_standard": "For IgG1 examples, separate Fab/Fv docking conclusions from Fc/NK/T-cell function conclusions.",
        "positive_signal": "Fab epitope geometry and IgG1 functional context are reported as separate fields.",
        "negative_or_caution_signal": "Fv docking alone is used to claim IgG1 Fc benefit.",
        "future_candidate_use": "Add IGG1_FORMAT_CONTEXT and avoid docking-only functional claims.",
        "computational_status": "Fv docking can only address epitope/occlusion.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:129-150; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:5",
    },
    {
        "criterion_id": "C04_CD226_AXIS",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "pathway_context",
        "evidence_grade": "MEDIUM",
        "criterion_layer": "downstream_pathway",
        "judgment_standard": "Record whether blockade may restore PVRL2-CD226/DNAM-1 activating context, not only physical ligand displacement.",
        "positive_signal": "Candidate is paired with CD226-axis annotation in functional plans.",
        "negative_or_caution_signal": "Docking clash is treated as the entire PVRIG mechanism.",
        "future_candidate_use": "Add CD226_axis_relevant and ligand_redirection notes.",
        "computational_status": "Not directly visible in static docking.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:155-198; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:6",
    },
    {
        "criterion_id": "C04_NK_T_CELL_READOUTS",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "public_preclinical_function",
        "evidence_grade": "MEDIUM",
        "criterion_layer": "cell_context",
        "judgment_standard": "Distinct-epitope blockers should preserve both NK and T-cell readout labels for downstream validation.",
        "positive_signal": "Functional package includes NK and T-cell activation assays or planned labels.",
        "negative_or_caution_signal": "Only T-cell readout or only docking is used to judge the mechanism.",
        "future_candidate_use": "Keep NK_AND_T_CELL_READOUT as a standard annotation.",
        "computational_status": "Requires functional validation outside docking.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:203-231; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:7",
    },
    {
        "criterion_id": "C04_CLINICAL_CAVEAT",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "evidence_boundary",
        "evidence_grade": "CAUTION",
        "criterion_layer": "claim_boundary",
        "judgment_standard": "Use SRF813/GSK4381562 as mechanism calibration and anti-overfit evidence, not as proven clinical efficacy evidence.",
        "positive_signal": "Clinical/IND status is described cautiously and separately from mechanism claims.",
        "negative_or_caution_signal": "Clinical-stage or abandonment status is used as direct proof or disproof of docking correctness.",
        "future_candidate_use": "Keep commercial/clinical outcome outside the docking validation label.",
        "computational_status": "No effect on pose scoring except evidence weighting.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:235-249",
    },
    {
        "criterion_id": "C04_NO_PUBLIC_COMPLEX",
        "case_id": "GSK4381562_SRF813",
        "case_name": "GSK4381562 / SRF813 / remzistotug",
        "evidence_type": "evidence_gap",
        "evidence_grade": "CAUTION",
        "criterion_layer": "claim_boundary",
        "judgment_standard": "Residue contacts for SRF813-like poses must be labeled as computational inference unless a public complex or epitope map is added.",
        "positive_signal": "Report says inferred_pose_contact rather than experimental_contact.",
        "negative_or_caution_signal": "Exact distinct-epitope residues are asserted without source.",
        "future_candidate_use": "Keep source evidence level and no_public_complex warning.",
        "computational_status": "Can dock predicted Fab/Fv, but contacts remain inferred.",
        "source_refs": "机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:277-295; 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:368-387",
    },
    {
        "criterion_id": "C05_SHR2002_CO_BLOCKING",
        "case_id": "SHR2002_TIGIT8_PVRIG30",
        "case_name": "SHR-2002 / TIGIT-8-PVRIG-30-IgG4",
        "evidence_type": "peer_reviewed_preclinical_bispecific",
        "evidence_grade": "MEDIUM_HIGH",
        "criterion_layer": "bispecific_format",
        "judgment_standard": "A PVRIG nanobody arm can succeed as part of a TIGIT/PVRIG co-blocking bispecific; future evaluation should not stop at naked VHH properties.",
        "positive_signal": "PVRIG arm remains exposed and can coengage PVRIG while TIGIT arm blocks TIGIT/CD155.",
        "negative_or_caution_signal": "Strong naked VHH docking is assumed to survive fusion without checking exposure/linker geometry.",
        "future_candidate_use": "Add TIGIT_combination_potential and fusion_exposure checks for format candidates.",
        "computational_status": "Requires architecture modeling beyond the current PVRIG/VHH pose.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:219-257; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:6",
    },
    {
        "criterion_id": "C05_PVRIG30_IS_NOT_SECONDARY",
        "case_id": "SHR2002_TIGIT8_PVRIG30",
        "case_name": "SHR-2002 / TIGIT-8-PVRIG-30-IgG4",
        "evidence_type": "format_success_anchor",
        "evidence_grade": "MEDIUM_HIGH",
        "criterion_layer": "positive_family",
        "judgment_standard": "PVRIG-30 family should be kept as a meaningful positive reference because it appears in bispecific context.",
        "positive_signal": "Candidate set includes non-151 VHH families in calibration.",
        "negative_or_caution_signal": "All non-151 families are discarded as weaker despite format success evidence.",
        "future_candidate_use": "Keep PVRIG-30-like family diversity in validation and leakage checks.",
        "computational_status": "Family-level criterion; not a residue-contact proof.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:234-246; 机制/success_cases/PVRIG成功案例机制研究_v1.md:379-386; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:6",
    },
    {
        "criterion_id": "C05_FORMAT_SPECIFIC_NOT_NAKED_PROOF",
        "case_id": "SHR2002_TIGIT8_PVRIG30",
        "case_name": "SHR-2002 / TIGIT-8-PVRIG-30-IgG4",
        "evidence_type": "claim_boundary",
        "evidence_grade": "CAUTION",
        "criterion_layer": "format_context",
        "judgment_standard": "SHR-2002 supports format-aware ranking, not proof that naked PVRIG-30 alone is optimal.",
        "positive_signal": "Report distinguishes arm-level paratope from whole-bispecific efficacy.",
        "negative_or_caution_signal": "Bispecific efficacy is credited entirely to the PVRIG nanobody arm.",
        "future_candidate_use": "Separate paratope_score from architecture_score.",
        "computational_status": "Requires bispecific controls and coengagement modeling.",
        "source_refs": "机制/data/literature/PVRIG_success_case_evidence_matrix.csv:6",
    },
    {
        "criterion_id": "C06_PM1009_SIM0348_MULTI_AXIS",
        "case_id": "PM1009_SIM0348",
        "case_name": "PM1009 / SIM0348",
        "evidence_type": "drug_dictionary_mechanism",
        "evidence_grade": "MEDIUM",
        "criterion_layer": "multi_axis_format",
        "judgment_standard": "PVRIG blockers can be part of multi-axis DNAM/CD226 rebalancing designs, including anti-TIGIT/anti-PVRIG bispecifics.",
        "positive_signal": "Candidate strategy records whether it targets PVRIG alone or TIGIT/PVRIG jointly.",
        "negative_or_caution_signal": "PVRIG-only docking is used to judge multi-axis format efficacy.",
        "future_candidate_use": "Add DNAM_axis_co_blocking_concept and TIGIT_PVRIG_co_blocking labels.",
        "computational_status": "Mechanism annotation only unless bispecific structure is modeled.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:259-280; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:7",
    },
    {
        "criterion_id": "C06_FC_TREG_CONTEXT",
        "case_id": "PM1009_SIM0348",
        "case_name": "PM1009 / SIM0348",
        "evidence_type": "drug_dictionary_mechanism",
        "evidence_grade": "LOW_MEDIUM",
        "criterion_layer": "effector_context",
        "judgment_standard": "Some multi-axis IgG1 designs may include Fc-mediated effects such as killing TIGIT/PVRIG-expressing Tregs; record this as a separate effector mechanism.",
        "positive_signal": "Effector function is intentionally desired and supported by format/assay plan.",
        "negative_or_caution_signal": "Fc-mediated depletion is inferred from PVRIG docking alone.",
        "future_candidate_use": "Add effector_function_intended flag for IgG1 or bispecific formats.",
        "computational_status": "Not inferable from PVRIG Fv docking.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:272-280; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:7",
    },
    {
        "criterion_id": "C06_SUMMARY_EVIDENCE_CAVEAT",
        "case_id": "PM1009_SIM0348",
        "case_name": "PM1009 / SIM0348",
        "evidence_type": "claim_boundary",
        "evidence_grade": "CAUTION",
        "criterion_layer": "evidence_weight",
        "judgment_standard": "Drug-dictionary mechanism entries are useful labels but lower-weight than assay, structure, or peer-reviewed data.",
        "positive_signal": "Used to define future-format labels, not quantitative docking thresholds.",
        "negative_or_caution_signal": "Mechanism summary is treated as detailed epitope/affinity evidence.",
        "future_candidate_use": "Use for roadmap annotations only until primary data are added.",
        "computational_status": "No direct scoring threshold.",
        "source_refs": "机制/data/literature/PVRIG_success_case_evidence_matrix.csv:7",
    },
    {
        "criterion_id": "C07_CD112RIVE_INTERFACE_ENGINEERING",
        "case_id": "CD112RIVE_structure_guided_trap",
        "case_name": "CD112RIVE / engineered CD112R variants",
        "evidence_type": "peer_reviewed_structure_guided_engineering",
        "evidence_grade": "MEDIUM_HIGH",
        "criterion_layer": "interface_engineering",
        "judgment_standard": "The PVRIG/CD112 interface can be engineered by structure-guided affinity tuning; use interface residue priority and contact density instead of black-box docking alone.",
        "positive_signal": "Candidate design/ranking explains which interface contacts or buried-surface features are improved.",
        "negative_or_caution_signal": "Docking score changes without interface-residue rationale are overtrusted.",
        "future_candidate_use": "Add interface_residue_priority, contact_density, and affinity_tuning_residue_map fields.",
        "computational_status": "Supports feature engineering; not an anti-PVRIG antibody positive.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:282-307; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:8",
    },
    {
        "criterion_id": "C07_NOT_ANTIBODY_CAVEAT",
        "case_id": "CD112RIVE_structure_guided_trap",
        "case_name": "CD112RIVE / engineered CD112R variants",
        "evidence_type": "claim_boundary",
        "evidence_grade": "CAUTION",
        "criterion_layer": "modality_boundary",
        "judgment_standard": "CD112RIVE is not an anti-PVRIG antibody; use it to validate interface engineering logic, not antibody paratope templates.",
        "positive_signal": "Used as feature-prior evidence for interface residues and ligand competition geometry.",
        "negative_or_caution_signal": "Its engineered receptor residues are copied into antibody CDR logic.",
        "future_candidate_use": "Keep antibody_modality and ligand_trap_modality separate.",
        "computational_status": "No direct VHH docking threshold.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:282-307; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:8",
    },
    {
        "criterion_id": "C08_NK_BIOLOGY_REQUIRED",
        "case_id": "NK_cell_blockade_biology",
        "case_name": "PVRIG blockade biology in NK studies",
        "evidence_type": "peer_reviewed_functional_biology",
        "evidence_grade": "MEDIUM_HIGH",
        "criterion_layer": "cell_context",
        "judgment_standard": "PVRIG blocker validation should include NK activation/tumor-context labels, not only CD8 T-cell rescue.",
        "positive_signal": "Functional plan includes NK, CD8, PVRL2-high tumor, or PBMC-reconstituted xenograft context.",
        "negative_or_caution_signal": "Candidate is rejected or accepted using only one T-cell checkpoint readout.",
        "future_candidate_use": "Add NK_activation_support and tumor_context fields to all candidate reports.",
        "computational_status": "Biology annotation only; does not alter pose geometry threshold.",
        "source_refs": "机制/success_cases/PVRIG成功案例机制研究_v1.md:347-359; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:9",
    },
]

FIELDS = [
    "criterion_id",
    "case_id",
    "case_name",
    "evidence_type",
    "evidence_grade",
    "criterion_layer",
    "judgment_standard",
    "positive_signal",
    "negative_or_caution_signal",
    "future_candidate_use",
    "computational_status",
    "source_refs",
]

RULES = {
    "version": "v2",
    "generated_at": DATE,
    "purpose": "Success-case-calibrated standards for deciding whether future PVRIG VHH/antibody candidates are likely blockers rather than generic binders.",
    "classifier": {
        "BLOCKER_LIKE_A": {
            "meaning": "Prioritized structurally blocker-like pose or experimentally proven blocker-like candidate.",
            "required_for_vhh_docking": {
                "hotspot_overlap_count": ">= 14",
                "total_vhh_pvrl2_residue_pair_occlusion": ">= 500",
                "cdr3_pvrl2_residue_pair_occlusion": ">= 100",
                "cdr3_occlusion_fraction": ">= 0.15",
            },
            "experimental_equivalent": "Strong PVRIG binding plus direct PVRIG-PVRL2/CD112 blocking evidence, ideally low-nM IC50 or better.",
        },
        "BLOCKER_PLAUSIBLE_B": {
            "meaning": "Alternative epitope or format-aware candidate with plausible ligand interference but incomplete quantitative support.",
            "required_notes": ["blocking evidence missing or weaker", "must not be remote binder-only", "needs follow-up assay or second-structure validation"],
        },
        "BINDER_LIKE_C": {
            "meaning": "PVRIG binder or interface-contacting pose without enough PVRL2 blocking geometry.",
            "rule": "If hotspot_overlap_count >= 14 but total_vhh_pvrl2_residue_pair_occlusion < 50, downgrade to BINDER_LIKE_C.",
        },
        "FORMAT_CONTEXT_D": {
            "meaning": "Mechanistically interesting only in Fc, VHH-Fc, or bispecific architecture context.",
            "rule": "Do not infer this class from naked VHH docking alone.",
        },
        "EVIDENCE_INFERENCE_ONLY_E": {
            "meaning": "Useful hypothesis or case label with insufficient structure/assay evidence for blocker prioritization.",
            "rule": "Keep in research notes; do not advance as blocker proof.",
        },
    },
    "hard_gates": [
        "Separate binding evidence from ligand-blocking evidence.",
        "Require PVRL2/CD112 blocking geometry or assay evidence before calling a candidate blocker-like.",
        "Downgrade hotspot-only non-occluding poses.",
        "Apply positive-control leakage checks against HR-151, Tab5/CPA.7.021, and known VHH families using normalized CDR definitions.",
        "Label residue contacts from docking as inference unless supported by a public complex or epitope map.",
    ],
    "soft_positive_features": [
        "Consensus interface coverage, especially R95 neighborhood.",
        "PVRL2 steric occlusion from a plausible CDR/paratope angle.",
        "Alternative distinct epitope that still interferes with PVRL2 binding.",
        "Compatibility with intended format: naked VHH, VHH-Fc, IgG1/IgG4, or TIGIT/PVRIG bispecific.",
        "NK/Fc/CD226/TIGIT context annotations for downstream functional validation.",
    ],
    "case_ids": sorted({row["case_id"] for row in ROWS}),
}


def write_csv() -> None:
    path = OUT / "success_case_mechanism_criteria_matrix.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)


def write_json() -> None:
    path = OUT / "blocker_judgment_rules_v2.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(RULES, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_markdown() -> None:
    path = OUT / "blocker_design_judgment_standards_v2.md"
    lines = []
    lines.append("# PVRIG blocker design judgment standards v2")
    lines.append("")
    lines.append(f"Generated: {DATE}")
    lines.append("")
    lines.append("## Bottom line")
    lines.append("")
    lines.append("The standard is not highest docking score. A future candidate should pass a layered chain: bind PVRIG ECD -> occupy or perturb the functional interface -> block PVRIG-PVRL2/CD112 -> fit the intended format and NK/T-cell context -> avoid positive-control sequence leakage.")
    lines.append("")
    lines.append("## Classifier")
    lines.append("")
    for label, spec in RULES["classifier"].items():
        lines.append(f"### {label}")
        lines.append("")
        lines.append(spec["meaning"])
        if "required_for_vhh_docking" in spec:
            lines.append("")
            lines.append("VHH docking first-pass thresholds:")
            lines.append("")
            for k, v in spec["required_for_vhh_docking"].items():
                lines.append(f"- `{k}` {v}")
            lines.append(f"- Experimental equivalent: {spec['experimental_equivalent']}")
        if "required_notes" in spec:
            lines.append("")
            for item in spec["required_notes"]:
                lines.append(f"- {item}")
        if "rule" in spec:
            lines.append("")
            lines.append(f"Rule: {spec['rule']}")
        lines.append("")
    lines.append("## Gates for future candidates")
    lines.append("")
    for gate in RULES["hard_gates"]:
        lines.append(f"- Hard gate: {gate}")
    for feat in RULES["soft_positive_features"]:
        lines.append(f"- Soft/context feature: {feat}")
    lines.append("")
    lines.append("## Case-derived standards")
    lines.append("")
    by_case = {}
    for row in ROWS:
        by_case.setdefault((row["case_id"], row["case_name"]), []).append(row)
    for (case_id, case_name), rows in by_case.items():
        lines.append(f"### {case_id}: {case_name}")
        lines.append("")
        for row in rows:
            lines.append(f"- `{row['criterion_id']}` ({row['evidence_grade']}, {row['criterion_layer']}): {row['judgment_standard']}")
            lines.append(f"  Positive: {row['positive_signal']}")
            lines.append(f"  Caution: {row['negative_or_caution_signal']}")
            lines.append(f"  Use: {row['future_candidate_use']}")
            lines.append(f"  Sources: {row['source_refs']}")
        lines.append("")
    lines.append("## Practical validation route")
    lines.append("")
    lines.append("1. Normalize candidate and positive-control CDRs with ANARCI/IMGT; apply leakage exclusion.")
    lines.append("2. Model candidate VHH or Fv/Fab; dock to fixed PVRIG with hotspot/CDR-guided workflow.")
    lines.append("3. Align pose to 8X6B and 9E6Y PVRIG baselines; overlay PVRL2/CD112.")
    lines.append("4. Score hotspot overlap, total VHH/Fv-PVRL2 occlusion, CDR3-specific occlusion, and CDR contact pattern.")
    lines.append("5. Classify with the rules above, then add format/NK/CD226/TIGIT context labels instead of blending them into docking score.")
    lines.append("6. Treat passing docking as structurally blocker-like, not experimental proof; confirm with competition IC50 or cell assay when possible.")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report() -> None:
    path = OUT / "success_case_validation_report.md"
    lines = []
    lines.append("# Success-case validation report for PVRIG blocker standards")
    lines.append("")
    lines.append(f"Generated: {DATE}")
    lines.append("")
    lines.append("## What was verified")
    lines.append("")
    lines.append("Local case-study markdown files, literature CSV evidence tables, and the HR-151 docking positive-control reports were cross-checked. Each extracted criterion is labeled by evidence grade and by whether it is directly computational, experimental, contextual, or a claim boundary.")
    lines.append("")
    lines.append("## Per-case validation")
    lines.append("")
    summaries = [
        ("COM701_CPA7021_Tab5", "Validated as the classic binder-versus-blocker and R95/I97 soft-hotspot case. It gives hard negative-control logic: Kd/binding is not enough; PVRIG-PVRL2 blocking or steric competition is required."),
        ("PVRIG_VHH_20_30_38_39_151_HR151", "Validated as the VHH-positive family plus the current executable docking calibration. HR-151 thresholds support BLOCKER_LIKE_A, and cluster_2 supplies an internal hotspot-only negative control."),
        ("IBI352g4a", "Validated as the Fc/NK context case. It still starts with binding plus blocking, but shows that NK, Fc/CD16a, and model context must be scored separately from docking."),
        ("GSK4381562_SRF813", "Validated as the distinct-epitope anti-overfit case. It allows alternative epitope solutions while preserving the hard requirement that PVRL2/CD112 blocking remains necessary."),
        ("SHR2002_TIGIT8_PVRIG30", "Validated as a bispecific-format case showing that a PVRIG nanobody arm, especially PVRIG-30 family, may succeed in TIGIT/PVRIG co-blocking architecture."),
        ("PM1009_SIM0348", "Validated as lower-resolution multi-axis mechanism evidence. It supports DNAM/CD226 and TIGIT/PVRIG co-blocking labels but does not provide quantitative docking thresholds."),
        ("CD112RIVE_structure_guided_trap", "Validated as non-antibody interface-engineering evidence. It supports contact-density and affinity-tuning features, not antibody CDR templates."),
        ("NK_cell_blockade_biology", "Validated as biology-context evidence requiring NK/tumor-context labels in downstream validation.")
    ]
    for case_id, text in summaries:
        lines.append(f"### {case_id}")
        lines.append("")
        lines.append(text)
        lines.append("")
        matching = [r for r in ROWS if r["case_id"] == case_id]
        for row in matching:
            lines.append(f"- {row['criterion_id']}: {row['judgment_standard']}")
        lines.append("")
    lines.append("## Extracted decision hierarchy")
    lines.append("")
    lines.append("1. Binding is necessary but not sufficient.")
    lines.append("2. Direct PVRIG-PVRL2/CD112 blocking or PVRL2 overlay occlusion is the primary blocker gate.")
    lines.append("3. R95/interface coverage is a strong soft hint, I97 is weaker, and S67 is advisory only.")
    lines.append("4. Distinct epitopes are allowed only if they still create ligand interference.")
    lines.append("5. CDR3 occlusion is useful but should be combined with total steric wall; do not require CDR3 to explain most occlusion.")
    lines.append("6. Fc/NK/CD226/TIGIT biology is a separate context layer, not a docking substitute.")
    lines.append("7. Positive controls calibrate the method but must also act as leakage exclusions.")
    lines.append("8. Docking contact residues are inference unless backed by complex structures or epitope maps.")
    lines.append("")
    lines.append("## Output files")
    lines.append("")
    lines.append("- `docking/success_case_validation/success_case_mechanism_criteria_matrix.csv`")
    lines.append("- `docking/success_case_validation/blocker_judgment_rules_v2.json`")
    lines.append("- `docking/success_case_validation/blocker_design_judgment_standards_v2.md`")
    lines.append("- `docking/success_case_validation/validate_success_case_standards.py`")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv()
    write_json()
    write_markdown()
    write_report()


if __name__ == "__main__":
    main()
