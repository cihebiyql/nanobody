# NABP-BERT 详细复现与数据集说明

生成日期：2026-07-07  
工作目录：`/mnt/d/work/抗体/code`  
本地模型目录：`downloaded_models/NABP-BERT`

本文档记录 NABP-BERT 的模型思想、训练流程、数据集构造、输入输出、使用方法，以及它在 PVRIG-PVRL2 阻断型纳米抗体项目中的可用点和局限。重点放在数据集，因为 NABP-BERT 的负样本构造方式对自建 PVRIG 数据集有参考价值。

## 1. 一句话定位

NABP-BERT 是一个基于 BERT 的 nanobody-antigen binding prediction 模型。它输入一条 nanobody / VHH 序列和一条 antigen 序列，输出二者是否结合的二分类概率。

它适合回答：

```text
这个 VHH 和这个抗原是否像一个 binding pair？
```

它不适合单独回答：

```text
Kd 是多少？
是否阻断 PVRIG-PVRL2？
VHH 是否结合 PVRIG-PVRL2 功能界面？
抗原哪些残基被 VHH 接触？
```

因此，在 PVRIG 项目中，NABP-BERT 更适合作为 DeepNano 之外的第二个 sequence-only binding classifier / baseline，用来做模型投票和交叉验证，而不是最终 blocker 排序模型。

## 2. 本地文件与权重状态

代码目录：

```text
downloaded_models/NABP-BERT
```

主要文件：

```text
README.md                                      官方说明
bert_config_3.json                             BERT 配置，默认 1 层、hidden 768
vocab/vocab_3kmer.txt                          3-mer 氨基酸词表
Nb_Ag_Sequence_Processing.ipynb                Nb-Ag 原始数据处理 notebook
CleanNbAgSeqs.py                               清理 Nb-Ag 序列和标签
ConstructNbAgTrainValTestDatasets.py           划分 Nb-Ag train / val / test
createTSV.py                                   生成 firstProteins / secondProteins TSV
tsv2record.py                                  TSV 转 TFRecord
create_pretraining_data.py                     BERT pretrain 数据生成
run_pretraining.py                             BERT 预训练入口
run_classifier.py                              BERT 分类通用代码
run_classifier_fatma.py                        fine-tuning / evaluation 主脚本
run_classifier_test_fatma.py                   测试脚本
run_fine_tune.sh                               fine-tuning 示例脚本
run_test.sh                                    测试示例脚本
pre_train.sh                                   预训练示例脚本
create_data.sh                                 pretrain TFRecord 生成脚本
```

原始 Nb-Ag 数据：

```text
data/Nb_Ag_data/Ag_NbBindingDatawithSequences_Sheet1.csv
data/Nb_Ag_data/Antibodies_Pairwise_Distance_Matrix.csv
```

PPI 数据：

```text
data/PPI_data/*.txt
```

UniProt 数据：

```text
data/uniprot_raw/uniprot_sprot.fasta.gz
data/uniprot_raw/uniprot_trembl.fasta.gz
data/uniprot_sprot.fasta/uniprot_sprot.fasta
data/uniprot_trembl.fasta
```

模型权重包已下载并解压：

```text
downloaded_models/NABP-BERT/_downloads/google_drive/NABP-BERT-models.zip
downloaded_models/NABP-BERT/NABP-BERT-models
```

解压后的模型目录包括：

```text
NABP-BERT-models/NABP-BASIC-BERT/
NABP-BERT-models/NABP-PROT-BERT/
NABP-BERT-models/NABP-PPI-PROT-BERT/
NABP-BERT-models/PPI-PROT-BERT/
NABP-BERT-models/PROT-BERT/
```

重要提醒：官方脚本里默认 checkpoint 路径多写成 `./model/...`，但本地解压后的目录是 `./NABP-BERT-models/...`。实际运行时要么修改 `--init_checkpoint`，要么建立软链接。

## 3. 模型思想

NABP-BERT 的核心思想是把蛋白序列转成 k-mer token，然后用 BERT 处理序列对。

论文/README 中描述了三层模型：

