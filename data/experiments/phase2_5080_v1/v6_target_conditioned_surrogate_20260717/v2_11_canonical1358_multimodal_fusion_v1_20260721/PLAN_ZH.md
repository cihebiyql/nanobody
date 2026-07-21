# V2.11 canonical 多模态融合计划

## 目标

在不访问 frozen/sealed truth 的前提下，用已有结构资产回答：

```text
S0 序列
+ M2 VHH 单体结构
+ C2 双受体粗姿态
→ 是否提高对独立双受体 Docking 连续几何的早期富集
```

证据边界始终只是 computational Docking geometry surrogate，不是结合或实验阻断概率。

## 可立即闭合的 cohort

V2.10 canonical10644 与现有 V4-D/V4-H 结构、C2、graph 资产的交集为 1,358 条：

- train：1,282 条、21 个 parent；
- development：76 条、6 个未见 parent；
- development 76 条均为 V4-D multi-seed teacher；
- 126D/C2/graph 的 sequence 和 monomer hash 均须闭合。

该 1,358 条用于立即验证。Runner 不硬编码行数；未来物化完整 10,644 条 M2/C2 后可直接重跑。

## 执行顺序

1. materializer 连接 canonical teacher、split、V4-D/V4-H 126D、C2 36D 和 650M cache；
2. train1282 内生成 whole-parent OOF 的 S0、M2、C2 prediction；
3. 仅用 train OOF 选择 C2 alpha、拟合非负凸融合和浅 GBDT；
4. 在 untouched dev76 上一次性评估早期富集；
5. 若提供 V2.10 full9849 的三种子预测，只作为独立 base comparator，不参与融合权重拟合；
6. 后续再把 target-attention B / marginal-contact E 接成额外 OOF branch。

## 为什么先做这个版本

旧证据显示 M2 对连续几何有较稳定信号，C2 有小幅增量；target/contact 更昂贵且此前 contact 独立增量不稳定。因此先用 CPU 严格证明结构/粗姿态能否改善新 canonical split 的 Top-K 富集，再决定 GPU target branch 的资源投入。
