# 纳米抗体/VHH 工具全景调研报告（开源可复现优先版）

生成日期：2026-07-06  
工作目录：`/mnt/d/work/抗体/tools/nanobody_tool_survey`  
资料包目录：`nanobody_tool_survey/`

## 0. 本地资料包说明

这版报告根据你的反馈重排：**正文优先讲能公开获取代码/权重、能本地复现或至少能稳定使用的工具**；不能确认开源复现、只有网页/商业平台/论文白皮书的工具不删除，而是放到后置章节，作为了解和对照。

- 论文 PDF 目录：`nanobody_tool_survey/papers/`
- 代码目录：`nanobody_tool_survey/code/`
- 报告目录：`nanobody_tool_survey/report/`
- 下载日志与 manifest：`nanobody_tool_survey/metadata/`、`nanobody_tool_survey/logs/`
- 调研工具总数：69 个
- 成功下载 PDF：18 个
- 成功浅克隆代码仓库：53 个
- PDF 下载状态统计：`{'downloaded': 18, 'http_403': 19, 'http_406': 1, 'not_pdf': 16}`
- 代码下载状态统计：`{'cloned': 53}`

阅读建议：

1. 先看第 1-2 章：这些是优先复现和优先理解的开源工具。
2. 再看第 3 章：这些工具有代码，但权重、许可证、依赖或 VHH 专用性有条件。
3. 最后看第 4 章：这些是网页/商业/论文模型，暂不作为本地复现主线。
4. 找论文和代码路径看附录：`report/asset_inventory.md`；找失败 PDF 原因看：`report/missing_pdfs.md`。

---

## 1. 先读结论：我把工具按“能不能复现”重新排了顺序

这版报告不再把所有工具平铺，而是按你真正要做项目时的优先级阅读：

- **A 类：优先复现/优先学习。** 本地已经有公开代码；模型权重公开、可脚本下载，或者工具本身不需要神经网络权重；从工程角度最值得先试。
- **B 类：可研究但复现有条件。** 代码公开，但存在非商业/学术许可证、权重申请、PyRosetta/FoldX/AF 参数、训练数据过大、VHH 非专用等限制；适合第二批看。
- **C 类：后置了解。** 主要是网页服务、商业平台、论文/白皮书、无公开代码/权重，或者当前无法确认能本地跑；不删掉，但放在后面作为概念和对照。

### 1.1 A 类优先清单

建议优先看的开源工具如下：

- **结构单体建模/复合物建模：** NanoBodyBuilder2/ImmuneBuilder、HeavyBuilder2、HADDOCK3、Boltz、Chai-1。NanoNet 也很重要，但许可证偏 research-use，所以放在“高价值 B 类”里详细介绍。
- **设计/优化：** RFantibody、AntiFold、IgGM、BioPhi/Sapiens、Humatch。VHHBERT 是 VHH 表征重要工具，但数据许可有非商业限制，放在 B 类详细说明。
- **识别/发现：** alpseq、phage-seq/nbseq、ANARCI、Immcantation/pRESTO/Change-O/airrflow、DeepNano、Paragraph。
- **性质/可开发性：** TNP、ProtParam/Compute pI-Mw；A3D/CamSol/IEDB 等可作为网页/外部补充。

如果你的目标是“先跑起来一个 VHH 项目”，最小闭环可以是：

1. `ANARCI` 或 `IgBLAST` 做编号和 CDR 定位。
2. `NanoBodyBuilder2` 或 `NanoNet` 做 VHH 单体结构。
3. `TNP` 做 VHH developability 风险。
4. 如果有抗原结构，用 `HADDOCK3`、`Chai-1`、`Boltz` 做复合物候选；不要只信一个模型。
5. 如果要 de novo 设计，用 `RFantibody` 做主线；再用 `AntiFold/IgGM` 做序列重设计或辅助生成。

### 1.2 B/C 类为什么后看

- 有些工具很强，但不满足“完全可复现优先”：例如 **AlphaFold3** 有代码但权重/使用条款更受限；**IgFold/IgLM/AbNatiV** 可以跑但许可证偏学术或非商业；**Germinal/NanoDesigner** 依赖 PyRosetta、AlphaFold/FoldX 等外部组件，复现链条较长。
- 有些工具是公司平台或论文模型，例如 **Chai-2、JAM-2、Latent-X2、TFDesign-sdAb、EasyNano、nanoFOLD**。这些适合了解前沿方向，但不适合作为第一批本地复现实验。
- 有些是网页/商业工具，例如 **ClusPro、HDOCK、Aggrescan3D、CamSol、IEDB、DynaMut2、FoldX、BioLuminate、PipeBio、Tamarind**。它们可以使用，但不属于“本地开源模型”。

---

## 2. A 类与高价值 B 类：优先阅读的本地工具详解

### 2.1 NanoBodyBuilder2 / ImmuneBuilder

- **工具定位：** VHH 单体结构预测首选之一。它不是做抗原复合物，也不是做序列设计，而是把一条纳米抗体/VHH 序列快速转成三维结构。
- **发布时间和后续：** ImmuneBuilder 论文发表于 2023 年，套件包含 ABodyBuilder2、NanoBodyBuilder2、TCRBuilder2。后续同一生态还有 HeavyBuilder2、ABodyBuilder3 等延伸。
- **怎么训练/搭建：** 这是免疫受体专用深度学习模型，训练数据主要来自 SAbDab 等抗体/纳米抗体结构库。模型从序列预测结构，会生成 ensemble，并选择接近平均构象的结构；随后可用 OpenMM refinement 清理 clash，同时输出残基级误差估计。
- **输入输出：** 输入 VHH FASTA 或字符串；输出 PDB 和误差估计。适合批量处理上百到上万条候选 VHH，比通用 AlphaFold 类工具快很多。
- **VHH 使用范围：** 适合已知 VHH 序列的结构初建模、CDR3 loop 观察、结构聚类、后续 docking 前结构准备、人源化突变前后构象对比。
- **局限：** 只预测单体，不知道抗原在哪里；长 CDR3、非常规二硫键、训练集中稀有构象仍可能偏；单个模型给出的 CDR3 不能直接当作真实结合构象。
- **本地状态：** 代码已克隆；BSD-3-Clause；README 显示模型权重可用，适合作为第一批复现工具。

