# PVRIG 下一代训练评估与执行状态

## 1. 目标和证据边界

当前目标是：

```text
VHH sequence + label-free monomer + fixed 8X6B/9E6Y PVRIG graphs
→ 近似独立双受体 Docking 的 R8/R9
→ Rdual = min(R8, R9)
→ 大库前筛和主动学习
```

这些输出只是 computational Docking geometry surrogate，不是结合概率、Kd、
实验阻断概率或 Docking Gold。V4-F/test32 仍保持 sealed。

## 2. 已完成的结构修正

### Attention/contact 分头

模型共享 rank-64 pair representation，但最后的 attention terminal 和 contact
terminal 已独立。Attention 使用双向 softmax 路由；contact 使用 sigmoid 及独立
receptor bias。BF16 的 entropy 统计在 FP32 计算。

### Exact-min 双受体输出

模型只直接预测 `R8/R9`，推理和导出时强制：

```text
Rdual = min(R8, R9)
```

不再给 `Rdual` 一个可以违反定义的独立自由输出。

### Orthogonal evidence branches

- M2：126D label-free monomer features 的 whole-parent Ridge。
- Neural：冻结 ESM2-650M residue states + VHH graph + 固定 PVRIG graphs。
- Neural forward 禁止读取 M2、126D、candidate/parent/source ID 和 Docking pose。
- M2/neural/contact 只在最后 meta-head 处融合。

## 3. 开放监督数据

| Source | Candidates | Parents | 用途 |
|---|---:|---:|---|
| V4-D | 226 | 20 | multi-seed scalar/contact teacher |
| V4-H | 1,281 | 11 | adaptive scalar + adaptive multi-seed residue/pair contact |
| 合计 | 1,507 | 31 | open whole-parent development |

Reliability tiers：A=349、B=241、C=917。V4-H 的 39 条技术不完整项不进入
1,507 行 scalar 监督。

V4-H contact 提取已于 Node23 完成：

- 1,281 valid candidates，39 technical incomplete；
- 3,536 个配对双受体 seed jobs；
- 317,518 residue rows，528,328 residue-pair rows；
- Top-8 pose，4.5 A contact cutoff，双受体仅取成功 seed 交集；
- 原始 receipt SHA256：`ef245ace9c7e2f8c6dbe15893c67689084d00e7720a1855fb88f900fe29b79be`。

V4-D 226 + V4-H 1,281 的 trainer-ready 双源表已物化并通过独立验证：

- marginal：186,328 rows / 1,507 candidates；
- pair：661,202 rows / 1,507 candidates；
- pair groups：3,014，空组 0；
- failed-seed imputation 0，legacy Stage1 rows 0；
- input contract SHA256：`3c7b5b2148494e203ddbf17871ab12aca2d725e8e07f2e8e97074065f55a2382`。

## 4. 真实 Node1 预校准

原预注册 contact-loss grid `1e-4..1e-2` 在 GPU4/5 实测无一点进入目标
contact-gradient fraction `5%..20%`，因此 fail closed：

- optimizer step = 0；
- prediction metrics access = 0；
- V4-F access = 0；
- 没有 calibration receipt、implementation freeze 或 formal C/D 训练。

宽网格诊断估计 5% 梯度占比约需 C=1.45、D=0.95。因此 adaptive-contact
protocol V2 预注册宽网格：

```text
[0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 7.5, 10]
```

该诊断只反映 loss scale，不是模型性能结果。

## 5. 四路开放开发正式结果

V2.2.2 已完成 A/B/C/D 的 5-fold whole-parent OOF，每个 lane 都覆盖 1,507 条、
31 parents。早期 `diagnostics/PRELIMINARY_AB_OUTER_EVALUATION_V1.json` 只保留为
preliminary development evidence，下面以正式 collector V1.1 的闭合结果为准。

| Model | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2 exact-min Ridge | **0.6094** | **0.03236** | **0.04291** |
| A: VHH-only neural | 0.3968 | 0.04250 | 0.05342 |
| B: target graph, no contact supervision | 0.1546 | 0.04714 | 0.05915 |
| C: marginal-contact supervision | 0.4897 | 0.03726 | 0.04847 |
| D: pair-contact supervision | **0.5675** | **0.03712** | **0.04813** |

当前结论：

1. 仅增加固定 PVRIG graph 不会自动提供有效信号，B 比 A 低 0.2422。
2. B 也不是完全干净的 attention-only 消融：无 contact BCE 时，未校准 contact logits
   仍进入 marginal pooling、pair summary 和 scalar head。下一版必须把 contact-derived
   path 从 clean B 的 scalar head 完全断开。
