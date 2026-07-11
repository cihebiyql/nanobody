# Phase 2 V2.5 Prospective PVRIG Assay Panel

Current target verdict: **DATA_NOT_READY_FOR_TARGET_MODEL**.

This 24-pair panel is a preregistered acquisition plan, not experimental evidence. No row becomes E6 truth until binding, competition, and QC measurements are complete and the sealed labels are unblinded once.

## Panel Shape

- Total: 24 VHH-PVRIG pairs in 8 groups of three.
- Paired mutation-effect groups: 5.
- Binder/nonblocker enrichment groups: 2.
- Verified-nonbinder confirmation groups: 1.
- Required measurements: SPR/BLI Kd, PVRIG-PVRL2 competition IC50 and/or reporter EC50, plus expression/SEC/aggregation QC.
- Replication: at least three independent runs across at least two days with randomized sample order.

## Gate Rule

A designed disruptive or alanine-scan sequence is not a negative. It can become a verified nonbinder only after concentration-dependent binding is absent through the preregistered maximum analyte concentration in all replicates and expression/SEC QC passes. Assay or expression failure remains excluded, not relabeled.

## Groups

### pvrig_family_20

- `mut_01_PVRIG-20_base_reference` - known_positive_reference - current status: `KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED`
- `mut_02_PVRIG-20_cdr3_cons_F99Y` - conservative_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`
- `mut_03_PVRIG-20_cdr3_arom_F99A` - paratope_disruptive_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`

### pvrig_family_30

- `mut_07_PVRIG-30_base_reference` - known_positive_reference - current status: `KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED`
- `mut_08_PVRIG-30_cdr3_cons_T101S` - conservative_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`
- `mut_09_PVRIG-30_cdr3_arom_W100A` - paratope_disruptive_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`

### pvrig_family_38

- `mut_12_PVRIG-38_base_reference` - known_positive_reference - current status: `KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED`
- `mut_13_PVRIG-38_cdr3_cons_D99E` - conservative_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`
- `mut_14_PVRIG-38_cdr3_arom_F100A` - paratope_disruptive_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`

### pvrig_family_39

- `mut_17_PVRIG-39_base_reference` - known_positive_reference - current status: `KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED`
- `mut_18_PVRIG-39_cdr3_cons_F99Y` - conservative_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`
- `mut_19_PVRIG-39_cdr3_arom_F99A` - paratope_disruptive_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`

### pvrig_family_151

- `case02_pos_01_PVRIG-151_HR151` - known_positive_reference - current status: `KNOWN_POSITIVE_CALIBRATION_REMEASURE_REQUIRED`
- `prospective_HR151_cdr3_cons_Y116F` - conservative_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`
- `prospective_HR151_cdr3_arom_Y116A` - paratope_disruptive_mutant - current status: `DESIGNED_MUTANT_UNMEASURED`

### pvrig_binder_nonblocker_screen_A

- `zym_test_359954` - de_novo_binding_and_competition_screen - current status: `PROSPECTIVE_UNMEASURED`
- `zym_test_5495` - de_novo_binding_and_competition_screen - current status: `PROSPECTIVE_UNMEASURED`
- `zym_test_21966` - de_novo_binding_and_competition_screen - current status: `PROSPECTIVE_UNMEASURED`

### pvrig_binder_nonblocker_screen_B

- `zym_test_3633872` - de_novo_binding_and_competition_screen - current status: `PROSPECTIVE_UNMEASURED`
- `zym_test_8787` - de_novo_binding_and_competition_screen - current status: `PROSPECTIVE_UNMEASURED`
- `zym_test_108006` - de_novo_binding_and_competition_screen - current status: `PROSPECTIVE_UNMEASURED`

### pvrig_verified_nonbinder_confirmation

- `mut_04_PVRIG-20_cdr3_center_ala_scan` - negative_verification_candidate_not_current_negative - current status: `DESIGNED_NEGATIVE_CONTROL_UNMEASURED_NOT_VERIFIED`
- `mut_10_PVRIG-30_cdr3_center_ala_scan` - negative_verification_candidate_not_current_negative - current status: `DESIGNED_NEGATIVE_CONTROL_UNMEASURED_NOT_VERIFIED`
- `mut_15_PVRIG-38_cdr3_center_ala_scan` - negative_verification_candidate_not_current_negative - current status: `DESIGNED_NEGATIVE_CONTROL_UNMEASURED_NOT_VERIFIED`

## Claim Boundary

`prospective_unmeasured_panel_not_binding_or_blocker_validation`
