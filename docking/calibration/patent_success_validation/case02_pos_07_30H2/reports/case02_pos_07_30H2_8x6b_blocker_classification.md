# Blocker judgment report: case02_pos_07_30H2_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 1
- BLOCKER_PLAUSIBLE_B: 6
- EVIDENCE_INFERENCE_ONLY_E: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 15 | 612 | 103 | 0.168301 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 11 | 503 | 137 | 0.272366 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 3 | 12 | 484 | 124 | 0.256198 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 8 | 519 | 51 | 0.0982659 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 10 | 634 | 127 | 0.200315 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 10 | 661 | 138 | 0.208775 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 9 | 8 | 557 | 120 | 0.21544 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_3 | EVIDENCE_INFERENCE_ONLY_E | 7 | 9 | 439 | 130 | 0.296128 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_2_model_4 | EVIDENCE_INFERENCE_ONLY_E | 8 | 6 | 264 | 87 | 0.329545 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
