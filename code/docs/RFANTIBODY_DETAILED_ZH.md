# RFantibody 详细原理、训练数据与 PVRIG 阻断型 VHH 复现说明

生成日期：2026-07-12  
工作目录：`/mnt/d/work/抗体/code`  
论文：*Atomically accurate de novo design of antibodies with RFdiffusion*  
论文 DOI：<https://doi.org/10.1038/s41586-025-09721-5>  
代码：<https://github.com/RosettaCommons/RFantibody>  
训练表：<https://doi.org/10.5281/zenodo.15741710>  
本次核验的代码版本：`8fe311415754e0276d1a39c87c57e69c88927a2d`

本文档重点解释 RFantibody 到底解决什么问题、三段模型如何衔接、训练数据如何构造、公开数据能否用于自建模型、实际输入输出是什么，以及怎样把它改造成 PVRIG-PVRL2 阻断型 VHH 的候选生成模块。

---

## 0. 结论先行

RFantibody 不是一个“给定 VHH 和抗原，判断是否结合”的分类模型。它是一个结构条件化的 **de novo 抗体/纳米抗体设计流水线**：

```text
抗原三维结构 + VHH framework + 目标表位热点 + CDR 长度范围
                            |
                            v
RFdiffusion：生成 CDR 主链、VHH 相对抗原的结合姿态
                            |
                            v
ProteinMPNN：为生成的 CDR 主链设计氨基酸序列
                            |
                            v
抗体微调版 RF2：重新预测复合物并检查结构自洽性
                            |
                            v
候选 VHH 序列 + 复合物 pose + pAE/pLDDT/RMSD 等过滤指标
```

它最适合回答：

```text
能否从一个成熟 VHH 骨架出发，生成一批可能在指定 PVRIG 表位上结合的全新 CDR 和复合物姿态？
```

它不能单独可靠回答：

```text
这个设计的 Kd 是多少？
这个设计一定能结合吗？
这个设计是否一定阻断 PVRIG-PVRL2？
这个设计在细胞功能实验中是否有效？
```

对本比赛最重要的定位是：

> RFantibody 应作为“指定 PVRIG-PVRL2 界面生成 VHH 候选”的前端生成器，而不是最终 blocker 排序器。最终排序必须额外加入 PVRL2 空间遮挡、界面重叠、复合物稳定性、糖基化冲突和可开发性等评分。

---

## 1. RFantibody 与 DeepNano/NABP-BERT 的本质区别

前面讨论的 DeepNano、NABP-BERT 等模型主要是判别式模型：

```text
输入：已有 VHH 序列 + 抗原序列
输出：是否可能结合 / 结合概率样式的分数
```

RFantibody 是生成式结构设计模型：

```text
输入：抗原结构 + 固定 VHH framework + 希望接触的抗原热点
输出：新的 CDR 几何、新的 CDR 序列、VHH-抗原复合物 pose
```

因此二者不互相替代，而是可以串联：

```text
RFantibody 生成候选
  -> RF2/AF3/Boltz/tFold 复合物复核
  -> DeepNano/NABP-BERT 作为 sequence-only 辅助先验
  -> PVRIG-PVRL2 blocker 几何评分
  -> 实验验证
```

RFantibody 的关键优势不是“更准确地预测结合概率”，而是它允许在设计时显式指定抗原表位。对于本项目，这意味着可以把生成区域引导到 PVRIG-PVRL2 界面，而不是在 PVRIG 全表面随机寻找 binder。

---

## 2. 论文、代码、权重和本地状态

### 2.1 论文与开放资产

| 资产 | 状态 | 说明 |
|---|---|---|
| Nature 论文 | 公开 | 描述模型、实验命中和结构验证 |
| Supplementary Information | 公开 | 训练数据、负样本、loss 和训练超参数的主要来源 |
| GitHub 代码 | 公开，MIT License | 包含三段推理和 Quiver 工具 |
| RFdiffusion 权重 | 公开下载 | 抗体微调的扩散模型 |
| ProteinMPNN 权重 | 公开下载 | 基础 ProteinMPNN，不是抗体专用重训版 |
| RF2 权重 | 公开下载 | 抗体复合物微调版本 |
| SAbDab 派生训练表 | 公开，CC BY 4.0 | Zenodo 上的 `AntibodyTrainingDataset.csv` |
| TCR 训练数据 | 方法可描述 | 未以同一完整训练包发布 |
| loop-mediated PDB 训练集 | 构建规则可描述 | 未发布成开箱即用的完整处理包 |
| 1.6M miniprotein binder 数据 | 非公开 in-house 数据 | 完整复训 RF2 的主要缺口 |

所以，“运行官方权重进行设计”是可复现的；“从零严格重训出完全相同的 RFdiffusion 和 RF2 权重”目前并不完全可复现。当前 GitHub 主要提供推理流水线、模型定义和测试，并没有一个配齐全部数据处理与采样状态的开箱即用端到端训练入口。

### 2.2 本地公开训练表

已下载：

```text
downloaded_models/RFantibody-data/AntibodyTrainingDataset.csv
downloaded_models/RFantibody-data/zenodo_15741710_metadata.json
downloaded_models/RFantibody-data/DATASET_AUDIT.json
downloaded_models/RFantibody-data/SOURCE.md
```

原始 CSV 校验：

```text
大小：8,516,238 bytes
MD5：e2eb7b90e3733e0ac9247dd53857c5aa
许可：CC BY 4.0
来源：modified from SAbDab
```

### 2.3 node1 已部署状态

本项目的 node1 已经完成三段部署和 smoke test：

```text
源码：/data/qlyu/software/RFantibody
权重：/data/qlyu/software/RFantibody/weights
环境：/data/qlyu/anaconda3/envs/rfdiffusion2
包装命令：
  /data/qlyu/software/RFantibody/bin/rfdiffusion
  /data/qlyu/software/RFantibody/bin/proteinmpnn
  /data/qlyu/software/RFantibody/bin/rf2
```

三份主权重的本地检查结果：

| 权重 | 文件大小 | MD5 | state 条目 | 参数量 |
|---|---:|---|---:|---:|
| `RFdiffusion_Ab.pt` | 483,452,922 bytes | `5614b1fc623b9cbc7e18190d0c2dc131` | 5,998 | 59,808,302 |
| `ProteinMPNN_v48_noise_0.2.pt` | 6,681,301 bytes | `91d54c97a68bf551114f8c74c785e90f` | 118 | 1,660,485 |
| `RF2_ab.pt` | 294,759,918 bytes | `7c230a10e6e5243aea81c32b8ed40193` | 8,044 | 72,899,168 |

部署细节和已通过的命令见：

```text
../node1/RFANTIBODY_NODE1_DEPLOYMENT.md
```

---

## 3. 三阶段模型总体流程

### 3.1 第一阶段：抗体微调版 RFdiffusion

这一阶段决定两件最核心的事：

1. VHH 的 CDR 主链长什么样；
2. 整个 VHH 以什么方向、什么位置贴到抗原上。

它不是简单地从已有 CDR 库中挑环，而是在三维空间中通过扩散去噪生成新的 CDR 主链和刚体结合姿态。VHH 的 framework 可以固定，目标抗原结构也作为条件提供，模型主要生成被指定为可设计的 CDR 区域。

### 3.2 第二阶段：ProteinMPNN

RFdiffusion 先给出“几何骨架”，但主链几何还需要匹配的氨基酸序列。ProteinMPNN 根据局部三维环境为 CDR 位点设计序列：

