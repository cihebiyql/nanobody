# V2.8：V4-I 扩充到 open3388 的训练与 early-enrichment 方案

## 0. 决策摘要

最新可用资产不是“约 4000 条独立序列”，而是：

```text
V4-I Stage1：3924 个 Docking job
              = 1962 条唯一候选 × 2 个受体

1962 条候选
├── 1881 条双受体候选级连续监督可用
└── 81 条技术不完整，仅可作 label-free/失败模式记录

其中 500 条进入 Stage2 重复：
├── 476 条形成 DUAL_2_SEED
└── 24 条仍按 paired-seed 口径为 DUAL_1_SEED
```

与现有 open1507 按 `sequence_sha256` 严格去重后：

```text
1507 + 1881 = 3388 条唯一监督序列
31 个 parent framework clusters（没有增加独立 parent 数）
```

因此结论是：**可以并入新一轮 development 训练，预期最可能改善已知 scaffold 内的 sibling 排序和生成器覆盖；不能把行数增加解释为独立生物学样本量同幅增加，也不能据此声称 unseen-parent 泛化已经解决。**

为避免把“数量增加”和“标签质量下降”混在一起，新版不只建立一个表，而是冻结三档数据：

```text
open1507：现有参考
open2007：open1507 + V4-I Stage2 500（476双seed、24单seed）
          = 4014条 receptor-specific scalar targets
open3388：open1507 + V4-I 全部1881条可分析Stage1，Stage2可用处覆盖
          = 6776条 receptor-specific scalar targets
```

用户记忆中的“约4000条”若按 R8/R9 两个受体标签行计数，对应 **open2007**；若按当前所有可用唯一VHH计数，最大可用是 **3388 条**。训练应先比较 open2007，再决定低可靠单seed的1381条是否带来额外收益。

证据边界保持：预测的是冻结协议下的双受体 computational Docking geometry，不是结合、Kd、实验阻断概率或 Docking Gold。V4-F/test32、formal outer truth、legacy128 均不得访问或合并。

---

## 1. 数据资产与口径

### 1.1 现有 open1507

| 来源 | 候选数 | 证据 |
|---|---:|---|
| V4-D open multi-seed | 226 | 多 seed 独立双受体 |
| V4-H adaptive | 1281 | 123 三 seed、241 两 seed、917 单 seed |
| 合计 | 1507 | 31 parent clusters |

### 1.2 新 V4-I

| 项目 | 数量 |
|---|---:|
| Dockable candidate | 1962 |
| Stage1 jobs | 3924 |
| Stage1 job success | 3921 |
| Stage1 candidate scalar valid | 1881 |
| Technical incomplete | 81 |
| Stage2 selected candidates | 500 |
| Stage2 repeat jobs | 1000 |
| Stage2 job success | 999 |
| Final DUAL_2_SEED candidates | 476 |
| Final DUAL_1_SEED candidates | 1405 |

V4-I 的四个生成/计算 lane：

```text
LATENT970          964
MPNN_NODE1         251
MPNN_NODE23        500
MPNN_NODE23_EXTRA  247
```

这些 lane 只可用于分层审计、采样和 source-stratified 指标，不得把 lane/candidate/parent ID 编码喂给模型。

### 1.3 关键风险

1. 新增 1881 条全部来自现有的 11 个高密度 parent clusters，新增 parent 数为 0。
2. V4-I 是 adaptive/high-yield 搜索结果，不是从整个候选空间均匀抽样。
3. Stage2 的 500 条由 Stage1 排名选择，repeat-seed 噪声估计偏向高分区。
4. V4-H 与 V4-I `protocol_core_sha256` 不同，但已观察到 protocol spec 的语义差异只涉及 panel 数量、job 数量和 smoke candidate；仍必须生成正式 compatibility receipt，不能只凭观察直接合并。
5. 新数据会让 11 个 parent 的行数远高于其余 20 个 parent；普通 per-row loss 会严重偏向这些 parent。

---

## 2. 新合并器的硬性契约

建议新增而不是修改旧 builder：

```text
build_pvrig_v2_8_open3388.py
validate_pvrig_v2_8_open3388.py
test_build_pvrig_v2_8_open3388.py
```

### 2.1 输入必须 hash-bound

至少绑定：

```text
open1507 supervised table
V4-I candidates.tsv
V4-I Stage1 candidate ranking
V4-I Stage1 terminal receipt
V4-I Stage2 500-candidate ranking
V4-I Stage2 release receipt
V4-I input receipt / monomer manifest
V4-H 与 V4-I protocol specs、rules、reference/hotspot hashes
```

禁止路径或内容匹配：

```text
V4-F / test32 / sealed / formal_outer_truth / legacy128
```

### 2.2 候选级聚合

对 V4-I：