### 2.2 NanoNet（高价值 B 类：VHH 专项，但 license 需确认）

- **工具定位：** VHH/VH/TCR Vβ 快速结构预测模型，尤其适合 repertoire 级别批量结构化。
- **发布时间和后续：** 2022 年 Frontiers in Immunology。相对 NanoBodyBuilder2，它更像轻量级快速坐标回归器。
- **怎么训练/搭建：** 端到端深度学习模型，用 one-hot 序列编码和 1D ResNet/CNN 模块直接预测 backbone 和 Cβ 坐标。训练集包含约两千条 mAb heavy chain 与 nanobody 结构，独立 Nb 测试集中评估过低相似度纳米抗体。
- **输入输出：** 输入 VHH/VH 序列；输出 backbone/Cβ 坐标，必要时再用 Modeller/SCWRL 等补全侧链。
- **VHH 使用范围：** 适合大规模候选序列做粗结构、按 CDR3 空间构型聚类、先筛掉明显异常结构。速度和简单性是主要优势。
- **局限：** 原始输出不是完整高质量全原子模型；抗原复合物完全不处理；许可证偏研究用途，商业使用需要进一步确认。
- **本地状态：** 代码和论文 PDF 已下载，适合作为结构 baseline；但本地 `LICENSE.txt` 是 research-use 类型，不宜把它列为“完全开放可商用”的 A 类。

### 2.3 HeavyBuilder2

- **工具定位：** 单 heavy-chain 抗体结构预测/大规模 repertoire 结构化工具。对 VHH 项目有参考价值，但不是最专门的 VHH 工具。
- **发布时间和后续：** 2025 年左右公开，用于 heavy-chain-only/repertoire-scale 建模。
- **怎么训练/搭建：** 继承 ImmuneBuilder/ABodyBuilder2 的免疫受体结构预测思路，去掉 light chain 依赖，对单条 heavy chain 做结构预测。
- **输入输出：** heavy-chain FASTA/MiAIRR 类输入，输出 heavy-chain PDB。
- **VHH 使用范围：** 如果你的数据混有普通 VH、heavy-chain-only antibody、camelid VHH，可以作为统一建模工具；纯 VHH 场景仍优先 NanoBodyBuilder2/NanoNet。
- **局限：** 公开论文细节和 VHH 专项评估少于 NanoBodyBuilder2；仍不处理抗原复合物。
- **本地状态：** 代码已克隆，可作为第二个结构预测基线。

### 2.4 HADDOCK3 / HADDOCK antibody-antigen workflows

- **工具定位：** 信息驱动 docking，不是神经网络生成器。它适合在已有 VHH 结构和抗原结构时，用已知或预测的 epitope/paratope 约束来建复合物。
- **发布时间和后续：** HADDOCK 体系长期用于蛋白 docking；HADDOCK3 是新工作流版本，官方也有 nanobody-antigen 教程。
- **怎么训练/搭建：** 没有训练权重。核心是物理能量函数、采样和用户给定的 ambiguous interaction restraints。约束可来自突变、竞争实验、HDX、交联、NMR、AlphaFold/Chai/Boltz 预测界面等。
- **输入输出：** 输入 VHH PDB、抗原 PDB、active/passive residues 或约束文件、TOML workflow；输出 docking decoys、clusters、HADDOCK score、界面能量等。
- **VHH 使用范围：** 很适合把 NanoBodyBuilder2/Chai/Boltz 给出的结构假设再做约束 docking 和 cluster 验证。对于已知表位的 VHH 工程特别有用。
- **局限：** 没有约束时成功率会明显下降；输入结构和约束质量决定上限；计算和参数门槛高于一键式 co-folding。
- **本地状态：** `haddock3` 和抗体抗原示例仓库已克隆；Apache-2.0；无需模型权重。

### 2.5 Chai-1

- **工具定位：** 通用生物分子结构/复合物预测模型，可用于 VHH-抗原 co-folding，也可处理蛋白、小分子、核酸、糖基化等对象。
- **发布时间和后续：** 2024 年公开预印本和代码；定位类似开放的 all-atom/foundation structure model。
- **怎么训练/搭建：** 深度学习结构模型，使用类似现代结构模型的几何表示和 diffusion/denoising 思路；README 标明代码和模型权重采用 Apache-2.0，可用于学术和商业。
- **输入输出：** 输入蛋白链序列、MSA/约束/修饰等配置；输出结构模型、ranking/confidence 信息。VHH 可作为单条蛋白链，抗原作为另一条链。
- **VHH 使用范围：** 适合在没有明确表位时生成 VHH-Ag 复合物假设；也适合与 Boltz/AlphaFold-Multimer/HADDOCK 交叉比较。
- **局限：** 通用模型不是 VHH 专门训练；抗体-抗原界面缺少共进化信号，容易出现看似自信但界面错误的 pose；GPU 和依赖较重。
- **本地状态：** 代码已克隆；Apache-2.0；权重公开，优先级高。

