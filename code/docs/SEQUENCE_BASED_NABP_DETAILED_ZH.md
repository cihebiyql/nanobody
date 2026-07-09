# Sequence-Based Nanobody-Antigen Binding Prediction 详细复现与数据集说明

生成日期：2026-07-08  
工作目录：`/mnt/d/work/抗体/code`  
本地模型目录：`downloaded_models/Sequence-Based-NABP`

本文档记录第四个模型/工作：Sequence-Based Nanobody-Antigen Binding Prediction。它不是一个大规模深度学习模型，而是一个 sequence-only 的传统机器学习 baseline：先把 VHH 和 antigen 序列转换为 k-mer、minimizer、PWM 或理化性质特征，再用 SVM、Random Forest、KNN、MLP 等分类器预测 nanobody-antigen 是否结合。

重点放在数据集构造，因为它和 NABP-BERT 的原始数据非常接近，也很适合我们后续搭建 PVRIG 专用数据集时借鉴和改造。

## 1. 一句话定位

这个工作回答的问题是：

```text
给定一条纳米抗体序列和一条抗原序列，这一对是否像 binding pair？
```

它不回答：

```text
Kd 或亲和力是多少？
PVRIG 上的结合表位在哪里？
是否阻断 PVRIG-PVRL2？
这个 VHH 是否覆盖 PVRIG-PVRL2 功能界面？
```

所以在我们的 PVRIG-PVRL2 阻断型纳米抗体项目中，它最适合作为传统机器学习 baseline 和消融对照，而不是最终排序模型。

## 2. 本地文件状态

代码和数据目录：

```text
downloaded_models/Sequence-Based-NABP
```

主要文件：

```text
README.md
Code/Antigene_Antibody_Data_Preprocessing_kmers.ipynb
Code/Antigene_Antibody_Data_Preprocessing_minimizers.ipynb
Code/Antigene_Antibody_Data_Preprocessing_PWM.ipynb
Code/t-SNE Plots.ipynb
Dataset/Ag-Nb Binding Data with Sequences - Sheet1.csv
Dataset/Ag-Nb Binding data with Sequences_new_Sarwan - Copy.csv
Dataset/Antibodies_Pairwise_Distance_Matrix.csv
Dataset/Nanobody_Features.csv
Dataset/Antigene_Features.csv
Plots/antigene_kmers_embedding.png
Plots/nanobody_kmers_embedding.png
```

本地额外整理了一个可命令行运行的 helper：

```text
repro_helpers/sequence_based_gapped_kmer.py
repro_helpers/requirements-sequence-baseline.txt
```

注意：官方仓库的 `README.md` 基本只有标题，核心逻辑在 notebook 里。这个工作没有深度学习 checkpoint，也没有需要加载的预训练权重；所谓“复现”主要是重新构造数据集、重新提特征、重新训练 scikit-learn 分类器。

## 3. 原始数据集

最重要的数据文件是：

```text
downloaded_models/Sequence-Based-NABP/Dataset/Ag-Nb Binding Data with Sequences - Sheet1.csv
```

本地统计结果如下：

```text
总行数：365
字段：
  sdAb-DB ID
  NB_ID
  Nanobody ID
  Source
  Antigen_ID
  Antigen
  Nanobody Sequence
  Antigen Sequence
  Ag-UniProt-ID

Nanobody ID unique：317
NB_ID unique：365
Antigen_ID unique：47
Antigen unique：48
Ag-UniProt-ID unique：46
```

来源分布：

```text
Llama (Lama glama)：167
Arabian camel (Camelus dromedarius)：102
Alpaca (Vicugna pacos)：41
Synthetic Construct：35
Camelid (Camelidae)：13
Bactrian camel (Camelus bactrianus)：7
```

序列长度：

```text
VHH / Nanobody sequence：
  n = 365
  min = 104 aa
  median = 123 aa
  mean = 122.8 aa
  max = 175 aa

Antigen sequence：
  n = 365
  min = 158 aa
  median = 537 aa
  mean = 751.1 aa
  max = 1816 aa
```

这个 CSV 的 365 行都被当成实验已知 positive binding pair。也就是说，原始数据不是一开始就有 binding / non-binding 二分类标签，而是只有正例。

