# Blocker judgment report: PVRIG_RFAb_v0_D_bb019_mpn03_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 6
- BLOCKER_PLAUSIBLE_B: 4

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 18 | 735 | 143 | 0.194558 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 2 | 18 | 695 | 127 | 0.182734 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_LIKE_A | 3 | 14 | 704 | 139 | 0.197443 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_LIKE_A | 4 | 17 | 738 | 139 | 0.188347 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_1 | BLOCKER_LIKE_A | 5 | 19 | 642 | 105 | 0.163551 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_7_model_1 | BLOCKER_LIKE_A | 8 | 14 | 702 | 130 | 0.185185 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 6 | 13 | 499 | 144 | 0.288577 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 10 | 631 | 142 | 0.22504 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_8_model_1 | BLOCKER_PLAUSIBLE_B | 9 | 13 | 793 | 138 | 0.174023 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_9_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 11 | 624 | 100 | 0.160256 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
