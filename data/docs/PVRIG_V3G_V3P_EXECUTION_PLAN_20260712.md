# PVRIG V3-G / V3-P 模型与数据执行方案

- 日期：2026-07-12
- 状态：审阅后执行稿
- 适用范围：`/mnt/d/work/抗体/data` 的通用 VHH-抗原模型、PVRIG 专用前筛模型，以及与 Node1 筛选漏斗的衔接
- 目标：把当前概念规划收敛为可实施、可审计、可回退的训练与候选筛选方案

## 1. 执行结论

原规划的核心方向正确：不能让一个模型直接从序列宣称“阻断概率”，而应明确拆成两个学习阶段和一个昂贵验证阶段：

```text
V3-G：通用 target-conditioned contact / binding prior
  学习真实结构接触、paratope、epitope 和真实 pair 的结合先验
                         ↓
V3-P：PVRIG geometry-surrogate frontscreen
  学习哪些候选更值得送入 PVRIG 结构、docking 和遮挡计算
                         ↓
Node1：正式结构与几何判定
  完整 QC、单体结构、HADDOCK、PVRL2 遮挡、8X6B/9E6Y 分层
```

但是，执行时必须增加五项修正：

1. 当前 mean-pooled V3 不能直接称为 `V3-G` 成品。其正式外部迁移评估已经失败，只能冻结为 `V3-G0` 基线。
2. 新的 residue-level 通用模型命名为 `V3-G1`；第一轮 PVRIG surrogate 命名为 `V3-P1`；主动学习更新后命名为 `V3-P2`。
3. PVRIG teacher 数据生产是当前关键路径；`V3-G1` 可以并行推进，但不能阻塞候选生成、Node1 teacher 计算或最终提交漏斗。
4. 在训练 `V3-P1` 前，必须先建立一个确定性的 Top-K pose 聚合器和统一 teacher manifest。不能直接拿零散 docking CSV 训练。
5. 第一版 PVRIG ranker 使用现有 PyTorch 环境可实现的小型 ordinal MLP；当前环境缺少 `lightgbm`、`xgboost`、`sklearn` 和 `scipy`，本阶段不为树模型增加新依赖。

最终输出是“前筛排序依据”，不是实验真值：

```text
generic_binding_prior
pvrig_hotspot_contact_score
pvrig_interface_specificity
predicted_G1_probability
predicted_G2_probability
predicted_G3_probability
predicted_occlusion
model_uncertainty
frontscreen_rank
```

明确禁止把这些字段重命名或解释为：

```text
binding_probability
blocker_probability
Kd
IC50
实验结合阳性
实验阻断阳性
```

## 2. 为什么要修正当前版本线

### 2.1 当前 V3 mean-pooling 正式评估失败

本地正式评估位于：

`experiments/phase2_5080_v1/runs/phase2_v3_binding/phase2_v3_binding_20260712T024039_011095Z/formal_evaluation/PHASE2_V3_FORMAL_EVALUATION.md`

外部 hTNFa 结果为：

| 项目 | 结果 |
| --- | ---: |
| 决策 | `FAIL_FALLBACK_TO_BASELINE` |
| 最强开发期基线 | `esm2_pair` |
| 基线 AUPRC | 0.225320 |
| `v3_full` ensemble AUPRC | 0.171535 |
| ensemble delta | -0.053785 |
| paired bootstrap 95% CI | [-0.072337, -0.038395] |

因此，当前 mean-pooled VHHBERT/ESM2 加浅层 pair head 的正确定位是：

```text
V3-G0 = 必须保留的失败基线和消融对照
```

它不能进入正式候选排序，也不能被当作通用结合模型已经完成的证据。

### 2.2 V2.3/V2.4 有可复用的 residue-level 能力

`CrossContactNetV23` 已经在以下文件中实现：

`experiments/phase2_5080_v1/src/train_phase2_v2_3.py`

它包含：

- frozen ESM2 residue cache；
- CDR type embedding；
- VHH 与 antigen Transformer encoder；
- bidirectional cross-attention；
- paratope、epitope 和 residue-pair contact heads。

V2.3 严格评估结果：

| 指标 | V2.3 mean | 对照/随机期望 | 结论 |
| --- | ---: | ---: | --- |
| contact AUPRC | 0.519729 | 0.199490 | 有明确可复用信号 |
| paratope AUPRC | 0.630628 | 0.168584 | 有明确可复用信号 |
| epitope AUPRC | 0.159777 | 0.083091 | 有限但高于基线 |
| ranking MRR | 0.524921 | 0.532976 | 未超过随机期望 |

所以正确的继承关系是：

