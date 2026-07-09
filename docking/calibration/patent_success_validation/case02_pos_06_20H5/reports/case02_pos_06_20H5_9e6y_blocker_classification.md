# Blocker judgment report: case02_pos_06_20H5_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 3
- BLOCKER_PLAUSIBLE_B: 6
- EVIDENCE_INFERENCE_ONLY_E: 1

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_2 | BLOCKER_LIKE_A | 2 | 14 | 620 | 130 | 0.209677 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_4 | BLOCKER_LIKE_A | 4 | 14 | 599 | 125 | 0.208681 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_7 | BLOCKER_LIKE_A | 7 | 14 | 616 | 130 | 0.211039 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 12 | 610 | 140 | 0.229508 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_3 | BLOCKER_PLAUSIBLE_B | 3 | 13 | 601 | 136 | 0.22629 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_5 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 625 | 140 | 0.224 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_6 | BLOCKER_PLAUSIBLE_B | 6 | 13 | 625 | 135 | 0.216 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 8 | 12 | 460 | 153 | 0.332609 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 9 | 11 | 708 | 189 | 0.266949 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | EVIDENCE_INFERENCE_ONLY_E | 10 | 9 | 426 | 113 | 0.265258 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
