# Blocker judgment report: case02_pos_07_30H2_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 6
- EVIDENCE_INFERENCE_ONLY_E: 3

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 9 | 611 | 87 | 0.14239 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 9 | 514 | 129 | 0.250973 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 3 | 8 | 503 | 126 | 0.250497 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 9 | 655 | 132 | 0.201527 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 6 | 9 | 689 | 137 | 0.198839 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 9 | 6 | 590 | 123 | 0.208475 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 4 | 7 | 517 | 49 | 0.0947776 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_2_model_3 | EVIDENCE_INFERENCE_ONLY_E | 7 | 7 | 465 | 130 | 0.27957 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_2_model_4 | EVIDENCE_INFERENCE_ONLY_E | 8 | 5 | 272 | 84 | 0.308824 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
