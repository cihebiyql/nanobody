# NABP-LSTM-Att 详细复现与数据集说明

生成日期：2026-07-08  
工作目录：`/mnt/d/work/抗体/code`  
本地模型目录：`downloaded_models/NABP-LSTM-Att`

本文档记录 NABP-LSTM-Att 的模型思想、训练流程、数据集构造、输入输出、使用方法，以及它在 PVRIG-PVRL2 阻断型纳米抗体项目中的可用点和局限。重点放在 CDR-aware 数据表示和正负样本构造，因为这部分最适合迁移到我们自己的 PVRIG 专用模型。

## 1. 一句话定位

NABP-LSTM-Att 是一个 sequence-only 的 nanobody-antigen binding prediction 模型。它不依赖三维结构，而是使用 VHH 的 CDR 序列和抗原序列，通过 CNN、BiLSTM 和 soft attention 预测纳米抗体-抗原是否结合。

它适合回答：

```text
这个 VHH 的 CDR 和这个抗原序列是否像一个 binding pair？
```

它不适合单独回答：

```text
Kd 是多少？
是否阻断 PVRIG-PVRL2？
VHH 是否覆盖 PVRIG-PVRL2 功能界面？
PVRIG 哪些残基被接触？
```

在 PVRIG 项目中，它最适合作为 CDR-aware 轻量模型和可改造 baseline，而不是最终 blocker 排序模型。

## 2. 本地文件与权重状态

代码目录：

```text
downloaded_models/NABP-LSTM-Att
```

主要文件：

```text
README.md                                  官方说明
model.py                                   NABP-LSTM-Att 模型定义
train.py                                   训练入口
test.py                                    测试入口
getDataFromSAbDab-nano.py                  从 SAbDab-nano 抓取数据
read_CSVs.py                               处理原始 SAbDab-nano CSV
prepareAntigenSeqs.py                      去 VHH 冗余后准备 antigen FASTA
create_intra_inter_group_binding.py        构造 intra/inter group binding pair
phylogenetic_tree_clusters.py              处理 Clustal Omega 系统发育树 cluster
create_train_test_datasets.py              构造 train/val/test
createTSV.py                               生成 CDR/Ag TSV
embedding.py                               生成 pickle feature
features.py                                TSV 到模型 feature 的转换逻辑
tokenization.py                            k-mer tokenizer
vocab/vocab_1kmer.txt                      1-mer 词表
vocab/vocab_2kmer.txt                      2-mer 词表
vocab/vocab_3kmer.txt                      3-mer 词表
Supplementary_Materials.pdf                补充材料
```

作者提供的压缩包：

```text
_downloads/google_drive/data.rar
_downloads/google_drive/model.rar
```

本地已解压：

```text
data/features/
model/
```

模型权重包括 9 组 k-mer 组合：

```text
model/cdr_kmer1_ag_kmer1/Model99.h5
model/cdr_kmer1_ag_kmer2/Model99.h5
model/cdr_kmer1_ag_kmer3/Model99.h5
model/cdr_kmer2_ag_kmer1/Model99.h5
model/cdr_kmer2_ag_kmer2/Model99.h5
model/cdr_kmer2_ag_kmer3/Model99.h5
model/cdr_kmer3_ag_kmer1/Model99.h5
model/cdr_kmer3_ag_kmer2/Model99.h5
model/cdr_kmer3_ag_kmer3/Model99.h5
```

注意：`data.rar` 解压时，3 个 `cdr_kmer2_*` 的 test CDR feature 文件报错，但默认脚本使用 `cdr_kmer3_ag_kmer1`，这一组完整，不影响默认复现和理解。

## 3. 模型思想

NABP-LSTM-Att 的核心思想是：不要把 VHH 当作一整条普通蛋白序列，而是重点看 CDR。

它把每个 VHH-antigen pair 拆成三条 CDR-antigen 样本：

```text
CDRH1 + antigen -> label
CDRH2 + antigen -> label
CDRH3 + antigen -> label
```

每条样本同时带有 CDR 编号：

```text
CDR_number = 1 / 2 / 3
```

模型通过 CDR sequence embedding + CDR number embedding，让模型知道当前输入是 CDR1、CDR2 还是 CDR3。