### 2.6 Boltz-1 / Boltz-2

- **工具定位：** 开放 all-atom 结构预测模型，Boltz-2 还扩展到部分亲和力相关输出。可以作为 AlphaFold3/Chai-1 的开放替代或互证模型。
- **发布时间和后续：** Boltz-1 在 2024/2025 前后公开，Boltz-2 后续加入更强的结构和 affinity 相关能力。
- **怎么训练/搭建：** 训练数据包括 PDB/OpenFold distillation 等大规模结构数据；仓库提供推理和训练说明，训练全量模型需要约数百 GB 级数据和较大算力。
- **输入输出：** YAML/FASTA 类输入，链类型可为 protein/DNA/RNA/ligand；输出 mmCIF、confidence、PAE/PDE/pLDDT、Boltz-2 affinity/likelihood 类结果。
- **VHH 使用范围：** 可把 VHH 和抗原作为两条 protein chain 输入，用来生成复合物结构候选；也可与 Chai-1/AF-Multimer 的界面一致性做比较。
- **局限：** VHH-Ag affinity 不是 Boltz-2 最核心校准对象，不能把 affinity 输出直接当 KD；MSA、链顺序、sampling seed 和模板会影响结果。
- **本地状态：** 代码已克隆；MIT；README 表明代码和权重开放，可学术/商业使用。

### 2.7 RFantibody

- **工具定位：** 目前最值得优先学习的开源 VHH/scFv de novo 设计管线之一。它不是单纯预测结构，而是从靶标表位出发生成抗体/纳米抗体候选。
- **发布时间和后续：** Baker/RosettaCommons 生态，Nature 2025 论文；代码仓库提供 nanobody full pipeline 示例。
- **怎么训练/搭建：** 以 RFdiffusion 为骨架，在抗体-抗原复合物上微调生成 CDR backbone；随后用 ProteinMPNN 设计 CDR 序列，再用抗体微调 RoseTTAFold2 做自一致性结构预测/过滤。训练时会把 target hotspot 定义为离抗体 CDR 最近的目标残基，并随机遮盖一部分 hotspot 训练模型学会表位条件设计。
- **输入输出：** 输入靶标结构、hotspot/epitope、VHH 或 scFv framework、CDR 长度/采样参数；输出 docked backbone、CDR 序列、复合物模型和过滤分数。
- **VHH 使用范围：** 适合“已知抗原结构 + 想打某个表位 + 希望生成新 VHH”的场景。README 提到 nanobody 输出常出现 side-on dock，这是模型从天然 VHH 结合方式学到的现象，不一定是 bug。
- **局限：** 命中率依赖靶点、表位、筛选规模和过滤；作者也强调当前缺少足够可靠的过滤指标，一般设计 campaign 可能需要上万级候选；生成结果仍需表达、binding、SEC/DSF 等实验。
- **本地状态：** 代码已克隆；MIT；README 提供 `include/download_weights.sh` 和 nanobody pipeline，适合第一批复现。

### 2.8 AntiFold

- **工具定位：** 抗体 inverse folding 工具：给定抗体/VHH 结构，设计或评分能折叠到该结构的序列。
- **发布时间和后续：** 2024 arXiv/OPIG 工具，属于 OX Pig 抗体工具链。
- **怎么训练/搭建：** 基于 ESM-IF1 微调，训练结合 SAbDab 结构和 OAS paired sequences 中由 ABodyBuilder2 建模的结构。模型学习结构条件下每个位置的氨基酸概率。
- **输入输出：** 输入 PDB/抗体结构和需要设计的位置；输出采样序列、per-residue probability、perplexity/zero-shot mutation score。
- **VHH 使用范围：** 适合在固定 VHH scaffold 或固定 CDR backbone 后做序列重设计；也适合给突变打分，筛掉不符合结构的变体。
- **局限：** 不知道抗原，不能保证 binding；训练主要是抗体结构分布，不是 VHH 结合功能分布；要结合 TNP、结构预测和实验。
- **本地状态：** 代码已克隆；BSD-3-Clause；README 提供模型权重下载链接。

### 2.9 IgGM

- **工具定位：** 抗体/纳米抗体序列-结构联合生成模型，可覆盖 de novo、inverse design、affinity maturation、humanization、structure prediction 等多任务。
- **发布时间和后续：** ICLR 2025；TencentAI4S 开源仓库。
- **怎么训练/搭建：** 结合 diffusion model 与 consistency model 思路，把抗体/纳米抗体结构和序列作为联合对象建模；仓库包含推理和 checkpoint 使用说明。
- **输入输出：** 可输入抗原 PDB/epitope、framework、FASTA、任务配置；输出候选抗体/纳米抗体序列和结构，部分流程可接 PyRosetta relax。
- **VHH 使用范围：** 适合探索“一个模型做多种抗体工程任务”的思路；如果只做 VHH de novo binder，建议与 RFantibody/Germinal/NanoDesigner 横向比较。
- **局限：** wet-lab 命中率和失败案例公开透明度不如单一任务工具；不同任务的默认参数需要仔细读 README。
- **本地状态：** 代码已克隆；MIT；有 checkpoint/Zenodo 下载线索，优先级较高。

### 2.10 VHHBERT / VHHCorpus-2M（高价值 B 类：VHH 表征，但数据许可受限）