## 4. 抗原距离矩阵

负样本和伪正样本的构造依赖这个文件：

```text
downloaded_models/Sequence-Based-NABP/Dataset/Antibodies_Pairwise_Distance_Matrix.csv
```

本地统计：

```text
47 x 47 antigen distance matrix
header 示例：AG_1, AG_2, AG_3, AG_39, AG_4, ...
```

这里的距离矩阵不是 VHH 距离，而是 antigen 之间的 pairwise distance。notebook 用它来做两个假设：

1. 如果一个 VHH 结合 antigen A，而 antigen B 和 A 很相似，那么这个 VHH 也可能结合 B。
2. 如果 antigen B 和 A 差异很大，那么把这个 VHH 和 B 配对可以作为 non-binding 候选。

这个构造思路很实用，但也要非常小心：它生成的是推断标签，不是直接实验验证标签。

## 5. notebook 中的数据集构造流程

以 `Code/Antigene_Antibody_Data_Preprocessing_kmers.ipynb` 为主，数据构造大致如下。

### 5.1 原始正样本

先把 365 条原始 VHH-antigen pair 全部标为：

```text
label = Yes
```

这些是原始 positive binding pair。

### 5.2 枚举替换抗原 pair

notebook 对 365 条原始记录做两层循环：

```text
for each known VHH-antigen row i:
    for each antigen row j:
        if antigen_name_j != antigen_name_i:
            生成 VHH_i + antigen_j 候选 pair
```

本地 notebook 输出：

```text
候选替换 pair 数：126,490
```

然后根据原始 antigen ID 和替换 antigen ID 在距离矩阵中查距离。

### 5.3 构造伪正样本

阈值：

```text
Yes_distance_value_threshold = 0.20
```

如果替换 antigen 与原始 antigen 的距离：

```text
distance <= 0.20
```

则把 `VHH_i + antigen_j` 标成新的 `Yes`。

notebook 输出：

```text
伪正样本：1,388
原始正样本：365
最终 Yes：1,753
```

这一步的生物学含义是“抗原相似性标签转移”。它能扩充小数据集，但这些 1,388 条不是直接实验确认的结合事件。

### 5.4 构造负样本候选

阈值：

```text
No_distance_value_threshold = 0.85
```

如果替换 antigen 与原始 antigen 的距离：

```text
distance >= 0.85
```

则把 `VHH_i + antigen_j` 作为 `No` 候选。

notebook 输出：

```text
负样本候选：108,050
```

然后 notebook 只随机取其中一小部分。

### 5.5 下采样负样本

notebook 设置：

```python
rows_percentage_selected = 1.6
num_rows = int((rows_percentage_selected / 100) * len(filtered_No_nanobody_sequences))
```

因此从 108,050 个负样本候选中抽取：

```text
No：1,728
```

### 5.6 最终训练数据规模

notebook 输出：

```text
总行数：3,481
Yes：1,753
No：1,728
```

也就是一个基本平衡的 binding / non-binding 分类数据集。

## 6. 数据构造中的关键风险

这部分非常重要，尤其是我们后续要自己建 PVRIG 数据集时不能照搬所有细节。

### 6.1 负样本不是实验阴性

`No` 标签来自 antigen 距离大于等于 0.85，而不是实验验证“不结合”。这类 negative 更准确地说是 presumed non-binding pair。

对普通纳米抗体-抗原二分类来说，这可以作为初始训练集；但对 PVRIG blocker 项目来说还不够，因为我们需要区分：

```text
PVRIG non-binder
PVRIG binder but non-blocker
PVRIG-PVRL2 blocker
```

如果只有“远距离 antigen 替换负样本”，模型学到的可能只是“抗原类型是否相似”，不一定学到 PVRIG 表位和阻断机制。

### 6.2 伪正样本也不是实验阳性

`distance <= 0.20` 的样本是根据 antigen 相似性扩增出来的。它的潜在问题是：相似 antigen 不一定共享同一个 VHH epitope，也不一定共享结合能力。

对于我们自己的数据集，可以使用这种思想，但最好明确标记：

