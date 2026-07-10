# NanoBind 详细复现、数据集与 PVRIG 多任务迁移说明

生成日期：2026-07-10  
工作目录：`/mnt/d/work/抗体/code`  
本地模型目录：`downloaded_models/NanoBind`  
论文：Zhao 等，*NanoBind: Mechanism-Driven Deep Learning of Nanobody-Antigen Molecular Recognition*，Research，2026，DOI：`10.34133/research.1327`  
论文公开全文：`https://pmc.ncbi.nlm.nih.gov/articles/PMC13287458/`  
代码仓库：`https://github.com/zhaosq17/NanoBind`

本文档记录第六个工作 NanoBind。重点说明它的五个子任务、共享编码器、训练数据构造、亲和力比较数据、输入输出、权重状态、复现命令，以及如何将它改造成 PVRIG-PVRL2 阻断型纳米抗体的多任务模型。

## 1. 一句话定位

NanoBind 是一个从纯序列出发、分层预测纳米抗体-抗原分子识别的统一框架：

```text
Tier 1：是否结合
Tier 2：抗原上哪些残基参与界面
Tier 3：相对亲和力和 Kd 区间
```

它包含五个逻辑子模型：

```text
NanoBind-seq   -> VHH-antigen binding probability
NanoBind-site  -> antigen residue-level interface probability
NanoBind-pro   -> site-prompt-enhanced binding probability
NanoBind-pair  -> 两个 VHH-antigen pair 的相对 Kd 顺序
NanoBind-affi  -> 借助 49 个参考锚点推断 Kd 区间
```

它是六个工作中理念最接近我们最终目标的一个，因为它不只做 binder/non-binder，还显式建模 interface 和 affinity。不过，它仍然没有 `PVRIG-PVRL2 blocking` 标签，所以不能直接把 binding/interface 输出当成 blocker 结论。

## 2. 本地资源状态

本地目录：

```text
downloaded_models/NanoBind
```

主要资源：

```text
README.md
NanoBind_env.yml

models/NanoBind_seq.py
models/NanoBind_site.py
models/NanoBind_pro.py
models/NanoBind_pair.py
models/esm2_t6_8M_UR50D/

train_nai.py
train_site.py
train_pair.py

predict_seq.py
predict_site.py
predict_pro.py
predict_pair.py
predict_affi.py

test_seq.py
test_site.py
test_pro.py
test_pair.py

data/Sabdab/
data/sdab/
data/affinity/
data/example/

output/checkpoint/
output/prediction_results/
output/test_results/
```

论文资料已经以可恢复下载方式补充到：

```text
downloaded_models/NanoBind/_downloads/PMC13287458_fulltext.xml
downloaded_models/NanoBind/_downloads/PMC13287458_supplementary.zip
downloaded_models/NanoBind/_downloads/research.1327.f1.pdf
downloaded_models/NanoBind/_downloads/research.1327.f1.txt
```

其中：

```text
PMC13287458_fulltext.xml    论文全文结构化 XML
research.1327.f1.pdf        Supplementary Tables S1-S18、Figures S1-S10、Notes S1-S9
research.1327.f1.txt        本地从 supplement PDF 提取的可搜索文本
```

## 3. 权重状态

本地已有 ESM-2 编码器：

```text
models/esm2_t6_8M_UR50D/model.safetensors   31,384,292 bytes
models/esm2_t6_8M_UR50D/pytorch_model.bin   31,406,877 bytes
models/esm2_t6_8M_UR50D/tf_model.h5         30,256,864 bytes
```

本地已有六个有效 NanoBind checkpoint：

```text
NanoBind_seq(...).model    38,904,282 bytes
NanoBind_site(...).model  103,432,362 bytes
NanoBind_pro(...).model   144,160,852 bytes
NanoBind_pair_0.model      42,011,422 bytes
NanoBind_pair_50.model     42,011,422 bytes
NanoBind_pair_100.model    42,011,686 bytes
```

这些文件都是真实 PyTorch ZIP-format checkpoint，不是 Git LFS pointer。

三套 `NanoBind_pair` 权重分别对应：

```text
pair_100：测试 complex 与训练 complex 100% overlap
pair_50：测试 complex 中约 50% 在训练中出现
pair_0：测试 complex 完全未在训练中出现
```

注意：没有独立的 `NanoBind_affi.model`。NanoBind-affi 实际复用 `NanoBind_pair_100.model`，再和 49 个参考复合物逐一比较。

## 4. 五个子模型不是五个互相独立的网络

