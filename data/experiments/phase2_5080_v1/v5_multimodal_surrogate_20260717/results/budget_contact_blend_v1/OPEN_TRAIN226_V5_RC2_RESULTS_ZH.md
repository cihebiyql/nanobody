# V5-RC.2 Budget-aware Contact Rank-Blend 结果

状态：`COMPLETE_OPEN_TRAIN226_BUDGET_CONTACT_BLEND_COMPARISON`

OPEN_TRAIN-only computational docking-geometry acquisition research; not binding, affinity, competition, experimental blocking, Docking Gold, or final submission authority.

| 模型 | Spearman | Parent-centered | Macro-parent | MAE | Top20 recall |
|---|---:|---:|---:|---:|---:|
| RC2_C0_structure_linear | 0.6868 | 0.2818 | 0.2377 | 0.02877 | 0.4348 |
| RC2_C1_structure_nonlinear | 0.6643 | 0.2655 | 0.2312 | 0.02808 | 0.3696 |
| RC2_C2_contact_bottleneck | 0.6668 | 0.2782 | 0.1998 | 0.02913 | 0.5217 |
| RC2_budget_rank_blend | 0.6681 | 0.2571 | 0.2331 | 0.02772 | 0.3913 |

Outer-fold gamma：`[0.0, 0.3, 0.5, 0.1, 0.5]`

决策：`FAIL_CONTACT_ONLY_EXPLORATION_NOT_EXPLOITATION`

