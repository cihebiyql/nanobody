# Blocker judgment report: case02_pos_05_PVRIG-39_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 3
- BLOCKER_PLAUSIBLE_B: 7

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_6 | BLOCKER_LIKE_A | 7 | 15 | 725 | 136 | 0.187586 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_8 | BLOCKER_LIKE_A | 9 | 14 | 682 | 125 | 0.183284 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_9 | BLOCKER_LIKE_A | 10 | 14 | 690 | 119 | 0.172464 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 13 | 696 | 134 | 0.192529 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 13 | 794 | 133 | 0.167506 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 3 | 13 | 768 | 129 | 0.167969 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_3 | BLOCKER_PLAUSIBLE_B | 4 | 12 | 700 | 138 | 0.197143 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_4 | BLOCKER_PLAUSIBLE_B | 5 | 11 | 681 | 133 | 0.195301 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_5 | BLOCKER_PLAUSIBLE_B | 6 | 12 | 680 | 127 | 0.186765 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_7 | BLOCKER_PLAUSIBLE_B | 8 | 11 | 671 | 137 | 0.204173 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
