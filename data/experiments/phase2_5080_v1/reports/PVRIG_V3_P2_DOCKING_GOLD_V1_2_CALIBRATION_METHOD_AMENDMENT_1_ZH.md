# PVRIG V3-P2 Docking Gold V1.2 校准方法修订 1

- 修订日期：2026-07-14（Asia/Shanghai）
- 适用协议：`DG_A_PVRIG_V1_2_DEV`
- 原方法文档：`PVRIG_V3_P2_DOCKING_GOLD_V1_2_CALIBRATION_METHOD_ZH.md`
- 原方法文档 SHA256：`ed1651b11eb865fdfa30cce6b69da4cdebc13f4982c53915cfa2bd838c4bbb25`
- 修订类型：测量不变性、来源闭包和输出 schema 修正；不改动预注册阈值分位数、support 门或 acceptance gate
- P2 状态：`P2_TRAINING_BLOCKED`

## 1. 修订原因

原方法文档把 `H=hotspot_weight_fraction` 写成 8X6B/9E6Y 两个 baseline 分别拟合的通道。
全量 fixed-Top-8 预检发现，47-case cohort 的两个 baseline 行实际上是对同一个 8X6B-docked pose 做两次 post-hoc 参考评分。PVRIG-VHH 内部接触在刚体变换下必须不变，但两次对齐后的三位小数 PDB 重写会使 4.5 A 边界接触翻转：

```text
5 / 376 poses: PVRIG-VHH contact-pair count 跨 baseline 不一致
2 / 376 poses: PVRIG contact-residue count 不一致
1 / 376 poses: hotspot overlap 14 -> 13
1 / 376 poses: H 0.5982142857 -> 0.5535714286
```

这是坐标量化误差，不是两个 PVRIG-PVRL2 baseline 的生物学差异。如果继续分别拟合 `H_8` 和 `H_9`，会把数值误差写入 Gold 规则。

## 2. Canonical internal-contact 通道

从本修订开始，每个 source pose 只计算一次 PVRIG-VHH 内部接触：

```text
source = raw 4_emref pose
numbering = source-docking-receptor numbering
47-case source docking receptor = 8X6B
hotspot column = pdb_8x6b_ref
```

以下字段在同一 pose 的 8X6B/9E6Y post-hoc baseline 行中必须完全相同：

```text
pvrig_vhh_contact_pair_count
pvrig_contact_residue_count
vhh_contact_residue_count
cdr_contact_residue_count
hotspot_count
hotspot_overlap_count
hotspot_overlap_fraction
hotspot_weight_total
hotspot_weight_overlap
hotspot_weight_fraction
pvrig_vhh_contacts
hotspot_overlaps
canonical_internal_score_payload_sha256
```

任一字段不一致都是硬失败，不得取平均、取较大值或用 tolerance 掩盖。

PVRL2 遮挡仍然是 baseline-specific：

```text
O_8, P_8 <- 8X6B PVRL2 reference
O_9, P_9 <- 9E6Y PVRL2 reference
H       <- shared canonical internal-contact channel
```

## 3. 阈值通道数修正

中心规则现在共有 5 个阈值通道，而不是 6 个：

```text
H_canonical
8X6B: O, P
9E6Y: O, P
```

对每个通道仍使用原预注册规则：

```text
L = family-balanced positive-part q20
U = family-balanced positive-part q50
required: L > 0 and U > L
```

`H_canonical` 只计权一次，不因它在两个 baseline 行中重复而双倍计权。两个 `S_pose_baseline` 共用同一个 `mu_H`：

```text
S_8 = sqrt(mu_O8 * (mu_H + mu_P8) / 2)
S_9 = sqrt(mu_O9 * (mu_H + mu_P9) / 2)
```

## 4. O 的单位和存储

`O` 的原始数据是 `total_occluding_residue_pair_count`。拟合和 membership 在 `log1p(O_raw)` 空间执行。规则文件必须同时保存：

```text
L_raw_count
U_raw_count
L_log1p
U_log1p
transform = log1p
```

下游消费者只能按 `transform` 字段执行一次变换，不得对已是 log 单位的阈值再取 `log1p`。

## 5. Conditional-null 语义

`*_min_distance_a` 是“4.5 A 接触集合中的最小距离”，当某 region 没有任何 occluding contact 时未定义。此时允许 JSON `null` / CSV 空单元格，但必须同时满足：

```text
occluding_atom_contact_count = 0
occluding_residue_pair_count = 0
vhh_residue_count = 0
pvrl2_residue_count = 0
```

其他任何数值空值、NaN 或 Inf 都是硬失败。不得把未定义距离改写为 0 或无穷大。

## 6. Processor 外部冻结锨

Processor 不能用自己生成的布尔字段证明自己已冻结。因此 V1.2 增加独立 release manifest：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_processor_release_manifest.json`

该 manifest 必须同时绑定：

```text
processor path + SHA256
processor test path + SHA256
selector CSV + audit + selector implementation
positive + mutant manifests
aligner + V1.2 scorers + scoring helper
hotspot + numbering reconciliation
8X6B + 9E6Y references
```

只有 canonical path、processor/test hash 和 13 个外部锨全部匹配时，`pose_rule_threshold_freeze_eligible` 才能为 `true`。

## 7. Bootstrap 输出基数

共享 H 后，B=2000 的 threshold 输出应为：

```text
2000 replicates
x 5 channels
x 2 cutpoints
= 20,000 threshold rows
```

另外必须对原 11 个 success anchors 在每个 replicate 阈值下重评分：

```text
2000 replicates x 11 anchors = 22,000 anchor-evaluation rows
```

若某 replicate 出现 `U<=L` 或其他阈值不可定义，必须保留 replicate 失败状态并计入 undefined rate，不得将 `U==L` 解释为阶跃 membership。

## 8. 不改动的预注册项

本修订不改动：

```text
q_low = 0.20
q_high = 0.50
support_fraction = 0.25
minimum_supporting_poses = 2
rank weight = normalized 1/log2(rank+1)
LOFO gates
bootstrap seed = 20260714
bootstrap B = 2000
bootstrap modal/retention gates
54-row robustness grid
mutant-only exact-base pairing
```

特别禁止因为看到 bootstrap、LOFO、mutant 或 tier 分布后修改这些值。中心规则如果未通过 acceptance gate，当前 RC 必须 FAIL，而不是从 grid 中选一行替换。

## 9. 声明边界

47-case cohort 仍然只能校准：

```text
pose-level geometry strata
post-hoc baseline-specific O/P
shared canonical H
R_calibration_run_8x6b_dock
```

它不能冻结或验证：

```text
independent 9E6Y-dock behavior
dual-receptor R_gold
formal holdout repeatability
experimental binding / affinity / blocking
P2 training release
```

在 family-aware 校准、8-run smoke、52-run regression、rebuilt Pilot64 和全新 formal holdout 依次通过前，状态必须保持：

```text
FAIL_DOCKING_GOLD_NOT_VALIDATED
P2_TRAINING_BLOCKED
```
