# 纳米抗体/VHH 工具开源可复现优先级分层说明

生成日期：2026-07-06  
工作目录：`/mnt/d/work/抗体/tools/nanobody_tool_survey`  
本文件只基于只读清单、已下载/已克隆资产和公开网页/仓库/论文链接整理；未移动 `papers/` 或 `code/`，未修改现有生成脚本。

## 0. 判定口径与证据路径

### 0.1 请求类型

综合研究：在已有纳米抗体/VHH 工具清单上，补充“开源可复现优先级分层”和 A 类工具的用途范围、输入输出、训练/构建方式、VHH 适用场景与局限。

### 0.2 本地证据

- 工具全集来自 `metadata/asset_manifest.py`，共 69 个条目。
- 下载/克隆状态来自 `metadata/asset_download_results.json`：论文 PDF 下载成功、失败原因、代码 clone 路径、短 commit head 都以该文件为准。
- 代码可复现性优先看本地 clone 中的 `README*`、`LICENSE*`、环境文件、权重/数据下载说明；本报告不重新下载权重、不构建环境。

### 0.3 分层规则

- **A 完全开源/本地可复现优先**：公开代码已在本地 clone；核心推理或流程有开放许可证或常见开源许可证；权重/示例/构建方式在 README 中可获得，或方法本身不依赖专有权重；没有强制闭源商业组件作为核心路径。A 类仍可能有 GPU/数据库/环境成本，也仍需实验验证。
- **B 代码公开但暂时后看**：代码公开或部分 clone 成功，但存在非商业/研究用途 license、模型权重/训练数据另行授权、缺少 license、强依赖 PyRosetta/FoldX/HDOCK/Schrodinger/AF3 参数等受限组件，或工具目标与 VHH 当前主线间接相关。
- **C 闭源/网页/商业/不可复现或仅论文**：manifest 中没有公开代码仓库，主要是网页服务、商业/闭源二进制、申请制服务、仅论文/预印本，或本地无法形成可审计的 open-source pipeline。

### 0.4 重要解释

本分层是“先做什么更可复现”的工程优先级，不是科学价值排名。C 类网页工具和 B 类受限工具仍可能很有用，但不适合作为第一批本地、可审计、可自动化的 VHH 报告主干。

## 1. 分层总览

### A. 完全开源/本地可复现优先

