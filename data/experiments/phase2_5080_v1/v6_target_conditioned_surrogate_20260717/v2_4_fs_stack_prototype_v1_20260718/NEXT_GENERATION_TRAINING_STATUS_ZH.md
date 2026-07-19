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

1. V1.2.1 的 195-job double cross-fit stack 已在 Node1 终态 PASS：
   package=`/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718`，
   runtime=`/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_1_20260718`，
   launcher/runner PID=`891011/891012`，graph SHA256=`2dab5078ad81f3b3c02fc995ce0a7b556e638d905c20d73d5eeebe81b86a0f57`。
   75 inner、15 outer、15 meta 和全部 195 个 job 均 PASS，15/15 meta validation
   通过，exact-min 违反 0，V4-F/test32 access=0。冻结正式结论为
   `DO_NOT_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK`。
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

## 11. V2.5 独立头和 strict meta 实施状态

`V2.5-ORTHO-CONTACT-POSE-STACK` 的两个代码面结构修复已完成：

- `B_CLEAN_TARGET_ATTENTION`：不实例化 contact module，scalar 路径只使用
  attention-conditioned evidence；
- `E_DECOUPLED_CONTACT`：attention/contact 使用独立 pair projection 和 terminal，
  contact 不反向输入 scalar；
- 两者只直接预测 R8/R9，训练使用 FP32 normalized softmin 辅助损失，
  推理时强制 exact-min；
- 数据防火墙继续禁止 M2/126D/ID/candidate Docking pose 进入 neural branch。

实现和真实 1,507 行 adapter 已通过 23 项测试。GPU1 串行 smoke 的初始包
在首个 preoptimizer 真实动态导入 V2.4 adapter 时 fail closed：adapter 的 sibling
`residue_model_v2_4.py` 未加入 `sys.path`。该失败未产生训练结果、未访问
V4-F/test32；旧 auth/runtime 保留为失败证据，修复必须另起 versioned V1.1。

Strict meta/noise 实施也已闭合：

- 挑战者冻结为 D-only、M2+C2、M2+D、M2+D+C2、reliability convex
  和 shallow HistGBDT；
- 执行 adapter 全套 24/24 测试通过；
- C2 inner replay 的冻结 alpha 为 `100/100/100/10/10`，与既有证据完全一致；
- Node1 input-closure watcher PID=`932630`，仅等待 strict V1.2.1 终态，
  并会停在 `PASS_INPUTS_READY_UNAUTHORIZED`，不会擅自读正式指标。

## 12. Inner-only 参数试验结果

GPU1 上完成了 D lane 的单个 `outer0/inner0` 六配置描述性 pilot。它不是
formal outer 证据，只用于决定下一轮应保留哪些 optimizer/loss challenger。

| 配置 | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| 8 epoch, lr=1e-4, wd=.02, Huber=.03 | 0.3167 | **0.02895** | **0.03672** |
| 16 epoch, lr=1e-4, wd=.02, Huber=.03 | 0.3589 | 0.03282 | 0.03986 |
| 16 epoch, lr=5e-5, wd=.02, Huber=.03 | 0.3323 | 0.03022 | 0.03703 |
| 16 epoch, lr=2e-4, wd=.02, Huber=.03 | **0.3692** | 0.02938 | 0.03788 |
| 16 epoch, lr=1e-4, wd=.01, Huber=.02 | 0.3649 | 0.03225 | 0.03935 |
| 16 epoch, lr=1e-4, wd=.03, Huber=.04 | 0.3681 | 0.03119 | 0.03776 |

因此 `16 epoch + lr=2e-4` 可作为 ranking challenger，但其 MAE/RMSE 没有超过
8-epoch baseline。不将该 inner-only 结果直接当作正式配置；下一轮只保留
8-epoch baseline、16-epoch/lr=2e-4 ranking challenger，以及必要时的 wd=.03/Huber=.04
稳定性 challenger，所有选择仍在 inner whole-parent CV 内完成。

## 13. V2.4 strict 和 V2.5 meta 正式结果

V2.4 的 195-job double cross-fit 已完成，它与较早的单层 outer OOF
结论不同：strict meta 后 D 没有保持增量。

| Model | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2 | **0.609401** | **0.032359** | **0.042907** |
| B target/no-contact | 0.610605 | 0.032478 | 0.043203 |
| C marginal | 0.606411 | 0.033710 | 0.044587 |
| D pair | 0.604492 | 0.034518 | 0.045555 |

D 的 5 个冻结 gate 全部失败。B 的 Spearman 只比 M2 高 0.001204，同时
MAE/RMSE 更差，而且 B 在预注册中只是消融，不允许看结果后改选它。D 的
contact meta 权重中位数约 0.00086，2/5 folds 近于零，condition number
2.29到4.23，说明主要是 contact 增量不稳定，不是数值矩阵崩溃。

随后的 V2.5 strict meta 又将 M2、D、C2、A/B-only noise head 和 shallow
HistGBDT 按冻结 whole-parent double cross-fit 组合：

| Model | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2+C2 | 0.617438 | **0.031999** | **0.042374** |
| M2+D | 0.614865 | 0.032784 | 0.043535 |
| M2+D+C2 | **0.620835** | 0.032500 | 0.043061 |
| M2+D+C2+reliability | 0.619943 | 0.032673 | 0.043293 |
| shallow HistGBDT | 0.584851 | 0.032257 | 0.042332 |

`M2+D+C2` 首次超过冻结 Spearman 线 0.619401，但它同时失败
Rdual MAE/RMSE、parent-macro MAE 和有改善 parent 数量等冻结门，因此正式结论仍是
`DO_NOT_PROMOTE`。Reliability 权重没有带来增益；HistGBDT 改善了误差，但排序
显著变差，不能替代线性主头。

