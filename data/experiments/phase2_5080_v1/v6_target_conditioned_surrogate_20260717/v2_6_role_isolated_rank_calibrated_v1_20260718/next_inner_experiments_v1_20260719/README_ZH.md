# V2.6 下一批 open-inner 最小实验 V1

## 目的

1. 补齐 `B_SCALAR_ATTENTION_ONLY` 的 seed 97/193，与 F0 做严格三种子匹配比较。
2. 将 early enrichment 设为主要工程指标：EF、Recall、binary NDCG 和 within-parent EF。
3. 评估 marginal-only 与 pair-only 接触监督，但不修改冻结的 Integration V1.3。

## 冻结边界

- 仅 `outer_0_inner_0` open-development split。
- 禁止读取 V4-F/test32、outer-test truth 和 outer metrics。
- 输出仍只代表独立双受体 Docking 连续几何的近似，不代表结合、Kd 或实验阻断。
- B 补种子直接复用冻结 V1.3 wrapper；训练超参数完全不变。

## 可行性结论

- B seed97/193：**可直接安全运行**。
- early-enrichment collector：**可直接运行**。
- marginal-only/pair-only：冻结 V1.3 在训练入口明确要求 marginal 和 pair 权重都大于 0，因此旧代码**不支持**。本目录已另建 Integration V1.4 扩展并通过 6 个 CPU contract tests；它没有编辑或覆盖 V1.3。仍需通过完整继承回归和两个 CUDA smoke，才允许建立 GPU launcher。

## 预期判定

- 先比较 B 与 F0 的三种子 ensemble，避免把初始化/ensemble 收益误认为 contact 收益。
- 优先看 true Top10/20% 在预测 Top5/10/20% 的 Recall 和 EF。
- 必须同时报告 within-parent 指标；只在全局排序富集而同 parent 内接近随机，说明模型主要利用 scaffold/parent 信号。
