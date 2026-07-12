# Blocker judgment report: PVRIG_RFAb_v0_A_bb016_mpn05_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 3
- BLOCKER_PLAUSIBLE_B: 5
- EVIDENCE_INFERENCE_ONLY_E: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_3_model_1 | BLOCKER_LIKE_A | 3 | 15 | 842 | 137 | 0.162708 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_1 | BLOCKER_LIKE_A | 6 | 15 | 688 | 117 | 0.170058 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_2 | BLOCKER_LIKE_A | 8 | 15 | 858 | 135 | 0.157343 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 18 | 660 | 92 | 0.139394 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | BLOCKER_PLAUSIBLE_B | 5 | 17 | 634 | 95 | 0.149842 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 13 | 645 | 102 | 0.15814 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 9 | 11 | 901 | 140 | 0.155383 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_7_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 8 | 819 | 147 | 0.179487 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | EVIDENCE_INFERENCE_ONLY_E | 2 | 13 | 493 | 35 | 0.0709939 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_2_model_2 | EVIDENCE_INFERENCE_ONLY_E | 4 | 13 | 485 | 41 | 0.0845361 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