这两个终态结果直接支持当前 V2.5 结构修复：不再使用旧 D 的 contact
路径，而是分别训练 clean attention、decoupled contact detached/shared，再与
M2/C2 做严格融合。V2.5 V1.2 的 6 个真实 GPU smoke 已全部 PASS，所有预优化
梯度隔离 gate 均正确，已具备启动正式多折训练的技术条件。

## 14. V2.5 正式 nested 训练与跨 lane 决策冻结

V2.5 V1.3 正式训练已在 Node1 的 GPU `1/2/4/5` 启动：

```text
runtime: /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_runtime_v1_3_20260718
scheduler PID: 999220
job graph SHA256: ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185
jobs: 225 inner GPU + 15 select + 45 outer-refit GPU + 15 ensemble + 1 collect = 301
```

V1.2 在任何训练结果产生前因 `node1_bundle` 路径前缀缺失而 fail closed；V1.3
只修复该路径，没有改变 split、模型、loss、参数搜索或评价规则。独立审查已确认
5x5 whole-parent split 闭合、31 个 parent 外层各留出一次、inner 不含 outer-test
parent、exact-min 和输入防火墙有效，V4-F/test32 access=0。

在 E_SHARED outer 结果产生前，已冻结跨 lane/meta 决策：

```text
primary neural lane: E_DECOUPLED_CONTACT_SHARED
diagnostic only: B_CLEAN_TARGET_ATTENTION, E_DECOUPLED_CONTACT_DETACHED
primary stack: M2 + C2 + E_SHARED scalar + persisted contact_score_R8/R9
contract SHA256: 0329a4749d9874f3bef7bda30d744d57b85b626783df9dc33a7fd931f3f75eb2
```

Contact 分数先在每个 outer-train 的 inner-OOF 行上做 robust scaling，再以强正则、
M2 锚定的约束残差进入 meta；禁止将 raw contact 当成 R 预测或计算
`contact-M2`。B/Detached 即使 outer 指标更漂亮也不能替换 E_SHARED。任一整体、
source、parent 或 paired-parent bootstrap gate 失败时，正式输出必须回退到原冻结 M2。

另一个需要如实解释的细节是：Detached 虽没有 contact loss 到 shared encoder 的直接
autograd 路径，但当前训练对所有可训练参数统一执行 global gradient clipping，因此
contact gradient 仍可能通过全局裁剪系数间接缩放 scalar 更新。当前运行不修改；下一版
必须改成 per-role clipping 或独立 optimizer/backward。

当前正式预测只持久化两维 contact composite。完整 14D pair summary 的 label-free
checkpoint 重放导出器已经实现并通过 7 项测试，但被硬标记为
`FUTURE_VERSION_DIAGNOSTIC_ONLY_NOT_CURRENT_V2_5_SELECTION`，不能事后加入本轮 primary。

## 15. Strict meta evaluator 独立审查与 V1.1 恢复

首版 evaluator V1 在训练终态前的独立审查中发现 8 类合同实现缺口，包括 whole-parent
运行时 gate、KKT 校验、parent-macro 指标、exact-min 容差、PRETRUTH 参数冻结、失败状态、
诊断输出和显式 M2 fallback。旧 watcher PID `1036343` 已在上游未终态时停止，旧包与
301-job 训练图均未修改。

V1.1 已另起版本修复并通过 17 项正常/篡改测试：

```text
local: strict_cross_lane_meta_evaluator_v1_1_20260718
remote package: /data1/qlyu/projects/pvrig_v2_5_strict_cross_lane_meta_package_v1_1_20260718
remote watcher PID: 1059455
status: WAITING_V1_3_TERMINAL
package manifest SHA256: f3b3e9378d51f6af90189d4b590c3d154aed5ca0dd528ebaa552e23472dda890
```

V1.1 会先冻结 PRETRUTH prediction、meta 参数、contact scaler 和全部哈希，再允许读取
outer truth 计算指标；真实性/hash 破坏继续 fail closed，合法但无增量或 feature closure
失败则发布显式 exact-M2 selected-production fallback。V4-F/test32 access=0。

## 16. Repeat-seed noise ceiling 与 V2.6 规划

已闭合 590 个独立候选的重复 seed 诊断：V4-D OPEN_TRAIN 226 条，V4-H repeat 364 条，
合计 3,062 个 receptor-seed scalar。候选级 terminal teacher 重算最大差 `<5e-10`。

| 来源 | Rdual seed-pair Spearman | Rdual ICC(1,1) | 解释 |
|---|---:|---:|---|
| V4-D 非自适应 | 0.672--0.725 | 0.702 | 可信的全局噪声基准 |
| V4-H adaptive | 0.334--0.506 | 0.213 | 分数范围压缩，不能外推全库 |

V4-D 三 seed 均值的经典相关上限约为 `0.936`，因此当前约 `0.62` 的 surrogate 仍有明显
模型改进空间。V4-D 完整三 seed 的 Rdual MAD 冻结得到：

```text
delta_noise = clip(median(MAD_seed)*1.4826*sqrt(2), 0.01, 0.03)
            = 0.019614956149
```

V2.6 已规划为 `ROLE-ISOLATED / RANK-CALIBRATED`：per-role optimizer/clipping、contact
独立 RNG、20-step B/E 参数轨迹等价 gate、shared-contact gradient budget、Huber+softmin+
noise-aware within-parent PairLogit、fold-local正斜率校准和 deterministic parent-pair epoch
cache。结构编码器 challenger 优先于 ESM2-3B；只有 target/contact 消融通过且与 noise ceiling
仍相差至少 0.05 时才启动 3B。V2.6 当前仅是 nonlaunching prereg skeleton，不会与正在运行
的 V2.5 混用。
