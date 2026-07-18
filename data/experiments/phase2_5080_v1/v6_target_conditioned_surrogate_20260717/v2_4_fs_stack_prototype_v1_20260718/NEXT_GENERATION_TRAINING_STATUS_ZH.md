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

## 5. A/B 开放开发结果

Node1 GPU1/2 已完成 A/B 的 5-fold whole-parent OOF，每个 lane 都覆盖 1,507 条、
31 parents。

| Model | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2 exact-min Ridge | **0.6094** | **0.03236** | **0.04291** |
| A: VHH-only neural | 0.4709 | 0.03755 | 0.04801 |
| B: target graph, no contact supervision | 0.4102 | 0.03960 | 0.05024 |

当前结论：

1. 仅增加固定 PVRIG graph 并不会自动提供有效信号，B 反而比 A 低 0.0607。
2. Neural 分支目前明显弱于 M2，说明不能把“更大 PLM/更深 attention”当作主要答案。
3. 同行拟合的乐观 non-negative meta 诊断中，B+M2 也只达到 0.6139，相对
   M2 仅 +0.0045，且 unsupervised contact-score 的两个系数均收缩为 0。该诊断是
   same-row optimistic ceiling，不可用作 promotion 结果。
4. 因此 V2.4 能否有增量，现在主要取决于 adaptive contact-supervised C/D，而不是 B。

持久证据：`diagnostics/PRELIMINARY_AB_OUTER_EVALUATION_V1.json`。

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

A 明确排除于 stack；B/C/D 在 GPU2/4/5 执行。当前 job graph 保持
`PENDING_POSTCALIBRATION_FREEZE`，不会提前启动。

## 8. 正在运行和下一步

1. 物化并冻结独立 V2 multi-batch trainer/deployment manifest。
2. 运行 8 个确定性 batch 的 broad-grid pre-step calibration。
3. 选择规则为 median contact-gradient fraction 在 5%到15%，且任一 batch <=30%。
4. 生成 V2 ready manifest + implementation freeze，再跑 four-lane tiny smoke。
5. 执行 C/D base OOF 和 195-job strict double cross-fit stack。
6. 执行 target/contact ablation，包括 hotspot shuffle、interface swap、conformer swap、
   target embedding permutation 和 contact-label shuffle。
7. 与 M2 0.6094 比较；若 strict stack 不能提高至至少约 0.6194 并同时满足
   MAE/source/parent 门，则写 `DO_NOT_PROMOTE`，不打开 V4-F。

## 9. 对更下一代 V2.5 的决策

如果 C/D 仍无明显增量，优先实施廉价 coarse-pose scan，而不是先把 ESM2-650M
换成 3B：

```text
VHH CDR surface point cloud + PVRIG interface surface
→ low-resolution rigid-body rotation/translation scan
→ Top-K shape/electrostatic/hotspot/angle features
→ 与 M2 + neural/contact 做严格 cross-fit 融合
```

当前最缺失的是 approach angle，而不是更长的 sequence embedding。

首轮 CPU pilot 已运行 20 条真实 V4-H 单体：每个受体 300 个低分辨率位姿，
平均 0.218 秒/候选，内存约 35 MB，刚体变换重算最大误差 `4.44e-16`。
19 条有开放 teacher 的小样本中，某些 orientation/dual-pose 特征与标签的
|Spearman| 约 0.33到0.52；这只是不可晋级的 signal check，不能用来选特征。
正式版会在 label-free 规则下把 36D pilot 压缩为 8到12 个对称/dual summary，
然后做 whole-parent OOF 增量评估。