```text
label_source = experimental_positive
label_source = transferred_positive_by_antigen_similarity
label_source = presumed_negative_by_antigen_distance
```

训练时可以给不同来源的 label 设置不同权重。

### 6.3 row-level split 可能高估泛化

notebook 用 `ShuffleSplit(n_splits=5, test_size=0.3)` 做随机划分。因为同一 VHH 序列、同一 antigen 序列、相似 antigen 或扩增样本可能同时出现在 train 和 test 中，row-level split 很容易高估泛化性能。

更严格的划分方式应该是：

```text
按 Nanobody ID / CDR3 cluster 划分
按 Antigen_ID / antigen family 划分
按 VHH-antigen pair group 划分
```

PVRIG 项目中，尤其应该避免同一条 VHH 或高度相似 CDR3 同时出现在训练集和测试集。

### 6.4 notebook 的负样本抽样实现有配对风险

notebook 对负样本下采样时分别对 nanobody 序列、antigen 序列和 label 做 `np.random.choice`：

```python
nanobody_sequences_NO_random_rows = np.random.choice(filtered_No_nanobody_sequences, ...)
antigene_sequences_NO_random_rows = np.random.choice(filtered_No_antigene_sequences, ...)
binding_label_NO_random_rows = np.random.choice(filtered_No_label_value, ...)
```

这会破坏原本的 VHH-antigen pair 对应关系。用于快速 baseline 影响不一定致命，但如果我们要做严谨复现或构建自己的 PVRIG 数据集，不应该这样写。正确做法是对“整行 pair”采样，而不是分别采样每个字段。

### 6.5 另一个 CSV 不建议作为主数据

本地还有：

```text
Dataset/Ag-Nb Binding data with Sequences_new_Sarwan - Copy.csv
```

这个文件只有约 303 行，并且存在大量空白/异常行。建议以 `Ag-Nb Binding Data with Sequences - Sheet1.csv` 作为主数据源。

## 7. 特征工程

这个工作比较有价值的地方不是模型复杂度，而是给了几类传统序列特征。

### 7.1 k-mer frequency

`Antigene_Antibody_Data_Preprocessing_kmers.ipynb` 中默认：

```text
k = 3
alphabet = A-Z
```

它为 VHH 和 antigen 分别统计 3-mer 频率。因为用的是 26 个英文字母：

```text
26^3 = 17,576
```

所以一条 VHH 的 3-mer frequency 是 17,576 维，一条 antigen 的 3-mer frequency 也是 17,576 维。

### 7.2 理化性质特征

notebook 还拼接了 VHH 和 antigen 的 11 个理化性质特征。本地文件：

```text
Dataset/Nanobody_Features.csv
Dataset/Antigene_Features.csv
```

字段包括：

```text
charge_at_pH_val
gravy
molecular_weight
aromaticity
instability_index
isoelectric_point
secondary_structure_fraction (helix)
secondary_structure_fraction (turn)
secondary_structure_fraction (sheet)
molar_extinction_coefficient (reduced)
molar_extinction_coefficient (oxidized)
```

最终拼接维度：

```text
VHH 3-mer：17,576
VHH 理化性质：11
Antigen 3-mer：17,576
Antigen 理化性质：11
总维度：35,174
```

notebook 中本地输出也显示：

```text
combined_data shape = (3481, 35174)
```

### 7.3 PCA 降维

notebook 对 35,174 维特征做 PCA：

```python
PCA(n_components=744)
```

输出：

```text
35174 -> 744
```

再把 744 维向量送入传统分类器。

### 7.4 minimizer 特征

`Antigene_Antibody_Data_Preprocessing_minimizers.ipynb` 使用 minimizer 思想构造更紧凑的序列特征。它的结果和 k-mer 非常接近，Random Forest 仍然最好。

### 7.5 PWM 特征

`Antigene_Antibody_Data_Preprocessing_PWM.ipynb` 使用 PWM/position-weight-matrix 相关表示，也做同样的分类器比较。

### 7.6 gapped k-mer 思路

notebook 里有 gapped k-mer 示例。对一个 3-mer：

```text
ACD
```

可以生成：

```text
ACD
-CD
A-D
AC-
```

