# V2.7：面向 10 万条 VHH 的多模型 Early-Enrichment 级联筛选方案

## 0. 版本与证据边界

```text
版本：V2.7-100K-MEEC-v1
名称：100K Multi-model Early-Enrichment Cascade
日期：2026-07-19
主目标：用有限计算把 100,000 条 VHH 收敛到可承担 Docking 的候选集合
主监督：独立 8X6B/9E6Y Docking 连续几何
冻结主目标：R_dual_min = min(R_8X6B, R_9E6Y)
```

本方案预测的是：

```text
VHH 在当前独立双受体 Docking 协议下的 computational blocking geometry
```

它不是：

```text
真实结合概率、Kd、实验阻断概率、Docking Gold 或比赛最终真值
```

V4-F/test32 在所有模型、融合权重、阈值和候选选择策略冻结前必须保持 sealed。所有开发和选择只使用 open development 数据；legacy 或 sealed 数据不得用于训练、调参或挑选融合器。

---

## 1. 当前证据告诉我们的事实

当前 inner-only pilot 的核心结果为：

| 模型 | Rdual Spearman | MAE | RMSE |
| --- | ---: | ---: | ---: |
| B | 0.2630 | 0.02975 | 0.03711 |
| E | 0.2630 | 0.02975 | 0.03711 |
| F0 三 seed ensemble | 0.3173 | 0.03145 | 0.03784 |
| F1 三 seed ensemble | 0.2076 | 0.04317 | 0.05457 |

F0 对随机有明显 global early enrichment：

```text
验证集 184 条、6 个 unseen parent clusters
预测 Top10%：19 条中命中 12 条真实 Top10%
Recall = 63.2%
EF = 6.12x

预测 Top20%：37 条中命中 14 条真实 Top10%
Recall = 73.7%
EF = 3.66x
```

但 B 的命中数几乎相同，B/F0 的 Top20% 重合 97.3%。因此目前能下的结论是：

1. 神经模型已经有从大池中早期富集较好 Docking 几何的信号；
2. F0 的 contact 监督改善了全局连续排序，但尚未证明改善榜首富集；
3. 当前优势可能主要来自 parent/scaffold 间差异；大 sibling family 内排序仍弱；
4. F1 的 `lambda_rank=0.1` 明显变差，当前版本停止扩展；
5. M2、B、F0 的互补性必须通过相同 split、相同 seed、严格 OOF stacking 验证，不能把不同协议下的指标直接横向比较。

所以生产方案不选“唯一冠军模型”，而使用：

```text
多模型共识 + 单模型救援 + 不确定性 + 多样性 + 随机 sentinel
```

---

## 2. 总体级联

```text
100,000 raw VHH
        │
        ▼
Stage 0：序列门控 + sequence-only 多模型
        │  保留约 15,000–25,000
        ▼
Stage 1：快速单体结构 + M2/B/F0 + 严格 OOF 融合
        │  保留约 1,500–3,000
        ▼
Stage 2A：双受体、单 seed Docking
        │  约 1,500–3,000
        ▼
Stage 2B：高价值候选补 seed + 随机 sentinel
        │  约 300–500 候选补至三 seed
        ▼
连续 R8/R9/Rdual teacher 增量
        │
        └──→ 重训 sequence student、M2/B/F0、融合器与不确定性模型
```

核心原则是逐层提升单位计算的富集率，而不是让 100,000 条全部进入结构预测或 Docking。

---

## 3. Stage 0：100K 序列级廉价筛选

### 3.1 输入

每条候选仅使用 Docking 前可获得的信息：

```text
完整 VHH 序列
IMGT numbering 与 FR/CDR mask
CDR1/2/3 序列和长度
parent/design method/patch provenance（只用于分组、审计和配额，不作模型输入）
```

禁止输入：

```text
candidate_id、parent_id、campaign_id 的可学习编码
Docking pose 或 pose-derived 特征
真实 R8/R9/Rdual
与已知阳性序列的相似度特征
```

### 3.2 硬门与轻量 QC

先执行：

```text
非法字符、长度、stop、精确重复
ANARCI/IMGT 可编号性
FR/CDR 完整性、保守 Cys
明显 glyco/PTM、极端疏水 run、低复杂度
CDR identity 比赛 hard gate
```

这些指标只用于安全门控和开发性风险，不得伪装成 PVRIG 几何证据。

### 3.3 Stage 0 模型组

#### S0-A：sequence docking surrogate

```text
frozen ESM2-650M 或缓存 residue embeddings
+ CDR/FR region embedding
+ CDR length/position
+ 少量 label-free physicochemical features
        ↓
R8_hat / R9_hat
        ↓
exact Rdual_hat = min(R8_hat, R9_hat)
```