```text
PROT-BERT
  普通蛋白序列自监督预训练模型。

PPI-PROT-BERT
  在普通 protein-protein interaction 数据上监督训练的模型。

NABP-BERT
  在 nanobody-antigen binding 数据上 fine-tune 的二分类模型。
```

NABP-BERT 有两个主要变体：

```text
NABP-PROT-BERT
  从 PROT-BERT 初始化，再 fine-tune 到 Nb-Ag binding。

NABP-PPI-PROT-BERT
  从 PPI-PROT-BERT 初始化，再 fine-tune 到 Nb-Ag binding。
```

可以理解为：

```text
大量普通蛋白序列
        ↓
PROT-BERT
        ↓
普通 PPI 数据
        ↓
PPI-PROT-BERT
        ↓
Nb-Ag binding 数据
        ↓
NABP-BERT
```

与 DeepNano 的区别：

```text
DeepNano:
  ESM2 protein language model + pooling ensemble + optional site prompt。

NABP-BERT:
  自己实现的 BERT + 3-mer tokenization + sequence-pair binary classifier。
```

NABP-BERT 没有 residue-level interface prediction，也没有 affinity regression。

## 4. 输入和输出

### 4.1 输入

模型输入是两条序列：

```text
VHH / nanobody sequence
antigen sequence
```

对于 PVRIG 项目，推荐输入：

```text
候选 VHH 序列
PVRIG extracellular domain, ECD 序列
```

不建议输入全长 PVRIG，因为跨膜区和胞内段对 VHH 结合预测没有帮助，还会占用 BERT 最大长度。

### 4.2 3-mer tokenization

NABP-BERT 不按单个氨基酸输入，而是使用 3-mer。

例如：

```text
原始序列:
QVQLVES

3-mer tokens:
qvq vql qlv lve ves
```

本地词表：

```text
downloaded_models/NABP-BERT/vocab/vocab_3kmer.txt
```

本地统计：

```text
总 token 数: 8004
特殊 token: [CLS], [SEP], [MASK], [UNK]
3-mer token: 8000 个
```

BERT 输入形式：

```text
[CLS] VHH_3mer_tokens [SEP] antigen_3mer_tokens [SEP]
```

### 4.3 最大长度限制

配置文件 `bert_config_3.json` 里：

```json
"max_position_embeddings": 512
```

由于输入需要 3 个特殊 token：

```text
[CLS]
[SEP]
[SEP]
```

所以 VHH 和 antigen 的 3-mer token 总数最多约 509。

代码注释中写到：

```text
VHH max length = 175 aa -> 173 个 3-mer token
antigen max length 需要约 <=338 aa
这样合并后约 509 token，再加 3 个特殊 token = 512
```

这就是 `CleanNbAgSeqs.py` 中过滤抗原长度的原因：

```python
if len(pair[1]) <= 338:
    keep
```

对 PVRIG 项目而言，PVRIG ECD 长度通常没问题，但仍应确认输入构建不会超过模型长度。

### 4.4 输出

模型是二分类输出：

```text
label 0 = non-binding
label 1 = binding
```

内部输出是 softmax probability：

```text
probability[:, 0] = non-binding probability
probability[:, 1] = binding probability
```

训练/验证脚本会计算：

```text
ACC
MCC
auROC
AUPR
SE / sensitivity
SP / specificity
confusion matrix
```

注意：这个输出不是 Kd，不是 IC50，也不是 blocking probability。

## 5. BERT 配置

本地配置文件：

```text
bert_config_3.json
```

当前内容要点：

```json
{
  "hidden_size": 768,
  "intermediate_size": 3072,
  "max_position_embeddings": 512,
  "num_attention_heads": 1,
  "num_hidden_layers": 1,
  "type_vocab_size": 2,
  "vocab_size": 8004
}
```

虽然下载的模型包中有不同 encoder/head 数量的模型，例如 10 encoders / 8 attention heads，脚本当前默认配置是 1 层、1 个 attention head。实际复现实验时，必须确保：

```text
bert_config_3.json 的 num_hidden_layers / num_attention_heads
和 init_checkpoint 对应模型结构一致
```

否则 checkpoint 可能无法完整加载或维度不匹配。

## 6. 数据集详解

### 6.1 原始 Nb-Ag 正样本

