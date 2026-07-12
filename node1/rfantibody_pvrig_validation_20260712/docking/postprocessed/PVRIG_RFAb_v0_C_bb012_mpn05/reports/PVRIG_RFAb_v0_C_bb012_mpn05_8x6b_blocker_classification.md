# Blocker judgment report: PVRIG_RFAb_v0_C_bb012_mpn05_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 8
- BLOCKER_PLAUSIBLE_B: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 20 | 724 | 126 | 0.174033 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 2 | 17 | 728 | 135 | 0.18544 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_LIKE_A | 3 | 17 | 710 | 120 | 0.169014 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_3 | BLOCKER_LIKE_A | 4 | 19 | 702 | 131 | 0.18661 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_1 | BLOCKER_LIKE_A | 6 | 18 | 800 | 141 | 0.17625 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_2 | BLOCKER_LIKE_A | 7 | 14 | 709 | 107 | 0.150917 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_2 | BLOCKER_LIKE_A | 8 | 17 | 787 | 140 | 0.177891 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_3 | BLOCKER_LIKE_A | 9 | 14 | 740 | 127 | 0.171622 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 723 | 100 | 0.138313 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_4 | BLOCKER_PLAUSIBLE_B | 10 | 12 | 656 | 106 | 0.161585 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
