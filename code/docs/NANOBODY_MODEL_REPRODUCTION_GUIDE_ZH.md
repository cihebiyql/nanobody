# 纳米抗体-抗原模型代码本地复现手册

生成日期：2026-07-06  
工作目录：`/mnt/d/work/抗体/code`  
本地代码根目录：`downloaded_models/`

本手册覆盖 6 个模型：DeepNano、NABP-BERT、NABP-LSTM-Att、Sequence-Based Nanobody-Antigen Binding Prediction、NanoBinder、NanoBind。目标不是只列论文摘要，而是让后续人员能按本地路径、依赖、数据、权重和命令逐个复现实验或推理。

## 0. 本地下载状态总表

| 模型 | 本地路径 | 代码/数据状态 | 权重状态 | 一句话定位 |
|---|---|---|---|---|
| DeepNano | `downloaded_models/DeepNano`；配套数据 `downloaded_models/DeepNano-data` | 已下载作者仓库、数据、ESM2-8M/35M/150M/650M encoder；35M/150M/650M checkpoint 正在后台续传 | 已补齐 8M 四个 checkpoint | 序列 + prompt site 的 NAI/PPI 结合预测 |
| NABP-BERT | `downloaded_models/NABP-BERT` | 已下载代码、少量原始 Nb-Ag 数据、vocab；HINT/UniProt 训练数据正在后台续传 | Google Drive 大模型包已下载完成 | K-mer BERT 序列二分类 |
| NABP-LSTM-Att | `downloaded_models/NABP-LSTM-Att` | 已下载代码、vocab、补充材料 | Google Drive 预处理特征/权重包已下载完成 | CDR-aware BiLSTM + attention 二分类 |
| Sequence-Based NABP | `downloaded_models/Sequence-Based-NABP` | 已下载官方 notebook 仓库和数据；另有本地 CLI helper | 无发布权重，传统 ML 需重训 | gapped k-mer + RF/SVM 等 baseline |
| NanoBinder | `downloaded_models/NanoBinder` | 已下载训练脚本；仓库不含论文 `dataset.csv` | 无可直接推理权重 | Rosetta energy score + RF 结构打分 |
| NanoBind | `downloaded_models/NanoBind` | 已下载代码、数据、ESM2-8M encoder、全部主要 checkpoint | `seq/site/pro/pair` 均已补齐；原 LFS 指针保留为 `.lfs-pointer.txt` | 多任务：结合、界面、相对亲和力、Kd 区间 |

下载来源清单保存在：`downloaded_models/_sources/repositories.tsv`。GitHub API 元数据保存在：`downloaded_models/_sources/github_metadata.json`。

后台断点下载入口：

```bash
cd /mnt/d/work/抗体/code
bash downloads_background/scripts/start_all_downloads.sh
bash downloads_background/scripts/status.sh
```

日志目录：`downloads_background/logs/`。当前长任务包括 DeepNano 扩展 checkpoint、NABP-BERT HINT/UniProt 训练数据；DeepNano 扩展 ESM2 encoder、NABP-BERT Google Drive 模型包、NABP-LSTM-Att Google Drive 文件夹与 NanoBind site checkpoint 已经完成。

## 1. DeepNano

### 1.1 论文与代码来源

- 论文：Deng et al., `Nanobody-antigen interaction prediction with ensemble deep learning and prompt-based protein language models`, Nature Machine Intelligence, 2024。DOI：`10.1038/s42256-024-00940-5`。
- 作者仓库：<https://github.com/ddd9898/DeepNano>
- 配套数据仓库：<https://github.com/ddd9898/DeepNano-data>
- 本地路径：`downloaded_models/DeepNano`、`downloaded_models/DeepNano-data`

### 1.2 模型思想

DeepNano 专门面向 nanobody-antigen interaction，而不是直接套普通 PPI 模型。仓库包含三类模型：

- `DeepNano-seq(PPI)`：先在通用 PPI 数据上训练的 sequence-only 模型。
- `DeepNano-seq(NAI)`：在 nanobody-antigen interaction 数据上训练的 sequence-only 模型。
- `DeepNano(NAI)`：在 sequence-only 基础上加入 `DeepNano-site` 的抗原结合位点 prompt 信息，试图让抗原潜在界面信息参与判断。

对 PVRIG 项目的用途：适合做第一层快速筛选，回答“这个 VHH 序列和 PVRIG 胞外域是否像一个可能结合对”。它不能直接输出可靠 Kd，也不判断是否阻断 PVRIG-PVRL2 表位。

### 1.3 本地文件结构

关键文件：

- `downloaded_models/DeepNano/README.md`：官方安装、checkpoint、demo。
- `downloaded_models/DeepNano/predict.py`：推理入口；注意输入路径在文件顶部硬编码。
- `downloaded_models/DeepNano/train_Sabdab.py`：NAI 训练入口。
- `downloaded_models/DeepNano/train_Sabdab_Site.py`：site 模型训练入口。
- `downloaded_models/DeepNano/test_nai.py`：复现 NAI 测试结果。
- `downloaded_models/DeepNano/data/Nanobody_Antigen-main/`：默认 Nb-Ag pair/sequence 数据。
- `downloaded_models/DeepNano/data/Sabdab/`：训练/验证和 5A interface site 数据。
- `downloaded_models/DeepNano/models/esm2_t6_8M_UR50D/`：仓库自带 ESM2-8M encoder。

已补齐的 8M checkpoint：

```text
downloaded_models/DeepNano/output/checkpoint/DeepNano_seq(esm2_t6_8M_UR50D)_DScriptData_finetune1_best.model
downloaded_models/DeepNano/output/checkpoint/DeepNano_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_best.model
downloaded_models/DeepNano/output/checkpoint/DeepNano_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_best.model
downloaded_models/DeepNano/output/checkpoint/DeepNano(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_best.model
```

### 1.4 环境复现

官方 README 指定：Python 3.9、PyTorch 1.13.1 + CUDA 11.6、`transformers==4.27.4`、`biopython==1.78`、`pandas==1.3.5`、`scikit-learn==1.0.2`。

