# PVRIG V3-P2 Docking Gold 训练与数据标准

更新时间：2026-07-13（Asia/Shanghai）

状态：`DRAFT_PENDING_DUAL_DOCKING_PILOT_AND_FREEZE`

当前执行进度：

```text
P2 planning inventory                    = PASS
dual-docking pilot64 selection           = PASS
pilot manifest unique sequences          = 64/64
replicate-seed candidates                = 16
independent 8X6B/9E6Y pilot docking      = NOT_STARTED
P2 preregistration                       = DRAFT_NOT_FROZEN
```

已生成的 pilot 入口：

```text
experiments/phase2_5080_v1/data_splits/pvrig_v3_p2/dual_docking_pilot64_manifest.csv
experiments/phase2_5080_v1/data_splits/pvrig_v3_p2/dual_docking_pilot64.fasta
experiments/phase2_5080_v1/audits/phase2_v3_p2_dual_docking_pilot_selection_audit.json
```

## 一、版本决策

V3-P2 不再尝试证明一个跨抗原通用的 `target-conditioned blocker model`。比赛当前真正需要的是一个更窄但可验证的模型：

```text
PVRIG 固定靶点 sequence-to-docking distiller
```

它的任务是：

```text
输入候选 VHH 序列
→ 预测该序列在冻结 Node1 docking 协议下的几何排序、G1-G5 层级和不确定性
→ 为昂贵 docking 分配计算预算
→ 最终提交仍由真实 Node1 docking 金标准决定
```

这里的“金标准”严格定义为：

> Node1 冻结协议产生的、可复现的、双 PVRIG 构象 docking 几何标签，是本项目的计算金标准。它不是 BLI、Kd 或实验功能阻断真值。

P2 的部署名称建议为：

```text
PVRIG-DockDistill-v2
```

P2 不输出“实验阻断概率”，而输出：

```text
predicted_docking_relevance
predicted_G1_to_G5_probabilities
predicted_geometry_metrics
predicted_contact_frequency
ensemble_uncertainty
frontscreen_rank
```

## 二、为什么必须改成固定靶点 docking 蒸馏

P1 已经证明两个事实。

第一，模型确实能够学习 docking teacher：

```text
ensemble NDCG = 0.9877
relevance Spearman = 0.5215
label shuffle 后明显下降
```

第二，P1 不能证明排序依赖 PVRIG target channel：

```text
hotspot shuffle EF drop = 0%
antigen ablation EF drop = 0%
target permutation EF drop = 0%
VHH-only EF drop = 12.5%
```

由于所有 prospective teacher 都面对同一个 PVRIG，抗原输入在样本之间几乎不变化。模型可以仅凭 VHH、parent 和生成器风格降低损失。继续把“target-conditioned”作为生产声明，不符合现有证据。

对比赛而言，更诚实也更有效的目标是：

1. 明确靶点固定为 PVRIG；
2. 直接蒸馏冻结 docking 协议；
3. 用新 parent、新方法和正式 holdout 检查序列到 docking 的泛化；
4. 把 generic binding、developability 和 docking 维持为三个独立证据通道。

## 三、现有数据盘点

机器可读盘点位于：

```text
experiments/phase2_5080_v1/audits/phase2_v3_p2_planning_inventory.json
```

### 3.1 Prospective candidate 数据

```text
正式 fast-gate eligible = 7,087
已进入 Teacher500       = 500
尚未做 teacher docking  = 6,587
```

Teacher500 仅包含一种 generation method：

```text
RFantibody_RFdiffusion_ProteinMPNN
```

### 3.2 Scaffold 余量

Top 200 scaffold 中：

```text
已使用 parent clusters = 40
尚未使用 clusters       = 160
```

因此可以建立真正不与 P1 parent 重叠的新 holdout。

### 3.3 当前 Teacher500 的 shortcut 证据

不同 parent 的稳定 G1+G2 比例为：

