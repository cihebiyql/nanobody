# PVRIG V5 多模态 Docking-Geometry Surrogate：网络调研、融合框架与执行计划

日期：2026-07-17

## 0. 结论

当前仍有明确提升空间，但最值得做的不是把 `R_dual_min` 粗暴离散后训练一个更大的分类器，而是建立一个可安全回退的分层模型：

```text
当前 M2 单体结构 Ridge（安全锚点）
        +
双受体 8X6B / 9E6Y 条件化 residue-contact 分支
        +
连续多任务、同 parent 排序和不确定性头
        ↓
OOF residual / stacking，只在 whole-parent CV 中确有增益时启用
```

推荐命名：

```text
V5-TB：受控 tabular / multi-task baselines
V5-RC：receptor-conditioned contact residual surrogate
V5-SD：structure-teacher → sequence-student distillation
```

核心原则：

1. `R_dual_min` 继续是主目标，不能改称结合概率、Kd 或实验阻断概率；
2. 先分别预测 `R_8X6B` 与 `R_9E6Y`，再计算 `min`，不要一开始压成单通道；
3. 分类头只作辅助，不能替代连续回归和 within-parent ranking；
4. 新分支通过嵌套 whole-parent CV 学 residual，失败时必须自动退回 M2；
5. 937 条 partial teacher 有严重完成顺序偏差，只能用于方法开发诊断；正式比较等待 terminal teacher；
6. 不能把 docking pose/seed 当独立生物样本，也不能把 parent ID 当生产特征。

---

## 1. 当前证据说明了什么

### 1.1 OPEN_TRAIN226

20 个 parent cluster、whole-parent nested CV：

| 模型 | Spearman | Pearson | MAE | NDCG | Top20% recall |
|---|---:|---:|---:|---:|---:|
| M1 sequence-only | 0.5921 | 0.5074 | 0.03169 | 0.98318 | 0.3696 |
| **M2 structure-only** | **0.6868** | **0.5978** | **0.02877** | **0.98678** | **0.4348** |
| M4 naive late fusion | 0.6803 | 0.5942 | 0.02878 | 0.98677 | 0.4348 |
| M5 structure + sequence residual | 0.6587 | 0.5487 | 0.03038 | 0.98615 | 0.3696 |

全量 scoring 时：

```text
fusion_structure_weight = 1.0
residual_gamma = 0.0
```

这说明：

- 单体结构确有额外信号；
- mean-pooled sequence embedding 与 126 维结构描述符的简单预测级融合没有产生互补增益；
- 新模型必须引入此前没有的信息，例如 residue-level、target-conditioned、contact 或 receptor-specific 信息，而不是重复拼接已有全局向量。

### 1.2 V4-H partial937

| 模型 | Spearman | Pearson | MAE | Top20% recall |
|---|---:|---:|---:|---:|
| M1 sequence-only | 0.5240 | 0.4947 | 0.03444 | 0.3989 |
| **M2 structure-only** | **0.5667** | **0.5310** | **0.03365** | **0.4574** |

M2−M1 的 parent bootstrap `ΔSpearman` 中位数为 `+0.04138`，95% CI 为 `[+0.01419,+0.09730]`。

但：

```text
parent-centered Spearman：M1 0.1389，M2 0.1977
```

因此目前主要短板不是跨 parent 粗排序，而是同一 parent 内的 CDR 设计排序。V5 必须把 within-parent ranking 单独作为训练和验收轴。

### 1.3 可用监督远多于单一 R_dual_min

当前 V4-E/V4-D teacher 表已有 51 列，包括：

```text
R_8X6B, R_9E6Y, R_dual_mean, R_dual_min, R_dual_gap
seed_sd_8X6B, seed_sd_9E6Y
hotspot_overlap_median_8X6B/9E6Y
total_occlusion_median_8X6B/9E6Y
cdr3_occlusion_median_8X6B/9E6Y
cdr3_fraction_median_8X6B/9E6Y
native_cross_support_agreement_mean
model_pair_consensus_fraction_mean
missing_seed_fraction
teacher_uncertainty
```

所以第一步不必等待新的标签定义；应先把现有连续通道用于 multi-task 学习。

---

## 2. 网络调研得到的可迁移方法

### 2.1 partner-conditioned residue graph，而不是 antigen-agnostic 全局池化

PECAN 使用两个蛋白的结构图、图卷积和 partner attention，证明结构邻域、配对上下文和通用 PPI transfer learning 都能贡献界面预测性能；其结果还显示抗体同源模型替代晶体结构时性能只受到较小影响。这直接支持使用冻结 VHH 单体预测结构作为输入，而不是只使用 mean pooling。

