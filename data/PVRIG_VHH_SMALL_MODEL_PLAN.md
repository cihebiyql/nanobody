# PVRIG 方向 VHH-抗原结合小模型规划

生成时间：2026-07-07  
工作区：`/mnt/d/work/抗体/data`

## 1. 目标定义

你现在要做的不是一个“全宇宙抗体亲和力模型”，而是一个面向比赛提交的、小而可控的 **VHH/纳米抗体-抗原结合性质预测与优化模型**。

最终希望模型输出：

1. 对一个候选 VHH 和一个抗原/受体序列或结构，预测它们是否可能结合、结合强弱或排序分数。
2. 在 VHH 上标注三个 CDR 片段：`CDR1`、`CDR2`、`CDR3`。
3. 在三个 CDR 内进一步标注哪些残基更像 paratope，也就是实际参与结合的纳米抗体残基。
4. 在抗原上预测 epitope，也就是抗体可能识别的结合区域。
5. 对 PVRIG 项目，额外判断预测 epitope 是否覆盖/竞争 PVRIG-PVRL2 真实结构界面，从而服务于“阻断 PVRIG-PVRL2”的设计目标。

建议把模型定位为：

> sequence + structure guided VHH-antigen interaction ranker  
> 中文：序列和结构共同约束的 VHH-抗原结合排序/位点预测模型。

这个模型的核心用途是 **筛选和优化候选**，不是直接证明结合；最终 Kd、IC50 仍然只能由实验确认。

---

## 2. 当前本地数据能支持什么

当前数据池已经足够做一个小模型原型。关键不是“所有数据都堆进去”，而是按标签类型分层使用。

### 2.1 PVRIG/PVRL2 靶点结构数据

本地已有真实靶点结构和序列：

| 数据 | 文件 | 可用信息 | 用途 |
|---|---|---|---|
| PVRIG-PVRL2 复合物 8X6B | `datasets/00_structures/8X6B.pdb`, `8X6B.cif`, `8X6B.fasta` | PVRIG 与 Nectin-2/PVRL2 复合物结构 | 定义 PVRIG 上要阻断的界面 |
| PVRIG-PVRL2 复合物 9E6Y | `datasets/00_structures/9E6Y.pdb`, `9E6Y.cif`, `9E6Y.fasta` | 另一套 PVRIG 与 Nectin-2/PVRL2 结构 | 验证界面一致性 |
| PVRIG 全长序列 | `datasets/00_structures/PVRIG_Q6DKI7_uniprot.fasta` | UniProt Q6DKI7，326 aa | 序列建模、编号映射 |
| PVRL2 全长序列 | `datasets/00_structures/PVRL2_Q92692_uniprot.fasta` | UniProt Q92692，538 aa | 配体/竞争界面参考 |

已经抽取出的 PVRIG-PVRL2 界面文件：

| 文件 | 行数/含义 |
|---|---|
| `structures/PVRIG_interface_residues_8X6B.csv` | 8X6B 中 PVRIG 侧 22 个 4.5 Å 界面残基 |
| `structures/PVRIG_interface_residues_9E6Y.csv` | 9E6Y 中 PVRIG 侧 22 个 4.5 Å 界面残基 |
| `structures/PVRIG_consensus_interface_residues.csv` | 两个结构合并后的 23 个共识界面列 |
| `structures/PVRIG_hotspot_set_v1.csv` | 26 条热点/软热点记录，含 UniProt 位置、权重、证据来源 |
| `structures/PVRIG_ligand_contact_pairs_8X6B.csv` | 8X6B 中 57 对 PVRIG-PVRL2 接触 |
| `structures/PVRIG_ligand_contact_pairs_9E6Y.csv` | 9E6Y 中 56 对 PVRIG-PVRL2 接触 |
| `structures/PVRIG_soft_epitope_hints.csv` | S67/R95/I97 等专利表位线索，作为软约束 |

结论：PVRIG 这边的真实结构足够做 **目标 epitope 约束**，但它不是 VHH-PVRIG 训练集。

### 2.2 本地发现的 anti-PVRIG 抗体结构

本地 SAbDab/SAAINT 表里能看到 `8JBJ`：`Crystal structure of anti-PVRIG Fab`，分辨率 1.61 Å。当前已额外落盘 `datasets/00_structures/8JBJ.cif` 供后续核查。