- **工具定位：** VHH 语言模型和数据集，不直接输出结构或复合物，而是提供 VHH 序列表征、embedding、突变分析和下游 binding prediction 的基础。
- **发布时间和后续：** 2024 arXiv/NeurIPS 数据集方向工作，仓库与 AVIDa-SARS-CoV-2 相关。
- **怎么训练/搭建：** RoBERTa/BERT-style masked language modeling，训练于超过 200 万条 alpaca VHH 序列；下游可 fine-tune 到 SARS-CoV-2 等 Nb-Ag 任务。
- **输入输出：** 输入 VHH 序列；输出 embedding、mask 位置概率、下游分类/回归模型分数。
- **VHH 使用范围：** 适合做 VHH 序列聚类、候选 embedding、变体打分、结合预测模型特征。它是“表征层”，通常要接分类器、结构工具或实验标签。
- **局限：** 语言模型学的是 VHH 序列分布，不直接学某个抗原的结合；SARS-CoV-2 benchmark 泛化到别的靶点需重新验证。
- **本地状态：** 代码和 PDF 已下载；代码是 MIT，但数据集/语料存在 CC BY-NC 条款，因此适合研究和建模理解，不应默认列入完全开放可商用主线。

### 2.11 BioPhi / Sapiens / OASis

- **工具定位：** 抗体人源化、人源性评分和 OAS human repertoire 对比工具。对 VHH 不是最专用，但可作为人源性辅助参考。
- **发布时间和后续：** BioPhi/Sapiens 论文约 2022 年；Merck 开源仓库。
- **怎么训练/搭建：** Sapiens 使用 OAS 中的人类抗体可变区序列训练语言模型/序列模型；OASis 统计序列片段在人类 repertoire 中的出现情况，辅助识别非人源片段。
- **输入输出：** 输入抗体/VH/VL 或相关序列；输出 humanization 建议、人源性分数、OASis identity/coverage 等。
- **VHH 使用范围：** 对 VHH 人源化可作辅助，但不能替代 VHH 专门方法，因为 VHH 的 FR2 hallmark、单域稳定性和 CDR3 特征与常规 VH/VL 不同。
- **局限：** 过度追求人源性可能破坏 VHH 溶解性或稳定性；建议和 AbNatiV/TNP/Llamanade/HuDiff-Nb 交叉使用。
- **本地状态：** BioPhi 和 Sapiens 代码已克隆。

### 2.12 Humatch

- **工具定位：** 抗体或 VHH human-likeness / humanization 辅助工具，属于 OPIG 生态。
- **怎么训练/搭建：** 基于序列相似性、human repertoire 或统计模型比较候选序列与人类抗体分布，定位不自然或非人源区域。
- **输入输出：** 输入可变区序列；输出匹配到的人源参考、位置级建议或分数。
- **VHH 使用范围：** 适合 VHH humanization 的早期筛选，尤其是和 AbNatiV/BioPhi/TNP 一起看“人源性 vs VHH 稳定性”的冲突位点。
- **局限：** 不是结合预测器，也不是 developability 总分；对 camelid VHH hallmark 的保护需要人为规则。
- **本地状态：** 代码已克隆；适合工具链补充。

### 2.13 alpseq

- **工具定位：** 针对 nanobody Illumina 2x300 数据的 Nextflow pipeline，从原始测序 reads 到候选序列和报告。
- **发布时间和后续：** 近年 VHH NGS 分析工具，适合展示库/免疫库筛选后处理。
- **怎么训练/搭建：** 不是深度学习模型，不需要权重；核心是 QC、read merge、过滤、翻译、CDR/候选统计和可视化报告。
- **输入输出：** 输入 FASTQ 和配置；输出清洗 reads、翻译后的 VHH 序列、候选表、统计图和 HTML/report。
- **VHH 使用范围：** 适合从免疫动物或展示库筛选轮次中快速整理 enriched clone；是实验数据进入计算筛选的入口。
- **局限：** 富集不等于结合；引物偏差、测序错误、display bias 和轮次设计会影响排序；后续仍需 ANARCI/IgBLAST、TNP 和实验验证。
- **本地状态：** 代码已克隆；GPL-3.0；无权重，复现门槛低。

### 2.14 phage-seq + nbseq

- **工具定位：** phage display/NGS 后的序列整理、feature table 和交互分析工具链。
- **怎么训练/搭建：** 规则和数据处理工具，不依赖模型权重；重点是把不同轮次、不同样本和 CDR3/AA 特征组织成可查询数据。
- **输入输出：** 输入 phage-seq reads、样本元数据、实验轮次；输出富集序列、CDR3 feature space、候选列表和可视化。
- **VHH 使用范围：** 适合 display panning 后找富集家族、代表 clone、轮次趋势；能和 NanoMAP/alpseq 互补。
- **局限：** 对实验设计依赖非常高；扩增偏差和 display fitness 可能制造假阳性；仍需 binding assay。
- **本地状态：** `phage-seq` 和 `nbseq` 仓库已克隆；无权重。

### 2.15 ANARCI

- **工具定位：** 抗体/免疫受体编号和 CDR 定位基础工具。几乎所有 VHH 流程都需要类似功能。
- **发布时间和后续：** 2016 Bioinformatics；OPIG 经典工具。
- **怎么训练/搭建：** 基于 HMMER/HMM profile，对输入序列匹配不同物种和链型的免疫受体 profile，然后按 IMGT/Chothia/Kabat/AHo 等规则编号。
- **输入输出：** 输入 FASTA；输出编号序列、chain type、domain 边界、CDR 区域、HMM hit 信息。
- **VHH 使用范围：** 用于定位 CDR1/2/3、过滤非抗体域、统一编号，为 TNP、structure modeling、humanization 和突变设计提供坐标系。
- **局限：** 不能单独判断某条 VH 是否一定是 camelid VHH；VHH-like hallmark、germline、自定义库和富集证据仍需额外判断。
- **本地状态：** 代码已克隆；BSD-like；无神经网络权重。