文件：

```text
data/Nb_Ag_data/Ag_NbBindingDatawithSequences_Sheet1.csv
```

字段：

```csv
sdAb-DB ID,
NB_ID,
Nanobody ID,
Source,
Antigen_ID,
Antigen,
Nanobody Sequence,
Antigen Sequence,
Ag-UniProt-ID
```

本地统计：

```text
原始正样本行数: 365
unique nanobody sequence: 357
unique antigen sequence: 46
unique antigen name: 48
unique Antigen_ID: 47
```

序列长度：

```text
VHH length:
  min 104
  median 123
  max 175

Antigen length:
  min 158
  median 537
  max 1816
```

来源分布前几类：

```text
Llama (Lama glama): 167
Arabian camel (Camelus dromedarius): 102
Alpaca (Vicugna pacos): 41
Synthetic Construct: 35
Camelid (Camelidae): 13
```

这 365 条基本是正样本，也就是已知 VHH-抗原结合对。

### 6.2 抗原距离矩阵

文件：

```text
data/Nb_Ag_data/Antibodies_Pairwise_Distance_Matrix.csv
```

这是抗原之间的 pairwise distance matrix。notebook 用这个矩阵生成额外正样本和负样本。

核心逻辑：

```text
如果 VHH 绑定抗原 A，且抗原 B 与 A 很相似：
  distance(A, B) <= 0.20
  则把 VHH-B 也作为扩展正样本。

如果 VHH 绑定抗原 A，且抗原 B 与 A 很不相似：
  distance(A, B) >= 0.85
  则把 VHH-B 作为负样本候选。
```

这是一种基于抗原相似性构造 label 的方法。

### 6.3 Nb-Ag 正负样本构造

notebook `Nb_Ag_Sequence_Processing.ipynb` 的主要逻辑：

```text
1. 读取 365 条真实 positive Nb-Ag pair。
2. 对每个 VHH，枚举其他抗原。
3. 如果替换抗原与原抗原 distance <= 0.20，则生成额外 positive。
4. 如果替换抗原与原抗原 distance >= 0.85，则生成 negative candidate。
5. 从 negative candidate 中随机采样，与 positive 数量平衡。
```

本地按 notebook 逻辑复算：

```text
原始正样本: 365
distance <= 0.20 扩展正样本: 1,388
最终正样本: 1,753

distance >= 0.85 候选负样本: 108,050
随机采样负样本: 1,753

合并后全量 Nb-Ag 数据: 3,506
  Yes: 1,753
  No: 1,753
```

这一步输出的 pickle 在官方流程中应保存为：

```text
dataAfterPreProcessing/Nb_Ag_Pairs_Dataset/Nb_Ag_full_dataset.pickle
```

其中每条样本是：

```python
(Nb_seq, Ag_seq, Ag_uniprot_id, label)
```

`label` 初始为：

```text
Yes
No
```

后续 `CleanNbAgSeqs.py` 会转换为：

```text
Yes -> 1
No -> 0
```

### 6.4 长度过滤后的 Cleaned_Nb_Ag_pairs

脚本：

```text
CleanNbAgSeqs.py
```

过滤规则：

```python
if len(antigen_seq) <= 338:
    keep
```

这样是为了让：

```text
VHH 3-mer tokens + antigen 3-mer tokens + [CLS]/[SEP]/[SEP] <= 512
```

本地复算得到：

```text
Cleaned_Nb_Ag_pairs: 1,314
  Yes: 562
  No: 752

VHH length:
  min 104
  median 123
  max 175

Antigen length:
  min 158
  median 约 250
  max 317

unique antigen UniProt IDs: 13
```

注意：过滤后正负样本不再完全平衡。并且只剩 13 个 unique antigen UniProt IDs，说明数据覆盖面比较窄。

### 6.5 Train / validation / test 划分

脚本：

```text
ConstructNbAgTrainValTestDatasets.py
```

逻辑：

```text
1. 对 Cleaned_Nb_Ag_pairs shuffle。
2. 90% 作为 trainCleaned_Nb_Ag_pairs。
3. 10% 作为 testCleaned_Nb_Ag_pairs。
4. 再从 trainCleaned_Nb_Ag_pairs 中取 5% 作为 validation。
```

