# Blocker judgment report: PVRIG_RFAb_v0_D_bb028_mpn04_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 7

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 10 | 689 | 146 | 0.211901 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 2 | 10 | 701 | 137 | 0.195435 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_3 | BLOCKER_PLAUSIBLE_B | 3 | 9 | 684 | 146 | 0.21345 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 9 | 528 | 60 | 0.113636 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_4 | BLOCKER_PLAUSIBLE_B | 5 | 7 | 665 | 136 | 0.204511 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 6 | 12 | 825 | 150 | 0.181818 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 9 | 757 | 134 | 0.177015 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
