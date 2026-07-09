# Multi-baseline blocker consensus: HR151_positive_control

## Summary

- CONSENSUS_BLOCKER_LIKE_A: 1
- DISCORDANT_PLAUSIBLE_VS_BINDER_RECHECK: 1
- SINGLE_BASELINE_BLOCKER_RECHECK: 3

## Poses

| model | consensus | baselines | best_rank | next_step |
| --- | --- | --- | ---: | --- |
| cluster_10_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 10 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_1_model_1 | CONSENSUS_BLOCKER_LIKE_A | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_LIKE_A | 1 | prioritize after leakage and format checks; both reference baselines support blocker-like geometry |
| cluster_2_model_1 | DISCORDANT_PLAUSIBLE_VS_BINDER_RECHECK | 8x6b:BINDER_LIKE_C;9e6y:BLOCKER_PLAUSIBLE_B | 2 | one baseline is plausible but another is binder-like; inspect PVRL2 placement and do not prioritize without redocking or assay evidence |
| cluster_3_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 3 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |
| cluster_8_model_1 | SINGLE_BASELINE_BLOCKER_RECHECK | 8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_PLAUSIBLE_B | 8 | inspect weaker baseline and decide whether this is an alternative epitope or an unstable pose |

## Interpretation boundary

- A single 8X6B pass is useful but remains a recheck label until 9E6Y is scored.
- Two-baseline support is stronger than a single-baseline blocker-like call.
- Discordant A/C calls should trigger alignment inspection or redocking, not automatic promotion.