| 阶段 | 工具 | 为什么进 A | 本地资产/公开证据 |
|---|---|---|---|
| VHH/重链单体结构 | NanoBodyBuilder2 / ImmuneBuilder | BSD-3-Clause；VHH 专项模型；本地 clone 和论文 PDF 均有 | `code/structure/nanobodybuilder2_immunebuilder/oxpig__immunebuilder`；https://github.com/oxpig/ImmuneBuilder；https://www.nature.com/articles/s42003-023-04927-7 |
| 重链结构/大规模 repertoire | HeavyBuilder2 | BSD-3-Clause；本地 clone；适合 heavy-chain-only 批处理 | `code/structure/heavybuilder2/oxpig__heavybuilder2`；https://github.com/oxpig/HeavyBuilder2 |
| VH/VL 结构补充 | ABodyBuilder3 | Apache-2.0；权重/数据在 Zenodo；可本地构建，但非 VHH 首选 | `code/structure/abodybuilder3/exscientia__abodybuilder3`；https://github.com/exscientia/abodybuilder3；https://academic.oup.com/bioinformatics/article/40/10/btae576/7810444 |
| CDR loop | ABlooper | BSD-3-Clause；CDR loop 专项；无强制商业组件 | `code/structure/ablooper/oxpig__ablooper`；https://github.com/oxpig/ABlooper；https://academic.oup.com/bioinformatics/article/38/7/1877/6517780 |
| 通用复合物 co-folding | AlphaFold-Multimer / ColabFold | AlphaFold2/ColabFold 可本地运行，代码和参数许可公开；资源成本高但可审计 | `code/structure/colabfold_alphafold_multimer/`；https://github.com/sokrypton/ColabFold；https://github.com/google-deepmind/alphafold；https://www.nature.com/articles/s41592-022-01488-1 |
| 通用复合物 co-folding | Chai-1 | Apache-2.0；README 声明代码和模型权重均 Apache-2.0；权重可自动下载 | `code/structure/chai1/chaidiscovery__chai-lab`；https://github.com/chaidiscovery/chai-lab；https://www.biorxiv.org/content/10.1101/2024.10.10.615955v2 |
| 通用复合物/亲和力 | Boltz-1 / Boltz-2 | MIT；README 声明代码和权重均 MIT、可商用；提供预测和训练文档 | `code/structure/boltz/jwohlwend__boltz`；https://github.com/jwohlwend/boltz；https://pmc.ncbi.nlm.nih.gov/articles/PMC11601547/ |
| 信息驱动 docking | HADDOCK3 + antibody-antigen scripts | Apache-2.0；不依赖学习权重；有 nanobody-antigen 教程和 antibody-antigen workflow | `code/structure/haddock3/`；https://github.com/haddocking/haddock3；https://github.com/haddocking/HADDOCK-antibody-antigen；https://www.bonvinlab.org/education/HADDOCK3/HADDOCK3-nanobody-antigen/ |
| Ab-Ag docking/design baseline | AbDockGen | MIT；ckpts 在仓库内；SAbDab/RAbD 数据处理流程公开 | `code/structure/abdockgen/wengong-jin__abdockgen`；https://github.com/wengong-jin/abdockgen；https://proceedings.mlr.press/v162/jin22a.html |
| docking 结果排序 | DeepRank-Ab | Apache-2.0；自动 PDB→DockQ/质量标志推理管线；适合作为 docking 后处理 | `code/structure/deeprank_ab/haddocking__deeprank-ab`；https://github.com/haddocking/DeepRank-Ab |
| de novo VHH/scFv 设计 | RFantibody | MIT；README 声明 non-profit/for-profit 均可用；有 nanobody full pipeline 和下载权重脚本 | `code/design/rfantibody/rosettacommons__rfantibody`；https://github.com/RosettaCommons/RFantibody；https://www.nature.com/articles/s41586-025-09721-5 |
| antibody/nanobody 生成 | IgGM | MIT；权重可自动下载；README 有 nanobody structure/design/humanization examples | `code/design/iggm/tencentai4s__iggm`；https://github.com/TencentAI4S/IgGM；https://openreview.net/forum?id=zmmfsJpYcq |
| inverse folding | AntiFold | BSD-3-Clause；模型下载链接公开；输入结构输出序列概率/采样序列 | `code/design/antifold/oxpig__antifold`；https://github.com/oxpig/AntiFold；https://arxiv.org/abs/2405.03370 |
| 人源性/可开发性 | BioPhi / Sapiens | MIT；BioConda/Docker/CLI/web 均有；适合 humanness/OASis/Sapiens baseline | `code/design/biophi/merck__biophi`；`code/design/biophi/merck__sapiens`；https://github.com/Merck/BioPhi；https://github.com/Merck/Sapiens；https://pmc.ncbi.nlm.nih.gov/articles/PMC8837241/ |
| 人源化 | Humatch | BSD-3-Clause；本地安装；基因特异 humanisation | `code/design/humatch/oxpig__humatch`；https://github.com/oxpig/Humatch；https://pmc.ncbi.nlm.nih.gov/articles/PMC11610552/ |
| paired antibody sequence generator | IgCraft | MIT；Hugging Face/Zenodo 权重数据；但偏 paired human antibody，VHH 只作参考 | `code/design/igcraft/mgreenig__igcraft`；https://github.com/mgreenig/igcraft；https://arxiv.org/abs/2503.19821 |
| 结构 ddG/亲和力变化 | Graphinity | BSD-3-Clause；示例、训练/推理配置和部分权重/数据路径公开；用于 Ab-Ag ddG 研究 | `code/design/graphinity/oxpig__graphinity`；https://github.com/oxpig/Graphinity；https://www.nature.com/articles/s43588-025-00823-8 |
| VHH NGS pipeline | alpseq | GPL-3.0；Nextflow pipeline；明确用于 Illumina 2x300 bp nanobody sequencing | `code/identification/alpseq/kzeglinski__alpseq`；https://github.com/kzeglinski/alpseq；https://pmc.ncbi.nlm.nih.gov/articles/PMC12885427/ |
| VHH phage-seq processing | phage-seq + nbseq | nbseq MIT；Snakemake workflow；用于 nanobody/VHH sequencing feature tables | `code/identification/phage_seq_nbseq/`；https://github.com/caseygrun/nbseq；https://github.com/caseygrun/phage-seq |
| 编号/链型识别 | ANARCI | BSD-like license；抗体/TCR numbering 和 receptor class identification；VHH 注释必备基础件 | `code/identification/anarci/oxpig__anarci`；https://github.com/oxpig/ANARCI；https://academic.oup.com/bioinformatics/article/32/2/298/1744206 |
| AIRR repertoire | Immcantation / pRESTO / Change-O / airrflow | AGPL/GPL/nf-core；AIRR 生态成熟；适合 BCR repertoire 标准化处理 | `code/identification/immcantation/`；https://immcantation.readthedocs.io/；https://github.com/immcantation/presto；https://github.com/immcantation/changeo；https://github.com/nf-core/airrflow |
| germline discovery | IgDiscover | MIT-like license；GitLab docs；用于从 repertoire 发现 V genes | `code/identification/igdiscover/gkhlab__igdiscover22`；https://gitlab.com/gkhlab/igdiscover22；https://gkhlab.gitlab.io/igdiscover22/ |
| Nb-Ag sequence/site prediction | DeepNano | MIT；README 声明代码和模型权重均在仓库；DeepNano-seq/site/interaction 三类模型 | `code/identification/deepnano/ddd9898__deepnano`；https://github.com/ddd9898/DeepNano；https://doi.org/10.1038/s42256-024-00940-5 |
| Ab-Ag sequence binding | AbAgIntPre | Apache-2.0；模型代码/数据目录公开；序列级 antibody-antigen interaction baseline | `code/identification/abagintpre/emerson106__abagintpre`；https://github.com/emersON106/AbAgIntPre；https://pmc.ncbi.nlm.nih.gov/articles/PMC9813736/ |
| paratope prediction | Paragraph | BSD-3-Clause；预训练权重在仓库；输入结构输出 paratope 概率 | `code/identification/paragraph/oxpig__paragraph`；https://github.com/oxpig/Paragraph；https://academic.oup.com/bioinformatics/article/39/1/btac732/6825310 |
| paratope prediction | ParaPred / parapred-pytorch | 原始和 PyTorch 版均有权重；PyTorch 版 MIT；适合作历史 baseline | `code/identification/parapred/`；https://github.com/eliberis/parapred；https://github.com/alchemab/parapred-pytorch；https://academic.oup.com/bioinformatics/article/34/17/2944/4972995 |
| epitope mapping | EpiScan | MIT；训练模型在仓库；病毒蛋白 antibody-specific epitope sequence mapping | `code/identification/episcan/gzbiomedical__episcan`；https://github.com/gzBiomedical/EpiScan；https://www.nature.com/articles/s41540-024-00432-7 |
| VHH developability | TNP / Therapeutic Nanobody Profiler | BSD-3-Clause；VHH/Nb 专项 developability profiler；本地 code clone | `code/properties/tnp/oxpig__tnp`；https://github.com/oxpig/TNP；https://www.nature.com/articles/s42003-026-09594-y |

