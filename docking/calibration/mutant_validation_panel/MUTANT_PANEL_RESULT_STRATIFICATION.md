# Mutant Panel Result Stratification

Updated: 2026-07-08

## Bottom line

- Panel records summarized: 36
- Consensus rows summarized: 357
- Aggregate classes: A/A=8; single-A=109; B=210; E=30; other=0
- Case-level calls: BLOCKER_PLAUSIBLE_B_ONLY=3; HAS_CONSENSUS_BLOCKER_LIKE_A=4; HAS_SINGLE_BASELINE_BLOCKER_RECHECK=29
- Manual-review candidates from CDR3-disruptive/alanine rows retaining A/A or single-A evidence: 12
- Machine-readable stratification CSV: `mutant_panel_result_stratification_summary.csv`

## Stratification summaries

### By family

| stratum | panel records | consensus rows | A/A | single-A | B | E | other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 11 | 109 | 1 | 52 | 46 | 10 | 0 |
| 30 | 10 | 98 | 6 | 26 | 58 | 8 | 0 |
| 38 | 5 | 50 | 0 | 11 | 37 | 2 | 0 |
| 39 | 10 | 100 | 1 | 20 | 69 | 10 | 0 |

### By mutation_class

| stratum | panel records | consensus rows | A/A | single-A | B | E | other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| known_20_family_cdr3_stability_delta | 1 | 10 | 0 | 2 | 7 | 1 | 0 |
| multi_cdr3_alanine_scan | 7 | 70 | 1 | 32 | 34 | 3 | 0 |
| single_aromatic_to_alanine_cdr3 | 7 | 68 | 6 | 18 | 40 | 4 | 0 |
| single_conservative_cdr3 | 7 | 69 | 0 | 17 | 43 | 9 | 0 |
| single_conservative_framework | 7 | 70 | 0 | 14 | 48 | 8 | 0 |
| unmutated_positive_control | 7 | 70 | 1 | 26 | 38 | 5 | 0 |

### By leakage_label

| stratum | panel records | consensus rows | A/A | single-A | B | E | other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EXACT_KNOWN_POSITIVE | 7 | 70 | 1 | 26 | 38 | 5 | 0 |
| NEAR_KNOWN_POSITIVE | 29 | 287 | 7 | 83 | 172 | 25 | 0 |

### By base_name

| stratum | panel records | consensus rows | A/A | single-A | B | E | other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20H5 | 5 | 49 | 1 | 25 | 19 | 4 | 0 |
| 30H2 | 5 | 49 | 0 | 11 | 33 | 5 | 0 |
| 39H4 | 5 | 50 | 1 | 15 | 32 | 2 | 0 |
| PVRIG-20 | 6 | 60 | 0 | 27 | 27 | 6 | 0 |
| PVRIG-30 | 5 | 49 | 6 | 15 | 25 | 3 | 0 |
| PVRIG-38 | 5 | 50 | 0 | 11 | 37 | 2 | 0 |
| PVRIG-39 | 5 | 50 | 0 | 5 | 37 | 8 | 0 |

## Manual-review candidates

These rows are CDR3 disruptive/alanine mutants but still contain A/A or single-baseline A consensus support, so they should be inspected before using the mutation panel as a fragility/negative-control readout.

| order | mutant | base | family | mutation class | mutation | leakage | case call | A/A | single-A | B | E |
| ---: | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 3 | mut_03_PVRIG-20_cdr3_arom_F99A | PVRIG-20 | 20 | single_aromatic_to_alanine_cdr3 | F99A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 4 | 5 | 1 |
| 4 | mut_04_PVRIG-20_cdr3_center_ala_scan | PVRIG-20 | 20 | multi_cdr3_alanine_scan | D102A;D103A;D104A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 9 | 1 | 0 |
| 9 | mut_09_PVRIG-30_cdr3_arom_W100A | PVRIG-30 | 30 | single_aromatic_to_alanine_cdr3 | W100A | NEAR_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | 5 | 0 | 4 | 0 |
| 10 | mut_10_PVRIG-30_cdr3_center_ala_scan | PVRIG-30 | 30 | multi_cdr3_alanine_scan | F102A;G103A;G104A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 8 | 2 | 0 |
| 14 | mut_14_PVRIG-38_cdr3_arom_F100A | PVRIG-38 | 38 | single_aromatic_to_alanine_cdr3 | F100A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 1 | 8 | 1 |
| 15 | mut_15_PVRIG-38_cdr3_center_ala_scan | PVRIG-38 | 38 | multi_cdr3_alanine_scan | G103A;S104A;S105A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 1 | 9 | 0 |
| 20 | mut_20_PVRIG-39_cdr3_center_ala_scan | PVRIG-39 | 39 | multi_cdr3_alanine_scan | F101A;G102A;D103A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 1 | 8 | 1 |
| 24 | mut_24_20H5_cdr3_arom_F99A | 20H5 | 20 | single_aromatic_to_alanine_cdr3 | F99A | NEAR_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | 1 | 8 | 1 | 0 |
| 25 | mut_25_20H5_cdr3_center_ala_scan | 20H5 | 20 | multi_cdr3_alanine_scan | D102A;E103A;D104A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 7 | 3 | 0 |
| 30 | mut_30_30H2_cdr3_center_ala_scan | 30H2 | 30 | multi_cdr3_alanine_scan | F102A;G103A;G104A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 4 | 4 | 2 |
| 34 | mut_34_39H4_cdr3_arom_F99A | 39H4 | 39 | single_aromatic_to_alanine_cdr3 | F99A | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 0 | 5 | 4 | 1 |
| 35 | mut_35_39H4_cdr3_center_ala_scan | 39H4 | 39 | multi_cdr3_alanine_scan | F101A;G102A;D103A | NEAR_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | 1 | 2 | 7 | 0 |