3. Contact 监督提供真实增量：C 相对 B `+0.3350`，D 相对 C `+0.0778`。
4. D 仍弱于 M2，因此应进入严格 OOF stacking，不应直接替换 M2。

正式持久证据：
`deployment/prepared/v2_2_2_post_outer_watcher_v1_1_terminal_evidence_20260718/`。

## 6. 架构前诊断的新结果

`diagnostics/PREARCHITECTURE_LIMITS_DIAGNOSTIC_V1.json` 已对 1,507 条开放开发数据完成两项诊断。

### 旧 residual 上限确实过紧

相对 M2 OOF，R8/R9 分别有 61.8%/62.4% 的样本需要的真值 residual
绝对值大于 0.02。所以旧 V2.3 的 `M2 + 0.02*tanh(residual)` 确实存在
明显容量上限。这也支持 V2.4 改为正交的 direct R8/R9 predictor，而不是继续
扩大 residual cap。

该 oracle 使用真值，只是容量上界，不是可训练性能。

### parent shortcut 是主要风险

描述性 eta-squared 显示 parent 分组单独解释约：

- R8：33.9%；
- R9：37.0%；
- Rdual：37.6%。

而全局 patch 和 design mode 各自的解释率均低于 0.04%。这不是因果方差分解，
但足以说明 random-row split 会严重高估结果，whole-parent OOF、parent-only
baseline 和 parent-cluster bootstrap 必须保留。

Tier C 的 uncertainty 大多为 0 只因为它们仅有一个 seed，不代表高可靠。
因此不使用 `1/(sigma^2+epsilon)` 让单 seed 样本获得最大权重。

## 7. 已完成的严格 stacking 框架

已实现 whole-parent double cross-fitting，不会把同一批 OOF 行既当 meta 训练又当
最终评价：

```text
75 inner GPU jobs
+ 15 outer-refit GPU jobs
+ 105 CPU assemble/validate/meta jobs
= 195 jobs
```

A 明确排除于 stack；B/C/D 使用 GPU2/4/5。Post-calibration freeze、四路 outer OOF
和 collector V1.1 已全部闭合。Strict package 的 split training、contact 和 VHH graph
输入经过三次 fail-closed pre-optimizer 修复后，V1.2.1 已通过真实三 lane smoke 并正式启动。

## 8. 正在运行和下一步

V2.2.2 已完成不可变冻结和四卡 tiny smoke：

- prefreeze manifest SHA256：`bbef3a0d4dc43f09ade77538b489b877945c59d4da78767f43febc463f2887d9`；
- calibration receipt SHA256：`ccd531b0c7d71665f285b1c438276907897481cc1faa923e9e795bbb00ecbc9a`；
- implementation freeze SHA256：`d7c4975313c249e72e2490c85e545ae2ba8d03b0fd90d8b85cd82c23194f76fc`；
- 冻结 contact weights：C=`1.5/0`，D=`1.0/0.5`；
- tiny smoke A/B/C/D 全部 PASS，实际命令权重和 trainer claim 均逐条校验；
- optimizer-step 前校准期间 prediction metrics/test32 访问均为 0。

正式 four-lane outer development 已于 2026-07-18 完成：

```text
Node1 launcher PID: 798802
GPU1: A_VHH_ONLY
GPU2: B_TARGET_NO_CONTACT
GPU4: C_SPLIT_MARGINAL
GPU5: D_SPLIT_PAIR
5 whole-parent folds/lane, 8 fixed epochs/fold
```

20 个 base outer jobs、每 lane 1,507 行、31 parents、exact-min、parent/source/hash
闭包均通过，V4-F/test32 access=0。后续依次为：

1. V1.2.1 的 195-job double cross-fit stack 已在 Node1 启动：
   package=`/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718`，
   runtime=`/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_1_20260718`，
   launcher/runner PID=`891011/891012`，graph SHA256=`2dab5078ad81f3b3c02fc995ce0a7b556e638d905c20d73d5eeebe81b86a0f57`。
   首批 outer0/inner0 的 B/C/D 三个 `RESULT.json` 已成功生成，随后已进入 inner1。
2. 物化 C/D OOF 证据并执行 target/contact ablation：hotspot shuffle、interface swap、
   conformer swap、target embedding permutation、contact-label shuffle。