这对 PVRIG 项目很有启发，因为纳米抗体识别抗原高度依赖 CDR，尤其 CDR3。相比纯全序列模型，CDR-aware 模型更适合我们后续做 PVRIG-specific binder/blocker classifier。

## 4. 输入和输出

### 4.1 输入

模型有三个输入：

```python
cdrs_ids          # CDR token IDs
cdrs_number_ids   # CDR 编号 token IDs
ags_ids           # antigen token IDs
```

其中：

```text
cdrs_ids:
  CDRH1 / CDRH2 / CDRH3 的 k-mer token ID。

cdrs_number_ids:
  表示当前 CDR 是 1、2 还是 3。

ags_ids:
  抗原序列的 k-mer token ID。
```

默认最大长度：

```python
MAX_LEN_cdr = 24
MAX_LEN_ag = 2371
```

对 PVRIG 项目，抗原应使用 PVRIG ECD 序列，而不是全长 PVRIG。

### 4.2 输出

输出是一个 sigmoid 概率：

```text
0 到 1 的 binding probability
```

标签定义：

```text
1 = binding
0 = non-binding
```

测试脚本输出：

```text
AUC_test
AUPR_test
```

README 报告：

```text
AUROC = 0.926
AUPR = 0.952
```

注意：这个输出不是 Kd，不是 IC50，也不是 blocking probability。

### 4.3 CDR-level 与 VHH-level 的区别

官方模型实际上按 CDR-level 样本训练和评估。一条原始 VHH-antigen pair 会被拆成：

```text
VHH_001_CDR1 + antigen_A -> label
VHH_001_CDR2 + antigen_A -> label
VHH_001_CDR3 + antigen_A -> label
```

因此如果要对完整 VHH-PVRIG pair 打分，需要额外聚合三个 CDR 的输出。

简单平均：

```text
VHH_score = mean(CDR1_score, CDR2_score, CDR3_score)
```

更符合 VHH 经验的加权方式：

```text
VHH_score = 0.2 * CDR1_score + 0.2 * CDR2_score + 0.6 * CDR3_score
```

如果我们自建 PVRIG 模型，更推荐把 CDR1、CDR2、CDR3 同时输入一个模型，而不是拆成三条完全独立样本。

## 5. 模型结构

模型定义：

```text
model.py
```

默认参数：

```python
MAX_LEN_cdr = 24
NB_WORDS_cdr = 8001
NB_cdr_number_ids = 3
MAX_LEN_ag = 2371
NB_WORDS_ag = 21
EMBEDDING_DIM = 100
filters = 256
cdr_kernel_size = 6
cdr_pool_size = cdr_strides = 4
ag_kernel_size = 60
ag_pool_size = ag_strides = 20
lstm_size = 50
att_size = 50
dropout = 0.5
```

默认对应：

```text
CDR k-mer = 3
antigen k-mer = 1
```

结构流程：

```text
CDR token ids
  -> CDR embedding

CDR number ids
  -> CDR number embedding

CDR embedding + CDR number embedding
  -> BatchNorm
  -> Dropout
  -> Conv1D
  -> MaxPooling1D

Antigen token ids
  -> Antigen embedding
  -> BatchNorm
  -> Dropout
  -> Conv1D
  -> MaxPooling1D

CDR branch + antigen branch concatenate
  -> BatchNorm
  -> Dropout
  -> Bidirectional LSTM
  -> Soft attention
  -> Dense sigmoid
```

所以它不是单纯的 LSTM，而是：

```text
Embedding + CNN motif extractor + BiLSTM sequence modeling + soft attention
```

这一结构适合学习 CDR 局部 motif 和抗原序列模式。

## 6. 数据来源和预处理流程

### 6.1 SAbDab-nano 数据抓取

脚本：

```text
getDataFromSAbDab-nano.py
```

它从 SAbDab-nano 页面抓取 nanobody-antigen 结构记录，提取字段包括：

```text
pdb
Hchain
Hchain_sequence
CDRH1
CDRH2
CDRH3
antigen_type
antigen_name
Antigen sequence_1
Method
Resolution
```

对于 nanobody 类型记录，输出 CSV 字段包括：