NanoBind 的层级关系如下：

```text
ESM-2 + NanoBind Encoder
  ├─ NanoBind-seq：直接预测是否结合
  ├─ NanoBind-site：预测 antigen interface residues
  ├─ NanoBind-pro：调用冻结的 NanoBind-site，把 site 结果作为 prompt，再预测是否结合
  └─ NanoBind-pair：比较两个 complex 的相对 Kd
       └─ NanoBind-affi：用 pair 模型对 49 个 Kd anchor 比较，输出亲和力区间
```

所以：

```text
NanoBind-pro 依赖 NanoBind-site checkpoint
NanoBind-affi 依赖 NanoBind-pair checkpoint + reference_set.csv
```

## 5. 共享 NanoBind Encoder

所有子模型的核心是同一个 sequence encoder。

### 5.1 ESM-2 residue embedding

默认使用：

```text
esm2_t6_8M_UR50D
hidden size = 320
max sequence length = 800
```

输入 VHH 或 antigen 序列后，ESM-2 为每个 residue 生成 320 维 embedding。

训练时有三种 finetune 设置：

```text
finetune = 0：冻结全部 ESM-2
finetune = 1：只训练 ESM-2 最后一层
finetune = 2：训练全部 ESM-2
```

论文和默认训练命令使用 `finetune=1`，即只微调最后一个 encoder layer，其余层冻结，以降低过拟合和计算量。

### 5.2 Global Adaptive Module

全局分支使用：

```text
self-attention + RoPE
```

目的：捕捉 CDR1/CDR2/CDR3 之间的长程协同以及相对位置关系。

RoPE 比绝对位置编码更适合描述：

```text
两个 motif 相隔多远
不同 CDR 之间的相对位置
同一功能模式在长度变化后的迁移
```

### 5.3 Local Adaptive Module

局部分支使用：

```text
Conv1d
kernel size = 5
```

目的：提取局部 CDR motif、短程氨基酸组合和相邻残基模式。

论文消融实验显示 kernel size 5 最好；去掉局部分支会明显降低 binding prediction 性能。

### 5.4 特征融合

全局和局部 residue features 拼接：

```text
320 + 320 = 640 dimensions per residue
```

再做平均池化，得到整条蛋白的 NanoBind Encoder Feature：

```text
NEF = 640-dimensional protein-level feature
```

这一设计的核心思想是：

```text
ESM-2 提供通用蛋白知识
Global module 捕捉 CDR 长程协同
Local module 捕捉 CDR 局部 motif
```

## 6. NanoBind-seq

### 6.1 任务

输入：

```text
VHH sequence
antigen sequence
```

输出：

```text
binding probability in [0,1]
binding label
```

### 6.2 架构

分别计算 VHH 和 antigen 的 640 维 NEF，然后做 Hadamard product：

```text
interaction_feature = NEF_VHH ⊙ NEF_antigen
```

再输入五层 MLP：

```text
640 -> 1024 -> 512 -> 256 -> 128 -> 1 -> sigmoid
```

Hadamard product 可以理解为：只保留 VHH 和 antigen 两侧同时激活的 feature dimensions，用于表示配对特异性。

### 6.3 推理阈值

本地 `predict_seq.py` 使用：

```text
probability > 0.3 -> binder
```

这个阈值不是通用常数，而是作者在 validation set 上按 F1 优化得到的任务特定阈值。迁移到 PVRIG 后必须重新校准。

## 7. NanoBind-site

### 7.1 任务

输入：

```text
VHH sequence
antigen sequence
```

输出：

```text
antigen 每个 residue 的 interface probability
threshold 后的 binding residue positions
```

如果 antigen 长度为 `L`，输出应为：

```text
[p1, p2, ..., pL]
```

### 7.2 Cross-Assist Module

NanoBind-site 不是只看 antigen 本身，而是做 nanobody-guided cross-attention：

```text
Query = antigen features
Key/Value = nanobody features
```

这样预测的是：

```text
对于当前这条 VHH，antigen 的哪些 residues 可能形成界面？
```

而不是：

```text
这个 antigen 一般有哪些表面残基？
```

cross-attention 输出与原始 antigen feature 通过一个可学习参数 `alpha` 融合，`alpha` 初始值为 0.5。

### 7.3 residue-level predictor

每个 antigen residue 的最终特征包含：

```text
VHH global feature
antigen global feature
antigen local/global residue feature
VHH-guided cross-attention feature
```

拼接维度：

