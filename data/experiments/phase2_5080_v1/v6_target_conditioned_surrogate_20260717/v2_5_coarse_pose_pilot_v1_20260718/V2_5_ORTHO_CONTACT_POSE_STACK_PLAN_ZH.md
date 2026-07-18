# V2.5-ORTHO-CONTACT-POSE-STACK 下一代训练方案

## 1. 目标与证据边界

目标保持为：

```text
VHH 序列 + label-free VHH 单体结构 + 固定 PVRIG 双构象
→ 逼近独立 8X6B/9E6Y Docking 的连续几何分数
→ 直接预测 R8、R9
→ 推理时 Rdual = min(R8, R9)
```

输出是 computational Docking geometry surrogate，不是结合概率、Kd、实验阻断概率、Docking Gold 或提交真值。V4-F/test32 在预测冻结前保持 sealed。

## 2. 当前正式证据

开放训练集共 1,507 条、31 个 whole-parent clusters：

- V4-D 多 seed：226 条；
- V4-H adaptive Stage 1：1,281 条；
- contact reliability Tier A/B/C：349/241/917。

V2.4 四路 whole-parent outer OOF：

| 分支 | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2 126D Ridge | 0.609401 | 0.032359 | 0.042907 |
| A VHH-only neural | 0.396806 | 0.042498 | 0.053424 |
| B target/no-contact | 0.154630 | 0.047137 | 0.059148 |
| C marginal-contact | 0.489678 | 0.037257 | 0.048471 |
| D pair-contact | 0.567502 | 0.037117 | 0.048127 |

关键结论：

1. M2 仍是最强单分支；单体结构和传统结构/QC 特征在当前数据量下非常有效。
2. contact 监督不是装饰：C 相对 B 提升 0.3350，D 相对 C 再提升 0.0778。
3. D 仍未超过 M2，因此下一步应做正交 stacking，不应以 D 替换 M2。
4. B 不是完全干净的 target-only 消融：它虽然不使用 contact BCE，但未监督的 contact logits 仍进入 marginal pooling、pair summary 和 scalar head。下一版必须新增真正的 attention-only lane。
5. D 的主要 receptor 短板是 R8：R8/R9 Spearman 约为 0.4472/0.5865，不能只盯 Rdual。
6. V4-D 与 V4-H 的 parent 集不重叠，source、parent、seed reliability 和 adaptive selection 存在混杂；source-stratified 指标必须一直保留。

粗姿势分支 C2 的 whole-parent OOF 为 0.583180；严格双层 M2+C2 达到 0.617438，相对 M2 提升 0.008037，但未达到预注册的 0.619401 promotion gate。它是小而稳定的正交证据，不是 standalone replacement。

## 3. 已确认应保留的结构修正

### 3.1 Attention 与 contact terminal 分离

共享低秩 pair representation，但使用：

```text
shared VHH/target factors
├── attention terminal + receptor temperature
└── contact terminal + receptor calibration bias
```

Attention 负责相对路由，contact 负责接触判别。不得重新共用最后一个 scalar logit。

但当前 balanced BCE 会在 candidate/receptor 内重新平衡正负质量，因此 sigmoid 输出应先称
`contact_score`，不能直接解释为真实 contact probability。若需要概率，必须在每个 inner-train
内做 prevalence-preserving temperature/Platt calibration，再应用到对应 outer-test。

### 3.2 只直接预测 R8/R9

推理时必须：

```text
Rdual = exact_min(R8, R9)
```

训练保留 R8/R9 receptor loss，并比较两种预冻结方案：

- exact-min auxiliary；
- fixed-tau softmin auxiliary。

tau 只能在 inner whole-parent CV 中选择；outer-test 不得参与。若 softmin 没有稳定增益，保留 exact-min，避免增加自由度。

## 4. 下一代正交架构

```text
M2 branch
126D label-free monomer/QC features
→ cross-fit Ridge
→ M2_R8 / M2_R9

Attention neural branch
frozen residue ESM2-650M
+ AA/CDR/position/confidence
+ VHH invariant graph
+ fixed 8X6B/9E6Y graphs
→ attention-conditioned interaction
→ neural_R8 / neural_R9
→ uncertainty

Contact evidence branch
shared residue/graph encoders
→ independent contact terminal
→ hotspot/interface/CDR/entropy summaries
→ inner-fold Ridge/calibration
→ contact_R8 / contact_R9

Coarse-pose branch
VHH CDR surface + PVRIG interface surface
→ low-resolution rigid-body scan
→ C2_R8 / C2_R9 + pose summaries

严格 inner-OOF evidence
→ strongly regularized meta-head
→ stacked_R8 / stacked_R9
→ exact-min stacked_Rdual
```