也就是近似：

```text
train: 85.5%
validation: 4.5%
test: 10%
```

重要问题：这个划分是普通随机切分，不是按 antigen、VHH family、CDR3 cluster 或 clonotype 分组切分。对于序列模型，这可能导致相似样本泄漏，使测试指标偏高。

对 PVRIG 项目，不能简单照搬这种 random split。

### 6.6 TSV 格式

脚本：

```text
createTSV.py
```

它会把一对序列拆成两个 TSV 文件：

```text
firstProteins_tr.tsv
secondProteins_tr.tsv
firstProteins_val.tsv
secondProteins_val.tsv
firstProteins_te.tsv
secondProteins_te.tsv
```

每一行格式类似：

```tsv
mode	label		tokenized_sequence
```

例如：

```tsv
train	1		qvq vql qlv lve ves ...
train	1		abc bcd cde ...
```

一对样本通过两个文件的相同行号对应：

```text
firstProteins_tr.tsv 第 i 行 = VHH
secondProteins_tr.tsv 第 i 行 = antigen
```

`run_classifier.py` 中的 `fatma_create_examples()` 会把两个文件同一行合并成 BERT 的 `text_a` 和 `text_b`。

### 6.7 TFRecord 格式

脚本：

```text
tsv2record.py
```

默认输入：

```text
dataAfterPreProcessing/Nb_Ag_Pairs_Dataset/asTSV/
```

默认输出：

```text
dataAfterPreProcessing/Nb_Ag_Pairs_Dataset/asTF_Record/
```

输出文件：

```text
NbAg_train.tf_record
NbAg_val.tf_record
NbAg_test.tf_record
```

TFRecord 中包含：

```text
input_ids
input_mask
segment_ids
label_ids
is_real_example
```

## 7. PPI 与 UniProt 数据

### 7.1 PPI 数据

PPI 文件目录：

```text
data/PPI_data/
```

本地已有 HINT binary high-quality 文件，例如：

```text
HomoSapiens_binary_hq.txt
MusMusculus_binary_hq.txt
DrosophilaMelanogaster_binary_hq.txt
SaccharomycesCerevisiae_binary_hq.txt
EscherichiaColi_binary_hq.txt
```

本地粗略行数：

```text
HomoSapiens_binary_hq.txt: 163,436 行
DrosophilaMelanogaster_binary_hq.txt: 31,307 行
SaccharomycesCerevisiae_binary_hq.txt: 29,858 行
ArabidopsisThaliana_binary_hq.txt: 26,204 行
CaenorhabditisElegans_binary_hq.txt: 11,859 行
MusMusculus_binary_hq.txt: 5,202 行
EscherichiaColi_binary_hq.txt: 4,823 行
SchizosaccharomycesPombe_binary_hq.txt: 3,799 行
RattusNorvegicus_binary_hq.txt: 938 行
OryzaSativa_binary_hq.txt: 290 行
```

`CleanHINTdatabase.py` 会读取这些 PPI 文件，抽取 UniProt pair，保存为：

```text
dataAfterPreProcessing/PPI_Dataset/set_pairs.pickle
dataAfterPreProcessing/PPI_Dataset/unique_protein_set.pickle
```

### 7.2 UniProt 数据

本地文件：

```text
data/uniprot_raw/uniprot_sprot.fasta.gz
data/uniprot_raw/uniprot_trembl.fasta.gz
data/uniprot_sprot.fasta/uniprot_sprot.fasta
data/uniprot_trembl.fasta
```

本地大小约：

```text
uniprot_sprot.fasta.gz: 94 MB
uniprot_trembl.fasta.gz: 40.5 GB
uniprot_sprot.fasta: 288 MB
uniprot_trembl.fasta: 78 GB
```

这些数据用于：

```text
1. PROT-BERT self-supervised pretraining。
2. 给 HINT PPI pair 补蛋白序列。
```

### 7.3 PPI 负样本构造

脚本：

```text
ConstructPPINegativeSamples.py
```

逻辑：

