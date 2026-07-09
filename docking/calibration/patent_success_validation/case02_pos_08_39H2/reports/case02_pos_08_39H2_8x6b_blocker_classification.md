# Blocker judgment report: case02_pos_08_39H2_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 4
- EVIDENCE_INFERENCE_ONLY_E: 6

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 16 | 815 | 103 | 0.12638 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 10 | 534 | 65 | 0.121723 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 7 | 10 | 519 | 75 | 0.144509 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 8 | 10 | 440 | 123 | 0.279545 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_2_model_1 | EVIDENCE_INFERENCE_ONLY_E | 2 | 8 | 251 | 67 | 0.266932 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 3 | 9 | 383 | 136 | 0.355091 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_5_model_1 | EVIDENCE_INFERENCE_ONLY_E | 5 | 9 | 471 | 49 | 0.104034 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_4_model_2 | EVIDENCE_INFERENCE_ONLY_E | 6 | 7 | 413 | 58 | 0.140436 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 9 | 9 | 322 | 134 | 0.416149 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_3_model_2 | EVIDENCE_INFERENCE_ONLY_E | 10 | 8 | 365 | 132 | 0.361644 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