来源：

- Pittala & Bailey-Kellogg, 2020, PECAN：<https://academic.oup.com/bioinformatics/article/36/13/3996/5823885>
- 官方代码：<https://github.com/vamships/PECAN>

MIPE 使用 sequence+structure 多模态对比学习，并显式估计 antibody–antigen interaction matrix。对本项目最重要的启示是：融合应发生在 residue/contact 层，而不是两个最终标量预测之间。

- MIPE, IJCAI 2024：<https://www.ijcai.org/proceedings/2024/669>

DeepInteract 更接近 V5 的实际输入边界：它接收两个未结合的单体结构，预测 partner-specific residue–residue contact map，并通过几何 Transformer 保持旋转/平移不变。其困难外部集上的 contact precision 仍有限，因此适合提供冻结 contact prior 或架构基线，而不应成为唯一判据。

- DeepInteract / Geometric Transformers：<https://arxiv.org/abs/2110.02423>
- 官方代码：<https://github.com/BioinfoMachineLearning/DeepInteract>

Paragraph 说明只用抗体预测结构和极小 residue feature vector 的等变 GNN 也能获得强 paratope 表征；因此首版不需要解冻大型 PLM。

- Paragraph：<https://academic.oup.com/bioinformatics/article/39/1/btac732/6825310>

### 2.2 PLM embedding 与结构图可以互补，但 posed-complex 模型不能直接照搬

DeepRank-GNN-esm 把 ESM-2 residue embedding 加到 PPI interface graph，能替代昂贵 PSSM；但它和 DeepRank-GNN、GNN-DOVE、PIsToN、DProQA 一样，主要输入是**已经存在的复合物 pose/interface**。当前 V5 的生产输入只有 VHH sequence/单体结构与固定 PVRIG，因此这些模型更适合作为：

```text
pose scorer 参考
特征设计参考
后续正交验证
```

不能直接声称是 cheap monomer-only surrogate。

- DeepRank-GNN-esm：<https://pmc.ncbi.nlm.nih.gov/articles/PMC10782804/>
- DeepRank-GNN：<https://academic.oup.com/bioinformatics/article/39/1/btac759/6845451>
- DProQA：<https://academic.oup.com/bioinformatics/article/39/Supplement_1/i308/7210460>

IgPose 将 ESM-2、EGNN 和界面聚合结合，并同时建立 pose classifier 与 DockQ regressor；其 generative decoy augmentation 说明，分类和回归可以共存，但分类头应回答明确的 pose-quality 问题，而不是替代连续几何监督。

- IgPose：<https://academic.oup.com/bioinformatics/article/42/3/btag076/8487143>
- 官方代码：<https://github.com/arontier/igpose>

### 2.3 几何预训练有价值，但当前 teacher 数量不支持端到端大模型

GearBind 使用 atom/edge/residue 多层几何消息传递和大规模无标签结构对比预训练，在有限有标签 affinity 数据上优于从头训练。它本身需要 WT/mutant 的已结合复合物结构，不能直接作为当前 pre-docking surrogate；其可迁移结论仅是：

```text
预训练或冻结结构编码器
→ 小型 PVRIG head
```

而不是用 226 或约 1320 条 PVRIG teacher 解冻整个几何网络。

- GearBind：<https://www.nature.com/articles/s41467-024-51563-8>

### 2.4 复杂 GNN 不保证胜过简单机制特征

蛋白 docking 研究中，低维界面几何、接触和物理化学特征配合 SVM/浅层模型长期仍是强基线；DeepRank-GNN 等深模型还高度依赖 pose 分布与 decoy 平衡。当前应保留 Ridge/ElasticNet/浅树，而不是默认 GNN 一定更好。

- ProQDock：<https://academic.oup.com/bioinformatics/article/32/12/i262/2288786>
- CSM-AB：<https://academic.oup.com/bioinformatics/article/38/4/1141/6420700>
- DeepRank-GNN：<https://academic.oup.com/bioinformatics/article/39/1/btac759/6845451>

### 2.5 2026 年方法只作为设计启示

CHIMERA-Bench 强调 unseen epitope、unseen antigen fold 和 temporal target，而 AgForce 报告 antigen blindness：模型可能主要依赖 antibody framework，改变 antigen 后仍产生相似输出。这些是近期预印本/研讨会证据，不能当作已确证结论，但足以支持正式增加 target/hotspot shuffle 和 framework shortcut 测试。

- CHIMERA-Bench：<https://arxiv.org/abs/2603.13431>
- AgForce：<https://arxiv.org/abs/2605.21610>

