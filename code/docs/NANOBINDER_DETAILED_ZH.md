# NanoBinder 详细复现与 PVRIG 结构评分说明

生成日期：2026-07-09  
工作目录：`/mnt/d/work/抗体/code`  
本地模型目录：`downloaded_models/NanoBinder`  
论文：Shrestha 等，*NanoBinder: a machine learning assisted nanobody binding prediction tool using Rosetta energy scores*，Journal of Cheminformatics，2025-06-16，DOI: https://doi.org/10.1186/s13321-025-01040-1  
代码仓库：`https://github.com/pallucs/NanoBinder`

本文档记录第五个模型 NanoBinder 的模型思想、数据集构造、训练方法、输入输出、使用方式、本地复现状态，以及它如何改造成我们 PVRIG-PVRL2 阻断型纳米抗体项目中的结构评分模块。

和前面几个 sequence-only 模型不同，NanoBinder 的核心不是从 VHH 和 antigen 序列直接判断是否结合，而是先有一个 VHH-antigen 复合物结构，再用 Rosetta 计算能量项和界面项，最后用机器学习判断这个复合物是否像真实结合复合物。

## 1. 一句话定位

NanoBinder 可以理解为：

```text
VHH-antigen complex pose
  -> Rosetta energy / interface features
  -> Random Forest
  -> binding probability / binder vs non-binder
```

它适合回答：

```text
这个已经建模或 docking 得到的 VHH-antigen 复合物 pose，在结构能量和界面特征上像不像真实 binder？
```

它不适合单独回答：

```text
这条 VHH 序列是否结合某个 antigen？
Kd 是多少？
是否阻断 PVRIG-PVRL2？
是否覆盖 PVRIG-PVRL2 功能界面？
```

在我们的 PVRIG 项目里，NanoBinder 的价值比前面几个 sequence-only 模型更接近最终实验目标，因为它可以进入“结构建模/docking 后的候选排序”阶段。但它仍然只是“结构 pose 是否像 binder”的评分器，不是 PVRIG-PVRL2 blocker 专用模型。

## 2. 本地文件与资源状态

本地目录：

```text
downloaded_models/NanoBinder
```

文件：

```text
README.md
Training.py
Hyper_parameter_tunning.py
NanoBinder-workflow.png
LICENSE
_downloads/13321_2025_1040_MOESM1_ESM.docx
_downloads/13321_2025_1040_MOESM2_ESM.docx
```

本地补充依赖文件：

```text
repro_helpers/requirements-nanobinder.txt
```

本地状态要特别注意：

```text
没有 dataset.csv
没有 RF_model_best.pkl
没有已经训练好的模型权重
没有 Rosetta 特征提取脚本
```

也就是说，当前公开仓库不能直接一键跑出 NanoBinder。它提供了 Random Forest 训练和调参脚本，但没有提供训练数据 `../data/Dataset/dataset.csv`，也没有提供最终训练好的 `.pkl` 模型。

论文页面提供了 supplementary DOCX，本地已下载到：

```text
downloaded_models/NanoBinder/_downloads/13321_2025_1040_MOESM1_ESM.docx
downloaded_models/NanoBinder/_downloads/13321_2025_1040_MOESM2_ESM.docx
```

`MOESM1` 主要包含交叉验证结果、实验验证表、超参数表等；`MOESM2` 是 web server 使用说明。

## 3. 这个工作和前四个模型的根本区别

前四个模型主要是 sequence-only：

```text
VHH sequence + antigen sequence -> binding probability
```

NanoBinder 是 structure-first：

```text
VHH-antigen complex structure -> Rosetta features -> binding probability
```

所以它不适合作为第一层筛选几万条 VHH 序列的模型。它更适合用在候选已经缩小、并且我们已经有 VHH-PVRIG 复合物结构或 docking pose 的阶段。

对 PVRIG 项目，一个合理的位置是：

```text
候选 VHH 序列
  -> DeepNano / NABP-BERT / NABP-LSTM-Att / baseline 做序列粗筛
  -> 建模 VHH 结构
  -> docking 到 PVRIG
  -> NanoBinder-style Rosetta feature score
  -> PVRIG-PVRL2 interface overlap / blocker score
  -> 最终排序
```

## 4. 数据集构造

NanoBinder 的数据集是本文档最重要的部分。