训练目标为 open Docking 的连续 R8/R9；不独立输出自由 Rdual。

#### S0-B：sequence student / teacher distillation

用 Stage 1 的结构模型组合产生软 teacher：

```text
M2/B/F0 OOF prediction distribution
        ↓ distill
sequence-only student
```

该 student 的作用是把结构模型的排序知识压缩到 100K 可承受的序列推理中。蒸馏标签必须是 OOF 或冻结 teacher 对未参与训练样本的预测，禁止自训练泄漏。

#### S0-C：cheap tabular challenger

输入只包括 CDR 长度、氨基酸组成、净电荷、疏水比例、低复杂度等轻量特征；模型使用 Ridge/ElasticNet 或浅层 GBDT。它主要用于检测神经模型是否只学到了简单组成偏差，并提供低成本互补排序。

#### S0-D：generic binding prior（独立证据轴）

若通用 VHH-PVRIG binding/contact prior 已通过自身 target-swap/null gate，可作为辅助列；它不能替代 Rdual surrogate，也不能被解释为 blocker probability。

### 3.4 Stage 0 融合与配额

不直接平均原始分数。先在 whole-parent OOF 内将各模型输出转为 fold-local rank/quantile，再训练强正则非负线性融合器；浅层 GBDT 只作为 challenger。

Stage 0 建议保留 20,000 条，配额为：

| 通道 | 比例 | 20K 数量 | 目的 |
| --- | ---: | ---: | --- |
| 融合器 exploitation Top | 70% | 14,000 | 主富集 |
| 单模型 Top-list union rescue | 10% | 2,000 | 防止融合器抹平互补信号 |
| 高不确定性/高分歧 | 8% | 1,600 | 主动学习决策边界 |
| parent/CDR3/patch/method 多样性 | 7% | 1,400 | 防止 scaffold shortcut |
| 分层随机 sentinel | 5% | 1,000 | 估计无偏选择收益与低分区噪声 |

同一候选重复命中多个通道时，空出的名额按上述优先顺序补齐；同一 parent、CDR3 cluster、design method 必须设置上限。

---

## 4. Stage 1：结构知情的多模型精筛

### 4.1 输入与结构成本控制

只对 Stage 0 survivor 生成快速 VHH 单体结构。优先使用本地已验证的最快单体预测器完成全 15K–25K；较慢的 IgFold/更高精度交叉检查只用于 Stage 1 高分子集。

结构预测前必须做 500–1,000 条实测 benchmark，并冻结：

```text
秒/序列
失败率
GPU/CPU 峰值
PDB/embedding 缓存大小
重复序列 cache hit
```

若预测 20K 的预计 wall time 超过 12 小时，则自动将 Stage 0 survivor 收紧到 10K–15K，而不是让结构阶段无界运行。

### 4.2 Stage 1 基模型

#### M2：126D 单体结构聚合 Ridge

输入：冻结的 126 维 VHH 单体结构聚合特征。

作用：提供当前最强、最稳定的低维结构基线。M2 的正式历史结果来自不同 nested OOF 协议，不能和当前 B/F0 inner split 数值直接比较；V2.7 必须在同一 split 上重新生成 M2 OOF。

#### B：scalar attention control

输入：

```text
frozen ESM2-650M residue embedding
VHH monomer residue graph
AA/CDR region embedding
monomer confidence
固定 8X6B/9E6Y PVRIG residue graphs 与 hotspot/interface mask
```

输出：直接 R8/R9，推理时 exact min。无 contact loss、无 pair ranking。

#### F0：shared-gated contact transfer

输入与 B 相同，增加独立 contact terminal 和 contact supervision。contact 梯度通过固定 `kappa=0.25` 预算进入 shared encoder；contact terminal 不直接把分数喂给 scalar head。

当前 F0 作为互补模型保留，但在 matched B 三 seed、更多 folds 和 early-enrichment 指标证明增量前，不得替代 B。

#### 结构/QC辅助列

可加入：

```text
monomer confidence
CDR3 confidence/构象稳定性
少量 developability flags
S0 sequence prediction
M2-B-F0 disagreement
seed ensemble variance
R8-R9 conformer gap
```

developability 与 geometry 应保留为两个证据轴；不允许因开发性加权而把 geometry surrogate 的含义改成不透明总分。

### 4.3 融合器

必须使用双层 cross-fitting：

```text
outer-train parents
  → inner-OOF M2/B/F0/S0/uncertainty features
  → 训练 meta-head
  → 基模型在全部 outer-train 重训
  → 生成 outer-test features
  → meta-head 预测 outer-test
```

融合器顺序：