1. Stage1 ranking 建立 1962 条 candidate ledger。
2. `TECHNICAL_INCOMPLETE` 的 81 条输出到单独无标签表；R8/R9/Rdual/weight 必须为空。
3. Stage2 500 条按 candidate ID 覆盖 Stage1 的 scalar evidence：
   - R8 = 各自成功 8X6B seed 的中位数；
   - R9 = 各自成功 9E6Y seed 的中位数；
   - `Rdual = exact min(R8,R9)`；
   - paired seed count = 两个 receptor 成功 seed 集合的交集大小；
   - 476 条为 DUAL_2_SEED，24 条保持 DUAL_1_SEED；不得因单侧有两个 seed 就升级整体 tier。
4. 其余 1381 条使用 Stage1 seed917 单 seed标签。
5. 严禁用 `confidence_adjusted_score` 代替监督目标；它是排名/证据惩罚，不是定义上的 Rdual。

### 2.3 去重与冲突

主生物学键：`sequence_sha256`；candidate ID 仅作 provenance。

按以下顺序 fail-closed：

```text
candidate_id 唯一
sequence 的实际 SHA256 与声明一致
同一 source 内 sequence_sha256 唯一
跨 source sequence_sha256 去重
parent / patch / design mode / CDR 字段闭合
monomer SHA256 闭合
```

若未来发现跨 campaign 相同序列：

- 相同 protocol semantics + 相同 monomer hash：保留 measurement ledger，并聚合为一个 candidate-level row；
- 相同序列但不同 monomer：作为结构技术重复，不能盲目平均；
- parent、sequence 或 CDR 声明冲突：直接失败；
- 同一序列绝不允许进入不同 split。

当前审计中 open1507 与 V4-I：candidate ID overlap=0，sequence hash overlap=0。

### 2.4 泄漏字段黑名单

不得进入任何模型特征：

```text
candidate_id
parent_id / parent_framework_cluster 的可学习编码
source_lane / campaign 的可学习编码
source_R_dual_min
source_rank / priority_rank / stage1 rank / combined rank
confidence_adjusted_score
successful seed count、seed IDs
technical reasons
任何 Docking pose-derived 输入
```

其中 source/campaign/tier 可用于采样权重、分层指标与审计，但不能作为预测特征。

### 2.5 输出

```text
pvrig_v2_8_open3388_supervised.tsv       # 精确 3388 行
pvrig_v2_8_v4i_incomplete81.tsv          # 精确 81 行，无数值标签
pvrig_v2_8_measurement_ledger.tsv         # 每 receptor/seed 的来源账本
pvrig_v2_8_parent_split_manifest.tsv
pvrig_v2_8_source_inventory.json
PVRIG_V2_8_DATASET_RECEIPT.json
SHA256SUMS
```

监督表必须保留：

```text
candidate_id, sequence, sequence_sha256
parent_framework_cluster
target_patch_id, design_mode, design_generator
teacher_source, source_lane（审计用）
protocol_semantic_id
R_8X6B, R_9E6Y, R_dual_min
successful seed counts/ids per receptor
paired_seed_count
seed_dispersion_8X6B/9E6Y/max
reliability tier/weight
monomer_sha256
claim_boundary
```

---

## 3. 协议兼容性先于训练

V4-H 与 V4-I 的 protocol spec SHA 不同，当前语义 diff 只见：

```text
candidate panel expected count
split count
expected candidate/total jobs
smoke candidate ID
```

下一步必须生成 `PROTOCOL_SEMANTIC_COMPATIBILITY_RECEIPT.json`，逐项确认以下完全相同：

```text
8X6B/9E6Y receptor 与 TL reference hashes
hotspot table hash
ATOM-only/HETATM policy
AIR/restraint 定义
HADDOCK stages 与参数
Top-8 pose selection
score_pose.py 与 blocker rules
native/cross overlay gate
candidate-specific tolerance = none
R8/R9/Rdual candidate aggregation公式
```

若任何影响标签尺度的字段不同：不得直接合并为同一标量监督；应改为 campaign-specific calibration 或 separate head。

---

## 4. split 设计

### 4.1 现有 split builder 必须版本化

当前 V2.4 split validator 假设一个 parent 只能对应一个 `teacher_source`。V4-I 会在同一 11 个 parent 下引入第三个 source，因此旧 builder 会合理地 fail。新版本应改为：

```text
一个 parent 可以有多个 teacher_source
但一个 parent 的全部 campaign、generator、seed repeat、近邻序列必须在同一 outer/inner fold
```

### 4.2 双轨评估

#### Track A：固定旧 outer fold 兼容评估

- V4-I 继承其 parent 在 open1507 中已经冻结的 outer fold；
- 用于与 V2.7 的 M2/B/F0/Stage0 结果作尽可能同口径对比；
- 不重新挑“漂亮 fold”。

加入 V4-I 后固定旧 fold 的行数约为：