核查结果：`8JBJ` 只包含 antibody heavy chain 和 antibody light chain 两类聚合物实体，SAbDab 表中 `antigen_chain=NA`。因此它更像 **anti-PVRIG Fab 自身结构**，不是可直接抽取 Fab-PVRIG epitope 的抗体-抗原复合物。它可以用于阳性抗体序列/结构参考，但不能当作 VHH-PVRIG 复合物监督样本。

当前本地没有看到明确的 **VHH-PVRIG 复合物结构训练样本**。所以路线应该是：

```text
用通用 VHH-抗原数据学习“怎么结合、哪里结合”
        +
用 PVRIG-PVRL2 结构定义“必须打到哪里”
        ↓
对 PVRIG 候选 VHH 做目标特异排序与优化
```

---

## 3. 最适合训练这个小模型的数据集

### 3.1 位点监督：paratope / epitope

这是你“标注三个结合片段”和“标注抗原结合区域”的核心数据。

| 数据集 | 文件 | 当前统计 | 标签 | 推荐用途 |
|---|---|---:|---|---|
| ZYMScott Paratope | `datasets/49_hf_broad_antibody/ZYMScott_Paratope/{train,val,test}.csv` | 851/139/240，共 1230 对 | `seq_nanobody`, `paratope`, `seq_antigen`, `epitope` | 第一优先；训练 VHH paratope 和 antigen epitope mask |
| NanoLAS active residues | `datasets/35_nanolas/active-residue.csv` | 4196 行 | active residue、residueChain、sequence | VHH/纳米抗体活性位点弱监督 |
| NanoLAS ligand binding sites | `datasets/35_nanolas/ligand-binding-sites.csv` | 2659 行 | ligand binding site | 弱监督/辅助验证 |
| silicobio SAbDab epitope | `datasets/51_hf_gap_fill/silicobio_peleke_antibody-antigen_sabdab/sabdab_training_dataset.csv` | 9523 行，约 4920 unique PDB | `antigen_seqs`, `epitope_residues`, `highlighted_epitope_seqs` | 训练抗原 epitope 头；注意多为常规抗体，不是 VHH-only |
| SAbDab2 single-domain structures | `datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz` | 2422 unique PDB，其中 2277 个在 summary 中有 antigen_chain | 需要从结构计算 paratope/epitope 接触 | 最关键的结构监督扩展集 |

ZYMScott Paratope 的质量很适合做第一个模型：检查结果显示三份 split 中 `paratope` 长度都与 `seq_nanobody` 对齐，`epitope` 长度都与 `seq_antigen` 对齐。缺点是带 affinity 的样本很少，只有 26 条非空 affinity，所以它适合训练位点，不适合单独训练亲和力。

### 3.2 亲和力/结合分数监督

| 数据集 | 文件 | 当前统计 | 标签 | 注意事项 |
|---|---|---:|---|---|
| ZYMScott VHH affinity-score | `datasets/49_hf_broad_antibody/ZYMScott_vhh_affinity-score/` | 12737 行，12735 unique seq | `seq`, `CDR1/2/3`, `score` | 很适合 VHH 分数回归/排序；但当前字段没有 antigen_seq，不能直接当通用 pair affinity |
| ZYMScott VHH affinity-seq | `datasets/49_hf_broad_antibody/ZYMScott_vhh_affinity-seq/` | 12737 行，含 `cluster_id` | `seq`, `CDR1/2/3`, `score`, `cluster_id` | 更适合去泄漏 split；同样需要确认 score 对应的任务/靶点 |
| sdAb-DB affinity rows | `datasets/36_sdab_db/sdab_db_affinity_rows.csv` | 1484 行；可解析 Kd 272 行 | `aa_sequence`, `antigen`, `kd_nm`, `doi` | 真 sdAb/VHH Kd 数据；但抗原多是名称，需要补 antigen sequence/structure |
| SAbDab affinity small table | `datasets/28_affinity_kd/antibody_affinity_protein_sabdab.csv` | 493 行 | antibody、antigen、Y | 小而直接，适合 sanity check |
| AbBiBench binding_affinity | `datasets/14_antibody_benchmark/AbBiBench/binding_affinity/` | 215699 行 | heavy/light chain mutation binding_score | 大量突变分数；不是 VHH-only，可做突变/排序预训练 |
| AbDesignDB mutant | `datasets/30_abdesign_db/datasets_mut.csv` | 1303 行 | mutation、affinity/ELISA ratio、CDR、antigen seq | 适合后期 CDR 局部优化 |
| SKEMPI2 | `datasets/03_skempi/skempi_v2.csv` | 7085 行 | PPI 突变前后 affinity | 泛蛋白互作突变效应预训练，不作为抗体主监督 |