### 2.16 Immcantation / pRESTO / Change-O / airrflow

- **工具定位：** AIRR-seq/BCR repertoire 分析生态，适合 VHH NGS 数据的预处理、注释表标准化、克隆家族和 SHM 分析。
- **怎么训练/搭建：** 传统生信流程，无神经网络权重。pRESTO 处理 reads，Change-O 规范注释表和 clone assignment，airrflow 用 nf-core/Nextflow 串联工作流。
- **输入输出：** 输入 FASTQ/IgBLAST/MiXCR/AIRR 表；输出 AIRR TSV、clone assignment、lineage、多样性和 SHM 统计。
- **VHH 使用范围：** 适合免疫后 VHH repertoire、亲和力成熟轮次、展示库轮次的 clone family 分析。
- **局限：** 默认人/鼠 BCR/TCR 设置要改成 camelid/VHH germline、primer 和 CDR3 规则；不是 binding predictor。
- **本地状态：** 多个仓库已克隆；开源，无权重。

### 2.17 DeepNano

- **工具定位：** Nanobody-antigen interaction prediction，直接预测 VHH 序列和抗原序列是否相互作用。
- **发布时间和后续：** 2024 Nature Machine Intelligence。
- **怎么训练/搭建：** ensemble deep learning + prompt-based protein language model。仓库包含 DeepNano-seq、DeepNano-site、DeepNano 等模型和训练/预测脚本，训练使用 Nb-Ag interaction 数据、PPI 数据和蛋白语言模型表征。
- **输入输出：** 输入 nanobody FASTA、antigen FASTA 和 pair table；输出 interaction/PPI probability 或 score，也可用于大规模候选排序。
- **VHH 使用范围：** 适合“已有很多 VHH 序列 + 一个或多个抗原序列”时做候选预排序；尤其适合 NGS/展示库筛出来的候选过多时做第一层筛选。
- **局限：** sequence-only/PLM-based 模型难以可靠捕获构象表位、糖基化、抗原构象状态和实验体系；分数不是 KD。
- **本地状态：** 代码已克隆；MIT；README 提供模型权重下载链接。

### 2.18 Paragraph

- **工具定位：** 抗体 paratope 预测工具，预测哪些抗体/VHH 残基可能参与结合。
- **怎么训练/搭建：** 结构/图模型或几何特征模型，训练于抗体-抗原复合物中的 residue-level paratope 标注。
- **输入输出：** 输入抗体或 VHH 结构/模型；输出每个残基的 paratope probability。
- **VHH 使用范围：** 适合从 NanoBodyBuilder2/IgFold 结构中找可能参与结合的 CDR/FR 残基，为 HADDOCK 约束、突变扫描、表位竞争实验提供假设。
- **局限：** 训练数据主要来自常规抗体复合物；VHH 的 framework-mediated contact 和长 CDR3 可能导致阈值偏差。
- **本地状态：** 代码已克隆；适合作为 docking 前辅助工具。

### 2.19 TNP — Therapeutic Nanobody Profiler

- **工具定位：** VHH 专用 developability profiler，是性质预测里最应该优先看的一项。
- **发布时间和后续：** Communications Biology 2026。目标是把 TAP 类抗体 developability 思路重新校准到纳米抗体。
- **怎么训练/搭建：** 不是单一黑箱深度模型，而是面向 VHH 的 descriptor/profile 系统。它整合临床阶段纳米抗体、OAS、PLAbDab-nano、SAbDab、Thera-SAbDab 和实验性 VHH/Fc 表达/SEC 等数据，定义与 VHH 风险相关的阈值和特征。
- **输入输出：** 输入 VHH 序列；输出 developability descriptors、风险等级、异常残基/patch 定位、CDR/loop/charge/hydrophobicity 相关指标。
- **VHH 使用范围：** 适合 hit triage、lead optimization 前的风险定位、人源化或突变设计前后比较。对于 VHH 项目，它比通用 TAP 更合适。
- **局限：** 临床 VHH 样本数量仍有限；结构相关 patch 依赖预测结构质量；TNP 不是表达量、热稳定性、PK 或免疫原性的直接实验替代。
- **本地状态：** 代码和 PDF 已下载；BSD-3-Clause；优先复现。

### 2.20 ProtParam / Compute pI-Mw

- **工具定位：** 蛋白基础物化性质计算，不是 ML 模型，但非常实用。
- **怎么训练/搭建：** 确定性公式和经验参数：分子量、理论 pI、消光系数、GRAVY、instability index、aliphatic index 等。
- **输入输出：** 输入 VHH 氨基酸序列；输出 pI/Mw/组成/疏水性等基础表格。
- **VHH 使用范围：** 适合所有候选 VHH 的基础 QC、IEX/formulation 初步判断、标签/突变前后 Mw 和 pI 变化检查。
- **局限：** 理论 pI 不等于实验 pI；不考虑三维结构、二硫键、PTM、浓度、盐和 formulation。
- **本地状态：** 主要是网页工具，但算法本身可复现；建议作为每条 VHH 的基础字段。

---

## 3. B 类：代码公开但复现有条件，第二批看

### 3.1 IgFold