论文描述的训练集来自 SAbDab 中的 nanobody-antigen 结构复合物。它先收集实验验证的 binding NB-AG complex，然后构造 non-binding NB-AG complex，最后对每个结构计算 Rosetta energy scores。

### 4.1 正样本

正样本来自 SAbDab 中实验验证的 nanobody-antigen complex。论文方法部分说明筛选条件包括：

```text
PDB identifier
nanobody heavy chain
antigen chain
antigen type
antigen type = Protein
```

非蛋白 antigen 被排除：

```text
carbohydrate
peptide
hapten
nucleic acid
```

论文 Fig. 1 / Methods 中给出的正样本规模：

```text
binding NB-AG complexes：1,396
label = 1
```

这比 DeepNano / SAbDab-nano 那种“序列 pair”数据更结构化，因为这里每一条样本必须有可用于 Rosetta 计算的三维复合物结构。

### 4.2 负样本

SAbDab 主要提供 binding complex，不天然提供大量 non-binding complex。NanoBinder 的关键数据工程就在负样本构造。

论文描述的负样本构造逻辑是：

```text
1. 从已有 binding complex 池中随机选择两个 NB-AG 复合物。
2. 在 PyMOL 中加载两个结构。
3. 使用 annotate_v 选择 nanobody heavy chain。
4. 用 PyMOL align 对两个 heavy chain 做结构叠合。
5. 如果 heavy-chain backbone RMSD < 2 Å，则把一个复合物中的 nanobody 和另一个复合物中的 antigen 组合成新复合物。
6. 每一对满足 RMSD < 2 Å 的 binding complexes 可以生成两个新的 non-binding complexes。
7. 已用于该过程的 binding complex 只使用一次，以减少冗余。
```

最终负样本数量：

```text
non-binding NB-AG complexes：2,570
label = 0
```

这里的负样本不是实验验证的“不结合”，而是结构重组得到的 presumed non-binding complex。它背后的假设是：两个结构相似的 nanobody scaffold 可以叠合，但换到另一个 antigen 上后，其 CDR 和 antigen 表面通常不互补，因此可作为非结合复合物。

### 4.3 最终训练数据规模

最终数据集：

```text
positive / binding：1,396
negative / non-binding：2,570
total：3,966
```

这个比例故意让 negative 更多，因为真实筛选场景中，大部分设计候选往往是不结合或弱结合。

### 4.4 对我们 PVRIG 数据集的启发

NanoBinder 的数据集思想对我们很有启发：

```text
不要只构造序列 pair 数据
要构造 pose-level 数据
每个 VHH-PVRIG docking pose 都可以是一条训练/评分样本
每条样本必须有结构特征
```

但 PVRIG 项目不能只照搬它的 label：

```text
NanoBinder label：binder / non-binder
我们需要 label：binder / non-binder / binder-but-non-blocker / blocker
```

我们的 hard negative 应该重点收集：

```text
能结合 PVRIG，但不阻断 PVRIG-PVRL2 的 VHH
```

这类样本是 NanoBinder 原始数据集没有显式区分的。

## 5. Rosetta 特征提取

NanoBinder 的输入不是原始序列，而是 Rosetta score file 中的能量项。

论文方法中描述的结构预处理包括：

```text
1. 输入 NB-AG complex PDB。
2. 删除水分子和非必要配体。
3. 删除 nanobody heavy chain 的 constant domain。
4. 将 nanobody heavy chain 重命名为 H。
5. 将 antigen chain 重命名为 A。
6. 重排链顺序。
7. 准备 residue file。
8. 使用 NATAA 指定 interface residues 做 native-side-chain repacking。
9. relax 结构，缓解 backbone phi/psi 和 side-chain clash。
10. 每个结构只生成一个 relaxed structure。
11. 生成包含 Rosetta energy scores 的 score file。
```

这里的核心点是：NanoBinder 不做新设计，它只是为了给已有 complex pose 计算更稳定的能量/界面描述符。

### 5.1 初始 40 个 Rosetta 特征

论文列出的初始 Rosetta features 包括 40 项：

```text
total_score
complex_normalized
dG_cross
dG_cross/dSASAx100
dG_separated
dG_separated/dSASAx100
dSASA_hphobic
dSASA_int
dSASA_polar
delta_unsatHbonds
dslf_fa13
fa_atr
fa_dun
fa_elec
fa_intra_rep
fa_intra_sol_xover4
fa_rep
fa_sol
hbond_E_fraction
hbond_bb_sc
hbond_lr_bb
hbond_sc
hbond_sr_bb
hbonds_int
lk_ball_wtd
nres_all
nres_int
omega
p_aa_pp
per_residue_energy_int
pro_close
rama_prepro
ref
side1_normalized
side1_score
side2_normalized
side2_score
yhh_planarity
packstat
sc_value
```

