# PVRIG V3-P2 Docking Gold V1.2 校准方法预注册

- 文档日期：2026-07-14（Asia/Shanghai）
- 方法状态：`CALIBRATION_METHOD_PREREGISTERED_IMPLEMENTATION_NOT_COMPLETE`
- 适用协议：`DG_A_PVRIG_V1_2_DEV`
- V1.1 状态：`FAIL_DOCKING_GOLD_NOT_VALIDATED`
- P2 状态：`P2_TRAINING_BLOCKED`
- 声明边界：本文只预注册计算 docking geometry 校准方法，不是实验 binding、affinity、Kd 或 functional blocking 真值。

## 1. 核心决定

V1.2 校准必须按以下顺序实施：

```text
fixed 4_emref Top-8 pose closure
-> ATOM-only PVRL2 continuous metrics
-> family-balanced success-anchor cutpoints
-> pose-level A/B/C/E geometry strata and continuous score
-> fixed rank-weighted run aggregation
-> LOFO / hierarchical bootstrap / mutant paired sensitivity
-> rules and hashes freeze
```

最重要的当前边界是：

> **47/47 校准 case 都只做过 8X6B-receptor docking。8X6B 和 9E6Y 在这些 case 中是同一批 pose 的两个 post-hoc scoring baseline，不是两次独立 receptor docking。因此这 47 个 case 只能冻结 pose 合同、baseline-specific cutpoint 和 `R_calibration_run_8x6b_dock`；不能冻结或验证最终 dual-receptor `R_gold`。**

现有 development protocol 已要求所有 run 从 `4_emref` 确定性取 Top-8，且禁止使用可变 final pose 分母（证据：`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_DEVELOPMENT_PROTOCOL_ZH.md:16-20`）。当前 Top-8 selection audit 记录 47 case、376 pose、`formal_eligible=false` 和 `source_stage=4_emref`（证据：`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_calibration_emref_top8_selection_audit.json:3`、`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_calibration_emref_top8_selection_audit.json:19449-19478`）。

## 2. 数据角色与禁止混用

### 2.1 核心校准 cohort

| cohort | 数量 | 用途 | 禁止用途 |
| --- | ---: | --- | --- |
| success anchors | 11 | H/O/P 阈值拟合、family sensitivity、LOFO、bootstrap | 不进普通训练，不代表所有成功机制 |
| mutant/perturbation controls | 36 | 与 exact base 的配对几何敏感性 | 永不预设为 negative，不参与 anchor cutpoint 拟合 |

11 个 success anchor 来自 5 个 family：

```text
20: 2
30: 2
38: 1
39: 3
151: 3
```

家族和样本账本见 `batch_manifest.csv` 的 11 条数据行（证据：`/mnt/d/work/抗体/docking/calibration/patent_success_validation/batch_manifest.csv:2-12`）。36 个 perturbation 及其 7 个 exact base reference 的角色见 mutant panel（证据：`/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/mutant_panel.csv:2-37`）。现有 development protocol 同样将 11 个 anchor 定义为 family sensitivity，将 36 个 mutant 定义为不预设负类的几何敏感性对照（证据：`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_DEVELOPMENT_PROTOCOL_ZH.md:240-253`）。

### 2.2 只作后续分布诊断的 cohort

- 21 个 matched controls：只用于 development distribution 和 out-of-support 诊断。
- 32 个 Teacher500 stratified candidates：只用于 development distribution、来源/生成器偏差和规则稳定性检查。
- 二者都不能并入 36-mutant panel 伪造“实验负例”，也不能反过来决定 success-anchor cutpoint。

这一分工与已冻结的 cohort 边界一致（证据：`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_DEVELOPMENT_PROTOCOL_ZH.md:232-253`）。

### 2.3 当前 sensitivity package 不能拟合阈值

