# Blocker judgment report: case02_pos_09_39H4_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 8
- EVIDENCE_INFERENCE_ONLY_E: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 13 | 817 | 142 | 0.173807 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 12 | 691 | 120 | 0.173661 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 3 | 10 | 735 | 142 | 0.193197 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_3 | BLOCKER_PLAUSIBLE_B | 4 | 9 | 676 | 148 | 0.218935 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_4 | BLOCKER_PLAUSIBLE_B | 5 | 10 | 733 | 145 | 0.197817 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_5 | BLOCKER_PLAUSIBLE_B | 6 | 9 | 561 | 127 | 0.226381 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_6 | BLOCKER_PLAUSIBLE_B | 7 | 10 | 675 | 150 | 0.222222 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_7 | BLOCKER_PLAUSIBLE_B | 8 | 9 | 682 | 153 | 0.22434 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 9 | 6 | 439 | 126 | 0.287016 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_4_model_1 | EVIDENCE_INFERENCE_ONLY_E | 10 | 4 | 318 | 117 | 0.367925 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