```text
8 * hidden_size = 8 * 320 = 2560
```

经过 3 个 residual units、线性层、Dropout 和 sigmoid，输出每个 antigen residue 的 probability。

### 7.4 输出文件

`predict_site.py` 输出 CSV 字段：

```text
pair_id
prediction_scores
binding_sites
binding_residues
```

默认阈值：

```text
score > 0.5 -> predicted interface residue
```

## 8. NanoBind-pro

### 8.1 任务

NanoBind-pro 仍然预测是否结合，但它会先调用 NanoBind-site，使用预测 interface residues 作为 prompt。

### 8.2 site prompt

流程：

```text
NanoBind-site 输出 antigen residue probabilities
  -> threshold 0.5
  -> 转成 0/1 residue mask
  -> Embedding(2, 8)
  -> 加 learnable positional encoding
  -> 单层 8-head Transformer encoder
  -> average pooling 得到 8 维 site prompt
```

site prompt 与 antigen 的 640 维 NEF 拼接，再压回 640 维，然后与 VHH NEF 做 Hadamard product。

最终 MLP 与 NanoBind-seq 类似：

```text
640 -> 1024 -> 512 -> 256 -> 128 -> 1
```

### 8.3 为什么比 NanoBind-seq 强

NanoBind-seq 对 antigen 所有 residue 大致一视同仁；NanoBind-pro 把少量预测界面 residue 的信息显式加入，因此能降低长 antigen 中非功能区域对 binding prediction 的稀释。

本地 `predict_pro.py` 使用：

```text
probability > 0.5 -> binder
```

## 9. NanoBind-pair

### 9.1 任务

输入两个 VHH-antigen pair：

```text
pair 1 = VHH1 + antigen1
pair 2 = VHH2 + antigen2
```

输出：

```text
P(Kd_pair1 > Kd_pair2)
```

这是最容易误解的地方：

```text
输出接近 1：pair 1 的 Kd 更大，因此 pair 1 更弱
输出接近 0：pair 1 的 Kd 更小，因此 pair 1 更强
```

不要把 `prediction=1` 误解释为“pair 1 更强”。作者的数据标签定义正好相反：第一对 Kd 更大时 label=1。

### 9.2 架构

每个 pair 先生成 640 维 interaction feature：

```text
f1 = NEF_VHH1 ⊙ NEF_Ag1
f2 = NEF_VHH2 ⊙ NEF_Ag2
```

拼接后：

```text
640 + 640 = 1280 = 4*d0
```

输入 MLP：

```text
1280 -> 640 -> 1024 -> 512 -> 256 -> 1
```

本地 `predict_pair.py` 使用 threshold 0.4。

## 10. NanoBind-affi

### 10.1 它不是独立训练模型

README 提到 `NanoBind_affi.py`，但本地仓库并不存在这个源文件，也不存在独立 affi checkpoint。

实际 `predict_affi.py` 使用：

```text
NanoBind_pair_100.model
data/affinity/reference_set.csv
```

### 10.2 49 个 Kd anchors

reference set 包含 49 个已知 Kd 的 VHH-antigen complexes，按 Kd 从小到大排列。

范围：

```text
最低 Kd = 7.17e-12 M
最高 Kd = 6.96e-4 M
```

49 个 anchors 定义理论上的 50 个区间：

```text
(-∞, anchor_1)
[anchor_1, anchor_2]
...
[anchor_48, anchor_49]
(anchor_49, +∞)
```

对一个 query pair，依次和 49 个 anchors 比较：

```text
query vs anchor_1
query vs anchor_2
...
query vs anchor_49
```

然后找与这些二元相对顺序最一致的 Kd interval。

### 10.3 输出

`predict_affi.py` 输出：

```text
pair_id
best_positions
predicted_Kd_intervals
```

这不是精确 Kd 回归，而是 affinity range estimation。

### 10.4 为什么这样设计

只有 185 个带 Kd 的 complexes，直接训练深度回归模型很容易过拟合。两两比较可以把少量绝对 Kd 转换成大量相对顺序样本，并且区间预测比精确回归更符合数据量限制。

## 11. 数据集总览

NanoBind 有三套主要数据：

```text
binding occurrence dataset
interface residue dataset
affinity dataset
```

这三套数据的标签粒度不同：

| 数据 | 一行代表什么 | 标签 |
| --- | --- | --- |
| Binding | 一对 VHH-antigen sequences | bind / non-bind |
| Site | 一个真实 VHH-antigen complex | antigen residue 0/1 mask |
| Affinity pair | 两个 VHH-antigen complexes 的比较 | pair1 Kd 是否大于 pair2 Kd |