- **定位：** 快速抗体结构预测，明确支持 nanobody/heavy-only 输入，可作为 NanoBodyBuilder2 的对照模型。
- **方法和数据：** AntiBERTy 在约 5.58 亿天然抗体序列上预训练，再用结构模块从 embedding 预测 backbone；可接 Rosetta refinement。
- **用途范围：** 大批量 VHH 单体建模、比较 CDR3 构象、给 docking 或 developability 工具提供结构输入。
- **为什么放 B：** 代码和模型可用，但许可证是 JHU Academic Software License，商业用途要单独联系；不是 VHH-only 训练。
- **局限：** 不处理抗原；对人工设计、非天然 framework、超长 CDR3 的置信度要谨慎。

### 3.2 AlphaFold3 / AlphaFold Server

- **定位：** all-atom biomolecular interaction 模型，可建蛋白、核酸、小分子、离子、修饰残基等复合物；可用于 VHH-Ag co-folding。
- **方法和数据：** 以 PDB 多类型生物分子结构为核心训练数据，使用 diffusion/denoising 风格结构生成。
- **用途范围：** 当你有 VHH 序列和抗原序列/结构时，可作为复合物候选生成器；也可和 Chai-1/Boltz/HADDOCK 互证。
- **为什么放 B：** 代码已公开，但本地权重和使用条款不是完全无门槛；服务器/本地使用条件需要单独遵守。
- **局限：** 抗体-抗原界面共进化信号弱，容易出现高置信错误 pose；分数不等于亲和力。

### 3.3 AlphaFold-Multimer / ColabFold

- **定位：** AF2 多链复合物预测和高效前端。对 VHH-Ag 可跑，但不是抗体专用。
- **方法和数据：** AF-Multimer 扩展 AF2 到多链；ColabFold 用 MMseqs2 加速 MSA。
- **用途范围：** 生成复合物 baseline、检查不同 seed/stoichiometry 下界面是否稳定、与 docking 结果比较。
- **为什么放 B：** 可用性强，但 AF 参数/许可证和 MSA 依赖需要记录；VHH-Ag 不一定可靠。
- **局限：** Ab/Nb-Ag 复合物缺乏共进化，接口预测经常不稳；需要多 seed、多模型和实验约束。

### 3.4 AbNatiV / AbNatiV2

- **定位：** 抗体/纳米抗体 nativeness、humanness 和 residue-level profile 评估，是 VHH 人源化和 hit selection 的重要工具。
- **方法和数据：** VQ-VAE/深度序列表征，学习 OAS 等大规模 antibody/nanobody repertoire 的天然序列分布，含 human、mouse、camelid VHH 等模型。
- **用途范围：** 判断设计序列是否偏离天然 VHH 分布，定位异常残基，做 humanization 前后比较。
- **为什么放 B：** 代码/模型可用，但许可证 CC BY-NC-SA，商业用途受限。
- **局限：** nativeness/humanness 不是表达、稳定、聚集或免疫原性；不能单独最大化分数。

### 3.5 HuDiff / HuDiff-Nb

- **定位：** 抗体和纳米抗体人源化 diffusion 模型；HuDiff-Nb 面向 nanobody。
- **方法和数据：** 自回归 diffusion/denoising 生成 humanized variants；公开仓库包含训练脚本、数据处理和 checkpoint 下载线索。
- **用途范围：** 已有 camelid VHH binder，想做人源化但尽量保留结合和 nativeness 时使用。
- **为什么放 B：** 代码公开，但 PolyForm Noncommercial；部分数据/权重需要单独下载，商业复现受限。
- **局限：** 人源化不是亲和力成熟；生成序列必须再过 TNP、结构、MHC-II 和实验。

### 3.6 Germinal

- **定位：** epitope-targeted VHH/scFv 生成管线，和 RFantibody 类似但实现路线不同。
- **方法和数据：** 组合 ColabDesign/AF-Multimer hallucination、AbMPNN、AlphaFold/RF 类结构过滤；少量靶点有低通量验证。
- **用途范围：** 当你有抗原结构和表位，想比较不同设计生成器时可作为 RFantibody 的对照。
- **为什么放 B：** 代码 Apache-2.0，但依赖 PyRosetta、AF-Multimer/AF3 参数等外部组件，复现链条长。
- **局限：** 仍在 active development；公开靶点和失败案例有限；命中率不可直接外推。

### 3.7 NanoDesigner

- **定位：** VHH 专项 CDR 设计/优化 workflow，强调 CDR generation 与 docking 的联合迭代。
- **方法和数据：** EM-like 迭代框架，调用 IgFold、DockQ、Rosetta、FoldX、HDOCK、side-chain packing 等模块，评估 ΔG/ΔΔG 和 docking 改善。
- **用途范围：** 已有 nanobody scaffold、抗原结构和表位/复合物信息时，做局部 CDR 优化。
- **为什么放 B：** 代码公开但外部依赖多，部分依赖许可证复杂；不是一键复现。
- **局限：** 能量函数和 docking 近似不能替代亲和力实验；依赖初始表位/结构质量。

### 3.8 IgLM

- **定位：** 抗体 autoregressive language model，可做序列生成、补全和突变建议。
- **方法和数据：** 在约 5.58 亿 heavy/light antibody variable sequences 上训练语言模型。
- **用途范围：** 作为 VHH 序列生成/补全的参考模型，或给 CDR mutational library 提供语言模型概率。
- **为什么放 B：** JHU Academic Software License，偏非商业；不是 VHH 专用，也不感知抗原。
- **局限：** sequence-only；生成天然样式不等于结合、稳定或低免疫风险。

### 3.9 DiffAb