```text
复用 V2.3/V2.4 的 residue-level contact/site 表征
不复用其未经验证的 pair-ranking 结论
```

## 3. 经本地清点后的数据基线

原规划中的 `6,385 canonical contact records` 已经过时。当前 clustered contact 文件实际是 `8,414` 条记录。

| 数据 | 当前本地规模 | 在新方案中的角色 |
| --- | ---: | --- |
| ZYMScott site pairs | 1,230 | paratope / epitope 监督 |
| clustered structure contacts | 8,414 records | residue contact 主监督 |
| contact positive residue pairs | 855,922 | contact head 正样本 |
| contact negative residue pairs | 3,423,688 | contact head 结构内负对照 |
| AVIDa-hIL6 | 573,891 rows | 真实 binder/non-binder 训练和突变泛化 |
| NanoLAS sequence rows | 30,667 | 弱监督和序列背景 |
| NanoLAS binding-site rows | 2,659 | site 弱监督 |
| NanoBind canonical affinity | 181 pairs | 同靶点/同系列 ranking |
| sdAb-DB affinity table | 1,484 rows | 清洗来源；其中既有汇总记录约 272 条 numeric Kd |
| SAbDab affinity table | 493 rows | 小规模 affinity ranking/校准 |
| PVRIG 成功/阳性校准 | 11 cases / 109 poses | 阈值、机制和 family holdout |
| PVRIG mutant/control | 36 cases / 357 poses | 校准扰动与失败模式 |

关键本地文件：

- `experiments/phase2_5080_v1/prepared/structure_contact_maps_v3_clustered.jsonl`
- `experiments/phase2_5080_v1/audits/clustered_split_build_summary_v2.json`
- `datasets/24_hf_nanobody/AVIDa-hIL6/AVIDa-hIL6.csv`
- `datasets/35_nanolas/cursor_sequence/sequence_cursor.csv`
- `datasets/35_nanolas/ligand-binding-sites.csv`
- `model_data/source_summary_v0.csv`

### 3.1 数据角色必须隔离

不同证据不能混成一个二元正负表：

| 数据类型 | 允许的监督 | 禁止的解释 |
| --- | --- | --- |
| 真实复合物结构 | contact、paratope、epitope | 不能自动变成 affinity 标签 |
| 真实 binder/non-binder | pair BCE、target dependence | 不能把 IL-6 真值说成 PVRIG 真值 |
| Kd/affinity | 同靶点、同批次、同家族 ranking | 不做跨实验绝对 Kd 回归 |
| constructed re-pairing | 低权重 contrastive | 不作为实验 non-binder BCE |
| 天然 VHH 大库 | naturalness、scaffold、分布背景 | 不标成 PVRIG non-binder |
| PVRIG docking teacher | geometry surrogate、contact-frequency soft label | 不称为实验阻断真值 |
| 已知 PVRIG 阳性 | 校准、anchor、family holdout | 不进入普通候选池或随机训练拆分 |

## 4. 版本、输入输出和 claim boundary

### 4.1 版本线

| 版本 | 定义 | 当前状态 |
| --- | --- | --- |
| `V3-G0` | mean-pooled generic pair baseline | 正式评估失败，仅作基线 |
| `V3-G1` | residue-level generic contact/site/binding model | 待实现，可与候选生产并行 |
| `V3-P1` | 首批 500 条 Node1 teacher 训练的 PVRIG surrogate | 当前主目标 |
| `V3-P2` | 增加 300-500 条主动学习 teacher 后的冻结版本 | 第二轮目标 |

### 4.2 V3-G1 输入与输出

输入：

```text
VHH amino-acid sequence
antigen amino-acid sequence
optional antigen residue/structure features
IMGT/CDR annotations
```

输出：

```text
paratope_probability_by_residue
epitope_probability_by_residue
residue_pair_contact_matrix
generic_binding_prior
generic_model_uncertainty
```

`generic_binding_prior` 只表示在训练分布内的 target-conditioned 排序先验，不是跨靶点可比的亲和力数值。

### 4.3 V3-P 输入与输出

VHH 输入：

- residue embedding；
- IMGT region / CDR type embedding；
- residue position；
- CDR1/2/3 length；
- 轻量 physicochemical features。

固定 PVRIG 输入：

- PVRIG residue embedding；
- 8X6B 与 9E6Y 两个独立 conformer feature channel；
- core / secondary / soft / non-interface mask；
- SASA、secondary structure 和 residue graph features；
- Patch A/B/C mask。

输出：

