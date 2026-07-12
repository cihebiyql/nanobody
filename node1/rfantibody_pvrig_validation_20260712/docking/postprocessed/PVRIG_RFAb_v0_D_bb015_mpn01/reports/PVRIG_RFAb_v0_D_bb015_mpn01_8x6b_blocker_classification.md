# Blocker judgment report: PVRIG_RFAb_v0_D_bb015_mpn01_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 5
- BLOCKER_PLAUSIBLE_B: 5

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_2_model_1 | BLOCKER_LIKE_A | 2 | 17 | 694 | 107 | 0.154179 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_LIKE_A | 3 | 16 | 697 | 139 | 0.199426 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_2 | BLOCKER_LIKE_A | 6 | 14 | 624 | 117 | 0.1875 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_5_model_2 | BLOCKER_LIKE_A | 8 | 16 | 659 | 103 | 0.156297 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_5_model_3 | BLOCKER_LIKE_A | 9 | 16 | 677 | 105 | 0.155096 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 15 | 551 | 83 | 0.150635 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 18 | 541 | 74 | 0.136784 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 721 | 142 | 0.196949 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 16 | 645 | 95 | 0.147287 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 13 | 721 | 125 | 0.17337 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
