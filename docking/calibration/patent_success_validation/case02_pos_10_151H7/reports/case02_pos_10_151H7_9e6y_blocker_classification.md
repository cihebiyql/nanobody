# Blocker judgment report: case02_pos_10_151H7_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 8
- EVIDENCE_INFERENCE_ONLY_E: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 11 | 595 | 120 | 0.201681 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 12 | 774 | 185 | 0.239018 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 3 | 11 | 759 | 173 | 0.227931 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_2 | BLOCKER_PLAUSIBLE_B | 4 | 10 | 737 | 170 | 0.230665 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 9 | 678 | 172 | 0.253687 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 7 | 11 | 775 | 189 | 0.243871 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_3 | BLOCKER_PLAUSIBLE_B | 8 | 10 | 456 | 63 | 0.138158 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 10 | 860 | 202 | 0.234884 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | EVIDENCE_INFERENCE_ONLY_E | 6 | 9 | 384 | 36 | 0.09375 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_5_model_1 | EVIDENCE_INFERENCE_ONLY_E | 9 | 8 | 448 | 152 | 0.339286 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
