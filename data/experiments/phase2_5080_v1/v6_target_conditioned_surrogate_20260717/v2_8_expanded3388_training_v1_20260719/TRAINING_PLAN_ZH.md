# V2.8 扩展训练计划：3,388 条标量教师 + 分阶段结构/接触扩展

## 目标

从 10 万条 VHH 中尽量早地富集高 `R_dual_min` 候选，使有限 Docking 预算优先覆盖更可能呈现双受体 blocker-like geometry 的序列。

模型输出仍严格限定为 Docking 几何代理，不外推为结合概率或实验阻断概率。

## Phase 0：保留当前模型的未重训快照

在任何 V4-I 标签参与拟合前，用当前 V2.7 模型冻结一次 V4-I 全集预测，形成 `CURRENT_MODEL_ON_V4I_PREUPDATE.tsv`。这是 generator-shift 的开放开发证据，不是 formal holdout。冻结后才允许 V4-I 加入训练。

## Phase 1：S0 扩展 sequence ensemble（立即执行）

训练数据分三档冻结比较：

```text
D0 = 1,507：既有 open teacher
D1 = 2,007：D0 + V4-I Stage 2 的 500 条候选
D2 = 3,388：D1 + 其余 1,381 条 Stage 1 单-seed候选
```

只有 D2 在 parent-macro early enrichment 上不弱于 D1 时，全部 3,388 条才作为主训练集；否则 D1 为主，额外 1,381 条只作低权重预训练或主动学习候选。

基础模型：

1. ESM2-650M mean/residue-pooled embedding + Ridge；
2. ESM2-650M + ElasticNet；
3. ESM2-3B challenger；
4. 650M/3B 预测的非负线性 stack；
5. 同 parent PairLogit/LambdaMART 仅作排序 challenger。

所有模型只直接预测 `R8`、`R9`，`Rdual` 由 exact min 得到。损失使用：

```text
L = weighted_Huber(R8) + weighted_Huber(R9)
  + 0.25 * within-parent pairwise rank loss
```

第一轮线性模型不使用 rank loss；神经/GBDT challenger 才加入。权重由三部分相乘后归一化：

```text
证据基础权重 × parent 反频率权重 × campaign/source-lane 平衡权重
```

seed dispersion 的连续降权只在 inner CV 比较，不事后按结果选阈值。

## Phase 2：M2 结构特征扩展

在 Node23 对 1,962 个 V4-I monomer PDB 运行与旧 teacher 相同的 126-D feature extractor，发布 candidate→sequence→monomer hash 闭包。81 条 Docking 技术不完整候选仍可用于无标签结构预处理，但不进入 scalar loss。

随后训练：

```text
126-D structure → cross-fit Ridge/ElasticNet → R8/R9 → exact min
```

M2 与 sequence 模型保持正交，直到最终 stack 才融合。

## Phase 3：V4-I contact teacher

从 Node23 raw Top-8 poses 提取：

- receptor-specific VHH residue marginal contact；
- 稀疏 VHH–PVRIG residue-pair contact；
- observed/expected seed count；
- contact variance/uncertainty；
- hotspot/interface masks。

优先级：

1. 476 条双 seed候选；
2. 1,405 条单 seed候选（低权重）；
3. 81 条技术不完整候选不做伪标签。

训练时拆分 attention logits 与 contact logits；contact head 绝不复用 attention 最终标量。Pair-only 暂停，先比较 marginal-only 与 scalar-only 是否有稳定增益。

## Phase 4：正交 late fusion

使用严格双层 cross-fitting 生成低维 OOF 证据：

```text
Sequence: seq_R8, seq_R9, exact_min, uncertainty
M2:       m2_R8, m2_R9, exact_min
Contact:  hotspot mass, interface specificity, CDR1/2/3 mass,
          entropy, conformer gap
Agreement: seq–M2 gap, R8–R9 gap, ensemble disagreement
```

二级模型顺序：

1. 非负线性 stack；
2. ElasticNet；
3. depth 2–3、强正则的 HistGradientBoosting/LightGBM challenger；
4. best-rank OR selector 作为固定 Docking 预算的组合策略。

不把原始 128 维 latent、parent ID、candidate ID、campaign ID 输入二级模型。

## 验证设计

主拆分：31 个 `parent_framework_cluster` 整体分组，沿用已有 outer-fold 绑定。V4-H/V4-I 同 parent 的所有 sibling 必须在同一 fold。

附加挑战：

- MPNN source-lane holdout；
- LATENT source-lane holdout；
- V4-I generator-shift open challenge；
- 高/中/低 Docking 分数分层的 repeat-seed noise diagnostic。

主要验收指标按 10 万库筛选用途定义：

| 指标 | 作用 |
|---|---|
| Recall true Top 1/5/10% @ predicted budget 1/5/10/20% | 直接衡量漏斗找回率 |
| EF@1/5/10/20% | 直接衡量早期富集 |
| within-parent EF/Recall | 排除只学 parent shortcut |
| source-lane challenge EF | 检查生成器泛化 |
| R8/R9/Rdual Spearman、MAE | 连续几何辅助指标 |
| seed-to-seed ceiling | 判断模型是否逼近教师噪声上限 |

## 生产 10 万库的组合选择器

不要求单模型独占筛选。推荐固定预算组合：

```text
60%：sequence ensemble/stack 高分
20%：M2 或 contact 模型补充的 rank-disagreement 候选
10%：高不确定性主动学习
10%：parent/patch/method 多样性探索
```

若仅有 sequence 特征，则使用：

```text
70%：Ridge/ElasticNet/3B stack 共识
20%：best-rank OR 联集
10%：多样性与不确定性探索
```

## 停止/升级条件

只有在 whole-parent OOF 中同时满足以下条件，复杂模型才替换简单 sequence baseline：

- 全局 EF@Top10% 明显提高；
- within-parent EF 不下降；
- 至少 3 个 seed/重复训练方向一致；
- bootstrap 95% CI 不支持纯偶然增益；
- target/contact ablation 能显著破坏 contact 模型表现。

否则保留简单模型，并把新增 Docking 预算优先投入随机多 seed sentinel 与新 parent clusters，而不是继续扩大网络参数。
