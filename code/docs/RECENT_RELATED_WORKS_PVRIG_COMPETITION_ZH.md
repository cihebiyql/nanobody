# PVRIG-PVRL2 阻断型 VHH 比赛：近期相关论文、数据与可复现路线

更新日期：2026-07-11  
工作目录：`/mnt/d/work/抗体/code`  
检索范围：重点覆盖 2024-2026；保留少数直接决定 PVRIG-PVRL2 机制的早期论文。  
核验来源：Crossref、PubMed/PMC、RCSB PDB、期刊正文、bioRxiv/arXiv、GitHub API、Zenodo/Hugging Face。

## 0. 结论先行

还有，而且 2025-2026 出现了几类比 DeepNano、NABP-BERT 更接近本比赛的新工作：

1. **指定表位生成 VHH/抗体**：RFantibody、tFold System、mBER、Germinal、IgGM。
2. **预测两个抗体是否占据重叠表位**：AbLang-PDB/AbLang-RBD 的对比学习工作，直接接近“是否可能竞争阻断”。
3. **结构 pose 排序**：DeepRank-Ab、AntiConf、ABAG-Rank、HADDOCK3 nanobody workflow。
4. **亲和力与突变优化**：AlphaBind、Graphinity、SE3Bind，但它们不能单独证明阻断。
5. **直接 PVRIG 证据**：8X6B、9E6Y、IBI352g4a，以及 2025 年使用 anti-PVRIG nanobody 的 TIGIT/PVRIG 双抗论文。

目前没有一个公开模型可以直接完成：

```text
VHH sequence + PVRIG -> reliable PVRIG-PVRL2 blocking probability/Kd
```

最合理的路线仍然是组合模型：

```text
指定 PVRIG-PVRL2 热点生成候选
  -> sequence/QC 初筛
  -> 多模型复合物采样
  -> pose 质量排序
  -> PVRL2 footprint overlap + steric occlusion
  -> affinity/developability 辅助排序
  -> binding、competition、functional assay 分轴验证
```

若只选三项立即投入：

1. **RFantibody**：最接近“指定 PVRIG 表位直接生成 VHH”，代码、权重、训练集都公开；本项目 node1 已完成三段式 smoke test。
2. **tFold System**：最接近“指定表位生成 + 复合物预测 + 虚拟筛选 + competition 实验验证”的完整范式。
3. **AbLang-PDB 的 epitope-overlap 思路**：最接近把“binder”进一步拆成“可能占据同一功能表位的 binder”；代码和权重公开，但原模型主要面向成对 VH/VL，需要为 VHH 重训或微调。

## 1. 比赛任务和硬约束

本文档筛选的不是泛泛的“抗体 AI”文章，而是与下面目标相近的工作：

```text
给定 PVRIG 靶点及其 PVRL2 功能界面，
设计或筛选能够结合 PVRIG、覆盖/干扰 PVRIG-PVRL2 界面、
具有较好亲和力并最终具备实验阻断能力的 VHH。
```

本地结构证据已经确定：

```text
PVRIG-PVRL2 structures：8X6B、9E6Y
PVRIG consensus interface：23 个 alignment columns
双结构支持 core hotspots：21 个
单结构支持 secondary hotspots：2 个
soft hints：S67、R95、I97
```

按 UniProt Q6DKI7 编号，当前更可靠的 PVRIG core interface 为：

```text
S71, L72, T74, N81, G82, A83,
V90, H92, R95, G96, R98, W100,
K135, A137, S138, F139, P140, E141, G142, S143, W144
```

局部最值得作为生成热点或阻断中心的残基是：

```text
R95, K135, F139, E141/G142, S143/W144
```

比赛必须显式区分：

```text
PVRIG non-binder
PVRIG binder but non-blocker
PVRIG-PVRL2 blocker
```

因此，AF3/Boltz/RFantibody 的高置信复合物、序列模型的高 binding probability、以及预测的低 ddG 都不能单独当作 blocker 标签。

## 2. 证据与可复现性分级

### 2.1 证据标记

- `[结构直接证据]`：有 PDB、cryo-EM、X-ray 或明确界面结构。
- `[实验功能证据]`：有 binding、competition、cell assay 或体内实验。
- `[同行评审方法]`：已在期刊或正式会议发表。
- `[预印本]`：尚未完成同行评审，结论和代码仍可能变化。
- `[代码证据]`：公开仓库可核查。
- `[推断]`：原文未做 PVRIG，本文根据输入/输出能力提出迁移方案。

### 2.2 可复现性等级

| 等级 | 定义 |
| --- | --- |
| A | 代码、权重、数据或明确可重建数据、示例命令基本齐全 |
| B | 推理可复现，但完整训练集或重训流程不完整 |
| C | 有代码，但依赖受限、权重/数据缺口明显，或仍在快速修复 |
| D | 论文或预印本真实，但核心模型、权重或数据未开放 |

### 2.3 比赛相关性评分

评分不是论文质量排名，而是对本比赛的实用性评分：