```text
输入：RFdiffusion 生成的 VHH-PVRIG 主链结构
固定：VHH framework 序列
设计：H1/H2/H3 或用户指定的部分 CDR
输出：每个 backbone 对应的一条或多条 CDR 序列
```

官方使用的是基础版 ProteinMPNN，并没有再训练一个专门的 antibody ProteinMPNN。抗体约束主要来自 RFdiffusion 生成的 CDR 几何，以及 wrapper 只允许 ProteinMPNN 改写 CDR。

### 3.3 第三阶段：抗体微调版 RoseTTAFold2

RF2 不直接相信设计 pose，而是拿“设计出来的序列 + 已知抗原结构”重新预测复合物：

```text
如果 RF2 在不知道原始设计坐标细节的情况下，仍然预测出相近 pose，
并且界面 pAE 较低，说明这个 sequence-backbone-interface 组合更自洽。
```

这通常称为 self-consistency filtering。它能减少明显不稳定或序列与结构不匹配的设计，但不能保证实验结合。

---

## 4. 第一阶段 RFdiffusion 的原理

### 4.1 扩散模型到底在“扩散”什么

普通图像扩散模型从噪声图像逐步恢复图像。RFdiffusion 对蛋白质残基的三维框架进行类似操作：

```text
真实蛋白结构
  -> 在残基平移与旋转框架上逐步加噪
  -> 网络学习每一步如何去噪
  -> 推理时从噪声开始生成新的三维主链
```

RFantibody 并不把整个系统都随机生成：

- 抗原 target 的主链结构作为条件固定；
- VHH 非 CDR framework 通过 template 特征固定；
- 被指定的 CDR 区域被生成；
- VHH 相对抗原的 rigid-body orientation 同时被生成；
- hotspot 特征告诉模型希望靠近抗原的哪些残基。

因此它做的是“带 framework 和 epitope 条件的 CDR/dock 共生成”。

训练和模型输入设计中，target backbone 与 sequence 被提供，但 target sidechain 坐标不作为显式固定条件。这意味着 `F139/W144` 这样的芳香 hotspot 能通过残基身份和主链位置提供语义，但其真实侧链 rotamer 与精细 packing 仍需要 RF2、Rosetta 或其他 all-atom 方法重新检查，不能把 RFdiffusion 输出直接当成原子级能量最优界面。

### 4.2 framework 为什么重要

RFantibody 不是从一条完全空白的蛋白链开始设计。用户提供一个成熟抗体或 VHH framework：

```text
framework 区域：结构和序列保留
CDR 区域：按设定的长度范围重新生成
```

论文的 VHH 设计使用人源化 `h-NbBCII10`/`h-NbBcII10FGLA` scaffold。这样做的好处是：

- 保留已知可表达、可折叠的主体框架；
- 把生成自由度集中在真正负责识别的 CDR；
- 减少完全 de novo 生成整个 VHH 的难度；
- 后续可把比赛已有优质 scaffold 作为新的 framework。

但是 framework 不是完全“与结合无关”。官方 README 明确指出，VHH 常出现 side-on dock，并可能有 framework-mediated contact。这是自然 VHH 训练分布的一部分，而不一定是错误。

### 4.3 hotspot 如何发挥作用

训练时，若一个抗原残基与最近 5 个抗体 CDR 残基的平均 Cβ 距离小于 8 Å，就被定义为真实 hotspot。模型训练时只随机展示真实 hotspot 的 0%-100%，因此它学习在部分表位提示下生成界面。

热点不是以下概念：

```text
不是实验 alanine scanning 得到的能量 hotspot；
不是保证必须形成某一条氢键的硬约束；
不是 blocker 标签；
不是 Kd 贡献的定量估计。
```

它更接近：

```text
“请尽量让生成的 CDR 界面出现在这些抗原残基附近。”
```

RFantibody 比原始 RFdiffusion 对 hotspot 组合更敏感。热点给得不好时，常见结果不是生成一个稍差的 binder，而是生成未对接、姿态异常或热点覆盖很差的 VHH。因此正式生成几千条之前必须做小规模 pilot。

### 4.4 CDR 长度如何控制

示例：

```text
H1:7,H2:6,H3:5-13
```

含义：

- H1 固定设计为 7 个残基；
- H2 固定设计为 6 个残基；
- H3 在 5-13 个残基之间均匀采样；
- 每条 CDR 的长度独立采样；
- framework 中存在但没有列出的 CDR 保持不变。

较长 H3 能进入沟槽或凹口，但也更难准确设计和预测。PVRIG 的目标是遮挡较平坦的蛋白-蛋白界面，第一轮不应盲目使用特别长 H3；官方 VHH 范围可以作为起点，再根据 pose 分布调整。

---

## 5. 第二阶段 ProteinMPNN 的原理

### 5.1 为什么 RFdiffusion 后还要 ProteinMPNN

RFdiffusion 的主要任务是生成主链和 dock。ProteinMPNN 的任务是寻找与该主链环境相容的氨基酸：

```text
每个残基看到邻近原子的几何环境
  -> 图神经网络编码邻域
  -> 自回归/条件采样氨基酸
  -> 得到与主链和界面更匹配的序列
```

同一 backbone 可以采样多条序列，例如：

```text
1,000 backbones x 4 sequences/backbone = 4,000 sequence-pose candidates
```

论文部分 retrospective 统计还比较了每个 backbone 的 8 条 MPNN 序列，并取过滤指标最好的序列。这说明“一个 backbone 只采一条序列”会丢失大量序列空间。

### 5.2 temperature 的意义

较低 temperature：

- 更偏向 ProteinMPNN 高概率氨基酸；
- 序列更保守；
- 多样性较低。

较高 temperature：

- 序列多样性更大；
- 也更容易采到不稳定或不自然序列。

官方完整示例使用 `0.2`，smoke test 使用 `0.1`。PVRIG pilot 可先用 `0.1-0.2`，不要一开始追求非常高的序列多样性。

### 5.3 它没有学会什么

基础 ProteinMPNN 并没有直接学习：

- PVRIG-PVRL2 是否阻断；
- VHH 的体内免疫原性；
- 精确 Kd；
- CDR 特异的实验 developability；
- 糖基化目标附近的真实构象熵代价。

所以必须在 ProteinMPNN 后进行结构复核和可开发性过滤。

---

## 6. 第三阶段 RF2 的原理与输出

### 6.1 RF2 在这里做什么

抗体微调版 RF2 接收：

```text
VHH/抗体序列
已知 target 结构
可选 hotspot mask
可选 framework/template 信息
```

RF2 的核心仍是 1D MSA/sequence、2D residue-pair 和 3D structure 三条信息轨道之间反复交换信息。针对抗体设计，作者加入或修改了：

- target 结构条件；
- hotspot 一维特征；
- antibody/TCR/loop-interface 数据微调；
- 结合/不结合负样本；
- 独立更新的 pBind head；
- 抗体复合物结构和置信度学习。

### 6.2 self-consistency 的含义

假设 RFdiffusion 设计 pose 为 A，RF2 从序列重新预测 pose 为 B：

- A 与 B 接近：序列较可能支持设计几何；
- A 与 B 差异很大：设计 backbone、序列和界面可能不自洽；
- RF2 对界面给出高 pAE：模型自己对相对链定位没有信心。

因此最基本的筛选是：

```text
interaction pAE < 10
设计结构与 RF2 重预测结构的 RMSD < 2 Å
```

论文作者也指出 Rosetta interface ddG `< -20` 可能有帮助，但不是经过所有靶点证明的硬阈值。