`docking_gold_v1_2_calibration_sensitivity` 虽已在 ATOM-only 语义下完成 932 行连续指标复算，但它使用的仍是 legacy `6_seletopclusts` 可变 final pose set，而不是 fixed Top-8。机器审计明确记录：

```text
fixed_k_pose_ensemble = false
formal_eligible = false
pose_source_protocol = legacy_6_seletopclusts_variable_final_pose_set
threshold_freeze_eligible = false
thresholds_or_classes_applied = false
```

证据：`experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_calibration_sensitivity/pvrig_v1_2_sensitivity_audit.json:1035-1045`、`experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_calibration_sensitivity/pvrig_v1_2_sensitivity_audit.json:1054-1073`、`experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_calibration_sensitivity/pvrig_v1_2_sensitivity_audit.json:1146-1149`。

因此该 package 只能证明 scorer sensitivity、record inventory 和 numeric closure，**不得用于本文的分位数阈值、A/B/C/E、run tier 或 `R_gold` 拟合**。

## 3. 47-case 输入闭包合同

拟合开始前必须同时满足：

```text
case_count = 47/47
canonical_pose_count = 47 * 8 = 376
baseline_metric_rows = 376 * 2 = 752
canonical_rank per case = exactly 1..8
source_stage = 4_emref for 376/376 poses
all required numeric fields = finite
reference PVRL2 HETATM used in occlusion = 0
pose/config/io/reference/hotspot/scorer provenance = hash-closed
```

任一硬门失败，该 case 不得生成 score/tier，也不得以 G5 表示计算失败。当前 selection audit 已证明 47 个 case 各有一个 `4_emref/io.json`，其中 43 个有 10 个 output、4 个有 9 个 output，并已确定性选出 376 个 pose。这只是 pose-selection closure；752 行新连续指标与后续规则仍须独立审计。

## 4. 连续指标 H/O/P

对每个 canonical pose `r` 和每个 post-hoc scoring baseline `b in {8x6b, 9e6y}` 分别计算：

| 通道 | 定义 | 范围/变换 | 角色 |
| --- | --- | --- | --- |
| `H_b` | `hotspot_weight_fraction` | `[0,1]`，identity | PVRIG-PVRL2 functional-interface hotspot 接触强度 |
| `O_b` | `total_occluding_residue_pair_count` | `>=0`，校准中用 `log1p` | VHH 对 PVRL2 参考位置的总残基对遮挡 |
| `P_b` | `(CDR1_pairs + CDR2_pairs + CDR3_pairs) / O_b` | `[0,1]`；`O_b=0` 时强制为 `0` | 遮挡是否主要由 CDR 而非 framework 贡献 |

`CDR3_pairs / O_b` 必须保留为次级解释指标，但不进入中心 pose score，以避免把合理的 CDR1/CDR2 贡献错误降级。

H/O/P 必须来自新 fixed Top-8 的 ATOM-only 连续指标表。PVRL2 只读 protein `ATOM` heavy atoms，全部 `HETATM`（包括 HOH、EDO、糖和其他配体）均排除。V1.1 已确认 `HETATM` 会改变连续指标和分类（证据：`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_V1_1_HETATM_CONTAMINATION_REJECTION_ZH.md:8-22`）。

## 5. family-balanced hurdle cutpoint

### 5.1 排名权重和 family 平衡

对 rank `r=1..8`：

```text
q_r = 1 / log2(r + 1)
Q_r = q_r / sum_{j=1..8}(q_j)
```

对 family `f`、该 family 内 success-anchor case `c` 和 rank `r`：

```text
w_fcr = (1 / 5) * (1 / n_f) * Q_r
```

`n_f` 是 family `f` 的 anchor case 数。因此每个 family 总权重严格为 `1/5`，family 内 case 等权，case 内 pose 按冻结 rank 权重。不使用 cluster-size 权重，也不对某个有 3 条 anchor 的 family 给予更高总权重。

### 5.2 zero hurdle 和基线特异分位数

对每个 baseline `b` 和每个 metric `m in {H,O,P}` 独立执行：

