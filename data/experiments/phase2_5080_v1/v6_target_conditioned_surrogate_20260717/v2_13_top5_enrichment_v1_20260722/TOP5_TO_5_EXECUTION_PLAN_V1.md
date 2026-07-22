# V2.13 Top5 富集向 EF=5 推进计划

## 目标

主指标固定为：

```text
EF@5%，真实正例 = 独立双受体 Docking R_dual_min 的 Top 10%
```

`EF@5 = 5` 等价于在筛出的前 5% 中约有 50% 属于 Docking Top 10%，约召回全部 Docking Top 10% 的 25%。

模型仍然只逼近计算 Docking 几何，不表示实验结合、Kd 或实验阻断概率。

## 数据边界

1. 所有模型选择只使用 9,849 条 teacher 的 whole-parent OOF。
2. 54 个 parent cluster 以固定五折整体隔离。
3. 已开放的 795 条 development 只允许在模型、权重和阈值冻结后作描述性评价。
4. frozen test 不参与本轮任何训练、调参或选择。
5. `R_dual_min` 在推理时始终由 `min(R8,R9)` 导出，不独立预测。

## Phase A：Top5 定向神经损失

并行训练三个固定变体：

- L1：Top 区域加权 Huber；
- L2：Top/非 Top 平衡 batch + 0.25 PairLogit；
- L3：Top/非 Top 平衡 batch + 0.50 PairLogit。

按预注册的 EF5、EF10、Spearman、MAE 和 fold 稳定性门槛选型，未通过则不事后放宽。

## Phase B：三种子集成

入选变体运行 seed 43、917、1931：

```text
mean_R8 = mean(seed_R8)
mean_R9 = mean(seed_R9)
Rdual = min(mean_R8, mean_R9)
```

任何坏 seed 都不得在看结果后剔除。seed 方差作为置信度证据，不作为 teacher 标签。

## Phase C0：结果盲多模态架构筛选

在旧 B 模态上先比较固定候选：

1. Equal-rank：S0/M2/C2/B 等权秩融合；
2. Robust rank grid：内层 whole-parent CV 选择受限权重；
3. Positive Ridge：分别拟合 R8/R9，严格导出 Rdual；
4. Logistic Top10：强正则二分类头，直接优化早期命中；
5. Shallow HGB：深度 2、大叶节点、强 L2、关闭 early stopping。

外层五折提供 meta OOF，内层 whole-parent CV 只负责超参数选择。

## Phase C1：三种子 B3 无调参替换

Phase B 完成后，不改变候选方法和超参数网格，只把 B 替换为 B3，并增加：

- seed Rdual 标准差；
- seed rank 一致性；
- B3 与 seed43 的差异；
- R8/R9 构象差距；
- 四模态均值、方差和最弱证据。

最终 primary 保留稳健秩融合；线性/Logistic/HGB 仅在 whole-parent OOF 明确增益且 fold 稳定时晋级。

## Phase D：大库运行策略

对 10 万序列分层计算：

```text
全库 S0
→ 约 1–2 万条补 M2/C2/B3
→ 80% 高融合分 + 10% 高不确定性 + 10% 多样性探索
→ 后续 Docking
```

每条输出：融合排名、R8/R9/Rdual、seed 标准差、多模态分歧和置信层级。

## 成功判据

1. whole-parent OOF `EF@5 >= 5.0`；
2. 不以单 fold 极端结果驱动，median/worst-fold 明显优于当前 baseline；
3. EF10、Spearman 和 MAE 不发生预注册门槛外退化；
4. 冻结后在新增 Docking batch 或 untouched cohort 上复现；
5. 若未达到 5，保留当前最佳模型并继续由新增 Docking 数据驱动主动学习，不修改旧结果阈值。
