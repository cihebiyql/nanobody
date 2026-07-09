# DeepNano 详细复现与数据集说明

生成日期：2026-07-06  
工作目录：`/mnt/d/work/抗体/code`  
本地模型目录：`downloaded_models/DeepNano`

本文档用于记录 DeepNano 的模型结构、训练流程、数据集设计、输入输出、使用方法，以及它在 PVRIG-PVRL2 阻断型纳米抗体项目中的可用点和局限。重点放在数据集组织，因为后续自建 PVRIG 专用 AI 模型时，DeepNano 的数据设计可作为重要参考。

## 1. 一句话定位

DeepNano 是面向 nanobody-antigen interaction, NAI 的序列模型集合。它从 VHH 序列和抗原序列预测二者是否可能结合，并进一步引入抗原结合位点预测作为 prompt，增强 NAI 预测。

它适合回答：

```text
这个 VHH 是否像一个可能结合目标抗原的 binder？
```

它不适合单独回答：

```text
Kd 是多少？
是否一定阻断 PVRIG-PVRL2？
是否结合 PVRIG 的功能性阻断表位？
```

因此，在 PVRIG 项目中，DeepNano 更适合作为第一层 sequence-only binder 筛选器，而不是最终排序模型。

## 2. 本地文件与权重状态

代码目录：

```text
downloaded_models/DeepNano
```

主要文件：

```text
README.md                         官方说明
predict.py                        推理入口，输入路径在文件顶部硬编码
train_DScriptData.py              普通 PPI 数据训练入口
train_Sabdab.py                   NAI 二分类训练入口
train_Sabdab_Site.py              抗原 binding-site 训练入口
models/models.py                  DeepNano-seq、DeepNano-site、DeepNano 模型定义
utils/dataloader.py               数据读取与格式约定
utils/evaluate.py                 指标计算
```

主要数据目录：

```text
data/Sabdab/                      SAbDab-nano 结构正样本、训练/验证 NAI 数据
data/Nanobody_Antigen-main/       Nb-Ag 测试数据
data/D_script/                    普通 PPI 训练/测试数据
data/case_study/                  HSA/GST case study
data/INDI/                        大规模 nanobody 背景库入口
```

本地已存在四档 ESM2 encoder：

```text
models/esm2_t6_8M_UR50D
models/esm2_t12_35M_UR50D
models/esm2_t30_150M_UR50D
models/esm2_t33_650M_UR50D
```

本地 checkpoint 总量约 17G，包含 8M、35M、150M、650M 的 `DeepNano-seq(PPI)`、`DeepNano-seq(NAI)`、`DeepNano-site` 和 `DeepNano(NAI)` 权重。快速复现建议从 8M 开始。

## 3. DeepNano 包含哪些模型

DeepNano 不是一个单模型，而是一组模型。

### 3.1 DeepNano-seq(PPI)

这是普通 protein-protein interaction, PPI 模型。它用通用 PPI 数据训练，学习两个蛋白序列是否相互作用。

用途：

```text
通用蛋白互作预训练 / baseline
```

对 PVRIG 项目价值有限，因为 VHH-抗原结合有特殊规律，不能直接用普通 PPI 结果作为最终判断。

### 3.2 DeepNano-seq(NAI)

这是纳米抗体-抗原二分类模型。输入 VHH 序列和抗原序列，输出结合概率。

用途：

```text
VHH-PVRIG 是否可能结合的快速初筛
```

这是最适合作为第一层筛选 baseline 的版本。

### 3.3 DeepNano-site

这是抗原 binding-site 预测模型。输入 VHH 和抗原序列，输出抗原每个残基成为 VHH 接触位点的概率。

用途：

```text
预测候选 VHH 可能接触 PVRIG 的哪些残基
```

对 PVRIG 项目很重要，因为我们真正关心的是 VHH 是否覆盖 PVRIG-PVRL2 界面。

### 3.4 DeepNano(NAI)

这是 prompt-based 版本。它先用 `DeepNano-site` 预测抗原结合位点，再把预测出的位点 mask 编码成 prompt，并与 ESM2 序列特征一起输入结合分类器。

用途：

```text
比单纯 sequence-only 更重视抗原潜在界面信息的 NAI 预测
```