推荐独立环境：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/DeepNano
conda create -n deepnano python=3.9 -y
conda activate deepnano
pip install torch==1.13.1 torchvision==0.14.1 torchaudio==0.13.1 --extra-index-url https://download.pytorch.org/whl/cu116
pip install -r requirements.txt
pip install tqdm
```

无 GPU 时也能尝试 CPU 推理，但 ESM2 和 ensemble 会慢很多。训练建议 GPU。

### 1.5 快速推理复现

官方 `predict.py` 默认读取：

```python
fasta_path = './data/Nanobody_Antigen-main/all_pair_data.seqs.fasta'
pair_path = './data/Nanobody_Antigen-main/all_pair_data.pair.tsv'
output_path = './output/predictions.csv'
```

运行默认 NAI sequence-only 模型：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/DeepNano
conda activate deepnano
python predict.py --model 1 --esm2 8M
```

模型编号：

- `--model 0`：DeepNano-seq(PPI)，需要 DScriptData checkpoint。
- `--model 1`：DeepNano-seq(NAI)，推荐作为 PVRIG 初筛 baseline。
- `--model 2`：DeepNano(NAI)，会额外加载 site checkpoint，推荐作为带界面 prompt 的初筛。

输出：`downloaded_models/DeepNano/output/predictions.csv`，列为 `Nanobody ID, Antigen ID, Prediction`。`Prediction` 是结合概率样式的分数，不要直接解释为 Kd。

### 1.6 自定义 PVRIG 输入

`predict.py` 没有 CLI 参数传路径，最稳妥做法是复制一份再改顶部 3 个变量：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/DeepNano
mkdir -p data/custom_pvrig output/custom_pvrig
cp predict.py predict_pvrig.py
```

准备 FASTA：

```text
>vhh_001
EVQLVESGGGLVQPGGSLRLSCAAS...
>pvrig_ecd
PVRIG_ECD_SEQUENCE_HERE
```

准备 pair TSV，无表头；若无标签可只写两列：

```text
vhh_001	pvrig_ecd
```

把 `predict_pvrig.py` 顶部改成：

```python
fasta_path = './data/custom_pvrig/input.seqs.fasta'
pair_path = './data/custom_pvrig/input.pair.tsv'
output_path = './output/custom_pvrig/predictions.csv'
```

运行：

```bash
python predict_pvrig.py --model 1 --esm2 8M
python predict_pvrig.py --model 2 --esm2 8M
```

### 1.7 重训练复现

复现 NAI 测试：

```bash
python test_nai.py
```

训练 NAI sequence-only：

```bash
CUDA_VISIBLE_DEVICES=0 python train_Sabdab.py --Model 1 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

训练 site：

```bash
CUDA_VISIBLE_DEVICES=0 python train_Sabdab_Site.py --Model 0 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

训练输出会写到 `output/checkpoint/`。若换 35M/150M/650M，需下载对应 ESM2 encoder 和 checkpoint；本地 ESM2 encoder 已完成，扩展 checkpoint 已启动后台断点续传：

```bash
bash downloads_background/scripts/download_deepnano_checkpoints.sh
bash downloads_background/scripts/download_deepnano_esm2_encoders.sh
```

在这些后台任务完成前，最稳妥的可复现推理版本仍然是 `--esm2 8M`。

### 1.8 复现风险

- `predict.py` 路径硬编码；批量 PVRIG 评估建议复制脚本或自行封装 wrapper。
- 8M checkpoint 和 35M/150M/650M ESM2 encoder 已补齐；更大模型 checkpoint 正在后台续传，未完成前不要把半文件当作可用模型。
- 输出是 binding probability/排序分，不是 Kd，也不是阻断分。
- 训练依赖 PyTorch/transformers 旧版本；不要混用最新版 transformers。

## 2. NABP-BERT

### 2.1 论文与代码来源

- 论文：`NABP-BERT: NANOBODY-antigen binding prediction based on bidirectional encoder representations from transformers (BERT) architecture`, Briefings in Bioinformatics, 2024。DOI：`10.1093/bib/bbae518`。
- 仓库：<https://github.com/FMoonlightS/NABP-BERT>
- 本地路径：`downloaded_models/NABP-BERT`

### 2.2 模型思想

NABP-BERT 把蛋白序列切成 k-mer token，用 BERT 架构学习 protein sequence 表示，然后做 nanobody-antigen binding 二分类。README 描述了两个变体：

- `NABP-PROT-BERT`：用 general protein self-supervised pretrain 的 PROT-BERT 初始化。
- `NABP-PPI-PROT-BERT`：先在 PPI 任务上训练 PPI-PROT-BERT，再迁移到 Nb-Ag。

对 PVRIG 项目的用途：适合作为 sequence-only binding probability 模型；在没有复合物结构之前，可以给 VHH-PVRIG 序列 pair 一个二分类概率。但它仍不识别 PVRIG-PVRL2 阻断表位。

### 2.3 本地文件结构

关键文件：

- `downloaded_models/NABP-BERT/README.md`
- `downloaded_models/NABP-BERT/bert_config_3.json`
- `downloaded_models/NABP-BERT/vocab/vocab_3kmer.txt`
- `downloaded_models/NABP-BERT/run_pretraining.py`
- `downloaded_models/NABP-BERT/run_classifier_fatma.py`
- `downloaded_models/NABP-BERT/create_data.sh`
- `downloaded_models/NABP-BERT/pre_train.sh`
- `downloaded_models/NABP-BERT/run_fine_tune.sh`
- `downloaded_models/NABP-BERT/run_test.sh`
- `downloaded_models/NABP-BERT/data/Nb_Ag_data/`：仓库自带 Nb-Ag CSV 与距离矩阵。

README 指向模型下载：<https://drive.google.com/file/d/1Sr3VMZ96z6duEvAaS6Fb4XtNBqaFX219/view?usp=sharing>。本地已用 `gdown --continue` 下载完成该 Google Drive 大模型包：`downloaded_models/NABP-BERT/_downloads/google_drive/NABP-BERT-models.zip`。

### 2.4 环境复现

`requirments.txt` 是说明表，不是标准 pip requirements。推荐单独 conda 环境，尽量按旧版本：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NABP-BERT
conda create -n nabpbert python=3.7.6 -y
conda activate nabpbert
pip install numpy==1.17.4 six==1.13.0 scikit-learn==0.22 scipy==1.4.1 h5py==2.9.0 keras==2.2.4
pip install tensorflow==1.15.0
```