重要判断：

- 真正“VHH + 抗原 + Kd”的高质量样本不多。
- 所以第一版不要承诺输出绝对 Kd；更稳的是输出 **binding/ranking score**，再用少量 Kd 数据校准。
- 对比赛提交，排序模型比绝对亲和力回归更实用。

### 3.3 结构监督与真实结构数量

| 结构来源 | 当前本地状态 | 可用量级 | 推荐用途 |
|---|---|---:|---|
| SAbDab2 full_all | `datasets/13_sabdab_structures/full_all/` | 21610 antibody instances，11288 unique PDB；10145 unique PDB 有 antigen_chain | 抗体-抗原结构接触抽取、验证集 |
| SAbDab2 single-domain | `datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz` | 2422 unique PDB；2277 有 antigen_chain | VHH/sdAb-抗原结构训练主力 |
| SAbDab2 sd_h | `datasets/13_sabdab_structures/sabdab_all_sd_h_structures.tgz` | 2362 unique PDB；2234 有 antigen_chain | heavy-like 单域结构训练 |
| RosettaCommons SAbDab | `datasets/49_hf_broad_antibody/RosettaCommons_SAbDab/sabdab_dataset_curated.tar.gz` | 4.8GB archive | 结构、annotation、IMGT/Chothia 辅助 |
| FarmerTao SAbDab 2025.8 | `datasets/49_hf_broad_antibody/FarmerTao_SAbDab_2025.8/all_structures.zip` | 6.4GB archive | 大结构包备份 |
| SAAINT-DB | `datasets/33_saaint_db/` | 结构抗体数据库包 | 结构建模/复核 |

对你这个小模型，最值得优先解包/索引的是 **SAbDab2 single-domain structures**，因为它最接近纳米抗体/VHH 的真实结构场景。

---

## 4. 推荐的小模型总体方案

不要一开始训练一个很大的 end-to-end 几何模型。建议做一个三头多任务小模型：

```text
输入：VHH sequence + CDR mask + antigen sequence + optional structure features

共享编码器：
  VHH residue encoder
  antigen residue encoder
  cross-attention / pair interaction block

输出头：
  Head A: VHH paratope 残基概率
  Head B: antigen epitope 残基概率
  Head C: binding/ranking score

PVRIG 专用后处理：
  epitope 与 PVRIG-PVRL2 interface overlap
  docking/结构接触一致性
  developability/novelty 过滤
```

### 4.1 第一版最稳架构

第一版建议用“冻结预训练 embedding + 小交互层”，而不是从零训练大模型。

可行配置：

1. VHH 编码：
   - 初期可用 amino-acid embedding + CDR position embedding。
   - 如果显存允许，再换 AntiBERTy/IgBERT/ESM2 小模型 frozen embedding。
2. 抗原编码：
   - ESM2 small 或 ProtBERT/ProtT5 frozen embedding。
   - PVRIG 只有 326 aa，全长不长，ECD 更短，推理成本低。
3. 交互层：
   - 2-4 层 cross-attention 或者 residue-pair biaffine scoring。
   - 隐藏维度 128-256 即可。
4. 结构特征：
   - 第一版不做重型 SE(3) 模型。
   - 先加入轻量结构特征：residue SASA、Cα contact、是否属于 CDR、是否属于 PVRIG interface、距离目标 epitope 的几何分数。
5. 输出：
   - 每个 VHH 残基一个 paratope probability。
   - 每个抗原残基一个 epitope probability。
   - 一个 pair-level binding/ranking score。

### 4.2 损失函数

建议多任务训练：

```text
Loss = 1.0 * BCE(paratope_mask)
     + 1.0 * BCE(epitope_mask)
     + 0.5 * Huber/MSE(binding_score_or_logKd)
     + 0.3 * pairwise_ranking_loss
     + 0.1 * regularization/developability_penalty
```