## 12. Binding 数据集

### 12.1 来源

训练和验证集直接使用 DeepNano 整理的数据：

```text
positive 来源：2023-01-24 以前的 SAbDab-nano
negative：cross-mismatching
negative 限制：mismatched antigens sequence identity < 60%
positive:negative = 1:10
```

独立测试集来自 sdAb-DB 工作：

```text
positive = 651
negative = 1,149
negative 构造要求 antigen pairwise edit distance > 0.9
```

### 12.2 本地训练集统计

文件：

```text
data/Sabdab/NAI_train.csv
```

本地实测：

```text
总样本：11,209
positive：1,019
negative：10,190
unique VHH sequences：749
unique antigen sequences：784
```

序列长度：

```text
VHH：min 16, median 121, max 138
antigen：min 10, median 279, max 793
```

存在少数异常短 chain fragment；构建自己的数据时应增加最小长度和序列质量检查。

### 12.3 本地验证集统计

文件：

```text
data/Sabdab/NAI_val.csv
```

本地实测：

```text
总样本：561
positive：51
negative：510
unique VHH sequences：47
unique antigen sequences：51
```

### 12.4 独立测试集

文件：

```text
data/sdab/NAI_test.tsv
data/sdab/NAI_test_seq.fasta
```

本地实测：

```text
总 pair：1,800
positive：651
negative：1,149
FASTA records：3,600
sequence length：104 到 782 aa
```

注意 Linux 区分大小写：

```text
data/Sabdab   训练/验证
data/sdab     独立测试
```

不要把这两个目录名写错。

## 13. Interface residue 数据集

### 13.1 标签定义

从真实 VHH-antigen 复合物结构中计算：

```text
VHH residue 与 antigen residue 距离 <= 5 Å
-> 定义为 interface/binding residue
```

NanoBind-site 训练的是 antigen 侧 residue mask。

### 13.2 训练集

文件：

```text
data/Sabdab/NAI_train_pos.csv
```

本地实测：

```text
样本：1,019
unique PDB：588
unique VHH sequences：749
unique antigen sequences：784
每个 antigen 标注 interface residues：min 10, median 22, max 45
有 affinity 字段的样本：24
```

字段：

```text
pdb
nanobody_chain
seq_nanobody
binding_site_nanobody
antigen_chain
seq_antigen
binding_site_antigen
affinity
affinity_method
```

### 13.3 验证集

文件：

```text
data/Sabdab/NAI_val_pos.csv
```

本地实测：

```text
样本：51
unique PDB：50
antigen interface residue count median：21
```

### 13.4 独立测试集

作者从 2023-01-24 到 2025-03-28 新增的 SAbDab-nano 数据中整理：

```text
data/Sabdab/NAI_test_pos.csv
```

本地实测：

```text
样本：439
unique PDB：257
unique VHH sequences：343
unique antigen sequences：343
antigen interface residue count：min 10, median 21, max 47
```

这个按时间切出的 test set 比随机 row split 更可信，但同源 VHH/antigen 是否完全隔离仍需进一步 cluster audit。

## 14. Affinity 数据集

### 14.1 原始绝对 Kd 数据

文件：

```text
data/affinity/all.csv
```

本地实测：

```text
complexes：185
unique ID：178
全部 185 条有数值 Kd
Kd min：7.17e-12 M
Kd median：1.5e-8 M
Kd max：6.96e-4 M
```

来源：

```text
71 个：SAbDab-nano，版本日期 2025-03-28
114 个：PubMed 文献检索，关键词 nanobody AND SPR
```

部分 antigen sequence 从 PDB 或 UniProt 补充。

### 14.2 相对标签定义

对任意两个 complexes：

```text
pair1 Kd > pair2 Kd -> label = 1
pair1 Kd < pair2 Kd -> label = 0
Kd 相同的组合删除
```

因为 Kd 越小亲和力越强，所以：

```text
label 1 = pair1 weaker
label 0 = pair1 stronger
```

### 14.3 100% overlap split

先把 185 个 complexes 全部两两组合，删除相同 Kd：

```text
原始 comparison groups：16,976
split：6:2:2
```

训练集再通过交换 pair 顺序做增强，最终本地文件：

```text
train_100.csv：20,370
val_100.csv：3,395
test_100.csv：3,396
```

