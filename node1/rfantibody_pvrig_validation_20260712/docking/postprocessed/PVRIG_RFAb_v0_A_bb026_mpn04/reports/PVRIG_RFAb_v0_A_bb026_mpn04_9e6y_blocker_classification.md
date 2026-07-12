# Blocker judgment report: PVRIG_RFAb_v0_A_bb026_mpn04_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 9
- EVIDENCE_INFERENCE_ONLY_E: 1

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 12 | 675 | 119 | 0.176296 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 12 | 591 | 69 | 0.116751 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 3 | 12 | 654 | 116 | 0.17737 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 9 | 734 | 74 | 0.100817 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 10 | 871 | 105 | 0.120551 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 9 | 729 | 72 | 0.0987654 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 10 | 891 | 115 | 0.129068 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 8 | 10 | 717 | 119 | 0.165969 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_2 | BLOCKER_PLAUSIBLE_B | 9 | 12 | 859 | 123 | 0.14319 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 10 | 2 | 531 | 32 | 0.0602637 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