```text
pdb
Hchain
Hchain_sequence
Heavy subgroup
Species
In complex?
scFv?
Has constant domain?
CDRH1
CDRH2
CDRH3
Antigen chain_1
Antigen chain_2
Antigen chain_3
antigen_type
antigen_name
Antigen species
Antigen sequence_1
Antigen sequence_2
Antigen sequence_3
HL
HC1
HC2
LC1
LC2
dc
Method
Resolution
Has constant region
```

### 6.2 原始 CSV 清理

脚本：

```text
read_CSVs.py
```

主要处理：

```text
1. 读取 data/nano/*.csv。
2. 提取 Hchain sequence、CDRH1/2/3、Antigen sequence_1。
3. 保留 antigen_type 为 protein 或 peptide 的记录。
4. 保存 data_filter.pickle。
5. 写出 nanobody_seqs.fasta。
```

输出：

```text
data/asPICKLE/data_filter.pickle
data/asFASTA/nanobody_seqs.fasta
```

注意：代码中 resolution 条件写成：

```python
if float(resolution) >= 3.0:
    keep
```

这和常规结构质量筛选习惯不完全一致，因为一般结构分辨率越小越好。复现作者结果时按代码执行即可；如果我们构建自己的 PVRIG 结构数据，应重新定义清楚结构质量过滤规则。

## 7. 去冗余与抗原聚类

### 7.1 VHH 去冗余

README 中使用 CD-HIT 对 nanobody sequence 去冗余：

```bash
cd-hit -i nanobody_seqs.fasta \
  -o nanobody_seqs_98.fasta \
  -c 0.98 \
  -n 5
```

含义：

```text
VHH sequence identity >= 98% 的序列去冗余。
```

### 7.2 抗原序列聚类

先由 `prepareAntigenSeqs.py` 在去除 VHH 冗余后写出 antigen FASTA：

```text
data/asFASTA/antigen_seqs_after_nanobody_identiy98.fasta
```

然后用 CD-HIT 按 antigen sequence 聚类：

```bash
cd-hit -i antigen_seqs_after_nanobody_identiy98.fasta \
  -o antigen_seqs_after_nanobody_identiy98_90.fasta \
  -c 0.90 \
  -n 5
```

含义：

```text
抗原序列 identity >= 90% 归为同组。
```

这一步会产生：

```text
antigen_seqs_after_nanobody_identiy98_90.fasta.clstr
```

后续用这个 cluster 文件构造 intra-group / inter-group 样本。

## 8. 正负样本构造

这是 NABP-LSTM-Att 最值得借鉴的部分。

### 8.1 Intra-group binding

脚本：

```text
create_intra_inter_group_binding.py
```

对于同一个 antigen cluster 内的不同复合物，构造交叉配对：

```text
VHH_i + antigen_j -> positive
VHH_j + antigen_i -> positive
```

代码中保存为：

```text
data/asPICKLE/intra_group_binding.pickle
```

逻辑假设：

```text
如果两个抗原序列很相似，那么一个 VHH 可能也能结合另一个同组抗原。
```

### 8.2 Inter-group binding

不同 antigen cluster 之间构造交叉配对：

```text
VHH_i + antigen_j_from_other_group
VHH_j + antigen_i_from_other_group
```

保存为：

```text
data/asPICKLE/inter_group_binding.pickle
```

后续从其中随机采样作为 negative。

逻辑假设：

```text
不同抗原组之间的交叉配对更可能不结合。
```

### 8.3 系统发育树 cluster

README 要求用 Clustal Omega 对 antigen sequences 构造 phylogenetic tree，然后整理成 5 个 cluster，保存为：

```text
data/clusters.csv
```

本地 `clusters.csv` 包含 5 行，对应 5 个抗原 cluster。

`phylogenetic_tree_clusters.py` 会把这些 cluster 保存为：

```text
data/asPICKLE/clusters.pickle
```

### 8.4 Train / validation / test 构造

脚本：

```text
create_train_test_datasets.py
```

核心逻辑：

```text
1. 对每个 phylogenetic cluster 内的真实 positive 复合物做 80/20 train/test 划分。
2. 对 intra_group_binding 做 80/20 train/test 划分。
3. 合并真实 positive 和 intra-group positive。
4. 从 inter_group_binding 中随机采样等量 negative。
5. negative 也做 80/20 train/test 划分。
6. 从 train 中再取 5% 做 validation。
7. 每个 VHH-antigen pair 拆成 CDR1/CDR2/CDR3 三条 CDR-antigen 样本。
```