也就是原始 k-mer 加上单缺口变体。这个思想适合小数据场景，因为它比严格连续 k-mer 更能容忍局部突变或保守替换。

本地 helper `repro_helpers/sequence_based_gapped_kmer.py` 就实现了这个 gapped k-mer spectrum 思路，并把 VHH 和 antigen 的 gapped k-mer 特征拼接后送入传统 ML 分类器。

## 8. 训练方法

notebook 对同一个数据集比较了多个 scikit-learn 分类器：

```text
SVM
Gaussian Naive Bayes
MLP
KNN
Random Forest
Logistic Regression
Decision Tree
```

划分方式：

```text
ShuffleSplit
n_splits = 5
test_size = 0.3
```

评估指标：

```text
Accuracy
Precision
Recall
F1 weighted
F1 macro
ROC AUC
Runtime
```

注意：notebook 的 ROC AUC 主要基于预测类别而不是严格的概率分数，所以它更像一个粗略分类性能指标，不应和深度学习论文中基于概率曲线的 AUROC 直接等价比较。

## 9. 本地 notebook 中的性能

### 9.1 k-mer 特征

`Antigene_Antibody_Data_Preprocessing_kmers.ipynb` 的 5 次 ShuffleSplit 平均结果：

```text
SVM  Accuracy 0.791, ROC AUC 0.790
NB   Accuracy 0.695, ROC AUC 0.691
MLP  Accuracy 0.811, ROC AUC 0.811
KNN  Accuracy 0.844, ROC AUC 0.844
RF   Accuracy 0.897, ROC AUC 0.898
LR   Accuracy 0.827, ROC AUC 0.827
DT   Accuracy 0.847, ROC AUC 0.847
```

Random Forest 最好，接近原始描述中的约 90% accuracy。

### 9.2 minimizer 特征

`Antigene_Antibody_Data_Preprocessing_minimizers.ipynb` 的 Random Forest：

```text
RF Accuracy 0.896
RF ROC AUC 0.897
```

### 9.3 PWM 特征

`Antigene_Antibody_Data_Preprocessing_PWM.ipynb` 的 Random Forest：

```text
RF Accuracy 0.893
RF ROC AUC 0.894
```

整体结论：在这个数据构造和 row-level split 设置下，Random Forest 对传统序列特征表现最好。

## 10. 输出是什么

这个工作输出的是二分类结果：

```text
Yes / No
```

根据分类器不同，也可以输出：

```text
binding probability
decision score
class label
```

但它没有以下输出：

```text
Kd
IC50
blocking probability
PVRIG-PVRL2 competition score
interface residues
epitope location
complex pose quality
```

因此它只能作为“是否可能结合”的粗筛基线，不能作为 PVRIG blocker 的最终判断。

## 11. 如何复现官方 notebook

官方 notebook 写死了 Windows 绝对路径，例如：

```text
E:/RA/Antigene_Antibody/Dataset/New/Ag-Nb Binding Data with Sequences - Sheet1.csv
```

本地复现时需要把路径改成：

```text
downloaded_models/Sequence-Based-NABP/Dataset/Ag-Nb Binding Data with Sequences - Sheet1.csv
downloaded_models/Sequence-Based-NABP/Dataset/Antibodies_Pairwise_Distance_Matrix.csv
```

推荐流程：

```bash
cd /mnt/d/work/抗体/code
python3 -m venv .venv_sequence_nabp
source .venv_sequence_nabp/bin/activate
pip install numpy pandas scikit-learn biopython matplotlib seaborn notebook
jupyter notebook downloaded_models/Sequence-Based-NABP/Code/Antigene_Antibody_Data_Preprocessing_kmers.ipynb
```

打开 notebook 后，需要手动修改路径再运行。若要严谨复现，我建议先把 notebook 改造成 `.py` 脚本，并修复“负样本分字段随机采样”的问题。

## 12. 如何运行本地 helper

本地 helper 不是官方 notebook 的逐行复刻，而是一个更干净的 gapped k-mer baseline：

```text
repro_helpers/sequence_based_gapped_kmer.py
```

它做的事情：