3. 将 V2.5 C2 粗姿态只作为
   fold-specific base prediction 增加到 challenger，不直接混合 PCA latent。
4. 与 M2 0.6094 比较；若 strict stack 不能提高至至少约 0.6194 并同时满足
   MAE/source/parent 门，则写 `DO_NOT_PROMOTE`，不打开 V4-F。

## 9. V2.5 coarse-pose 正式开放开发结果

如果 C/D 仍无明显增量，优先实施廉价 coarse-pose scan，而不是先把 ESM2-650M
换成 3B：

```text
VHH CDR surface point cloud + PVRIG interface surface
→ low-resolution rigid-body rotation/translation scan
→ Top-K shape/electrostatic/hotspot/angle features
→ 与 M2 + neural/contact 做严格 cross-fit 融合
```

当前最缺失的是 approach angle，而不是更长的 sequence embedding。现在已不只是
20 条 pilot，而是完成了1,507 条的全量 label-free 特征物化和正式 whole-parent OOF：

- 36D raw 和 12D symmetric 特征均全 finite；
- 平均 0.2345 秒/候选，全量 wall time 393.23 秒；
- 刚体旋转不变性误差 `<=1.50e-14`；
- 候选 Docking pose 输入=0，test32/V4-F 访问=0；
- C1 为 symmetric12D Ridge，C2 为 outer/inner-parent 内拟合的 32D→PCA8→Ridge；
- 两者都只直接预测 R8/R9，dual 为 exact min。

| Model | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| C1 symmetric12D Ridge | 0.5646 | 0.03250 | 0.04211 |
| C2 inner-train PCA8 Ridge | 0.5832 | 0.03236 | 0.04201 |
| frozen M2 comparator | **0.6094** | **0.03236** | 0.04291 |

因此 coarse-pose 单独分支的正式结论是 `DO_NOT_PROMOTE_V2_5_COARSE_POSE`。但 C2 显著优于
无特征基线，且 V4-D 子集 Rdual Spearman 为 0.6587，所以它仍适合作为与 M2/contact
不同的正交证据分支，通过严格 double cross-fitting 后只用 fold-specific base prediction 参与 stack。

这一点已用独立的 `M2 + C2` double-cross-fit stack 实测：

| Model | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| frozen M2 | 0.609401 | 0.032359 | 0.042907 |
| M2 + C2 strict stack | **0.617438** | **0.031999** | **0.042374** |

相对 M2，Spearman `+0.008037`，MAE/RMSE、两个 source MAE 和 parent-macro MAE 都改善。但预注册
门槛是 `>=0.619401`，实际仍低 0.001963，所以结论是 `DO_NOT_PROMOTE_M2_C2_STACK`，不事后
修改正则或门槛。五个 outer folds 对 C2 的共享权重约为 0.11到0.21，说明其增量较小但跨 fold
稳定，值得作为最终 M2+contact+coarse 的第三正交分支。

## 10. 下一代冻结架构决策

建议下一代命名为 `V2.5-ORTHO-CONTACT-POSE-STACK`，不再简单加深 D 分支：

```text
M2: 126D monomer Ridge -----------\
contact neural: ESM2+graphs -------+--> strict inner-OOF linear stack --> R8/R9 --> exact min
coarse pose: label-free scan -------/
noise head: repeated-seed A/B -----> uncertainty / capped reliability
```

主 meta-head 仍应是强正则的非负线性/ElasticNet，不把 128D latent 直接交给 GBDT。由于只有
31 个 parent clusters，shallow GBDT/LightGBM 只能是 challenger，并限制 depth 2到3、较大 min leaf、
少量树和强 L2。

下一批 Docking 不应再只选首 seed 高分项，而应冻结高/中/低分随机 sentinel，平衡 parent、
patch 和 design mode，全部补第二/第三 seed。当前重复子集中 A/B 的 seed-dispersion 中位数
约为 0.0404/0.0247，而 Tier C 的零方差主要是单 seed 不可估，因此不得用未校正的
`1/(sigma^2+epsilon)` 让 Tier C 获得最大权重。应先仅用 A/B 训练方差头，再对 C 输出
cross-fitted 预测不确定性，并对 reliability weight 设上限。

如果 C/D + M2 + coarse-pose 的 strict stack 仍不超过冻结 promotion gate，再测试抗体专用 PLM
或 ESM2-3B 的冻结 embedding challenger；不应在没有 approach-angle/contact 增量证据时先解冻大模型。
