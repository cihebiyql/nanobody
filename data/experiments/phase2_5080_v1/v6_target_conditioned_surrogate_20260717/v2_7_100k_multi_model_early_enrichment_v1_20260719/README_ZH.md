# V2.7：10 万条序列的多模型早期富集

## Stage 0 目标

建立第一个可运行的 **sequence-only** 基线：只读取 VHH 序列、CDR 序列、
冻结 ESM2 pooled embedding 和由序列直接计算的理化特征，直接预测：

```text
R_8X6B
R_9E6Y
R_dual_min = min(R_8X6B, R_9E6Y)
```

主用途不是替代 Docking，而是在约 100,000 条设计序列中优先富集值得继续
Docking 的候选。当前版本只进行 open-development inner-validation；不访问
V4-F/test32、outer-test truth 或 outer-test metrics。

## 首批模型

1. `RIDGE_ESM2_650M`：ESM2-650M 的 whole-VHH/CDR1/CDR2/CDR3 pooled embedding + 序列理化特征。
2. `RIDGE_ESM2_3B`：ESM2-3B 的同类 pooled embedding + 序列理化特征。
3. `RIDGE_ESM2_650M_3B`：两种 PLM embedding 拼接 + 序列理化特征。
4. `ELASTICNET_ESM2_650M_PCA`：650M embedding 经 train-only PCA 后的 ElasticNet。
5. `MLP_ESM2_650M_PCA`：650M embedding 经 train-only PCA 后的浅层 MLP。
6. `MEAN_5MODEL`：以上五个模型对 R8/R9 的固定算术均值；推理时重新 exact-min。

Ridge 的 alpha 只在 1,085 条 inner-train 内按 whole-parent GroupKFold 选择；
184 条 inner-score 不参与特征缩放、PCA、模型拟合或超参数选择。

## 主评估

- `R_dual_min` Spearman、MAE、RMSE；
- true Top10% / Top20% 在 predicted Top5% / Top10% / Top20% 中的 recall、precision、EF；
- binary NDCG；
- within-parent Top20% enrichment；
- 多模型 Top-K 重合度，判断集成是否只是重复同一信号。

## 证据边界

这些标签和预测只表示独立 8X6B/9E6Y computational Docking geometry 的近似，
不是结合概率、Kd、实验阻断概率或 Docking Gold。任何 model selection 结论只适用于
当前 open inner development split。