```text
pvrig_contact_matrix
pvrig_hotspot_contact_score
pvrig_non_interface_contact_score
pvrig_interface_specificity
cdr1_contact_mass
cdr2_contact_mass
cdr3_contact_mass
p_G1, p_G2, p_G3, p_G4, p_G5
predicted_hotspot_overlap
predicted_total_occlusion
predicted_cdr3_occlusion
predicted_topk_blocker_fraction
seed_mean
seed_std
frontscreen_rank
```

输出表必须带：

```text
claim_boundary = geometry_surrogate_for_frontscreen_only
requires_node1_confirmation = true
```

## 5. V3-G1 通用模型计划

### 5.1 Phase G1：contact/site 预训练

主数据：

```text
SAbDab2/single-domain clustered structure contacts
ZYMScott paratope/epitope
NanoLAS site weak supervision
```

任务：

```text
L_contact
L_paratope
L_epitope
```

执行要求：

- 复用现有全局 cluster split；
- exact VHH、VHH cluster、CDR3 proxy cluster、antigen sequence、antigen cluster 跨 split 重叠必须为 0；
- NanoLAS 弱标签降低权重并单独记录来源；
- 不因样本量大就让弱监督淹没真实结构监督。

### 5.2 Phase G2：真实 binding 与 ranking

真实二元标签：

```text
AVIDa-hIL6
NbBench 中可确认的真实 binder/non-binder 数据
后续通过审计的其他实验 pair
```

Affinity 仅用于：

```text
同 target / family / campaign 内的 pairwise 或 listwise ranking
```

建议总损失起始形式：

```text
L_generic =
    1.00 * L_contact
  + 0.50 * L_paratope
  + 0.50 * L_epitope
  + 0.50 * L_real_binding
  + 0.25 * L_affinity_rank
  + 0.20 * L_target_dependence
```

这些是初始工程权重，必须在 dev split 上调，不是固定科学常数。

### 5.3 target-dependence 验证

通用模型必须通过以下对照：

- VHH 不变、交换 antigen；
- antigen 不变、交换 VHH；
- antigen embedding ablation；
- antigen residue order/局部 patch shuffle；
- VHH-only baseline；
- antigen-only baseline；
- mean-pooled `V3-G0` baseline。

如果交换或删除 antigen 后排序几乎不变，则模型仍可能依赖 framework、长度或数据集风格捷径，不得进入 V3-P 正式特征集。

## 6. PVRIG 候选库生产

### 6.1 Parent scaffold 选择

从现有 design-ready / clean scaffold 库中选 48 个 parent，覆盖：

- parent framework cluster；
- CDR3 长度区间；
- framework family；
- 净电荷；
- 疏水比例；
- developability；
- 与已知阳性 CDR 的距离。

要求：

- parent 本身通过 ANARCI/IMGT 和基础 developability；
- 已知阳性及近邻只用于 leakage 检查，不能成为 parent；
- parent cluster 在候选生成前就分配到 train/dev/test，所有后代继承同一 split。

### 6.2 固定三个 target patch

```text
Patch A：H92 / R95 / R98 / W100 中心热点带
Patch B：K135 / F139 / E141 / S143 / W144 下部界面带
Patch C：跨 Patch A/B 的广覆盖和替代 approach angle
```

Patch 定义必须保存为显式 residue manifest，并同时记录 8X6B、9E6Y 的链和残基映射，不能只写自然语言名称。

### 6.3 设计矩阵

正式规模：

```text
48 parent
× 3 target patch
× 2 主设计模式
× 每组 30-40 条
= 8,640-11,520 条原始设计
```

至少保留：

```text
CDR3-dominant
CDR1 + CDR3
```

`balanced CDR1/2/3` 和 fixed-pose AntiFold/ProteinMPNN 可作为补充分支，但必须记录独立的 `design_method` 和 `design_type`。

先运行 1,000-5,000 条 production pilot，验证：

- provenance 是否完整；
- 重复率；
- ANARCI 成功率；
- CDR 长度/组成是否失控；
- 生成器是否忽略 patch；
- 设计方法是否产生明显风格捷径。

通过 pilot 后再扩到 8,640-11,520 条，不应一开始就批量生产全部候选。

### 6.4 Candidate provenance 最小字段

```text
candidate_id
sequence_sha256
vhh_sequence
parent_scaffold_id
parent_cluster_id
parent_sequence_sha256
design_type
design_method
design_seed
target_patch_id
intended_pose_family
designed_regions
cdr1_before, cdr1_after
cdr2_before, cdr2_after
cdr3_before, cdr3_after
split
calibration_only
leakage_status
```

## 7. 快速硬筛和 teacher 抽样

### 7.1 全库 fast QC

对全部候选运行：