README 同时列 `tensorflow==1.15.0` 和 `tensorflow-gpu==2.1.0`，这在真实环境里容易冲突。优先固定 TensorFlow 1.15；若要 GPU，建议按 CUDA 10.0/10.1 与 TF 1.15 的兼容矩阵另建环境。

### 2.5 数据预处理复现

README 要求下载：

- PPI data：当前入口建议用 <https://hint.yulab.org/download>，下载 Binary files；README 里的旧 `http://hint.yulab.org/download/` 在核验时不稳定/可能 404。后台脚本使用当前 raw URL，例如 `https://hint.yulab.org/download-raw/2024-06/HomoSapiens_binary_hq.txt`。
- UniProt：<https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/>，下载 `uniprot_sprot.fasta.gz` 和 `uniprot_trembl.fasta.gz`。
- Google Drive 模型/数据包：见上方链接。

本地后台下载脚本：

```bash
bash downloads_background/scripts/download_google_drive_assets.sh
bash downloads_background/scripts/download_nabpbert_training_data.sh
```

预处理顺序：

```bash
# Nb-Ag 数据：README 要求先在 Colab 跑 Nb_Ag_Sequence_Processing.ipynb
python CleanNbAgSeqs.py
python ConstructNbAgTrainValTestDatasets.py

# PPI 数据
python createDatabase.py
python get_unmappedKeysInSwissPortDatabase.py
python ExtractingProteinSeqsFromTrembleDatabase.py
python CleanHINTdatabase.py
python PrepearPPIDatasetSequences.py
python Remove_Homology.py
python ConstructPPINegativeSamples.py

# TSV 与 TFRecord
python createTSV.py
python tsv2record.py

# pretrain 数据
python Prepear_PreTrain_Dataset.py
sh create_data.sh
```

这些脚本会期望 `dataAfterPreProcessing/`、`model/` 等目录存在。若使用作者 Google Drive 包，先解压到项目根目录。

### 2.6 预训练、微调、测试命令

预训练：

```bash
sh pre_train.sh
```

`pre_train.sh` 默认参数：

- input：`./dataAfterPreProcessing/PreTrainDataset/PretrainData_Final.tfrecord`
- output：`./model/3kmer_model/num_hidden_layers_10/num_attention_heads_8/`
- config：`./bert_config_3.json`
- max sequence length：512
- train steps：1,000,000

微调：

```bash
sh run_fine_tune.sh
```

测试：

```bash
sh run_test.sh
```

`run_test.sh` 默认加载：

```text
./model/3kmer_Classifier_model_512/NbAg/NoPreTrain_1_1/model_NbAg_1.ckpt
```

如果使用 Google Drive 下载的不同 checkpoint，需要改 `--init_checkpoint`。

### 2.7 自定义 PVRIG 推理

仓库没有开箱即用的 `predict_pair.py`，所以自定义 PVRIG 一般走三步：

1. 把 VHH-PVRIG pair 做成与 `Nb_Ag_Pairs_Dataset/asTF_Record/` 相同格式的 TFRecord。
2. 修改 `run_test.sh` 的 `--data_root` 指向自定义 TFRecord 目录。
3. 修改 `--init_checkpoint` 指向已训练 NABP-BERT checkpoint。

如果只是项目方案阶段，建议把 NABP-BERT 作为“可复现但工程成本较高”的 sequence-only baseline，不作为第一优先落地工具。

### 2.8 复现风险

- 关键模型在 Google Drive，本地已下载完成；下一步需要解压并把 checkpoint 路径接到作者脚本。
- TensorFlow 1.x + 旧 Keras 环境维护成本高。
- 数据准备链条长，依赖 HINT、UniProt、同源去除和 TFRecord。
- 预测的是结合二分类，不是 Kd，也不是 PVRIG-PVRL2 阻断。

## 3. NABP-LSTM-Att

### 3.1 论文与代码来源

- 论文：`NABP-LSTM-Att: Nanobody-Antigen binding prediction using bidirectional LSTM and soft attention mechanism`, Computational Biology and Chemistry, 2025。DOI：`10.1016/j.compbiolchem.2025.108490`。
- 仓库：<https://github.com/FMoonlightS/NABP-LSTM-Att>
- 本地路径：`downloaded_models/NABP-LSTM-Att`

说明：该仓库题名、README、作者账号和脚本与论文高度一致；PubMed/DOI 论文题名也匹配。可访问证据中未直接看到出版社页面反链仓库，所以正式发表材料中若要写“官方仓库”，建议再核对论文 Code Availability 或联系作者；工程复现层面当前选择合理。

### 3.2 模型思想

NABP-LSTM-Att 是更轻量的 sequence model：

- 输入侧重点不是完整 VHH 简单拼接，而是 VHH CDR token 与抗原 token。
- CDR 与抗原分别 embedding。
- 经过 Conv1D、pooling、BiLSTM。
- soft attention 聚焦关键序列片段。
- 输出 binding probability。

本地 `model.py` 固定参数：

- `MAX_LEN_cdr = 24`
- `MAX_LEN_ag = 2371`
- `cdr_kmer = 3`
- `ag_kmer = 1`
- `Embedding dim = 100`
- `BiLSTM hidden size = 50`

对 PVRIG 项目的用途：非常适合作为可改造 baseline。相比 BERT 更轻，便于改成 CDR-aware VHH-PVRIG classifier，并进一步把 CDR3 权重、PVRIG/PVRL2 界面 mask 加进去。

### 3.3 本地文件结构

关键文件：