### 6.3 当前命令实际输出的主要指标

当前 GitHub 主分支 wrapper 会在 PDB/Quiver metadata 中整理：

- `interaction_pae`：跨链 residue-pair 的平均预测对齐误差；越低通常越好；
- `pred_lddt`：每残基及均值的局部结构置信；越高通常越好；
- `target_aligned_antibody_rmsd`：先对齐 target 后，抗体相对设计的 RMSD；
- `target_aligned_cdr_rmsd`：先对齐 target 后，CDR 的 RMSD；
- `framework_aligned_antibody_rmsd`；
- `framework_aligned_cdr_rmsd`；
- 各单独 CDR 的 framework-aligned RMSD。

这些值可以用 `qvscorefile` 从 Quiver 文件提取成表格。

### 6.4 关于 pBind 的重要代码事实

RF2 网络内部确实计算 `p_bind`，训练时也有 `Lbind`。但是当前主分支的 `model_runner.py` 虽然接收了 `p_bind`，却没有把它加入 `_process_output()` 返回的常规 metrics。

因此：

> 当前标准 RFantibody CLI/Quiver 输出不能被描述为“已经提供 pBind 分数”。默认可直接使用的是 pAE、pLDDT 和 RMSD 等指标。如果需要 pBind，必须小幅修改 wrapper，把 `output_i["p_bind"]` 明确写入 metrics，并验证数值维度和 checkpoint 兼容性。

即使导出 pBind，它仍然只是训练分布下的结合分类置信，不是 Kd，也不是 PVRIG-PVRL2 阻断概率。

### 6.5 三阶段实际文件输出

| 阶段 | PDB 目录模式 | Quiver 模式 | 主要内容 |
|---|---|---|---|
| RFdiffusion | `*_0.pdb`、相应 `*.trb` | `1_rfdiffusion.qv` | 生成的 CDR backbone、VHH-target dock、热点/生成 metadata |
| ProteinMPNN | `*_dldesign_0.pdb` 等 | `2_proteinmpnn.qv` | 保持结构索引的设计序列和 pose |
| RF2 | `*_best.pdb` 等 | `3_rf2.qv` | 重预测复合物、pLDDT/pAE/RMSD metadata |
| `qvscorefile` | `.sc` | 从 `.qv` 自动生成 `.sc` | 每个 tag 一行的评分表 |

RF2 wrapper 在多个 recycle 中通常保留平均 pLDDT 最好的结果；这不表示该 recycle 一定有最正确的链间 pose，所以仍要结合 `interaction_pae` 和 target-aligned RMSD，而不能只读取文件名中的 `best`。

---

## 7. 训练数据详解

这一节是自建 AI 模型时最值得借鉴、也最容易误解的部分。

### 7.1 数据集并不是单一 SAbDab 表

RFantibody 的两个微调模型使用了四类信息源：

```text
1. SAbDab 抗体/纳米抗体结构
2. TCR-pMHC 结构
3. PDB 中 loop-mediated protein-protein interfaces
4. 1.6M in-house miniprotein binder/nonbinder 实验标签，仅用于 RF2 第二阶段
```

前三类用于扩大“由 loop 主导的分子识别”结构分布；第四类主要用于增强 RF2 对实验 binder/nonbinder 的区分。

### 7.2 SAbDab 抗体结构集

补充材料给出的构建规则：

- 数据来源：SAbDab；
- 结构发布日期早于 2023-01-13；
- X-ray 或 cryo-EM；
- 分辨率 `< 5 Å`；
- CDR 按 Chothia 编号定义；
- 将各 CDR 序列拼接后，用 MMseqs2 在 70% sequence similarity 聚类；
- 按 cluster 做 90:10 train:test 划分；
- 2,235 个 train clusters；
- 245 个 test clusters；
- 6,205 个总 PDB structures；
- 其中 4,936 个结构含 antigen；
- 一个 PDB 中若有多个抗体 copy，可以作为多个训练条目被采样。

这里的核心是 **按 CDR cluster 划分，而不是随机按行划分**。如果同一或高度相似 CDR 出现在 train 和 validation，模型会因为序列近重复而得到虚高结果。

### 7.3 最终结构验证集与 CSV 的 validation flag 不是一回事

论文另外构建了两个更严格的 final validation set：

1. 2023-01-13 之后发布，且 target 与训练 target 的 sequence similarity `<30%`；
2. 原 test set 中再次验证 target 与训练 target similarity `<30%`。

每个 cluster 只取一个结构，并把 target 长度限制为 100-500 aa，最终分别是：

```text
104 structures
47 structures
```

公开 CSV 中的 `validation_set=True` 有 1,125 行，它代表发布表中的 cluster split 标记，不能直接等同于论文所说的 104 + 47 个严格 final validation structures。

### 7.4 公开 CSV 的本地审计结果

`AntibodyTrainingDataset.csv` 不是“11,777 个独立、实验确认的抗体-抗原互作”。本地逐行审计结果如下：

| 项目 | 数量 |
|---|---:|
| 总行数 | 11,777 |
| 唯一 PDB | 6,205 |
| 唯一 antibody cluster | 2,480 |
| 非空 target cluster | 1,320 |
| `negative_example=False` | 5,920 |
| `negative_example=True` | 5,857 |
| `validation_set=False` | 10,652 |
| `validation_set=True` | 1,125 |
| heavy+light (`HL`) | 9,301 |
| heavy-only (`H`) | 2,085 |
| light-only (`L`) | 391 |
| 有 target sequence | 8,314 |
| 无 target sequence | 3,463 |
| 数值 affinity 行 | 1,263 |
| 含数值 affinity 的唯一 PDB | 709 |
| X-ray 行 | 9,259 |
| EM 行 | 2,507 |
| 最早结构日期 | 1976-03-17 |
| 最晚结构日期 | 2023-01-11 |

这张表包含：

- 同一 PDB 内的重复 copy；
- 同一结构的不同 antibody/target 组合；
- 构造负样本；
- heavy-only 和 light-only 条目；
- 没有蛋白 target sequence 的条目；
- 少量 affinity 信息；
- 聚类和 split 信息。

### 7.5 CSV 中最值得保留的字段

自建数据管线时，至少保留：

```text
pdb
Hchain / Lchain / antigen_chain
ab_chains
cdr_seq / cdr_len
target_seq
ab_cluster / target_cluster
negative_example / negative_item
validation_set
date
resolution / method
affinity / delta_g / affinity_method / temperature
antigen_type / antigen_name / species
```

注意：CSV 本身主要是元数据和序列索引，不是已经打包好的所有三维原子坐标。若训练结构模型，还需要按 PDB ID 下载结构、处理 biological assembly、选择正确链、统一编号、解析缺失残基并重建 contact map。

### 7.6 能否把 `ab_chains=H` 直接当成 VHH

不能无条件这样做。

`ab_chains=H` 是 heavy-only 条目，确实富集 camelid VHH 或其他单域重链，但还需要结合：

- heavy species；
- antibody subtype/annotation；
- 是否 scFv；
- 链长和保守位点；
- 是否存在配对轻链但表中缺失；
- ANARCI/IgBLAST 的 V-domain 识别；
- VHH hallmark residues。

如果要构造高质量 VHH 子集，推荐把 `ab_chains=H` 作为候选筛选条件，而不是最终标签。

### 7.7 CSV 中的负样本是什么

RF2 训练中负样本以 50% 概率动态采样，主要有三类：

#### A. 错配 antibody-target

对一个正样本 target，换入另一个 antibody：