| 维度 | 0 分 | 1 分 | 2 分 |
| --- | --- | --- | --- |
| 靶点条件化 | 与靶点无关 | 输入靶点序列/结构 | 可指定表位、热点或界面 |
| blocker 相关性 | 只做通用性质 | 做 binding/interface | 直接支持竞争、重叠表位或位阻判断 |
| 设计输出 | 不生成候选 | 输出评分/结构 | 生成可实验序列或结构 |
| 可复现性 | 无公开资产 | 部分代码/权重 | 代码、权重、数据/示例较完整 |
| 当前可落地性 | 不能接入 | 可作辅助模块 | 可直接进入当前 PVRIG pipeline |

## 3. 最值得优先看的近期工作

| 优先级 | 工作 | 年份/状态 | 核心能力 | 公开资产 | 相关性 | 决策 |
| --- | --- | --- | --- | --- | ---: | --- |
| 1 | RFantibody / RFdiffusion antibody | Nature，在线 2025；卷期 2026 | 指定热点生成 VHH/scFv，ProteinMPNN 设计序列，RF2 过滤 | 代码、权重、训练集 | 10/10 | 第一优先复现 |
| 2 | tFold System | Nature Communications，在线 2025；卷期 2026 | 抗原+表位+框架生成、复合物预测、虚拟筛选 | 代码、权重、测试集 | 9/10 | 第一优先复现/对照 |
| 3 | AbLang-PDB/AbLang-RBD epitope overlap | Patterns 2026 | 从抗体序列预测重叠表位/竞争关系 | 代码、权重、部分数据 | 8/10 | 改造成 VHH overlap prior |
| 4 | mBER | bioRxiv 2025 | `mber-vhh`、热点条件化 VHH binder 设计 | 代码、依赖权重、示例 | 8/10 | 计算试跑，谨慎解释 |
| 5 | IgGM | ICLR 2025 | 抗体/纳米抗体序列-结构联合生成，可指定 epitope | 代码、权重、示例 | 8/10 | 作为第二生成器 |
| 6 | Germinal | bioRxiv 2025 | 指定表位生成 VHH/scFv，多后端 cofold/filter | 代码；依赖外部参数 | 7/10 | 条件成熟后复现 |
| 7 | HADDOCK3 nanobody-antigen workflow | bioRxiv 2025 + 官方 workflow | 带 paratope/epitope restraint 的 VHH docking | 代码、benchmark、cfg、分析数据 | 8/10 | 当前结构主线可直接用 |
| 8 | DeepRank-Ab | Communications Biology 2026 | 抗体-抗原 docking pose 的 DockQ 回归与排序 | 代码、权重、Zenodo 数据 | 8/10 | pose 排序首选之一 |
| 9 | AntiConf | Briefings in Bioinformatics 2026 | AI 预测抗体-抗原复合物的 precision-driven confidence | 代码、Zenodo 数据 | 7/10 | 与 DeepRank-Ab 交叉过滤 |
| 10 | ABAG-Rank | bioRxiv 2026 | 对 AF3/Boltz 抗体复合物进行 learning-to-rank | 代码、两个 checkpoint、示例；训练集不公开 | 7/10 | 推理可用，不能完整重训 |
| 11 | AlphaBind | mAbs 2025 | affinity prediction、finetuning 和序列优化 | 代码、checkpoint、教程；需 NGC 资产 | 6/10 | 有本靶点实验数据后再微调 |
| 12 | Graphinity | Nature Computational Science 2025 | 结构条件的抗体-抗原 ΔΔG 预测 | 代码、大规模合成 ddG 数据 | 6/10 | affinity 辅助，不作 blocker 主判据 |

## 4. A 类：指定表位生成和设计

### 4.1 RFantibody：当前最接近比赛目标的公开工作

**论文**：*Atomically accurate de novo design of antibodies with RFdiffusion*  
**DOI**：<https://doi.org/10.1038/s41586-025-09721-5>  
**代码**：<https://github.com/RosettaCommons/RFantibody>  
**训练集**：<https://doi.org/10.5281/zenodo.15741710>  
**状态**：`[同行评审方法] [实验功能证据] [代码证据]`，可复现性 A-。

RFantibody 的输入与输出非常符合本比赛：

```text
输入：抗原结构 + VHH framework + 目标热点 + CDR 长度范围
输出：VHH backbone/复合物 pose + CDR 序列 + RF2 结构和置信过滤结果
```

论文对 VHH 做了真正的实验验证，而不只是 retrospective benchmark：

- 使用人源化 VHH framework 设计多个靶点的候选。
- 对部分靶点筛选约 9,000 个设计，对部分靶点筛选 95 个设计。
- 各靶点实验命中率约为 0%-2%，说明计算设计仍需要大规模筛选。
- RBD 和 TcdB VHH 通过 competition assay 验证了预期表位。
- TcdB VHH 还出现功能性中和证据。
- 论文公开了训练集、代码和权重下载路径。

对 PVRIG 的直接迁移方式：

```text
target = PVRIG extracellular IgV domain
framework = 当前 top VHH scaffolds 或 RFantibody 示例 h-NbBCII10
hotspots = R95,K135,F139,S143,W144
secondary hotspot sets = 邻近 E141/G142、H92/R98、S71/T74
```

不建议一次把全部 21 个 core residues 都作为强热点。RFantibody 对热点组合敏感，应当用多个小 hotspot set 分开采样：