这里 test 中的 complexes 都在 train 中出现过，只是 pairwise 组合不同，因此该 split 的性能偏乐观。

### 14.4 50% overlap split

两阶段 hold-out：

```text
先留出 19 complexes 做 val
再留出 19 complexes 做 test
剩余 147 做 train
再从 train pool 抽 18 个加入 val 和 test
```

这样 val/test 各有 37 个 complexes，其中约一半对训练完全新颖。

本地文件：

```text
train_50.csv：21,708
val_50.csv：665
test_50.csv：663
```

### 14.5 0% overlap split

先按 complex 层面做 6:2:2，再在各 split 内两两组合：

```text
train_0.csv：12,180
val_0.csv：666
test_0.csv：663
```

test complex 完全没有在 train 出现，因此这是评估新 VHH/新 antigen 泛化最重要的 split。

### 14.6 对 PVRIG 项目的关键启发

两两比较能把少量 Kd 扩展为很多 pairwise labels，但这些 labels 不是统计独立样本。不能只看 pair 数量就认为数据量变成了两万。

对 PVRIG 最合理的构造是：

```text
尽量只比较同一个 PVRIG construct
尽量使用同一种 assay
尽量来自同一实验批次
优先比较同 campaign VHH
```

这样能减少不同 antigen、不同 SPR/BLI 条件、不同固定化方式带来的系统偏差。

## 15. 论文性能

### 15.1 Binding prediction

论文五次独立训练平均：

```text
NanoBind-seq
  MCC    0.482 ± 0.054
  F1     0.566 ± 0.065
  AUROC  0.775 ± 0.025
  AUPRC  0.740 ± 0.033

NanoBind-pro
  MCC    0.547 ± 0.056
  F1     0.616 ± 0.049
  AUROC  0.792 ± 0.036
  AUPRC  0.773 ± 0.039
```

NanoBind-pro 相比 seq 的提升说明 predicted interface prompt 确实有价值。

本地已有的单次 `output/test_results/NanoBind_seq_results.csv` 内容是：

```text
Accuracy  0.8050
Precision 0.9054
Recall    0.5146
F1        0.6562
AUROC     0.8170
AUPRC     0.7933
MCC       0.5756
```

这只是仓库内已有输出，不是本轮在当前环境新跑出的结果。

### 15.2 Interface prediction

独立 test set：

```text
NanoBind-site
  MCC    0.249 ± 0.017
  F1     0.272 ± 0.010
  AUROC  0.705 ± 0.007
  AUPRC  0.260 ± 0.012
```

residue-level class imbalance 很强，因此不要只看 accuracy，应重点看 MCC、F1 和 AUPRC。

### 15.3 Relative affinity

```text
NanoBind-pair 100%
  ACC 0.963, MCC 0.924, F1 0.957, AUROC 0.995, AUPRC 0.994

NanoBind-pair 50%
  ACC 0.778, MCC 0.555, F1 0.792, AUROC 0.851, AUPRC 0.864

NanoBind-pair 0%
  ACC 0.701, MCC 0.399, F1 0.645, AUROC 0.758, AUPRC 0.615
```

对我们真正有参考意义的是 0% overlap，而不是 100%。

### 15.4 Affinity range

从 136 个非 reference complexes 中抽 20 个测试：

```text
14 个落在正确 interval
5 个落在相邻 interval
1 个跨 3 bins，但绝对偏差很小
```

更换 20%/40% anchors 后，正确或相邻区间的累计命中率仍约为：

```text
0.97 ± 0.03
0.95 ± 0.05
```

## 16. 训练方法

### 16.1 NanoBind-seq / NanoBind-pro

`train_nai.py` 默认：

```text
batch size：32
learning rate：5e-5
epochs：10
optimizer：AdamW
weight decay：1e-4
loss：binary cross entropy
selection metric：validation AUPRC
seed：1998
```

命令：