输出：

```text
data/asPICKLE/train_data_pos.pickle
data/asPICKLE/val_data_pos.pickle
data/asPICKLE/test_data_pos.pickle
data/asPICKLE/train_data_neg.pickle
data/asPICKLE/val_data_neg.pickle
data/asPICKLE/test_data_neg.pickle
data/asPICKLE/train_CDR_antigen.pickle
data/asPICKLE/val_CDR_antigen.pickle
data/asPICKLE/test_CDR_antigen.pickle
```

注意：负样本是构造出来的，不等于实验验证的 non-binder。

## 9. k-mer 表示和特征文件

### 9.1 词表

本地词表：

```text
vocab/vocab_1kmer.txt
vocab/vocab_2kmer.txt
vocab/vocab_3kmer.txt
```

本地统计：

```text
vocab_1kmer.txt: 21 tokens
  20 个氨基酸 + [UNK]

vocab_2kmer.txt: 401 tokens
  400 个 2-mer + [UNK]

vocab_3kmer.txt: 8001 tokens
  8000 个 3-mer + [UNK]
```

### 9.2 TSV 格式

脚本：

```text
createTSV.py
```

它将数据写成两类 TSV：

```text
CDR_tr.tsv / CDR_val.tsv / CDR_te.tsv
Ag_tr.tsv / Ag_val.tsv / Ag_te.tsv
```

每行格式：

```tsv
mode    ID    label    tokenized_sequence    CDR_number
```

例如：

```text
train    sample_001    1    qvq vql qlv ...    3
```

### 9.3 Feature pickle

脚本：

```text
embedding.py
```

它读取 TSV，转换成 `InputFeatures`：

```text
input_ids
label_id
cdr_number_ids
```

输出目录：

```text
data/features/cdr_kmer{X}_ag_kmer{Y}/
```

每组包含：

```text
cdr_features_tr.pickle
cdr_features_val.pickle
cdr_features_te.pickle
ag_features_tr.pickle
ag_features_val.pickle
ag_features_te.pickle
```

## 10. 训练集规模

作者提供的默认特征组合：

```text
cdr_kmer3_ag_kmer1
```

本地统计如下。

CDR-level 样本数：

```text
train:
  total: 6,144
  positive: 3,069
  negative: 3,075

validation:
  total: 324
  positive: 162
  negative: 162

test:
  total: 1,626
  positive: 816
  negative: 810
```

因为每个 VHH-antigen pair 被拆成 3 条 CDR 样本，所以 pair-level 约为：

```text
train:
  2,048 个 VHH-antigen pair

validation:
  108 个 VHH-antigen pair

test:
  542 个 VHH-antigen pair

合计:
  2,698 个 VHH-antigen pair
```

正负 pair 基本平衡：

```text
positive pair: 约 1,349
negative pair: 约 1,349
```

## 11. 序列长度统计

默认 `cdr_kmer3_ag_kmer1`：

```text
CDR token length:
  train min 1, median 5, max 22
  val   min 2, median 5, max 19
  test  min 1, median 5, max 22

Antigen token length:
  train min 66, median 489, max 2279
  val   min 118, median 491, max 2279
  test  min 66, median 438, max 1537
```

因为 CDR 使用 3-mer，所以一个 7 aa 的 CDR 会变成 5 个 token。

与 NABP-BERT 相比，NABP-LSTM-Att 能处理更长抗原。NABP-BERT 受 BERT 512 长度限制，抗原被限制到约 338 aa；NABP-LSTM-Att 默认 antigen 最大 token 长度为 2371。

## 12. k-mer 组合和权重

作者提供 9 组 k-mer 组合：

```text
cdr_kmer1_ag_kmer1
cdr_kmer1_ag_kmer2
cdr_kmer1_ag_kmer3
cdr_kmer2_ag_kmer1
cdr_kmer2_ag_kmer2
cdr_kmer2_ag_kmer3
cdr_kmer3_ag_kmer1
cdr_kmer3_ag_kmer2
cdr_kmer3_ag_kmer3
```

默认训练/测试脚本：

```python
cdr_kmer = 3
ag_kmer = 1
```