- 标准氨基酸和长度检查；
- sequence SHA256 和精确去重；
- ANARCI/IMGT；
- FR/CDR 完整性；
- 保守 Cys；
- stop、异常字符、低复杂度；
- 严重 CDR glycosylation motif、疏水 run 和明显结构破坏；
- 任一 CDR 与已知阳性 identity `<80%`；正式候选优先 `<75%`。

该阶段不运行：

```text
TNP
全量结构预测
HADDOCK
全局 O(N^2) diversity
```

QC 通过池必须冻结 manifest 和 hash。之后 teacher 抽样只从该 frozen pool 选择，校准专用变体除外。

### 7.2 先做 96 条 teacher pilot

在正式 500 条前，先选 96 条验证端到端 teacher 生产：

- 覆盖三个 patch；
- 覆盖两种主设计模式；
- 覆盖多个 parent cluster 和 CDR3 长度；
- 包含高、中、低 generic/contact heuristic；
- 包含随机 sentinel；
- 不用当前失败的 `V3-G0` 单独主导抽样。

96 条 pilot 的 stop condition：

- 结构、docking、双 baseline 重评分可完整运行；
- 每个 pose 可追溯到 candidate、structure、run 和 config hash；
- Top-K 聚合重复运行结果一致；
- 缺失/失败状态有显式编码，而不是默认为 G5；
- 总耗时和失败率足以估算 500 条规模。

### 7.3 首批 500 条 teacher set

建议分层如下：

| 抽样层 | 数量 | 目的 |
| --- | ---: | --- |
| 通用 contact/interface heuristic 高分 | 140 | 提高成功候选密度 |
| 中等分数 | 90 | 学习决策边界 |
| 低分但 QC 通过 | 50 | 学习真实计算失败模式 |
| embedding/parent/patch 最大多样性 | 100 | 覆盖搜索空间 |
| 随机 QC-pass sentinel | 70 | 估计选择偏差和真实基线 |
| 阳性家族校准变体 | 50 | calibration-only anchor 和局部敏感性 |
| 合计 | 500 | 其中正式候选 450，校准专用 50 |

约束：

```text
同一 parent <= 8-10 条
同一 parent + patch + method <= 3-4 条
所有 target patch 均覆盖
所有 CDR3 长度区间均覆盖
所有主要 design method 均覆盖
```

校准变体必须设置：

```text
calibration_only = true
submission_eligible = false
```

## 8. Node1 teacher 生成与统一聚合器

### 8.1 每条 candidate 的 teacher 流程

```text
NanoBodyBuilder2 单体预测和 QC
→ HADDOCK3 against PVRIG
→ 保留 Top 10 poses 和 cluster 信息
→ 8X6B reference geometry scoring
→ 9E6Y reference-interface rescoring
→ hotspot / total occlusion / CDR contribution
→ pose-level contact extraction
→ deterministic candidate-level aggregation
```

必须记录一个重要事实：当前“双 baseline”主要是同一批 8X6B receptor setup 产生的 pose，再对 8X6B/9E6Y 两个参考界面评分，并不等于两次独立 docking。

因此 teacher 表应显式包含：

```text
pose_generation_receptor
geometry_reference_8x6b_used
geometry_reference_9e6y_used
independent_9e6y_docking = false/true
```

最终 Top 20 候选再补独立 9E6Y receptor docking；它不是第一轮 500 条 teacher 的硬性前置条件。

### 8.2 现有字段

当前 Node1 已能提供：

```text
hotspot_overlap_count
total_vhh_pvrl2_residue_pair_occlusion
cdr3_pvrl2_residue_pair_occlusion
cdr3_occlusion_fraction
class_8x6b
class_9e6y
consensus_class
```

### 8.3 必须新增的候选级字段

```text
top10_AA_fraction
top10_A_or_B_fraction
top10_C_fraction
top10_E_fraction
blocker_supporting_cluster_count
median_hotspot_overlap
median_total_occlusion
median_cdr3_occlusion
median_cdr3_occlusion_fraction
pose_cluster_entropy
best_pose_vs_median_gap
valid_pose_count
failed_pose_count
teacher_completeness
```

不要把无 pose、结构失败或 docking 失败自动编码为 G5。必须区分：

```text
VALID_GEOMETRY_G5
STRUCTURE_FAILED
DOCKING_FAILED
INSUFFICIENT_VALID_POSES
MISSING_REFERENCE_MAPPING
```

### 8.4 Residue-level soft teacher

对每个候选 Top-K pose，输出 VHH residue `i` 和 PVRIG residue `j` 的接触频率：

```text
y_ij = sum_k(w_k * I[(i,j) contacts in pose k]) / sum_k(w_k)
```

`w_k` 可由以下可审计成分组成：

- HADDOCK rank/score 的截断权重；
- pose cluster 去冗余权重；
- 8X6B/9E6Y tier 权重；
- 双 baseline 一致性权重。

