# V2.11 Full10644 Clean Target-Attention 训练结果

## 结论

四个冻结种子均完成 8 个固定 epoch，795 条 whole-parent open-development 预测完整闭合。B_CLEAN_TARGET_ATTENTION 四种子均值 ensemble 达到：

- `R_dual_min Spearman = 0.653587`
- `R_dual_min MAE = 0.032283`
- `EF@Top5% (true top10%) = 3.2297`
- `EF@Top10% (true top10%) = 2.7328`
- `Recall true top20%@budget20% = 0.4277`
- `within-parent macro recall@20% = 0.3917`

它取得当前最低 MAE 和最高 within-parent macro recall，但整体 Spearman 与早期富集并未全面超过既有模型。因此它适合作为互补的靶标感知结构分支，不应仅凭本次 open-development 结果替换 S0/M2/C2。

## 同一 development795 对比

| 模型 | Rdual Spearman | Rdual MAE | EF@5 | EF@10 | Recall20@20 | WP Recall20 |
|---|---:|---:|---:|---:|---:|---:|
| B_CLEAN_TARGET_ATTENTION_4SEED_ENSEMBLE | 0.6536 | 0.03228 | 3.230 | 2.733 | 0.428 | 0.392 |
| S0_FULL9849_FROZEN_ENSEMBLE_BASE_ONLY | 0.6397 | 0.03343 | 3.727 | 2.609 | 0.415 | 0.301 |
| M2_STRUCTURE_ALPHA10 | 0.6597 | 0.03315 | 3.230 | 2.981 | 0.453 | 0.320 |
| C2_COARSE_POSE_PCA8 | 0.6085 | 0.03787 | 2.981 | 1.863 | 0.390 | 0.355 |
| M2_C2_CONVEX | 0.6629 | 0.03372 | 2.733 | 2.733 | 0.491 | 0.317 |
| S0_M2_C2_CONVEX | 0.6647 | 0.03337 | 3.230 | 2.733 | 0.472 | 0.346 |

## 稳定性

- 四种子 Rdual 排名 Spearman：`0.9667–0.9830`。
- 候选预测标准差均值：`0.008937`。
- Top5% 种子间交集为 25–29/40，说明极早期候选仍存在种子不确定性，生产筛选应使用 ensemble 和 exploration quota。

## V1.1 后处理恢复

原 V1 evaluator 因 float32 真值序列化最大误差 `2.9798e-8` 超过冻结 `2e-8` 而 fail-closed。V1.1 在执行前冻结为 `4e-8`，9/9 本地测试与 2/2 Node1 聚焦测试通过；生产中 receptor 最大误差仍为 `2.9798e-8`，target/prediction exact-min 误差均为 0。没有重训、改预测、选种子或访问 frozen test。

## 下一步

1. 保留 S0 负责极早期 Top5 富集；
2. 保留 M2/M2+C2 负责总体排序和 Top20 recall；
3. 将 B_CLEAN_TARGET_ATTENTION 作为靶标感知与 within-parent 互补证据；
4. 下一版只在 train parents 内生成 clean-attention inner-OOF 特征，训练强正则线性 stack；
5. 在 10 万级筛选中采用 ensemble 排名 + 模型分歧 + parent/patch 多样性配额，而不是单模型机械取前列。

## 证据边界

这些结果仅表示对独立双受体计算 Docking 几何的 open-development 逼近，不是结合概率、Kd、实验阻断概率、Docking Gold 或正式 sealed-test 结果。