硬隔离：

- neural branch 不读取原始 126D M2 特征或 M2 prediction；
- M2 不读取 neural/contact/coarse-pose 特征；
- 三路仅在二级 cross-fit meta-head 汇合；
- 禁止 parent/candidate/campaign ID；
- 禁止 candidate Docking pose-derived 输入；
- 禁止把原始 128D 或更高维 latent 直接交给 GBDT。

## 5. 神经分支 V2.5 的必要修正

### 5.1 干净消融定义

固定五路：

1. `A_VHH_ONLY`：无 target graph、无 contact；
2. `B_TARGET_ATTENTION_ONLY`：只允许 attention-conditioned pooling，contact terminal、contact summary 和 contact-derived weights 从 scalar path 完全断开；
3. `C_MARGINAL_CONTACT`：加入 marginal supervision；
4. `D_PAIR_CONTACT`：加入 pair supervision；
5. `E_D_NO_CONTACT_TO_SCALAR`：contact 只作为显式 meta evidence，不反向进入 scalar head，用于测量纠缠是否伤害主回归。

### 5.2 低维显式证据输出

Primary 二级模型先只接收约 8--12 维：

- M2_R8/R9；
- neural_R8/R9；
- contact_R8/R9；
- C2_R8/R9；
- neural seed std_R8/R9（仅在三 seed 版本加入）。

扩展 challenger 最多接收约 20--40 维：

- M2_R8/R9/dual；
- neural_R8/R9/dual；
- C2_R8/R9/dual；
- 8X6B/9E6Y hotspot mass；
- interface specificity；
- CDR1/2/3 contact mass；
- contact entropy；
- dual hotspot minimum、conformer gap；
- M2-neural、M2-C2、neural-C2 disagreement；
- predicted uncertainty；
- CDR3 length、monomer confidence 和少量预注册 developability 字段。

Primary meta 使用 M2 fallback 的凸 residual stack：

```text
pred_t = M2_t
       + wN * (Neural_t - M2_t)
       + wC * (Contact_t - M2_t)
       + wP * (C2_t - M2_t)

wN,wC,wP >= 0
wN+wC+wP <= 1
```

这样任何新增分支无增量时都能收缩回 M2，避免自由 intercept 和大量标准化系数在 31 个 parent 上过拟合。

### 5.3 不确定性和噪声建模

只使用有真实重复 seed 的 Tier A/B 学习：

```text
Var(R8), Var(R9), P(seed disagreement)
```

Tier C 的“缺少重复”不得解释为零方差。可靠性权重使用 capped inverse variance：

```text
w = clip(1 / (sigma^2 + epsilon), w_min, w_max)
```

上限、下限和 epsilon 在 formal outer evaluation 前冻结。主报告同时给出未加权指标，防止 reliability weighting 掩盖坏分区。

## 6. 监督分层

| 监督 | Tier A 349 | Tier B 241 | Tier C 917 |
|---|---:|---:|---:|
| R8/R9 scalar | 主监督 | 主监督 | 主监督 |
| marginal contact | 主监督 | 次监督 | 低权重/一致性 |
| full pair contact | 主监督 | 次监督 | 默认关闭 |
| noise head | 可用 | 可用 | 不作真值 |

V4-D/V4-H 固定源权重不再是唯一权重；它与 candidate-level capped reliability 分开报告和消融。

## 7. Meta-head 与机器学习 challenger

严格 outer/inner 双层 cross-fitting：

```text
outer-train parents
→ inner whole-parent OOF base features
→ fit meta-head
→ refit base models on all outer-train
→ score untouched outer-test parents
```

优先顺序：

1. 非负线性 shared-slope stack；
2. ElasticNet；
3. shallow HistGradientBoosting/LightGBM challenger：depth 2--3、large min leaf、少量树、强正则；
4. within-parent PairLogit/LambdaMART 只作为辅助排序，不替代连续 R8/R9 回归。

所有 meta 超参数只在 inner whole-parent CV 选择。不能在全体 outer-OOF 行上拟合后又用同一批行报告性能。

## 8. 优化器和训练参数搜索

当前 V2.4 使用 frozen ESM2-650M、AdamW、lr=1e-4、weight decay=0.02、8 epochs、dropout=0.25、SmoothL1 beta=0.03、无 scheduler。它是固定开发基线，不代表完成了充分调参。

