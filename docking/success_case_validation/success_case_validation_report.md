# Success-case validation report for PVRIG blocker standards

Generated: 2026-07-07

## What was verified

Local case-study markdown files, literature CSV evidence tables, and the HR-151 docking positive-control reports were cross-checked. Each extracted criterion is labeled by evidence grade and by whether it is directly computational, experimental, contextual, or a claim boundary.

## Per-case validation

### COM701_CPA7021_Tab5

Validated as the classic binder-versus-blocker and R95/I97 soft-hotspot case. It gives hard negative-control logic: Kd/binding is not enough; PVRIG-PVRL2 blocking or steric competition is required.

- C01_BINDER_NOT_BLOCKER: Binding to PVRIG is not sufficient; require blocking-oriented evidence or geometry that competes with PVRL2.
- C01_KD_AND_IC50_SPLIT: Treat Kd as binding evidence and IC50/competition as blocking evidence; never collapse them into one docking score.
- C01_R95_I97_S67_WEIGHTING: Use R95 as high-weight soft hotspot, I97 as low/medium hint, and S67 as advisory epitope/cross-reactivity clue only.
- C01_POSITIVE_CONTROL_LEAKAGE: Use Tab5/CPA.7.021 as positive-control mechanism references and sequence leakage exclusions, not as templates to copy.
- C01_FC_FORMAT_IS_INDEPENDENT: Fc-reduced/IgG4 checkpoint-blocking logic is a format choice, not the same variable as epitope blocking.
- C01_COMBINATION_CONTEXT: PVRIG blockade may be nonredundant and combination-sensitive; do not reject a blocker only because one isolated T-cell readout is weak.
- C01_NO_COMPLEX_CAVEAT: Do not state COM701/Tab5 contact residues as experimentally proven without a public complex structure or verified patent figures.

### PVRIG_VHH_20_30_38_39_151_HR151

Validated as the VHH-positive family plus the current executable docking calibration. HR-151 thresholds support BLOCKER_LIKE_A, and cluster_2 supplies an internal hotspot-only negative control.

- C02_VHH_BLOCKING_VALUES: Multiple VHH families show nM-level PVRIG-PVRL2 blocking; do not calibrate only to PVRIG-151/HR-151.
- C02_BINDING_VALUES: Successful VHH blockers also have sub-nM to low-nM binding, but binding strength does not replace blocking assessment.
- C02_HR151_OCCLUSION_THRESHOLDS: First-pass BLOCKER_LIKE_A requires hotspot overlap >=14, total VHH-PVRL2 residue-pair occlusion >=500, CDR3-PVRL2 residue-pair occlusion >=100, and CDR3 occlusion fraction >=0.15.
- C02_HOTSPOT_ONLY_NEGATIVE_CONTROL: Hotspot/interface contact with total PVRL2 occlusion <50 is BINDER_LIKE_C and should be downgraded.
- C02_CDR3_WEDGE_NOT_ONLY_FACTOR: CDR3 should provide nontrivial PVRL2 occlusion, but requiring CDR3 to explain >50% of occlusion is too strict.
- C02_CDR_NUMBERING_NORMALIZATION: Normalize Kabat/IMGT CDR definitions with ANARCI before similarity or contact comparisons.
- C02_FORMAT_DEPENDENCE: Single VHH blocking can be strong, but VHH-Fc, bivalent, or TIGIT-PVRIG bispecific format may determine in-vivo strength.

### IBI352g4a

Validated as the Fc/NK context case. It still starts with binding plus blocking, but shows that NK, Fc/CD16a, and model context must be scored separately from docking.

- C03_BLOCKING_FIRST: Even Fc/NK-enhanced antibodies must first satisfy PVRIG binding and PVRIG-PVRL2 blocking.
- C03_NK_PRIMARY_READOUT: For Fc-competent PVRIG antibodies, NK activation/killing is a primary success readout, not an optional afterthought.
- C03_MODEL_CONTEXT_REQUIRED: In-vivo interpretation must record NK-supporting vs T-cell-skewed model context.
- C03_FC_CD16A_INDEPENDENT_SCORE: Fc/CD16a coengagement is a separate efficacy amplifier for IgG1/VHH-Fc/bispecific formats.
- C03_LAYERED_SCORING: Keep antigen binding, ligand blocking, epitope competition, format compatibility, cell-context, and developability as separate scores.
- C03_NO_CDR_TEMPLATE: Use IBI352g4a as Fc/NK mechanism constraint, not as a CDR or residue-contact template.

### GSK4381562_SRF813