```text
正样本:
  HINT 中真实 interacting pair。

负样本:
  从正样本的 firstProtein 列随机抽一个，
  从 secondProtein 列随机抽一个，
  拼成非原始配对。
```

这种负样本构造方式简单高效，但也有噪声：随机拼出的 pair 不一定真的不相互作用，只是未知/未记录。

## 8. 训练流程

NABP-BERT 的完整训练流程比较重，可以分成四步。

### 8.1 准备 Nb-Ag 数据

官方 README 建议先在 Google Colab 中执行：

```text
Nb_Ag_Sequence_Processing.ipynb
```

它会生成：

```text
dataAfterPreProcessing/Nb_Ag_Pairs_Dataset/Nb_Ag_full_dataset.pickle
```

然后执行：

```bash
python CleanNbAgSeqs.py
python ConstructNbAgTrainValTestDatasets.py
```

接着生成 TSV 和 TFRecord：

```bash
python createTSV.py
python tsv2record.py
```

### 8.2 准备 PPI 数据

官方流程：

```bash
python createDatabase.py
python get_unmappedKeysInSwissPortDatabase.py
python ExtractingProteinSeqsFromTrembleDatabase.py
python CleanHINTdatabase.py
python PrepearPPIDatasetSequences.py
python Remove_Homology.py
python ConstructPPINegativeSamples.py
```

这一步会构建 PPI pair、补 UniProt 序列、过滤长度、去除同源性、构造负样本。

### 8.3 PROT-BERT pretraining

先准备普通蛋白预训练数据：

```bash
python Prepear_PreTrain_Dataset.py
```

然后生成 TFRecord：

```bash
sh create_data.sh
```

`create_data.sh` 实际调用：

```bash
python create_pretraining_data.py \
  --input_file=./dataAfterPreProcessing/PreTrainDataset/PretrainData_Final.txt \
  --output_file=./dataAfterPreProcessing/PreTrainDataset/PretrainData_Final.tfrecord \
  --vocab_file=./vocab/vocab_3kmer.txt \
  --do_lower_case=True \
  --max_seq_length=512 \
  --max_predictions_per_seq=20 \
  --masked_lm_prob=0.15 \
  --random_seed=12345 \
  --dupe_factor=5
```

再进行预训练：

```bash
sh pre_train.sh
```

`pre_train.sh` 中关键参数：

```text
input_file: PretrainData_Final.tfrecord
output_dir: model/3kmer_model/num_hidden_layers_10/num_attention_heads_8/
train_batch_size: 8
max_seq_length: 512
num_train_steps: 1,000,000
learning_rate: 2e-5
```

这一步非常重，通常不建议从头复现。已有预训练权重时应直接使用下载的 checkpoint。

### 8.4 Fine-tuning 到 Nb-Ag binding

示例脚本：

```bash
sh run_fine_tune.sh
```

脚本中关键参数：

```bash
python run_classifier_fatma.py \
  --data_name=NbAg \
  --data_root=./dataAfterPreProcessing/Nb_Ag_Pairs_Dataset/asTF_Record/ \
  --do_eval=True \
  --num_train_epochs=100 \
  --batch_size=64 \
  --bert_config=./bert_config_3.json \
  --vocab_file=./vocab/vocab_3kmer.txt \
  --init_checkpoint=... \
  --save_path=...
```

重要提醒：`run_classifier_fatma.py` 里有硬编码路径问题。虽然参数 `data_name=NbAg`，但是代码中训练集/验证集默认可能仍指向 PPI：

```python
input_file = data_root + "PPI_train.tf_record"
# input_file = data_root + "NbAg_train.tf_record"
```

验证集也类似：

```python
input_file = data_root + "PPI_val.tf_record"
# input_file = data_root + "NbAg_val.tf_record"
```

如果要训练 Nb-Ag，必须改成：

```python
input_file = data_root + "NbAg_train.tf_record"
input_file = data_root + "NbAg_val.tf_record"
```

否则会用错数据，或者直接找不到文件。

## 9. 环境复现

官方 README 推荐：

```text
python 3.7.6
tensorflow 1.15.0
tensorflow-gpu 2.1.0
six 1.13.0
numpy 1.17.4
scikit-learn 0.22
```