要求：

- 权重公式、接触距离阈值和 Top-K 必须冻结在 config 中；
- 同一 cluster 的大量相似 pose 不能淹没其他 cluster；
- contact frequency 是 docking-derived soft label，不是晶体结构真值；
- 训练中其 loss 权重低于真实结构 contact 监督。

输出：

```text
PVRIG-specific contact-frequency matrix
PVRIG epitope-frequency vector
VHH paratope-frequency vector
```

### 8.5 G1-G5 不是简单二分类

现有 11 条阳性系列、109 个 pose 的分布：

| 类别 | pose 数 |
| --- | ---: |
| A/A consensus | 3 |
| single-baseline A | 36 |
| plausible B | 57 |
| E / insufficient geometry | 13 |

因此禁止：

```text
A/A = 1
其他 = 0
```

候选级有序 relevance：

| Tier | 含义 | relevance |
| --- | --- | ---: |
| G1 | A/A 且有多 pose/cluster 支持 | 4 |
| G2 | A/B 或 single-baseline A | 3 |
| G3 | B/B plausible | 2 |
| G4 | binder-like C | 1 |
| G5 | 有效计算但几何不支持 | 0 |

具体 candidate-level tier 阈值不能现在拍脑袋固定。先用现有 11 个阳性 cases 和 36 个 mutant/control cases 跑聚合器审计，再冻结 `PVRIG_TEACHER_SCHEMA_V1` 和 tier rule config。

### 8.6 计划产物

```text
experiments/phase2_5080_v1/data_splits/pvrig_teacher_v1_manifest.csv
experiments/phase2_5080_v1/prepared/pvrig_teacher_v1/candidate_summary.csv
experiments/phase2_5080_v1/prepared/pvrig_teacher_v1/pose_contact_frequency.jsonl
experiments/phase2_5080_v1/prepared/pvrig_teacher_v1/teacher_config.json
experiments/phase2_5080_v1/audits/PVRIG_TEACHER_V1_AUDIT.md
```

每个文件都应保存或伴随保存 SHA256、生成命令、git commit、环境和上游输入 hash。

## 9. PVRIG 专用模型架构

### 9.1 Residue-level backbone

复用 V2.3/V2.4：

```text
VHH residue encoder
        ↓
2 层 bidirectional cross-attention
        ↑
PVRIG residue + conformer encoder
        ↓
biaffine contact-map head
```

8X6B 与 9E6Y 保留独立通道，最后再在 head 中融合；不要在输入阶段直接平均两个结构。

### 9.2 两层模型而不是全量端到端解冻

第一版：

```text
frozen ESM2 / VHHBERT
+ 冻结或低学习率 generic contact backbone
+ 可训练 PVRIG cross-attention / pooling
+ 小型 PyTorch ordinal MLP ranker
```

初期只有约 500 条 PVRIG teacher，不足以支持稳定解冻整个蛋白语言模型。

第一版不使用 LightGBM/LambdaMART 的原因是当前运行环境缺依赖。后续只有在以下条件满足时才比较树模型：

- 用户明确同意新增依赖；
- 输入 feature manifest 已冻结；
- parent-cluster split 完全相同；
- 与 ordinal MLP 做同一 formal test 的公平比较。

### 9.3 建议特征

```text
generic_binding_prior
hotspot_contact_mass
secondary_hotspot_contact_mass
non_interface_contact_mass
interface_specificity
cdr1_contact_mass
cdr2_contact_mass
cdr3_contact_mass
contact_entropy
8x6b tier probabilities
9e6y tier probabilities
consensus tier probabilities
predicted geometry metrics
seed disagreement
cheap developability features
```

Developability 可以参与最终 cascade，但必须单独保留原始字段，避免模型高分掩盖硬性 QC 失败。

### 9.4 建议损失

```text
L_PVRIG =
    1.00 * L_ordinal_tier
  + 0.70 * L_geometry_regression
  + 0.50 * L_within_campaign_rank
  + 0.50 * L_pose_contact_frequency
  + 0.20 * L_positive_anchor
  + 0.30 * L_generic_replay
```

解释：

- `L_ordinal_tier`：保留 G1 > G2 > G3 > G4 > G5 的顺序；
- `L_geometry_regression`：预测连续 occlusion / hotspot 指标；
- `L_within_campaign_rank`：同 parent、patch 或生成批次内排序；
- `L_pose_contact_frequency`：学习 Top-K docking soft contact；
- `L_positive_anchor`：已知阳性对重新计算过的 matched perturbation；
- `L_generic_replay`：每批混入 20%-30% 通用真实 contact/binding 样本，防止遗忘。