- `downloaded_models/NABP-LSTM-Att/model.py`：模型结构。
- `downloaded_models/NABP-LSTM-Att/train.py`：训练入口。
- `downloaded_models/NABP-LSTM-Att/test.py`：测试入口。
- `downloaded_models/NABP-LSTM-Att/createTSV.py`：生成 k-mer TSV。
- `downloaded_models/NABP-LSTM-Att/embedding.py`：生成 feature pickle。
- `downloaded_models/NABP-LSTM-Att/vocab/`：1/2/3-mer vocab。
- `downloaded_models/NABP-LSTM-Att/data/clusters.csv`：聚类文件。
- `downloaded_models/NABP-LSTM-Att/Supplementary_Materials.pdf`

README 指向预处理数据和模型权重：<https://drive.google.com/drive/folders/1P8Ps9gRh_IAuAof-EfYLOeOh4LdsuaVU?usp=sharing>。本地已用 `gdown --folder --continue` 下载完成该 Google Drive folder，主要文件位于 `downloaded_models/NABP-LSTM-Att/_downloads/google_drive/data.rar` 与 `downloaded_models/NABP-LSTM-Att/_downloads/google_drive/model.rar`。

### 3.4 环境复现

同样是旧 TensorFlow/Keras 栈：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NABP-LSTM-Att
conda create -n nabplstm python=3.7.6 -y
conda activate nabplstm
pip install numpy==1.17.4 scipy==1.4.1 scikit-learn==0.22 h5py==2.9.0 keras==2.2.4 tensorflow==1.15.0 six==1.13.0
```

如果要 GPU，需要按 TF 1.15 的 CUDA 兼容环境单独配置。

### 3.5 从原始数据复现预处理

README 顺序如下：

```bash
python getDataFromSAbDab-nano.py
python read_CSVs.py

# 需要外部安装 cd-hit
cd-hit -i nanobody_seqs.fasta -o nanobody_seqs_98.fasta -c 0.98 -n 5

python prepareAntigenSeqs.py
cd-hit -i antigen_seqs_after_nanobody_identiy98.fasta -o antigen_seqs_after_nanobody_identiy98_90.fasta -c 0.90 -n 5

python create_intra_inter_group_binding.py
# README 要求把 antigen_seqs_after_nanobody_identiy98.fasta 上传 Clustal Omega 构树，再保存 clusters.csv
python phylogenetic_tree_clusters.py
python create_train_test_datasets.py
python createTSV.py
python embedding.py
```

注意 README 中 `identity` / `identiy` 拼写不一致，实际运行时要按脚本里的文件名检查。

如果只想复现论文测试，优先下载 Google Drive 中的 `data/features/cdr_kmer3_ag_kmer1/` 和 `model/cdr_kmer3_ag_kmer1/Model99.h5`，避免从 SAbDab-nano 和 Clustal Omega 全流程重做。本地后台命令：

```bash
bash downloads_background/scripts/download_google_drive_assets.sh
```

### 3.6 训练与测试

训练：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NABP-LSTM-Att
conda activate nabplstm
python train.py
```

测试：

```bash
python test.py
```

脚本期望输入：

```text
data/features/cdr_kmer3_ag_kmer1/cdr_features_tr.pickle
data/features/cdr_kmer3_ag_kmer1/ag_features_tr.pickle
data/features/cdr_kmer3_ag_kmer1/cdr_features_val.pickle
data/features/cdr_kmer3_ag_kmer1/ag_features_val.pickle
data/features/cdr_kmer3_ag_kmer1/cdr_features_te.pickle
data/features/cdr_kmer3_ag_kmer1/ag_features_te.pickle
model/cdr_kmer3_ag_kmer1/Model99.h5
```

脚本内写死：

```python
os.environ["CUDA_VISIBLE_DEVICES"]="4"  # train.py
os.environ["CUDA_VISIBLE_DEVICES"]="3"  # test.py
```

单卡或 CPU 复现时需要改掉这两行。

### 3.7 自定义 PVRIG 改造建议

建议不要原样当最终打分器，而是作为轻量可控 baseline：

- 输入 VHH 时只抽 CDR1/CDR2/CDR3，尤其保留 CDR3 的单独 channel。
- 抗原输入用 PVRIG ECD 全序列；另加一个 PVRIG-PVRL2 界面 mask channel。
- 输出两个头：`binding_probability` 和 `interface_overlap_probability`。
- 训练负样本要区分“非结合”和“结合但非阻断”，否则会把非阻断 binder 排到前面。

### 3.8 复现风险

- Google Drive 权重/预处理特征包已下载完成；下一步需要解压并按脚本期望路径放置。
- 旧 TF/Keras 依赖脆弱。
- 预处理依赖 SAbDab-nano、CD-HIT、Clustal Omega 网页服务。
- 默认脚本硬编码 GPU id。
- 输出是 binding classifier，不是阻断模型。

## 4. Sequence-Based Nanobody-Antigen Binding Prediction

### 4.1 论文与代码来源

- 论文：`Sequence-Based Nanobody-Antigen Binding Prediction`, ISBRA 2023 / Lecture Notes in Computer Science。DOI：`10.1007/978-981-99-7074-2_18`。
- arXiv：<https://arxiv.org/abs/2308.01920>
- 官方仓库：<https://github.com/sarwanpasha/Nanobody_Antigen>
- 本地路径：`downloaded_models/Sequence-Based-NABP`
- 本地论文 PDF：`downloaded_models/Sequence-Based-NABP-paper.pdf`
- 本地辅助 CLI：`repro_helpers/sequence_based_gapped_kmer.py`

来源核验备注：arXiv/Springer 论文写明 code and preprocessed datasets online，并给出 `sarwanpasha/Nanobody_Antigen`；该方法不是发布 checkpoint 的深度模型，因此不要期待 `.pt/.h5/.ckpt` 权重。

### 4.2 方法思想

这是传统 ML baseline，主要流程：

1. 从 sdAb-DB/UniProt 整理 nanobody-antigen 正样本。
2. 用抗原距离矩阵构造非结合样本：如果两个已知 binding pair 的抗原相距足够远，则交叉组合可作为 non-binding candidate。
3. 用 gapped k-mer spectrum 表示 VHH 和抗原序列。
4. 拼接 VHH embedding 与抗原 embedding。
5. 用 RF/SVM/LR/DT/NB/KNN/MLP 等分类器做 binding/non-binding。
6. 论文报告 Random Forest 总体表现较好，accuracy 接近 90%。