1. 先报告加权 zero mass `pi0_bm = sum(w_fcr * I[x_bm=0])`。
2. 只在 `x_bm > 0` 的 positive part 中重新归一化权重。
3. 中心下切点 `L_bm` 取 positive-part 加权 `q20`。
4. 中心上切点 `U_bm` 取 positive-part 加权 `q50`。
5. 8X6B 和 9E6Y 使用同一分位数规则，但保留 baseline-specific raw cutpoint，禁止先平均两个 baseline 再拟合。
6. 同时报告不加权 zero mass 和不加权 positive-part q20/q50，仅作 sensitivity，不替代 family-balanced 中心规则。

任一 baseline/metric 出现 positive part 不足以同时定义两个分位数、`L<=0` 或 `U<=L`，都必须判定 threshold fit FAIL，不得用 epsilon、手工阈值或旧 V1.1 阈值修补。

### 5.3 归一化 membership

对 `m in {H,O,P}`：

```text
mu_bm(x) = 0,                                              if x = 0
mu_bm(x) = clip((T_m(x)-T_m(L_bm))/(T_m(U_bm)-T_m(L_bm)), 0, 1), if x > 0

T_O(x) = log1p(x)
T_H(x) = x
T_P(x) = x
```

这是连续标度，不是概率校准。

## 6. pose 连续分数和 A/B/C/E 几何层

### 6.1 baseline-specific pose score

```text
S_b = sqrt(mu_bO * ((mu_bH + mu_bP) / 2))
```

`S_b` 仅表示该 pose 在 scoring baseline `b` 下的相对遮挡几何支持。它不是 binding probability、blocking probability 或亲和力分数。

### 6.2 A/B/C/E 定义

每个 baseline 独立分类，且按下表从上到下应用：

| stratum | 冻结条件 | 解释边界 |
| --- | --- | --- |
| A | `O>=U_O and H>=U_H and P>=L_P` | 强 blocker-like geometry support |
| B | `not A and O>=L_O and (H>=L_H or P>=L_P)` | plausible blocker geometry support |
| C | `H>=L_H and O<L_O` | hotspot-facing / binder-like，但遮挡不足 |
| E | 其他 | 当前 pose 几何支持不足 |

表中所有 `L/U` 都是当前 baseline 的 raw cutpoint。A/B/C/E 是有序 geometry strata，不是阳性/阴性、binder/non-binder 或实验 blocker/non-blocker。

### 6.3 paired-scoring-baseline relevance

将同一 pose 在 8X6B 和 9E6Y post-hoc scoring baseline 下的 stratum 组合映射为：

| 条件（按优先级） | `rel` |
| --- | ---: |
| A/A | 4 |
| 任一单 baseline 为 A，但非 A/A | 3 |
| 无 A，任一 baseline 为 B | 2 |
| 无 A/B，任一 baseline 为 C | 1 |
| E/E | 0 |

连续 paired score 为：

```text
S_pair = (S_8x6b + S_9e6y) / 2
baseline_gap = abs(S_8x6b - S_9e6y)
```

`baseline_gap` 单独报告，不减分、不嵌入 `S_pair`。这里的“paired”仍只指同一 pose 的两个 scoring baseline，不代表独立双 receptor docking。

## 7. fixed Top-8 run 聚合

### 7.1 连续 run score

用第 5.1 节的 `Q_r` 聚合恰好 8 个 pose：

```text
R_run = sum_{r=1..8}(Q_r * S_pair_r)
```

不使用 `/cluster_size`，不按 fingerprint cluster 大小调整权重，不用可变 pose 数重新归一化。

### 7.2 support 和 G1-G5

对 `k in {1,2,3,4}`：

```text
F_k = sum_{r=1..8}(Q_r * I[rel_r >= k])
N_k = count_{r=1..8}(rel_r >= k)
```

中心 tier 要求 `F_k>=0.25 and N_k>=2`，取满足条件的最高 `k`：

