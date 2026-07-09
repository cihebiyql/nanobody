# Blocker judgment report: case02_pos_01_PVRIG-151_HR151_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 5
- BLOCKER_PLAUSIBLE_B: 5

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 15 | 875 | 197 | 0.225143 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_LIKE_A | 2 | 20 | 779 | 195 | 0.250321 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_2 | BLOCKER_LIKE_A | 5 | 19 | 811 | 211 | 0.260173 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_3 | BLOCKER_LIKE_A | 7 | 19 | 767 | 199 | 0.259452 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_5_model_1 | BLOCKER_LIKE_A | 8 | 14 | 848 | 198 | 0.233491 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 3 | 9 | 525 | 101 | 0.192381 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 4 | 11 | 478 | 74 | 0.154812 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 6 | 10 | 436 | 209 | 0.479358 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_3_model_3 | BLOCKER_PLAUSIBLE_B | 9 | 9 | 553 | 114 | 0.206148 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 10 | 9 | 593 | 202 | 0.340641 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