1. 非负线性 stacking / ElasticNet primary；
2. 浅层 HistGradientBoosting/LightGBM challenger，depth 2–3、强正则、大 min leaf；
3. 低权重 PairLogit/LambdaMART 只作 within-parent rank challenger，不替代连续 R8/R9 回归。

融合必须分别生成 `R8_hat`、`R9_hat`，最终：

```text
Rdual_hat = min(R8_hat, R9_hat)
```

不得独立训练一个不受约束的 Rdual 输出。

### 4.4 Stage 1 → Docking 的配额

以保留 2,000 条为例：

| 通道 | 比例 | 数量 | 目的 |
| --- | ---: | ---: | --- |
| 融合器 exploitation Top | 60% | 1,200 | 主富集 |
| M2/B/F0/S0 单模型 union rescue | 15% | 300 | 保留互补模式 |
| 高预测但模型强分歧 | 10% | 200 | 判断模型盲区 |
| 新 parent/CDR3/patch/method 多样性 | 10% | 200 | 扩展搜索空间 |
| 分层随机 sentinel | 5% | 100 | 估计真实 enrichment 与 noise floor |

所有通道均设置 parent、CDR3 cluster、patch 和 method 上限。最终 Docking 队列不能机械取一个黑箱总分前 2,000。

---

## 5. Stage 2：Docking 与主动学习反哺

### 5.1 Stage 2A：广覆盖单 seed 双受体

对 1,500–3,000 条执行：

```text
8X6B independent Docking, seed 1
9E6Y independent Docking, seed 1
固定 Top-K、ATOM-only、HETATM zero gate、hash closure
```

保存连续：

```text
R8、R9、Rdual=min(R8,R9)
hotspot、occlusion、CDR contribution
support fraction、supporting pose count
pose/cluster dispersion
```

G1–G5 只作解释，不作为唯一主监督。

### 5.2 Stage 2B：补 seed 的选择

从 Stage 2A 中选择 300–500 条补至三 seed，固定包含：

| 类型 | 建议比例 |
| --- | ---: |
| 高 Rdual exploitation | 35% |
| 首 seed 中等、接近决策边界 | 20% |
| 模型高分但 Docking 低分 | 10% |
| 模型低分但 Docking 高分 | 10% |
| 新 parent/patch/method/CDR3 | 10% |
| Stage 0/1 预注册随机 sentinel | 15% |

随机 sentinel 必须覆盖预测高、中、低分区，且无论首 seed 结果如何都补齐，才能估计 score-dependent noise；自适应高分补 seed 不能被误当成无偏重复样本。

### 5.3 反哺顺序

每个新增 Docking round 终止后：

```text
1. 冻结 manifest、sequence hash、structure hash、Docking receipt
2. 生成 candidate-level 连续 teacher 与 repeat-seed uncertainty
3. whole-parent/whole-CDR3 去重和 split closure
4. 更新 S0 sequence surrogate
5. 更新 M2/B/F0 OOF predictions
6. 重训严格 cross-fit meta-head
7. 只在 open prospective sentinel 上评价 early enrichment
8. 冻结下一轮选择器后，才对新 100K 池评分
```

不得用同一批新增 Docking 同时训练融合器并报告其性能；每轮至少保留一组 prospective whole-parent block 或预注册随机 sentinel。

---

## 6. 早期富集是主验收指标

### 6.1 开发指标

在 whole-parent held-out open 数据上同时报告：

```text
Recall(true Top10%) @ predicted Top5/10/20%
Recall(true Top20%) @ predicted Top10/20%
EF@Top5/10/20%
binary NDCG@Top5/10/20%
within-parent macro EF 和 recall
各 parent 的最小/中位/最大表现
Spearman、MAE、RMSE（辅助）
```

连续 NDCG 在 Rdual 取值范围窄时可能虚高，不能单独作为成功证据。

### 6.2 V2.7 首轮门槛

这些是工程门槛，不是生物学真值：

1. 在相同 seed/fold 下，融合器对 B 与 M2 最强基线的 `EF@Top10%` 不劣，bootstrap 95% CI 不出现实质负增量；
2. `Recall(true Top10%) @ predicted Top20% >= 75%`；
3. `EF(true Top10%) @ predicted Top10% >= 4x`；
4. within-parent macro `EF@Top20% >= 1.5x`，并把 `>=2x` 作为下一轮目标；
5. 三 seed Top-list overlap 与 rank stability 达到预注册门槛；
6. target/hotspot/conformer ablation 必须显著降低 early enrichment，否则不能声称模型使用了 PVRIG 几何信息。

当前 F0 在单一 inner split 已达到 global `EF@Top10%=6.12x` 和 Top20 recall 73.7%，但 B 基本相同，且验证仅有 184 条/6 parents。因此它是可行性证据，不是 V2.7 正式通过。