- replacement antibody 来自不同的 `<70% CDR similarity` cluster；
- 保持 train/test partition 不跨界；
- replacement antibody 原始 antigen 与当前 antigen 的 similarity `<20%`；
- 仅从原结构中确实有 antigen 的 antibody 采样。

这种负样本是“高概率不结合”，但不是实验确认 nonbinder。一个抗体理论上仍可能偶然交叉反应。

#### B. CDR swap

把关键 CDR 换成：

- 相同长度；
- 与原 loop sequence identity `<40%`；
- 来自同一 train/test partition。

抗体主要替换 H3，TCR 替换 alpha3 + beta3。作者假设这种替换通常会破坏结合。

#### C. 实验 miniprotein binder/nonbinder

作者还使用 41 个 target、共 1.6M 个 de novo miniprotein designs 的 yeast surface display 标签。这里有真实实验 binder/nonbinder 监督，但该数据是 in-house 数据，没有随 Zenodo 抗体 CSV 完整公开。

### 7.8 TCR-pMHC 数据

该数据的目的不是让 RFantibody 设计 TCR，而是补充“由多个可变 loop 识别 target”的结构规律：

- 129 个 crystal structures；
- 2,574 个 AF2-predicted structures；
- 39 个 MHC subtype clusters；
- 35 train clusters；
- 4 test clusters；
- test 只使用晶体结构，相关 AF2 models 不进入训练。

这是一种结构蒸馏和跨体系增广。它能增加 loop-interface 样本，但也意味着模型不完全只学习天然 antibody distribution。

### 7.9 loop-mediated PDB interface 数据

作者从 PDB 筛选普通蛋白复合物，要求：

- 异源二聚体；
- 排除 SAbDab 结构；
- X-ray/cryo-EM 分辨率 `<5 Å`；
- 接口残基定义为两链 Cα 距离 `<10 Å`；
- 一侧接口中 `>70%` interacting residues 位于 loop；
- interacting loops 总长度 `>10 residues`；
- 两条链都要相对结构化，非 loop 二级结构比例 `>40%`；
- loop-interface 一侧定义为 binder；
- binder 长度 `<=250 residues`；
- 以 30% sequence similarity 聚类；
- 2,010 train clusters；
- 254 test clusters；
- 共 18,767 个 heterodimeric complexes。

这个数据集非常值得自建模型借鉴：抗体结构数量有限时，可以加入“界面由 loop 主导”的普通蛋白复合物，预训练模型学习 loop-mediated recognition，再回到 VHH 数据微调。

但它不是抗体数据，不能让这部分样本在最终 VHH 专用微调中占比过高，否则可能降低对 VHH framework、CDR 拓扑和抗体可开发性的特异性。

### 7.10 对完整复训开放性的判断

可以严格复现的部分：

- 当前代码和推理流程；
- 三份主要推理权重；
- SAbDab 派生 CSV；
- 论文描述的主要数据构建规则；
- 官方示例和筛选阈值；
- 用公开 PDB/SAbDab 重新构造近似结构集。

不能严格一比一复现的部分：

- 原作者的完整 preprocessing snapshot；
- 所有 TCR 和 loop-mediated 样本的最终处理后张量；
- 1.6M in-house miniprotein 实验标签；
- 训练采样中每一步随机状态与内部工程细节；
- 与作者完全相同的训练硬件和软件快照。

因此合理目标是：

```text
优先复现官方推理；
若要训练自有模型，借鉴数据设计和多任务目标，
而不是声称能够从公开资产精确重训同一个 RFantibody。
```

---

## 8. RFdiffusion 的训练方法

### 8.1 训练混合比例

```text
50% SAbDab antibody examples
10% TCR-pMHC examples
40% loop-mediated PDB interfaces
```

训练时：

- 有 target 的样本：target backbone 和 target sequence 提供给模型，但不提供 target sidechain；
- binder/antibody/TCR/loop-interface 一侧加噪并去噪；
- antibody/TCR 的非 CDR framework 作为 template 固定；
- 无 resolved target 的 antibody 样本会对整个 antibody 加噪，用于学习抗体单体几何。

### 8.2 训练 loss

三项 loss 权重都是 1.0：

| Loss | 作用 | 权重 |
|---|---|---:|
| `LFrame` | 残基 frame 的 MSE | 1.0 |
| `L2D` | residue-pair distogram | 1.0 |
| `LMLM` | masked sequence categorical cross-entropy | 1.0 |

模型使用 sequence self-conditioning：前一步对序列/结构的预测可以作为下一步的条件，帮助生成结构和序列特征保持一致。

### 8.3 训练超参数

```text
初始化：vanilla RFdiffusion sequence self-conditioning 版本
crop size：768
pseudo-batch size：16
epochs：70
examples per epoch：512
学习率：前 100 gradient steps 从 0 warmup 到 0.0005
硬件：2 x NVIDIA A100 80 GB
时间：约 3 天
```

补充材料明确指出，crop size 768 的训练需要 80 GB GPU。这里的“2 张 A100、约 3 天”是作者训练报告，不代表推理也需要同样硬件。推理单卡显存需求取决于 target 长度、总残基数、并发和输出规模。

---

## 9. RF2 的训练方法

### 9.1 第一阶段微调

```text
45% SAbDab
10% TCR
45% loop-mediated PDB interfaces
```

训练设置：

```text
negative probability：50%
pseudo-batch size：64
初始学习率：0.001
每 10,000 optimizer steps 乘 0.95
epochs：400
examples per epoch：512
硬件：8 x NVIDIA L40S
时间：约 7 天
```

### 9.2 第二阶段微调

从第一阶段权重继续：

```text
45% SAbDab
10% TCR
10% loop-mediated PDB interfaces
35% 1.6M miniprotein binder/nonbinder data
```

训练设置：

```text
pseudo-batch size：32
epochs：207
examples per epoch：512
硬件：4 x NVIDIA L40S
时间：约 3 天
其余设置基本沿用第一阶段
```

### 9.3 RF2 loss

| Loss | 含义 | 权重 |
|---|---|---:|
| `Ldist` | distogram | 1.0 |
| `LFAPE` | backbone/all-atom FAPE | 10.0 |
| `LpLDDT` | pLDDT accuracy estimation | 1.0 |
| `Lbond` | bond geometry | 0.02 |
| `LvdW` | Rosetta Lennard-Jones 风格的 van der Waals | 0.02 |
| `LMLM` | masked language modelling | 3.0 |
| `LpAE` | predicted aligned error | 0.01 |
| `Lbind` | positive/negative binding classification | 1.0 |

对正样本，结构 loss 可作用于整个复合物。对错配负样本，由于没有“正确的复合物刚体方向”，结构 loss 只在 binder 和 target 各自内部计算，不对跨链相对 pose 施加正结构监督。对 CDR-swap 负样本，被替换 loop 上也不施加虚假的真实结构监督。

这一设计非常值得自建 pair model 借鉴：

> “不结合”不等于两条单体结构是错的；负样本 loss 应主要惩罚跨链结合判断，而不是破坏各自单体结构。

### 9.4 RF2 训练时的空间裁剪

显存限制下，作者对不同数据采用不同裁剪：

- antibody heavy chain 按 Chothia 编号从开头裁到随机的 105-115 左右，近似保留 VH；
- light chain 从开头裁到随机的 100-110 左右，近似保留 VL；
- VHH 使用同样的 heavy-variable-domain 裁剪逻辑；
- antigen 以随机真实 hotspot 为中心做空间裁剪；
- 抗体样本的总最大长度通常设为 384；
- TCR-pMHC 预处理后总长最多约 436，不再额外裁剪；
- loop-mediated binder 因预先限制为 `<=250 aa` 而不裁 binder，只空间裁 target。

