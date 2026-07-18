# Residue V2 冻结前 Loss Scale 只读审计

- 审计日期：2026-07-18
- 审计性质：正式 implementation freeze 前、仅使用 open training1507 与 tiny smoke 的只读诊断
- sealed test / V4-F：未读取
- 代码、阈值、损失权重：本审计未修改
- 证据边界：以下均是对计算 Docking 几何 teacher 的训练尺度诊断，不是结合、亲和力、实验阻断或 Docking Gold 证据。

## 一、冻结判断

**当前配置不应直接进入正式 freeze。**

冻结值：

```text
dual                 1.0
receptor             0.35
marginal contact     1e-4
pair contact         5e-5
ranking              1e-4
residual L2          0.05
```

真实 full1507 tiny `D_FULL_PAIR` smoke 表明，直接 contact supervision（marginal + pair）合计只占加权 objective 的 **0.1839%**；pair 单项仅占 **0.0513%**。同时，pair 网格有 **98.4908%** 的 exact-zero cell，普通 dense mean BCE 会强烈受到零类控制。

因此当前 D lane 更接近“带有极弱 pair 正则的 C lane”，不足以作为一个有辨识力的 `C_PATCH` vs `D_FULL_PAIR` pair-supervision 消融。

**建议：在任何正式 OOF/freeze 之前，另起显式、可追溯的 loss-scale amendment。不得静默改动现有 `PREREGISTRATION_V2.json`，也不得在看到正式 OOF 结果后再改。**

---

## 二、审计输入

### 2.1 训练候选

```text
v6_supervised1507.tsv
1507 candidates
31 parent clusters
V4D_OPEN_MULTI_SEED: 226
V4H_STAGE1_SEED917: 1281
```

几何目标分布：

| Source | Target | mean | std | min | median | max |
|---|---:|---:|---:|---:|---:|---:|
| V4D | R_8X6B | 0.5560 | 0.0477 | 0.3979 | 0.5569 | 0.6616 |
| V4D | R_9E6Y | 0.5535 | 0.0484 | 0.4183 | 0.5535 | 0.6667 |
| V4D | R_dual_min | 0.5420 | 0.0461 | 0.3979 | 0.5444 | 0.6449 |
| V4H | R_8X6B | 0.5765 | 0.0550 | 0.3847 | 0.5758 | 0.7108 |
| V4H | R_9E6Y | 0.5727 | 0.0540 | 0.3779 | 0.5728 | 0.7024 |
| V4H | R_dual_min | 0.5553 | 0.0521 | 0.3779 | 0.5556 | 0.6856 |

### 2.2 Marginal contact teacher

Marginal 表覆盖所有 VHH residue，并保留 exact zero：

| Source | receptor | residue cells | zero fraction | target mean | weighted target mean |
|---|---:|---:|---:|---:|---:|
| V4D | 8X6B | 27,569 | 71.30% | 0.14079 | 0.13648 |
| V4D | 9E6Y | 27,569 | 71.92% | 0.13762 | 0.13350 |
| V4H | 8X6B | 158,759 | 75.11% | 0.09595 | 0.09595 |
| V4H | 9E6Y | 158,759 | 75.52% | 0.09454 | 0.09454 |

Marginal 的零类不平衡中等偏强，但远弱于 pair 网格。

### 2.3 Pair contact teacher

正式输入：

```text
pvrig_v6_dual_pair_contact_targets_v2_20260718/
pair_table_semantics = SPARSE_ABSENCE_IS_EXACT_ZERO
593,346 nonzero soft-target rows
39,315,208 full residue-pair cells
```

| Source | receptor | full cells | nonzero rows | nonzero fraction | exact-zero fraction | dense mean target |
|---|---:|---:|---:|---:|---:|---:|
| V4D | 8X6B | 2,839,607 | 66,374 | 2.3374% | 97.6626% | 0.003317 |
| V4D | 9E6Y | 2,977,452 | 66,500 | 2.2335% | 97.7665% | 0.003117 |
| V4H | 8X6B | 16,352,177 | 231,728 | 1.4171% | 98.5829% | 0.003400 |
| V4H | 9E6Y | 17,145,972 | 228,744 | 1.3341% | 98.6659% | 0.003211 |
| **合计** | dual | **39,315,208** | **593,346** | **1.5092%** | **98.4908%** | **0.003290** |

非零 soft targets 也主要靠近零：

| Source/receptor | nonzero median | `<0.05` | `<0.10` | `>=0.50` |
|---|---:|---:|---:|---:|
| V4D / 8X6B | 0.0843 | 28.54% | 55.43% | 3.43% |
| V4D / 9E6Y | 0.0843 | 29.25% | 56.08% | 3.52% |
| V4H / 8X6B | 0.1776 | 0% | 26.54% | 9.65% |
| V4H / 9E6Y | 0.1776 | 0% | 26.43% | 9.89% |

