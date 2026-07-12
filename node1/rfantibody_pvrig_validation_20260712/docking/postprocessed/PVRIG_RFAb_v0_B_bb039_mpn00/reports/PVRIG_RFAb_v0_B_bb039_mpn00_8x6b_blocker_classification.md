# Blocker judgment report: PVRIG_RFAb_v0_B_bb039_mpn00_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 4
- BLOCKER_PLAUSIBLE_B: 4
- EVIDENCE_INFERENCE_ONLY_E: 1

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 16 | 649 | 121 | 0.186441 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 3 | 18 | 651 | 118 | 0.18126 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_LIKE_A | 4 | 14 | 517 | 114 | 0.220503 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_3 | BLOCKER_LIKE_A | 5 | 16 | 629 | 124 | 0.197138 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 6 | 13 | 719 | 113 | 0.157163 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 11 | 332 | 105 | 0.316265 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 8 | 14 | 854 | 116 | 0.135831 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 9 | 11 | 807 | 121 | 0.149938 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | EVIDENCE_INFERENCE_ONLY_E | 2 | 12 | 354 | 38 | 0.107345 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
