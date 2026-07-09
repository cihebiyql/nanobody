# Multi-baseline blocker consensus: case02_pos_07_30H2

## Summary

- BLOCKER_PLAUSIBLE_B: 6
- EVIDENCE_INFERENCE_ONLY_E: 2
- SINGLE_BASELINE_BLOCKER_RECHECK: 1

## Poses

| model | consensus | baselines | best_rank | next_step |
| --- | --- | --- | ---: | --- |
| cluster_1_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 1 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 2 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_2_model_2 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 3 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_2_model_3 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 7 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |
| cluster_2_model_4 | EVIDENCE_INFERENCE_ONLY_E | 8x6b:EVIDENCE_INFERENCE_ONLY_E;9e6y:EVIDENCE_INFERENCE_ONLY_E | 8 | do not prioritize as blocker until missing occlusion or blocking evidence is collected |
| cluster_3_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:EVIDENCE_INFERENCE_ONLY_E | 4 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 5 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_4_model_2 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 6 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_4_model_3 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 9 | keep as follow-up only; collect stronger occlusion or assay evidence |

## Interpretation boundary

- A single 8X6B pass is useful but remains a recheck label until 9E6Y is scored.
- Two-baseline support is stronger than a single-baseline blocker-like call.
- Discordant A/C calls should trigger alignment inspection or redocking, not automatic promotion.
