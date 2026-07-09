# Blocker judgment report: case02_pos_08_39H2_9e6y

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_PLAUSIBLE_B: 4
- EVIDENCE_INFERENCE_ONLY_E: 6

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 10 | 831 | 97 | 0.116727 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 4 | 11 | 556 | 68 | 0.122302 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 10 | 467 | 55 | 0.117773 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 7 | 9 | 539 | 85 | 0.157699 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_1 | EVIDENCE_INFERENCE_ONLY_E | 2 | 5 | 232 | 61 | 0.262931 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 3 | 7 | 389 | 136 | 0.349614 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_4_model_2 | EVIDENCE_INFERENCE_ONLY_E | 6 | 9 | 411 | 60 | 0.145985 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_6_model_1 | EVIDENCE_INFERENCE_ONLY_E | 8 | 7 | 451 | 129 | 0.286031 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 9 | 8 | 338 | 130 | 0.384615 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_3_model_2 | EVIDENCE_INFERENCE_ONLY_E | 10 | 7 | 362 | 132 | 0.364641 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