| 最高通过 `k` | run tier |
| ---: | --- |
| 4 | G1 |
| 3 | G2 |
| 2 | G3 |
| 1 | G4 |
| 无 | G5 |

`R_run` 和 tier 必须并存：tier 提供有序解释，连续 `R_run` 保留层内信息。

### 7.3 当前 47-case 只能得到的分数

对当前 47 个 8X6B-docked case，唯一准确名称是：

```text
R_calibration_run_8x6b_dock
```

不得将它命名为 `R_gold`、`R_dual_receptor` 或 `R_8x6b_9e6y_docking`。47 个 config 均以 `pvrig_8x6b_chainB.pdb` 为 docking receptor；首个与末个 case 的配置锚点分别为 `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_01_PVRIG-151_HR151/haddock3/case02_pos_01_PVRIG-151_HR151_pvrig_hotspot_test.cfg:6-9` 和 `/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs/mut_36_39H4_fw_cons_Y59F/haddock3/mut_36_39H4_fw_cons_Y59F_pvrig_hotspot_test.cfg:6-9`，全量 47-config 遍历复核见第 15 节。

## 8. 最终 dual-receptor `R_gold`

只有对同一 candidate 完成两条独立 docking receptor run，且两条 run 都各自通过 fixed Top-8 全合同后，才能定义：

```text
R_run8dock = R_run from an independent 8X6B-receptor docking run
R_run9dock = R_run from an independent 9E6Y-receptor docking run

R_gold = (R_run8dock + R_run9dock) / 2
```

同时必须报告：

```text
R_gold_min = min(R_run8dock, R_run9dock)
R_gold_max = max(R_run8dock, R_run9dock)
docking_receptor_gap = abs(R_run8dock - R_run9dock)
per-receptor F_k / N_k / tier
dual-receptor support summary
```

每个独立 receptor docking run 中的 Top-8 pose 仍可各自对 8X6B/9E6Y 两个 post-hoc baseline 打分；但“scoring-baseline agreement”与“docking-receptor agreement”必须分列。当前 47-case package 没有 9E6Y-receptor docking run，因此不能检验这一聚合式的重复性、稳定性或 acceptance gate。最终 formal 64/16 holdout 的两类 receptor run 必须在 docking 前同时冻结（现有 formal 合同证据：`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_DEVELOPMENT_PROTOCOL_ZH.md:533-595`）。

## 9. contact fingerprint 只作不确定性诊断

对每个 pose 保留三类 set-valued fingerprint：

| fingerprint | 概念定义 |
| --- | --- |
| `AG` | VHH-PVRIG antigen contact residue-pair set |
| `O8` | 对 8X6B scoring baseline 的 VHH-PVRL2 occluding residue-pair set |
| `O9` | 对 9E6Y scoring baseline 的 VHH-PVRL2 occluding residue-pair set |

对 AG/O8/O9 分别计算 Jaccard similarity，再做 complete-link clustering：中心 similarity threshold 为 `0.50`，sensitivity threshold 为 `0.40` 和 `0.60`。“complete-link at tau”表示同一 cluster 内所有 pose pair 的 Jaccard 都不低于 `tau`。

可报告：

```text
fingerprint_cluster_count
fingerprint_cluster_entropy
largest_fingerprint_cluster_fraction
single_fingerprint_basin
AG/O8/O9 cluster sensitivity at 0.40/0.50/0.60
```

这些字段只表示 sampling concentration/diversity 和不确定性。禁止用 fingerprint cluster：

- 选 pose 或改变 rank；
- 使用 `/cluster_size` 分母调整 `R_run`；
- 将 single basin 自动解释为高置信度；
- 因为与 success anchor 更相似而加分。

## 10. 预注册 sensitivity grid

生产中心设置唯一且预先冻结：

```text
q_low = 0.20
q_high = 0.50
support_fraction = 0.25
minimum_supporting_poses = 2
```