对 PVRIG 项目可以作为比 `DeepNano-seq(NAI)` 更强的第一层筛选器。

## 4. 模型输入和输出

### 4.1 输入

核心输入是两条氨基酸序列：

```text
nanobody / VHH sequence
antigen sequence
```

在 PVRIG 项目中，推荐使用：

```text
候选 VHH 序列
PVRIG extracellular domain, ECD 序列
```

不建议输入全长 PVRIG，因为跨膜区和胞内段对 VHH 结合没有意义，反而会干扰模型。

### 4.2 输出

`predict.py` 输出 CSV：

```csv
Nanobody ID,Antigen ID,Prediction
vhh_001,pvrig_ecd,0.873
vhh_002,pvrig_ecd,0.214
```

`Prediction` 是结合概率样式的分数，范围 0 到 1。它不等价于 Kd、IC50 或 blocking rate。

模型内部有三个 pooling 分支：

```text
p_ave: average pooling 特征预测
p_min: min pooling 特征预测
p_max: max pooling 特征预测
```

最终预测使用平均：

```python
p = (p_ave + p_min + p_max) / 3
```

## 5. 模型结构

DeepNano 基于 ESM2 蛋白语言模型。

### 5.1 DeepNano-seq

流程：

```text
VHH sequence -> ESM2 -> VHH embedding
Antigen sequence -> ESM2 -> antigen embedding
VHH embedding + antigen embedding -> MLP -> binding probability
```

ESM2 embedding 分别做 average、max、min pooling，然后由三个 MLP head 预测，最后 ensemble。

### 5.2 DeepNano-site

流程：

```text
VHH sequence -> ESM2 -> VHH global embedding
Antigen sequence -> ESM2 -> antigen per-residue embedding
每个抗原残基 embedding + VHH embedding -> MLP -> residue binding-site probability
```

输出形状近似为：

```text
batch_size x antigen_length x 1
```

每个抗原残基得到一个 0 到 1 的界面概率。

### 5.3 DeepNano prompt-based 版本

流程：

```text
VHH + antigen -> DeepNano-site -> antigen site probability
site probability > 0.5 -> 0/1 site mask
site mask -> embedding + positional encoding + transformer prompt encoder
prompt embedding + VHH/antigen ESM2 embedding -> MLP -> binding probability
```

也就是说，DeepNano 的 prompt 不是自然语言 prompt，而是“预测出的抗原结合位点 mask”。

## 6. 训练流程

DeepNano 的训练可以理解为三层。

### 6.1 普通 PPI 训练

脚本：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/DeepNano
python train_DScriptData.py --Model 1 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

用途：训练 `DeepNano-seq(PPI)`。

主要数据：

```text
data/D_script/pairs/human_train.tsv
data/D_script/pairs/human_test.tsv
data/D_script/seqs/human_dedup.fasta
```

本地统计：

```text
human_train.tsv: 421,792 对
  positive: 38,344
  negative: 383,448

human_test.tsv: 52,725 对
  positive: 4,794
  negative: 47,931
```

### 6.2 DeepNano-site 训练

脚本：

```bash
python train_Sabdab_Site.py --Model 0 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

用途：训练抗原 residue-level binding-site predictor。

训练数据：

```text
data/Sabdab/NAI_train_pos.csv
data/Sabdab/NAI_val_pos.csv
```

本地统计：

```text
NAI_train_pos.csv: 1,019 条正样本
NAI_val_pos.csv: 51 条正样本
```

训练设置：

```text
batch size: 32
learning rate: 5e-5
epochs: 200
loss: per-residue binary cross entropy
```

### 6.3 NAI 二分类训练

训练 `DeepNano-seq(NAI)`：

```bash
python train_Sabdab.py --Model 0 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

训练 prompt-based `DeepNano(NAI)`：

```bash
python train_Sabdab.py --Model 1 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

训练数据：

```text
data/Sabdab/NAI_train.csv
data/Sabdab/NAI_val.csv
```

本地统计：

```text
NAI_train.csv: 11,209 对
  positive: 1,019
  negative: 10,190

NAI_val.csv: 561 对
  positive: 51
  negative: 510
