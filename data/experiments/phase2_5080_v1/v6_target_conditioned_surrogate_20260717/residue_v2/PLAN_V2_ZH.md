# Residue V2：双域平衡的三维靶点条件 Docking 几何代理

## 目标

V2 的唯一主目标仍是：

```text
VHH 序列 + label-free VHH 单体结构 + 固定 PVRIG 双构象
→ 预测独立 8X6B/9E6Y Docking 的连续几何
→ 主目标 R_dual_min
```

证据边界：V2 只逼近计算 Docking 几何，不输出结合概率、Kd、实验竞争/阻断概率、
Docking Gold 或最终提交结论。V4-F/test32 在预测冻结前保持 sealed。

V1.5 已冻结为对照，不修改其 trainer、collector、阈值或结果。V1.5 F3 的整体
`ΔSpearman=+0.00281`，但 V4D 为 `-0.01060`、Top20 只净增 1 条，说明继续微调
旧 residual 权重的收益不足。V2 因此另起版本，解决四个结构性问题。

## 四项改动

### 1. V4D 226 条多种子 residue-contact 监督

Node23 原始 V4D OPEN_TRAIN 数据可闭合为：

```text
226 candidates
20 parent clusters
2 receptors
3 expected seeds
1356 scheduled jobs
1355 SUCCESS + 1 FAILED_MAX_ATTEMPTS
```

225 条候选为完整 `2 receptor × 3 seed`；唯一技术不完整候选为：

```text
RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00
```

它缺少 `8x6b/seed3253`，但仍有 8X6B 两个成功 seed 和 9E6Y 三个成功 seed，
因此保留并记录 observed seed count，不补零、不伪造重复。

提取规则：

1. 只读取 `model_split=OPEN_TRAIN`；
2. 先执行 V4D V1.2 已冻结的 native overlay `t_ca_rmsd_a <= 1.0 Å`；
3. 每 job 对有效 pose 按 HADDOCK score 排序，取 Top-8；
4. 每 job 至少 4 个有效 pose；
5. heavy-atom `ATOM`、4.5 Å 接触；
6. pose 权重为归一化 `1/log2(rank+1)`；
7. 每 seed 独立形成 pair contact frequency；
8. 同 receptor 的 observed seeds 等权聚合；
9. 同时保存 pair mean、variance、support、observed/expected seed count；
10. residue marginal 使用 `mean_seed(P_pose(any PVRIG contact for residue i))`，不能以
    `max_j mean_seed(pair_ij)` 静默替代。

V5 已存在 133,062 行未经 V1.2 pose-validity 重建的 contact-pair 中间表，只作为
交叉核验，不直接成为 V2 canonical teacher。V2 必须从冻结原始 poses 重新生成。

### 2. 双域平衡采样与损失

训练集固定为：

| source | candidates | parents | teacher |
|---|---:|---:|---|
| V4D OPEN_TRAIN | 226 | 20 | multi-seed dual receptor |
| V4H Stage1 | 1281 | 11 | single-seed dual receptor |
| 合计 | 1507 | 31 | continuous computational geometry |

`teacher_source` 只用于 sampler、loss 和审计，禁止作为模型特征。

训练 microbatch 固定为 `2 V4D + 6 V4H`，并保存每 epoch 的确定性重采样清单。
标量、receptor、ranking、marginal contact、pair contact 都先在各 source 内归一化，
再按 source 等权融合：

```text
L_component = 0.5 * L_V4D + 0.5 * L_V4H
```

这避免 1281 条 V4H 在梯度上淹没 226 条更高重复度的 V4D。原 sample weight 只可在
source 内使用，不得被误当作已经完成 domain balance。

### 3. 实际有效的晋级门

V2 不沿用 V1.5 的“只要略有改善即可”门槛。正式 OOF 结果必须同时满足：

1. global `ΔSpearman >= 0.010`；
2. V4D `ΔSpearman >= 0`；
3. V4H `ΔSpearman >= 0`；
4. parent win 定义为 `ΔSpearman >= +0.01`，loss 定义为 `<= -0.01`；
5. 全部 parents 的 wins > losses；
6. V4D parents 和 V4H parents 分别 wins >= losses；
7. exact Top20 预算：global k=302，净增真阳性至少 5 条；
8. V4D k=46、V4H k=257 均不得净损失；
9. global parent bootstrap median delta > 0 且 positive fraction >= 0.80；
10. V4D、V4H 各自的 parent bootstrap median delta >= 0 且 positive fraction >= 0.80；
11. 任一 source 的 MAE 恶化不得超过 0.001；
12. source/candidate/parent/outer-fold 闭包全部通过。

任何一项失败均输出 `DO_NOT_PROMOTE_RESIDUE_V2`。不得看结果后修改门槛、删除 parent、
挑 seed 或重新解释同一版本。

### 4. VHH 三维残基图与 PVRIG 双构象交互

候选输入只允许 label-free 单体结构，禁止读取 candidate docking pose/complex。

VHH graph：

```text
node = frozen ESM2 residue state + AA + CDR/FR + confidence
edge = sequence edge + CA kNN16/radius12Å
edge feature = distance RBF + sequence separation + local-frame direction
encoder = 3-layer residual invariant MPNN, hidden128
```

PVRIG target graph：

```text
8X6B 和 9E6Y 分开缓存
node = AA/PLM + interface mask + SASA/secondary structure + local geometry
encoder = shared 2-layer invariant MPNN + conformer embedding
```

交互层使用低秩双向 cross-attention/biaffine pair logits，输出两个 receptor 的
VHH×PVRIG residue-pair contact matrix，再聚合 hotspot mass、interface specificity、
CDR1/2/3 mass、entropy、dual-min/gap。最终仍以显式 cross-fit M2 为基线：

```text
prediction = M2 + 0.02 * tanh(residual)
```

绝对坐标不能直接进入普通 MLP；图缓存必须通过旋转/平移不变性测试。

## 首轮冻结消融矩阵

四个 lane 在 Node1 GPU1-4 并行，各自顺序完成 5 个 whole-parent outer folds：

| lane | 单一新增因素 |
|---|---|
| A_DOMAIN | V1.5 head + 双域平衡 + 双域 marginal contact |
| B_VHH3D | A + VHH 3D residue graph |
| C_PATCH | B + 8X6B/9E6Y target graph/cross interaction；pair BCE=0 |
| D_FULL_PAIR | C + 双域 residue-pair soft BCE |

首轮冻结 ESM2，不做 LoRA。只有 D 或 C 在严格门槛上接近或通过，且三维信号稳定，
才允许在后续 V2.1 另行预注册 LoRA。

## 执行顺序

1. 生成 V4D V2 contact teacher 和 pose inventory；
2. 合并 V4D/V4H contact target，验证 1507/31 闭包；
3. 构建 1507 条 VHH monomer graph cache 与两个 PVRIG conformer graph cache；
4. 完成 sampler/loss/model/collector 单测；
5. 冻结所有输入、实现、矩阵和门槛哈希；
6. Node1 四卡 smoke；
7. 四 lane × 五 outer folds 正式 OOF；
8. 四 lane 全部 terminal 后统一 collector；
9. 最佳 lane 再以 seed 43/107/211 重复，至少 2/3 单 seed 和 ensemble 通过；
10. 仅在晋级后冻结全训练模型，用于大库 frontscreen；V4-F/test32 继续 sealed。