这里有一个明显历史遗留问题：`tensorflow==1.15.0` 和 `tensorflow-gpu==2.1.0` 同时出现并不干净。代码本身使用的是 TensorFlow 1.x 风格：

```text
tf.app.flags
tf.Session
tf.placeholder
tf.contrib
tf.python_io.TFRecordWriter
```

因此更合理的复现方向是 TensorFlow 1.x 环境。

建议环境：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NABP-BERT
conda create -n nabpbert python=3.7 -y
conda activate nabpbert
pip install numpy==1.17.4 scipy==1.4.1 scikit-learn==0.22 six==1.13.0 h5py==2.9.0
pip install tensorflow==1.15.0
```

如果需要 GPU，需要匹配老版本 CUDA/cuDNN；这个环境比 DeepNano 更难复现。只做数据处理和文档分析时，不建议先花时间处理 GPU 环境。

## 10. 如何用自己的 PVRIG 数据

如果要把 PVRIG 数据放进 NABP-BERT 流程，最小格式是：

```python
(VHH_seq, PVRIG_ECD_seq, antigen_id_or_uniprot_id, label)
```

其中：

```text
label = 1 表示结合 PVRIG
label = 0 表示不结合 PVRIG
```

然后需要生成两个 TSV 文件：

```text
firstProteins_tr.tsv      VHH 3-mer tokens
secondProteins_tr.tsv     PVRIG 3-mer tokens
```

每行格式：

```tsv
train	1		qvq vql qlv lve ...
```

再通过 `tsv2record.py` 转成 TFRecord。

如果只是推理候选 VHH-PVRIG pair，需要准备类似的 tokenized TSV，然后用已有 checkpoint 加载模型输出 `probability[:, 1]`。

不过官方仓库没有一个像 DeepNano `predict.py` 那样简单的自定义 FASTA 推理入口；实际使用时需要额外写一个小脚本，把 FASTA/CSV 转为 tokenized TSV/TFRecord，再调用模型。

## 11. 对 PVRIG 项目的可用点

### 11.1 可作为第二个 sequence-only binding scorer

DeepNano 和 NABP-BERT 的模型架构不同：

```text
DeepNano: ESM2 embedding
NABP-BERT: 3-mer BERT
```

因此可以把 NABP-BERT 作为 DeepNano 之外的独立序列模型，用来交叉验证。

推荐使用方式：

```text
DeepNano 高分 + NABP-BERT 高分:
  更像 PVRIG binder，优先保留。

DeepNano 高分 + NABP-BERT 低分:
  可能模型分歧，进入结构复核。

DeepNano 低分 + NABP-BERT 高分:
  可能是 DeepNano 漏掉的候选，进入备选池。

两个都低:
  优先过滤。