论文中 gapped k-mer 例子：对 `ACD` 生成 `ACD`、`-CD`、`A-D`、`AC-`。这能保留局部 motif，同时容忍一个位置 gap。

对 PVRIG 项目的用途：非常适合写成 baseline 与消融对照。例如：`gapped k-mer + RandomForest`，用于证明深度模型/结构模型确实有增益。

### 4.3 官方仓库结构

- `downloaded_models/Sequence-Based-NABP/README.md`：只有项目名，缺少运行说明。
- `downloaded_models/Sequence-Based-NABP/Code/Antigene_Antibody_Data_Preprocessing_kmers.ipynb`
- `downloaded_models/Sequence-Based-NABP/Code/Antigene_Antibody_Data_Preprocessing_minimizers.ipynb`
- `downloaded_models/Sequence-Based-NABP/Code/Antigene_Antibody_Data_Preprocessing_PWM.ipynb`
- `downloaded_models/Sequence-Based-NABP/Code/t-SNE Plots.ipynb`
- `downloaded_models/Sequence-Based-NABP/Dataset/Ag-Nb Binding Data with Sequences - Sheet1.csv`
- `downloaded_models/Sequence-Based-NABP/Dataset/Antibodies_Pairwise_Distance_Matrix.csv`
- `downloaded_models/Sequence-Based-NABP/Dataset/Antigene_Features.csv`
- `downloaded_models/Sequence-Based-NABP/Dataset/Nanobody_Features.csv`

官方 notebook 硬编码了 Windows 绝对路径，例如 `E:/RA/Antigene_Antibody/Dataset/New/...`，所以不能一键在 Linux 复现。

### 4.4 官方 notebook 复现方式

```bash
cd /mnt/d/work/抗体/code/downloaded_models/Sequence-Based-NABP
python -m venv .venv
source .venv/bin/activate
pip install numpy pandas scipy scikit-learn matplotlib seaborn biopython openpyxl notebook
jupyter notebook Code/Antigene_Antibody_Data_Preprocessing_kmers.ipynb
```

然后手工把 notebook 里的 `E:/RA/Antigene_Antibody/Dataset/New/` 替换为本地相对路径：

```text
/mnt/d/work/抗体/code/downloaded_models/Sequence-Based-NABP/Dataset/
```

如果想批处理：

```bash
jupyter nbconvert --execute --to notebook --inplace Code/Antigene_Antibody_Data_Preprocessing_kmers.ipynb
```

但必须先改路径，否则会找不到数据。

### 4.5 本地 CLI helper 复现方式

我额外写了一个不修改第三方仓库的可运行 helper：`repro_helpers/sequence_based_gapped_kmer.py`。它直接读取官方 CSV，实现 gapped k-mer + 分类器，输出 `metrics.json`。

安装依赖：

```bash
cd /mnt/d/work/抗体/code
python -m venv .venv-seqbase
source .venv-seqbase/bin/activate
pip install -r repro_helpers/requirements-sequence-baseline.txt
```

运行 RandomForest baseline：

```bash
python repro_helpers/sequence_based_gapped_kmer.py \
  --classifier rf \
  --k 3 \
  --negative-threshold 0.85 \
  --negative-ratio 1.0 \
  --splits 5 \
  --out-dir repro_outputs/sequence_based_gapped_kmer_rf
```

输出：

```text
repro_outputs/sequence_based_gapped_kmer_rf/metrics.json
```

可选分类器：`rf`、`svm`、`lr`、`dt`、`nb`、`knn`、`mlp`。

注意：helper 是工程化复现脚本，不是论文作者原 notebook 原样执行；它保留 gapped k-mer、距离阈值负样本、5 次随机划分等核心思想，用于可重复 baseline。

### 4.6 自定义 PVRIG baseline

要把它用于 PVRIG：

1. 准备训练 CSV，至少包含：`Nanobody Sequence`、`Antigen Sequence`、label。
2. PVRIG 只有一个抗原时，传统“抗原距离矩阵构造负样本”不够，需要额外加入非 PVRIG 或不结合 PVRIG 的 VHH 负样本。
3. 推荐把 PVRIG-PVRL2 界面附近 motif/position mask 作为额外手工特征，形成：

```text
[VHH gapped k-mer] + [PVRIG gapped k-mer] + [CDR3 length/charge] + [interface-overlap prior]
```

### 4.7 复现风险

- 作者 README 几乎为空。
- 官方代码是 notebook，路径硬编码，未封装 CLI。
- 没有保存好的模型权重；必须重训。
- 论文指标受负样本构造和随机划分影响很大。
- 适合作 baseline，不适合作最终排序模型。

## 5. NanoBinder

### 5.1 论文与代码来源

- 论文：`NanoBinder: a machine learning assisted nanobody binding prediction tool using Rosetta energy scores`, Journal of Cheminformatics, 2025。DOI：`10.1186/s13321-025-01040-1`。
- PMC：<https://pmc.ncbi.nlm.nih.gov/articles/PMC12172308/>
- 仓库：<https://github.com/pallucs/NanoBinder>
- Web server：<https://nsclbio.jbnu.ac.kr/tools/webserver/>
- 本地路径：`downloaded_models/NanoBinder`

来源核验备注：当前能核到的匹配论文标题/方法的公开代码是 `pallucs/NanoBinder`。所谓 `DukeNash/NanoBinder` 在 2026-07-06 通过 GitHub API 核验为 404，未找到可引用的公开仓库证据，不应作为该工作的来源。

### 5.2 模型思想

NanoBinder 是结构打分模型，不是 sequence-only 模型。核心流程：

1. 从 SAbDab 收集实验验证的 nanobody-antigen 复合物。
2. 用结构叠合/交换方式构造非结合复合物。
3. 对每个复合物用 RosettaAntibody/Rosetta scoring 生成能量特征。
4. 去掉高度相关特征。
5. 用 Random Forest + SMOTETomek 做 binding/non-binding 分类。

