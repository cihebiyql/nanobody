# Blocker judgment report: case02_pos_06_20H5_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 8
- BLOCKER_PLAUSIBLE_B: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 15 | 592 | 136 | 0.22973 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_2 | BLOCKER_LIKE_A | 2 | 19 | 595 | 122 | 0.205042 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_3 | BLOCKER_LIKE_A | 3 | 16 | 583 | 133 | 0.22813 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_4 | BLOCKER_LIKE_A | 4 | 17 | 587 | 124 | 0.211244 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_5 | BLOCKER_LIKE_A | 5 | 17 | 617 | 136 | 0.220421 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_6 | BLOCKER_LIKE_A | 6 | 17 | 603 | 134 | 0.222222 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_1_model_7 | BLOCKER_LIKE_A | 7 | 17 | 598 | 127 | 0.212375 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_LIKE_A | 9 | 15 | 676 | 179 | 0.264793 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 8 | 11 | 441 | 168 | 0.380952 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 11 | 436 | 116 | 0.266055 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