必须完整报告的 sensitivity grid 为尔卡尔积：

```text
q_low in {0.10, 0.20, 0.30}
q_high in {0.40, 0.50, 0.60}
support_fraction in {0.20, 0.25, 0.33}
minimum_supporting_poses in {2, 3}
```

共 54 组。所有组合必须使用同一输入、同一 family weighting 和同一审计格式一次性输出。不得按 G1/G2 数量、mutant 变弱程度、某个 family 的表现或“看起来合理”选择 best-looking grid。中心设置不因 sensitivity 结果改变；若中心设置失败 acceptance gate，当前 RC 应 FAIL，而不是切换到最好看的网格。

## 11. LOFO family robustness

以 family 为最小留出单位，执行 5 折 leave-one-family-out：

1. 每折只用其他 4 个 family 的 success anchors 拟合 baseline-specific H/O/P cutpoint。
2. 对被留出 family 的 anchor 应用该折阈值，不使用 mutant 或 21+32 development cohort 补数。
3. 每个 family 至少有 1 个 held-out anchor 位于 G1-G3。
4. 五个 family 的 G1-G3 recall 等权平均（macro-family recall）必须 `>=0.80`。
5. 将每个 anchor 在 all-family fit 与其 family-held-out fit 的 tier 比较：至少 `9/11` 的变化不超过 1 级，任何 anchor 都不得变化超过 2 级。

若任一 LOFO 折的 hurdle cutpoint 不可定义，该折与整体 LOFO gate 都 FAIL，不允许回退到 all-family cutpoint。

## 12. hierarchical bootstrap

冻结：

```text
seed = 20260714
B = 2000
resampling unit level 1 = family block
resampling unit level 2 = cases within sampled family
atomic unit kept intact = each case's fixed Top-8 poses
```

每个 bootstrap replicate 都重新拟合 H/O/P baseline-specific cutpoint，并对原 11 个 anchor 输出：

- 每个 raw `L/U` cutpoint 的分布与不可定义比例；
- `R_calibration_run_8x6b_dock` 分布；
- G1-G5 概率和 modal tier probability；
- G1-G3 retention probability；
- baseline gap 与 support 分布。

建议的稳定性门（必须在首次 threshold fit 前作为 RC 的确定规则，不得事后修改）：

```text
at least 9/11 anchors have modal-tier probability >= 0.70
each family has at least one anchor with P(G1-G3) >= 0.70
```

同时必须报告没有通过这两个门的 case/family，不得只报总数。

## 13. mutant paired sensitivity

36 个 mutant/perturbation case 不进入阈值拟合，也不提供 negative label。每个 perturbation 只能与 mutant manifest 中同一 base molecule 的 exact `base_reference` 比较，输出：

```text
delta_R = R_mutant - R_exact_base
delta_F_k = F_k_mutant - F_k_exact_base, k=1..4
delta_N_k = N_k_mutant - N_k_exact_base, k=1..4
delta_tier_strength = strength(mutant) - strength(exact_base)
  where strength(G1..G5) = 4,3,2,1,0
AG/O8/O9 mutant-vs-base Jaccard
fingerprint cluster transition
baseline-gap delta
```

必须保留所有方向：若 mutant 的 score/support/tier 上升，原样保留正 delta，不截断为 0，不因“设计意图是破坏”而翻转或重贴标签。对没有 exact base 闭包的行，配对 sensitivity 为缺失并触发硬失败，不得选择“最像的”其他 anchor。

## 14. failure 、soft flag 和 training eligibility

### 14.1 硬失败

以下情形不生成 label：

- provenance/hash 不闭包；
- pose 不是恰好 Top-8 或 rank 不是 1..8；
- 任一 H/O/P、score、support 非有限数；
- baseline row 缺失/重复；
- PVRL2 occlusion 使用了任何 `HETATM`；
- cutpoint 不可定义或非退化条件失败。