权重只是起始值。正式版本必须记录 dev 选择过程，并在 test 冻结后不再调整。

## 10. 已知阳性的正确用法

PVRIG-20、30、38、39、151 等系列只允许进入四个通道：

1. 阈值和阻断机制校准；
2. 低权重 positive anchor；
3. leave-one-family-out 验证；
4. 重新建模和 docking 后的局部突变敏感性分析。

每个 family 可生成 10-20 条：

- 保守突变；
- 芳香残基 alanine scan；
- CDR3 中心扰动；
- CDR1/CDR2 辅助扰动；
- 同组成 CDR shuffle。

但是：

- 突变不能人工标为负；
- 必须重新建模、docking 和双 baseline 评分；
- 全部设置 `calibration_only`；
- 不进入候选库；
- 不参与普通随机拆分；
- 与已知阳性 CDR 的相似度不作为模型输入，只作为模型外 hard gate。

## 11. 数据划分和泄漏控制

### 11.1 通用数据

至少隔离：

```text
exact VHH
VHH sequence cluster
CDR3 cluster
exact antigen
antigen sequence/family cluster
PDB complex
epitope patch
```

constructed re-pairing 只能停留在 contrastive 通道，不能因为 split 无重叠就被升级为实验 negative。

### 11.2 PVRIG teacher

主 split 单位：

```text
parent_framework_cluster
```

在候选生成前分配：

```text
70% parent clusters → train
15% parent clusters → dev
15% parent clusters → formal test
```

同一 parent 的以下对象必须在同一 split：

- 所有 design seeds；
- 所有 CDR 变体；
- 所有近邻 CDR3；
- 所有结构和 docking poses；
- 所有 active-learning 后续样本。

另设 challenge block：

- 完整留出一个生成方法，或
- 完整留出一批 parent family。

所有 bootstrap confidence interval 以 parent cluster 为重采样单位，不能按 candidate 行独立 bootstrap。

### 11.3 Positive family holdout

五个阳性家族轮流：

```text
4 个 family 用于校准
1 个 family 完全留出
```

评估留出 family 是否排在以下对象之前：

- matched perturbation；
- 随机天然 VHH；
- binder-like C；
- 有效 G5；
- 计算失败样本之外的真正低几何候选。

该结果是机制校准证据，不与 parent-cluster formal test 混成一个总指标。

## 12. 正式验收和反捷径测试

以下门槛是项目工程门槛，不是行业公认真值。

### 12.1 主指标

| 指标 | 建议门槛 |
| --- | ---: |
| G1+G2 Recall@Top 20% | >=70% |
| EF@Top 10% | >=3x random |
| NDCG@100 | 显著超过最强基线 |
| geometry composite Spearman | >=0.35-0.40 |
| 三 seed Top-100 共同候选 | >=60 |
| hotspot shuffle 后 EF 下降 | >=25% |

最重要的业务指标是：

> 只允许对 20% 候选运行昂贵 Node1 时，模型能否找回大多数真正的 G1/G2 teacher candidates。

### 12.2 必须比较的基线

```text
random
cheap-QC-only
generic_binding_prior only
hotspot contact mass only
VHH-only
mean-pooled V3-G0
simple linear/MLP feature head
```

只有超过最强基线才有资格改变 full-QC shortlist。

### 12.3 Formal gate

```text
三个 seed 均优于最强 baseline
ensemble delta 的 parent-cluster bootstrap 95% CI 下界 > 0
permutation p < 0.05
null-label 训练不通过
VHH-only / target-ablation 不通过正式门槛
```

“null/shuffle 不通过”是好结果：表示模型没有在无效标签或失去 target 信息时仍虚假获得高分。

### 12.4 反捷径测试的分层解释

对 `V3-G1`：

- antigen swap；
- antigen ablation；
- unseen antigen family；
- unseen epitope / fold challenge。

对 `V3-P1/P2`：

- hotspot mask shuffle；
- core/secondary/non-interface mask 交换；
- 8X6B-only、9E6Y-only 和双 conformer 消融；
- patch label shuffle；
- design-method holdout；
- parent-family holdout。

因为 V3-P 只有一个 PVRIG target，它本身不能证明跨靶点泛化；跨靶点 claim 只能由 V3-G 数据和测试支持。

### 12.5 失败回退

若 `V3-P1` formal gate 失败：

- 不改变 Node1 现有排序；
- 不阻塞候选结构和 docking；
- 使用 QC + contact heuristic + diversity 的分层抽样；
- 保留模型仅作分析列；
- 将失败原因用于下一批 active-learning 采样。

这保证模型开发不会成为比赛主线的单点阻塞。

