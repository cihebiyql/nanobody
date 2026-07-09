# PVRIG blocker design judgment standards v2

Generated: 2026-07-07

## Bottom line

The standard is not highest docking score. A future candidate should pass a layered chain: bind PVRIG ECD -> occupy or perturb the functional interface -> block PVRIG-PVRL2/CD112 -> fit the intended format and NK/T-cell context -> avoid positive-control sequence leakage.

## Classifier

### BLOCKER_LIKE_A

Prioritized structurally blocker-like pose or experimentally proven blocker-like candidate.

VHH docking first-pass thresholds:

- `hotspot_overlap_count` >= 14
- `total_vhh_pvrl2_residue_pair_occlusion` >= 500
- `cdr3_pvrl2_residue_pair_occlusion` >= 100
- `cdr3_occlusion_fraction` >= 0.15
- Experimental equivalent: Strong PVRIG binding plus direct PVRIG-PVRL2/CD112 blocking evidence, ideally low-nM IC50 or better.

### BLOCKER_PLAUSIBLE_B

Alternative epitope or format-aware candidate with plausible ligand interference but incomplete quantitative support.

- blocking evidence missing or weaker
- must not be remote binder-only
- needs follow-up assay or second-structure validation

### BINDER_LIKE_C

PVRIG binder or interface-contacting pose without enough PVRL2 blocking geometry.

Rule: If hotspot_overlap_count >= 14 but total_vhh_pvrl2_residue_pair_occlusion < 50, downgrade to BINDER_LIKE_C.

### FORMAT_CONTEXT_D

Mechanistically interesting only in Fc, VHH-Fc, or bispecific architecture context.

Rule: Do not infer this class from naked VHH docking alone.

### EVIDENCE_INFERENCE_ONLY_E

Useful hypothesis or case label with insufficient structure/assay evidence for blocker prioritization.

Rule: Keep in research notes; do not advance as blocker proof.

## Gates for future candidates

- Hard gate: Separate binding evidence from ligand-blocking evidence.
- Hard gate: Require PVRL2/CD112 blocking geometry or assay evidence before calling a candidate blocker-like.
- Hard gate: Downgrade hotspot-only non-occluding poses.
- Hard gate: Apply positive-control leakage checks against HR-151, Tab5/CPA.7.021, and known VHH families using normalized CDR definitions.
- Hard gate: Label residue contacts from docking as inference unless supported by a public complex or epitope map.
- Soft/context feature: Consensus interface coverage, especially R95 neighborhood.
- Soft/context feature: PVRL2 steric occlusion from a plausible CDR/paratope angle.
- Soft/context feature: Alternative distinct epitope that still interferes with PVRL2 binding.
- Soft/context feature: Compatibility with intended format: naked VHH, VHH-Fc, IgG1/IgG4, or TIGIT/PVRIG bispecific.
- Soft/context feature: NK/Fc/CD226/TIGIT context annotations for downstream functional validation.

## Case-derived standards

### COM701_CPA7021_Tab5: COM701 / CPA.7.021 / Tab5

- `C01_BINDER_NOT_BLOCKER` (HIGH, hard_negative_control): Binding to PVRIG is not sufficient; require blocking-oriented evidence or geometry that competes with PVRL2.
  Positive: PVRIG binder also blocks PVRIG-PVRL2 under competition assay or has PVRL2-occluding pose.
  Caution: Good Kd/BLI or docking energy without IC50/competition/occlusion is binder-like, not blocker-like.
  Use: Hard gate before ranking; do not advance binder-only candidates as blocker leads.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:110-133; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:2
- `C01_KD_AND_IC50_SPLIT` (HIGH, binding_vs_blocking): Treat Kd as binding evidence and IC50/competition as blocking evidence; never collapse them into one docking score.
  Positive: Both binding and ligand-blocking measurements or proxies are present.
  Caution: Only Kd/EC50/binding score is reported.
  Use: Report binding_score and blocking_score as separate columns for every candidate.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:101-107
- `C01_R95_I97_S67_WEIGHTING` (HIGH, soft_hotspot): Use R95 as high-weight soft hotspot, I97 as low/medium hint, and S67 as advisory epitope/cross-reactivity clue only.
  Positive: Pose covers consensus interface and can include R95/I97 neighborhood without needing to copy Tab5.
  Caution: Candidate is designed mainly around S67 while losing PVRL2-interface coverage.
  Use: Weight R95/interface coverage; do not make S67 a hard objective.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:193-243; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:2
