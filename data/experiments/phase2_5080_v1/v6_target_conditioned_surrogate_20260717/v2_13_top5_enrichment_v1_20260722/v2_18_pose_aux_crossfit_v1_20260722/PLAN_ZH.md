# V2.18 Pose-Aux Cross-Fit 计划

## 目标

在不把 Docking 派生量作为推理输入的前提下，利用尚未消费的 Top-8 pose 连续分解监督，检验其是否能提高严格 whole-parent OOF 的 `EF@5%`。

当前基线为 V2.13-L1：

- 9,849 条 strict train；
- 54 个 parent framework clusters；
- 全局 Docking top10% 为阳性；
- top5% 预算为 493 条；
- 152 hits，`EF@5%=3.0828512886`。

`EF@5%=5` 至少需要 247 hits。本版本只在达到冻结晋级门槛时取代 L1。

## 数据事实

- V29 canonical release 中可安全用于当前训练的 6,872 条候选已经全部包含在 train9849，新增 scalar teacher 为 0。
- 这 6,872 条拥有 primary seed917 的 Top-8 pose 连续分解监督。
- 其中 1,372 条拥有至少两个 Docking seeds，可训练测量不确定性辅助头。
- 全覆盖的 126D monomer 与 36D coarse-pose 已在 V2.15--V2.17 使用；它们不是新模态。
- V4-H contact teacher 可覆盖 strict train 的 1,169 条候选，但单独作为第二阶段扩展，不与本版本首轮混合，避免无法归因。

## 输入防火墙

推理侧只允许：

1. 126D label-free monomer/置信度特征；
2. 36D label-free coarse-pose 特征；
3. 经严格 cross-fitting 产生的基础模型预测；
4. 由 label-free 特征预测出的 pose-aux 与 uncertainty 值。

禁止输入：

- candidate、parent、campaign、teacher-source ID；
- 真实 Top-8 pose 指标；
- 真实多 seed dispersion；
- Docking pose PDB 或 Docking score；
- open development 795 与 frozen test。

Parent 只允许用于 fold 划分和 groupwise loss。

## 辅助监督

从 seed917 Top-8 pose 表和 job summary 聚合：

- 每个 scoring reference 的 geometry utility 分布；
- hotspot、total occlusion、CDR3 occlusion/fraction；
- A/B support fractions；
- 每个 docking conformation 的 job geometry、pair consensus、native-cross agreement、strict-A fraction；
- 有重复 seed 子集的 `seed_dispersion_Rdual`。

## 严格验证

```text
5-fold outer whole-parent CV
└── 每个 outer-train 内 4-fold inner whole-parent CV
```

- inner-OOF 产生 outer-train 的 pose-aux 预测；
- 在完整 outer-train 重训辅助模型后产生 outer-test 预测；
- outer-test 永远只能看到预测辅助值，不能看到真实 pose 辅助标签；
- open795 与 frozen test 访问数必须为 0。

## 冻结挑战者

首轮只允许：

1. `A0_L1`：现有 L1 参考；
2. `A1_RIDGE_AUX`：强正则线性融合；
3. `A2_HGB2_AUX`：depth=2 的浅层 HGB challenger；
4. `A3_RIDGE_AUX_UNCERTAINTY`：在 A1 基础上加入预测 seed dispersion。

不得在 outer 结果后扩充网格。

## 晋级与停止线

- 完整性失败：任何 parent overlap、Docking 真值进入 outer-test 特征、ID 输入、open/test 访问，立即失败。
- 晋级：`EF@5% >= 3.40`、相对 L1 `delta >= 0.30`、至少 168 hits、Spearman 下降不超过 0.03。
- 目标达成：`EF@5% >= 5.0` 且至少 247 hits。
- 未达到晋级线：停止继续枚举相同输入上的头部/损失，等待更多独立 Docking、多 seed sentinel 或可复现 residue-contact/approach-angle 信息。

## 声明边界

输出仅表示对独立双受体计算 Docking 几何的 surrogate 富集能力；不是结合概率、Kd、IC50、实验阻断、表达或纯度证据。