这一点解释了为什么 PVRIG 这种小 IgV target 没必要继续截得很碎：完整 ECD 已足够短，保留整体表面反而更有利于学习真实接近方向和排除不可能的 dock。

---

## 10. 模型输入格式

### 10.1 target structure

RFdiffusion 需要抗原 PDB，而不是只有 FASTA。对于本项目，输入应是 PVRIG extracellular IgV domain 的结构。

不建议：

- 输入全长 PVRIG 的跨膜和胞内区域；
- 把 PVRL2 一起保留为 target 后再期待模型自动理解“需要竞争”；
- 使用编号混乱、缺失严重或包含无关复合物链的 PDB；
- 没有核对 hotspot residue 编号就直接运行。

### 10.2 HLT framework format

RFantibody 使用 HLT 格式在各阶段传递链和 CDR 信息。它本质上仍是 PDB，但要求：

```text
Heavy chain：H
Light chain：L
Target chain：T
链顺序：Heavy -> Light -> Target
CDR：在 PDB 末尾用 REMARK PDBinfo-LABEL 标记绝对残基索引
```

VHH 没有 L 链，只需要 H framework 和 T target。官方提供：

```text
scripts/examples/example_inputs/h-NbBCII10.pdb
```

若使用自己的 scaffold，应先做 Chothia 编号并转换为 HLT。当前代码仓库中的实际工具名和 VHH 示例命令是：

```bash
python scripts/util/chothia2HLT.py mychothia.pdb \
  --heavy H \
  --output myHLT.pdb
```

如果输入 PDB 的重链不是 H，应把 `--heavy H` 换成实际链名；若一次转换完整复合物，还可以增加 `--light <chain>` 和 `--target <chain>`。官方 README 截至本次核验仍写作不存在的 `chothia_to_HLT.py` 和旧参数形式，应以代码中的 `scripts/util/chothia2HLT.py --help` 为准。

### 10.3 hotspot 编号

hotspot 采用：

```text
<chain id><PDB residue number>
```

例如：

```text
T57,T101,T106
```

这里是输入 PDB 的实际 residue number，不是 UniProt position，也不是 CSV 行号。PVRIG 原始 8X6B chain B 改名为 T 后：

```text
UniProt R95  -> 8X6B B57  -> RFantibody T57
UniProt W100 -> 8X6B B62  -> RFantibody T62
UniProt K135 -> 8X6B B97  -> RFantibody T97
UniProt F139 -> 8X6B B101 -> RFantibody T101
UniProt S143 -> 8X6B B105 -> RFantibody T105
UniProt W144 -> 8X6B B106 -> RFantibody T106
```

编号映射必须保留在 manifest 中，不能只在命令行手工记忆。

---

## 11. 标准使用方法

### 11.1 官方安装

官方当前推荐 Linux、NVIDIA GPU、CUDA 11.8+，并使用 Python 3.10/uv：

```bash
git clone https://github.com/RosettaCommons/RFantibody.git
cd RFantibody
bash include/download_weights.sh
uv sync
source .venv/bin/activate
rfdiffusion --help
```

权重下载脚本当前会下载：

```text
RFdiffusion_Ab.pt
ProteinMPNN_v48_noise_0.2.pt
RF2_ab.pt
RFab_noframework-nosidechains-5-10-23_trainingparamsadded.pt
```

脚本本身使用 `wget` 且检测到 `weights/` 已存在时会整体跳过，不适合不稳定网络下精细断点续传。若重新部署，应优先对每个 URL 使用 `aria2c -c` 或 `curl -C -`，并在结束后校验 MD5/文件大小。

### 11.2 三段完整示例

```bash
# 1. 生成 backbone 和 dock
rfdiffusion \
  --target target.pdb \
  --framework h-NbBCII10.pdb \
  --output-quiver 1_rfdiffusion.qv \
  --num-designs 1000 \
  --design-loops "H1:7,H2:6,H3:5-13" \
  --hotspots "T57,T101,T106"

# 2. 为每个 backbone 采样多条 CDR 序列
proteinmpnn \
  --input-quiver 1_rfdiffusion.qv \
  --output-quiver 2_proteinmpnn.qv \
  --loops "H1,H2,H3" \
  --seqs-per-struct 4 \
  --temperature 0.2

# 3. RF2 重新预测复合物并输出 self-consistency 指标
rf2 \
  --input-quiver 2_proteinmpnn.qv \
  --output-quiver 3_rf2.qv \
  --num-recycles 10

# 4. 提取评分和最终结构
qvscorefile 1_rfdiffusion.qv
qvscorefile 3_rf2.qv
qvextract 3_rf2.qv -o final_designs/
```

当前主分支的 `qvscorefile` 会自动把结果写到同名 `.sc` 文件，而不是把 TSV 内容输出到标准输出。例如，输入 `3_rf2.qv` 会生成 `3_rf2.sc`。

### 11.3 Quiver 的意义

如果生成 1,000 backbones，每个采 4 条序列，就有 4,000 个结构。直接保存成几千个小 PDB 会给文件系统和后续扫描造成压力。Quiver `.qv` 把多个结构、tag 和 score metadata 打包到一个文件中。

常用命令：

```bash
qvls designs.qv
qvls designs.qv | wc -l
qvscorefile designs.qv  # 自动生成 designs.sc
qvextract designs.qv -o pdbs/
qvls designs.qv | shuf | head -n 20 | qvextractspecific designs.qv
qvsplit designs.qv 100 -o chunks/
```

这对断点执行也很重要：三个阶段分别保存 Quiver，就可以从失败阶段重启，而不必重新运行 RFdiffusion。

---

## 12. 论文的实验结果应如何理解

### 12.1 VHH 实验命中率

| Target | 筛选数量 | SPR 确认 binder | 命中率 |
|---|---:|---:|---:|
| TcdB | 96 | 2 | 2% |
| IL7R | 96 | 0 | 0% |
| H1 stem，小规模 | 96 | 1 | 1% |
| H1 stem，大规模 | 9,000 | 20 | 0.2% |
| SARS-CoV-2 RBD | 9,000 | 5 | 0.06% |
| RSV site III | 9,000 | 1 | 0.01% |

论文正文有时把低通量描述为 95 designs，补充表按实际统计列为 96；理解上应视为约 95-96 条的小规模 plate-level campaign，而不要把这一条差异当成模型性能结论。

### 12.2 初始亲和力

代表性初始设计：

```text
Influenza HA：78 nM
TcdB：约 260-262 nM
SARS-CoV-2 RBD：5.5 uM
RSV site III：1.4 uM
```

这说明 RFantibody 可以直接产生可测 binder，甚至出现 nM 级设计，但并不是所有靶点都能稳定达到高亲和力。部分设计随后用 OrthoRep 做实验亲和成熟，提升约 100-1,000 倍。

### 12.3 表位和功能验证

- RBD 设计与已知同表位 binder 竞争，支持指定表位结合；
- TcdB VHH 与指定表位 binder 竞争；
- TcdB VHH 在细胞体系中出现毒素中和；
- Influenza HA VHH 获得约 3.0 Å cryo-EM 复合物；
- 设计 VHH backbone 与实验结构约 1.45 Å RMSD；
- CDR3 约 0.8 Å RMSD。

这些结果很重要，因为它们证明 RFantibody 不只是 benchmark 上的结构模型，确实完成了 sequence synthesis -> expression -> binding -> competition/structure 的实验闭环。