其中：

- `paratope_mask` 来自 ZYMScott Paratope、SAbDab2 single-domain 结构接触、NanoLAS 弱监督。
- `epitope_mask` 来自 ZYMScott Paratope、silicobio SAbDab、SAbDab2 结构接触。
- `binding_score_or_logKd` 来自 ZYMScott VHH score、sdAb-DB Kd、SAbDab affinity、AbBiBench。
- 对 Kd 建议转成 `-log10(Kd_M)` 或 `pKd`，不要直接用 nm 原值。

---

## 5. 训练流程建议

### Phase 0：建立统一索引，不直接训练

先把所有可用样本统一成一个表：

```text
sample_id
source_dataset
split
vhh_seq
cdr1_seq
cdr2_seq
cdr3_seq
cdr1_span
cdr2_span
cdr3_span
vhh_paratope_mask
antigen_name
antigen_seq
antigen_epitope_mask
pdb_id
structure_path
antibody_chain_ids
antigen_chain_ids
label_type          # paratope_mask / epitope_mask / score / kd / binding_score / ddg
label_value
quality_flag
notes
```

第一版索引只做 5 个来源：

1. `ZYMScott_Paratope`
2. `ZYMScott_vhh_affinity-score` / `ZYMScott_vhh_affinity-seq`
3. `sdAb-DB affinity rows`
4. `silicobio SAbDab training dataset`
5. `SAbDab2 single-domain structures` 派生接触样本

### Phase 1：CDR/Paratope 头

目标：模型能在 VHH 上标出 CDR1/2/3，并预测 CDR 内哪些位点更可能参与结合。

注意：CDR1/2/3 的边界不要完全交给模型学，应该用 ANARCI/IMGT 或已有字段直接标注。模型真正需要学的是：

```text
在 CDR1/2/3 中，哪些残基更可能成为 paratope。
```

训练数据：

- 主监督：ZYMScott Paratope 的 `paratope` mask。
- 扩展监督：SAbDab2 single-domain 结构中 VHH 与 antigen 4.5 Å 接触残基。
- 弱监督：NanoLAS active residue。

### Phase 2：Antigen Epitope 头

目标：输入 VHH + antigen，输出 antigen 每个残基成为 epitope 的概率。

训练数据：

- ZYMScott Paratope 的 `epitope` mask。
- silicobio SAbDab 的 `epitope_residues` / `highlighted_epitope_seqs`。
- SAbDab2 single-domain 结构中 antigen 侧 4.5 Å 接触残基。

对 PVRIG 推理时，不是让模型自由找任意 epitope，而是额外加入一个目标约束：

```text
预测 epitope 必须尽量覆盖 structures/PVRIG_hotspot_set_v1.csv 中的核心界面区域。
```

### Phase 3：Binding/Ranking 头

目标：给一个 VHH-antigen pair 输出结合排序分数。

建议先做排序，不做绝对 Kd：

- pairwise ranking loss 更适合不同数据集标签尺度不一致的问题。
- sdAb-DB/SAbDab affinity 的 Kd 可作为小规模校准。
- AbBiBench/AbDesignDB 更适合学“突变后分数升降”，不是直接泛化到所有抗原。

第一版可以输出：

```text
binding_rank_score: 0-1
calibrated_pKd: optional，仅在可校准样本上输出
confidence: high/medium/low
```

### Phase 4：PVRIG 专用阻断评分

对 PVRIG 赛题，模型最终排序不应只看 binding score，而应看“是否打到 PVRIG-PVRL2 界面”。

建议提交候选的综合评分：

```text
PVRIG_blocking_score =
    0.30 * predicted_binding_rank
  + 0.25 * predicted_epitope_overlap_with_PVRIG_interface
  + 0.15 * predicted_paratope_confidence_on_CDRs
  + 0.15 * structure/docking_interface_score
  + 0.10 * developability_score
  + 0.05 * novelty/diversity_score
```

其中 `predicted_epitope_overlap_with_PVRIG_interface` 用以下文件计算：

- `structures/PVRIG_hotspot_set_v1.csv`
- `structures/PVRIG_consensus_interface_residues.csv`
- `structures/PVRIG_key_contact_residues_v1.csv`

---

## 6. 三个可行路线

### 路线 A：最稳的 baseline，小而快