下一版仅做小型、预注册、inner-CV 参数搜索：

- head/GNN learning rate：`5e-5, 1e-4, 2e-4`；
- weight decay：`0.01, 0.03`；
- SmoothL1 beta：`0.02, 0.04`；
- contact loss 总权重：当前值的 `0.5x, 1.0x`；
- fixed warmup 5% + cosine 与无 scheduler 二选一；
- 8/16 epochs，用 inner parent validation 选择，禁止 outer early stopping。

先冻结 PLM。只有正交 contact+pose stack 已证明增益后，才测试解冻 ESM2 最上 1--2 层，学习率为 head 的 1/10--1/20。ESM2-3B/ESM-C 不是第一优先级，因为当前最缺的是 approach angle 和可靠标签，而不是更大的 sequence encoder。

## 9. 必做诊断与因果消融

已经完成：

- oracle clipped residual / residual saturation：旧 ±0.02 cap 确认是瓶颈；
- parent variance：parent 可解释约 34--38%，必须 whole-parent CV。

下一步：

1. seed noise ceiling 和 test-retest reliability；
2. high/mid/low score 条件方差；
3. clean `B_TARGET_ATTENTION_ONLY`；
4. hotspot mask shuffle；
5. interface/off-interface swap；
6. 8X6B/9E6Y conformer swap；
7. target encoder state permutation；
8. contact-label donor shuffle 并重训 C/D；
9. parent-only、CDR3-only、M2-only baselines。

若 target/contact 操作不使模型稳定退化，则不能声称模型真正使用了 PVRIG 位点信息。

## 10. 新 Docking 数据设计

下一批不能只对首 seed 高分候选追加 seed。固定增加约 120--180 条 sentinel：

- 高/中/低首 seed 分数各约三分之一；
- 覆盖不同 parent、patch、design mode、CDR3 长度；
- 无论首 seed 结果如何，统一补足第二、第三 seed；
- sentinel 选择和哈希在运行前冻结。

它们用于估计 measurement noise，不把多个 seed 当成多个独立生物学样本。

## 11. 执行顺序

### Phase 0：闭合当前 V2.4

1. 正式收集四路 outer OOF；
2. 执行 75 inner GPU + 15 outer-refit GPU + 105 CPU 的 strict nested stack；
3. 不打开 V4-F；
4. 若未通过 gate，保留 `DO_NOT_PROMOTE`，不调 gate。

### Phase 1：V2.5 数据与消融

1. 生成 clean B/E lanes；
2. 完成五类 target/contact ablation；
3. 训练 repeated-seed noise head；
4. 冻结 C2 coarse-pose feature contract。

### Phase 2：V2.5 正交 base models

1. 固定全 1,507 scalar supervision；
2. 按 A/B/C 分层 contact supervision；
3. limited inner-CV optimizer/loss search；
4. 输出严格 inner-OOF 低维 evidence vectors。

### Phase 3：strict meta challengers

1. M2 + D；
2. M2 + D + C2；
3. M2 + D + C2 + uncertainty；
4. linear/ElasticNet primary；
5. shallow GBDT 仅作 challenger。

### Phase 4：冻结与 prospective test

只有开放开发集 promotion gates 全部通过，才冻结 final refit、生成 V4-F 32 条预测并一次性 unseal。未通过则继续保持 V4-F sealed。

## 12. Promotion gates

主门保持：

- Rdual Spearman `>= 0.619401`；
- MAE `<= 0.032359`；
- paired whole-parent bootstrap delta 的 95% CI 下界 `> 0`；
- V4-D 与 V4-H 两个 source 的 delta Spearman 均不为负；
- parent-macro delta `> 0`；
- 至少 16/31 parents 的 delta 非负；
- R8/R9 均报告，无单受体塌缩；
- exact-min 违规为 0；
- 1,507 candidates / 31 parents / 五 outer folds 完整闭合；
- V4-F/test32 access 在预测冻结前为 0。

## 13. 停止规则

满足以下任一项，停止继续加大模型：

1. strict stack 未超过 M2 且 target/contact ablation 不敏感；
2. 增益只来自同 parent 内 sibling shortcut，whole-parent test 不增益；
3. 三个 seed 的方向不一致；
4. coarse-pose/contact 增量不能在 V4-D/V4-H 两源同时成立；
5. 噪声上限显示现有 teacher 已不足以支持更高相关性。

此时优先增加无偏多 seed sentinel 和更可靠 Docking teacher，而不是从 ESM2-650M 盲目升级到更大 PLM。