```text
fold0 627
fold1 729
fold2 403
fold3 1027
fold4 602
```

必须用 parent-macro 指标，不能让 fold3 的密集行数主导结论。

#### Track B：新 V2.8 parent-balanced nested development split

- 仅根据 candidate count 和 parent ID 的预注册 hash tie-break 重新分配 31 个 parent；
- 在读取任何新模型预测指标前冻结；
- outer/inner 都以 whole parent 为最小单元；
- 输出每 fold 的 parent 数、候选数、source、generator、patch/mode 分布。

Track B 是新训练的主要开发 split，但旧指标与新 split 指标不得直接拼在同一表中冒充提升。

### 4.3 temporal/generator challenge

另外建立两个非独立但实用的 challenge：

```text
Temporal sibling challenge:
train = open1507
score = V4-I（同 11 parent）
目的 = 测量已知 parent 上的新 sibling 排序

Generator challenge:
LATENT 与 MPNN 相互留出
目的 = 检查模型是否只识别生成器风格
```

这两项不能替代 whole-parent OOF，但更贴近未来 100K 序列池的实际筛选场景。

---

## 5. 权重与采样

### 5.1 seed reliability

保持预注册单调权重作为 primary：

```text
DUAL_3_SEED / V4D multi-seed: 1.00
DUAL_2_SEED:                  0.80
DUAL_1_SEED:                  0.65
```

V4-I 最终贡献：

```text
476 × 0.80
1405 × 0.65
```

81 technical incomplete 权重为空，不进入 scalar/contact loss。

### 5.2 parent balancing

单纯 per-row 加权会让新增的 11 个 parent 压倒其余 parent。训练 fold 内应计算：

```text
w_final = w_seed_reliability × w_parent_balance
```

Primary：每个 train parent 的总 scalar-loss mass 归一到相同值，再把全 fold 平均权重归一到 1。Challenger：`1/sqrt(n_parent)`，避免对稀疏 parent 过度放大。

所有 parent 权重必须只用当前 train fold 行数计算；score fold 不参与 fit。

### 5.3 balanced sampler

神经模型 batch 建议分层：

```text
先均匀采 parent
再在 parent 内按 source_lane × patch × design_mode 采样
最后乘 reliability loss weight
```

不要简单全局 shuffle 3388 行。

---

## 6. contact/structure 数据扩充

### 6.1 Scalar 与 Stage0 可立即使用

1881 条 V4-I 的 sequence、R8/R9/Rdual 已足够先运行：

```text
ESM2-650M Ridge
ESM2-650M + 3B ElasticNet
轻量 physicochemical Ridge/GBDT
```

新增 embedding cache 必须按 sequence SHA 去重，并记录 model/checkpoint/layer/pooling hash。

### 6.2 M2/structure

V4-I 1962 条都已有冻结单体 PDB；应复用 open1507 的同一结构特征 extractor，生成 1881 条 supervised + 81 条 label-free feature rows。禁止从 Docking pose 提取 M2 输入。

### 6.3 Contact

V4-I raw job results 可生成新的 contact teacher，但必须新建 V4-I extractor contract：

```text
contact cutoff = 4.5 Å
固定 Top-8
pose weight = normalized 1/log2(rank+1)
seed aggregation = paired successful seed intersection
8X6B 与 9E6Y 分开输出
```

预计用于 contact 的 paired job：

```text
1381 单 seed候选 × 2 jobs = 2762
24 paired-one-seed候选 × 2 jobs = 48
476 two-seed候选 × 4 jobs = 1904
合计 4714 个 job_result
```

Primary contact 训练：

- marginal contact：全部 1881，单 seed 低权重；
- full pair contact：476 条 DUAL_2_SEED primary，单 seed只作低权重 challenger；
- 不得把81条技术不完整转成全零 contact negative。

---

## 7. 模型实验矩阵

### Phase A：低成本数据增量审计

在相同 split、相同 seed 下比较：

| 实验 | 数据 | 模型 | 目的 |
|---|---|---|---|
| A0 | open1507 | Ridge/ElasticNet | 冻结参考 |
| A1 | open3388 | Ridge/ElasticNet | 数据增量本身 |
| A2 | open3388 | parent-balanced Ridge/ElasticNet | 抑制11-parent domination |
| A3 | train1507 → V4-I | Stage0 | sibling temporal challenge |
| A4 | LATENT↔MPNN holdout | Stage0 | generator shortcut |

数据规模必须作为独立消融轴：

```text
D0 = open1507
D1 = open2007（只加Stage2 500）
D2 = open3388（再加Stage1-only 1381）
```

只有 D2 相对 D1 改善 parent-macro early enrichment，才证明大量单seed Stage1 rows值得进入生产训练；否则保留 D1 作为主训练集，D2 仅用于低权重预训练或不确定性建模。