1. 读取 365 条原始 positive pair。
2. 读取 antigen distance matrix。
3. 可选地根据相似 antigen 生成 pseudo-positive。
4. 根据 antigen distance 生成 presumed-negative。
5. 对 VHH 和 antigen 分别提 gapped k-mer spectrum。
6. 拼接 VHH 特征和 antigen 特征。
7. 训练 Random Forest、SVM、Logistic Regression、Decision Tree、Gaussian NB、KNN 或 MLP。
8. 输出 5-fold / ShuffleSplit 指标到 JSON。

安装依赖：

```bash
cd /mnt/d/work/抗体/code
python3 -m venv .venv_sequence_baseline
source .venv_sequence_baseline/bin/activate
pip install -r repro_helpers/requirements-sequence-baseline.txt
```

运行 Random Forest baseline：

```bash
python repro_helpers/sequence_based_gapped_kmer.py \
  --classifier rf \
  --splits 5 \
  --test-size 0.30 \
  --out-dir repro_outputs/sequence_based_gapped_kmer_rf
```

输出文件：

```text
repro_outputs/sequence_based_gapped_kmer_rf/metrics.json
```

如果希望保存最后一个 fold 的模型：

```bash
python repro_helpers/sequence_based_gapped_kmer.py \
  --classifier rf \
  --splits 5 \
  --save-model \
  --out-dir repro_outputs/sequence_based_gapped_kmer_rf
```

注意：helper 当前依赖 `scikit-learn`。如果直接在系统 Python 下运行并报：

```text
ModuleNotFoundError: No module named 'sklearn'
```

就使用上面的 venv 安装依赖。

## 13. 这个模型对 PVRIG 项目的用处

### 13.1 最适合作为 baseline

它很适合写进我们的方案或论文中作为传统机器学习 baseline：

```text
gapped k-mer + Random Forest
k-mer + Logistic Regression
k-mer + XGBoost
CDR-only k-mer + Random Forest
VHH full sequence + PVRIG ECD sequence baseline
```

这样我们可以证明后续 DeepNano、NABP-BERT、NABP-LSTM-Att、结构 docking 模型或多任务模型确实优于简单特征。

### 13.2 适合小数据冷启动

PVRIG 专用 VHH 数据一开始可能很少。传统特征 + RF/XGBoost 不需要大规模 GPU，也不需要复杂预训练，适合在只有几十到几百条实验数据时先跑起来。

### 13.3 适合做消融

可以比较：

```text
全 VHH 序列 vs CDR-only
CDR1+CDR2+CDR3 vs CDR3-only
PVRIG 全胞外域 vs PVRIG interface window
普通 k-mer vs gapped k-mer
只用序列特征 vs 序列 + docking/interface 特征
```

这对我们判断“阻断信息到底来自哪里”很有帮助。

### 13.4 可以做快速 hard-negative 诊断

训练 PVRIG blocker 模型时，最重要的不是普通 negative，而是 hard negative：

```text
能结合 PVRIG，但不阻断 PVRIG-PVRL2
```

Sequence-Based baseline 可以先训练一个普通 PVRIG binding classifier。如果一个 VHH 被这个 baseline 判断很像 binder，但在竞争实验中不阻断，就可以加入 hard-negative blocker 数据集。

## 14. 迁移到我们自己的 PVRIG 数据集时该怎么设计

我建议不要只做二分类：

```text
VHH + PVRIG -> bind / non-bind
```

而是至少设计成三类或多任务：

```text
class 0：non-binder
class 1：PVRIG binder but non-blocker
class 2：PVRIG-PVRL2 blocker
```

或者多任务：

```text
task 1：binds_PVRIG
task 2：blocks_PVRIG_PVRL2
task 3：binds_interface_site
task 4：affinity_bin / Kd_range
```

### 14.1 推荐数据表字段

建议我们自己的训练表至少包含：

```text
vhh_id
vhh_sequence
cdr1
cdr2
cdr3
target_id
target_sequence
target_region
binds_pvrig
blocks_pvrig_pvrl2
competition_assay_type
kd_nm
ic50_nm
epitope_bin
interface_residue_label
label_source
assay_source
split_group_vhh
split_group_cdr3
split_group_target
notes
```

其中：

