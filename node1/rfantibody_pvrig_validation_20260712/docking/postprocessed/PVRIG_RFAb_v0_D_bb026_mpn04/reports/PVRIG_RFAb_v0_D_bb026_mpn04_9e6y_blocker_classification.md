# Blocker judgment report: PVRIG_RFAb_v0_D_bb026_mpn04_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 10

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 12 | 646 | 124 | 0.19195 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 2 | 12 | 670 | 120 | 0.179104 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_3 | BLOCKER_PLAUSIBLE_B | 3 | 11 | 662 | 124 | 0.187311 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 11 | 756 | 93 | 0.123016 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_4 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 734 | 118 | 0.160763 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 6 | 9 | 789 | 114 | 0.144487 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 11 | 889 | 119 | 0.133858 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 8 | 10 | 805 | 108 | 0.134161 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_3 | BLOCKER_PLAUSIBLE_B | 9 | 9 | 761 | 97 | 0.127464 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 9 | 669 | 89 | 0.133034 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