### 6.3 100K prospective 验收

在 Stage 2 的随机 sentinel 与 exploitation 队列之间比较：

```text
selected subset 的 Rdual 分布是否显著优于随机 sentinel
top docking decile 在 selected subset 的 EF
按 parent/patch/method 分层后的 enrichment
模型高低分区的 repeat-seed 方差
每 1,000 次 Docking 找到的高 Rdual 候选数
```

生产决策应优化“每 1,000 个 Docking 发现多少高价值候选”，而非只优化全数据 Spearman。

---

## 7. 吞吐与计算预算

### 7.1 计划预算

| 阶段 | 数量 | 主要资源 | 目标 wall time | 超预算回退 |
| --- | ---: | --- | ---: | --- |
| hard gate/编号/轻量 QC | 100K | 32–48 CPU | <=2 h | 分块并行、缓存编号 |
| ESM2-650M embedding + S0 推理 | 100K | 4x4090 | <=6 h | FP16/BF16、长度桶、缓存、减少 ensemble |
| 快速单体结构 | 15K–25K | 4x4090 或 CPU worker | <=12 h | survivor 收紧至 10K–15K |
| M2/B/F0 inference | 15K–25K | 4x4090 | <=2–4 h | 缓存 graph/embedding，F0 ensemble 延后 |
| 双受体单 seed Docking | 2K 候选=4K jobs | Node23 ~120–145 jobs/h | ~28–34 h | 分两批启动，不改变协议 |
| 400 候选补两个 seed | 1.6K jobs | Node23 ~120–145 jobs/h | ~11–14 h | 优先保留随机 sentinel 与边界样本 |

Docking 吞吐使用最近 controller 的实测量级进行预算；序列和结构阶段在正式 100K 前必须以本机 500–1,000 条 benchmark 更新，不应把目标预算误写成已实现吞吐。

### 7.2 存储预算

100K 不应重复保存多份 ESM2 residue embedding。建议：

```text
sequence hash → content-addressed embedding cache
只为 Stage 0 survivor 保留 residue-level embedding
其余只保留 pooled/low-dimensional output
PDB 只为 Stage 1 survivor生成
Docking pose 只为 Stage 2 保存
```

每轮启动前检查 `/data1` 空间；低于预注册 headroom 时 fail closed，不得在训练中途因磁盘满而产生不完整 teacher。

---

## 8. 近期执行顺序

### Phase A：补齐因果对照

1. 运行 B seeds 97/193，与 F0 三 seed完全 matched；
2. 运行 F0 marginal-only、pair-only、combined ablation；
3. 在同一 inner folds 上重算 early enrichment 和 within-parent 指标；
4. 冻结 F1 `lambda_rank=0.1` 为负结果，不再扩展。

### Phase B：建立 100K sequence stage

1. 实现 S0-A sequence-only R8/R9 baseline；
2. 从 OOF M2/B/F0 构建 S0-B distillation teacher；
3. 建立 100K 分块 scoring、断点续跑、hash/cache 与配额选择器；
4. 先以现有 open 数据做回放，证明 Stage 0 Top20% 能保留大多数真实 Top10%。

### Phase C：严格多模型融合

1. 在完全相同 whole-parent nested split 上生成 M2/B/F0/S0 OOF；
2. 训练非负 ElasticNet stack；
3. 浅层 GBDT 只作 challenger；
4. 同时报 global 与 within-parent early enrichment；
5. 若融合没有稳定超过 `max(B,M2)`，保留模型 union，不强行发布单一融合分。

### Phase D：首轮 100K prospective round

1. Stage 0 100K → 20K；
2. Stage 1 20K → 2K；
3. 2K 双受体单 seed；
4. 400 条补 seed，其中至少 15% 是预注册随机 sentinel；
5. 用新 teacher 重训并冻结 V2.7-v2；
6. test32 仍保持 sealed，直到 formal model family、融合器和阈值全部冻结。

---

## 9. 最终决策规则

对于 100K 筛选，本方案不要求某一个模型永久获胜。正式选择器由五类证据组成：

```text
1. OOF-calibrated ensemble exploitation
2. M2/B/F0/S0 单模型 top-list union
3. ensemble uncertainty / model disagreement
4. scaffold/CDR3/patch/method diversity
5. stratified random sentinel
```

这使系统能够随着新增 Docking 数据持续提高，而不会因为早期模型偏差把整个未探索空间永久删除。

最重要的停止/通过条件不是“相关系数看起来更高”，而是：

> 在 whole-parent held-out 和 prospective random sentinel 上，单位 Docking 预算发现的高 Rdual 候选显著增加，并且这种提升在不同 parent、patch、method 上可复现。