### 14.2 soft flags

必须保留已计算的 score/tier，同时设置 `training_eligible=false`：

```text
THRESHOLD_UNSTABLE
BASELINE_DISCORDANT
DOCKING_RECEPTOR_DISCORDANT
SINGLE_FINGERPRINT_BASIN
HIGH_POSE_DISPERSION
CALIBRATION_OUT_OF_SUPPORT
```

`THRESHOLD_UNSTABLE` 由 LOFO/bootstrap/central-grid 稳定性门触发；`SINGLE_FINGERPRINT_BASIN` 由中心 `tau=0.50` 下单 cluster 触发。其他四个 flag 的数值边界尚未可冻结，必须在第一次规则释放前仅使用 development/calibration 分布预先定义；不得查看 formal holdout 后再定义。

soft flag 不应把有效几何结果伪装成计算缺失；但在解决 flag 前，不得将该行作为 P2 训练监督。

## 15. acceptance gates

| gate | 通过条件 |
| --- | --- |
| pose closure | 47/47 case、376/376 pose、每 case ranks=1..8 |
| metric closure | 752/752 baseline rows，无缺失/重复，所有必需数值 finite |
| ATOM-only | PVRL2 `HETATM used=0`，record inventory 闭包 |
| threshold validity | 每个 baseline x H/O/P 的 zero mass 可报告，positive-part `L>0` 且 `U>L` |
| family balance | 5 family 各占 `1/5` anchor fit 权重，不使用 cluster-size weighting |
| sensitivity grid | 54/54 组合全量输出，中心 grid 不事后更换 |
| LOFO | 每 family 至少 1 个 G1-G3；macro-family recall `>=0.80`；`>=9/11` tier shift `<=1`；无 shift `>2` |
| bootstrap | seed/B/层级单位冻结；`>=9/11` modal probability `>=0.70`；每 family 至少 1 anchor 的 `P(G1-G3)>=0.70` |
| mutant sensitivity | 所有可配对 perturbation 只与 exact base 比较，正负 delta 均保留 |
| claim boundary | 只声称 computational docking geometry calibration |

上述门只能冻结 `R_calibration_run_8x6b_dock` 层面的校准规则。它们不能替代独立 8X6B-dock/9E6Y-dock 的 formal completeness、repeatability 和 dual-receptor `R_gold` 验证。

## 16. 禁止的优化目标和不可复用的旧规则

必须显式禁止：

1. 复用 V1.1 A 类的 `14 / 500 / 100 / 0.15` 硬阈值。
2. 复用旧 B 类的 `300 / 10 / 50` 硬编码规则。
3. 复用旧 class-derived `R_gold` 或将旧 sensitivity class 映射到新 tier。
4. 使用 `/cluster_size`、largest-cluster bonus 或 fingerprint 相似性改写 rank/score。
5. 以 A/A 为唯一成功模式，或将 A/A 以外全部当负类。
6. 最大化 G1/G2 数量、anchor recall、mutant “按预期变弱”比例或 tier 均衡度来选阈值。
7. 从 54 组 sensitivity grid 中挑选结果最好的一组作生产规则。
8. 用 21 matched + 32 Teacher500 决定 success-anchor cutpoint。
9. 查看 formal holdout 结果后修改 cutpoint、support、K、rank weight、flag 或 fingerprint threshold。
10. 把本方法评估为 accuracy、specificity、Kd prediction、binder classification 或 functional blocking prediction。

## 17. 尚未可冻结的项目

以下不得在本文中伪造数值或声称已完成：

