# PVRIG V5-TB OPEN_TRAIN226 执行结果

状态：`COMPLETE_OPEN_TRAIN226_NESTED_DEVELOPMENT_COMPARISON`

## 证据边界

OPEN_TRAIN-only development approximation of independent dual-receptor computational docking geometry; not Docking Gold, binding probability, affinity, competition, experimental blocking, or final submission authority.

## Nested whole-parent OOF

| model | Spearman | parent-centered | macro-parent | MAE | NDCG | Top20 recall | ΔSpearman vs B1 CI |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0_train_mean | -0.1748 | -0.0049 | 0.0000 | 0.03750 | 0.97125 | 0.2174 | -0.8309 [-1.1996,-0.4316] |
| B1_structure_direct | 0.6868 | 0.2818 | 0.2377 | 0.02877 | 0.98678 | 0.4348 | reference |
| B2_dual_receptor_min | 0.6828 | 0.2756 | 0.2354 | 0.02930 | 0.98639 | 0.4348 | -0.0041 [-0.0215,+0.0163] |
| B3_structure_plus_physchem | 0.6739 | 0.2846 | 0.2571 | 0.02921 | 0.98653 | 0.4130 | -0.0108 [-0.0368,+0.0092] |
| B4_direct_dual_convex | 0.6841 | 0.2758 | 0.2424 | 0.02862 | 0.98691 | 0.4348 | -0.0020 [-0.0370,+0.0354] |
| B5_top20_ridge_classifier | 0.6308 | 0.2447 | 0.1300 | 0.03171 | 0.98753 | 0.4348 | -0.0519 [-0.1504,+0.0191] |
| B6_within_parent_pairwise_ridge | 0.2259 | 0.0726 | 0.0819 | 0.03666 | 0.97866 | 0.1739 | -0.4342 [-0.7925,-0.1724] |

## 双受体辅助结果

- R_8X6B Spearman: `0.6578`
- R_9E6Y Spearman: `0.6556`
- R_dual_gap Spearman: `0.0176`
- Top20 classifier raw AP: `0.4596`

## 当前选择

- 最佳候选：`B4_direct_dual_convex`
- 相对 B1 的 development gates：`FAIL_KEEP_B1_STRUCTURE_DIRECT`
- 本轮不宣称 formal PASS；V4-F/test32 与 OPEN_DEVELOPMENT 未访问。

