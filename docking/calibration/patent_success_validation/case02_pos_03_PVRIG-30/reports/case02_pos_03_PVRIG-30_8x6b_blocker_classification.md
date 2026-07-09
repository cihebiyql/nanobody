# Blocker judgment report: case02_pos_03_PVRIG-30_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 4
- BLOCKER_PLAUSIBLE_B: 6

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 14 | 517 | 137 | 0.26499 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_1 | BLOCKER_LIKE_A | 5 | 18 | 833 | 139 | 0.166867 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_5_model_1 | BLOCKER_LIKE_A | 6 | 16 | 668 | 117 | 0.17515 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_2 | BLOCKER_LIKE_A | 10 | 14 | 769 | 137 | 0.178153 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 13 | 376 | 137 | 0.364362 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 3 | 11 | 747 | 144 | 0.192771 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 4 | 12 | 547 | 140 | 0.255941 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_2 | BLOCKER_PLAUSIBLE_B | 7 | 17 | 634 | 98 | 0.154574 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 8 | 9 | 562 | 98 | 0.174377 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_7_model_1 | BLOCKER_PLAUSIBLE_B | 9 | 12 | 681 | 134 | 0.196769 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