### B. 代码公开但权重/数据/license/依赖受限，暂时后看

| 工具 | 后看原因 | 仍可保留的用途 |
|---|---|---|
| NanoNet | `LICENSE.txt` 是 research-use license，明确排除直接/间接商业获益；虽是 VHH 专项但不是完全开源许可。证据：https://github.com/dina-lab3D/NanoNet | 学术内部 VHH 单体建模对照；与 NanoBodyBuilder2 交叉验证。 |
| IgFold | JHU Academic Software License；README 写明 code 和 pre-trained models 仅 non-commercial use。证据：https://github.com/Graylab/IgFold | 快速 nanobody/VH baseline；但商业/转化项目需先处理授权。 |
| DeepAb | Rosetta-DL non-commercial license；非 VHH 专项。证据：https://github.com/RosettaCommons/DeepAb | 历史抗体结构 baseline；不作第一批 VHH 主线。 |
| H3-OPT | 依赖 AbRSA 下载和 Schrodinger Python API；局部 CDR-H3 优化强但环境/商业依赖限制明显。证据：https://github.com/chenhd21/H3-OPT；https://elifesciences.org/articles/91512 | 有 CDR-H3 局部优化需求时作为专门候选。 |
| RosettaAntibody3 / SnugDock | Rosetta/PyRosetta 授权和安装复杂；manifest 未 clone 代码；但论文/文档支持 single-domain/camelid 场景。证据：https://docs.rosettacommons.org/docs/latest/application_documentation/antibody/antibody-protocol；https://pmc.ncbi.nlm.nih.gov/articles/PMC7993800/ | 高分辨率 docking/refinement；需要 Rosetta 许可后再纳入。 |
| AlphaFold 3 / AlphaFold Server | 源码 Apache-2.0，但模型参数必须从 Google 获得且受 `WEIGHTS_TERMS_OF_USE.md` 非商业条款约束；server 也不是本地可审计。证据：https://github.com/google-deepmind/alphafold3；https://www.nature.com/articles/s41586-024-07487-w；https://alphafoldserver.com/ | VHH-Ag co-folding 强对照；内部非商业研究可用，生产/商业需授权。 |
| BALMFold | 推理代码公开，但 README 要从 Google Drive 下载预训练权重；VHH 项目中主要是抗体语言模型/结构补充。证据：https://github.com/beam-labs/balm | 抗体结构/功能预测对照；先不作为主线。 |
| NanoDesigner | GitHub clone 缺少明确 LICENSE；流程依赖 IgFold、HDOCK、Rosetta、FoldX 等多外部组件。证据：https://github.com/bio-ontology-research-group/NanoDesigner；https://pmc.ncbi.nlm.nih.gov/articles/PMC12333243/ | 有 scaffold+epitope 的 VHH CDR 设计想法时阅读方法，但落地前先清授权/依赖。 |
| Germinal | 仓库 Apache-2.0，但 README 明确 PyRosetta、IgLM、AF3/Protenix/Chai 等组件需单独许可/权重；active development。证据：https://github.com/SantiagoMille/germinal；https://www.biorxiv.org/content/10.1101/2025.09.19.677421v1 | epitope-targeted de novo VHH 设计可作为方法参考；等依赖策略确定后再运行。 |
| TFDesign-sdAb | Nature 文章的 Code availability 指向 IgGM-FR 和 A2Binder/PALM 组件，但 manifest 没有本地 clone，且不是一个已打包在资料包中的单一可复现 pipeline。证据：https://www.nature.com/articles/s41421-025-00843-8；https://github.com/TencentAI4S/IgGM；https://github.com/TencentAILabHealthcare/PALM | sdAb tailored design 方法值得跟踪；若要落地，先补 clone、license、权重和组件版本。 |
| DiffAb | Apache-2.0 代码，但设计新抗原时需要 HDOCK；relax/能量需要 PyRosetta；权重在 Hugging Face/Google Drive。证据：https://github.com/luost26/diffab；https://openreview.net/forum?id=jSorGn2Tjg | 抗原特异 CDR 生成基线；受限依赖解决后再跑。 |
| IgLM | JHU Academic Software License，non-commercial；预训练数据另行下载。证据：https://github.com/Graylab/IgLM | 抗体语言模型 baseline；可作为 Germinal/序列生成依赖的风险点。 |
| VHHBERT / AVIDa-SARS-CoV-2 | 代码 MIT，但数据集 README 标明 CC BY-NC 4.0；更像数据/benchmark，不是直接工具。证据：https://github.com/cognano/AVIDa-SARS-CoV-2；https://arxiv.org/abs/2405.18749 | SARS-CoV-2 VHH interaction 数据与预训练语料参考。 |
| AbNatiV / AbNatiV2 | LICENSE 是 CC BY-NC-SA 4.0，README 明确不能商业使用。证据：https://gitlab.doc.ic.ac.uk/sormanni-lab/abnativ；https://www.nature.com/articles/s42256-023-00778-3 | VHH nativeness/humanization 很重要，但先作为学术评估工具。 |
| HuDiff / HuDiff-Nb | PolyForm Noncommercial License；虽提供 Nb humanization 模型和数据，但非商业限制。证据：https://github.com/TencentAI4S/HuDiff；https://www.biorxiv.org/content/10.1101/2024.10.22.619416v1 | VHH humanization 方法参考；商业或转化前需授权。 |
| NanoMAP | VHH 分析代码公开，但 `LICENSE.txt` 为 CC BY-NC-SA 4.0。证据：https://github.com/wlwhite-tufts/NanoMAP；https://pmc.ncbi.nlm.nih.gov/articles/PMC13001438/ | 学术 VHH 序列处理/可视化参考；不作为完全开源主线。 |
| MiXCR | 功能成熟，但本地 `LICENSE` 是 Academic User / academic-only EULA，不是开源许可证。证据：https://github.com/milaboratory/mixcr；https://mixcr.com/mixcr/reference/overview-analysis-overview/ | AIRR/BCR repertoire 标准工具；授权确认后可用于生产流程。 |
| NABP-BERT | clone 中未见明确 license；README 要从 Google Drive 下载模型。证据：https://github.com/FMoonlightS/NABP-BERT；https://academic.oup.com/bib/article/26/1/bbae518/7926359 | 纳米抗体-抗原序列 binding 预测对照；需补 license/weights 可追溯性。 |
| GearBind | Apache-2.0 代码，但自有复合物使用需 FoldX 处理；README 明示部分 FoldX 生成结构因 license 不能提供。证据：https://github.com/DeepGraphLearning/GearBind；https://www.nature.com/articles/s41467-024-51563-8 | 蛋白-蛋白 ddG 参考；VHH-Ag 需谨慎外推。 |
| ImaPEp | clone 中未见明确 LICENSE；虽然模型和训练/预测脚本在仓库，但授权不可判定。证据：https://github.com/3BioCompBio/ImaPEp；https://www.mdpi.com/1422-0067/25/10/5434 | paratope-epitope pair probability 参考；先补授权信息。 |