```

训练设置：

```text
batch size: 32
learning rate: 5e-5
epochs: 10
optimizer: AdamW
loss: BCE(p_ave) + BCE(p_min) + BCE(p_max) 的平均
best checkpoint: validation AUPR 最优
```

## 7. DeepNano 数据集详解

这是 DeepNano 对我们最有价值的部分。

### 7.1 SAbDab-nano 结构正样本

核心文件：

```text
data/Sabdab/all_binding_site_data_5A.csv
```

本地统计：

```text
总行数: 1,184 条正样本 NAI
unique PDB: 668
unique nanobody sequence: 831
unique antigen sequence: 904
```

字段：

```csv
pdb,nanobody_chain,seq_nanobody,binding_site_nanobody,antigen_chain,seq_antigen,binding_site_antigen,affinity,affinity_method
```

含义：

```text
pdb                    结构来源 PDB ID
nanobody_chain         VHH 链 ID
seq_nanobody           VHH 序列
binding_site_nanobody  VHH 侧界面残基索引
antigen_chain          抗原链 ID
seq_antigen            抗原序列
binding_site_antigen   抗原侧界面残基索引
affinity               亲和力，绝大多数缺失
affinity_method        亲和力测定方法，绝大多数缺失
```

README 标明该数据为 5A binding site 数据。可理解为根据复合物结构中 VHH 与抗原原子距离阈值整理出的界面残基。

本地统计：

```text
VHH 侧 binding-site residue count:
  min 10, median 20, max 40

抗原侧 binding-site residue count:
  min 10, median 22, max 45
```

亲和力字段大量缺失：

```text
affinity = None: 1,157 / 1,184
```

结论：这个数据集非常适合训练“界面残基预测”，但不适合直接训练可靠 Kd 回归模型。

### 7.2 训练和验证二分类数据

文件：

```text
data/Sabdab/NAI_train.csv
data/Sabdab/NAI_val.csv
```

格式：

```csv
ID_nanobody,seq_nanobody,ID_antigen,seq_antigen,Interaction label
```

标签：

```text
1 = 结合
0 = 不结合 / 构造负样本
```

本地统计：

```text
NAI_train.csv
  rows: 11,209
  positive: 1,019
  negative: 10,190
  VHH length: min 16, median 121, max 138
  antigen length: min 10, median 279, max 793

NAI_val.csv
  rows: 561
  positive: 51
  negative: 510
  VHH length: min 112, median 122, max 138
  antigen length: min 63, median 285, max 534
```

这里的负样本大概率主要来自 VHH 和非对应抗原的重组错配。它适合训练通用 bind/non-bind 分类，但不等于真实实验中的 hard negative。

对 PVRIG 项目来说，最重要的 hard negative 应该是：

```text
结合 PVRIG，但不阻断 PVRIG-PVRL2 的 VHH
```

这类样本比随机 non-binder 更能帮助模型学到 blocker 规律。

### 7.3 DeepNano-site 正样本数据

文件：

```text
data/Sabdab/NAI_train_pos.csv
data/Sabdab/NAI_val_pos.csv
```

这些文件只包含正样本，因为只有复合物结构正样本才能定义真实界面残基。

字段与 `all_binding_site_data_5A.csv` 类似。

代码中读取逻辑：

```python
_, _, seq_nanobody, _, _, seq_antigen, BSite_antigen, _, _ = item
```

`BSite_antigen` 是逗号分隔的抗原界面残基索引。代码直接把索引转成 0/1 向量：

```text
抗原长度 = L
binding_site_antigen = 105,106,107
=> site_mask[105] = 1
=> site_mask[106] = 1
=> site_mask[107] = 1
=> 其他位置 = 0
```

因此后续自建 PVRIG 数据时必须明确保存索引体系：

```text
seq_index_0based
seq_index_1based
PDB residue number
UniProt residue number
```

避免结构编号、序列编号和 Python index 混淆。

### 7.4 NAI 测试数据

文件：

```text
data/Nanobody_Antigen-main/all_pair_data.pair.tsv
data/Nanobody_Antigen-main/all_pair_data.seqs.fasta
```

`pair.tsv` 格式：

```tsv
Nanobody-ID Antigen-ID Label
```

本地统计：

```text
all_pair_data.pair.tsv: 1,800 对
  positive: 651
  negative: 1,149

all_pair_data.seqs.fasta: 3,600 条序列
  min length: 104
  median length: 168
  max length: 782