- `C01_POSITIVE_CONTROL_LEAKAGE` (HIGH, leakage_guard): Use Tab5/CPA.7.021 as positive-control mechanism references and sequence leakage exclusions, not as templates to copy.
  Positive: Different CDR/paratope reaches the same functional interface.
  Caution: High CDR similarity to Tab5/CPA.7.021/HR-151 or light mutation of known positives.
  Use: Add positive_CDR_leakage_penalty before final ranking.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:62-67; 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:299-304
- `C01_FC_FORMAT_IS_INDEPENDENT` (MEDIUM, format_context): Fc-reduced/IgG4 checkpoint-blocking logic is a format choice, not the same variable as epitope blocking.
  Positive: Candidate report states whether it is naked VHH, VHH-Fc, IgG4, IgG1, or bispecific.
  Caution: Docking result is used to claim Fc-mediated or in-vivo activity.
  Use: Keep format_compatibility_score separate from paratope docking score.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:248-276
- `C01_COMBINATION_CONTEXT` (MEDIUM, combo_context): PVRIG blockade may be nonredundant and combination-sensitive; do not reject a blocker only because one isolated T-cell readout is weak.
  Positive: Mechanism can be tested with PD-1/TIGIT combination or PVRL2-high tumor context labels.
  Caution: Single-assay failure is overinterpreted as no PVRIG mechanism.
  Use: Add TIGIT_PD1_combination_context and PVRL2_high_tumor_context annotations.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:169-187
- `C01_NO_COMPLEX_CAVEAT` (CAUTION, claim_boundary): Do not state COM701/Tab5 contact residues as experimentally proven without a public complex structure or verified patent figures.
  Positive: Claims are labeled as patent mapping, structure baseline, or docking inference.
  Caution: Residue contacts are stated as direct complex facts.
  Use: Keep evidence_level and inference_level fields in reports.
  Sources: 机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md:320-330

### PVRIG_VHH_20_30_38_39_151_HR151: PVRIG-20/30/38/39/151 and HR-151

- `C02_VHH_BLOCKING_VALUES` (HIGH, positive_family): Multiple VHH families show nM-level PVRIG-PVRL2 blocking; do not calibrate only to PVRIG-151/HR-151.
  Positive: Candidate resembles a new functional solution among several VHH families and passes blocking geometry.
  Caution: Ranking treats 151/HR-151 as the only useful positive center.
  Use: Use multiple VHH families as success-case anchors and positive-leakage controls.
  Sources: 机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md:96-117; 机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_evidence_table.csv:2-7
- `C02_BINDING_VALUES` (HIGH, binding_support): Successful VHH blockers also have sub-nM to low-nM binding, but binding strength does not replace blocking assessment.
  Positive: Candidate has plausible affinity support and independent PVRL2-competition support.
  Caution: Candidate has high predicted binding but no PVRL2 occlusion or blocking assay.
  Use: Use binding as prerequisite/support, then apply occlusion and interface gates.
  Sources: 机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md:121-149; 机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_evidence_table.csv:2-7
- `C02_HR151_OCCLUSION_THRESHOLDS` (HIGH_FOR_SCREENING, hard_computational_gate): First-pass BLOCKER_LIKE_A requires hotspot overlap >=14, total VHH-PVRL2 residue-pair occlusion >=500, CDR3-PVRL2 residue-pair occlusion >=100, and CDR3 occlusion fraction >=0.15.
  Positive: Pose passes all HR-151-calibrated occlusion thresholds.
  Caution: Pose fails PVRL2 overlay occlusion even if HADDOCK score or hotspot overlap is strong.
  Use: Use as the current executable screen for VHH blocker-like docking poses.
  Sources: docking/case02_hr151_pvrig/reports/blocker_validation_protocol_v1.md:29-49
- `C02_HOTSPOT_ONLY_NEGATIVE_CONTROL` (HIGH_FOR_SCREENING, hard_negative_control): Hotspot/interface contact with total PVRL2 occlusion <50 is BINDER_LIKE_C and should be downgraded.
  Positive: High hotspot overlap plus substantial total and CDR3 occlusion.
  Caution: HR-151 cluster_2 pattern: hotspot overlap 20 but total and CDR3 occlusion 0.
  Use: Reject hotspot-only non-occluding poses before final ranking.
  Sources: docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md:62-68; docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md:99-114
- `C02_CDR3_WEDGE_NOT_ONLY_FACTOR` (MEDIUM_HIGH_FOR_SCREENING, paratope_geometry): CDR3 should provide nontrivial PVRL2 occlusion, but requiring CDR3 to explain >50% of occlusion is too strict.
  Positive: CDR3 contributes a focused wedge while framework provides supporting steric wall outside the interface.
  Caution: Rules force long-CDR3 dominance and reject compact or framework-supported blockers.
  Use: Keep CDR3-specific occlusion threshold modest and combine with total occlusion.
  Sources: docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md:75-96