### C. 闭源/网页/商业/不可复现或仅论文，暂时后看

| 工具 | 后看原因 | 可保留用途 |
|---|---|---|
| ClusPro / AbEMap | manifest 无 code；主要是网页/服务和论文协议。证据：https://pmc.ncbi.nlm.nih.gov/articles/PMC10898366/；https://cluspro.org/help.php | 快速网页 docking/epitope 参照，不作本地可复现主干。 |
| HDOCK | manifest 无 code；通常是网页/二进制而非开源代码。证据：https://pmc.ncbi.nlm.nih.gov/articles/PMC5793843/ | DiffAb/NanoDesigner 等依赖项或 docking 对照。 |
| Chai-2 | manifest 无 code；预印本/网页信息优先，不能本地复现。证据：https://www.biorxiv.org/content/10.1101/2025.07.05.663018v1.full-text | 作为最新设计方向追踪。 |
| Latent-X2 | manifest 无 code，仅 arXiv。证据：https://arxiv.org/abs/2512.20263 | 论文阅读，不纳入自动化。 |
| JAM-2 | manifest 无 code；Nabla PDF/商业主体，缺少可审计实现。证据：https://nabla-public.s3.us-east-1.amazonaws.com/2025_Nabla_JAM2.pdf | 高层方法/实验结果参考。 |
| EasyNano | manifest 无 code，仅 arXiv。证据：https://arxiv.org/abs/2606.12772 | 等公开代码后再评估。 |
| nanoFOLD | manifest 无 code，仅预印本。证据：https://www.biorxiv.org/content/10.1101/2025.04.29.651236v1 | VHH inverse folding 方向参考。 |
| Llamanade | manifest 无 code。证据：https://pmc.ncbi.nlm.nih.gov/articles/PMC8351782/ | 方法阅读。 |
| mCSM-AB2 | manifest 无 code，主要网页/服务。证据：https://academic.oup.com/bioinformatics/article/36/5/1453/5607734 | 抗体突变亲和力网页对照。 |
| IgBLAST | NCBI 官方工具很有用，但不是 manifest 中的开源代码 clone；本分层按“非完全开源”后看。证据：https://www.ncbi.nlm.nih.gov/igblast/ | 免疫受体 V(D)J 注释标准对照。 |
| EpiPred / SAbPred | manifest 无 code，主要 OPIG/SAbPred web server 和论文。证据：https://academic.oup.com/nar/article/44/W1/W474/2499346 | epitope/paratope 网页对照。 |
| AbAdapt | manifest 无 code。证据：https://academic.oup.com/bioinformaticsadvances/article/2/1/vbac015/6543605 | adaptive immune receptor/antibody sequence 分析参考。 |
| Aggrescan3D / A3D 2.0 | manifest 无 code，主要 web server。证据：https://academic.oup.com/nar/article/47/W1/W300/5485072 | 聚集风险网页对照。 |
| CamSol | manifest 无 code，网页/方法页。证据：https://www-vendruscolo.ch.cam.ac.uk/camsolmethod.html | 溶解性 proxy 对照。 |
| ProtParam / Compute pI/Mw | ExPASy 网页服务，公式可复现但不是本清单开源代码。证据：https://web.expasy.org/protparam/；https://web.expasy.org/compute_pi/ | pI/MW/理化性质快速对照。 |
| IEDB / NetMHCIIpan | web/server/服务条款，不是本地开源 clone。证据：https://tools.iedb.org/；https://services.healthtech.dtu.dk/services/NetMHCIIpan-4.3/ | 免疫原性/MHC-II 风险筛查对照。 |
| TAP / Therapeutic Antibody Profiler | manifest 无 code；web server。证据：https://pmc.ncbi.nlm.nih.gov/articles/PMC6410772/；https://opig.stats.ox.ac.uk/webapps/sabdab-sabpred/sabpred/tap | developability 网页对照；VHH 用 TNP 优先。 |
| Protein-Sol / Abpred | manifest 无 code；网页服务。证据：https://protein-sol.manchester.ac.uk/；https://protein-sol.manchester.ac.uk/abpred | 溶解性/抗体属性网页对照。 |
| DynaMut2 | manifest 无 code；网页服务。证据：https://biosig.lab.uq.edu.au/dynamut2/ | 突变稳定性网页对照。 |
| FoldX | 商业/授权工具；manifest 无 code。证据：https://foldxsuite.crg.eu/products；https://pmc.ncbi.nlm.nih.gov/articles/PMC1160148/ | 作为 NanoDesigner/GearBind/Graphinity 相关依赖或 ddG 对照，授权后再用。 |
| SOLart | manifest 无 papers/code_urls；本地清单无可追溯来源。 | 暂不纳入，除非后续补来源。 |