先证明 expanded data 改善 early enrichment，再上 GPU。

### Phase B：结构模型

```text
M2-open1507 vs M2-open3388
B-open3388
marginal-only-open3388
combined contact open3388（challenger）
```

Pair-only 已在 V2.7 表现较弱，不作为 first priority。

### Phase C：损失与优化器

仅在 inner development 冻结小矩阵：

```text
Huber beta: 0.02 / 0.03 / 0.05
AdamW lr: 1e-4 / 3e-4
weight decay: 0.01 / 0.05
contact: none / marginal-only / marginal+0.1 pair
rank auxiliary: 0 / 0.01 / 0.03
```

约束：

- rank loss 只用于同 parent 且双方均为 ≥2-seed 的 pair；
- `lambda_rank=0.1` 已失败，不再重跑；
- early stopping 主指标为 inner parent-macro early enrichment，不是 train loss；
- 每个入围配置至少 3 seeds；不得挑单 seed 最好结果。

### Phase D：融合

Primary：

```text
Stage0 Ridge/ElasticNet
+ M2
+ marginal-only
→ fold-local rank/quantile
→ nonnegative linear / ElasticNet stack
```

Challenger：depth 2–3 的 shallow HistGBDT/LightGBM。输入仅 20–40 维 OOF 证据：R8/R9/Rdual、uncertainty、conformer gap、模型分歧、少量 label-free QC。必须双层 cross-fitting，不得在生成 meta 特征的同一行上训练并报告。

生产仍用多模型 quota，而不是单个黑箱分数。

---

## 8. early-enrichment 主评估

每个 whole-parent outer fold、每个 seed、ensemble 都必须报告：

```text
Recall(true Top10%) @ predicted Top5/10/20%
Recall(true Top20%) @ predicted Top10/20%
EF@Top1/5/10/20%
binary NDCG@Top5/10/20%
parent-macro within-parent EF/Recall
source-lane / generator / patch / mode stratified metrics
worst-parent quartile
```

统计要求：

- candidate ID 固定 tie-break；
- 同时给 cutoff tie 的 pessimistic/expected/optimistic；
- parent-cluster bootstrap 95% CI；
- 报 global micro 和 parent macro，不能只报 micro；
- advancement gate 以 early enrichment 为主，Spearman/MAE 为辅。

建议开发 gate：

```text
相对 strongest open1507 baseline：
1. predicted Top20% 对 true Top10% recall 不下降；
2. parent-macro EF@10/20 至少一项提高，且不是单个 parent 驱动；
3. 至少 4/5 outer folds 方向一致，或 parent-bootstrap CI 下界 > 0；
4. temporal V4-I challenge 的 MPNN 和 LATENT 两个 lane 均非退化；
5. 3-seed Top-list 稳定性通过。
```

若只改善 Spearman 而不改善 early enrichment，不升级生产选择器。

---

## 9. 推荐执行顺序

```text
1. 冻结 V4-I source inventory 与 protocol semantic compatibility receipt
2. 在读取V4-I行级标签参与任何调参前，用当前冻结模型生成 train1507→V4-I prediction freeze，保住一次generator-shift回放
3. 实现同一合并器的 open2007 与 open3388 两档输出；81 technical rows fail-closed
4. 生成 fixed-old-fold 与 new-parent-balanced 两套 split
5. 先跑 Stage0 Ridge/ElasticNet 数据增量实验
6. 生成 V4-I monomer 126D features，重跑 M2
7. 从4714个 paired job_result 提取 V4-I marginal/contact teacher
8. 跑 B / marginal-only / combined 的3-seed inner development
9. 严格 cross-fit 融合，比较 early enrichment
10. 冻结 100K 选择器与 Docking quota
11. 下一批 Docking预注册高/中/低分随机多-seed sentinel，提供更无偏噪声估计
```

停止条件：若 expanded open3388 在 parent-macro early enrichment、temporal sibling challenge 和 generator challenge 均没有稳定增量，则保留新数据用于 calibration/active learning，但不替换 V2.7 生产选择器。

---

## 10. 现有训练代码的版本迁移边界

不能把 open3388 直接塞入当前 V2.6 launcher。现有 inner-pilot/ablation 代码冻结了 `expected_rows=1269`、`expected_train_rows=1085`、`expected_score_rows=184` 以及 real1507 trust anchors、contact closure 和 package hashes。新数据需要另起：

```text
open3388 data contract
open3388 whole-parent split contract
open3388 graph/embedding/structure closure
open3388 contact teacher contract
open3388 trainer integration
open3388 trust anchors
open3388 launcher/package freeze
```

旧 real1507 package、结果、trust anchors 全部保留只读；不得改常数后继续沿用旧版本名，也不得让新 launcher 静默加载 real1507 的 row-count/trust-anchor receipt。
