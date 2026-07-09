# Blocker judgment report: case02_pos_09_39H4_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 2
- BLOCKER_PLAUSIBLE_B: 6
- EVIDENCE_INFERENCE_ONLY_E: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 17 | 779 | 139 | 0.178434 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_2 | BLOCKER_LIKE_A | 3 | 14 | 725 | 142 | 0.195862 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 2 | 11 | 663 | 117 | 0.176471 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_3 | BLOCKER_PLAUSIBLE_B | 4 | 13 | 657 | 140 | 0.21309 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_4 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 718 | 134 | 0.18663 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_5 | BLOCKER_PLAUSIBLE_B | 6 | 8 | 550 | 117 | 0.212727 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_6 | BLOCKER_PLAUSIBLE_B | 7 | 11 | 639 | 142 | 0.222222 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_2_model_7 | BLOCKER_PLAUSIBLE_B | 8 | 13 | 669 | 148 | 0.221226 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 9 | 8 | 421 | 118 | 0.280285 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_4_model_1 | EVIDENCE_INFERENCE_ONLY_E | 10 | 5 | 325 | 117 | 0.36 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