## 2. A 类工具的用途范围、输入输出、训练/构建方式与 VHH 场景

### 2.1 VHH/重链单体结构与 loop 建模

| 工具 | 用途范围 | 输入 -> 输出 | 训练/构建方式 | 适合的 VHH 场景 | 局限 |
|---|---|---|---|---|---|
| NanoBodyBuilder2 / ImmuneBuilder | 从 VHH/抗体/TCR 序列快速预测单体结构，给出 ensemble 和误差估计 | VHH 序列/FASTA -> PDB、误差/置信信息 | 论文和 README 描述为免疫受体专用深度学习模型；代码 BSD；本地 `setup.py`；权重随包或按包逻辑获取 | VHH 候选批量建模、CDR3 构象初筛、docking 前单体结构准备、结构聚类 | 不预测抗原复合物；长/非典型 CDR3、额外二硫键、训练集稀有框架仍要用多模型和实验/结构约束复核 |
| HeavyBuilder2 | high-throughput heavy-chain-only 结构化分析 | heavy-chain/VHH-like 序列或 repertoire -> heavy-chain PDB/结构特征 | 基于 ImmuneBuilder 系列；BSD；本地 `setup.py` | 大规模重链 repertoire 结构空间分析；当输入不确定是否 camelid VHH 时可作快速补充 | 不是 VHH 专项首选；VHH hallmark、长 CDR3 和抗原界面仍需 NanoBodyBuilder2/实验信息复核 |
| ABodyBuilder3 | 常规 VH/VL Fv 结构预测增强版 | VH/VL 序列 -> Fv PDB、模型不确定性 | Apache；README 指向 Zenodo 数据/模型权重；OpenFold 相关依赖 | 对照普通抗体 Fv 或从 VHH 项目扩展到 scFv/VH-VL 时使用 | VHH 无 light chain，直接优先级低；权重/数据体积和 OpenFold 依赖增加复现成本 |
| ABlooper | CDR loop 尤其 H3 loop 建模/重建 | 抗体/VHH 结构或序列上下文 -> loop 坐标/PDB | Equivariant graph neural network；BSD；本地安装简单 | 修补 VHH 单体模型中 CDR3 局部、比较多个结构模型的 loop 差异 | 只解决 loop，不解决整体 VHH-Ag pose；loop 质量依赖上下文结构和编号一致性 |

