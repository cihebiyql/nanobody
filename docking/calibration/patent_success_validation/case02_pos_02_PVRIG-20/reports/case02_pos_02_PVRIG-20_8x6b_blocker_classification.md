# Blocker judgment report: case02_pos_02_PVRIG-20_8x6b

Format context: `naked_vhh`
Rules: `/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json`

## Summary

- BLOCKER_LIKE_A: 4
- BLOCKER_PLAUSIBLE_B: 4
- EVIDENCE_INFERENCE_ONLY_E: 2

## Top classified poses

| model | class | rank | hotspot | total_occlusion | cdr3_occlusion | cdr3_fraction | reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cluster_1_model_1 | BLOCKER_LIKE_A | 1 | 19 | 528 | 158 | 0.299242 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_2_model_1 | BLOCKER_LIKE_A | 2 | 15 | 922 | 156 | 0.169197 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_1 | BLOCKER_LIKE_A | 4 | 15 | 548 | 110 | 0.20073 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_4_model_2 | BLOCKER_LIKE_A | 6 | 16 | 640 | 148 | 0.23125 | passes HR-151-calibrated hotspot, total occlusion, CDR3 occlusion, and CDR3 fraction thresholds |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 3 | 15 | 482 | 151 | 0.313278 | partial occlusion and interface signal suggest possible blocker geometry below A thresholds |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 5 | 13 | 664 | 146 | 0.21988 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 7 | 13 | 556 | 179 | 0.321942 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_8_model_1 | BLOCKER_PLAUSIBLE_B | 10 | 8 | 527 | 102 | 0.193548 | substantial PVRL2 occlusion exists but one or more HR-151-calibrated A thresholds are missing |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 8 | 9 | 362 | 59 | 0.162983 | does not meet blocker-like or binder-like calibrated criteria from current available columns |
| cluster_7_model_2 | EVIDENCE_INFERENCE_ONLY_E | 9 | 5 | 297 | 50 | 0.16835 | does not meet blocker-like or binder-like calibrated criteria from current available columns |

## Interpretation boundary

- `BLOCKER_LIKE_A` means structurally blocker-like under the HR-151-calibrated screen, not experimentally proven blocking.
- `BINDER_LIKE_C` catches the known failure mode where hotspot/interface contact does not create PVRL2 occlusion.
- Format/Fc/NK/TIGIT/CD226 effects must be evaluated as separate biology or architecture layers.
- Repeat the overlay against 9E6Y before final candidate ranking.