```text
set-A: R95,F139,W144
set-B: K135,E141,S143
set-C: H92,R98,F139
set-D: S71,T74,S143,W144
```

本项目现状：`../node1/RFANTIBODY_NODE1_DEPLOYMENT.md` 记录 RFdiffusion、ProteinMPNN、RF2 三段已在 node1 部署并通过 smoke test，因此 RFantibody 不是“只存在论文里”的远期方案，而是可直接进入 PVRIG 小规模 pilot 的工具。

**不能过度声称**：RFantibody 生成到正确热点不等于一定能阻断 PVRL2；仍需把 pose 对齐到 8X6B/9E6Y 后计算 footprint overlap 和 PVRL2 occlusion。

### 4.2 tFold System：最接近完整实验闭环的工作

**论文**：*De novo design of epitope-specific antibodies via a structure-driven computational workflow*  
**DOI**：<https://doi.org/10.1038/s41467-025-67361-9>  
**代码**：<https://github.com/TencentAI4S/tfold>  
**状态**：`[同行评审方法] [实验功能证据] [代码证据]`，可复现性 A-/B+。

论文的工作流输入是：

```text
antigen sequence + specified epitope + antibody framework
```

输出是 CDR 序列、复合物结构和筛选分数。其关键价值是：论文不仅做 binding，还用 competition assay 检查指定表位是否被命中。这一点与 PVRIG-PVRL2 比赛高度相似。

训练数据值得特别注意：

- 抗体单体训练数据来自 2021-12-31 前 SAbDab：8,264 个 VH/VL 复合物、1,693 个 heavy-only、376 个 light-only 样本。
- 抗体-抗原复合物训练集：4,834 个 antibody-antigen complexes。
- nanobody/single-domain-antibody-antigen 训练集：1,319 个 complexes。
- 验证集包括 99 个 antibody-antigen 和 40 个 nanobody-antigen complexes。
- 测试集包括 99 个 antibody-antigen 和 41 个 nanobody-antigen complexes，并按时间和抗原相似度隔离。
- 官方仓库公开推理代码、权重、测试集和 framework library，但完整重训所需的精确快照仍需自行按论文规则重建。

论文也诚实指出：tFold-Ag 对 nanobody-antigen complex 的准确率仍低于 AF3，且 confidence 对细小突变和真/假 binder 的区分能力有限。因此它适合作为**生成器和结构候选来源**，不能作为唯一 ranking model。

### 4.3 mBER：VHH 专用命令行和热点约束非常实用

**论文**：*mBER: Controllable de novo antibody design with million-scale experimental screening*  
**DOI**：<https://doi.org/10.1101/2025.09.26.678877>  
**代码**：<https://github.com/manifoldbio/mber-open>  
**状态**：`[预印本] [代码证据]`，可复现性 C。

仓库提供专门的 `mber-vhh`：

```bash
mber-vhh \
  --input-pdb target.pdb \
  --chains A \
  --hotspots A56
```

它支持 VHH binder 设计，并提供约 9 GB 的 AF2、NanoBodyBuilder2、ESM2 等外部权重下载脚本。对小型靶点的 VHH 设计，README 认为低于 16 GB VRAM 可能可运行；常规推荐 32 GB 以上。

对本比赛的价值是接口和工程实现，而不是把预印本中的 million-scale 实验结论视为已完全复现。公开仓库没有完整开放其大规模实验筛选数据。

### 4.4 Germinal：表位条件化能力强，但复现成本高

**DOI**：<https://doi.org/10.1101/2025.09.19.677421>  
**代码**：<https://github.com/SantiagoMille/germinal>  
**状态**：`[预印本] [代码证据]`，可复现性 C。

Germinal 将 ColabDesign hallucination、AbMPNN 重设计和 AF3/Chai/Protenix cofold/filter 串成一条 VHH/scFv 流水线。它能够直接输入目标热点，但有几个现实限制：

- 需要 PyRosetta academic license。
- 依赖 AlphaFold-Multimer 参数；AF3 参数取得也受官方许可条件约束。
- README 推荐 40-80 GB 级 GPU，较大任务推荐 60 GB 以上。
- 仓库仍在活跃修复，近期曾修正 hotspot/CDR3 索引问题。
- 没有 Germinal 自己独立训练的一套完整公开权重和训练集；它更像多工具编排系统。

因此它适合在 RFantibody/tFold pilot 后作为**独立生成器增加多样性**，不宜作为第一个复现对象。

### 4.5 IgGM：可指定新表位的 VHH 生成器

**论文**：*IgGM: A Generative Model for Functional Antibody and Nanobody Design*  
**预印本 DOI**：<https://doi.org/10.1101/2024.09.19.613838>  
**会议状态**：ICLR 2025 accepted  
**代码**：<https://github.com/TencentAI4S/IgGM>  
**状态**：`[同行评审会议] [代码证据]`，可复现性 B-。

官方示例直接支持：

```text
给定 nanobody framework + antigen PDB + epitope residue list
  -> 设计 CDR 序列并预测整体结构
```

这使其很适合与 RFantibody 做“不同生成范式的共识候选”。公开权重和推理示例较完整，但完整训练数据没有随仓库完全打包，因此更适合 inference，而不是从头复训。