```text
ANARCI/IMGT 标 CDR
        ↓
ZYMScott Paratope 训练 paratope/epitope 双头
        ↓
ZYMScott VHH score + sdAb-DB Kd 训练排序头
        ↓
PVRIG interface overlap 后处理
        ↓
输出 Top candidates + CDR/epitope 标注
```

优点：最快，1-2 天内能做出可运行原型。  
缺点：结构利用较弱，亲和力不一定准。

### 路线 B：推荐路线，序列 + 真实结构结合

```text
路线 A
        +
解包/索引 SAbDab2 single-domain structures
        +
从结构自动抽取 VHH-antigen contact masks
        +
加入轻量结构特征和结构验证集
```

优点：最贴近你的目标，能真正用真实结构+真实序列。  
缺点：需要写结构预处理脚本，清洗成本更高。

### 路线 C：后期优化路线，模型 + docking/设计闭环

```text
路线 B 模型打分
        ↓
候选 VHH 结构预测：NanoBodyBuilder2 / IgFold
        ↓
PVRIG ECD docking 或受约束对接
        ↓
检查是否覆盖 PVRIG-PVRL2 interface
        ↓
CDR 局部突变：AntiFold / ProteinMPNN / 手动规则
        ↓
重新打分，形成优化循环
```

优点：最适合最终 Top 50。  
缺点：不能作为第一步；否则会被 docking 噪声拖住。

当前推荐：**先做路线 B 的小版本**。

---

## 7. 对 PVRIG 项目的具体用法

### 7.1 模型训练时

训练集不要强行要求 PVRIG 阳性样本，因为当前本地没有足够的 VHH-PVRIG 真实阳性。训练目标应是：

```text
学习一般 VHH 如何通过 CDR 接触抗原
学习抗原哪些表面残基容易成为 epitope
学习序列/结构特征与结合分数的关系
```

### 7.2 PVRIG 推理时

对每个候选 VHH：

1. 用 ANARCI/IMGT 标出 CDR1/CDR2/CDR3。
2. 用模型预测 VHH paratope 残基概率。
3. 输入 PVRIG ECD 序列/结构，预测 PVRIG epitope 残基概率。
4. 计算预测 epitope 与 PVRIG-PVRL2 真实界面的 overlap。
5. 预测结合排序分数。
6. 用 VHH 结构预测 + PVRIG 结构 docking 做轻量复核。
7. 过滤 developability 风险：异常 cysteine、糖基化 motif、过疏水 CDR3、低复杂度、过高相似性。
8. 输出候选排序和解释。

候选输出建议长这样：

```text
candidate_id
vhh_sequence
cdr1/cdr2/cdr3
paratope_top_residues
predicted_pvrig_epitope_residues
pvrig_interface_overlap_score
binding_rank_score
blocking_score
developability_flags
novelty_flags
recommended_action
```

---

## 8. 关键风险

1. **PVRIG 专用阳性太少**  
   不能训练“PVRIG 专用监督模型”，只能训练通用 VHH-antigen interaction prior，再用 PVRIG 结构做目标约束。

2. **亲和力标签尺度不统一**  
   不同数据集的 `score`、`Kd`、`binding_score` 含义不一样。第一版必须做 ranking，不要硬混成一个绝对 Kd。

3. **ZYMScott VHH affinity 缺 antigen_seq 字段**  
   它可用于 VHH 序列分数/固定任务排序，但不能单独代表任意 VHH-antigen pair affinity。

4. **SAbDab/silicobio 多为常规抗体**  
   可学 epitope 和结构接触规律，但要避免让模型只学 VH/VL Fab 模式。VHH 主监督仍应优先 SAbDab2 single-domain 和 ZYMScott/NanoLAS。

5. **结构接触不等于功能阻断**  
   对 PVRIG，必须用 PVRIG-PVRL2 interface overlap 作为额外目标，否则模型可能找到非阻断表位。

---

## 9. 第一阶段交付物建议

建议下一步不是马上训练，而是先做可复现数据索引：

1. `model_data/index_v0_samples.parquet`  
   统一样本索引。
2. `model_data/pvrig_target_epitope_v0.csv`  
   从 `structures/PVRIG_hotspot_set_v1.csv` 整理出的 PVRIG 目标 epitope。