这些特征覆盖了：

```text
复合物整体能量
界面结合能
单位 SASA 归一化结合能
埋藏表面积
疏水/极性埋藏面积
氢键数量和能量
界面残基数
范德华吸引/排斥
构象能、rama、omega、proline closure 等局部几何项
```

### 5.2 从 40 个特征筛到 37 个

论文和脚本都先删除：

```text
packstat
sc_value
total_score
```

原因：

```text
packstat 和 sc_value 在该数据集中为零或不提供有效区分信息
total_score 是总加权分数，和其他能量项高度相关
```

剩余：

```text
37 energy scores
```

### 5.3 从 37 个特征筛到最终 26 个

`Hyper_parameter_tunning.py` 中做了相关性过滤：

```python
corr_matrix = X_data.corr().abs()
upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
to_drop = [column for column in upper.columns if any(upper[column] > 0.95)]
```

也就是：

```text
Pearson |correlation| > 0.95 的冗余特征被删除
```

最终用于 Random Forest 的 26 个特征：

```text
complex_normalized
dG_cross
dG_cross/dSASAx100
dSASA_hphobic
dSASA_int
dSASA_polar
delta_unsatHbonds
dslf_fa13
fa_atr
hbond_E_fraction
hbond_bb_sc
hbond_lr_bb
hbond_sc
hbond_sr_bb
hbonds_int
nres_int
omega
per_residue_energy_int
pro_close
rama_prepro
ref
side1_normalized
side1_score
side2_normalized
side2_score
yhh_planarity
```

这 26 个特征也正是本地 `Training.py` 中硬编码的：

```python
naonobody_features_rf = [...]
```

变量名里 `naonobody` 是原脚本拼写，不影响运行。

## 6. 训练方法

本地 `Training.py` 读取：

```python
df = pd.read_csv('../data/Dataset/dataset.csv')
```

预处理：

```python
df.dropna(inplace=True)
df.drop(columns=['PDB','total_score','description','packstat','sc_value'], inplace=True)
X_data = df[26 selected features]
Y_data = df['label']
```

分类器：

```text
RandomForestClassifier
```

不平衡处理：

```text
SMOTETomek(sampling_strategy='minority')
```

交叉验证：

```text
StratifiedKFold
n_splits = 5
random_state = 43
shuffle = True
```

输出指标：

```text
PRC / average precision
MCC
F1
Accuracy
ROC curve
PR curve
```

保存图：

```text
../results/roc-plot.png
../results/prc-plot.png
```

## 7. Random Forest 超参数

本地 `Training.py` 使用：

```python
params = {
    'n_estimators': 185,
    'criterion': 'gini',
    'max_depth': 10,
    'min_samples_split': 3,
    'min_samples_leaf': 1,
    'max_features': 'sqrt',
    'bootstrap': False,
    'random_state': 474,
    'class_weight': 'balanced'
}
```

补充材料 Table S8 中写的是 `max_features = auto`，而本地代码是 `sqrt`。在旧版 scikit-learn 中，RandomForestClassifier 的 `auto` 对分类任务基本等价于 `sqrt`；在新版 scikit-learn 中 `auto` 已不推荐或不可用。因此本地代码使用 `sqrt` 更适合当前环境。

`Hyper_parameter_tunning.py` 使用 Optuna 搜索：

```text
n_estimators：100 到 500
criterion：gini / entropy
max_depth：4 到 10
min_samples_split：2 到 5
min_samples_leaf：1 到 5
max_features：sqrt / log2
bootstrap：True / False
random_state：1 到 1000
class_weight：balanced / balanced_subsample
```

注意：脚本中 `study.optimize(..., n_trials=10)`，但注释建议至少 5000 trials。复现实验时如果只跑 10 trials，不能期待完全复现论文最优结果。

## 8. 论文和补充材料中的性能

论文报告 Random Forest 是表现最好的模型。

平均 5-fold cross-validation：

```text
MCC：0.8203
F1：0.8806
Accuracy：0.9185
PRC / average precision：0.8253
```