结论：pair 不是普通约 1:1 分类问题，而是约 **1.5% 稀疏、且正值多为软小值** 的密集 soft-BCE 问题。

---

## 三、真实 tiny smoke 的原始损失量级

为避免只做静态推断，使用当前 trainer、当前 full1507、当前 contact/pair 表，复跑等价的 tiny `D_FULL_PAIR`、outer fold 0、1 epoch smoke。该运行只用于 scale audit，不是正式模型结果。

```text
status: PASS_OUTER_FOLD_COMPLETE
elapsed: 94.53 s
max RSS: 3,195,204 KB
RESULT SHA256:
1a0af1e423e1828778f456389935083b11ab16d4ead4428f88e3c64f44ef1651
sealed test accessed: false
```

统计对象为 5 个 inner-selection train 段加 1 个 final-refit train 段，共 6 个 loss 日志的平均值。

| Component | raw mean | frozen weight | weighted mean | objective fraction |
|---|---:|---:|---:|---:|
| dual | 0.0257642 | 1.0 | 0.0257642 | 72.6303% |
| receptor | 0.0275156 | 0.35 | 0.00963047 | 27.1487% |
| marginal | 0.470101 | 1e-4 | 0.0000470101 | 0.1325% |
| pair | 0.364230 | 5e-5 | 0.0000182115 | 0.0513% |
| ranking | 0.0963992 | 1e-4 | 0.0000096399 | 0.0272% |
| residual L2 | 0.0000707245 | 0.05 | 0.0000035362 | 0.0100% |
| **total** | — | — | **0.0354731** | 100% |

```text
marginal + pair weighted contribution
= 6.5222e-5
= 0.1839% of total objective
```

V4D/V4H 的 pair raw loss 均值分别为 0.3633 和 0.3652，说明 source balancing 本身正常；问题不是 V4H 数量淹没 V4D，而是整个 direct contact lane 相对几何损失太弱。

---

## 四、梯度贡献近似

### 4.1 方法边界

当前 `RESULT.json` 记录 per-component loss，但不记录每个 component 的独立 parameter-gradient norm。本节因此给出两种可复核 proxy：

1. **实际加权 objective contribution**：来自上述真实 tiny smoke；
2. **输出空间一阶导数量级**：按当前 SmoothL1/BCE/ranking 公式解析估计。

这不是完整网络 parameter-gradient 的替代品；正式 amendment 必须增加独立 per-component gradient-norm smoke 后再冻结。

### 4.2 Geometry

`dual/receptor` 使用 `beta=0.03` 的 SmoothL1。raw loss 约 0.026–0.028，表明大量误差已处于或接近线性区，输出导数通常为 `O(0.1–1)`：

```text
dual weighted output-gradient scale:       O(1)
receptor weighted aggregate scale:         O(0.35)
per receptor channel approximately:         O(0.175)
```

### 4.3 Marginal BCE

在无信息 `logit=0, p=0.5` 时，source-balanced target mean 约 0.095–0.136：

```text
|p-y| ≈ 0.36–0.41
× 1e-4
≈ 3.6e-5–4.1e-5
```

结合 smoke BCE 0.47 的量级，实际典型直接 logit-gradient 仍大致在 `2e-5–4e-5`。

### 4.4 Pair BCE

全体 dense mean soft target 为 0.0032899。在 `logit=0`：

```text
mean bias derivative = 0.5 - 0.0032899 = 0.4967101
× 5e-5
= 2.4836e-5
```

若用 smoke pair BCE 0.364 粗略反推 zero-cell probability 约 0.30，则加权 bias-gradient proxy 约为：

```text
(0.30 - 0.0033) × 5e-5 ≈ 1.5e-5
```

因此 pair direct gradient 是 `O(1e-5)`，相对 geometry 的 `O(1e-1–1)` 小约 **4–5 个数量级**。即使考虑不同 head Jacobian，当前权重也极可能使 pair supervision 在共享参数更新中接近不可辨识。

### 4.5 Ranking 与 residual

- ranking raw mean 0.0964、temperature 0.03。按 `d softplus(z)/dz` 反推，活跃 pair 的加权 prediction-gradient 约 `O(3e-4)`，但还要经过 per-candidate pair normalization；仍显著低于 geometry。
- residual RMS 约 `sqrt(7.07e-5)=0.00841`。L2 对 residual 的加权导数约 `O(2.8e-4)`/output；再经过 `0.02*tanh` 上界缩放，传回 raw residual head 的尺度约 `O(5.6e-6)`。