```

### 11.2 可借鉴抗原相似性负样本构造

NABP-BERT 最值得借鉴的是数据构造：

```text
利用 antigen similarity / distance matrix 构造扩展正样本和负样本。
```

对 PVRIG 项目，可以借鉴为：

```text
PVRIG vs 其他 IgSF/checkpoint 抗原的相似性矩阵
PVRIG ortholog / mutant / domain construct 的相似性矩阵
PVRIG-PVRL2 interface mutant 的功能差异矩阵
```

但是不能直接照搬“distance >= 阈值就是负样本”。对于 blocker 项目，更重要的是功能标签。

### 11.3 可作为传统深度学习 baseline

NABP-BERT 可以写进方案中作为：

```text
sequence-only BERT baseline
```

与以下模型形成对照：

```text
DeepNano: ESM2 + site prompt
NABP-LSTM-Att: BiLSTM + attention
Sequence-Based NABP: gapped k-mer + traditional ML
NanoBinder: structure-based RF
NanoBind: newer multitask Nb-Ag model
```

## 12. 对 PVRIG 项目的局限

### 12.1 不是 blocker 模型

NABP-BERT 只能判断：

```text
VHH 是否可能结合 PVRIG
```

不能判断：

```text
是否阻断 PVRIG-PVRL2
```

它可能选出很多：

```text
结合 PVRIG 但不阻断 PVRIG-PVRL2 的 VHH
```

这类在我们的项目中是 hard negative。

### 12.2 没有界面 residue 输出

NABP-BERT 没有类似 DeepNano-site 的输出，因此不能直接给出：

```text
VHH 可能接触 PVRIG 哪些残基
VHH 接触位点是否覆盖 PVRIG-PVRL2 界面
```

这限制了它在 blocker 任务中的解释性。

### 12.3 数据规模小且抗原覆盖窄

过滤后 Nb-Ag 数据约 1,314 条，unique antigen UniProt ID 约 13 个。这个规模对泛化能力是明显限制。

### 12.4 负样本是构造出来的

负样本来自抗原替换和 distance 阈值，不等于真实实验验证 non-binder。

在 PVRIG 项目中，真实 hard negative 更重要：

```text
实验确认不结合 PVRIG 的 VHH
实验确认结合 PVRIG 但不阻断 PVRIG-PVRL2 的 VHH
```

### 12.5 随机切分可能导致泄漏

官方流程使用随机切分。对于序列任务，应避免同源 VHH、同一 CDR3 family、同一 antigen family 同时出现在 train 和 test。

PVRIG 项目应使用 group split：

```text
按 CDR3 cluster 分组
按 VHH clonotype 分组
按 discovery batch 分组
按 antigen construct 分组
```

## 13. 建议的 PVRIG 数据格式

如果借鉴 NABP-BERT，但面向我们的 blocker 项目，建议不要只做二分类表，而应扩展为：

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
pvrig_pvrl2_interface_residues,
pvrig_pvrl2_overlap_score,
source,
batch,
split_group
```

其中最关键的是：

```text
bind_label:
  是否结合 PVRIG。

block_label:
  是否阻断 PVRIG-PVRL2。

pvrig_pvrl2_overlap_score:
  VHH 结合区域与 PVRIG-PVRL2 界面的重叠程度。
```

如果要用 NABP-BERT 思路构造负样本，建议分层：

```text
easy negative:
  明确不结合 PVRIG 的 VHH。

target negative:
  结合其他 checkpoint/IgSF 靶点但不结合 PVRIG 的 VHH。

hard negative:
  结合 PVRIG 但不阻断 PVRIG-PVRL2 的 VHH。

decoy negative:
  CDR3 相似但功能不同的 VHH。
```

## 14. 推荐在项目中的定位

NABP-BERT 在我们项目中建议放在第二层：

```text
第一层:
  DeepNano / DeepNano-site
  得到 VHH-PVRIG 结合概率和潜在 PVRIG 接触区域。

第二层:
  NABP-BERT
  独立 sequence-only 模型打分，做交叉验证和投票。

第三层:
  docking / NanoBinder 类结构打分
  评估 pose、界面能、shape complementarity、clash、buried SASA。

第四层:
  PVRIG-PVRL2 interface overlap / blocker-specific model
  判断是否可能阻断功能界面。
```

不要把 NABP-BERT 的 binding probability 单独作为最终排序。

## 15. 结论

NABP-BERT 的主要价值：

```text
1. 提供一个独立于 DeepNano 的 sequence-only BERT baseline。
2. 使用 3-mer tokenization，适合解释为传统 protein k-mer + transformer 模型。
3. 数据构造中使用 antigen distance matrix，这对自建负样本有启发。
4. 可以作为 PVRIG binder 初筛的辅助投票模型。
```

主要局限：

```text
1. 不是 blocker 模型。
2. 不输出 Kd、IC50 或 blocking rate。
3. 不预测界面残基。
4. TensorFlow 1.x 老代码，环境复现成本较高。
5. Nb-Ag 数据过滤后规模较小，抗原覆盖较窄。
6. 负样本是基于距离矩阵构造，不等于真实实验 non-binder。
```

最终建议：

```text
NABP-BERT 适合保留为 PVRIG 项目的 sequence-only baseline 和 DeepNano 的交叉验证模型。
如果要训练我们自己的 PVRIG AI 模型，应该借鉴它的 k-mer/BERT 表示和 antigen-distance 负样本思想，但必须额外加入 blocker/non-blocker 标签、PVRIG-PVRL2 interface overlap 和真实实验 hard negatives。
```
