# Multi-baseline blocker consensus: PVRIG_RFAb_v0_B_bb015_mpn01

## Summary

- BLOCKER_PLAUSIBLE_B: 2
- CONSENSUS_BLOCKER_LIKE_A: 1
- SINGLE_BASELINE_BLOCKER_RECHECK: 7

## Poses

| model | consensus | baselines | best_rank | next_step |
| --- | --- | --- | ---: | --- |
| cluster_1_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 1 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_1_model_2 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 3 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_1_model_3 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 6 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_1_model_4 | CONSENSUS_BLOCKER_LIKE_A | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_LIKE_A | 7 | prioritize after leakage and format checks; both reference baselines support blocker-like geometry |
| cluster_2_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 2 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_3_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 4 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_4_model_1 | BLOCKER_PLAUSIBLE_B | 8x6b:BLOCKER_PLAUSIBLE_B;9e6y:BLOCKER_PLAUSIBLE_B | 5 | keep as follow-up only; collect stronger occlusion or assay evidence |
| cluster_5_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 8 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_5_model_2 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 9 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_5_model_3 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 10 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |

## Interpretation boundary

- A single 8X6B pass is useful but remains a recheck label until 9E6Y is scored.
- Two-baseline support is stronger than a single-baseline blocker-like call.
- Discordant A/C calls should trigger alignment inspection or redocking, not automatic promotion.