```

注意：模型 tokenizer 最大长度是 800，部分 dataloader 会过滤大于 800 aa 的序列。因此使用 PVRIG 时建议输入 ECD 构建，而不是全长蛋白。

### 7.5 HSA/GST case study

文件：

```text
data/case_study/mmc4_HSA_pos.csv
data/case_study/mmc4_HSA.csv
data/case_study/mmc3_GST_pos.csv
data/case_study/mmc3_GST.csv
```

本地统计：

```text
HSA positive: 33 条
HSA total: 44 条
GST positive: 59 条
GST total: 98 条
```

字段包括：

```csv
Protein Sequenze,ELISA affinity (LogIC50 (O.D.450nm))
```

这部分更像 virtual screening case study，不是核心训练集。它有 ELISA 相关值，但量太小，不适合单独训练亲和力模型。

### 7.6 INDI 大规模背景库

README 提到：

```text
INDI/INDI_100w_nanobody.fasta
```

这是从 INDI-ngs 抽样的一百万条 nanobody，用于大规模虚拟筛选。例如固定 HSA 抗原，对一百万条 VHH 打分，看已知 binder 是否排在前面。

对 PVRIG 项目的启发：如果我们有大规模 VHH library，可以用 DeepNano 做第一层筛选，然后再进行结构 docking、PVRIG-PVRL2 interface overlap 和实验优先级排序。

## 8. 快速使用方法

### 8.1 安装环境

官方推荐：

```text
python == 3.9
torch == 1.13.1 + CUDA 11.6
transformers == 4.27.4 或 <= 4.30.2
biopython == 1.78
pandas == 1.3.5
scikit-learn == 1.0.2
```

示例：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/DeepNano
conda create -n deepnano python=3.9 -y
conda activate deepnano
pip install -r requirements.txt
```

### 8.2 运行默认测试数据

sequence-only NAI：

```bash
python predict.py --model 1 --esm2 8M
```

prompt-based NAI：

```bash
python predict.py --model 2 --esm2 8M
```

模型编号：

```text
--model 0: DeepNano-seq(PPI)
--model 1: DeepNano-seq(NAI)
--model 2: DeepNano(NAI)
```

ESM2 规模：

```text
--esm2 8M
--esm2 35M
--esm2 150M
--esm2 650M
```

建议先用 `8M` 验证流程，再用大模型正式筛选。

### 8.3 自定义 PVRIG 输入

`predict.py` 顶部硬编码了：

```python
fasta_path = './data/Nanobody_Antigen-main/all_pair_data.seqs.fasta'
pair_path = './data/Nanobody_Antigen-main/all_pair_data.pair.tsv'
output_path = './output/predictions.csv'
```

可以复制一份脚本，例如：

```bash
cp predict.py predict_pvrig.py
```

然后修改为自己的文件。

FASTA 示例：

```fasta
>vhh_001
QVQLVESGGGLVQAGGSLRLSCAAS...
>vhh_002
QVQLVESGGGLVQAGGSLRLSCAAS...
>pvrig_ecd
PVRIG_ECD_AMINO_ACID_SEQUENCE...
```

pair TSV 示例，无标签：

```tsv
vhh_001	pvrig_ecd
vhh_002	pvrig_ecd
```

pair TSV 示例，有标签：

```tsv
vhh_001	pvrig_ecd	1
vhh_002	pvrig_ecd	0
```

输出：

```text
output/predictions.csv
```

## 9. 如何借鉴 DeepNano 处理自己的 PVRIG 数据

### 9.1 最低配数据格式

如果只想训练 PVRIG binder classifier，可以仿照 DeepNano：

```csv
ID_nanobody,seq_nanobody,ID_antigen,seq_antigen,Interaction label
vhh_001,QVQLVES...,PVRIG_ECD,AA...,1
vhh_002,QVQLVES...,PVRIG_ECD,AA...,0
```

但这只能学习：

```text
是否结合 PVRIG
```

不能学习：

```text
是否阻断 PVRIG-PVRL2
```

### 9.2 推荐的 PVRIG 多任务数据格式

建议自建数据表包含：