Validated as the distinct-epitope anti-overfit case. It allows alternative epitope solutions while preserving the hard requirement that PVRL2/CD112 blocking remains necessary.

- C04_DISTINCT_EPITOPE_ALLOWED: Allow blocker poses that do not mimic HR-151/Tab5/R95-I97, provided they still block or occlude the functional PVRIG-PVRL2 interface.
- C04_BLOCKING_STILL_REQUIRED: Distinct epitope does not relax the core blocking requirement against CD112/PVRL2.
- C04_IGG1_FORMAT_CONTEXT: For IgG1 examples, separate Fab/Fv docking conclusions from Fc/NK/T-cell function conclusions.
- C04_CD226_AXIS: Record whether blockade may restore PVRL2-CD226/DNAM-1 activating context, not only physical ligand displacement.
- C04_NK_T_CELL_READOUTS: Distinct-epitope blockers should preserve both NK and T-cell readout labels for downstream validation.
- C04_CLINICAL_CAVEAT: Use SRF813/GSK4381562 as mechanism calibration and anti-overfit evidence, not as proven clinical efficacy evidence.
- C04_NO_PUBLIC_COMPLEX: Residue contacts for SRF813-like poses must be labeled as computational inference unless a public complex or epitope map is added.

### SHR2002_TIGIT8_PVRIG30

Validated as a bispecific-format case showing that a PVRIG nanobody arm, especially PVRIG-30 family, may succeed in TIGIT/PVRIG co-blocking architecture.

- C05_SHR2002_CO_BLOCKING: A PVRIG nanobody arm can succeed as part of a TIGIT/PVRIG co-blocking bispecific; future evaluation should not stop at naked VHH properties.
- C05_PVRIG30_IS_NOT_SECONDARY: PVRIG-30 family should be kept as a meaningful positive reference because it appears in bispecific context.
- C05_FORMAT_SPECIFIC_NOT_NAKED_PROOF: SHR-2002 supports format-aware ranking, not proof that naked PVRIG-30 alone is optimal.

### PM1009_SIM0348

Validated as lower-resolution multi-axis mechanism evidence. It supports DNAM/CD226 and TIGIT/PVRIG co-blocking labels but does not provide quantitative docking thresholds.

- C06_PM1009_SIM0348_MULTI_AXIS: PVRIG blockers can be part of multi-axis DNAM/CD226 rebalancing designs, including anti-TIGIT/anti-PVRIG bispecifics.
- C06_FC_TREG_CONTEXT: Some multi-axis IgG1 designs may include Fc-mediated effects such as killing TIGIT/PVRIG-expressing Tregs; record this as a separate effector mechanism.
- C06_SUMMARY_EVIDENCE_CAVEAT: Drug-dictionary mechanism entries are useful labels but lower-weight than assay, structure, or peer-reviewed data.

### CD112RIVE_structure_guided_trap

Validated as non-antibody interface-engineering evidence. It supports contact-density and affinity-tuning features, not antibody CDR templates.

- C07_CD112RIVE_INTERFACE_ENGINEERING: The PVRIG/CD112 interface can be engineered by structure-guided affinity tuning; use interface residue priority and contact density instead of black-box docking alone.
- C07_NOT_ANTIBODY_CAVEAT: CD112RIVE is not an anti-PVRIG antibody; use it to validate interface engineering logic, not antibody paratope templates.

### NK_cell_blockade_biology

Validated as biology-context evidence requiring NK/tumor-context labels in downstream validation.

- C08_NK_BIOLOGY_REQUIRED: PVRIG blocker validation should include NK activation/tumor-context labels, not only CD8 T-cell rescue.

## Extracted decision hierarchy

1. Binding is necessary but not sufficient.
2. Direct PVRIG-PVRL2/CD112 blocking or PVRL2 overlay occlusion is the primary blocker gate.
3. R95/interface coverage is a strong soft hint, I97 is weaker, and S67 is advisory only.
4. Distinct epitopes are allowed only if they still create ligand interference.
5. CDR3 occlusion is useful but should be combined with total steric wall; do not require CDR3 to explain most occlusion.
6. Fc/NK/CD226/TIGIT biology is a separate context layer, not a docking substitute.
7. Positive controls calibrate the method but must also act as leakage exclusions.
8. Docking contact residues are inference unless backed by complex structures or epitope maps.

## Output files

- `docking/success_case_validation/success_case_mechanism_criteria_matrix.csv`
- `docking/success_case_validation/blocker_judgment_rules_v2.json`
- `docking/success_case_validation/blocker_design_judgment_standards_v2.md`
- `docking/success_case_validation/validate_success_case_standards.py`