### 4.6 2025-2026 最新生成工作：开放程度决定优先级

| 工作 | 状态 | 公开资产 | 对本比赛的价值 | 建议 |
| --- | --- | --- | --- | --- |
| ConTact | arXiv 2026，`10.48550/arXiv.2605.21600` | `mansoor181/ConTact`；未见完整 checkpoint/data bundle | 显式先预测 CDR-antigen contact，再生成 CDR | 借鉴多任务结构，暂不作主生成器 |
| AgForce | arXiv 2026，`2605.21610` | `mansoor181/ag-force` | 检测 antigen-conditioned generator 的“antigen blindness” | 用作条件化有效性的负控框架 |
| AbFlow | KDD/arXiv 2026，`10.48550/arXiv.2602.07084` | `WangWenda87/AbFlow`，HF 数据和多任务 checkpoint | paratope-centric full-atom design、affinity optimization | 可复现性较好，列入第二批 |
| GeoGAD | Bioinformatics 2026，`10.1093/bioinformatics/btag042` | `WeiSongJian/GeoGAD`、Zenodo | CDR-H3 sequence/structure co-design 和 affinity optimization | 更适合固定 backbone 优化 |
| AntibodyDesignBFN | arXiv 2026，`10.48550/arXiv.2601.05605` | GitHub + Hugging Face checkpoint | 固定 backbone 的快速序列设计 | 适合作为 CDR sequence redesign 对照 |
| Origin-1 | bioRxiv 2026，`10.64898/2026.01.14.699389` | `AbSciBio/origin-1` 主要开放数据/分析；核心平台不完整 | epitope-conditioned all-atom 设计范式 | 读策略，不当作完整开源模型 |
| Chai-2 | bioRxiv 2025，`10.1101/2025.07.05.663018` | 公开 `chai-lab` 主要是 Chai-1；Chai-2 设计能力未完整开放 | 少量候选、指定表位、wet-lab 设计范式 | 作为结果标杆，不作复现主线 |
| JAM/Nabla | bioRxiv 2025，`10.1101/2025.01.21.633066` | 未见完整公开权重/代码 | 指定表位、VHH/scFv/mAb、实验验证 | 作为产业标杆和方法参考 |
| GeoFlow-V3 | bioRxiv 2025，`10.1101/2025.10.20.682964` | 未见完整公开模型权重 | 快速 epitope-conditioned VHH design | 暂列观察清单 |

## 5. B 类：从 binding 进一步走向 interface、overlap 和 affinity

### 5.1 AbLang-PDB/AbLang-RBD：最接近“竞争表位预测”的新工作

**论文**：*Contrastive learning enables epitope overlap predictions for targeted antibody discovery*  
**DOI**：<https://doi.org/10.1016/j.patter.2025.101419>  
**期刊**：Patterns，2026  
**代码**：<https://github.com/IGlab-VUMC/AbLangPDB1>、<https://github.com/IGlab-VUMC/AbLangRBD1>  
**权重**：<https://huggingface.co/clint-holt/AbLangPDB1>、<https://huggingface.co/clint-holt/AbLangRBD1>  
**归档权重**：<https://doi.org/10.6084/m9.figshare.29647952>  
**状态**：`[同行评审方法] [实验功能证据] [代码证据]`，可复现性 A-/B+。

这项工作不是输入抗原后预测 binding，而是输入两个抗体序列，预测它们是否可能占据重叠表位。它的训练基础包括：

- 1,909 个非冗余人源抗体结构。
- 约 180 万个抗体对比较。
- 结构重叠、同一 Pfam/不同 Pfam，以及 SARS-CoV-2 RBD epitope mapping 数据。
- 冻结的 AbLang heavy/light backbone、LoRA 和对比学习目标。

AbLang-PDB 的用途与限制必须同时理解：

```text
适合：给定一个已知功能表位 reference antibody，找可能占据重叠表位的候选。
不适合：没有 reference 时直接判断 VHH 是否阻断 PVRIG-PVRL2。
```

对 PVRIG 的可迁移方案：

1. 用本地已知 PVRIG blocking VHH 作为 reference，但仅放在 calibration/retrieval lane。
2. 将模型从 VH/VL 双链改成 VHH 单链 encoder。
3. 训练标签优先来自结构 footprint overlap 和真实 competition 数据，而不是只用序列相似度。
4. 输出 `epitope_overlap_prior`，只占最终总分的一小部分。

重要风险：比赛有序列新颖性和 leakage 风险，不能通过贴近已知阳性 VHH 序列来“刷” overlap 分数。已知阳性必须与普通训练正例隔离。

### 5.2 AVIDa 数据：对自建 VHH 模型最有用的数据之一

| 数据集 | 规模/特点 | 适合训练什么 | 不适合声称什么 |
| --- | --- | --- | --- |
| AVIDa-hIL6，NeurIPS 2023 | 573,891 个 VHH-antigen pairs，单一 hIL-6 靶点、含大量突变/非结合配对 | target-conditioned binding、hard negatives、mutation sensitivity | 不能直接泛化成 PVRIG blocker |
| AVIDa-SARS-CoV-2，NeurIPS 2024 | VHH-variant interaction 数据 + VHHCorpus-2M | VHH language pretraining、antigen variant robustness、pair classification | 病毒抗原分布不等于免疫检查点界面 |

