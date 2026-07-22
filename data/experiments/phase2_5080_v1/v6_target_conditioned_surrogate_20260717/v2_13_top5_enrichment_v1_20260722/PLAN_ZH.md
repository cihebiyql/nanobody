# V2.13-TOP5：早期富集专项训练计划

## 目标

在不访问 frozen test、也不使用已经开放的 development 795 条进行训练或超参数选择的前提下，将四模态前筛的 Top 5% 富集从当前开放开发集的 `EF@5=3.975` 推向 `EF@5>=5.0`。

这里的正例定义保持不变：独立双受体 Docking 连续真值 `R_dual_min=min(R_8X6B,R_9E6Y)` 的真值 Top 10%。`EF@5=5` 等价于 Top 5% shortlist 中约 50% 属于 Docking 真值 Top 10%。该标签只表示计算 Docking 几何，不表示实验结合或阻断概率。

## 当前基线

- 训练池：9,849 条，54 个 parent framework clusters。
- 严格 whole-parent 五折 Clean-Attention OOF：`EF@5=2.2107`。
- 四模态开放开发集 portfolio：Top 40/795 命中 16 条，`EF@5=3.975`。
- 高把握 HC-A：8 条中 6 条属于 Docking 真值 Top 10%，但样本仍小，只作为开发证据。

## 执行分期

### Phase A：Top5 导向损失（本轮立即执行）

固定 ESM2-650M、VHH label-free monomer graph、8X6B/9E6Y fixed target graphs、原 whole-parent 五折和 seed 43，只改变训练目标：

| Variant | 改动 |
|---|---|
| L1 | Top 区域加权 Huber/softmin；不加 pair ranking |
| L2 | L1 + balanced top/non-top minibatch + PairLogit，权重 0.25 |
| L3 | L1 + balanced top/non-top minibatch + PairLogit，权重 0.50 |

训练标签分位数只从每个 fold 的 fit parents 计算；parent/candidate ID 不进入 neural forward。推理继续严格使用 `min(R8,R9)`。

三条 lane 分别占用 Node1 GPU 3/4/5，每条 lane 顺序训练五个 folds。CPU 线程固定为 1，避免加剧 Node1 当前 CPU 超订。每个 GPU 任务启动前要求空闲显存至少 18 GiB，并检查滚动利用率。

### Phase B：多 seed

只对 Phase A 在五折 OOF 中通过稳健门槛的 variant 继续运行 seed `43/917/1931`。不剔除较差 seed。聚合方式预注册为：先分别平均 R8/R9，再计算 exact min；rank mean 作为独立排序输出。

### Phase C：严格 meta-stack

使用 S0、M2、C2 和 Phase B 的 B ensemble，通过 nested whole-parent cross-fitting 比较：

1. equal percentile-rank mean；
2. 非负 rank-weighted stack；
3. Positive Ridge/ElasticNet；
4. shallow LambdaMART/PairLogit challenger。

普通 HGB top10 classifier 已在 V2.12 失败，不再作为主线。

### Phase D：冻结和 prospective 验证

冻结模型、seed、融合公式、HC-A/HC-B 规则和 tie-break 后，再评价下一批独立 Docking。开放 dev795 只允许在完整冻结后做一次描述性比较，不能用于选择。

## 选择门槛

Phase A/B 相对同协议 L0/V2.12 基线必须满足：

- pooled/fold-robust EF@5 明确改善；
- 至少 4/5 folds 不出现实质性退化，或 fold 方差显著下降；
- EF@10 不下降超过 5%；
- Spearman 不下降超过 0.03；
- MAE 不恶化超过 10%；
- 所有 exact-min、candidate、parent、fold、hash 和禁止访问 gate 通过。

最终目标只能由冻结后的独立 Docking cohort 证明：

```text
EF@5 >= 5.0
Precision@5 >= 0.50
Recall@5 >= 0.25
```

## 证据边界

V2.13 仍是独立双受体计算 Docking 几何 surrogate。whole-parent OOF 不等于 CDR3-family OOD；当前数据存在跨 parent 的 CDR3 复用。任何开发集结果都不能升级为实验 blocker 概率或正式比赛成功率。