本地下载的 `MOESM1` Supplementary Table S1 中，每折 RF 结果为：

```text
Fold 1：MCC 0.8185, F1 0.8829, ACC 0.9168, PRC 0.8187
Fold 2：MCC 0.8244, F1 0.8804, ACC 0.9205, PRC 0.8374
Fold 3：MCC 0.8330, F1 0.8905, ACC 0.9243, PRC 0.8238
Fold 4：MCC 0.8157, F1 0.8754, ACC 0.9167, PRC 0.8278
Fold 5：MCC 0.8102, F1 0.8740, ACC 0.9142, PRC 0.8190
Average：MCC 0.8203±0.008, F1 0.8806±0.006, ACC 0.9185±0.004, PRC 0.8253±0.008
```

NanoBinder 还和 GDockScore 做了实验验证集比较。论文中设置：

```text
binding probability >= 0.5 -> predicted binder
binding probability < 0.5 -> predicted non-binder
```

实验验证的一个很重要结论是：NanoBinder 对 non-binder 的过滤能力更强，但对 predicted binder 的精确确认仍有 false positive。

这对我们很关键：它更适合作为“排除差 pose / non-binder”的过滤器，而不是唯一决定哪些 VHH 必然成功的模型。

## 9. SHAP 解释和关键特征

论文的 SHAP 分析显示，影响 NanoBinder 判断的主要特征集中在界面结合能和界面质量上。

最重要的特征包括：

```text
dG_cross/dSASAx100
dG_cross
per_residue_energy_int
hbonds_int
side1_normalized
side2_normalized
complex_normalized
delta_unsatHbonds
fa_atr
hbond_bb_sc
```

生物学解释：

```text
dG_cross/dSASAx100：单位界面面积上的结合能，反映界面能量效率
dG_cross：跨界面结合能，越有利通常越支持 binding
per_residue_energy_int：界面残基平均相互作用强度
hbonds_int：界面氢键数量
delta_unsatHbonds：埋藏但未满足的氢键，通常越多越不利
fa_atr：范德华吸引项
side1/side2_normalized：界面两侧的归一化能量
```

对 PVRIG 项目，这些特征可以直接转化为我们的结构评分模块：

```text
VHH-PVRIG pose 是否有足够负的界面能？
单位 buried SASA 的能量是否合理？
是否有足够的界面氢键？
是否存在大量 unsatisfied buried polar atoms？
PVRIG 侧 interface residues 的 per-residue energy 是否集中在 PVRL2 interface？
```

## 10. 输入和输出

### 10.1 输入

从用户使用角度，NanoBinder 需要输入：

```text
VHH-antigen complex PDB
nanobody heavy chain ID
antigen chain ID
结构是否已经 relax
```

web server 默认：

```text
heavy chain = H
antigen chain = A
relaxed = Yes
```

本地 2026-07-09 检查：

```text
https://nsclbio.jbnu.ac.kr/tools/webserver/
HTTP status 200
页面 title: Nano-Binder
```

### 10.2 训练脚本输入

`Training.py` 期望一个 CSV：

```text
../data/Dataset/dataset.csv
```

最少需要这些列：

```text
PDB
description
label
total_score
packstat
sc_value
complex_normalized
dG_cross
dG_cross/dSASAx100
dSASA_hphobic
dSASA_int
dSASA_polar
delta_unsatHbonds
dslf_fa13
fa_atr
hbond_E_fraction
hbond_bb_sc
hbond_lr_bb
hbond_sc
hbond_sr_bb
hbonds_int
nres_int
omega
per_residue_energy_int
pro_close
rama_prepro
ref
side1_normalized
side1_score
side2_normalized
side2_score
yhh_planarity
```

如果要完整复现 feature-selection，也要包含 37 个 energy score。

### 10.3 输出

NanoBinder 输出：

```text
binding probability
binding / non-binding label, threshold 通常为 0.5
```

训练脚本输出：

```text
每个 fold 的 PRC、MCC、F1、ACC
ROC curve 图
PR curve 图
```

它不输出：

```text
Kd
IC50
affinity rank with calibrated Kd
PVRIG-PVRL2 blocking probability
epitope residues
是否覆盖功能界面
```

## 11. 如何复现训练

因为公开仓库缺少 `dataset.csv` 和 Rosetta feature extraction pipeline，所以完整复现需要自己重建数据集。