论文最终使用 26 个 Rosetta energy features，包括：

```text
complex_normalized, dG_cross, dG_cross/dSASAx100, dSASA_hphobic,
dSASA_int, dSASA_polar, delta_unsatHbonds, dslf_fa13, fa_atr,
hbond_E_fraction, hbond_bb_sc, hbond_lr_bb, hbond_sc, hbond_sr_bb,
hbonds_int, nres_int, omega, per_residue_energy_int, pro_close,
rama_prepro, ref, side1_normalized, side1_score, side2_normalized,
side2_score, yhh_planarity
```

对 PVRIG 项目的用途：非常有用。比赛最终不只是序列结合，还需要实验结合与阻断；我们一定会做 VHH-PVRIG 复合物建模/docking。NanoBinder 的思路可以改造成结构评分模块：对每个 pose 计算 Rosetta interface energy、buried SASA、shape complementarity、H-bond、clash 等，再加 PVRIG-PVRL2 阻断评分。

### 5.3 本地文件结构

仓库很小：

- `downloaded_models/NanoBinder/README.md`
- `downloaded_models/NanoBinder/Training.py`
- `downloaded_models/NanoBinder/Hyper_parameter_tunning.py`
- `downloaded_models/NanoBinder/NanoBinder-workflow.png`
- `downloaded_models/NanoBinder/LICENSE`

当前仓库不包含 `data/Dataset/dataset.csv`，但 `Training.py` 写死读取：

```python
df = pd.read_csv('../data/Dataset/dataset.csv')
```

因此本地只能复现训练代码结构；要复现实验指标，必须按论文方法重建 `dataset.csv` 或向作者/网页服务获取数据。

同样未发现官方发布的 `nbsrf.joblib`、`RF_model_best.pkl` 或等价 ready-to-use 权重。`Hyper_parameter_tunning.py` 会在你本地准备好 `dataset.csv` 并训练后输出 `../results/RF_model_best.pkl`；这不是作者公开权重包。

### 5.4 环境复现

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NanoBinder
conda create -n nanobinder python=3.10 -y
conda activate nanobinder
pip install pandas numpy matplotlib scikit-learn imbalanced-learn optuna shap
```

若要重建特征，还需要 Rosetta/RosettaAntibody、PyMOL、SAbDab 下载脚本和 PDB 预处理脚本；这些不在仓库中。

### 5.5 训练脚本复现

假设你已经准备好：

```text
/mnt/d/work/抗体/code/downloaded_models/data/Dataset/dataset.csv
/mnt/d/work/抗体/code/downloaded_models/results/
```

注意脚本从 `downloaded_models/NanoBinder` 运行时，`../data/Dataset/dataset.csv` 实际指向：

```text
/mnt/d/work/抗体/code/downloaded_models/data/Dataset/dataset.csv
```

运行：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NanoBinder
mkdir -p ../results
python Training.py
```

输出：

```text
../results/roc-plot.png
../results/prc-plot.png
```

超参搜索：

```bash
python Hyper_parameter_tunning.py
```

输出：

```text
../results/RF_model_best.pkl
../results/Optuna_hyperparameter.csv
```

### 5.6 如何重建 `dataset.csv`

论文方法给出的重建路线：

1. 从 SAbDab 获取 1396 个实验验证 nanobody-protein antigen 复合物。
2. 去掉水、非必要 ligand、constant domain。
3. 重命名并重排 chain：nanobody heavy chain 为 `H`，antigen chain 为 `A`。
4. 构造非结合复合物：随机选两个 binding complex，在 PyMOL 中对 heavy chain 结构叠合；若 RMSD < 2 A，交叉组合 nanobody 与 antigen，得到 non-binding complex。
5. Rosetta relax 每个 complex，生成一个 relaxed structure。
6. 用 Rosetta scoring 生成 40 个能量项。
7. 删除 `total_score`、`packstat`、`sc_value`，再按相关性阈值 0.95 去冗余，得到 26 个特征。
8. 写成 `dataset.csv`，至少包含 26 个特征和 `label` 列。

最小 CSV 列：

```text
complex_normalized,dG_cross,dG_cross/dSASAx100,dSASA_hphobic,dSASA_int,dSASA_polar,delta_unsatHbonds,dslf_fa13,fa_atr,hbond_E_fraction,hbond_bb_sc,hbond_lr_bb,hbond_sc,hbond_sr_bb,hbonds_int,nres_int,omega,per_residue_energy_int,pro_close,rama_prepro,ref,side1_normalized,side1_score,side2_normalized,side2_score,yhh_planarity,label
```

### 5.7 PVRIG 阻断改造

对每个 VHH-PVRIG docking pose：

1. 生成 NanoBinder 26 个 Rosetta 特征。
2. 加入 PVRIG-PVRL2 阻断特征：
   - VHH 接触的 PVRIG residue 与 PVRL2 interface residue 的 overlap。
   - VHH CDR 是否覆盖 PVRIG-PVRL2 hot spot。
   - VHH 是否与 PVRL2 同时发生空间冲突。
   - buried SASA、shape complementarity、interface H-bond、clash。
3. 训练两个分数：
   - `binding_pose_quality`
   - `blocking_likelihood`
4. 最终排序不要只用 binding probability；应使用：

```text
final_score = sequence_binding_score + structure_pose_score + interface_blocking_score - developability_penalty
```

### 5.8 复现风险

- 仓库不含 `dataset.csv`，也未公开 ready-to-use RF 权重/`nbsrf.joblib`，不能直接复现论文 MCC。
- 不要把 `DukeNash/NanoBinder` 当作可信替代来源；当前公开核验为 404。
- 重建数据需要 Rosetta、PyMOL、SAbDab、PDB 处理，工程量明显高于 sequence-only 模型。
- NanoBinder 判断 pose 是否像 binder，不等于判断是否阻断 PVRIG-PVRL2。

## 6. NanoBind

### 6.1 论文与代码来源