```bash
python train_nai.py --Model 0 --finetune 1 --ESM2 esm2_t6_8M_UR50D
python train_nai.py --Model 1 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

### 16.2 NanoBind-site

`train_site.py` 默认：

```text
batch size：8
learning rate：5e-5
epochs：200
optimizer：AdamW
weight decay：0.01
loss：residue-level binary cross entropy
selection metric：validation best F1
```

每个 epoch 会在 validation 上扫描：

```text
threshold = 0.0, 0.1, ..., 1.0
```

选择 F1 最优阈值。

命令：

```bash
python train_site.py --Model 0 --finetune 1 --ESM2 esm2_t6_8M_UR50D
```

### 16.3 NanoBind-pair

`train_pair.py` 默认：

```text
dataset：train_100 / val_100
batch size：32
learning rate：5e-5
epochs：10
optimizer：AdamW
weight decay：1e-4
loss：binary cross entropy
selection metric：validation AUPRC
```

默认脚本只训练 100% overlap 版本。训练 50% 或 0% 版本时，需要手工切换 CSV 路径和保存文件名。

## 17. 环境安装

官方环境：

```text
Python 3.9.13
PyTorch 1.13.1
CUDA 11.6 wheel
Transformers 4.27.4
Biopython 1.78
Pandas 1.3.5
Scikit-learn 1.0.2
```

推荐使用：

```bash
cd /mnt/d/work/抗体/code/downloaded_models/NanoBind
conda env create -f NanoBind_env.yml
conda activate NanoBind
```

当前系统基础 Python 没有：

```text
torch
transformers
biopython
scikit-learn
scipy
```

因此本轮完成了代码、数据、权重和文档级验证，但没有在基础 Python 中重新运行 GPU/CPU 推理。

## 18. 推理命令

README 使用 Windows 反斜杠；在当前 Linux/WSL 环境应改成 `/`。

### 18.1 Binding probability

```bash
python predict_seq.py \
  --nb data/example/nb1.fasta \
  --ag data/example/ag1.fasta
```

### 18.2 Site-prompt binding probability

```bash
python predict_pro.py \
  --nb data/example/nb1.fasta \
  --ag data/example/ag1.fasta
```

### 18.3 Antigen interface residues

```bash
python predict_site.py \
  --nb data/example/nb1.fasta \
  --ag data/example/ag1.fasta
```

### 18.4 Relative affinity

```bash
python predict_pair.py \
  --nb1 data/example/nb1.fasta \
  --ag1 data/example/ag1.fasta \
  --nb2 data/example/nb2.fasta \
  --ag2 data/example/ag2.fasta
```

### 18.5 Affinity interval

```bash
python predict_affi.py \
  --nb data/example/nb1.fasta \
  --ag data/example/ag1.fasta
