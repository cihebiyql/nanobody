# Multi-baseline blocker consensus: case02_pos_08_39H2

## Summary

- BLOCKER_PLAUSIBLE_B: 5
- EVIDENCE_INFERENCE_ONLY_E: 5

## Poses

| model | consensus | baselines | best_rank | next_step |
| --- | --- | --- | ---: | --- |
| cluster_1_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 1 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_2_model_1 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 2 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |
| cluster_3_model_1 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 3 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |
| cluster_3_model_2 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 10 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 4 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_4_model_2 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 6 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 7 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_5_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:BLOCKER_PLAUSIBLE_B | 5 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_6_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:EVIDENCE_INFERENCE_ONLY_E | 8 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_7_model_1 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 9 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |

## Interpretation boundary

- A single 8X6B pass is useful but remains a recheck label until 9E6Y is scored.
- Two-baseline support is stronger than a single-baseline blocker-like call.
- Discordant A/C calls should trigger alignment inspection or redocking, not automatic promotion.