### 2.2 VHH-抗原复合物建模、docking 和排序

| 工具 | 用途范围 | 输入 -> 输出 | 训练/构建方式 | 适合的 VHH 场景 | 局限 |
|---|---|---|---|---|---|
| ColabFold / AlphaFold-Multimer | 多链 co-folding baseline，生成 VHH-Ag 候选复合物 | 多链 FASTA/MSA -> PDB/mmCIF、pLDDT、PAE、ipTM/pTM | AlphaFold2/Multimer 参数和数据库下载；ColabFold 用 MMseqs2 加速 MSA；代码公开 | 无表位约束时快速生成一批 pose；与 HADDOCK/Chai/Boltz 交叉验证 | 抗体-抗原缺少共进化，ipTM/PAE 可能高置信错 pose；本地数据库约 100GB-1TB 级；seed/MSA/模板敏感 |
| Chai-1 | 通用多模态结构/复合物预测，支持蛋白、小分子、核酸、糖基化等 | FASTA/结构输入、可选 MSA/template/restraint -> PDB/置信分数 | Apache-2.0；README 说明权重自动下载，默认可不用 MSA；可用 MSA/template server 增强 | VHH-Ag co-folding、含非蛋白组分的靶标对照、与 Boltz/AF-Multimer 取共识 | 非 VHH 专项；interface 置信度不等于亲和力；默认无 MSA 时需更多交叉验证 |
| Boltz-1 / Boltz-2 | all-atom biomolecular interaction prediction；Boltz-2 还给 affinity 相关输出 | YAML/FASTA/分子描述 -> 结构、binder/affinity 相关输出 | MIT；README 声明代码和权重 MIT；有 prediction/training docs | VHH-Ag 复合物候选、与 Chai/AF 系列对照；小分子/蛋白多组分项目也可复用 | Boltz-2 affinity 主要不能直接等价为 VHH-Ag KD；VHH 特异训练偏置未知；仍需实验/约束过滤 |
| HADDOCK3 + antibody-antigen | 信息驱动 docking/refinement，利用 paratope/epitope/restraints | VHH 结构 + 抗原结构 + active/passive residues/TOML -> decoys、cluster、HADDOCK score | 无训练权重；Apache；CNS/HADDOCK 环境；nanobody-antigen 教程和 antibody-antigen script | 已知或预测表位、已有单体结构、需要把实验信息融入 docking 的场景 | 无约束 blind docking 成功率有限；输入结构和约束质量决定结果；score 不是亲和力 |
| AbDockGen | antibody-antigen docking 与 CDR 设计 baseline | renumbered PDB/JSONL -> docked pose 或生成序列/结构 | MIT；README 指明 SAbDab 数据、IMGT renumber、ckpts 推理命令 | 作为 ML docking/design 历史 baseline；小规模对照 VHH-Ag pose | 训练以传统 Ab-Ag 为主；VHH 特异性弱；依赖旧 CUDA/PyTorch 版本 |
| DeepRank-Ab | docking decoy ranking 和 DockQ 预测 | PDB/ensemble -> DockQ score、质量标志、排序 | Apache；README 描述自动结构处理和 pretrained EGNN inference | HADDOCK/ClusPro/AF/Chai/Boltz 生成多 pose 后的统一排序辅助 | 预印本/新工具；ranking 不能替代实验；VHH 外推需校准 |

### 2.3 de novo 设计、inverse folding、人源化/可开发性