### 12.4 不能忽略的现实

实验命中率仍为 0%-2%，多数大规模 campaign 需要约 10,000 条设计。作者明确把“缺少可靠 filter”视为当前主要限制。

RF2 过滤并没有在所有 target 上稳定区分 binder。论文 retrospective AF3 分析中 ipTM 对 VHH binder/nonbinder 的 AUC 为 0.86，但该结果由 influenza HA binder 数量主导，不能直接外推为所有新 target 都有 0.86 AUC。

因此不应把论文解读成：

```text
生成 100 条 -> RF2 排前 10 -> 必然得到 binder
```

更合理的解读是：

```text
它把“指定表位 de novo VHH 设计”从几乎不可行推进到了低命中率但可实验验证的阶段；
成功仍依赖生成规模、过滤质量和实验筛选能力。
```

---

## 13. PVRIG-PVRL2 项目的具体迁移方案

### 13.1 target 结构选择

本地已有：

```text
../data/structures/8X6B.pdb
../data/structures/9E6Y.pdb
```

建议第一轮以 8X6B 的 PVRIG chain B 为 target，提取 PVRIG extracellular IgV domain，并把链名改为 `T`。保留原始 PDB residue numbering，避免热点映射再次偏移。

可用下面的无第三方依赖脚本生成 protein-only target：

```bash
cd /mnt/d/work/抗体/code
mkdir -p prepared_inputs

python - <<'PY'
from pathlib import Path

src = Path('../data/structures/8X6B.pdb')
dst = Path('prepared_inputs/pvrig_8x6b_chainT.pdb')

out = []
for line in src.read_text().splitlines(keepends=True):
    if line.startswith('ATOM  ') and len(line) >= 22 and line[21] == 'B':
        out.append(line[:21] + 'T' + line[22:])

out.extend(['TER\n', 'END\n'])
dst.write_text(''.join(out))
print(dst, 'ATOM records:', sum(x.startswith('ATOM  ') for x in out))
PY

# 应只看到 target chain T；热点残基号仍应包含 57、62、97、101、105、106。
awk '/^ATOM/ {print substr($0,22,1), substr($0,23,4)}' \
  prepared_inputs/pvrig_8x6b_chainT.pdb | sort -u | head
```

该脚本故意只保留 `ATOM`，因此不会把 PVRL2、水和 NAG 放进 RFantibody target；原始含糖复合物仍必须保留给后续 blocker/glycan clash 复核。正式运行前还应检查 altloc、缺失残基和链终止是否符合当前 parser 预期。

8X6B 中 PVRIG chain B 的 NAG 与 ASN B91 相连。RFantibody 本身没有显式解决 glycan-aware design：

- 生成时可先使用 protein-only PVRIG；
- 但最终 pose 必须放回包含 NAG 的 8X6B/9E6Y 环境；
- 删除与糖链严重冲突的候选；
- 对糖链附近表位保守处理，因为真实 glycan 还有构象集合和熵效应。

PVRIG IgV domain 较小，不需要像大型病毒糖蛋白那样过度 crop。过度裁剪可能删除限制 VHH 接近方向的真实表面。

### 13.2 hotspot 不要一次给满 21 个界面残基

本地共识界面见：

```text
../data/structures/PVRIG_hotspot_set_v1.csv
```

RFantibody hotspot 是稀疏引导，而不是把整块界面全部列为硬约束。建议把 3-5 个 hotspot 组成多组独立 campaign。PVRIG 表面包含对生成较有利的芳香/疏水 anchor，例如 W100、F139、W144，以及 V90、A137、P140。

优先 pilot：

| Pilot | UniProt 语义 | 8X6B 改名 T 后的命令 | 目的 |
|---|---|---|---|
| A | R95/F139/W144 | `T57,T101,T106` | 中心带电点 + 两个芳香 anchor |
| B | W100/F139/W144 | `T62,T101,T106` | 更偏疏水/芳香核心 |
| C | K135/F139/S143/W144 | `T97,T101,T105,T106` | 覆盖 C-terminal interface patch |
| D | S71/T74/S143/W144 | `T33,T36,T105,T106` | 跨越两个界面片区，作为几何探索 |

这些组应分别运行，而不是合并成一个超长 hotspot list。比较：

- 成功 dock 比例；
- hotspot contact coverage；
- VHH 方向是否覆盖 PVRL2 footprint；
- RF2 self-consistency；
- 是否频繁与糖链或 PVRIG 主体冲突；
- 生成 pose 的聚类多样性。

### 13.3 推荐 pilot 规模

第一轮的目标不是直接找实验候选，而是判断 hotspot 和 CDR 参数是否能生成合理 dock：

```text
每个 hotspot set：50-100 backbones
每个 backbone：2-4 MPNN sequences
RF2：10 recycles
总计：4 组 x 50-100 x 2-4 = 400-1,600 sequence-pose candidates
```

pilot 通过后，再把最好的 1-2 组扩大到：

```text
每组 1,000-5,000 backbones
每 backbone 4-8 sequences
```

如果实验端最多只能合成 50-100 条，计算端仍应尽可能生成数千到数万条，再通过多级 filter 压缩。论文低命中率不支持“只生成 100 条然后完全相信 top score”。

### 13.4 node1 的 PVRIG pilot 命令模板

假设准备好：

```text
/data/qlyu/software/RFantibody/inputs/pvrig_8x6b_chainT.pdb
/data/qlyu/software/RFantibody/scripts/examples/example_inputs/h-NbBCII10.pdb
```

截至 2026-07-12，framework 已存在，但 node1 上的 `inputs/pvrig_8x6b_chainT.pdb` 还没有建立；所以下列命令是完成 PVRIG 链提取和编号核验后的可执行模板，不是已经跑完的 PVRIG 结果。

先运行小规模：

```bash
cd /data/qlyu/software/RFantibody

OUT=/data/qlyu/software/tests/pvrig_rfantibody_pilot/set_A
mkdir -p "$OUT"

CUDA_VISIBLE_DEVICES=0 bin/rfdiffusion \
  --target inputs/pvrig_8x6b_chainT.pdb \
  --framework scripts/examples/example_inputs/h-NbBCII10.pdb \
  --output-quiver "$OUT/1_rfdiffusion.qv" \
  --num-designs 50 \
  --design-loops "H1:7,H2:6,H3:5-13" \
  --hotspots "T57,T101,T106" \
  --diffuser-t 50

CUDA_VISIBLE_DEVICES=0 bin/proteinmpnn \
  --input-quiver "$OUT/1_rfdiffusion.qv" \
  --output-quiver "$OUT/2_proteinmpnn.qv" \
  --loops "H1,H2,H3" \
  --seqs-per-struct 4 \
  --temperature 0.2

CUDA_VISIBLE_DEVICES=0 bin/rf2 \
  --input-quiver "$OUT/2_proteinmpnn.qv" \
  --output-quiver "$OUT/3_rf2.qv" \
  --num-recycles 10 \
  --seed 42

bin/rfantibody-env -c \
  'import sys; from rfantibody.cli.quiver import qvscorefile; qvscorefile.main(args=[sys.argv[1]])' \
  "$OUT/1_rfdiffusion.qv"

bin/rfantibody-env -c \
  'import sys; from rfantibody.cli.quiver import qvscorefile; qvscorefile.main(args=[sys.argv[1]])' \
  "$OUT/3_rf2.qv"
```