### 4.6 重要架构说明

Pair logits 还会通过 pair summary / residual pathway 接收 geometry loss 的间接梯度。因此不能说 pair head 完全没有梯度。

但这类间接梯度只要求 pair 表征有助于拟合 `R_dual_min`，**不等同于监督 pair contact map 本身**。当前 direct pair BCE 过弱时，D lane 无法证明学到了 docking-derived residue-pair contact pattern。

---

## 五、零类支配判断

### Pair

**明确会被零类支配。**

- exact zero：98.49%；
- dense mean target：0.00329；
- 普通 dense mean BCE 的常数偏置最优方向强烈指向接近零；
- 非零 target 中还有大量 0.03–0.18 的软小值；
- 单纯提高 `5e-5` 权重会同时放大大量零 cell，不一定增加有效 positive-contact 学习。

所以问题不是只把 `5e-5` 改大即可，而是 **loss normalization/formulation 与 weight 必须一起预注册**。

### Marginal

Marginal 的 exact-zero 比例为 71%–76%，不平衡较轻，但 `1e-4` 使其 direct signal 同样接近无效。它可保留 dense soft BCE，但至少需要在 amendment gradient pilot 中校准；若仍不足，可采用与 pair 一致的 nonzero/zero 分层归一化。

---

## 六、正式 freeze 前的显式 amendment 建议

### 必须做

1. 新建独立版本的 loss-scale amendment；原文件保留，不覆写历史。
2. 声明 amendment 发生于正式 OOF 与 sealed test 解封之前，仅使用 open training1507 tiny smoke。
3. 为每个 component 记录：
   - raw loss；
   - frozen-weighted loss；
   - 对全部 trainable head parameters 的独立 gradient L2 norm；
   - 对 pair head、target encoder、residual head 的分组 gradient norm；
   - marginal+pair / total-gradient fraction。
4. 将现有 `contact_gradient_fraction_fail_scale=0.30` 明确解释为**上限**；另加非零下限。当前契约只有上限，无法发现 contact supervision 过弱。
5. amendment 固定后才重建 implementation freeze 与部署矩阵；不得复用现有 freeze hash。

### Pair loss 首选形式

不建议继续使用未经平衡的全网格单一 mean BCE。建议预注册候选级、受体级的两部分 loss：

```text
L_pair_candidate_receptor
= 0.5 * mean_uncertainty_weighted_BCE(nonzero sparse rows)
+ 0.5 * mean_BCE(exact-zero absent rows)
```

然后继续维持现有：

```text
candidate mean
→ receptor mean
→ source 内 sample-weight mean
→ 0.5*V4D + 0.5*V4H
```

优点：

- positive set 由 `SPARSE_ABSENCE_IS_EXACT_ZERO` 的非零行直接定义，无需事后阈值；
- 保留完整 soft target 与 uncertainty；
- 不让 98.49% 零 cell 决定全部梯度；
- 保持 candidate、receptor、source 三层公平归一化。

Focal/asymmetric BCE 可作为备选，但会引入额外 gamma 等超参数；在当前阶段，上述显式 nonzero/zero 双项归一化更易审计。

### 权重如何确定

本审计**不建议直接给出一个事后“最佳权重”**。应在 amendment 中预注册一个很小的 open-only gradient calibration grid，并在任何正式 OOF 前一次性冻结。

建议冻结标准而非追逐 tiny metric：

```text
contact direct gradient fraction:
- 必须有明确非零下限，使 D lane 与 C lane 可辨识；
- 必须低于现有 30% 安全上限，避免 noisy docking contact teacher 主导几何目标；
- 用固定 batch/seed/initialization 计算，不用 validation Spearman 选权重。
```

一个合理的工程校准目标区间可预注册为 **5%–20% direct contact gradient fraction**，同时保留 30% hard ceiling；具体权重由梯度 norm 达标决定，而不是由本次 tiny 预测表现决定。

---

## 七、最终结论

```text
1e-4 marginal:
  raw BCE 有信号，但权重后只有 objective 的 0.1325%，direct gradient 约 O(1e-5)。

5e-5 pair:
  权重后只有 objective 的 0.0513%，direct gradient 约 O(1e-5)，几乎无直接信号。

pair data:
  98.4908% exact zero；普通 dense BCE 明确受零类支配。

freeze decision:
  DO NOT FREEZE CURRENT LOSS SCALE.

required action:
  在正式 OOF 前另起显式 amendment；先改变 pair 的正/零归一化，再用 open-only
  per-component gradient-norm smoke 校准权重和非零下限，最后重建 freeze。
```
