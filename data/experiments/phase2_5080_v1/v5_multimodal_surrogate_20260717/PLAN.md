# PVRIG V5 多模态 Docking-Geometry Surrogate 实施计划

日期：2026-07-17

## 目标

在不改变现有 V4-D/V4-H 冻结产物的前提下，逐步验证新信息和新预测头是否能稳定超过当前 `M2 structure-only Ridge`：

```text
VHH sequence / label-free monomer structure
→ cheap surrogate
→ approximate independent 8X6B/9E6Y docking geometry
```

主目标继续是 `R_dual_min`。所有输出只能称为 computational docking-geometry surrogate，不能称为结合概率、Kd、PVRL2 实验竞争或实验阻断概率。

## 数据边界

第一阶段只使用：

```text
OPEN_TRAIN226
20 parent framework clusters
V4-E open research teacher continuous fields
open258 label-free monomer structure features
```

不读取：

```text
OPEN_DEVELOPMENT32 用于调参
V4-F/test32
任何 sealed prospective label
legacy128 training merge
```

`partial937` 仅允许在 OPEN_TRAIN226 方法冻结后作偏置敏感性诊断，不作为独立验证或模型选择依据。

## 共同验证合同

```text
outer = deterministic 5-fold whole-parent CV
inner = deterministic 5-fold whole-parent CV
supervision unit = candidate
seed/pose 不展开为训练行
parent ID 不作为模型输入
```

主指标：

```text
global Spearman / Pearson / MAE / NDCG / Top20 recall
parent-centered Spearman
per-parent macro mean/median Spearman
R8 / R9 / dual-gap auxiliary metrics
paired parent bootstrap delta vs M2
```

## 逐步实验

### Step 1：复现与数据闭合

- B0：outer-train mean；
- B1：当前 126 维结构特征直接预测 `R_dual_min`；
- 检查 B1 是否接近现有 M2 OOF 结果；
- 记录输入 SHA256、候选/parent/feature 数和 fold assignment。

### Step 2：双受体连续多头

- B2：用同一结构输入、共享 alpha，分别拟合 `R_8X6B` 与 `R_9E6Y`；
- 推理时计算 `min(pred_R8, pred_R9)`；
- 同时报告 `pred_gap=abs(pred_R8-pred_R9)`；
- alpha 只在 inner whole-parent OOF 上选择。

### Step 3：低维信息融合

- B3：126 structure + 27 dependency-free physicochemical descriptors；
- B4：B1 与 B2 的 inner-OOF convex stacking；
- 不使用 parent、candidate 或 batch ID 特征。

### Step 4：机器学习辅助头

- B5：outer-train top20 阈值定义的 Ridge classification head；
- B6：只使用同 parent 且 `|delta R| >= 0.02` 的 pairwise-difference Ridge ranker；
- 两者均只作排序辅助，不替代连续目标。

### Step 5：效果门

相对 M2 的候选改进必须同时满足：

1. global OOF Spearman 提高；
2. parent-centered Spearman 不下降；
3. Top20 recall 不下降；
4. 增益不是由单一 parent 驱动；
5. parent-bootstrap delta 的方向稳定。

本轮是 development comparison，不宣称 formal PASS。正式版本需另行预注册、冻结代码/输入哈希，并保留 untouched holdout。

### Step 6：V5-RC 输入准备

若 Step 1–5 完成，则建立但暂不伪造 contact 数据的合同：

```text
candidate × receptor × VHH residue × PVRIG residue contact-frequency
receptor-specific hotspot/interface masks
CDR1/2/3 contact mass
contact entropy / coverage / off-interface mass
```

只有 terminal top-K pose 可追溯聚合完成后，才训练 `M2 + gamma*contact_residual`。

## 停止条件

- 如果双受体、physchem、classification 和 pairwise heads 均不能稳定超过 M2，则保留 M2；
- 不通过改阈值、删除 parent、改 fold 或挑最好 seed 修成成功；
- 如果依赖缺失，优先完成 NumPy/Ridge 强基线，不临时引入未经批准的新依赖。

## 2026-07-17 执行结果

| 阶段 | 结果 | 决策 |
|---|---|---|
| V5-TB OPEN_TRAIN226 | B1 structure `Spearman=0.6868`；B2–B6 均未稳定超过 | 保留 B1/M2 |
| partial937 偏置诊断 | B2/B3 仅约 `+0.003`，bootstrap CI 跨 0；B4 约 `+0.001` | 不作模型替换 |
| V5-RC contact teacher | 226 candidates、452 receptor rows、133,062 residue-pair rows；1 seed 失败但仍满足每 receptor ≥2 seeds | contact teacher 闭合，可训练 proxy |
| V5-RC 无泄漏 contact proxy | C0 `0.6868`；最佳 contact C2 `0.6668`；contact target 中位 Spearman `0.2620` | `FAIL_KEEP_C0_STRUCTURE_LINEAR` |
| V5-RC.2 budget rank blend | blend `Spearman=0.6681`、parent-centered `0.2571`、Top20 `0.3913`，均未保住 C0 | contact 仅限 exploration |

V5-RC 的重要信号不是全局相关性提高，而是 C2 的 Top20 recall 从 `0.4348` 提高到 `0.5217`。这说明 contact proxy 当前不适合替代连续主模型，但可能适合作为 acquisition/高分候选补充通道。该用途必须另起版本，用 nested rank blend 或 budget-aware classifier 验证，不能在本版本结果上直接事后调权重。

## 下一轮建议

V5-RC.2 已按上述方式执行并失败。因此当前冻结结论是：

1. `C0/B1/M2 structure-only Ridge` 继续作为 exploitation 主模型；
2. contact proxy 不进入主总分，也不替换 M2；
3. contact 分数最多用于 10%–20% exploration quota 或模型分歧抽样；
4. 下一次真正值得做的升级不是继续调小型融合头，而是 residue-level、target-conditioned sequence/structure cross-attention，并增加更多 parent/diverse Docking teacher；
5. 新架构必须另起版本，并与当前 C0、C1、C2 三个强基线在 untouched parent clusters 上比较。