### 11.1 安装 Python 依赖

```bash
cd /mnt/d/work/抗体/code
python3 -m venv .venv_nanobinder
source .venv_nanobinder/bin/activate
pip install -r repro_helpers/requirements-nanobinder.txt
```

### 11.2 准备目录

`Training.py` 用的是相对路径 `../data/Dataset/dataset.csv` 和 `../results/`。如果从 `downloaded_models/NanoBinder` 运行，路径会指向 `downloaded_models/data/Dataset/dataset.csv`，不一定符合直觉。

更稳妥的方法是复制脚本或改路径：

```bash
mkdir -p downloaded_models/NanoBinder/data/Dataset
mkdir -p downloaded_models/NanoBinder/results
```

然后把脚本里的：

```python
df = pd.read_csv('../data/Dataset/dataset.csv')
roc_fig.savefig('../results/roc-plot.png', ...)
prc_fig.savefig('../results/prc-plot.png', ...)
```

改成：

```python
df = pd.read_csv('data/Dataset/dataset.csv')
roc_fig.savefig('results/roc-plot.png', ...)
prc_fig.savefig('results/prc-plot.png', ...)
```

或者从一个人为构造的工作目录运行，让 `../data` 和 `../results` 正好存在。

### 11.3 重建 `dataset.csv`

完整重建步骤：

```text
1. 从 SAbDab 下载 nanobody-antigen complex PDB。
2. 只保留 protein antigen。
3. 记录 PDB ID、nanobody chain、antigen chain、antigen type。
4. 标记所有真实 complex 为 label = 1。
5. 用 PyMOL 对两个 binding complexes 的 nanobody heavy chain 进行结构叠合。
6. 如果 RMSD < 2 Å，则交换 nanobody-antigen pairing，生成 presumed non-binding complex。
7. 标记这些重组 complex 为 label = 0。
8. 对每个 complex 做 Rosetta 预处理、relax、interface repacking。
9. 导出 Rosetta score file。
10. 汇总为 dataset.csv。
```

### 11.4 运行训练

```bash
cd downloaded_models/NanoBinder
python Training.py
```

预期结果：

```text
打印 5 个 fold 的 PRC、MCC、F1、ACC
生成 roc-plot.png
生成 prc-plot.png
```

如果要重新调参：

```bash
cd downloaded_models/NanoBinder
python Hyper_parameter_tunning.py
```

注意：调参脚本默认只跑 10 trials；要接近论文搜索强度，需要显著增大 `n_trials`，并准备较长运行时间。

## 12. 当前本地无法直接复现的原因

本地当前不能直接训练，原因不是 Python 脚本本身，而是资源缺失：

```text
downloaded_models/NanoBinder/data/Dataset/dataset.csv 不存在
downloaded_models/NanoBinder/results/RF_model_best.pkl 不存在
Rosetta score extraction pipeline 不在公开仓库中
Rosetta 本身需要独立安装和许可
```

论文 Data availability 部分写着“没有生成或分析数据集”，但正文 Methods 和代码都显然依赖一个结构训练集以及 `dataset.csv`。因此对我们来说，稳妥表述是：

```text
公开代码仓库给出了训练/调参脚本，但没有公开可直接运行的训练 CSV 和模型权重。
如果要复现，需要按 Methods 从 SAbDab + PyMOL + Rosetta 重新构建结构特征表。
```

## 13. 它和 PVRIG-PVRL2 阻断项目的关系

NanoBinder 对我们非常有用，但要用在正确位置。

### 13.1 它能帮助什么

它可以作为 VHH-PVRIG docking pose 的结构合理性评分器：

```text
这个 pose 是否有合理界面能？
这个 pose 是否有足够 buried SASA？
这个 pose 是否有合理氢键网络？
这个 pose 是否有明显 clash 或 unsatisfied polar penalty？
这个 pose 是否像真实 nanobody-antigen binder？
```

它还可以帮助我们从多个 docking pose 中选择更可信的 pose：

```text
同一个 VHH 对 PVRIG 有 20 个 docked poses
  -> 对每个 pose 计算 Rosetta features
  -> NanoBinder-style RF 给 binding probability
  -> 保留高概率且低 clash 的 poses
```

### 13.2 它不能解决什么

它不能直接判断：

```text
是否阻断 PVRIG-PVRL2
是否覆盖 PVRIG 的 PVRL2 interface
是否与 PVRL2 竞争同一表位
是否一定有低 Kd
```

