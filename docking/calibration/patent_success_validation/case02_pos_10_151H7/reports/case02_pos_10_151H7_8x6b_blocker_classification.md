# Blocker judgment report: case02_pos_10_151H7_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 5
- BLOCKER_PLAUSIBLE_B: 2
- EVIDENCE_INFERENCE_ONLY_E: 3

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_2_model_1 | BLOCKER_LIKE_A | 2 | 18 | 746 | 176 | 0.235925 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_LIKE_A | 3 | 18 | 749 | 175 | 0.233645 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_2 | BLOCKER_LIKE_A | 4 | 18 | 713 | 173 | 0.242637 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_2 | BLOCKER_LIKE_A | 7 | 17 | 759 | 177 | 0.233202 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_6_model_1 | BLOCKER_LIKE_A | 10 | 15 | 840 | 200 | 0.238095 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 1 | 11 | 582 | 108 | 0.185567 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 9 | 636 | 170 | 0.267296 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_1_model_2 | EVIDENCE_INFERENCE_ONLY_E | 6 | 9 | 387 | 31 | 0.0801034 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_1_model_3 | EVIDENCE_INFERENCE_ONLY_E | 8 | 9 | 457 | 51 | 0.111597 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_5_model_1 | EVIDENCE_INFERENCE_ONLY_E | 9 | 9 | 428 | 157 | 0.366822 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