| 工具 | 用途范围 | 输入 -> 输出 | 训练/构建方式 | 适合的 VHH 场景 | 局限 |
|---|---|---|---|---|---|
| RFantibody | epitope-targeted de novo antibody/nanobody design | target PDB、framework PDB、hotspots/CDR 配置 -> RFdiffusion dock、ProteinMPNN 序列、RF2/Quiver score | MIT；`include/download_weights.sh`；Docker/Apptainer/uv；README 有 `nanobody_full_pipeline.sh` | 已有靶标结构和表位假设，要生成 VHH/scFv binder；适合做大规模设计池 | GPU/存储成本高；作者 README 指出 filter 仍是主要限制，常需 10k 量级设计；生成不等于表达/亲和力 |
| IgGM | antibody/nanobody 结构预测、CDR 设计、epitope design、humanization | nanobody framework/FASTA、抗原 PDB、epitope -> 序列和结构；可选 relax | MIT；权重可自动下载；PyRosetta relax 可选但受限 | 快速尝试 VHH CDRH3/CDR loop 设计、反向设计、结构预测、人源化候选 | 新模型，实验命中率需按靶点验证；若启用 PyRosetta relax 会引入授权约束 |
| AntiFold | antibody inverse folding，给定结构采样适配序列并输出 residue likelihood | VHH/抗体 PDB -> CSV residue log-likelihood、FASTA sampled sequences | BSD；ESM-IF1 fine-tuned on SAbDab/OAS；model.pt 公开下载 | 固定 VHH backbone 或 docking pose 后做 CDR/框架序列重设计、mutation scoring | 不是 VHH-only；inverse folding 保结构不保证结合；输入编号/结构缺失会影响结果 |
| BioPhi / Sapiens | humanness/OASis/Sapiens 人源化与抗体语言模型评估 | VH/VL/VHH-like 序列 -> humanness、OASis identity、suggested mutations | MIT；Docker/Conda/PyPI；Sapiens 模型包公开 | VHH humanization 初筛、human-like 过滤、设计序列可开发性报告 | 主要从 human antibody repertoire 学习；VHH 人源性和免疫原性不是同一概念，camelid hallmark 可能被误判 |
| Humatch | gene-specific antibody humanisation | antibody heavy/light sequences -> humanized sequences/匹配结果 | BSD；依赖 ANARCI；本地 pip install | 如果 VHH 项目扩展到 conventional antibody 或想比较 heavy-chain humanization 策略 | 原始目标是 heavy+light joint humanisation；对单域 VHH 需谨慎解释 |
| IgCraft | paired human antibody sequence generation | condition CSV/HDF5、IMGT region mask -> generated paired sequences | MIT；Hugging Face/Zenodo weights/data；Lightning 环境 | 作为 human antibody generative baseline；若要从 VHH 转 scFv/paired Ab 可参考 | 不是 VHH 专项；模型偏 paired human antibody，VHH 直接使用风险高 |
| Graphinity | antibody-antigen ΔΔG 研究和 EGNN affinity-change baseline | Ab-Ag complex/mutation configs -> ΔΔG prediction CSV；也可训练 | BSD；conda env；示例推理/训练；数据来自 SAbDab、FoldX/Rosetta synthetic ddG | VHH-Ag 突变优先级排序的研究型对照，尤其已有复合物结构时 | 论文/README 强调实验 ddG 数据不足且泛化不稳；FoldX/Rosetta synthetic 数据不等于真实 VHH affinity |
| TNP | Therapeutic Nanobody Profiler，VHH developability 筛选 | nanobody sequence(s) -> developability/property profile | BSD；本地 package；VHH 专项论文和代码 | VHH hit triage：聚集/电荷/可开发性 proxy、设计后过滤、报告中的首选性质模块 | 预测性质是 proxy；不能替代表达、SEC、DSF、binding assay；模型适用域需按序列长度/框架检查 |

### 2.4 VHH discovery、NGS、编号和 paratope/epitope 预测