一个 VHH 可能：

```text
NanoBinder score 高
结构结合合理
但结合在 PVRIG 背面或非功能表位
因此完全不阻断 PVRIG-PVRL2
```

所以 NanoBinder 只能解决“这个 VHH-PVRIG 复合物像不像 binder”，不能解决“它是不是 blocker”。

## 14. 我们应该怎么改造成 PVRIG 结构评分模块

我建议把 NanoBinder 思路扩展成两层结构分数：

```text
binding_pose_score
blocking_interface_score
```

### 14.1 binding_pose_score

这部分借鉴 NanoBinder：

```text
Rosetta interface energy
dG_cross
dG_cross/dSASA
dSASA_int
dSASA_hphobic
dSASA_polar
hbonds_int
delta_unsatHbonds
nres_int
per_residue_energy_int
clash penalty
shape complementarity
```

作用：

```text
判断 VHH-PVRIG pose 是否像真实可结合复合物
```

### 14.2 blocking_interface_score

这是我们必须新增的，NanoBinder 没有：

```text
PVRIG-PVRL2 known interface residues coverage
VHH contact residues 是否覆盖 PVRL2-binding hot spot
VHH 与 PVRL2 是否有空间冲突
VHH footprint 与 PVRL2 footprint 的 Jaccard overlap
VHH-PVRIG pose 是否遮挡 PVRL2 docking path
PVRIG interface side-chain 是否被 VHH 直接接触
```

作用：

```text
判断这个 binder 是否可能是 PVRIG-PVRL2 blocker
```

### 14.3 最终组合

对每个 candidate pose：

```text
final_score =
  w1 * NanoBinder-style binding_pose_score
  + w2 * PVRIG-PVRL2 interface_overlap_score
  + w3 * steric_blocking_score
  + w4 * PVRIG hotspot contact_score
  - w5 * clash/unsatisfied_penalty
  - w6 * developability_penalty
```

如果没有足够训练数据，先用规则化打分；有实验数据后，再训练 PVRIG-specific RF/XGBoost/LightGBM 或多任务模型。

## 15. PVRIG 专用训练表建议

如果我们要基于 NanoBinder 思想训练自己的结构模型，建议每一行是一条 pose，而不是一条序列：

```text
pose_id
vhh_id
pvrig_structure_id
pvrig_chain
vhh_chain
pose_rank
rosetta_total_score
complex_normalized
dG_cross
dG_cross_dSASA_x100
dG_separated
dSASA_int
dSASA_hphobic
dSASA_polar
hbonds_int
delta_unsatHbonds
nres_int
per_residue_energy_int
shape_complementarity
clash_score
pvrig_contact_residues
pvrig_pvrl2_interface_overlap
pvrig_hotspot_contacts
steric_clash_with_pvrl2
binds_pvrig
blocks_pvrig_pvrl2
kd_nm
ic50_nm
label_source
assay_type
split_group_vhh
split_group_cdr3
notes
```

关键是同时保留两个 label：

```text
binds_pvrig
blocks_pvrig_pvrl2
```

因为：

```text
binds_pvrig = 1, blocks_pvrig_pvrl2 = 0
```

这类样本对 blocker 模型最有价值。

## 16. 推荐的 PVRIG 计算流程

```text
1. 准备 PVRIG ECD 结构
2. 标注 PVRIG-PVRL2 interface residues / hotspots
3. 为每条候选 VHH 建模结构
4. 对 VHH-PVRIG 做 docking，保留 top N poses
5. 对每个 pose 做 relax / repack
6. 计算 Rosetta interface features
7. 计算 PVRIG-PVRL2 footprint overlap
8. 计算 VHH 与 PVRL2 的 steric blocking
9. NanoBinder-style RF 过滤明显不合理 pose
10. blocker score 排序
11. 选择少量候选做 BLI/SPR + PVRIG-PVRL2 competition assay
```

实验标签回流后：

```text
1. 更新 pose-level dataset
2. 增加 hard negatives
3. 训练 PVRIG-specific blocker classifier
4. 重新校准 final_score 权重
```

## 17. 使用 NanoBinder web server

web server：

```text
https://nsclbio.jbnu.ac.kr/tools/webserver/
```

Supplementary manual 说明的输入包括：

```text
单个或多个 PDB
heavy chain ID
antigen chain ID
结构是否已经 relax
```

