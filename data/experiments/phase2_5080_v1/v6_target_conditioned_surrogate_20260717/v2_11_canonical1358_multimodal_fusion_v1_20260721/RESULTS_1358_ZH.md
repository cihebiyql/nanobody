# V2.11 canonical1358 多模态开放开发集结果

日期：2026-07-21

## 证据边界

- 目标：逼近独立 8X6B/9E6Y Docking 的连续计算几何，主读数为 `R_dual_min`。
- 本结果不是结合概率、Kd、实验阻断概率或 Docking Gold。
- 仅使用开放 development：76 条、6 个未见 parent；冻结/密封测试访问次数均为 0。
- 融合权重只由 1,282 条 train 的 inner whole-parent OOF 拟合，development 不参与拟合或选择。

## 模态

- `S0`：ESM2-650M 序列 embedding + 理化特征。
- `M2`：VHH 单体结构的 126 维 label-free 几何特征。
- `C2`：VHH 单体与固定 8X6B/9E6Y PVRIG 表面的 300 个低分辨率刚体扫描姿势汇总，36 维，训练时在 fold 内压缩为 PCA8。
- `S0+M2+C2`：非负凸融合；权重由 train inner OOF 冻结。
- `GBDT`：浅层 challenger，不作为默认晋级模型。

## 开放 development76 结果

`EF@10` = true Top10% 在预测 Top10% 中的富集倍数；`Recall@20` = true Top20% 在预测 Top20% 中的召回率。

| 模型 | Rdual Spearman | MAE | EF@10 | Recall@20 | within-parent Top20 macro recall |
|---|---:|---:|---:|---:|---:|
| matched S0 | 0.46247 | 0.032924 | 2.375 | 0.3750 | 0.2778 |
| M2 structure | **0.67177** | **0.028375** | 2.375 | 0.5000 | 0.3889 |
| C2 coarse-pose | 0.59707 | 0.031506 | **4.750** | **0.6875** | **0.4444** |
| M2+C2 | 0.62682 | 0.030551 | **4.750** | **0.6875** | 0.3889 |
| S0+M2+C2 | 0.63445 | 0.029765 | 3.5625 | **0.6875** | **0.4444** |
| shallow GBDT | 0.51956 | 0.030817 | 1.1875 | 0.3750 | 0.2778 |
| full9849 S0 frozen ensemble | 0.64930 | 0.028588 | **4.750** | 0.5625 | 0.2778 |

## 解释

1. `M2` 是当前连续回归最强分支，说明单体结构确实提供了序列之外的信息。
2. `C2` 在早期富集和同 parent 精排上最强，说明廉价粗姿势扫描补充了模型最缺少的 approach-angle 信息。
3. `S0+M2+C2` 提高了 Top20% 召回和同 parent 精排，但没有在所有指标上支配 `M2` 或全量 `S0`。
4. 全量训练的 `S0` 明显强于仅在 matched1282 上训练的 `S0`，因此正式结论必须在完整 9,849 train / 795 development 上重新比较各模态。
5. 浅层 GBDT 在本次严格 OOF 设计下没有增益，不晋级。

## 下一步

1. 已完成 canonical10644 的 10,644/10,644 单体结构闭合和 M2-126D 提取。
2. 生成 canonical10644 的 label-free C2 粗姿势特征。
3. 在正式开放划分 9,849 train / 795 development 上训练并比较 `S0`、`M2`、`C2`、正则化融合和候选组合策略。
4. 补齐 10,644 条 label-free VHH residue graph，运行纯 target-attention challenger；在得到增量证据前不启用新的 contact 监督。

## 可复现证据

- 本地结果目录：`results/canonical1358_multimodal_v1/`
- `METRICS.json` SHA256：`b4b66ea67b8dfc7f64390b66e0cc65cf197fe52ab308178e0c31375c032de6c2`
- `SHA256SUMS` 已重新校验全部通过。