代码与数据：

- <https://github.com/cognano/AVIDa-hIL6>
- <https://github.com/cognano/AVIDa-SARS-CoV-2>
- <https://huggingface.co/COGNANO/VHHBERT>

对自己的模型，AVIDa 最大的价值不是把 IL-6/SARS 标签搬到 PVRIG，而是学习以下数据组织方式：

```text
同一个 VHH 对多个 antigen variants
同一个 antigen 对多个 VHH
真实 bind/non-bind 标签
按 VHH cluster、antigen family 和实验批次隔离 split
```

### 5.3 interface/paratope/epitope 模型

| 工作 | 年份 | 任务 | 代码/数据 | PVRIG 用法 |
| --- | ---: | --- | --- | --- |
| MIPE | IJCAI 2024，DOI `10.24963/ijcai.2024/669` | paratope + epitope residue prediction | `WangZhiwei9/MIPE`，pickle 数据公开，未见正式权重 | 给 pose/热点一致性打分；不是 binding 模型 |
| ParaSurf | Bioinformatics 2025，`10.1093/bioinformatics/btaf062` | 基于表面的 paratope-antigen interaction prediction | 论文和实现资源需按补充材料核验 | 检查 CDR 是否真正朝向功能表位 |
| ParaAntiProt | Scientific Reports 2024，`10.1038/s41598-024-80940-y` | 抗体序列 paratope prediction | `Alirzeanoroozi/ParaAntiProt` | 生成候选的 paratope prior |
| Paraplume | PLOS Computational Biology 2026，`10.1371/journal.pcbi.1013981` | repertoire-scale paratope prediction | 公开程度需单独核验 | 大批 VHH 快速 paratope 预筛 |
| AsEP | NeurIPS 2024，`10.52202/079017-0373` | antibody-specific epitope benchmark | `biochunan/AsEP-dataset`、Zenodo | 学习无泄漏 split 与 epitope 指标 |

### 5.4 binding/affinity 模型

| 工作 | 年份/状态 | 作用 | 关键限制 |
| --- | --- | --- | --- |
| AntiBinder | Briefings in Bioinformatics 2025，`10.1093/bib/bbaf008` | antibody-antigen interaction classification | binder 不等于 blocker |
| RLEAAI | Briefings in Bioinformatics 2025，`10.1093/bib/bbaf238` | PLM + sequence order 的 interaction prediction | 主要是 sequence-only pair score |
| AbAgIPA | BMC Bioinformatics 2024，`10.1186/s12859-024-05961-w` | backbone-aware interaction prediction | 结构输入质量决定上限 |
| AlphaBind | mAbs 2025，`10.1080/19420862.2025.2534626` | affinity prediction、finetune、optimization | 最适合有本靶点 assay 后微调，不应直接输出绝对 Kd |
| Graphinity | Nature Computational Science 2025，`10.1038/s43588-025-00823-8` | mutation ΔΔG prediction | 作者明确指出实验数据太少、泛化不稳 |
| SE3Bind | bioRxiv 2026，`10.64898/2026.01.17.700115` | SE(3)-equivariant affinity prediction | 预印本，需核验 checkpoint 和外部测试 |
| NanoBEP | bioRxiv 2025，`10.1101/2025.02.04.635413` | nanobody binding energy prediction | 未核验到官方代码、权重和完整训练集，不作主基线 |

Graphinity 的数据尤其适合做“数据量与泛化”研究：

- 942,723 个 FoldX synthetic ΔΔG mutations。
- 20,829 个 Rosetta Flex ddG synthetic mutations。
- 数据和 PDB 通过 Zenodo/OPIG 提供。
- 论文结论恰恰是：现有实验 ΔΔG 数据不足，模型很容易在随机 split 上表现好、在严格 split 上失效。

这与本项目当前结论一致：没有 PVRIG-specific binder/nonblocker/nonbinder 数据时，扩大模型不等于得到可靠 blocker classifier。

## 6. C 类：复合物预测、docking 和 blocker scoring

### 6.1 HADDOCK3 nanobody-antigen workflow

**论文预印本**：*Combining AI structure prediction and integrative modelling for nanobody-antigen complexes*  
**DOI**：<https://doi.org/10.1101/2025.07.01.662355>  
**代码/数据**：<https://github.com/haddocking/nanobodies>  
**状态**：`[预印本] [代码证据]`，复现实用性 A。

仓库包括 benchmark PDB、ImmuneBuilder/AF2/AF2-Multimer 输入、不同 restraint 场景、HADDOCK3 cfg、CAPRI/DockQ 结果和分析脚本。对 PVRIG 可以直接把本地 21 core hotspots 转成 ambiguous restraints，并比较：

```text
all-surface
loose interface
two-hit interface
known PVRIG core interface
mixed paratope + known epitope
```

它不训练 blocker 模型，但可以显著提高 docking 的可控性和可解释性。

### 6.2 DeepRank-Ab、AntiConf 和 ABAG-Rank

#### DeepRank-Ab

