# Blocker judgment report: PVRIG_RFAb_v0_D_bb012_mpn04_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 8

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 10 | 692 | 58 | 0.083815 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 11 | 598 | 142 | 0.237458 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 3 | 11 | 887 | 140 | 0.157835 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 4 | 10 | 503 | 145 | 0.28827 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 768 | 140 | 0.182292 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 10 | 521 | 119 | 0.228407 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 7 | 10 | 767 | 144 | 0.187744 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_4 | BLOCKER_PLAUSIBLE_B | 8 | 10 | 702 | 136 | 0.193732 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