```text
最低 = 8.3%
最高 = 100%
```

说明 parent framework 与 docking tier 高度相关。P2 必须使用 parent-group validation、parent-balanced sampling 和 within-parent ranking。

另外：

```text
Spearman(generic_binding_prior, teacher_relevance) = -0.3168
Spearman(cheap_qc_score, teacher_relevance)        =  0.0718
```

因此：

1. generic prior 不进入 P2 docking head；
2. cheap QC 不进入 docking target；
3. 两者只在模型之外用于最终 cascade 和 portfolio 约束。

### 3.4 已知阳性与突变校准数据

当前已有：

```text
11 条已知阳性 VHH
5 个阳性家族：20 / 30 / 38 / 39 / 151
36 条阳性相关 reference/mutant controls
47 条 calibration-only candidate summaries
466 个有效 docking poses
```

基于现有稳定 docking tier，可以构造 25 对严格有序的：

```text
known positive > same-family lower-docking control
```

这些数据量不足以作为普通监督集，但足以作为低权重 positive-anchor lane 和 leave-one-family-out 诊断。

## 四、阳性数据应该怎样让模型学习

阳性数据不能简单复制到训练表中并标记为 `1`。正确使用分四层。

### 4.1 Docking prototype

从每个阳性家族的 top poses 聚合：

```text
PVRIG epitope-frequency vector
VHH paratope-frequency vector
VHH-PVRIG contact-frequency matrix
hotspot overlap distribution
occlusion distribution
approach/cluster distribution
```

模型学习的是成功案例的 docking 几何分布，而不是阳性序列相似度。

### 4.2 Positive-anchor ranking

只使用 docking 已验证的有序对：

```text
positive score > matched control score
```

不允许因为一个突变是 alanine scan 就自动标负；所有 pair 的次序必须由冻结 docking gold label 决定。

建议损失权重：

```text
positive_anchor_weight = 0.15
```

它是辅助损失，不得压过 prospective docking teacher。

### 4.3 五家族 leave-one-family-out

开发阶段做 5 folds：

```text
4 个阳性家族可用于 anchor
1 个完整家族只做诊断
```

评估模型能否在未见阳性家族上保持 docking-ordered pair 的方向，而不是只记住某个 CDR motif。

### 4.4 Leakage exclusion

以下规则保持不变：

```text
known-positive similarity 不是模型输入
exact positive 不进入 submission pool
near-positive control 不进入 submission pool
正式候选任一 CDR identity 必须 <80%，主提交目标 <75%
positive-neighborhood 全部 calibration-only
```

## 五、P2 docking gold label 标准

### 5.1 三个质量级别

#### DG-A：正式 gold label

必须满足：

```text
独立 8X6B receptor docking
独立 9E6Y receptor docking
每个 receptor 至少 8 个有效 selected poses
每个 receptor 至少 2 个 pose clusters
所有 pose 均有 geometry 和 residue-contact 输出
无 tolerance relaxation
monomer sequence/geometry QC pass
```

P2 新 open-development 数据和正式 test 只接受 DG-A。

#### DG-B：现有 silver label

```text
8X6B-generated poses
+ 8X6B geometry
+ 9E6Y reference-interface rescoring
```

现有 Teacher500 属于 DG-B，可进入训练，但默认样本权重为：

```text
silver_weight = 0.50
```

#### DG-C：不完整标签

包括：

```text
任一 receptor <8 poses
contact extraction incomplete
只有单一 pose cluster
使用放宽 tolerance
输入或 provenance 缺失
```

DG-C 不进入正式训练或 test，必须重跑或只保留为审计记录。

### 5.2 Pose relevance

继续使用已有有序含义：

```text
A/A consensus                 = 4
single-baseline A or A/B      = 3
plausible B                   = 2
binder-like C                 = 1
evidence insufficient E       = 0
```

不能使用 `A/A=1、其他=0`。