### 2.6 代码许可和复用风险

公开实现不能默认直接并入比赛生产代码：

| 项目 | 公开实现许可/状态 | 建议 |
|---|---|---|
| Paragraph | BSD-3-Clause | 可优先复用轻量图特征思想 |
| DeepRank-GNN / GearBind | Apache-2.0 | 可研究代码级复用，但仍需核对依赖许可 |
| PECAN | GPLv3+，且 Python 2.7/TensorFlow 1.x 老栈 | 以架构重实现为主，不直接嵌入现流水线 |
| MIPE | CC BY-NC 4.0 | 先确认比赛/后续用途是否满足 non-commercial |
| IgPose | 公开仓库标注 CC BY-NC-ND 4.0，训练说明有限 | 仅作方法参考或独立评估，不直接修改后合并 |

正式实现前必须再次核对仓库当前 LICENSE 和依赖条款。

---

## 3. 推荐 V5 总体架构

```text
VHH sequence residue embeddings
          +
VHH monomer residue graph / current 126 descriptors
          +
IMGT CDR masks + pLDDT/SASA/local geometry/physchem
                     │
                     ▼
          frozen/light VHH encoder
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
8X6B receptor graph          9E6Y receptor graph
hotspot/interface masks      hotspot/interface masks
       │                           │
       └──── low-rank cross-attention / biaffine contact ────┐
                                                              ▼
                          receptor-specific contact summaries
              hotspot mass / off-interface mass / CDR mass / entropy
                                                              │
                      M2 receptor-specific base + residual head
                           ŷ8 = base8 + γ8 δ8
                           ŷ9 = base9 + γ9 δ9
                                                              │
                        ŷdual = min(ŷ8, ŷ9)
```

### 3.1 为什么用 residual，而不是替换 M2

当前 M2 已有稳定证据。新 contact 分支最容易过拟合，因此使用：

```text
new_prediction = M2_prediction + gamma * contact_residual
gamma ∈ {0, 0.25, 0.5, 0.75, 1.0}
```

`gamma` 只能在 nested whole-parent inner CV 选择。若新信息无稳定增益，`gamma=0`，模型自动退回当前 M2。

### 3.2 双受体必须分开编码

不要在输入阶段平均 8X6B 与 9E6Y。先分别输出：

```text
pred_R_8X6B
pred_R_9E6Y
pred_R_dual_gap
```

再派生：

```text
pred_R_dual_min = min(pred_R_8X6B, pred_R_9E6Y)
```

这样才能学习：

- 两个受体构象共同支持的几何；
- 只在单一构象表现好的不稳定候选；
- receptor sensitivity，而不是把它混入一个不可解释的总分。

### 3.3 residue/contact 分支输出

每个 receptor 至少输出以下可解释量：

```text
hotspot_contact_mass
interface_contact_mass
off_interface_contact_mass
interface_specificity
CDR1_contact_mass
CDR2_contact_mass
CDR3_contact_mass
contact_entropy
contact_coverage
8X6B_vs_9E6Y_contact_disagreement
```

如果 raw docking pose 可用，再从每条候选 top-K poses 生成：

```text
VHH residue i – PVRIG residue j contact frequency
```

但必须以 candidate 为监督单位，并对 pose、cluster、receptor、seed 进行聚合，禁止把 pose 展开成独立训练样本。

---

## 4. 机器学习头应该怎样设计

### 4.1 主头：连续多任务回归

第一优先不是分类，而是：

```text
X → R_8X6B
  → R_9E6Y
  → R_dual_min
  → R_dual_gap
```

先比较：

1. multi-output Ridge；
2. MultiTask ElasticNet；
3. 两层小 MLP；
4. 低维结构/contact 特征上的浅 CatBoost/LightGBM。

多任务学习可利用两个 receptor 和多个连续几何通道的相关性，但不能把真实辅助标签作为推理输入。

### 4.2 辅助头：within-parent pairwise ranking

目标是解决当前 parent-centered Spearman 偏低的问题：

```text
group_id = parent_framework_cluster
只构造同 parent pairs
只使用 |Ri - Rj| 大于冻结 noise margin 的 pairs
```

推荐比较：

- CatBoost PairLogit；
- LightGBM LambdaMART；
- 小 MLP pairwise logistic loss。

LambdaMART 是成熟的 learning-to-rank 方法，但 relevance 分桶会丢失连续信息，因此只作辅助头。

- LambdaMART 综述：<https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/>

### 4.3 分类头：可以加，但只能回答有限问题

建议两个分类头：

#### A. 技术有效性头