使用注意：

```text
1. 上传 PDB 必须是 nanobody-antigen complex。
2. chain ID 要正确；默认 heavy chain H、antigen chain A。
3. 同一批上传文件最好都已经 relax，或者都没有 relax，不要混用。
4. 未 relax 的结构会让服务器花更长时间。
5. 上传后会返回 JobID，需要保存 JobID 后续查询结果。
```

对我们而言，web server 可作为快速 sanity check；大规模筛选还是应该本地搭 Rosetta + 批处理 pipeline。

## 18. 与前四个模型的比较

| 模型 | 输入 | 主要表示 | 输出 | PVRIG 项目定位 |
| --- | --- | --- | --- | --- |
| DeepNano | VHH 序列 + antigen 序列 / site prompt | ESM2 + ensemble | binding probability | 第一层 binder 粗筛 |
| NABP-BERT | VHH 序列 + antigen 序列 | 3-mer BERT | binding probability | sequence-only binder 概率 |
| NABP-LSTM-Att | VHH CDR + antigen 序列 | CNN + BiLSTM + attention | binding probability | CDR-aware 轻量模型 |
| Sequence-Based NABP | VHH/antigen 序列 | k-mer/minimizer/PWM + ML | Yes/No 或概率 | 传统 baseline |
| NanoBinder | VHH-antigen complex structure | Rosetta energy + RF | binding probability | 结构 pose 过滤与 docking 后排序 |

NanoBinder 是第一个真正进入结构层面的模型。它的输出比 sequence-only 更接近实验复合物合理性，但仍然不是功能阻断预测。

## 19. 主要局限

### 19.1 依赖高质量结构

如果 VHH-PVRIG pose 本身错了，Rosetta energy 再好也可能是假阳性。

### 19.2 不直接预测亲和力

NanoBinder 输出 probability，不是 Kd。它可以排序，但不能把 0.9 解释成纳摩尔亲和力。

### 19.3 对高度相似变体不够敏感

论文讨论中提到，对少数高度相似 nanobody 变体，模型可能无法捕捉细小框架突变导致的 CDR 构象差异。这对我们的 affinity maturation / CDR 微突变筛选也要小心。

### 19.4 正负标签仍然有构造偏差

负样本是结构重组得到的 presumed non-binder，不是全部实验阴性。模型可能学到“重组结构的特征”而不完全是生物学 non-binding 的全部规律。

### 19.5 不含 blocker 标签

这是对 PVRIG 项目最大的不足。一个结构合理的 VHH-PVRIG binder 仍然可能不阻断 PVRIG-PVRL2。

## 20. 我们应该如何实际使用它

我建议把 NanoBinder 作为我们 PVRIG pipeline 的结构评分底座：

```text
第一阶段：sequence ensemble 找可能 binder
第二阶段：VHH-PVRIG docking
第三阶段：NanoBinder-style Rosetta feature score 过滤不合理 pose
第四阶段：PVRIG-PVRL2 interface/blocking score 做最终功能排序
第五阶段：实验回流训练 PVRIG-specific blocker classifier
```

最实用的落地方式：

```text
先不急着完整复现原始 NanoBinder 训练集
先照搬它的 26 个 Rosetta features
对我们自己的 VHH-PVRIG poses 做批量特征提取
用 NanoBinder 思路训练/规则化一个结构评分器
再额外加入 PVRIG-PVRL2 interface overlap 特征
```

## 21. 结论

NanoBinder 对我们非常重要，因为它把问题从“序列是否像 binder”推进到“结构 pose 是否像真实 nanobody-antigen complex”。

它最适合用于：

```text
1. VHH-PVRIG docking pose 过滤
2. Rosetta interface energy 结构评分
3. binder/non-binder 结构层面判断
4. 与 PVRIG-PVRL2 interface overlap 联合做 blocker 排序
```

它不适合单独用于：

```text
1. 从纯序列直接预测 binder
2. 输出 Kd
3. 判断 PVRIG-PVRL2 阻断
4. 最终实验候选唯一排序依据
```

如果迁移到我们的课题，最关键的改造是：

```text
NanoBinder-style binding pose probability
  + PVRIG-PVRL2 functional interface overlap
  + binder-but-non-blocker hard negative
  = PVRIG-specific blocker scoring model
```

这比单纯调用 NanoBinder 原模型更符合我们的目标。