### 5.3 Candidate docking relevance

对每个 receptor 独立计算 cluster-balanced relevance：

```text
w_pose = 1 / log2(rank + 1) / poses_in_same_cluster
R_receptor = sum(w_pose * pose_relevance) / sum(w_pose)
```

双构象连续金标准为：

```text
R_gold = mean(R_8X6B, R_9E6Y)
conformer_disagreement = abs(R_8X6B - R_9E6Y)
```

`conformer_disagreement` 单独作为不确定性标签，不从 `R_gold` 中用任意权重扣分。

### 5.4 Stable G1-G5

将两次独立 docking 的 pose 合并，但 cluster ID 必须带 receptor 前缀。按至少两个独立支持 cluster 的规则形成 stable tier：

```text
G1 = 至少两个 cluster 支持 relevance >=4
G2 = 否则至少两个 cluster 支持 relevance >=3
G3 = 否则至少两个 cluster 支持 relevance >=2
G4 = 否则至少两个 cluster 支持 relevance >=1
G5 = 其他
```

排序主目标使用连续 `R_gold`，stable tier 用于有序分类和解释。

## 六、先做 64 条 dual-docking pilot

在冻结 P2 label builder 前，先运行 protocol pilot：

| 来源 | 数量 | 目的 |
| --- | ---: | --- |
| 已知阳性 | 11 | 保证成功家族全部覆盖 |
| matched mutant/control | 21 | 建立局部敏感性和 anchor 对 |
| Teacher500 分层样本 | 32 | 覆盖 G1/G2/G3/G5、parent 和 patch |
| 合计 | 64 | 锁定 dual-docking gold 协议 |

所有 64 条执行独立 8X6B 和 9E6Y docking。另从中冻结 16 条执行重复 docking seed，用于估计计算金标准本身的可复现性。

Pilot 通过条件：

```text
64/64 DG-A complete
16 replicate candidate R_gold Spearman >=0.70
16 replicate candidate stable-tier weighted kappa >=0.60
contact extraction failures = 0
tolerance relaxation = false
```

如果未通过，先修正 docking protocol 或 label aggregation，不开始 P2 训练。

## 七、P2 新数据规模与组成

### 7.1 Open-development 新增 320 条 DG-A

#### Block A：现有 40 parent 的 active-learning 补点，160 条

每个 parent 选择 4 条：

```text
1 条 P1 predicted high
1 条 P1 decision boundary
1 条 P1 predicted low but QC-pass
1 条 P1 seed-disagreement / model-conflict
```

目标是补足同一 parent 内的 tier variation，降低 parent shortcut。

#### Block B：10 个新 development parent，80 条

从尚未使用的 160 个 Top200 clusters 中冻结 10 个 parent，每个 8 条：

```text
4 条 RFantibody H3/H1H3 designs
4 条在冻结 pose family 上的 AntiFold/ProteinMPNN local redesign
```

#### Block C：fixed-pose redesign，80 条

从 Teacher500 中选择 20 个不同 parent/patch/pose-family seeds，每个生成 4 条局部 redesign：

```text
20 × 4 = 80
```

这些序列用于学习同一 geometry family 内的序列敏感性，也为 method diversity 提供第二种来源。

### 7.2 Positive-neighborhood v2，60 条 calibration-only DG-A

五个阳性家族各 12 条：

```text
4 条保守 CDR 变体
4 条 docking-contact residue 扰动
4 条同组成 shuffle / disruptive controls
```

全部重新运行 dual docking。标签完全来自 docking，不按设计意图预设。

### 7.3 新 formal holdout，160 条 DG-A

从未使用的 Top200 clusters 冻结 16 个新 parent：

```text
16 parents × 10 candidates = 160
```

要求：

```text
与 open-development parent cluster overlap = 0
与 open-development exact sequence overlap = 0
与 open-development CDR3 >=80% cluster overlap = 0
所有 sequence/provenance 在 docking 前冻结
所有 labels 对 trainer 保持 sealed
```