- 6 组 baseline x H/O/P 的 raw `L/U` cutpoint；
- 47-case 的 752 行 fixed-Top-8 ATOM-only 连续指标是否已全部闭包；
- LOFO 与 2,000 次 bootstrap 的实际结果；
- `BASELINE_DISCORDANT`、`DOCKING_RECEPTOR_DISCORDANT`、`HIGH_POSE_DISPERSION` 和 `CALIBRATION_OUT_OF_SUPPORT` 的数值触发边界；
- AG/O8/O9 的 canonical residue-key serialization 和输出 schema 哈希；
- 独立 9E6Y-receptor docking 的 run score、receptor gap 和 support；
- 最终 dual-receptor `R_gold` 的 repeatability/acceptance；
- 全新未触碰 formal holdout 的选择、哈希、运行和审计；
- `P2_TRAINING_BLOCKED -> P2_TRAINING_READY` 放行。

若任一项仍未闭包，就必须保留 `IMPLEMENTATION_NOT_COMPLETE` 和 `P2_TRAINING_BLOCKED`。

## 18. 本地证据复核命令

从 `/mnt/d/work/抗体/data` 运行以下只读命令，可复核 47-case pose inventory 和全量 docking receptor config：

```bash
python - <<'PY'
import collections
import json
from pathlib import Path

data_root = Path.cwd()
repo_root = data_root.parent
audit_path = data_root / "experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_calibration_emref_top8_selection_audit.json"
audit = json.loads(audit_path.read_text())
cases = audit["cases"]

io_paths = {repo_root / case["source_io_relpath"] for case in cases}
configs = []
for case in cases:
    cfgs = list((repo_root / case["workdir_relpath"] / "haddock3").glob("*.cfg"))
    assert len(cfgs) == 1, (case["case_id"], cfgs)
    configs.extend(cfgs)

texts = [path.read_text() for path in configs]
print("cases", len(cases))
print("unique_existing_io", len(io_paths), all(path.is_file() for path in io_paths))
print("source_output_count", dict(sorted(collections.Counter(case["source_output_count"] for case in cases).items())))
print("selected_pose_count", sum(case["selected_pose_count"] for case in cases))
print("configs", len(configs))
print("8x6b_receptor_configs", sum('"data/pvrig_8x6b_chainB.pdb"' in text for text in texts))
print("9e6y_receptor_configs", sum("9e6y" in text.lower() for text in texts))
PY
```

已验证输出：

```text
cases 47
unique_existing_io 47 True
source_output_count {9: 4, 10: 43}
selected_pose_count 376
configs 47
8x6b_receptor_configs 47
9e6y_receptor_configs 0
```

## 19. 方法冻结后的实施顺序

```text
1. 建立 376-pose / 752-baseline-row ATOM-only 连续指标表
2. 运行硬闭包审计，任一失败则停止
3. 只用 11 success anchors 拟合 family-balanced baseline-specific H/O/P cutpoint
4. 输出中心规则与全部 54 组 sensitivity grid
5. 运行 LOFO 和 seed=20260714、B=2000 hierarchical bootstrap
6. 对 36 mutant 运行 exact-base paired sensitivity，保留所有增加/减少
7. 冻结 scorer/rules/manifest/reference/hotspot/fingerprint schema 哈希
8. 在 development smoke/regression 中验证，不把 47-case 冒充 formal
9. 冻结全新未触碰 64/16 formal holdout
10. 完成独立 8X6B-dock + 9E6Y-dock formal validation，才可计算和审计 dual-receptor R_gold
```

## 20. 最终预注册声明

```text
The 47-case calibration cohort is development-only.
All 47 cases were docked against the 8X6B receptor only.
8X6B and 9E6Y are post-hoc scoring baselines for those poses.
The current legacy-final sensitivity package cannot fit thresholds.
Success-anchor thresholds are family-balanced and baseline-specific.
Mutants are paired sensitivity controls, never presumed negatives.
Top-8 rank weights are fixed; cluster-size weighting is forbidden.
The 47-case cohort can freeze R_calibration_run_8x6b_dock only.
Dual-receptor R_gold requires independent 8X6B-dock and 9E6Y-dock runs.
No accuracy, specificity, Kd, binding, or functional blocking claim is allowed.
Implementation and formal validation are not complete; P2 training remains blocked.
```