- 论文：*DeepRank-Ab: a scoring function for antibody-antigen complexes based on geometric deep learning*。
- DOI：<https://doi.org/10.1038/s42003-026-10408-4>。
- 代码：<https://github.com/haddocking/DeepRank-Ab>。
- 数据：<https://doi.org/10.5281/zenodo.17911452>。
- 输出：预测 DockQ 和 pose quality flag。
- 定位：判断“这个复合物 pose 像不像正确 pose”，不是判断“是否阻断”。

#### AntiConf

- DOI：<https://doi.org/10.1093/bib/bbag137>。
- 代码：<https://github.com/timucinlab/Ab-Ag_prediction>。
- 数据：<https://doi.org/10.5281/zenodo.16404871>。
- 定位：对 AI 生成的 antibody-antigen complexes 做 precision-oriented confidence scoring，可与 DeepRank-Ab 做共识过滤。

#### ABAG-Rank

- DOI：<https://doi.org/10.64898/2026.03.17.712376>。
- 代码：<https://github.com/tadteo/ABAG-Rank>。
- 仓库提供两个 checkpoint 和 inference-ready HDF5 示例。
- 训练集来自 AF3/Boltz 候选结构，但大规模 private dataset 未公开，因此推理可复现、完整训练不可复现。

### 6.3 推荐的 PVRIG blocker 几何评分

对每个 VHH-PVRIG pose，先将 PVRIG 对齐到 8X6B 和 9E6Y，再计算：

```text
footprint_overlap = VHH 接触的 PVRIG 残基与 21 core hotspots 的重叠比例
central_hotspot_coverage = R95/K135/F139/S143/W144 的覆盖数量
pvrl2_occlusion = 放回 PVRL2 后，VHH 对 PVRL2 的空间遮挡/冲突程度
cdr3_occupation = CDR3 在功能界面接触中的占比
pose_quality = DeepRank-Ab / AntiConf / ABAG-Rank / AF3-Boltz confidence 共识
interface_energy = Rosetta/FoldX/物理能量项
internal_clash = VHH-PVRIG pose 自身不合理碰撞惩罚
```

一个可用于初始排序、但尚未经过 assay 校准的启发式为：

```text
S_blocker =
  0.25 * footprint_overlap
  + 0.20 * pvrl2_occlusion
  + 0.15 * central_hotspot_coverage
  + 0.15 * pose_quality
  + 0.10 * cdr3_occupation
  + 0.10 * binding_prior
  + 0.05 * affinity_prior
  - clash_penalty
  - developability_penalty
  - known_positive_similarity_penalty
```

所有分量应先按同一批候选做 robust rank normalization。这个公式只是 assay 前的排序先验，不能命名为“实验阻断概率”。

## 7. D 类：直接 PVRIG/PVRL2 结构和功能论文

| 工作 | 证据 | 对比赛的用途 |
| --- | --- | --- |
| *Structural basis for the immune recognition and selectivity of the immune receptor PVRIG for ligand Nectin-2*，Structure 2024，`10.1016/j.str.2024.03.012`，PDB 8X6B | 2.0 Å PVRIG-PVRL2 结构 | 直接定义功能 footprint 和生成热点 |
| *Structure-guided engineering of CD112 receptor variants for optimized immunotherapy*，Molecular Therapy 2025，`10.1016/j.ymthe.2025.04.032`，PDB 9E6Y | 2.2 Å 独立结构 | 验证 8X6B 界面并降低单结构偏差 |
| *Characterization of a novel anti-PVRIG antibody with Fc-competent function...*，2024，`10.1007/s00262-024-03671-z` | IBI352g4a 报告 Kd 0.53 nM，并完全阻断 PVRIG-PVRL2 | 亲和力、competition 和 Fc 功能标杆；公开表位不足 |
| *Co-blocking TIGIT and PVRIG Using a Novel Bispecific Antibody...*，MCT 2025，`10.1158/1535-7163.MCT-23-0614` | anti-PVRIG nanobody 被用于 TIGIT/PVRIG 双抗，报告双轴阻断和 T/NK 功能 | 最直接的 anti-PVRIG nanobody 格式先例 |
| *PVRIG and PVRL2 Are Induced in Cancer and Inhibit CD8+ T-cell Function*，2019，`10.1158/2326-6066.CIR-18-0442` | COM701/PVRIG-PVRL2 功能轴 | 证明 competition 是必须测量的机制指标 |

两套结构的重复核心接触包括：

```text
PVRL2 Y64/F145 <-> PVRIG R95
PVRL2 H86/S92/M89/G90 <-> PVRIG F139
PVRL2 N81 <-> PVRIG S143/W144/E141/G142
PVRL2 E141 <-> PVRIG K135
```

若目标是解除 PVRIG 抑制，原则上优先设计 anti-PVRIG VHH，而不是直接阻断 PVRL2，因为 PVRL2 也是 CD226/DNAM-1 激活轴的配体。

## 8. 对自建 AI 模型最有价值的数据设计

### 8.1 推荐的数据表结构

```text
pair_id
vhh_sequence
antigen_sequence_hash
antigen_structure_id
vhh_cluster_id
antigen_family_id
binder_label                 # measured / unknown
blocker_label                # nonbinder / binder_nonblocker / blocker / unknown
kd_nm_or_interval
paratope_mask
epitope_mask
pose_id
pose_quality_label
interface_contact_map
source_dataset
evidence_grade
assay_type
split_group
license_or_use_constraint
```