3. `model_data/sabdab2_single_domain_contacts.parquet`  
   从 SAbDab2 single-domain 结构抽取的 VHH-antigen 接触。
4. `model_data/train_config_v0.yaml`  
   记录数据来源、split、标签权重、模型超参。
5. `reports/model_data_quality_v0.md`  
   记录每个数据源样本数、缺失、标签冲突、泄漏风险。

第一版模型训练完成后，应该交付：

1. `models/vhh_antigen_ranker_v0/`
2. `reports/vhh_antigen_ranker_v0_eval.md`
3. `reports/pvrig_candidate_scoring_template.csv`
4. `scripts/score_pvrig_candidates.py`

---

## 10. 我建议采用的最终规划

最可行方案：

```text
Phase 0: 统一索引和数据质量检查
Phase 1: 训练 VHH paratope + antigen epitope 双头模型
Phase 2: 加入 binding/ranking score 头
Phase 3: 加入 SAbDab2 single-domain 结构接触作为结构监督
Phase 4: 用 PVRIG-PVRL2 interface 做目标特异 blocking score
Phase 5: 对候选 VHH 做 CDR 局部优化和复打分
```

第一版不要追求“大而全”，只要做到：

- 能读入 VHH + antigen。
- 能自动输出 CDR1/CDR2/CDR3。
- 能输出 VHH paratope mask。
- 能输出 antigen epitope mask。
- 能输出 pair binding/ranking score。
- 对 PVRIG 能计算 epitope overlap 和 blocking score。

这就已经满足“有一个 AI 模型，并且模型服务于 PVRIG-PVRL2 阻断抗体设计”的核心要求。

---

## 11. 最后校准层：已知 PVRIG blocker / mutant control 只做校准，不做普通训练

2026-07-08 已接入 `/mnt/d/work/抗体/docking` 中的成功案例验证结果，生成位置：

- `model_data/pvrig_blocker_positive_calibration_v0.csv`
- `model_data/pvrig_blocker_positive_pose_labels_v0.csv`
- `model_data/pvrig_blocker_mutant_control_calibration_v0.csv`
- `model_data/pvrig_blocker_mutant_pose_labels_v0.csv`
- `model_data/pvrig_blocker_threshold_sensitivity_v0.csv`
- `model_data/pvrig_blocker_calibration_summary_v0.json`
- `reports/pvrig_blocker_final_calibration_layer_v0.md`

这部分数据的定位非常重要：

```text
它们不是普通训练正例。
它们是最后校准、阈值、泄漏排除、鲁棒性和 false-positive 审计数据。
```

已锁定信息：

- 11 条 WO2021180205A1 阳性 VHH/HCVR，family 覆盖 151、20、30、38、39。
- 109 条 positive pose consensus labels。
- 36 条 mutant/control panel。
- 357 条 mutant/control pose labels。
- 162 条 threshold sensitivity rows，来自 positive cohort 和 mutant/control cohort 各 81 个阈值设置。
- mutant/control 泄漏标签：7 条 exact known-positive，29 条 near known-positive。

最终模型使用顺序应改成：

```text
候选 VHH + PVRIG
  ↓
Phase 1/2 AI model prior
  - paratope probability
  - epitope probability
  - VHH/ranking score
  - PVRIG target overlap
  ↓
PVRIG blocker calibration gate
  - exact/near known-positive leakage check
  - positive success threshold calibration
  - 8X6B/9E6Y dual-baseline docking consensus
  - mutant/control false-positive audit
  - CDR3 disruptive/alanine retained-A manual review
  ↓
final_blocker_like_calibrated_label
```

最终候选表应新增这些列：

```text
known_positive_identity_fraction
leakage_label
haddock_8x6b_class
haddock_9e6y_class
dual_baseline_consensus_class
positive_threshold_supported
mutant_panel_false_positive_risk
manual_pose_review_required
final_blocker_like_calibrated_label
```

使用边界：

- exact/near known-positive 不进入新候选排名，只能作为 control / calibration。
- 单 baseline A 只能叫 recheck，优先级低于 8X6B+9E6Y 双 baseline A/A。
- mutant/control 中 CDR3 disruptive 或 alanine 仍 retained-A 的情况必须手动看 pose，不能直接当真阻断。
- 最终声明仍然是 computational blocker-like geometry，不是实验 IC50/Kd 证明。