对应权重：

```text
model/cdr_kmer3_ag_kmer1/Model99.h5
```

重要坑：`createTSV.py` 和 `embedding.py` 中默认写的是：

```python
CDR_kmer = 3
Ag_kmer = 3
```

而 `train.py` 和 `test.py` 默认是：

```python
cdr_kmer = 3
ag_kmer = 1
```

如果要重新生成默认模型的特征，需要把 `createTSV.py` 和 `embedding.py` 的 `Ag_kmer` 改成 1，否则会生成 `cdr_kmer3_ag_kmer3`，与默认模型不匹配。

## 13. 训练方法

训练脚本：

```text
train.py
```

默认设置：

```python
cdr_kmer = 3
ag_kmer = 1
epochs = 100
batch_size = 64
optimizer = adam
loss = binary_crossentropy
```

运行：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NABP-LSTM-Att
python train.py
```

每个 epoch 结束后，callback 会：

```text
1. 在 validation set 上预测。
2. 计算 AUROC。
3. 计算 AUPR。
4. 保存当前 epoch 权重。
```

权重保存路径：

```text
model/cdr_kmer3_ag_kmer1/Model0.h5
model/cdr_kmer3_ag_kmer1/Model1.h5
...
model/cdr_kmer3_ag_kmer1/Model99.h5
```

原始代码没有 early stopping，也没有自动选择 validation AUPR 最佳模型。测试脚本固定加载：

```text
Model99.h5
```

如果我们自己训练，建议改成保存 validation AUPR 最优权重。

## 14. 测试方法

测试脚本：

```text
test.py
```

默认加载：

```text
data/features/cdr_kmer3_ag_kmer1/cdr_features_te.pickle
data/features/cdr_kmer3_ag_kmer1/ag_features_te.pickle
model/cdr_kmer3_ag_kmer1/Model99.h5
```

运行：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NABP-LSTM-Att
python test.py
```

输出：

```text
AUC_test : ...
AUPR_test : ...
```

README 报告：

```text
AUROC = 0.926
AUPR = 0.952
```

注意：这个指标基于作者构造的 CDR-level 数据集，不能直接等价于 PVRIG blocker 任务性能。

## 15. 环境复现

`requirments.txt` 中推荐：

```text
h5py 2.9.0
keras 2.2.4
numpy 1.17.4
scikit-learn 0.22
scipy 1.4.1
six 1.13.0
tensorflow 1.15.0
tensorflow-gpu 2.1.0
```

代码使用老 Keras / TensorFlow 1.x 风格，因此建议单独环境：

```bash
conda create -n nabp_lstm python=3.7 -y
conda activate nabp_lstm
pip install numpy==1.17.4 scipy==1.4.1 scikit-learn==0.22 six==1.13.0 h5py==2.9.0
pip install tensorflow==1.15.0 keras==2.2.4
```

如果需要 GPU，需要匹配老 CUDA/cuDNN。只做结构分析和数据处理时，不建议优先折腾 GPU 环境。

## 16. 对 PVRIG 项目的可用点

### 16.1 CDR-aware 思路很适合迁移

PVRIG blocker 任务高度依赖 VHH 的 CDR，尤其 CDR3。NABP-LSTM-Att 的最大价值是明确把 CDR1/CDR2/CDR3 作为模型核心输入。

这适合改造成：

```text
CDR-aware VHH-PVRIG binding classifier
CDR-aware PVRIG-PVRL2 blocker classifier
```

### 16.2 模型轻，适合快速改造

与 ESM2 或 BERT 模型相比，NABP-LSTM-Att 权重只有数 MB 到十几 MB：

```text
cdr_kmer3_ag_kmer1/Model99.h5: 约 10 MB
```

结构简单：

```text
Embedding + CNN + BiLSTM + Attention
```

适合快速做 PVRIG-specific 实验。

### 16.3 可做方案中的 CDR-aware baseline

我们可以将它作为：

```text
CDR-aware deep learning baseline
```

与其他模型形成互补：

```text
DeepNano: ESM2 + site prompt
NABP-BERT: BERT sequence-only
NABP-LSTM-Att: CDR-aware BiLSTM attention
Sequence-Based NABP: gapped k-mer traditional ML
NanoBinder: structure-based scoring
NanoBind: newer multitask Nb-Ag framework
```