```text
P(scoring-valid / technically-complete)
```

用途是预测 pipeline 技术失败风险，不得解释为不结合或不阻断。

#### B. Top-tail 辅助头

```text
P(R_dual_min 位于 outer-train 内 top 20%)
```

阈值只能由各 outer-train fold 内计算，不能用全数据分位数泄漏到验证集。

不建议：

```text
G1/G2 = 1，其余 = 0
```

因为硬门对连续 Docking 噪声和阈值变化敏感，会损失排序信息。

### 4.4 树模型的正确位置

CatBoost 的 ordered boosting 专门降低类别统计引起的 prediction shift，适合作为 small-n tabular 对照；LightGBM 适合受控的浅树实验。它们不应直接吞入全部 1115 个 raw embedding dimension。

推荐输入：

```text
126 structure descriptors
27 physicochemical features
contact summary scalars
少量严格预注册的 sequence summaries
```

并限制：

```text
depth 2–4
强 L2
大 min_data_in_leaf
配置总数不超过约 15–20 个
```

严禁把 `parent_framework_cluster`、candidate ID 或 batch ID 作为生产特征。parent 只可作为 split/group/ranking query。

- CatBoost：<https://proceedings.neurips.cc/paper/2018/hash/14491b756b3a51daac41c24863285549-Abstract.html>
- LightGBM：<https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html>

### 4.5 融合方式

所有 stacking 都必须使用 whole-parent OOF prediction：

```text
base models:
  M2 structure Ridge
  multi-task dual-receptor Ridge
  contact residual model
  shallow tree model

meta model:
  non-negative convex weights
  sum(weights) = 1
```

不能用 in-sample base prediction 训练 meta learner。

---

## 5. 不确定性框架

不要把所有不确定性压成一个数字。至少分开：

| 通道 | 含义 |
|---|---|
| model ensemble std | epistemic/model instability |
| predicted R8–R9 gap | receptor/conformer sensitivity |
| teacher seed SD | docking measurement variability |
| missing/invalid fraction | technical completeness |
| contact-head disagreement | mechanism/model disagreement |

第一版使用 5-seed 或 parent-bootstrap ensemble。Deep Ensembles 是简单而强的 uncertainty baseline，但没有 coverage 保证。

- Deep Ensembles：<https://papers.neurips.cc/paper_files/paper/2017/hash/9ef2ed4b7fd2c810847ffa5fa85bce38-Abstract.html>

当独立 parent 数增加后，再做 group-aware conformal。普通 row-level conformal 不适合一个 parent 下大量相关设计；当前只有约 20 个独立 parent 时，正式 group coverage 区间会非常粗。

- Conformal prediction beyond exchangeability：<https://arxiv.org/abs/2202.13415>

---

## 6. 分阶段执行方案

### Phase 0：冻结当前证据边界

保持不变：

```text
primary = R_dual_min
M2 = current champion
V4-F/test32 = sealed
partial937 = biased development diagnostic
candidate = supervision unit
```

### Phase 1：V5-TB，先跑便宜强基线

在 terminal teacher 可用后，依次比较：

```text
B0 global mean / parent-only diagnostic / CDR3-length-only
B1 M1 sequence Ridge
B2 M2 structure Ridge
B3 dual-head multi-output Ridge: R8 + R9 → min
B4 ElasticNet structure/contact
B5 shallow CatBoost regression
B6 shallow LightGBM regression
B7 PairLogit/LambdaMART within-parent auxiliary rank
B8 non-negative OOF stacking
```

这一阶段很可能比立即训练大型 GNN 更快发现真实增益。

### Phase 2：V5-RC，加入 residue/contact 条件化

1. 为 VHH 单体提取 residue-level frozen ESM2/VHHBERT；
2. 建立 VHH residue graph：坐标、CDR mask、pLDDT、SASA、二级结构、局部形状和 physchem；
3. 分别缓存 8X6B/9E6Y receptor graph 和 interface/hotspot mask；
4. 训练低秩 cross-attention 或 biaffine contact head；
5. 将 contact summaries 作为 M2 residual；
6. 只有 nested CV 稳定增益时启用 `gamma>0`。

### Phase 3：pose-contact teacher

从 terminal Docking 的 top-K pose/cluster 聚合 contact frequency：

```text
candidate × receptor × VHH residue × PVRIG residue
```

训练：

```text
contact-frequency auxiliary loss
hotspot mass regression
occlusion component regression
```

不要使用 rank-1 pose 单标签；比较 top-1、top-K 和 cluster-weighted 三种监督。

### Phase 4：V5-SD，结构 teacher 蒸馏到 sequence student

