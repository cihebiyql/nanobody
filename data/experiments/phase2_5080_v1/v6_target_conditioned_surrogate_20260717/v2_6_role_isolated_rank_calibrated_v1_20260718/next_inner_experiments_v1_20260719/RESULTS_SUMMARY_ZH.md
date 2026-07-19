# V2.6 open-inner 下一批实验结果

## 执行闭环

- `B_SCALAR_ATTENTION_ONLY` 补齐 seed 97/193，与原 seed43 组成三种子 ensemble；两任务均为 544 optimizer steps，全部 firewall 为 0。
- Integration V1.4 没有覆盖 V1.3；31 个 CPU/继承回归测试通过。
- 第一次 CUDA smoke V1.4 因新包缺失 delta-noise 路径而在 optimizer step 之前 fail-closed，失败证据保留。
- V1.4.1 只修正 immutable delta-noise artifact 的路径闭合；marginal-only 与 pair-only 两个 smoke 均通过 68 steps。
- V1.4.2 完成 2 个 ablation × 3 seeds × 8 epochs，共 6 个任务；每个任务 544 steps，全部 firewall 为 0。

## Early enrichment

inner score set 为 184 条、6 个未见 parent clusters。采用：

- true positives：真实 Docking `R_dual_min` Top10% 或 Top20%；
- 预测预算：Top5%、Top10%、Top20%；
- 主计数为 `ceil(N × fraction)`，同时记录 floor sensitivity；
- 同分按 `score desc, candidate_id asc`，并记录 cutoff tie 的 best/worst/expected hits。

三种子 B、combined F0、marginal-only 和 pair-only 在所有全局 Top5/10/20 hit、Recall 和 EF 上完全相同：

| 真值集合 | 预测预算 | hits | Recall | EF |
|---|---:|---:|---:|---:|
| true Top10% | Top5% | 7/19 | 0.368 | 6.779× |
| true Top10% | Top10% | 12/19 | 0.632 | 6.116× |
| true Top10% | Top20% | 14/19 | 0.737 | 3.664× |
| true Top20% | Top5% | 8/37 | 0.216 | 3.978× |
| true Top20% | Top10% | 15/37 | 0.405 | 3.926× |
| true Top20% | Top20% | 17/37 | 0.459 | 2.285× |

历史上 F0 Top5 出现 `6` 与本次 `7` 的差异来自预算取整：184×5%=9.2，floor 取 9 条时命中 6 条，ceil 取 10 条时命中 7 条；不是 cutoff tie 改变造成的。

## 连续排序诊断

| Variant | Rdual Spearman | MAE | RMSE | within-parent Top20 EF |
|---|---:|---:|---:|---:|
| B 三种子 | 0.29837 | 0.03140 | 0.03785 | 1.582 |
| F0 combined | 0.31726 | 0.03145 | 0.03784 | 1.582 |
| F0 marginal-only | **0.32455** | 0.03113 | 0.03743 | 1.582 |
| F0 pair-only | 0.31510 | **0.03036** | **0.03687** | **1.341** |

## 结论

1. B/F0 的全局 early enrichment 已明显高于随机，但 contact supervision 在这个 split 上没有增加 Top-K 命中。
2. marginal-only 对中段/全局连续排序的增量最好，但仍只是单一 open inner split 的小幅结果。
3. pair-only 虽降低 MAE/RMSE，却使 within-parent early enrichment 变差，不适合作为下一轮主 challenger。
4. 目前最值得扩展的是 `B 三种子` 与 `marginal-only 三种子` 到其余 open inner folds；combined 作为参考，pair-only 暂停扩张。
5. 在更多 whole-parent folds 重现前，不启动 formal nested 或 sealed V4-F/test32 评价，也不宣称实验阻断能力。

## 证据边界

所有结果仅表示：

`VHH sequence + label-free monomer/target features → independent dual-receptor computational Docking geometry` 的 open-development 近似。

不表示 binding、Kd、实验 blocking、Docking Gold 或比赛提交真值。