Primary formal holdout 使用与生产候选一致的 RFantibody H3/H1H3 设计，以测试 unseen-parent 泛化。

另可建立 40 条新方法 challenge block，但它只作辅助诊断，不替代 160 条 primary formal test。

### 7.4 P2 最终数据账本

```text
现有 Teacher500 DG-B                    = 500
新增 open-development DG-A              = 320
现有 positive/reference/mutant calibration = 47
新增 positive-neighborhood DG-A          = 60
新 formal DG-A sealed                    = 160
------------------------------------------------
总候选记录                              = 1,087
其中 prospective open train/dev          = 820
calibration-only                          = 107
untouched formal test                     = 160
```

## 八、P2 模型架构

### 8.1 主模型只蒸馏 docking

输入：

```text
VHH ESM2 residue embeddings
exact CDR type masks
frozen V2.3 residue/contact representation
fixed PVRIG residue embedding
fixed 8X6B / 9E6Y structure channels
```

禁止进入 docking head 的字段：

```text
generic_binding_prior
cheap_qc_score
known-positive sequence similarity
parent_id / parent cluster one-hot
generator ID one-hot
```

其中 generic prior 与 QC 在模型之外保留，不能污染 docking target。

### 8.2 输出头

```text
ordered G1-G5 probabilities
R_gold regression
R_8X6B / R_9E6Y regressions
conformer disagreement regression
hotspot / total / CDR3 occlusion regressions
dual-conformer contact-frequency heads
paratope / epitope heads
ensemble uncertainty
```

### 8.3 训练损失草案

```text
1.00 × R_gold continuous ranking/regression
0.80 × within-parent / within-campaign rank loss
0.70 × ordered G1-G5 loss
0.50 × dual-conformer geometry regression
0.50 × contact-frequency loss
0.30 × conformer consistency/disagreement loss
0.50 × generic contact/paratope replay
0.15 × docking-validated positive-anchor loss
```

最终权重只能在 open-development parent-group CV 上选择，formal labels 不得参与。

### 8.4 Parent shortcut 控制

不使用 parent ID 作为输入，但仍需：

```text
parent-balanced batch sampler
每个 parent/tier 的 inverse-frequency sample weight
within-parent ranking pairs
5-fold parent-group cross-validation
parent-only 和 CDR3-only baseline
```

P2 生产模型不是通过 antigen-ablation gate 验收，而是通过 unseen-parent、unseen-sequence 和 method-stratified docking enrichment 验收。

## 九、训练与冻结流程

### Phase P2-0：冻结 gold protocol

```text
64 dual-docking pilot
→ reproducibility gate
→ 冻结 receptor prep、restraints、seeds、top-k、cluster 和 label builder
```

### Phase P2-1：建立 open-development 数据

```text
500 DG-B Teacher500
+ 320 DG-A prospective
+ 107 calibration-only
```

旧 P1 formal test 已经解封，因此其 75 条可以并入 P2 open-development，但不能再作为 P2 formal evidence。

### Phase P2-2：开发期模型选择

```text
5-fold parent-group CV
3 seeds per candidate architecture
只使用 open-development labels
选择 architecture / loss / early stopping / uncertainty policy
```

### Phase P2-3：冻结正式版本

在 formal unseal 前冻结：

```text
data manifest and SHA256
parent/CDR3 cluster assignments
docking protocol hash
label builder hash
model config
loss weights
three seeds
baselines
metrics and thresholds
formal evaluator hash
```

### Phase P2-4：一次性 formal evaluation

```text
160 formal candidates
16 untouched parent clusters
evaluator-only label join
one-shot report
```

看过结果后不得修改同一版本阈值。

## 十、正式验收标准

### 10.1 Docking label 质量门