- **定位：** 抗原条件的抗体 CDR sequence/structure diffusion 生成模型。
- **方法和数据：** 训练于 SAbDab 抗体-抗原复合物，扩散生成 CDR 结构和序列。
- **用途范围：** 研究 CDR 生成模型时可参考；如果要用于 VHH，需要改 framework/链输入并验证。
- **为什么放 B：** 代码和权重公开线索存在，但默认是常规抗体，不是 VHH 专用。
- **局限：** 对 VHH 单域、framework contact 和超长 CDR3 的适配不确定。

### 3.10 GearBind / Graphinity / mCSM-AB2

- **定位：** 抗体-抗原突变亲和力变化预测或 affinity maturation ranking 工具。
- **方法和数据：** GearBind 用 geometric GNN，CATH 预训练 + SKEMPI fine-tuning；Graphinity 用 Siamese equivariant GNN；mCSM-AB2 用 graph signatures 和实验 mutation 数据。
- **用途范围：** 已有 VHH-Ag 复合物结构时，对 CDR 或界面突变做排序，帮助缩小实验库。
- **为什么放 B：** 部分代码公开，但训练数据不是 VHH 专用，泛化风险明显；mCSM-AB2主要是 web/server。
- **局限：** ΔΔG 模型误差大，不应单独决定突变；输入复合物结构错，排序就会错。

### 3.11 ABodyBuilder3 / ABlooper / DeepAb / H3-OPT / AbDockGen / DeepRank-Ab / BALMFold

- **定位：** 这些是结构预测、loop 建模、docking generation 或 docking ranking 的补充工具。
- **用途范围：** ABodyBuilder3 适合常规 VH/VL；ABlooper 做 CDR loop；DeepAb 是历史结构基线；H3-OPT 做 CDR-H3 loop 优化；AbDockGen/DeepRank-Ab 用于抗体-抗原 docking generation/ranking；BALMFold 是通用结构模型方向。
- **为什么放 B：** 多数不是 VHH 专用，或需要特定权重/外部依赖，适合作为方法学习和对照，不是 VHH 项目首选主线。
- **局限：** 不能替代 NanoBodyBuilder2/TNP/RFantibody 这类 VHH 更贴近的工具。

### 3.12 NanoMAP / MiXCR / IgDiscover / NABP-BERT / AbAgIntPre / ParaPred / EpiScan / ImaPEp

- **定位：** 识别/发现和 binding/epitope/paratope 预测补充工具。
- **用途范围：** NanoMAP 做 VHH repertoire/clonal family；MiXCR 做通用 BCR/TCR repertoire；IgDiscover 发现 germline；NABP-BERT/AbAgIntPre 做 sequence-level interaction；ParaPred 做 paratope；EpiScan/ImaPEp 做 epitope/paratope 相关预测。
- **为什么放 B：** 有代码，但有的许可证非商业、有的不是 VHH 专用、有的训练标签有限；适合在 A 类流程跑通后补充。
- **局限：** 富集或序列级 interaction 分数不能替代 binding assay；epitope/paratope prediction 只能提出假设。

---

## 4. C 类：后置了解，暂不作为本地复现主线

### 4.1 Chai-2、JAM-2、Latent-X2、TFDesign-sdAb、EasyNano、nanoFOLD

- **共同定位：** 前沿抗体/纳米抗体设计模型或公司/预印本平台，报告了较强的 zero-shot 或 epitope-targeted 设计能力。
- **为什么后看：** 当前没有稳定公开代码/权重，或主要是白皮书/论文/公司平台；不能作为“本地可复现模型”优先线。
- **仍然值得看什么：** 它们的任务设定、hit-rate 评价方式、wet-lab 验证格式、表位条件设计策略、失败案例定义。可以作为未来工具发展方向，而不是现在的主流程依赖。

### 4.2 Llamanade

- **定位：** VHH 人源化/工程化方法，基于 VHH 与人 IgG 序列/结构比较，提出人源化 mutation plan。
- **为什么后看：** 论文和方法重要，但本地公开可复现代码不如 HuDiff/AbNatiV/BioPhi 明确。
- **用途范围：** 已有 VHH binder 要做人源化时，可把 Llamanade 的保守位点思想作为人工规则参考，尤其注意不要破坏 VHH hallmark 和 solubility residues。

### 4.3 ClusPro / AbEMap / HDOCK / EpiPred-SAbPred / AbAdapt

- **定位：** 网页 docking、表位预测或 antibody-antigen workflow。
- **为什么后看：** 多数是 web/server 工具，不能完全本地复现；或者底层代码/参数不完全开放。
- **用途范围：** 快速提出 VHH-Ag docking/epitope 假设，给 HADDOCK3 或实验设计提供候选；适合做交叉验证而非单一结论。
- **局限：** rigid docking 对 VHH CDR3 和抗原柔性处理有限；web score 不是 affinity。

### 4.4 Aggrescan3D、CamSol、Protein-Sol/Abpred、IEDB/NetMHCIIpan、TAP、DynaMut2、FoldX、SOLart

- **定位：** developability、solubility、aggregation、MHC-II immunogenicity、mutation stability 等性质预测工具。
- **为什么后看：** 很多是网页服务、商业许可或独立二进制，不属于本地开源模型；但实际项目中仍然很有用。
- **用途范围：** A3D 看结构聚集 patch；CamSol/Protein-Sol 看溶解性；IEDB/NetMHCIIpan 看 HLA-II binding epitope；FoldX/DynaMut2 看突变稳定性；TAP 是常规抗体 developability 对照。
- **局限：** 所有这些都是 risk proxy，不是表达、SEC、Tm、DLS、HIC、ADA 或 PK 的替代。

### 4.5 IgBLAST、ProtParam 等官方/网页基础工具

