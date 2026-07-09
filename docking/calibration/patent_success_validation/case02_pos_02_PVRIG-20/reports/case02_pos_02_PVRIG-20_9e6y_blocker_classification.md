# Blocker judgment report: case02_pos_02_PVRIG-20_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 7
- EVIDENCE_INFERENCE_ONLY_E: 3

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 12 | 511 | 163 | 0.318982 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 11 | 964 | 162 | 0.16805 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 10 | 540 | 103 | 0.190741 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 9 | 673 | 132 | 0.196137 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 11 | 642 | 130 | 0.202492 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 11 | 587 | 180 | 0.306644 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_8_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 7 | 541 | 106 | 0.195933 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 3 | 9 | 486 | 156 | 0.320988 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 8 | 7 | 369 | 64 | 0.173442 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_7_model_2 | EVIDENCE_INFERENCE_ONLY_E | 9 | 6 | 305 | 56 | 0.183607 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