## 17. 对 PVRIG 项目的局限

### 17.1 仍然只是 binding classifier

NABP-LSTM-Att 判断：

```text
是否结合 antigen
```

不是：

```text
是否阻断 PVRIG-PVRL2
```

因此它可能选出结合 PVRIG 但不阻断 PVRIG-PVRL2 的 VHH。

### 17.2 没有 residue-level interface 输出

模型有 attention，但 attention 不等于真实界面。它不能直接输出：

```text
PVRIG 哪些残基可能被 VHH 接触
```

也不能判断：

```text
VHH 接触位点是否覆盖 PVRIG-PVRL2 interface
```

这部分需要 DeepNano-site、NanoBind、docking 或自建 interface predictor 补充。

### 17.3 负样本是构造的

负样本来自 inter-group antigen swap，而不是实验确认 non-binder。对 PVRIG 项目，更重要的 hard negative 是：

```text
结合 PVRIG 但不阻断 PVRIG-PVRL2 的 VHH
```

### 17.4 CDR 拆分标签可能引入噪声

官方做法把一个 pair 的标签复制给 CDR1/CDR2/CDR3：

```text
CDR1 + antigen -> pair label
CDR2 + antigen -> pair label
CDR3 + antigen -> pair label
```

但真实 binding 可能主要由 CDR3 贡献，CDR1/CDR2 只是辅助。给三个 CDR 相同标签会引入标签噪声。

自建模型建议改成：

```text
CDR1、CDR2、CDR3 同时输入
由模型自己学习各 CDR 权重
或者显式提高 CDR3 权重
```

## 18. 推荐的 PVRIG 改造方案

如果借鉴 NABP-LSTM-Att，建议不要原样拆成三条 CDR 样本，而是设计成多输入模型。

推荐输入：

```text
CDR1 sequence
CDR2 sequence
CDR3 sequence
PVRIG ECD sequence
PVRIG-PVRL2 interface mask
```

推荐输出：

```text
bind_label:
  是否结合 PVRIG

block_label:
  是否阻断 PVRIG-PVRL2

interface_overlap_score:
  是否可能覆盖 PVRIG-PVRL2 界面

affinity_bin:
  高/中/低亲和力分档
```

推荐结构：

```text
CDR1/2/3 embeddings
  -> CDR type embedding
  -> CNN motif extractor
  -> BiLSTM / attention

PVRIG embedding
  -> interface mask prompt

concat
  -> binding head
  -> blocking head
  -> interface-overlap head
  -> affinity-bin head
```

这样比原始 NABP-LSTM-Att 更贴合 PVRIG-PVRL2 blocker 任务。

## 19. 项目定位

建议把 NABP-LSTM-Att 放在我们的模型体系中：

```text
DeepNano:
  第一层强 sequence model，提供 binding probability 和 site prompt。

NABP-BERT:
  独立 sequence-only BERT 模型，做投票 baseline。

NABP-LSTM-Att:
  CDR-aware 轻量模型，适合改造成 PVRIG-specific classifier。

NanoBinder / docking:
  结构打分和阻断界面评估。

自建 PVRIG blocker 模型:
  最终整合 binding、interface、blocking label。
```

## 20. 结论

NABP-LSTM-Att 的主要价值：

```text
1. 强调 CDR1/CDR2/CDR3，尤其适合 VHH 任务。
2. 模型轻，易改造，适合快速做 PVRIG-specific baseline。
3. 正负样本构造使用 antigen group / inter-group 思路，有数据工程参考价值。
4. 可作为 CDR-aware deep learning baseline 写入方案。
```

主要局限：

```text
1. 不是 blocker 模型。
2. 不输出 Kd、IC50 或 blocking rate。
3. 不预测 PVRIG residue-level interface。
4. 负样本是构造的，不是实验验证 non-binder。
5. CDR1/CDR2/CDR3 继承同一 pair label，可能引入噪声。
6. 老 TensorFlow/Keras 环境复现成本较高。
```

最终建议：

```text
NABP-LSTM-Att 不适合作为最终 PVRIG-PVRL2 blocker 排序模型，
但它是目前几个已看模型中最适合改造成 CDR-aware PVRIG 专用模型的轻量框架。
```