## 13. 主动学习和 V3-P2

`V3-P1` 冻结后，从剩余候选中再选 300-500 条：

```text
高预测分
高不确定性
seed/head 分歧大
generic binding prior 高但 geometry surrogate 低
geometry surrogate 高但 generic binding prior 低
新 parent / 新 patch / 新 design method
随机 sentinel
```

不能只选高分样本。第二轮必须保留随机 sentinel 和新空间样本，否则无法评估 selection bias。

主动学习后：

- 所有新增候选继承 parent-cluster split；
- formal test parent clusters 不参与主动选择和再训练；
- 训练集扩展后冻结为 `V3-P2`；
- 如需解冻 cross-attention，学习率应比 ranker 小 10-20 倍；
- 最多只尝试语言模型顶部一层解冻，不直接全量 fine-tune。

## 14. 与 Node1 生产漏斗的衔接

对全 8,000-12,000 条候选输出前筛表后，进入 full QC 的配额：

```text
80%：frontscreen_rank 最高
10%：uncertainty / seed disagreement 最高
10%：parent / patch / method diversity exploration
```

建议数量：

```text
全库 fast QC survivor：约 5,000-9,000
进入 Node1 full QC：约 800-1,000
full QC survivor：约 300-500
geometry pool：约 150-250
单体结构复核后：约 80-120
HADDOCK/遮挡主池：约 60-100
最终提交：50 条 portfolio
```

`frontscreen_rank` 只决定昂贵计算预算，不直接决定最终提交。

最终 50 条仍需按以下维度组合选择：

- G1/G2/G3 几何层级；
- generic binding/contact prior；
- developability 和表达风险；
- parent/CDR3/patch/design method 多样性；
- pose cluster 稳定性；
- model uncertainty；
- 独立 9E6Y docking 复核结果。

## 15. 分阶段执行表

### Phase 0：冻结合同，1-2 个工作日

产物：

```text
PVRIG_TEACHER_SCHEMA_V1
G1_G5_RULES_V1
PVRIG_PATCH_MANIFEST_V1
CANDIDATE_PROVENANCE_SCHEMA_V1
PARENT_CLUSTER_SPLIT_V1
```

完成条件：字段、缺失状态、hash、split 和 claim boundary 均有机器可读定义。

### Phase 1：实现 teacher 聚合器，2-4 个工作日

先用现有：

```text
11 positive cases / 109 poses
36 mutant-control cases / 357 poses
```

验证：

- Top-K 聚合；
- cluster 去冗余；
- 双 baseline class；
- 连续 geometry summary；
- contact-frequency export；
- 重复运行确定性；
- 缺失和失败状态。

这是当前第一优先级，先于训练 `V3-P1`。

### Phase 2：48 个 parent、patch 和设计 pilot，3-7 个工作日

- 选 48 个 parent；
- 冻结 Patch A/B/C 映射；
- 生成 1,000-5,000 条 pilot；
- 跑 fast QC；
- 审计 provenance、重复率、ANARCI 成功率和生成器偏差；
- 通过后扩到 8,640-11,520 条。

### Phase 3：96 条 teacher pilot，按 Node1 实测排期

- 完整跑单体结构、HADDOCK、Top-10、8X6B/9E6Y；
- 输出 teacher audit；
- 估算 500 条吞吐、失败率和存储量；
- 修正聚合器，不训练正式模型。

### Phase 4：500 条首批 teacher，按 Node1 实测排期

- 按 140/90/50/100/70/50 分层抽样；
- 冻结 teacher manifest；
- 跑完整 Node1 teacher；
- 冻结 `pvrig_teacher_v1` 数据包和 audit。

### Phase 5：训练和冻结 V3-P1，2-5 个工作日

- frozen backbone；
- ordinal MLP；
- 至少 3 seeds；
- parent-cluster formal test；
- target/hotspot/design-method ablation；
- 与全部 baseline 比较；
- PASS 才允许影响 shortlist。

### Phase 6：主动学习和 V3-P2

- 再选 300-500 条；
- 保留 test cluster 完全隔离；
- 重新训练并冻结 `V3-P2`；
- 重跑同一 formal gate。

### Phase 7：全库评分和 Node1 生产筛选

- 80/10/10 配额进入 full QC；
- 150-250 条 geometry pool；
- 60-100 条 docking 主池；
- Top 20 补独立 9E6Y docking；
- 形成最终 50 条多样化 portfolio。

## 16. 并行关系和真正关键路径

可以并行：

```text
A. V3-G1 的真实 binding/contact 训练
B. 48 parent 选择与候选设计 pilot
C. 现有 calibration pose 的 teacher 聚合器开发
```