node1 当前只为三个推理阶段和 Python 环境建立了 wrapper，没有单独的 `bin/qvscorefile`，所以上面通过 `bin/rfantibody-env` 调用当前源码中的 Click 命令。每次调用会在输入 Quiver 旁自动生成同名 `.sc` 文件。命令模板不应跳过 target 文件的链名和 residue numbering 检查。

### 13.5 第一层 RFantibody/RF2 过滤

建议至少保留：

```text
interaction_pae < 10
target_aligned_antibody_rmsd < 2 Å
target_aligned_cdr_rmsd < 2 Å
无严重原子 clash
确实接触指定 hotspot，而不是仅在附近游离
```

不要只按全局 pLDDT 排名。VHH framework 本来就容易预测得很稳定，全局高 pLDDT 可能掩盖跨链相对位置不确定。真正应看的是 interaction pAE 和 target-aligned interface/CDR self-consistency。

### 13.6 第二层复合物交叉预测

对 RF2 通过的候选，用至少一种独立方法重新预测：

```text
AlphaFold3 / 本地可用替代
Boltz
tFold
HADDOCK3 constrained docking
```

交叉预测时要问：

1. 独立模型是否仍把 VHH 放到同一 PVRIG 表位？
2. CDR3 是否仍占据 PVRL2 接触区域？
3. 不提供过强 hotspot privileged information 时，pose 是否仍能恢复？
4. 多 seed 的 pose 是否收敛，而不是只有一个偶然解？

### 13.7 第三层 blocker 几何评分

把每个 VHH-PVRIG pose 的 PVRIG 对齐到 8X6B 和 9E6Y，然后计算：

```text
epitope_overlap
  = VHH 接触 PVRIG 的残基中，有多少属于 PVRIG-PVRL2 共识界面

hotspot_coverage
  = 预先定义的高权重 PVRIG hotspot 被 VHH 覆盖的比例

pvrl2_occlusion
  = 把 PVRL2 放回后，VHH 与 PVRL2 的空间占据/冲突程度

cdr3_interface_occupation
  = CDR3 对功能界面的 buried area/contact contribution

dual_structure_robustness
  = 在 8X6B 和 9E6Y 两个参考结构中是否都保持遮挡

glycan_compatibility
  = 与 NAG/潜在糖链是否发生不可接受冲突
```

推荐最终 blocker score 不直接由单一网络概率决定，而是组合：

```text
S_blocker =
  w1 * RF2/independent-model pose confidence
  + w2 * PVRIG-PVRL2 footprint overlap
  + w3 * explicit PVRL2 steric occlusion
  + w4 * interface energy/shape complementarity
  + w5 * hotspot coverage
  + w6 * pose convergence
  - w7 * clash/glycan penalty
  - w8 * developability penalty
  - w9 * novelty/leakage risk
```

其中 `w2`、`w3` 是比赛任务与普通 binder 设计的核心差异。

### 13.8 第四层界面和可开发性过滤

结构过滤可加入：

- Rosetta interface ddG；
- buried SASA；
- shape complementarity；
- hydrogen bonds 和 salt bridges；
- unsatisfied buried polar atoms；
- interface clash；
- DeepRank-Ab/AntiConf 等 pose confidence；
- CDR loop strain 和不合理 cis/trans peptide；
- 与 PVRIG glycan 的冲突。

序列过滤可加入：

- N-linked glycosylation motif；
- 非预期 cysteine；
- deamidation/isomerization hotspot；
- 高疏水 patch；
- aggregation/SAP；
- 净电荷和 pI；
- 重复序列和 synthesis risk；
- 人源性/免疫原性；
- 与已知序列或比赛泄漏集合的相似性。

---

## 14. RFantibody 数据对自建 AI 模型有什么用

### 14.1 最有价值的不是直接拿 CSV 做二分类

公开表的真正价值是提供：

- antibody/CDR cluster；
- target cluster；
- antibody-target chain mapping；
- CDR sequence 和长度；
- PDB 结构索引；
- 构造负样本；
- affinity 子集；
- 可按 cluster/date 做防泄漏 split 的基础。

若只把 11,777 行随机打乱做 binary classification，很容易出现：

- 同 PDB copy 泄漏；
- 高相似 CDR 泄漏；
- 同 target 或近同源 target 泄漏；
- constructed negative 被误当实验 nonbinder；
- 无 target sequence 行被错误填充；
- 把 affinity 缺失当作弱结合；
- 把所有 heavy-only 都当 VHH。

### 14.2 推荐的数据层次

#### Level A：结构正样本

从 SAbDab/PDB 重新下载结构，生成：

```text
VHH/antibody sequence
target sequence
CDR mask
paratope mask
epitope mask
residue-residue contact map
complex coordinates
ab_cluster
target_cluster
```

适合训练：

- paratope/epitope prediction；
- contact map prediction；
- interface representation；
- pose confidence；
- structure-conditioned sequence scoring。

#### Level B：弱负样本

使用 mismatch 和 CDR-swap，但明确记录：

```text
label_source = constructed_negative
label_confidence = weak/moderate
```

不能与实验确认 nonbinder 等权。

#### Level C：affinity 子集

CSV 只有 1,263 个数值 affinity 行、709 个唯一 PDB，且实验方法、温度、单位和条件可能不一致。应先标准化：

```text
Kd / Ka / IC50 类型
单位转换
temperature
assay method
原始文字和值
重复测量聚合
```

它可以做 affinity auxiliary task 或 pairwise ranking，但不适合不清洗就训练精确 Kd 回归。

#### Level D：PVRIG 专用 blocker 数据

这是 RFantibody 公开数据没有提供的关键层：

```text
VHH-PVRIG binding label
VHH-PVRIG affinity
PVRL2 competition/blocking label
blocking percentage / IC50
PVRIG epitope/contact residues
complex pose or docking ensemble
expression/developability
assay context
```

已知 PVRIG blocker 只能放在 calibration、external test 或严格 leakage-control lane，不能随意复制成普通训练正样本，否则比赛评估可能变成记忆已知序列。

### 14.3 推荐的多任务模型输出

若要训练自己的 PVRIG 模型，推荐输出分开定义：

```text
P_bind          是否可能结合 PVRIG
P_pose_good     当前复合物 pose 是否可信
P_interface     每个 PVRIG/VHH 残基成为界面的概率
P_overlap       与 PVRIG-PVRL2 界面重叠程度
P_block         阻断 PVRIG-PVRL2 的概率
affinity_rank   相对亲和力排序或区间
developability 表达、聚集和化学风险
```

不要把它们压成一个未经校准的“总分”。binder、pose、affinity 和 blocker 是不同问题，训练标签和实验含义也不同。

### 14.4 推荐 split 规则

至少同时控制：

```text
antibody split：按 ab_cluster/CDR similarity
target split：按 target_cluster/target sequence similarity
structure split：同一 PDB 的所有 copy 必须同组
date split：必要时按 deposition date
PVRIG family split：防止同源 receptor 泄漏
known blocker split：独立 calibration/test
```

对通用模型可做三种测试：

1. unseen antibody，seen target family；
2. seen antibody distribution，unseen target；
3. antibody 和 target 双冷启动。

第三种最接近真正的新靶点泛化，也最难。

---

## 15. 建议的 PVRIG 端到端工作流