- `C02_CDR_NUMBERING_NORMALIZATION` (HIGH, leakage_guard): Normalize Kabat/IMGT CDR definitions with ANARCI before similarity or contact comparisons.
  Positive: All candidate and positive-control CDRs are compared under one numbering convention.
  Caution: Mixed Kabat and IMGT CDRs create false similarity or false novelty.
  Use: Run ANARCI/IMGT before CDR leakage exclusion and CDR-specific scoring.
  Sources: 机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md:184-211; 机制/data/literature/PVRIG_case02_vhh_docking_calibration_tags.csv:12-13
- `C02_FORMAT_DEPENDENCE` (MEDIUM_HIGH, format_context): Single VHH blocking can be strong, but VHH-Fc, bivalent, or TIGIT-PVRIG bispecific format may determine in-vivo strength.
  Positive: Candidate remains geometrically compatible with Fc fusion or bispecific architecture if that is the development route.
  Caution: Naked VHH docking is used to infer in-vivo efficacy or bispecific coengagement.
  Use: Add VHH_fusion_compatibility_score and TIGIT_combination_potential.
  Sources: 机制/data/literature/PVRIG_case02_vhh_docking_calibration_tags.csv:9-11; 机制/success_cases/PVRIG成功案例机制研究_v1.md:379-386

### IBI352g4a: IBI352g4a Fc-competent anti-PVRIG

- `C03_BLOCKING_FIRST` (HIGH, hard_functional_gate): Even Fc/NK-enhanced antibodies must first satisfy PVRIG binding and PVRIG-PVRL2 blocking.
  Positive: Binding Kd/EC50 and PVRIG-PVRL2 blocking IC50 are both in the nM range or better.
  Caution: Fc/NK mechanism is invoked without showing ligand blocking.
  Use: Do not let format biology bypass ligand-blocking gate.
  Sources: 机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:64-83; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:4-8
- `C03_NK_PRIMARY_READOUT` (HIGH, cell_context): For Fc-competent PVRIG antibodies, NK activation/killing is a primary success readout, not an optional afterthought.
  Positive: CD107a/CD137 or NK killing rises in PVRL2-high tumor/NK coculture or analogous setting.
  Caution: Only immediate T-cell activation is measured and NK is absent.
  Use: Add NK_activation_support and PVRL2_high_tumor_context labels.
  Sources: 机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:92-142; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:9-11
- `C03_MODEL_CONTEXT_REQUIRED` (HIGH, cell_context): In-vivo interpretation must record NK-supporting vs T-cell-skewed model context.
  Positive: Candidate is evaluated in a model with NK, Fc receptor, and PVRL2 context when claiming Fc-competent efficacy.
  Caution: A weak NK-poor model is used to reject the mechanism globally.
  Use: Store model_context and immune_compartment fields with efficacy data.
  Sources: 机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:147-171; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:12
- `C03_FC_CD16A_INDEPENDENT_SCORE` (HIGH, format_context): Fc/CD16a coengagement is a separate efficacy amplifier for IgG1/VHH-Fc/bispecific formats.
  Positive: Format can engage Fc receptors when desired and does not block the paratope geometry.
  Caution: All anti-PVRIG designs are forced to IgG1, or naked VHH is expected to reproduce Fc effects.
  Use: Add format_score and Fc_engagement_required_or_not; keep them separate from docking.
  Sources: 机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:215-243; 机制/data/literature/PVRIG_case03_ibi352g4a_fc_nk_evidence_table.csv:15-16
- `C03_LAYERED_SCORING` (HIGH, scoring_architecture): Keep antigen binding, ligand blocking, epitope competition, format compatibility, cell-context, and developability as separate scores.
  Positive: Candidate has a multi-column evidence profile rather than one blended docking number.
  Caution: Binding/docking score is treated as final drug-efficacy score.
  Use: Use this as the schema for future candidate scorecards.
  Sources: 机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:254-279
- `C03_NO_CDR_TEMPLATE` (CAUTION, claim_boundary): Use IBI352g4a as Fc/NK mechanism constraint, not as a CDR or residue-contact template.
  Positive: Reports cite it for blocking plus Fc/NK biology only.
  Caution: Residue epitope or sequence-derived CDR lessons are inferred without public sequence/complex evidence.
  Use: Mark residue-level conclusions as unavailable.
  Sources: 机制/case_studies/03_IBI352g4a_Fc_NK_机制详解.md:307-313