- **定位：** IgBLAST 是 V(D)J/germline 注释基础工具；ProtParam 是基础物化计算。
- **为什么不是 A 类模型：** 它们不是本地深度模型，但算法/服务稳定、权威，仍应作为基础 QC 使用。
- **用途范围：** IgBLAST 适合自定义 camelid germline 做 V/D/J 和 junction 注释；ProtParam 适合所有 VHH 的 pI/Mw/GRAVY 基础表。

### 4.6 商业平台：BioLuminate、PipeBio、Tamarind Bio

- **定位：** 商业/云平台，把结构预测、docking、developability、NGS 和报告工作流包装起来。
- **为什么后看：** 闭源、版本和参数不透明，无法作为可复现开源模型；但可用于实际生产流程或对照。
- **使用注意：** 如果使用商业平台，必须导出输入、输出、底层工具版本、参数、数据库版本和失败样本，不要只保留黑箱总分。

---

## 5. 按任务选择工具：更实用的阅读路线

### 5.1 我只有 VHH 序列，想知道结构和风险

- **第一步：** ANARCI 编号，确认 CDR 区域和序列是否完整。
- **第二步：** NanoBodyBuilder2 和 NanoNet 建模；IgFold 可作为 B 类对照。
- **第三步：** TNP 做 VHH developability；ProtParam 做基础物化字段；A3D/CamSol/Protein-Sol 做补充。
- **第四步：** 如果要突变，先用 AntiFold 看结构兼容性，再用 FoldX/DynaMut2 粗筛稳定性。

### 5.2 我有 NGS/展示库数据，想找候选 VHH

- **第一步：** alpseq 或 phage-seq/nbseq 处理 reads 和富集。
- **第二步：** ANARCI/IgBLAST/MiXCR/Immcantation 做编号、VDJ、clone family、lineage 和 SHM。
- **第三步：** TNP/AbNatiV 过滤 developability/nativeness 异常。
- **第四步：** DeepNano/NABP-BERT 做序列级 Nb-Ag 预排序，但必须用 binding assay 确认。

### 5.3 我知道抗原结构，想设计新的 VHH

- **第一步：** 明确 target state、表位和不想碰的区域；没有表位时先用结构/功能位点/实验信息缩小范围。
- **第二步：** RFantibody 做主设计线；IgGM/Germinal/NanoDesigner 做对照或补充。
- **第三步：** Chai-1/Boltz/AF-Multimer/AF3 生成复合物假设；HADDOCK3 用表位/突变约束做 refinement。
- **第四步：** TNP、AntiFold、A3D/CamSol、IEDB/NetMHCIIpan 做风险过滤；保留序列多样性进入实验。

### 5.4 我有 binder，想做人源化或亲和力成熟

- **人源化：** HuDiff-Nb、AbNatiV、BioPhi/Sapiens、Humatch、Llamanade 思路一起看；不要单独最大化 humanness。
- **亲和力成熟：** 有复合物结构时用 GearBind/Graphinity/mCSM-AB2/FoldX 排序突变；没有结构时先做结构和复合物假设。
- **风险闭环：** 每个突变都要检查 TNP、聚集、溶解性、MHC-II epitope、表达/Tm/SEC 实验。

---

## 6. 读工具时最容易踩的坑

- **开源代码不等于可复现。** 还要看权重、许可证、训练数据、外部依赖、GPU 要求、输入格式和示例是否完整。
- **能跑 VHH 不等于为 VHH 校准。** 通用蛋白模型可以输入 VHH，但阈值、置信度和误差模式未必适合纳米抗体。
- **结构置信度不等于结合正确。** VHH-Ag co-folding 的错误常常看起来很自信，必须多模型、多 seed、docking 和实验互证。
- **序列自然性不等于可开发性。** AbNatiV/BioPhi/IgLM 类工具只能说明像不像训练分布，不能替代 TNP、聚集/溶解性和实验。
- **生成式命中率不可横向比较。** 每个论文的靶点、表位、筛选规模、实验格式、成功定义都不同。
- **商业或网页工具要记录版本。** 否则即使结果好，也很难复现和追责。

---

## 7. 建议你优先精读的 12 个工具

1. **NanoBodyBuilder2/ImmuneBuilder**：VHH 单体结构主线。
2. **NanoNet**：VHH 快速结构 baseline。
3. **TNP**：VHH developability 主线。
4. **RFantibody**：开源 VHH de novo 设计主线。
5. **AntiFold**：结构条件序列重设计。
6. **Chai-1**：开放复合物 co-folding。
7. **Boltz**：开放 AF3-like 结构/复合物模型。
8. **HADDOCK3**：约束 docking 和实验信息融合。
9. **ANARCI**：编号/CDR 定位基础设施。
10. **alpseq 或 phage-seq/nbseq**：NGS/展示库入口。
11. **DeepNano**：VHH-Ag 序列级候选排序。
12. **AbNatiV/HuDiff-Nb/BioPhi**：人源化与 nativeness 风险评估。

---

## 8. 本地资料怎么用

- 先从 `report/asset_inventory.md` 找本地代码和 PDF。
- 每个本地代码仓库优先读 `README.md`、`LICENSE`、`environment.yml`、`pyproject.toml`、`requirements.txt`。
- 如果要真正跑某个模型，先记录：代码 commit、模型权重 URL、数据库版本、输入 FASTA/PDB、随机种子、GPU、参数文件和输出目录。
- 对下载失败的论文 PDF，见 `report/missing_pdfs.md`。这些没有绕过 403/反爬/付费墙，只保留了链接和失败原因。