### 8.2 推荐的多任务输出

```text
Task 1: pair binding probability/rank
Task 2: VHH paratope mask
Task 3: PVRIG epitope mask
Task 4: residue-residue contact map
Task 5: blocker class = nonbinder / binder_nonblocker / blocker
Task 6: affinity rank or interval，而不是虚假的精确 Kd
Task 7: pose quality
```

### 8.3 可直接利用的数据源

| 数据 | 最适合的任务 | 主要风险 |
| --- | --- | --- |
| RFantibody Zenodo training dataset | 结构条件的 VHH/antibody generation、热点条件化 | 需按抗原和抗体 cluster 去重 |
| tFold SAbDab temporal sets | monomer/complex prediction、epitope-conditioned design | 完整训练快照需重建，nanobody 数据仍少 |
| SAbDab/SAbDab-nano | 结构、contact map、paratope/epitope | 结构标签不等于 binding negative |
| AVIDa-hIL6 / AVIDa-SARS-CoV-2 | 真正 VHH bind/non-bind、mutation hard negatives | 单靶点/病毒域迁移偏差 |
| AsEP / CHIMERA-Bench | epitope benchmark 和严格 split | 主要是通用抗体，不是 PVRIG blocker |
| Graphinity / SKEMPI | mutation ΔΔG | 大量标签为计算合成，不能冒充实验 Kd |
| DeepRank-Ab / HADDOCK benchmark | pose quality、DockQ | pose 正确不等于功能阻断 |
| 本地 8X6B/9E6Y | PVRIG-PVRL2 footprint、occlusion ground truth | 只有 receptor-ligand，不是 VHH complex |

### 8.4 必须隔离的数据

- 已知 PVRIG blocking VHH/HR-151/专利成功系列只放 calibration、retrieval 或最终盲评对照，不混入普通训练正例。
- 由 docking 构造的假负例只能叫 `synthetic contrast`，不能叫 verified non-binder。
- 高 AF3/Boltz ipTM 不能转成 binder 标签。
- 高 hotspot overlap 不能转成 blocker 标签。
- 同一 VHH 的近邻、同一 antigen family 和同一结构模板必须 group split，避免随机行切分泄漏。

## 9. 推荐的实际复现顺序

### 第一批：立即复现或接入

1. **RFantibody**：node1 已部署；先对 3-4 组 PVRIG hotspot sets 各做小规模 pilot。
2. **DeepRank-Ab + AntiConf**：对已有 AF3/Boltz/HADDOCK poses 做正交质量过滤。
3. **HADDOCK3 nanobody workflow**：将 21 core + 2 secondary hotspots 转成 restraint scenarios。
4. **AbLang-PDB**：先复现原论文 inference，再评估单链 VHH 改造成本。
5. **tFold**：下载权重和测试集，先验证 nanobody-antigen complex prediction，再决定是否运行生成模块。

### 第二批：增加生成多样性和 affinity prior

1. IgGM。
2. mBER。
3. AlphaBind。
4. Graphinity。
5. AbFlow/GeoGAD。

### 暂不作为主线

- NanoBEP：缺少已核验的官方代码、权重和完整训练数据。
- Chai-2、JAM、GeoFlow-V3：结果很接近比赛，但核心设计能力没有完整公开。
- Origin-1：公开仓库更偏数据和分析，不能等同于完整开放模型。
- Germinal：代码真实，但依赖和 GPU 成本高，且仍在快速修复。

## 10. 最终推荐的比赛 pipeline

```text
P0  Target preparation
    8X6B + 9E6Y consensus interface
    -> hotspot sets + PVRL2 reference coordinates

P1  Candidate generation
    RFantibody + IgGM/tFold/mBER
    -> 多生成器、多 hotspot set、多 framework

P2  Sequence and developability gate
    ANARCI/IMGT + AbNatiV/TNP/QC + novelty/leakage control

P3  Complex sampling
    AF3/Chai/Boltz/tFold/HADDOCK3
    -> 每个 VHH 多 seed、多 pose

P4  Pose quality
    DeepRank-Ab + AntiConf + ABAG-Rank + geometry QC

P5  Blocker geometry
    footprint overlap + PVRL2 occlusion + CDR3 occupation
    + central hotspot coverage

P6  Binding/affinity auxiliary scores
    DeepNano/NABP/NanoBind + AlphaBind/Graphinity
    仅作 rank features，不直接输出 blocker 标签

P7  Experimental axes
    expression/QC
    -> PVRIG binding
    -> PVRL2 competition
    -> cell functional rescue
```

## 11. 广义文献索引

### 11.1 生成与优化

