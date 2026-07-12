# Blocker judgment report: PVRIG_RFAb_v0_A_bb026_mpn04_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 3
- BLOCKER_PLAUSIBLE_B: 6
- EVIDENCE_INFERENCE_ONLY_E: 1

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 17 | 662 | 108 | 0.163142 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 3 | 18 | 645 | 108 | 0.167442 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_6_model_1 | BLOCKER_LIKE_A | 8 | 15 | 690 | 114 | 0.165217 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 19 | 595 | 83 | 0.139496 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 13 | 710 | 77 | 0.108451 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 14 | 833 | 96 | 0.115246 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 14 | 720 | 73 | 0.101389 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 17 | 872 | 110 | 0.126147 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_2 | BLOCKER_PLAUSIBLE_B | 9 | 17 | 844 | 120 | 0.14218 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 10 | 4 | 489 | 24 | 0.0490798 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