### GSK4381562_SRF813: GSK4381562 / SRF813 / remzistotug

- `C04_DISTINCT_EPITOPE_ALLOWED` (HIGH_FOR_ANTI_OVERFIT, anti_overfit): Allow blocker poses that do not mimic HR-151/Tab5/R95-I97, provided they still block or occlude the functional PVRIG-PVRL2 interface.
  Positive: Alternative epitope/angle still creates PVRL2 steric occlusion or credible allosteric ligand interference.
  Caution: Remote binder is accepted merely because distinct epitopes are allowed.
  Use: Use as anti-overfit control family in ranking and model training.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:24-30; 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:74-106; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:2-4
- `C04_BLOCKING_STILL_REQUIRED` (HIGH, hard_functional_gate): Distinct epitope does not relax the core blocking requirement against CD112/PVRL2.
  Positive: Candidate has PVRL2 occlusion, competition assay, or ligand-interference evidence.
  Caution: Nonblocking remote-surface binder is scored high as distinct.
  Use: Keep BLOCKING_STILL_REQUIRED as a hard gate in every epitope bin.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:115-127; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:3
- `C04_IGG1_FORMAT_CONTEXT` (MEDIUM_HIGH, format_context): For IgG1 examples, separate Fab/Fv docking conclusions from Fc/NK/T-cell function conclusions.
  Positive: Fab epitope geometry and IgG1 functional context are reported as separate fields.
  Caution: Fv docking alone is used to claim IgG1 Fc benefit.
  Use: Add IGG1_FORMAT_CONTEXT and avoid docking-only functional claims.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:129-150; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:5
- `C04_CD226_AXIS` (MEDIUM, downstream_pathway): Record whether blockade may restore PVRL2-CD226/DNAM-1 activating context, not only physical ligand displacement.
  Positive: Candidate is paired with CD226-axis annotation in functional plans.
  Caution: Docking clash is treated as the entire PVRIG mechanism.
  Use: Add CD226_axis_relevant and ligand_redirection notes.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:155-198; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:6
- `C04_NK_T_CELL_READOUTS` (MEDIUM, cell_context): Distinct-epitope blockers should preserve both NK and T-cell readout labels for downstream validation.
  Positive: Functional package includes NK and T-cell activation assays or planned labels.
  Caution: Only T-cell readout or only docking is used to judge the mechanism.
  Use: Keep NK_AND_T_CELL_READOUT as a standard annotation.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:203-231; 机制/data/literature/PVRIG_case04_srf813_docking_calibration_tags.csv:7
- `C04_CLINICAL_CAVEAT` (CAUTION, claim_boundary): Use SRF813/GSK4381562 as mechanism calibration and anti-overfit evidence, not as proven clinical efficacy evidence.
  Positive: Clinical/IND status is described cautiously and separately from mechanism claims.
  Caution: Clinical-stage or abandonment status is used as direct proof or disproof of docking correctness.
  Use: Keep commercial/clinical outcome outside the docking validation label.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:235-249
- `C04_NO_PUBLIC_COMPLEX` (CAUTION, claim_boundary): Residue contacts for SRF813-like poses must be labeled as computational inference unless a public complex or epitope map is added.
  Positive: Report says inferred_pose_contact rather than experimental_contact.
  Caution: Exact distinct-epitope residues are asserted without source.
  Use: Keep source evidence level and no_public_complex warning.
  Sources: 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:277-295; 机制/case_studies/04_GSK4381562_SRF813_distinct_epitope_机制详解.md:368-387

### SHR2002_TIGIT8_PVRIG30: SHR-2002 / TIGIT-8-PVRIG-30-IgG4

- `C05_SHR2002_CO_BLOCKING` (MEDIUM_HIGH, bispecific_format): A PVRIG nanobody arm can succeed as part of a TIGIT/PVRIG co-blocking bispecific; future evaluation should not stop at naked VHH properties.
  Positive: PVRIG arm remains exposed and can coengage PVRIG while TIGIT arm blocks TIGIT/CD155.
  Caution: Strong naked VHH docking is assumed to survive fusion without checking exposure/linker geometry.
  Use: Add TIGIT_combination_potential and fusion_exposure checks for format candidates.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:219-257; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:6
- `C05_PVRIG30_IS_NOT_SECONDARY` (MEDIUM_HIGH, positive_family): PVRIG-30 family should be kept as a meaningful positive reference because it appears in bispecific context.
  Positive: Candidate set includes non-151 VHH families in calibration.
  Caution: All non-151 families are discarded as weaker despite format success evidence.
  Use: Keep PVRIG-30-like family diversity in validation and leakage checks.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:234-246; 机制/success_cases/PVRIG成功案例机制研究_v1.md:379-386; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:6