```text
formal DG-A completeness = 160/160
contact extraction failures = 0
tolerance relaxation = false
parent overlap = 0
exact sequence overlap = 0
CDR3 >=80% cluster overlap = 0
```

### 10.2 Primary model metrics

将 formal `R_gold` 最高的 20% 定义为 `formal_top_quintile`。这使阳性基率固定为 20%，所有预算指标数学可达。

冻结门建议为：

| 指标 | 门槛 |
| --- | ---: |
| NDCG | ensemble 超过最强 dev-selected baseline，parent-cluster bootstrap 95% CI lower >0 |
| R_gold Spearman | >=0.40 |
| Precision@Top20% budget，对 true top quintile | >=0.50 |
| Recall@Top30% budget，对 true top quintile | >=0.70 |
| Paired parent-cluster permutation | p<0.05 |
| 单种子 | 至少 2/3 seeds 超过最强 baseline |
| Label shuffle | 不得通过 primary gate |
| Generic contact replay | 三种子全部 retention >=90% |

这些阈值在 pilot 和 open-development 完成后必须再次执行数学可达性检查，然后冻结；不能在 formal unseal 后修改。

### 10.3 Positive-anchor diagnostics

```text
leave-one-positive-family-out strict-pair concordance >=70%
有至少 5 个 strict pairs 的家族不得低于 55%
positive similarity 不得作为输入
```

该项用于检查模型是否学习到成功 docking 几何邻域，不把少量阳性当成普通大样本分类问题。

### 10.4 Shortcut baselines

必须报告并比较：

```text
parent-only baseline
CDR3-only baseline
cheap-QC baseline
generic-prior baseline
P1 ensemble baseline
frozen-contact hotspot baseline
label-shuffle null
```

P2 只有在 unseen-parent formal test 上超过这些基线，才能进入生产前筛。

## 十一、P2 通过后如何用于比赛

P2 只分配 docking 预算，不直接选择最终 50 条。

建议配额：

```text
70%：predicted docking relevance Top
15%：ensemble uncertainty / model disagreement
15%：parent / patch / CDR3 / method diversity exploration
```

这些候选进入真实 Node1 docking。最终提交排序使用：

```text
第一层：hard QC / CDR novelty / structure sanity
第二层：真实 docking gold tier 和 R_gold
第三层：generic binding prior、表达和 developability
第四层：portfolio diversity constraints
```

模型预测不能覆盖真实 docking 结果；generic prior 也不能覆盖 docking tier。

## 十二、立即执行顺序

1. 冻结 64 条 dual-docking pilot manifest；
2. 建立独立 8X6B/9E6Y runner 和 DG-A completeness audit；
3. 实现 `PVRIG docking gold v2` label builder；
4. pilot 通过后冻结 320 open-development selection manifest；
5. 同时冻结 16 个新 formal parent 和 160 条 blinded sequence manifest；
6. 运行 open-development docking，formal labels 继续 sealed；
7. 实现不含 generic prior/QC 的 P2 docking distiller；
8. 完成 parent-group CV、positive-family LOFO 和 baseline comparison；
9. 冻结 P2 preregistration；
10. 三种子正式训练后一次性解封 160 条 formal labels；
11. 若通过，才将 P2 用于全库 docking 预算分配；
12. 最终 50 条仍按真实 docking gold + developability + diversity 选择。

## 十三、停止条件

在以下条件满足前，不开始 P2 formal training：

```text
64 条 pilot reproducibility gate PASS
DG-A label builder frozen
320 open-development complete
160 formal sequence manifest frozen
formal labels sealed
positive-anchor pairs frozen
parent/CDR3 leakage audit PASS
metrics 数学可达性审计 PASS
```

这一路线既让少量已知阳性真正参与学习，又避免模型退化成“寻找与阳性最相似的序列”；同时把用户指定的 docking 金标准放在模型训练、正式验收和最终比赛选择的中心位置。