- 论文：`NanoBind: Mechanism-Driven Deep Learning of Nanobody-Antigen Molecular Recognition`, Research, 2026。DOI：`10.34133/research.1327`。
- 仓库：<https://github.com/zhaosq17/NanoBind>
- 本地路径：`downloaded_models/NanoBind`

### 6.2 模型思想

NanoBind 是 5 个子模型组成的统一框架：

- `NanoBind-seq`：快速 binding prediction。
- `NanoBind-site`：抗原 interface residue prediction。
- `NanoBind-pro`：利用 site 模型增强 binding prediction。
- `NanoBind-pair`：比较两个 Nb-Ag complex 的相对亲和力强弱。
- `NanoBind-affi`：基于 pair model 和 reference set 预测 affinity range / Kd 区间。

它使用 ESM2-8M encoder，并结合 self-attention / 1D convolution 学习 CDR/抗原模式。对 PVRIG 项目来说，它比普通二分类更接近需求，因为它显式涉及 interface residue 和 affinity range。但它仍不是专门的 PVRIG-PVRL2 阻断模型。

### 6.3 本地文件结构

关键文件：

- `downloaded_models/NanoBind/README.md`
- `downloaded_models/NanoBind/NanoBind_env.yml`
- `downloaded_models/NanoBind/predict_seq.py`
- `downloaded_models/NanoBind/predict_site.py`
- `downloaded_models/NanoBind/predict_pro.py`
- `downloaded_models/NanoBind/predict_pair.py`
- `downloaded_models/NanoBind/predict_affi.py`
- `downloaded_models/NanoBind/train_nai.py`
- `downloaded_models/NanoBind/train_site.py`
- `downloaded_models/NanoBind/train_pair.py`
- `downloaded_models/NanoBind/models/esm2_t6_8M_UR50D/`
- `downloaded_models/NanoBind/data/example/`
- `downloaded_models/NanoBind/data/sdab/`
- `downloaded_models/NanoBind/data/Sabdab/`
- `downloaded_models/NanoBind/data/affinity/`

Checkpoint 状态：

```text
OK   output/checkpoint/NanoBind_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model
OK   output/checkpoint/NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model
OK   output/checkpoint/NanoBind_pro(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model
OK   output/checkpoint/NanoBind_pair_0.model
OK   output/checkpoint/NanoBind_pair_50.model
OK   output/checkpoint/NanoBind_pair_100.model
```

`predict_pro.py` 会在模型构造时加载 `NanoBind_site`；当前 site checkpoint 已补齐，因此 `predict_seq.py`、`predict_site.py`、`predict_pro.py`、`predict_pair.py`、`predict_affi.py` 在依赖环境正确时都有权重条件。

### 6.4 环境复现

官方环境文件：`downloaded_models/NanoBind/NanoBind_env.yml`。

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NanoBind
conda env create -f NanoBind_env.yml
conda activate NanoBind
```

如果 `conda env create` 在新机器上解 CUDA wheel 慢，可手动安装：

```bash
conda create -n nanobind python=3.9.13 -y
conda activate nanobind
pip install torch==1.13.1 torchvision==0.14.1 torchaudio==0.13.1 --extra-index-url https://download.pytorch.org/whl/cu116
pip install biopython==1.78 pandas==1.3.5 scikit-learn==1.0.2 transformers==4.27.4 tqdm numpy==1.24.4
```

### 6.5 Git LFS 权重状态与补齐方法

本地最初下载后，`NanoBind_site...model` 是 134 bytes Git LFS 指针；现在已经通过 Git LFS batch API + `curl -C -` 续传补齐为真实模型文件，大小为 `103432362` bytes。原始指针保留在：

```text
downloaded_models/NanoBind/output/checkpoint/NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model.lfs-pointer.txt
```

若以后在新机器上重新补齐，安装了 `git-lfs` 时最简单：

```bash
cd /mnt/d/work/抗体/code/downloaded_models
rm -rf NanoBind_lfs_clone
git clone https://github.com/zhaosq17/NanoBind.git NanoBind_lfs_clone
cd NanoBind_lfs_clone
git lfs install
git lfs pull
cp "output/checkpoint/NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model" \
  "/mnt/d/work/抗体/code/downloaded_models/NanoBind/output/checkpoint/"
```

本机已经把同样的逻辑固化为后台脚本：

```bash
bash downloads_background/scripts/download_nanobind_site_lfs.sh
```

该脚本会在模型完整时直接退出；如果下载中断，会自动刷新 Git LFS 签名 URL 并从 `.part` 文件断点续传。

### 6.6 快速推理

进入环境：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NanoBind
conda activate NanoBind
mkdir -p output/prediction_results
```

binding prediction：

```bash
python predict_seq.py --nb data/example/nb1.fasta --ag data/example/ag1.fasta \
  --output output/prediction_results/predictions_NanoBind_seq.csv
```

interface prediction：site checkpoint 已补齐，需先按环境文件安装依赖。

```bash
python predict_site.py --nb data/example/nb1.fasta --ag data/example/ag1.fasta \
  --output output/prediction_results/predictions_NanoBind_site.csv
```

enhanced binding prediction：依赖 site checkpoint；当前权重已补齐。

```bash
python predict_pro.py --nb data/example/nb1.fasta --ag data/example/ag1.fasta \
  --output output/prediction_results/predictions_NanoBind_pro.csv
```

relative affinity pair comparison：

```bash
python predict_pair.py \
  --nb1 data/example/nb1.fasta --ag1 data/example/ag1.fasta \
  --nb2 data/example/nb2.fasta --ag2 data/example/ag2.fasta \
  --output output/prediction_results/predictions_NanoBind_pair.csv
```

Kd/affinity range：

```bash
python predict_affi.py --nb data/example/nb1.fasta --ag data/example/ag1.fasta \
  --output output/prediction_results/predictions_NanoBind_affi.csv
```

### 6.7 论文结果复现

README 给出的复现命令：

```bash
python test_seq.py
python test_site.py
python test_pro.py
python test_pair.py
```

当前状态下：

- `test_seq.py`：具备权重条件。
- `test_site.py`：具备权重条件。
- `test_pro.py`：具备权重条件。
- `test_pair.py`：具备权重条件。