有依赖、必须串行：

```text
teacher schema
→ aggregator 在现有 11+36 cases 上通过审计
→ 96 条端到端 pilot
→ 500 条正式 teacher
→ V3-P1
→ 300-500 条主动学习
→ V3-P2
```

所以当前瓶颈不是“再设计一个更复杂网络”，而是：

```text
把 Node1 pose 结果变成确定、无泄漏、可训练、可复现的 teacher 数据集
```

## 17. 接下来立即执行的三件事

### 第一件：冻结 teacher schema 和聚合规则

先定义候选级、pose 级、contact-frequency 级字段，以及失败状态和 hash。随后用现有 466 个 calibration poses 做回放。

完成标志：

```text
candidate_summary.csv
pose_contact_frequency.jsonl
PVRIG_TEACHER_V1_AUDIT.md
```

能从相同输入重复得到完全相同的 hash 和统计结果。

### 第二件：选定 48 个 parent 并冻结生成矩阵

不要先训练 `V3-P`。先完成：

- parent cluster coverage；
- parent leakage exclusion；
- Patch A/B/C residue mapping；
- 两种主设计模式；
- candidate provenance schema。

完成标志：可生成 1,000-5,000 条 pilot，并能从每条序列追溯到 parent、patch、method 和 seed。

### 第三件：跑 96 条 teacher pilot

96 条的目的不是追求模型指标，而是发现：

- 结构失败模式；
- docking 配置问题；
- Top-K/cluster 统计是否稳定；
- 8X6B/9E6Y 映射是否一致；
- 单条和 500 条的实际成本。

只有 pilot 通过后才投入 500 条 teacher 预算。

## 18. 不建议现在做的事情

- 不继续把 mean-pooled `V3-G0` 包装成生产模型；
- 不把 V2.3/V2.4 pair MRR 当作已验证能力；
- 不在 teacher manifest 之前训练 PVRIG head；
- 不把 A/A 之外全部标负；
- 不把 docking 失败当作真实 G5；
- 不用已知阳性相似度作为模型输入；
- 不只抽当前模型 Top candidates；
- 不跨 target 回归统一绝对 Kd；
- 不在初期 500 条 teacher 上全量解冻 ESM2/VHHBERT；
- 不为 LightGBM 临时增加依赖，除非后续明确批准并做公平比较；
- 不让 `V3-G1` 研发阻塞 Node1 teacher 生产和比赛漏斗。

## 19. 外部证据边界

以下文献支持的是方法和验证原则，不替代本地正式评估：

1. AVIDa-hIL6：573,891 个 VHH-antigen labeled pairs，包含 WT IL-6 和 30 个突变体。  
   https://arxiv.org/abs/2306.03329
2. AgForce：支持检查 antigen blindness、framework shortcut 和 antigen-conditioning 是否真正生效。  
   https://arxiv.org/abs/2605.21610
3. AntiFold：支持在已有结构/pose 上做抗体专用 inverse-folding 局部优化，不等于独立发现新表位。  
   https://arxiv.org/abs/2405.03370
4. CHIMERA-Bench：支持 unseen epitope、unseen antigen fold 和 temporal target 等更严格划分原则。  
   https://arxiv.org/abs/2603.13431

本项目的 PVRIG claim 仍以本地 Node1 teacher、已知阳性校准、parent-cluster formal test 和最终实验结果为准。

## 20. 最终架构

```text
真实通用数据
SAbDab/ZYMScott contacts + AVIDa/NbBench real labels + within-target affinity rank
                              ↓
V3-G1 residue-level generic backbone
paratope + epitope + contact + generic binding prior
                              ↓
冻结或低学习率通用表征
                              ↓
PVRIG fixed features
8X6B channel + 9E6Y channel + hotspot/patch masks
                              ↓
PVRIG-specific cross-attention / pooling
                              ↓
Node1 teacher
Top-K poses + cluster support + continuous occlusion + contact frequency + G1-G5
                              ↓
PyTorch ordinal MLP + 3-seed uncertainty
                              ↓
V3-P1 / V3-P2 frontscreen rank
                              ↓
80% exploitation + 10% uncertainty + 10% exploration
                              ↓
Node1 full QC / structure / HADDOCK / PVRL2 occlusion
                              ↓
最终 50 条 portfolio
```

## 21. 一句话决策

> 接受“V3-G 通用能力 + V3-P PVRIG 专用代理 + Node1 昂贵验证”的总体架构；立即优先建设确定性的 Node1 teacher 数据层，并将当前 mean-pooled V3 降级为 `V3-G0` 失败基线。候选生成、teacher 聚合和 96 条 pilot 是下一步，网络复杂化不是下一步。