```

## 19. 输入 FASTA 规则

`predict_seq.py`、`predict_pro.py`、`predict_site.py` 要求：

```text
VHH FASTA records 数量 == antigen FASTA records 数量
第 i 条 VHH 与第 i 条 antigen 配对
```

不是笛卡尔积。

例如：

```text
nb.fasta：4 条 VHH
ag.fasta：4 条 antigen
-> 生成 4 个 pair
```

如果需要把 1 条 PVRIG antigen 与 10,000 条 VHH 全部配对，需要在 antigen FASTA 中重复 PVRIG sequence，或改写 dataloader 做广播。

所有模型默认最大长度 800 aa，超过部分会被 tokenizer 截断。PVRIG ECD 本身不长，不是问题；但输入全长膜蛋白或长 fusion construct 时必须先明确截取胞外结构域。

## 20. 当前代码中的复现注意事项

### 20.1 README 与实际文件不完全一致

README 提到：

```text
models/NanoBind_affi.py
test_case.py
```

本地仓库中这两个源文件不存在。affi 推理实际由 `predict_affi.py + NanoBind_pair.py` 完成。

### 20.2 `predict_affi.py` 阈值和论文不同

论文公式使用：

```text
NanoBind-pair probability >= 0.5
```

本地 `predict_affi.py` 使用：

```text
probability > 0.4
```

复现论文时应明确使用哪个阈值，不要混用。

### 20.3 affinity interval 存在边界索引风险

本地代码包含：

```text
49 reference anchors
48 个内部 interval strings
理论上 50 个区间，包括两个外侧区间
```

`find_best_positions()` 中新最大值分支使用 `i+1`，并列分支使用 `i`，边界位置的编号不一致。极端情况下可能无法正确输出 `<7.17e-12 M`，或者在最弱外侧区间产生索引问题。

因此如果要把 NanoBind-affi 用于正式批量预测，建议先修正并为以下三类情况写单元测试：

```text
query 比所有 anchors 都强
query 位于任意两个 anchors 中间
query 比所有 anchors 都弱
```

### 20.4 pair label 方向很容易写反

再次强调：

```text
label=1 表示 pair1 Kd 更大、亲和力更弱
```

PVRIG 数据生成脚本必须与这个定义一致。

### 20.5 100% overlap 权重不等于新靶点泛化权重

`NanoBind_pair_100.model` 在 test 中见过相同 complexes，只有组合不同。将它用于全新 PVRIG campaign 时，应把 0% overlap 结果视为更现实预期，并优先比较 `pair_0.model`。

### 20.6 随机性设置有拼写问题

训练脚本写的是：

```python
torch.backends.cudnn.deterministics = True
```

PyTorch 正确属性通常是：

```python
torch.backends.cudnn.deterministic = True
```

原代码的设置可能没有真正启用 deterministic mode。

### 20.7 padding 未完全参与后续 mask

ESM-2 接收 attention mask，但自定义 self-attention 和全局平均池化没有显式排除 padding residue。对变长 batch，这可能让 padding 影响 NEF。单条推理影响较小；重新训练时应考虑 masked attention 和 masked mean pooling。

## 21. 对 PVRIG 项目最有用的模块

### 21.1 NanoBind-seq：第一层 binder filter

输入：

```text
candidate VHH sequence
PVRIG extracellular-domain sequence
```

输出：

```text
PVRIG binding probability
```

用途：快速筛掉明显 non-binder。

### 21.2 NanoBind-site：PVRIG contact map

输出 PVRIG 每个 residue 被当前 VHH 接触的概率。

我们可以准备一个已知 PVRIG-PVRL2 interface mask：

```text
M_PVRL2[i] = 1 if PVRIG residue i belongs to PVRL2 interface
```

NanoBind-site 输出：

```text
P_VHH_contact[i]
```

计算：

```text
interface_overlap = sum(P_VHH_contact[i] * M_PVRL2[i]) / sum(M_PVRL2)
```

这可以成为 sequence-only blocker prior。

但要注意：预测 VHH 接触 PVRIG-PVRL2 interface 不等于一定阻断，仍需结构和竞争实验确认。

### 21.3 NanoBind-pro：把 interface prior 注入 binding

NanoBind-pro 已经证明 site prompt 能提高 binding prediction。我们可以把普通 site mask 替换或扩展成：

```text
predicted VHH-PVRIG contact mask
known PVRIG-PVRL2 functional interface mask
hotspot mask
```

让模型不仅知道“哪里可能结合”，还知道“哪些位置与阻断功能有关”。

### 21.4 NanoBind-pair：同靶点候选相对排序

对于两个候选：

```text
VHH-A + PVRIG
VHH-B + PVRIG
```

pairwise classifier 可以学习：

```text
哪一个 Kd 更小
哪一个 affinity 更强
```

相对排序通常比直接回归 Kd 更适合小数据。

### 21.5 NanoBind-affi：PVRIG-specific Kd bins

不建议直接使用跨 49 种不同 complexes 的全局 anchors 作为最终 PVRIG Kd 标尺。

更好的做法是收集 PVRIG-specific anchors：

```text
已实验测定 Kd 的 PVRIG VHH
同一个 PVRIG construct
同一种 SPR/BLI assay
相同或可校准的实验条件
```

即使只有 8-20 个 anchors，也可能比跨 antigen 的 49 个参考更适合我们的 campaign。

## 22. 建议改造成 PVRIG 多任务模型

我们真正需要的任务不是五个原始任务的简单复制，而是：

```text
Task 1：binds_PVRIG
Task 2：PVRIG contact residue probabilities
Task 3：overlaps_PVRL2_interface
Task 4：blocks_PVRIG_PVRL2
Task 5：relative_affinity
Task 6：Kd_interval
```

推荐共享 NanoBind Encoder，然后建立多个 heads：

```text
shared ESM-2 + global/local CDR encoder
  ├─ binding head
  ├─ antigen-site head
  ├─ blocker head
  ├─ pairwise affinity head
  └─ affinity-bin head
```

blocker head 的输入可以包含：

```text
VHH NEF
PVRIG NEF
predicted contact mask
known PVRIG-PVRL2 interface mask
contact/interface overlap
docking-derived steric blocking score
Rosetta/NanoBinder structural score
```

## 23. PVRIG 数据表建议

建议每个实验 VHH-PVRIG pair 保留：

```text
vhh_id
vhh_sequence
cdr1
cdr2
cdr3
pvrig_construct_id
pvrig_sequence
binds_pvrig
binding_probability_label_source
blocks_pvrig_pvrl2
competition_assay_type
competition_percent
ic50_nm
kd_m
kd_method
pvrig_contact_residues
pvrl2_interface_overlap
epitope_bin
structure_pose_id
rosetta_binding_score
campaign_id
assay_batch
split_group_cdr3
split_group_scaffold
notes
```

最重要的 hard negative：

```text
binds_pvrig = 1
blocks_pvrig_pvrl2 = 0
```

如果缺少这类样本，模型只会学习 binder，不会学会 blocker。

## 24. PVRIG affinity pair 构造原则

对同一批 PVRIG VHH：

```text
if Kd_A > Kd_B:
    label(A,B) = 1
    label(B,A) = 0