- RFantibody：<https://doi.org/10.1038/s41586-025-09721-5>
- tFold System：<https://doi.org/10.1038/s41467-025-67361-9>
- Germinal：<https://doi.org/10.1101/2025.09.19.677421>
- mBER：<https://doi.org/10.1101/2025.09.26.678877>
- IgGM：<https://doi.org/10.1101/2024.09.19.613838>
- GeoGAD：<https://doi.org/10.1093/bioinformatics/btag042>
- AbFlow：<https://doi.org/10.48550/arXiv.2602.07084>
- ConTact：<https://doi.org/10.48550/arXiv.2605.21600>
- AntibodyDesignBFN：<https://doi.org/10.48550/arXiv.2601.05605>
- IgDiff：<https://doi.org/10.1089/cmb.2024.0768>
- AbMEGD：<https://doi.org/10.24963/ijcai.2024/303>
- AntiFold：<https://doi.org/10.1093/bioadv/vbae202>

### 11.2 binding、interface 与 affinity

- AbLang-PDB/AbLang-RBD overlap：<https://doi.org/10.1016/j.patter.2025.101419>
- MIPE：<https://doi.org/10.24963/ijcai.2024/669>
- ParaSurf：<https://doi.org/10.1093/bioinformatics/btaf062>
- ParaAntiProt：<https://doi.org/10.1038/s41598-024-80940-y>
- AntiBinder：<https://doi.org/10.1093/bib/bbaf008>
- RLEAAI：<https://doi.org/10.1093/bib/bbaf238>
- AbAgIPA：<https://doi.org/10.1186/s12859-024-05961-w>
- AlphaBind：<https://doi.org/10.1080/19420862.2025.2534626>
- Graphinity：<https://doi.org/10.1038/s43588-025-00823-8>
- SE3Bind：<https://doi.org/10.64898/2026.01.17.700115>
- NanoBEP：<https://doi.org/10.1101/2025.02.04.635413>
- AsEP：<https://doi.org/10.52202/079017-0373>
- Paraplume：<https://doi.org/10.1371/journal.pcbi.1013981>

### 11.3 docking、pose 与结构评分

- HADDOCK3 nanobody-antigen：<https://doi.org/10.1101/2025.07.01.662355>
- DeepRank-Ab：<https://doi.org/10.1038/s42003-026-10408-4>
- ABAG-Rank：<https://doi.org/10.64898/2026.03.17.712376>
- AntiConf：<https://doi.org/10.1093/bib/bbag137>
- AI-augmented physics-based docking：<https://doi.org/10.1093/bioinformatics/btaf129>
- DockQ v2：<https://doi.org/10.1093/bioinformatics/btae586>
- PPIformer：<https://github.com/anton-bushuiev/PPIformer>
- AsEP/WALLE：<https://github.com/biochunan/AsEP-dataset>

## 12. 已核验但容易误写的事项

- RFantibody DOI 中含 2025，在线日期是 2025-11-05，但正式卷期显示 Nature 649 (2026)；文档统一写“在线 2025，卷期 2026”。
- tFold DOI 中含 2025，在线日期是 2025-12-10，正式卷期为 2026。
- Patterns epitope-overlap 论文 DOI 中含 2025，但 Crossref 的正式发表时间为 2026-02。
- MIPE 是 IJCAI 2024，不是 2025。
- DeepRank-Ab 已于 2026 年在 Communications Biology 同行评审发表，不再只按预印本处理。
- ABAG-Rank 仍是 2026 bioRxiv 预印本，且训练数据不完整公开。
- NanoBEP 目前只确认预印本，未确认官方代码、权重和完整训练集。
- 8X6B/9E6Y 是 PVRIG-PVRL2 receptor-ligand 结构，不是 anti-PVRIG VHH 复合物。
- GSK4381562/remzistotug/SRF813 有临床开发信息，但未找到可替代原始论文的公开 PVRIG-antibody complex 结构或同行评审 epitope 论文。

## 13. 与现有六个模型文档的关系

现有详细复现文档仍然有价值，但应放在新 pipeline 的不同位置：

- `docs/DEEPNANO_DETAILED_ZH.md`：sequence-only binding prior。
- `docs/NABP_BERT_DETAILED_ZH.md`：sequence-only pair classifier。
- `docs/NABP_LSTM_ATT_DETAILED_ZH.md`：可改造的 CDR-aware baseline。
- `docs/SEQUENCE_BASED_NABP_DETAILED_ZH.md`：传统机器学习 baseline。
- `docs/NANOBINDER_DETAILED_ZH.md`：结构能量特征和 pose plausibility。
- `docs/NANOBIND_DETAILED_ZH.md`：binding/interface/affinity 多任务框架。

新增文献并不是替换这六个模型，而是补齐它们缺少的三块：

```text
指定 PVRIG 功能表位生成 VHH
预测/比较功能表位重叠
对复合物 pose 和 PVRL2 位阻进行显式评分
```

## 14. 最重要的边界

本项目的最终科学表述应始终保持：

```text
模型可以提出 blocker-like candidates，
不能在缺少 competition assay 时声称已经得到真实 PVRIG-PVRL2 blocker。
```

当前最缺的数据不是更多通用 VHH 序列，而是同一 PVRIG 靶点上的：

```text
verified non-binder
verified binder but non-blocker
verified blocker
matched affinity / competition / functional measurements
```

这些数据一旦产生，AbLang-PDB 式 overlap learning、NanoBind 式多任务学习、AlphaBind 式靶点内微调，以及当前 V2.x 的 ranking/contact 模型才可能真正收敛到比赛目标。
