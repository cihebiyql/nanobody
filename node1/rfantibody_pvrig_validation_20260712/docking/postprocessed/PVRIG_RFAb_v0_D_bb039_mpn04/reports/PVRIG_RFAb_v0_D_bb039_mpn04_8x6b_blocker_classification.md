# Blocker judgment report: PVRIG_RFAb_v0_D_bb039_mpn04_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 3
- BLOCKER_PLAUSIBLE_B: 7

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_2_model_1 | BLOCKER_LIKE_A | 2 | 19 | 724 | 115 | 0.15884 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_2 | BLOCKER_LIKE_A | 3 | 18 | 691 | 111 | 0.160637 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_3 | BLOCKER_LIKE_A | 9 | 15 | 638 | 115 | 0.180251 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 19 | 790 | 114 | 0.144304 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 15 | 811 | 110 | 0.135635 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 17 | 819 | 107 | 0.130647 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 18 | 814 | 108 | 0.132678 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 14 | 767 | 108 | 0.140808 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 8 | 14 | 809 | 103 | 0.127318 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 13 | 751 | 101 | 0.134487 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