生产筛选时，不应对全库都预测结构。推荐：

```text
结构/contact V5 teacher
        ↓ distillation
sequence residue student
        ↓
8,000–15,000 全库快筛
        ↓
Top 1,500–2,500 再跑单体结构 V5
        ↓
Top 300–500 进入 Docking
```

这一路线把“结构更准确”与“序列快筛更便宜”同时保留。

### Phase 5：active learning

采集分数：

```text
high predicted geometry
+ model disagreement
+ receptor disagreement
+ parent/patch/method diversity
```

先用已有 campaign 做 retrospective replay，比较：

```text
random
greedy-high-score
uncertainty-only
diversity-only
combined acquisition
```

若 learning-curve AUC 不超过简单基线，不部署 active learning。

---

## 7. 验证与消融矩阵

### 7.1 数据划分

主 split：

```text
outer 5-fold whole-parent CV
inner whole-parent CV
```

challenge：

```text
CDR3 cluster holdout
structure-similarity holdout
design-method holdout
```

937 若包含原 226，不得称作独立测试；terminal 1320 若仍只有 11 个 parent，统计有效独立单位仍接近 parent 数，而不是 1320。

### 7.2 主指标

```text
global OOF Spearman / Pearson / MAE
parent-centered Spearman
per-parent macro median Spearman
Top20% recall
NDCG@top20%
R8 / R9 / gap 单独指标
parent-bootstrap delta CI
```

### 7.3 必须消融

1. M2-only、contact-only、M2+contact residual；
2. direct `R_dual_min` vs `R8/R9 → min`；
3. 8X6B-only、9E6Y-only、平均 receptor、分离双头；
4. CDR3-only、CDR1+3、all-CDR、whole-VHH；
5. hotspot mask removal/shuffle；
6. interface/off-interface mask swap；
7. antigen/receptor embedding shuffle；
8. frozen vs partially fine-tuned encoder；
9. rank-1 vs top-K vs cluster-weighted contact label；
10. 3-seed vs 5-seed ensemble；
11. global rigid rotation/translation invariance；
12. parent-group split vs row-random split，后者只作泄漏诊断。

### 7.4 建议预注册成功门

以下为工程门槛建议，不是领域公认真值：

1. `ΔSpearman(V5−M2)` 的 parent-bootstrap 95% CI 下界大于 0；
2. parent-centered 和 per-parent macro 指标方向一致，并非只由一个 parent 驱动；
3. Top20% recall 不下降，最好提高至少 0.03–0.05；
4. hotspot/target shuffle 后性能明显下降，证明模型使用了 PVRIG 条件；
5. residual gamma 跨 fold 稳定，且多数 fold 不退化为 0；
6. uncertainty 与绝对误差正相关，且高置信区间覆盖可校准；
7. 所有输入在生产推理时真实可得，不读取 docking pose-derived 真值。

失败时保留：

```text
M2 champion
+ V5 research-only evidence
```

不得通过改阈值、删 parent 或挑最好 fold 把结果修成 PASS。

---

## 8. 资源与实现边界

### 本机 RTX 5080

适合：

```text
per-residue embedding cache
小型 graph/cross-attention head
5-seed ensemble
结构 teacher → sequence student distillation
```

### Node23

继续负责：

```text
独立 8X6B/9E6Y Docking teacher
top-K pose/contact 聚合源数据
```

### 不建议当前做

```text
用 226 条端到端解冻 ESM2/VHHBERT
用 937 partial 偏置样本做正式模型选择
直接训练大型 EquiDock/DiffDock-PP 替代现有主线
把 posed-complex scorer 假装成 monomer-only surrogate
把 parent ID 喂给生产模型
把 G1–G5 作为唯一标签
```

---

## 9. 推荐执行优先级

```text
P0  terminal teacher 完成后重放 M1/M2
P1  multi-output Ridge：R8/R9/dual/gap
P2  shallow CatBoost/LightGBM + ElasticNet 强基线
P3  within-parent PairLogit/LambdaMART 辅助头
P4  M2 + frozen contact summaries residual
P5  residue-level dual-receptor cross-attention/contact head
P6  top-K pose-contact teacher
P7  structure-teacher → sequence-student distillation
P8  retrospective active learning replay
```

最有可能真正改善当前结果的不是“更复杂的 final classifier”，而是：

> **把双受体、热点、CDR residue 几何和 top-K contact consistency 变成显式输入/辅助监督，再用小型、group-aware、可回退的 residual/ranking head 融合。**

这条路线直接针对当前最弱的 within-parent 排序，同时维持 M2 的已验证优势和完整证据边界。