- `C05_FORMAT_SPECIFIC_NOT_NAKED_PROOF` (CAUTION, format_context): SHR-2002 supports format-aware ranking, not proof that naked PVRIG-30 alone is optimal.
  Positive: Report distinguishes arm-level paratope from whole-bispecific efficacy.
  Caution: Bispecific efficacy is credited entirely to the PVRIG nanobody arm.
  Use: Separate paratope_score from architecture_score.
  Sources: 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:6

### PM1009_SIM0348: PM1009 / SIM0348

- `C06_PM1009_SIM0348_MULTI_AXIS` (MEDIUM, multi_axis_format): PVRIG blockers can be part of multi-axis DNAM/CD226 rebalancing designs, including anti-TIGIT/anti-PVRIG bispecifics.
  Positive: Candidate strategy records whether it targets PVRIG alone or TIGIT/PVRIG jointly.
  Caution: PVRIG-only docking is used to judge multi-axis format efficacy.
  Use: Add DNAM_axis_co_blocking_concept and TIGIT_PVRIG_co_blocking labels.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:259-280; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:7
- `C06_FC_TREG_CONTEXT` (LOW_MEDIUM, effector_context): Some multi-axis IgG1 designs may include Fc-mediated effects such as killing TIGIT/PVRIG-expressing Tregs; record this as a separate effector mechanism.
  Positive: Effector function is intentionally desired and supported by format/assay plan.
  Caution: Fc-mediated depletion is inferred from PVRIG docking alone.
  Use: Add effector_function_intended flag for IgG1 or bispecific formats.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:272-280; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:7
- `C06_SUMMARY_EVIDENCE_CAVEAT` (CAUTION, evidence_weight): Drug-dictionary mechanism entries are useful labels but lower-weight than assay, structure, or peer-reviewed data.
  Positive: Used to define future-format labels, not quantitative docking thresholds.
  Caution: Mechanism summary is treated as detailed epitope/affinity evidence.
  Use: Use for roadmap annotations only until primary data are added.
  Sources: 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:7

### CD112RIVE_structure_guided_trap: CD112RIVE / engineered CD112R variants

- `C07_CD112RIVE_INTERFACE_ENGINEERING` (MEDIUM_HIGH, interface_engineering): The PVRIG/CD112 interface can be engineered by structure-guided affinity tuning; use interface residue priority and contact density instead of black-box docking alone.
  Positive: Candidate design/ranking explains which interface contacts or buried-surface features are improved.
  Caution: Docking score changes without interface-residue rationale are overtrusted.
  Use: Add interface_residue_priority, contact_density, and affinity_tuning_residue_map fields.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:282-307; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:8
- `C07_NOT_ANTIBODY_CAVEAT` (CAUTION, modality_boundary): CD112RIVE is not an anti-PVRIG antibody; use it to validate interface engineering logic, not antibody paratope templates.
  Positive: Used as feature-prior evidence for interface residues and ligand competition geometry.
  Caution: Its engineered receptor residues are copied into antibody CDR logic.
  Use: Keep antibody_modality and ligand_trap_modality separate.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:282-307; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:8

### NK_cell_blockade_biology: PVRIG blockade biology in NK studies

- `C08_NK_BIOLOGY_REQUIRED` (MEDIUM_HIGH, cell_context): PVRIG blocker validation should include NK activation/tumor-context labels, not only CD8 T-cell rescue.
  Positive: Functional plan includes NK, CD8, PVRL2-high tumor, or PBMC-reconstituted xenograft context.
  Caution: Candidate is rejected or accepted using only one T-cell checkpoint readout.
  Use: Add NK_activation_support and tumor_context fields to all candidate reports.
  Sources: 机制/success_cases/PVRIG成功案例机制研究_v1.md:347-359; 机制/data/literature/PVRIG_success_case_evidence_matrix.csv:9

## Practical validation route

1. Normalize candidate and positive-control CDRs with ANARCI/IMGT; apply leakage exclusion.
2. Model candidate VHH or Fv/Fab; dock to fixed PVRIG with hotspot/CDR-guided workflow.
3. Align pose to 8X6B and 9E6Y PVRIG baselines; overlay PVRL2/CD112.
4. Score hotspot overlap, total VHH/Fv-PVRL2 occlusion, CDR3-specific occlusion, and CDR contact pattern.
5. Classify with the rules above, then add format/NK/CD226/TIGIT context labels instead of blending them into docking score.
6. Treat passing docking as structurally blocker-like, not experimental proof; confirm with competition IC50 or cell assay when possible.