| 工具 | 用途范围 | 输入 -> 输出 | 训练/构建方式 | 适合的 VHH 场景 | 局限 |
|---|---|---|---|---|---|
| alpseq | Illumina 2x300 bp nanobody sequencing pipeline | paired FASTQ/config -> preprocessing、clone/feature tables、analysis report | GPL-3.0；Nextflow；文档网站；无需深度学习权重 | 免疫库/展示库 NGS 的 VHH clone 富集和基础 QC | 需要按项目修改 `nextflow.config`；不直接预测 binding/structure |
| phage-seq + nbseq | phage display coupled HTS 和 VHH feature table processing | FASTQ/Snakemake workflow -> VHH feature tables、enrichment-ready outputs | nbseq MIT；workflow/repo 数据公开；Snakemake 安装 | phage display 或类似 selection 实验后的 VHH 序列整理 | 任务特定 workflow；输入实验设计不同时需改规则和元数据 |
| ANARCI | antibody numbering 和 receptor class identification | sequence/FASTA -> IMGT/Chothia/Kabat 等编号、chain type | BSD-like；HMMER/IMGT germline models；本地 CLI/Python | 所有 VHH 流程的前置：识别 CDR、标准编号、过滤异常序列 | 对非常短/破碎/非典型序列可能失败；VHH hallmark 需要额外规则 |
| Immcantation / pRESTO / Change-O / airrflow | AIRR repertoire preprocessing、VDJ assignment output processing、clonal assignment | FASTQ/VDJ aligner outputs/AIRR tables -> standardized AIRR tables、clones、reports | AGPL/GPL/nf-core；成熟文档和容器生态 | 大规模 BCR/VHH repertoire 的标准化表格和 clone lineage 分析 | VHH 专项逻辑少，需要结合 ANARCI/VHH hallmark；许可证 copyleft 影响集成方式 |
| IgDiscover | 从 antibody repertoire 发现新 V genes | HTS reads/repertoire config -> inferred germline V genes | MIT-like；conda/env；GitLab docs | 非模式物种、camelid 样本或 germline reference 不完整时发现 V gene | 输入数据质量和个体/物种背景强相关；不输出 binding 结论 |
| DeepNano | Nb-Ag sequence/site/interaction prediction | nanobody sequence、antigen sequence/信息 -> interaction/site prediction | MIT；README 声明代码和模型权重在仓库；PyTorch/transformers 环境 | 大规模候选的 sequence-only 结合初筛、antigen-site 粗筛 | 训练集和抗原类型适用域要严格核查；预测概率不能替代亲和力实验 |
| AbAgIntPre | sequence-only antibody-antigen interaction classifier | antigen sequence + antibody heavy/light or related sequence features -> interaction probability | Apache；Siamese CNN + CKSAAP；数据来自 SAbDab/CoV-AbDab | 缺结构时的 Ab-Ag/VHH-Ag 粗筛对照 | 原方法偏常规 antibody；VHH 单链输入需要映射/适配，泛化风险高 |
| Paragraph | structure-based paratope prediction | antibody/VHH structure -> residue-level paratope probabilities | BSD；GNN；预训练权重在仓库 | VHH 单体结构已有时预测 paratope，给 HADDOCK/设计热点提供约束 | 依赖结构质量；训练偏既有抗体结构；paratope 概率不是 epitope 或 binding pose |
| ParaPred | sequence-based paratope prediction baseline | antibody sequence/CDR -> paratope labels/probabilities | 原始 Keras 版与 PyTorch 版均有权重；PyTorch 版 MIT | 无结构或快速 baseline；与 Paragraph/DeepNano-site 交叉 | 历史模型，性能和编号适配可能落后；VHH 长 CDR3 外推需验证 |
| EpiScan | antibody-specific viral epitope mapping from sequence | antibody/antigen sequence features -> epitope mapping output | MIT；trained_model 在仓库；PyTorch 依赖 | 病毒抗原 VHH/antibody epitope mapping 的 sequence-level 对照 | 重点是 viral protein；非病毒靶点外推有限 |

## 3. 建议的开源可复现优先路线

1. **先建基础注释层**：`ANARCI` + `alpseq`/`nbseq`/`Immcantation`，把 VHH 序列、编号、CDR、clone/enrichment 表统一起来。
2. **再建单体结构层**：`NanoBodyBuilder2` 为 VHH 主线，`HeavyBuilder2` 和 `ABlooper` 作补充；常规 VH/VL 项目再引入 `ABodyBuilder3`。
3. **复合物候选不要只信一个模型**：用 `Chai-1`、`Boltz`、`ColabFold/AF-Multimer` 做 co-folding 候选，再用 `HADDOCK3` 在有 paratope/epitope 约束时 refinement；`DeepRank-Ab` 做 decoy 排序辅助。
4. **设计类先区分“生成”和“过滤”**：`RFantibody`/`IgGM` 负责生成，`AntiFold` 做固定骨架序列重设计，`TNP`/`BioPhi`/`Paragraph`/`DeepNano` 做可开发性和界面证据过滤。
5. **B/C 类只在证据缺口明确时引入**：例如需要 AF3 作强对照、需要 Rosetta refinement、需要 FoldX ddG、需要网页免疫原性筛查时，再单独处理 license、参数、数据和可复现记录。

## 4. 证据充分性与未决风险

- 已覆盖本地 manifest 的全部 69 个条目，并按本地 clone/license/README、论文/网页链接进行了分层。
- 没有实际安装、下载权重、运行模型或验证输出；因此“可复现”指公开材料显示具备本地复现路径，不代表当前机器已可运行。
- GitHub 仓库状态可能在 2026-07-06 后变化；本报告的本地 commit head 以 `metadata/asset_download_results.json` 为准。
- 许可证判定只做工程 triage，不构成法律意见；商业/转化使用前应复核上游 LICENSE、模型权重条款和第三方依赖条款。
- VHH-Ag 结构/亲和力预测普遍存在“高置信错 pose”和“proxy 不等于实验”的风险；任何 A/B/C 分层都不能替代 wet-lab validation。

## 5. 可复用结论

优先把报告主线建立在 A 类：`ANARCI`/`alpseq`/`nbseq`/`Immcantation` 做序列与 repertoire，`NanoBodyBuilder2`/`HeavyBuilder2`/`ABlooper` 做 VHH 单体，`Chai-1`/`Boltz`/`ColabFold`/`HADDOCK3`/`DeepRank-Ab` 做复合物候选和排序，`RFantibody`/`IgGM`/`AntiFold` 做开放设计，`TNP`/`BioPhi`/`Paragraph`/`DeepNano` 做过滤。B 类等 license、权重、外部依赖清楚后再跑；C 类只作网页/论文对照或方法追踪。