```

同时记录：

```text
assay type
instrument
temperature
PVRIG construct
immobilization direction
fit model
batch
```

推荐只在条件相容时生成 pairwise label。

不要把不同条件下的 10 nM 和 20 nM 机械地视为可靠顺序，因为实验误差可能大于差异。

可以设置最小 log-fold gap：

```text
abs(log10(Kd_A) - log10(Kd_B)) >= delta
```

差异过小的 pair 标为 uncertain 或不加入训练。

## 25. 推荐的实际筛选流程

```text
候选 VHH 序列
  -> developability/sequence filters
  -> NanoBind-seq binding probability
  -> NanoBind-site PVRIG contact map
  -> contact map 与 PVRIG-PVRL2 interface overlap
  -> NanoBind-pro site-prompt binding probability
  -> VHH-PVRIG docking
  -> NanoBinder-style Rosetta score
  -> structural blocking/steric score
  -> NanoBind-pair relative affinity ranking
  -> PVRIG-specific blocker ensemble
  -> SPR/BLI + competition assay
```

## 26. 与前五个模型的关系

| 模型 | 主要输入 | 主要输出 | PVRIG 定位 |
| --- | --- | --- | --- |
| DeepNano | VHH + antigen sequence/site prompt | binding probability | 第一层 binder 筛选 |
| NABP-BERT | VHH + antigen sequence | binding probability | sequence-only baseline |
| NABP-LSTM-Att | CDR + antigen sequence | binding probability | CDR-aware 轻量模型 |
| Sequence-Based NABP | k-mer/minimizer/PWM | binding class | 传统 ML baseline |
| NanoBinder | complex structure + Rosetta | pose binding probability | docking pose 过滤 |
| NanoBind | sequence + site + relative affinity | binding/site/Kd range | 多任务主干与 blocker 改造基础 |

最合理的组合不是只选一个，而是：

```text
NanoBind sequence/site/affinity
+ NanoBinder structure score
+ PVRIG-PVRL2 interface/blocking labels
```

## 27. 主要局限

### 27.1 Binding negatives 仍是构造标签

训练 negative 由 cross-mismatching 产生，不是全部实验 non-binder。

### 27.2 缺少 near-binding hard negatives

论文也指出当前数据难以严格测试 true/near-binding negatives。对 blocker 项目，这个问题更严重。

### 27.3 Affinity 数据跨 antigen、跨文献、跨 assay

185 个 Kd 来源异质，可能存在 assay condition confounding。

### 27.4 区间预测不是精确 Kd

NanoBind-affi 输出 range，不应把区间中点当成可靠 Kd。

### 27.5 interface prediction 不等于 blocking prediction

预测接触 PVRIG 某些 residues 仍不能证明与 PVRL2 竞争。

### 27.6 模型最大长度 800

长 antigen 会被截断；应使用生物学相关 domain，而不是盲目输入全长 precursor。

## 28. 结论

NanoBind 是这六个工作中最适合用作我们自研模型架构参考的一个，因为它已经把任务拆成：

```text
是否结合
在哪里结合
谁更强
大致多强
```

对 PVRIG 项目，最重要的不是原样调用五个子模型，而是增加缺失的功能层：

```text
是否覆盖 PVRIG-PVRL2 interface
是否真正阻断 PVRIG-PVRL2
```

最值得直接复用的部分：

```text
1. ESM-2 + Global/Local CDR encoder
2. NanoBind-site 的 partner-specific cross-attention
3. NanoBind-pro 的 interface prompt
4. NanoBind-pair 的小数据相对亲和力学习
5. NanoBind-affi 的 anchor-based range estimation
```

必须新增的部分：

```text
1. PVRIG-PVRL2 interface mask
2. blocker/non-blocker labels
3. binder-but-non-blocker hard negatives
4. docking/steric-blocking/Rosetta structural features
5. PVRIG-specific affinity anchors
```

因此，NanoBind 最适合作为我们未来 `PVRIG-specific multi-task nanobody model` 的序列与界面主干，而 NanoBinder 可以作为它的结构评分补充。

