# V2.12 OOF 早期富集 portfolio

## 目标

在 Clean-Attention 五折 OOF 完成后，将四条互补证据合并：

```text
S0：序列 ESM2 统计基线
M2：VHH 单体结构特征
C2：廉价粗姿态扫描
B：序列 + VHH residue graph + 固定 PVRIG 双构象 target graphs
```

本版本不强迫只选一个模型，而是同时产生：

1. 四模态非负凸融合的连续 `R8/R9/Rdual_min`；
2. 强正则 positive Ridge 连续融合；
3. label-free rank-percentile consensus；
4. 固定浅层 top-10% 分类头 challenger。

最终比较重点是大库前筛需要的 `EF@5%`、`Recall true-top10%@5% budget`、`EF@10%` 与 within-parent top20 recall，而不是只看 MAE。

## 数据使用

- 只在 9,849 行 whole-parent OOF base predictions 上拟合融合头；
- 795 行 open development 仅用于版本冻结后的描述性评估；
- frozen/sealed test 不访问；
- Clean-Attention OOF 固定 seed 43，因此 open-development 也只使用 full-train seed43，避免 seed 分布不一致。

## 证据边界

基础特征对每条训练行均为 whole-parent OOF，但在没有重新训练双层 nested base learners 的情况下，不能把 meta-head 的训练内指标称为严格 nested OOF。正式报告只使用：

- base OOF 的描述性指标；
- 融合头在 open development 上的开发性结果。

该结果仍只是独立双受体 Docking 连续几何的代理，不是实验结合、Kd、实验阻断或 Docking Gold。