```text
binds_pvrig：是否结合 PVRIG
blocks_pvrig_pvrl2：是否阻断 PVRIG-PVRL2
kd_nm：亲和力，缺失也可以
ic50_nm：竞争/阻断强度，缺失也可以
epitope_bin：是否落在 PVRL2 interface 附近
label_source：实验标签、相似性转移标签、docking 推断标签等
```

### 14.2 PVRIG-specific negative 应该分层

不能只用随机 VHH 或其他 antigen pair 作为 negative。更好的 negative 分层是：

```text
easy negative：
  完全不结合 PVRIG 的 VHH

decoy antigen negative：
  结合其他靶点但不应结合 PVRIG 的 VHH

hard negative：
  结合 PVRIG，但不阻断 PVRIG-PVRL2 的 VHH

interface hard negative：
  docking 看起来能接触 PVRIG，但不覆盖 PVRL2 interface 的 VHH
```

Sequence-Based NABP 原始数据只有前两类思想，没有 PVRIG blocker hard negative。

### 14.3 推荐 split 策略

PVRIG 数据集必须避免 row-level 泄漏。推荐：

```text
Group split by VHH clone / CDR3 cluster
Group split by scaffold family
Hold-out top CDR3 identity cluster
Temporal split by discovery campaign
Assay-batch-aware split
```

如果将来只有一个 target PVRIG，那么 antigen split 没意义；重点应放在 VHH/CDR3/scaffold 的去冗余和 hold-out。

## 15. 我建议我们如何使用它

对当前项目，我建议把 Sequence-Based NABP 放在这个位置：

```text
候选 VHH 序列
  ↓
规则过滤：长度、框架、CDR3、疏水性、聚集风险
  ↓
Sequence-Based baseline：gapped k-mer + RF/XGBoost
  ↓
DeepNano / NABP-BERT / NABP-LSTM-Att：sequence-only binding ensemble
  ↓
结构建模/docking：VHH-PVRIG pose
  ↓
PVRIG-PVRL2 interface overlap/blocking score
  ↓
综合排序 + 实验验证
```

它的角色应该是：

```text
便宜、快、可解释、可做 baseline
```

不是：

```text
最终 blocker predictor
```

## 16. 与前面三个模型的区别

| 模型 | 主要表示 | 是否深度学习 | 输出 | 对 PVRIG 的定位 |
| --- | --- | --- | --- | --- |
| DeepNano | ESM2 + ensemble + site prompt | 是 | binding probability / site-aware prediction | 第一层 binder 筛选 |
| NABP-BERT | 3-mer BERT | 是 | binding probability | sequence-only binder 概率 |
| NABP-LSTM-Att | CDR + antigen + BiLSTM attention | 是 | binding probability | CDR-aware 轻量模型 |
| Sequence-Based NABP | k-mer/minimizer/PWM + ML | 否 | Yes/No 或概率/score | baseline 与消融对照 |

Sequence-Based NABP 的优势是简单、可解释、依赖少；劣势是表示能力弱、容易受数据泄漏影响、没有结构/表位/阻断信息。

## 17. 结论

Sequence-Based Nanobody-Antigen Binding Prediction 对我们最有价值的不是它本身的 90% accuracy，而是它提供了一个非常清楚的传统 baseline 范式：

```text
小规模 positive pair
  + antigen distance 生成 pseudo-positive / presumed-negative
  + k-mer/gapped-kmer/minimizer/PWM
  + Random Forest / XGBoost
  + 严格 group split
```

迁移到 PVRIG 项目时，我们可以保留“序列特征 + 传统模型 + baseline”的框架，但必须修改标签体系：

```text
不要只预测 bind / non-bind
必须显式加入 blocker / non-blocker
必须收集 PVRIG binder but non-blocker 作为 hard negative
必须把 PVRIG-PVRL2 interface 信息引入后续结构评分或多任务标签
```

因此，这个工作适合用于：

```text
1. PVRIG VHH 早期快速 baseline
2. 传统机器学习对照
3. CDR/k-mer 消融实验
4. 小数据阶段的冷启动模型
```

不适合单独用于：

```text
1. 最终阻断排序
2. Kd 预测
3. PVRIG-PVRL2 interface 覆盖判断
4. 实验候选的最终决策
```
