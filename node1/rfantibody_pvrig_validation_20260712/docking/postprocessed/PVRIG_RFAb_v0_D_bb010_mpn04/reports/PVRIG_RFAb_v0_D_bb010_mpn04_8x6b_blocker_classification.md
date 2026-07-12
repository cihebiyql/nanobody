# Blocker judgment report: PVRIG_RFAb_v0_D_bb010_mpn04_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 6
- BLOCKER_PLAUSIBLE_B: 3
- EVIDENCE_INFERENCE_ONLY_E: 1

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 17 | 674 | 126 | 0.186944 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 3 | 18 | 712 | 132 | 0.185393 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_LIKE_A | 4 | 15 | 719 | 119 | 0.165508 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_5_model_1 | BLOCKER_LIKE_A | 6 | 14 | 717 | 126 | 0.175732 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_7_model_1 | BLOCKER_LIKE_A | 8 | 17 | 658 | 113 | 0.171733 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_8_model_1 | BLOCKER_LIKE_A | 9 | 15 | 639 | 100 | 0.156495 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 16 | 484 | 59 | 0.121901 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 16 | 615 | 92 | 0.149593 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_9_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 12 | 636 | 109 | 0.171384 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | EVIDENCE_INFERENCE_ONLY_E | 5 | 9 | 446 | 23 | 0.0515695 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