## Per-panel record summary

| order | mutant | base | family | mutation class | leakage | case call | class counts | consensus CSV |
| ---: | --- | --- | ---: | --- | --- | --- | --- | --- |
| 1 | mut_01_PVRIG-20_base_reference | PVRIG-20 | 20 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=4; BLOCKER_PLAUSIBLE_B=6; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_01_PVRIG-20_base_reference/reports/mut_01_PVRIG-20_base_reference_8x6b_9e6y_consensus.csv` |
| 2 | mut_02_PVRIG-20_cdr3_cons_F99Y | PVRIG-20 | 20 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=7; BLOCKER_PLAUSIBLE_B=1; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_02_PVRIG-20_cdr3_cons_F99Y/reports/mut_02_PVRIG-20_cdr3_cons_F99Y_8x6b_9e6y_consensus.csv` |
| 3 | mut_03_PVRIG-20_cdr3_arom_F99A | PVRIG-20 | 20 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=4; BLOCKER_PLAUSIBLE_B=5; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_03_PVRIG-20_cdr3_arom_F99A/reports/mut_03_PVRIG-20_cdr3_arom_F99A_8x6b_9e6y_consensus.csv` |
| 4 | mut_04_PVRIG-20_cdr3_center_ala_scan | PVRIG-20 | 20 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=9; BLOCKER_PLAUSIBLE_B=1; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_04_PVRIG-20_cdr3_center_ala_scan/reports/mut_04_PVRIG-20_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 5 | mut_05_PVRIG-20_fw_cons_D61E | PVRIG-20 | 20 | single_conservative_framework | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=7; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_05_PVRIG-20_fw_cons_D61E/reports/mut_05_PVRIG-20_fw_cons_D61E_8x6b_9e6y_consensus.csv` |
| 6 | mut_06_PVRIG-20_patent_20_D103E_style | PVRIG-20 | 20 | known_20_family_cdr3_stability_delta | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=2; BLOCKER_PLAUSIBLE_B=7; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_06_PVRIG-20_patent_20_D103E_style/reports/mut_06_PVRIG-20_patent_20_D103E_style_8x6b_9e6y_consensus.csv` |
| 7 | mut_07_PVRIG-30_base_reference | PVRIG-30 | 30 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | CONSENSUS_BLOCKER_LIKE_A=1; SINGLE_BASELINE_BLOCKER_RECHECK=5; BLOCKER_PLAUSIBLE_B=3; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_07_PVRIG-30_base_reference/reports/mut_07_PVRIG-30_base_reference_8x6b_9e6y_consensus.csv` |
| 8 | mut_08_PVRIG-30_cdr3_cons_T101S | PVRIG-30 | 30 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=9; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_08_PVRIG-30_cdr3_cons_T101S/reports/mut_08_PVRIG-30_cdr3_cons_T101S_8x6b_9e6y_consensus.csv` |
| 9 | mut_09_PVRIG-30_cdr3_arom_W100A | PVRIG-30 | 30 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | CONSENSUS_BLOCKER_LIKE_A=5; SINGLE_BASELINE_BLOCKER_RECHECK=0; BLOCKER_PLAUSIBLE_B=4; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_09_PVRIG-30_cdr3_arom_W100A/reports/mut_09_PVRIG-30_cdr3_arom_W100A_8x6b_9e6y_consensus.csv` |
| 10 | mut_10_PVRIG-30_cdr3_center_ala_scan | PVRIG-30 | 30 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=8; BLOCKER_PLAUSIBLE_B=2; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_10_PVRIG-30_cdr3_center_ala_scan/reports/mut_10_PVRIG-30_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 11 | mut_11_PVRIG-30_fw_cons_Y60F | PVRIG-30 | 30 | single_conservative_framework | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=7; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_11_PVRIG-30_fw_cons_Y60F/reports/mut_11_PVRIG-30_fw_cons_Y60F_8x6b_9e6y_consensus.csv` |
| 12 | mut_12_PVRIG-38_base_reference | PVRIG-38 | 38 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=4; BLOCKER_PLAUSIBLE_B=6; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_12_PVRIG-38_base_reference/reports/mut_12_PVRIG-38_base_reference_8x6b_9e6y_consensus.csv` |
| 13 | mut_13_PVRIG-38_cdr3_cons_D99E | PVRIG-38 | 38 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=9; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_13_PVRIG-38_cdr3_cons_D99E/reports/mut_13_PVRIG-38_cdr3_cons_D99E_8x6b_9e6y_consensus.csv` |
| 14 | mut_14_PVRIG-38_cdr3_arom_F100A | PVRIG-38 | 38 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=8; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_14_PVRIG-38_cdr3_arom_F100A/reports/mut_14_PVRIG-38_cdr3_arom_F100A_8x6b_9e6y_consensus.csv` |
| 15 | mut_15_PVRIG-38_cdr3_center_ala_scan | PVRIG-38 | 38 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=9; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_15_PVRIG-38_cdr3_center_ala_scan/reports/mut_15_PVRIG-38_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 16 | mut_16_PVRIG-38_fw_cons_T61S | PVRIG-38 | 38 | single_conservative_framework | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=4; BLOCKER_PLAUSIBLE_B=5; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_16_PVRIG-38_fw_cons_T61S/reports/mut_16_PVRIG-38_fw_cons_T61S_8x6b_9e6y_consensus.csv` |
| 17 | mut_17_PVRIG-39_base_reference | PVRIG-39 | 39 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=6; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_17_PVRIG-39_base_reference/reports/mut_17_PVRIG-39_base_reference_8x6b_9e6y_consensus.csv` |
| 18 | mut_18_PVRIG-39_cdr3_cons_F99Y | PVRIG-39 | 39 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=5; EVIDENCE_INFERENCE_ONLY_E=4 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_18_PVRIG-39_cdr3_cons_F99Y/reports/mut_18_PVRIG-39_cdr3_cons_F99Y_8x6b_9e6y_consensus.csv` |
| 19 | mut_19_PVRIG-39_cdr3_arom_F99A | PVRIG-39 | 39 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | BLOCKER_PLAUSIBLE_B_ONLY | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=0; BLOCKER_PLAUSIBLE_B=9; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_19_PVRIG-39_cdr3_arom_F99A/reports/mut_19_PVRIG-39_cdr3_arom_F99A_8x6b_9e6y_consensus.csv` |
| 20 | mut_20_PVRIG-39_cdr3_center_ala_scan | PVRIG-39 | 39 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=8; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_20_PVRIG-39_cdr3_center_ala_scan/reports/mut_20_PVRIG-39_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 21 | mut_21_PVRIG-39_fw_cons_Y59F | PVRIG-39 | 39 | single_conservative_framework | NEAR_KNOWN_POSITIVE | BLOCKER_PLAUSIBLE_B_ONLY | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=0; BLOCKER_PLAUSIBLE_B=9; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_21_PVRIG-39_fw_cons_Y59F/reports/mut_21_PVRIG-39_fw_cons_Y59F_8x6b_9e6y_consensus.csv` |
| 22 | mut_22_20H5_base_reference | 20H5 | 20 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=4; BLOCKER_PLAUSIBLE_B=6; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_22_20H5_base_reference/reports/mut_22_20H5_base_reference_8x6b_9e6y_consensus.csv` |
| 23 | mut_23_20H5_cdr3_cons_F99Y | 20H5 | 20 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=4; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_23_20H5_cdr3_cons_F99Y/reports/mut_23_20H5_cdr3_cons_F99Y_8x6b_9e6y_consensus.csv` |
| 24 | mut_24_20H5_cdr3_arom_F99A | 20H5 | 20 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | CONSENSUS_BLOCKER_LIKE_A=1; SINGLE_BASELINE_BLOCKER_RECHECK=8; BLOCKER_PLAUSIBLE_B=1; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_24_20H5_cdr3_arom_F99A/reports/mut_24_20H5_cdr3_arom_F99A_8x6b_9e6y_consensus.csv` |
| 25 | mut_25_20H5_cdr3_center_ala_scan | 20H5 | 20 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=7; BLOCKER_PLAUSIBLE_B=3; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_25_20H5_cdr3_center_ala_scan/reports/mut_25_20H5_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 26 | mut_26_20H5_fw_cons_D61E | 20H5 | 20 | single_conservative_framework | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=5; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_26_20H5_fw_cons_D61E/reports/mut_26_20H5_fw_cons_D61E_8x6b_9e6y_consensus.csv` |
| 27 | mut_27_30H2_base_reference | 30H2 | 30 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=5; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_27_30H2_base_reference/reports/mut_27_30H2_base_reference_8x6b_9e6y_consensus.csv` |
| 28 | mut_28_30H2_cdr3_cons_T101S | 30H2 | 30 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=1; BLOCKER_PLAUSIBLE_B=8; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_28_30H2_cdr3_cons_T101S/reports/mut_28_30H2_cdr3_cons_T101S_8x6b_9e6y_consensus.csv` |
| 29 | mut_29_30H2_cdr3_arom_W100A | 30H2 | 30 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | BLOCKER_PLAUSIBLE_B_ONLY | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=0; BLOCKER_PLAUSIBLE_B=9; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_29_30H2_cdr3_arom_W100A/reports/mut_29_30H2_cdr3_arom_W100A_8x6b_9e6y_consensus.csv` |
| 30 | mut_30_30H2_cdr3_center_ala_scan | 30H2 | 30 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=4; BLOCKER_PLAUSIBLE_B=4; EVIDENCE_INFERENCE_ONLY_E=2 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_30_30H2_cdr3_center_ala_scan/reports/mut_30_30H2_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 31 | mut_31_30H2_fw_cons_Y60F | 30H2 | 30 | single_conservative_framework | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=7; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_31_30H2_fw_cons_Y60F/reports/mut_31_30H2_fw_cons_Y60F_8x6b_9e6y_consensus.csv` |
| 32 | mut_32_39H4_base_reference | 39H4 | 39 | unmutated_positive_control | EXACT_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=6; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_32_39H4_base_reference/reports/mut_32_39H4_base_reference_8x6b_9e6y_consensus.csv` |
| 33 | mut_33_39H4_cdr3_cons_F99Y | 39H4 | 39 | single_conservative_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=3; BLOCKER_PLAUSIBLE_B=7; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_33_39H4_cdr3_cons_F99Y/reports/mut_33_39H4_cdr3_cons_F99Y_8x6b_9e6y_consensus.csv` |
| 34 | mut_34_39H4_cdr3_arom_F99A | 39H4 | 39 | single_aromatic_to_alanine_cdr3 | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=5; BLOCKER_PLAUSIBLE_B=4; EVIDENCE_INFERENCE_ONLY_E=1 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_34_39H4_cdr3_arom_F99A/reports/mut_34_39H4_cdr3_arom_F99A_8x6b_9e6y_consensus.csv` |
| 35 | mut_35_39H4_cdr3_center_ala_scan | 39H4 | 39 | multi_cdr3_alanine_scan | NEAR_KNOWN_POSITIVE | HAS_CONSENSUS_BLOCKER_LIKE_A | CONSENSUS_BLOCKER_LIKE_A=1; SINGLE_BASELINE_BLOCKER_RECHECK=2; BLOCKER_PLAUSIBLE_B=7; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_35_39H4_cdr3_center_ala_scan/reports/mut_35_39H4_cdr3_center_ala_scan_8x6b_9e6y_consensus.csv` |
| 36 | mut_36_39H4_fw_cons_Y59F | 39H4 | 39 | single_conservative_framework | NEAR_KNOWN_POSITIVE | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | CONSENSUS_BLOCKER_LIKE_A=0; SINGLE_BASELINE_BLOCKER_RECHECK=2; BLOCKER_PLAUSIBLE_B=8; EVIDENCE_INFERENCE_ONLY_E=0 | `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_36_39H4_fw_cons_Y59F/reports/mut_36_39H4_fw_cons_Y59F_8x6b_9e6y_consensus.csv` |

## Interpretation boundary

- This report stratifies docking/postprocess labels only; it is not experimental evidence of PVRIG-PVRL2 blocking.
- Exact/near known positives remain leakage or perturbation controls unless separately approved for candidate ranking.
- Single-baseline A rows require manual pose review/redock before promotion.

## Reproducibility

```bash
python docking/success_case_validation/summarize_mutant_panel_results.py
```
