# Blocker judgment report: PVRIG_RFAb_v0_A_bb005_mpn01_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 6
- BLOCKER_PLAUSIBLE_B: 1

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 20 | 734 | 120 | 0.163488 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 2 | 18 | 754 | 124 | 0.164456 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_3 | BLOCKER_LIKE_A | 3 | 18 | 693 | 122 | 0.176046 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_4 | BLOCKER_LIKE_A | 4 | 16 | 680 | 124 | 0.182353 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_LIKE_A | 5 | 14 | 668 | 135 | 0.202096 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_2 | BLOCKER_LIKE_A | 6 | 16 | 765 | 129 | 0.168627 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_3 | BLOCKER_PLAUSIBLE_B | 7 | 13 | 739 | 127 | 0.171854 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
