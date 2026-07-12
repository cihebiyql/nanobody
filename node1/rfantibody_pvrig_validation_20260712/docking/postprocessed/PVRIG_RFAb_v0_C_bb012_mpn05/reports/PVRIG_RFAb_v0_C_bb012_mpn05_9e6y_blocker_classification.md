# Blocker judgment report: PVRIG_RFAb_v0_C_bb012_mpn05_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 1
- BLOCKER_PLAUSIBLE_B: 9

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 14 | 742 | 132 | 0.177898 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 2 | 11 | 747 | 146 | 0.195448 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 3 | 13 | 707 | 108 | 0.152758 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_3 | BLOCKER_PLAUSIBLE_B | 4 | 13 | 729 | 138 | 0.1893 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 10 | 749 | 111 | 0.148198 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 6 | 12 | 798 | 139 | 0.174185 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 7 | 11 | 731 | 113 | 0.154583 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 8 | 10 | 830 | 139 | 0.16747 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 9 | 9 | 780 | 127 | 0.162821 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_4 | BLOCKER_PLAUSIBLE_B | 10 | 8 | 681 | 100 | 0.146843 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