```csv
vhh_id,
vhh_seq,
antigen_id,
antigen_seq,
bind_label,
block_label,
kd_nm,
ic50_nm,
assay_type,
antigen_construct,
pvrig_contact_residues,
vhh_contact_residues,
pvrig_pvrl2_interface_residues,
pvrig_pvrl2_overlap_score,
source,
batch,
split_group
```

关键字段解释：

```text
bind_label
  1 = 结合 PVRIG
  0 = 不结合 PVRIG

block_label
  1 = 阻断 PVRIG-PVRL2
  0 = 不阻断 PVRIG-PVRL2
  NA = 未测 blocking

kd_nm / ic50_nm
  亲和力或功能阻断强度

pvrig_contact_residues
  VHH 接触 PVRIG 的残基，可来自结构、突变、docking 或模型预测

pvrig_pvrl2_overlap_score
  VHH 接触区域与 PVRIG-PVRL2 界面的重叠程度
```

### 9.3 推荐数据分层

建议把数据分成四层：

```text
Tier A: 通用 nanobody-antigen 数据
  用 DeepNano/SAbDab-nano 这类数据预训练，学习通用 VHH-抗原结合规律。

Tier B: PVRIG bind / non-bind 数据
  训练 PVRIG-specific binder classifier。

Tier C: PVRIG blocker / non-blocker 数据
  核心任务。区分“结合但不阻断”和“结合且阻断”。

Tier D: 结构或 docking 派生界面数据
  包括 VHH-PVRIG 接触残基、buried SASA、界面能、与 PVRIG-PVRL2 界面的 overlap。
```

### 9.4 负样本设计

DeepNano 的负样本适合通用 bind/non-bind 任务，但 PVRIG 项目必须加入 hard negatives：

```text
不结合 PVRIG 的 VHH
结合 PVRIG 但不阻断 PVRIG-PVRL2 的 VHH
结合其他免疫检查点但不结合 PVRIG 的 VHH
CDR3 很相似但功能不同的 VHH
```

尤其第二类最关键。如果没有这类样本，模型很容易只学到“是否 binder”，而不是“是否 blocker”。

### 9.5 数据划分防泄漏

不要简单随机按行切分。推荐按以下单位 group split：

```text
CDR3 cluster
VHH family / clonotype
发现来源 / panning batch
实验 batch
抗原构建版本
```

否则训练集和测试集可能出现高度相似的 VHH，指标会虚高。

## 10. DeepNano 在 PVRIG 项目中的建议用法

建议不要直接把 DeepNano 的 `Prediction` 作为最终排名，而是作为总分的一部分。

推荐排序框架：

```text
final_rank_score =
  DeepNano binding probability
  + predicted PVRIG-site overlap with PVRIG-PVRL2 interface
  + docking/interface energy score
  + CDR3 developability score
  + sequence liability filter
```

更具体地：

```text
第一层：DeepNano-seq(NAI) / DeepNano(NAI)
  快速过滤明显不像 PVRIG binder 的 VHH。

第二层：DeepNano-site 或自建 site predictor
  预测 VHH 是否可能接触 PVRIG-PVRL2 界面附近。

第三层：结构建模 / docking / NanoBinder 类结构打分
  看 VHH-PVRIG pose 是否合理、是否空间上阻断 PVRL2。

第四层：实验优先级
  综合表达、稳定性、CDR3 liability、亲和力预测和阻断界面覆盖。
```

## 11. 结论

DeepNano 对我们的价值不是“直接给出最终 blocker”，而是：

```text
1. 提供 VHH-PVRIG sequence-only 结合概率。
2. 提供抗原 residue-level binding-site 预测思路。
3. 提供通用 Nb-Ag 数据整理模板。
4. 提供多阶段模型设计范式：binding classifier + site prompt。
```

它最大的局限是：

```text
1. 输出不是 Kd。
2. 不是 PVRIG-PVRL2 阻断模型。
3. 训练数据的 affinity 大量缺失。
4. 负样本主要服务于 bind/non-bind，不足以学习 blocker/non-blocker。
5. site prompt 预测的是一般 VHH-抗原界面，不是专门的 PVRIG-PVRL2 功能界面。
```

因此，DeepNano 最适合作为 PVRIG 项目的第一层筛选与数据工程参考；最终 blocker 排序必须额外加入 PVRIG-PVRL2 interface overlap、结构打分和实验 blocking 标签。
