# V2.14 Listwise Top5 神经训练计划

## 为什么需要 V2.14

V2.13 的 C0 结果说明：

- 等权四模态 whole-parent OOF EF5 约 2.96；
- 嵌套受限权重约 3.02，但未达到预注册增益门槛；
- Logistic/HGB/ExtraTrees hard-negative 头没有改善；
- 四个单模态 Top5 并集仍覆盖 325 个真实 Top10，理论 EF5 上限约 6.59。

因此主要问题是深层表示在 Top 区域的排序不够，而不是简单 meta-head 不够复杂。

## 固定架构

保持 V2.13 的输入和物理一致性：

```text
ESM2-650M residue embedding（冻结）
+ VHH 单体图
+ 8X6B 固定靶标图
+ 9E6Y 固定靶标图
→ 分别预测 R8/R9
→ 推理时 exact min 得到 Rdual
```

不引入 candidate ID、parent ID、campaign ID、Docking pose 或 pose-derived 输入。

## 训练改变

把 minibatch 从 8×累积4 改为 32×累积1，保持近似相同有效 batch 和更新次数，使每个 batch 能形成真正的 listwise 排序。

每个 batch 固定包含：

```text
8 条训练折内 truth percentile >= 0.90
24 条其余候选
```

比较三个结果盲变体：

1. N1 ListMLE：Top 加权 Plackett–Luce/ListMLE；
2. N2 SoftTopK：可微 soft-rank 直接最大化 batch Top-K 中的正例召回；
3. N3 Hybrid：ListMLE + SoftTopK + 低权重 PairLogit。

基础 R8/R9 Huber 和 softmin 辅助损失继续保留。

## 评估与晋级

- 仍使用相同 54 parent、五折 whole-parent OOF；
- seed43 完成结果盲选型；
- 通过门槛后才运行 seed917/1931；
- 主指标 EF@5，辅助 EF10、NDCG@5、Spearman、MAE、fold 稳定性；
- 不访问开放 development 或 frozen test；
- 若无变体通过门槛，保留 V2.13/多模态 baseline，不放宽阈值。

## 资源计划

等待当前 V2.13 Phase B/C/HN 链终止后，在 Node1 GPU 3/4/5 并行运行 N1/N2/N3；CPU 线程每任务固定为 1，GPU 启动门槛沿用 V2.13。