```text
步骤 1：准备 PVRIG target
  8X6B chain B -> chain T
  保留 residue numbering
  建立 UniProt/PDB/RFantibody 三套编号映射

步骤 2：分 hotspot set 做 RFdiffusion pilot
  每组 50-100 backbones
  检查 dock 成功率、热点覆盖和方向

步骤 3：ProteinMPNN 扩展序列
  每 backbone 2-4 条，pilot 后增加到 4-8 条

步骤 4：RF2 self-consistency
  interaction pAE、target-aligned RMSD、CDR RMSD

步骤 5：独立复合物预测
  AF3/Boltz/tFold/HADDOCK，多 seed/多方法一致性

步骤 6：PVRL2 blocker 几何评分
  对齐 8X6B/9E6Y，计算 overlap、occlusion、hotspot coverage

步骤 7：界面能量和 pose quality
  Rosetta、DeepRank-Ab、AntiConf、clash、bSASA、SC

步骤 8：糖基化与可开发性
  NAG/糖链冲突、聚集、化学风险、人源性

步骤 9：去冗余和多样性选择
  sequence cluster + pose cluster + epitope subregion cluster

步骤 10：实验
  expression -> binding SPR/BLI -> PVRL2 competition -> cellular function
```

实验上至少要把三类结果分开：

```text
binding：是否结合 PVRIG
competition：是否阻断/竞争 PVRL2
function：是否恢复或改变目标免疫功能轴
```

一个 VHH 可以是强 binder 但不阻断；也可能在体外竞争但细胞功能不理想。这正是 RFantibody 之后必须建立专用 blocker 层的原因。

---

## 16. RFantibody 的主要优点与局限

### 16.1 优点

1. **真正支持指定表位 de novo 生成**，比 sequence-only binder classifier 更接近比赛目标。
2. **固定成熟 framework，只设计 CDR**，减少生成自由度并提高可开发性起点。
3. **同时生成 CDR 几何和 dock**，不是先孤立生成 VHH 再盲 docking。
4. **有真实 VHH 实验验证**，包括 SPR、competition、neutralization 和 cryo-EM。
5. **代码和主要推理权重公开**，本项目 node1 已通过三段 smoke test。
6. **训练数据设计先进**，结合 SAbDab、TCR、loop interfaces 和实验 nonbinder。
7. **Quiver 适合大规模、可分阶段和断点式运行**。

### 16.2 局限

1. **命中率低**：论文为 0%-2%，一般可能需要约 10k 规模。
2. **过滤器是主要瓶颈**：低 pAE 和低 RMSD 不等于实验 binder。
3. **不输出可靠 Kd**：不能把 RF2 confidence 当 affinity。
4. **不理解 PVRIG-PVRL2 阻断任务**：hotspot targeting 不等于 functional blockade。
5. **糖基化建模不足**：PVRIG 的 NAG/潜在糖链需后处理检查。
6. **完整训练数据未全公开**：尤其 1.6M in-house miniprotein 数据。
7. **hotspot 组合敏感**：错误热点可能导致大量未对接设计。
8. **VHH 可能 side-on docking**：有时 framework 接触显著，需要判断是否适合比赛和开发目标。
9. **当前 wrapper 未默认导出 pBind**：不能误报标准输出字段。
10. **计算成功不等于实验成功**：仍需表达、结合、竞争和功能实验闭环。

---

## 17. 最终建议

对 PVRIG 比赛，RFantibody 是目前最值得优先使用的公开生成模型之一，但正确用法不是“运行一次并取 RF2 top 10”，而是：

```text
用多个稀疏 PVRIG-PVRL2 hotspot set 生成结构多样的 VHH
  -> 用 RF2 检查 sequence-structure self-consistency
  -> 用独立模型复核 pose
  -> 显式计算 PVRL2 footprint overlap 和 steric occlusion
  -> 加入能量、糖基化、可开发性和去泄漏过滤
  -> 用结合、竞争、功能三层实验验证
```

对自建 AI 模型，RFantibody 最值得借鉴的不是一个单独网络层，而是四个设计原则：

1. **按 CDR 和 target 双重聚类防止数据泄漏**；
2. **用 loop-mediated interfaces 扩充有限的抗体结构数据**；
3. **把结构、结合、界面和置信度做成多任务，而不是单一二分类**；
4. **把 binder 与 blocker 分开建模，增加 PVRL2 competition 的专用标签和几何目标**。

在本项目中的准确定位可概括为：

> RFantibody 负责产生“可能在正确 PVRIG 表位结合”的候选；PVRIG 专用 blocker scoring 负责判断它是否真正遮挡 PVRL2；实验负责给出最终答案。

---

## 18. 复现检查清单

### 数据与来源

- [ ] 记录 RFantibody Git commit；
- [ ] 校验三份权重 checksum；
- [ ] 校验公开 CSV 的 MD5；
- [ ] 保存 Zenodo metadata 和 license；
- [ ] 不把 11,777 行说成独立实验互作；
- [ ] 不把 constructed negatives 说成实验 nonbinders；
- [ ] 不把所有 `ab_chains=H` 自动当 canonical VHH；
- [ ] 不把 CSV validation flag 与 104+47 final sets 混淆。

### PVRIG 输入

- [ ] 从 8X6B/9E6Y 确认 PVRIG 链；
- [ ] 目标链改名为 T；
- [ ] 保留 PDB residue numbering；
- [ ] 保存 UniProt <-> PDB <-> RFantibody 映射；
- [ ] 检查缺失残基、altloc、非蛋白原子和 chain break；
- [ ] 记录 NAG/糖基化位置；
- [ ] 每组只给 3-5 个合理 hotspot。

### 推理

- [ ] 先 pilot，再扩大；
- [ ] RFdiffusion、ProteinMPNN、RF2 分阶段保存 Quiver；
- [ ] 每 backbone 采多条 MPNN 序列；
- [ ] RF2 使用足够 recycles；
- [ ] 导出 interaction pAE 和 target-aligned RMSD；
- [ ] 若需 pBind，先修改并验证 wrapper；
- [ ] 使用独立复合物模型交叉验证。

### blocker 筛选

- [ ] 对齐 8X6B 和 9E6Y；
- [ ] 计算 PVRIG-PVRL2 interface overlap；
- [ ] 计算显式 PVRL2 occlusion；
- [ ] 检查 CDR3 是否真正占据功能界面；
- [ ] 检查 NAG/糖链冲突；
- [ ] 加入 interface energy 和 pose quality；
- [ ] 做序列、pose 和表位区域多样性选择；
- [ ] 将 known blockers 保持在 calibration/leakage-control lane。

### 实验

- [ ] 表达和纯化；
- [ ] SPR/BLI binding；
- [ ] PVRL2 competition；
- [ ] 细胞功能；
- [ ] 记录 negatives，不只记录成功 hits；
- [ ] 将实验结果回流用于 PVRIG 专用过滤器校准。

---

## 19. 主要参考与本地证据

### 官方来源

- Nature 论文：<https://doi.org/10.1038/s41586-025-09721-5>
- GitHub：<https://github.com/RosettaCommons/RFantibody>
- 公开抗体训练表：<https://doi.org/10.5281/zenodo.15741710>
- RFdiffusion：<https://doi.org/10.1038/s41586-023-06415-8>
- ProteinMPNN：<https://doi.org/10.1126/science.add2187>

### 本地证据

```text
downloaded_models/RFantibody-data/AntibodyTrainingDataset.csv
downloaded_models/RFantibody-data/DATASET_AUDIT.json
downloaded_models/RFantibody-data/SOURCE.md
../node1/RFANTIBODY_NODE1_DEPLOYMENT.md
../data/structures/8X6B.pdb
../data/structures/9E6Y.pdb
../data/structures/PVRIG_hotspot_set_v1.csv
../data/structures/PVRIG_numbering_reconciliation.csv
```