仍未在当前全局环境直接执行测试，原因是需要按 `NanoBind_env.yml` 创建旧版 PyTorch/transformers 环境，避免污染系统 Python。

### 6.8 自定义 PVRIG 输入

NanoBind 的 predict 脚本已经支持 FASTA 参数。准备：

```bash
mkdir -p data/custom_pvrig
cat > data/custom_pvrig/vhh.fasta <<'EOF'
>vhh_001
EVQLVESGGGLVQPGGSLRLSCAAS...
EOF
cat > data/custom_pvrig/pvrig.fasta <<'EOF'
>pvrig_ecd
PVRIG_ECD_SEQUENCE_HERE
EOF
```

先跑 sequence binding：

```bash
python predict_seq.py --nb data/custom_pvrig/vhh.fasta --ag data/custom_pvrig/pvrig.fasta \
  --output output/prediction_results/pvrig_NanoBind_seq.csv
```

再跑界面、增强结合和亲和力区间：

```bash
python predict_site.py --nb data/custom_pvrig/vhh.fasta --ag data/custom_pvrig/pvrig.fasta \
  --output output/prediction_results/pvrig_NanoBind_site.csv
python predict_pro.py --nb data/custom_pvrig/vhh.fasta --ag data/custom_pvrig/pvrig.fasta \
  --output output/prediction_results/pvrig_NanoBind_pro.csv
python predict_affi.py --nb data/custom_pvrig/vhh.fasta --ag data/custom_pvrig/pvrig.fasta \
  --output output/prediction_results/pvrig_NanoBind_affi.csv
```

### 6.9 复现风险

- 当前 site checkpoint 已补齐；site/pro 相关命令的主要剩余风险是环境依赖，而不是权重缺失。
- `predict_seq.py` 阈值为 0.3，`predict_pro.py` 阈值为 0.5，`predict_pair.py` 阈值为 0.4；这些阈值是作者脚本经验值，不应直接当作 PVRIG 项目最终阈值。
- `predict_affi.py` 的 Kd 区间来自 reference set 相对比较，不等于精确 Kd 回归。
- NanoBind 仍不直接判断 PVRIG-PVRL2 阻断，需要叠加表位 overlap/结构阻断评分。

## 7. 面向 PVRIG 阻断 VHH 的推荐使用顺序

建议不要把任一模型单独作为最终排序依据。推荐流水线：

1. **快速序列初筛**：DeepNano `--model 1/2` + NanoBind-seq + NABP-LSTM-Att/NABP-BERT 可选。
2. **传统 baseline 对照**：Sequence-Based gapped k-mer + RF，记录可解释、轻量的 sequence-only baseline。
3. **结构建模与 docking**：对高分 VHH 生成 VHH-PVRIG complex poses。
4. **结构质量打分**：借鉴 NanoBinder，计算 Rosetta/interface features。
5. **阻断特异评分**：计算 VHH 接触 PVRIG residue 与 PVRIG-PVRL2 interface 的 overlap、空间冲突和 hot spot 覆盖。
6. **综合排序**：binding score + pose score + blocking score + developability penalty。

最小可执行打分表建议列：

```text
vhh_id
pvrig_sequence_binding_deepnano
pvrig_sequence_binding_nanobind_seq
sequence_baseline_rf_probability
pose_rosetta_interface_energy
pose_buried_sasa
pose_hbonds
pose_clash_penalty
pvrig_pvrl2_interface_overlap
blocking_likelihood
final_rank_score
```

## 8. 验证记录

本地已验证：

- `downloaded_models/DeepNano`、`DeepNano-data`、`NABP-BERT`、`NABP-LSTM-Att`、`Sequence-Based-NABP`、`NanoBinder`、`NanoBind` 均存在。
- DeepNano 8M 四个 checkpoint 已按代码期望名称保存。
- NanoBind checkpoint 中 `seq/site/pro/pair` 均是真实二进制模型；`site` 模型大小为 `103432362` bytes，原始 134 bytes LFS 指针已另存为 `.lfs-pointer.txt`。
- 后台断点下载脚本已启动：`deepnano_checkpoints`、`nabpbert_training_data` 仍在续传；`deepnano_esm2` 和 `nanobind_site_lfs` 已完成。
- `repro_helpers/sequence_based_gapped_kmer.py` 已通过 `python3 -m py_compile` 语法检查。

未执行完整模型测试的原因：

- 当前系统未预装各模型旧版 Python 依赖；直接在全局环境运行会污染环境。
- NABP-BERT/NABP-LSTM-Att 的 Google Drive 权重/数据包已下载完成；尚未在当前全局环境解压和执行测试。
- NanoBinder 缺论文训练数据 `dataset.csv`。

## 9. 外部来源链接

- DeepNano paper DOI：<https://doi.org/10.1038/s42256-024-00940-5>
- DeepNano GitHub：<https://github.com/ddd9898/DeepNano>
- DeepNano-data GitHub：<https://github.com/ddd9898/DeepNano-data>
- NABP-BERT paper DOI：<https://doi.org/10.1093/bib/bbae518>
- NABP-BERT GitHub：<https://github.com/FMoonlightS/NABP-BERT>
- NABP-LSTM-Att paper DOI：<https://doi.org/10.1016/j.compbiolchem.2025.108490>
- NABP-LSTM-Att GitHub：<https://github.com/FMoonlightS/NABP-LSTM-Att>
- Sequence-Based paper DOI：<https://doi.org/10.1007/978-981-99-7074-2_18>
- Sequence-Based arXiv：<https://arxiv.org/abs/2308.01920>
- Sequence-Based GitHub：<https://github.com/sarwanpasha/Nanobody_Antigen>
- NanoBinder paper DOI：<https://doi.org/10.1186/s13321-025-01040-1>
- NanoBinder PMC：<https://pmc.ncbi.nlm.nih.gov/articles/PMC12172308/>
- NanoBinder GitHub：<https://github.com/pallucs/NanoBinder>
- NanoBind paper DOI：<https://doi.org/10.34133/research.1327>
- NanoBind GitHub：<https://github.com/zhaosq17/NanoBind>
