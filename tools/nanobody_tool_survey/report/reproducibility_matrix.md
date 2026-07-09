### 1.3 全部工具速览矩阵（按可复现优先级）

| 优先级 | 类别 | 工具 | 主要用途范围 | 本地代码 | PDF/论文状态 |
|---|---|---|---|---|---|
| A 开源可复现优先 | 结构预测/复合物建模 | NanoBodyBuilder2 / ImmuneBuilder | VHH单体结构预测；批量建模、CDR3观察、docking前准备 | 已克隆 1 个仓库 | downloaded |
| B 可用但许可/商业需确认 | 结构预测/复合物建模 | NanoNet | VHH/VH快速结构预测；repertoire级粗建模 | 已克隆 1 个仓库 | downloaded |
| B 学术许可/非完全开放 | 结构预测/复合物建模 | IgFold | 抗体/nanobody结构baseline；快速PDB生成 | 已克隆 1 个仓库 | downloaded |
| A 开源可复现优先 | 结构预测/复合物建模 | HeavyBuilder2 | 单heavy-chain结构建模；VHH/VH混合数据补充 | 已克隆 1 个仓库 | 无直接PDF候选 |
| B 非VHH主线/补充 | 结构预测/复合物建模 | ABodyBuilder3 | 常规VH/VL结构预测；VHH项目只作参考 | 已克隆 1 个仓库 | http_403 |
| B 非VHH主线/补充 | 结构预测/复合物建模 | DeepAb | 历史抗体结构预测baseline；非VHH主线 | 已克隆 1 个仓库 | 无直接PDF候选 |
| B CDR loop补充 | 结构预测/复合物建模 | ABlooper | CDR loop预测；修正局部loop而非完整复合物 | 已克隆 1 个仓库 | http_403 |
| B CDR-H3补充 | 结构预测/复合物建模 | H3-OPT | CDR-H3 loop优化；长CDR3局部精修参考 | 已克隆 1 个仓库 | http_406 |
| C 外部软件/许可流程 | 结构预测/复合物建模 | RosettaAntibody3 / SnugDock | 抗体/纳米抗体docking和refinement；高门槛 | 无本地公开代码 | not_pdf |
| B 权重/条款受限 | 结构预测/复合物建模 | AlphaFold 3 / AlphaFold Server | all-atom复合物预测；VHH-Ag候选pose | 已克隆 1 个仓库 | downloaded |
| B AF参数/条款需记录 | 结构预测/复合物建模 | AlphaFold-Multimer / ColabFold | AF2多链复合物baseline；多seed互证 | 已克隆 2 个仓库 | downloaded |
| A 开源可复现优先 | 结构预测/复合物建模 | Chai-1 | 开放复合物/co-folding模型；VHH-Ag候选pose | 已克隆 1 个仓库 | http_403 |
| A 开源可复现优先 | 结构预测/复合物建模 | Boltz-1 / Boltz-2 | 开放AF3-like结构/复合物模型；可与Chai互证 | 已克隆 1 个仓库 | not_pdf |
| A 开源可复现优先 | 结构预测/复合物建模 | HADDOCK2.4 / HADDOCK3 | 约束docking；把表位/突变/预测界面转成restraints | 已克隆 2 个仓库 | not_pdf |
| C 网页/服务为主 | 结构预测/复合物建模 | ClusPro / AbEMap | 网页docking/epitope候选；用于假设生成 | 无本地公开代码 | not_pdf |
| C 网页/服务为主 | 结构预测/复合物建模 | HDOCK | 网页protein-protein docking；快速候选pose | 无本地公开代码 | not_pdf |
| B 通用模型/补充 | 结构预测/复合物建模 | BALMFold | 通用结构模型；VHH补充baseline | 已克隆 1 个仓库 | http_403 |
| B docking生成补充 | 结构预测/复合物建模 | AbDockGen | 抗体-抗原docking生成；研究对照 | 已克隆 1 个仓库 | downloaded |
| B docking排序补充 | 结构预测/复合物建模 | DeepRank-Ab | docking pose排序；HADDOCK生态补充 | 已克隆 1 个仓库 | 无直接PDF候选 |
| A 开源可复现优先 | 设计/优化/人源化 | RFantibody | 表位条件de novo VHH/scFv设计；开源主线 | 已克隆 1 个仓库 | downloaded |
| B 外部依赖较多 | 设计/优化/人源化 | NanoDesigner | VHH CDR设计/优化workflow；外部依赖多 | 已克隆 1 个仓库 | not_pdf |
| B PyRosetta/AF依赖 | 设计/优化/人源化 | Germinal | epitope-targeted VHH/scFv生成；RFantibody对照 | 已克隆 1 个仓库 | http_403 |
| A 开源可复现优先 | 设计/优化/人源化 | IgGM | 抗体/nanobody结构-序列联合生成；多任务模型 | 已克隆 1 个仓库 | http_403 |
| C 论文为主/代码未获 | 设计/优化/人源化 | TFDesign-sdAb | 单域抗体设计论文；本地不可复现优先级低 | 无本地公开代码 | downloaded |
| C 闭源/公司平台 | 设计/优化/人源化 | Chai-2 | 公司zero-shot抗体/VHH设计平台；了解前沿 | 无本地公开代码 | http_403 |
| C 论文/公司平台 | 设计/优化/人源化 | Latent-X2 | all-atom生成平台；公司/论文方向 | 无本地公开代码 | downloaded |
| C 白皮书/公司平台 | 设计/优化/人源化 | JAM-2 | Nabla VHH/mAb设计白皮书；了解benchmark设定 | 无本地公开代码 | downloaded |
| C 预印本/代码未确认 | 设计/优化/人源化 | EasyNano | epitope-targeted nanobody CDR设计预印本 | 无本地公开代码 | downloaded |
| B 非VHH主线/需适配 | 设计/优化/人源化 | DiffAb | 抗原条件CDR diffusion；需适配VHH | 已克隆 1 个仓库 | http_403 |
| A 开源可复现优先 | 设计/优化/人源化 | AntiFold | 结构条件inverse folding；VHH scaffold/CDR重设计 | 已克隆 1 个仓库 | downloaded |
| C 预印本/代码未确认 | 设计/优化/人源化 | nanoFOLD | VHH inverse folding预印本；代码/权重未明确 | 无本地公开代码 | http_403 |
| B 学术许可/非VHH专用 | 设计/优化/人源化 | IgLM | 抗体语言模型；序列生成/补全，非VHH专用 | 已克隆 1 个仓库 | 无直接PDF候选 |
| B 数据许可/下游任务受限 | 设计/优化/人源化 | VHHBERT / VHHCorpus-2M | VHH语言模型/embedding；下游binding和突变分析 | 已克隆 1 个仓库 | downloaded |
| B 非商业许可 | 设计/优化/人源化 | AbNatiV / AbNatiV2 | nativeness/humanness；VHH hit selection和人源化风险 | 已克隆 1 个仓库 | downloaded |
| B 非商业许可 | 设计/优化/人源化 | HuDiff / HuDiff-Nb | HuDiff-Nb人源化；保留结合前提下改造VHH | 已克隆 1 个仓库 | http_403 |
| C 方法重要但代码不明确 | 设计/优化/人源化 | Llamanade | VHH人源化规则/结构方法；概念参考 | 无本地公开代码 | not_pdf |
| A 开源可复现优先 | 设计/优化/人源化 | BioPhi / Sapiens / OASis | 人源化/humanness/OASis；VHH辅助参考 | 已克隆 2 个仓库 | not_pdf |
| A 开源可复现优先 | 设计/优化/人源化 | Humatch | human-likeness匹配；人源化辅助 | 已克隆 1 个仓库 | not_pdf |
| B/C 待确认 | 设计/优化/人源化 | IgCraft | 抗体生成/工程新工具；需进一步验证 | 已克隆 1 个仓库 | downloaded |
| C 网页服务为主 | 设计/优化/人源化 | mCSM-AB2 | Ab-Ag突变ΔΔG；有复合物时辅助亲和力成熟 | 无本地公开代码 | http_403 |
| B 非VHH专用ΔΔG | 设计/优化/人源化 | GearBind | 几何GNN突变/结合排序；非VHH专用 | 已克隆 1 个仓库 | downloaded |
| B 非VHH专用ΔΔG | 设计/优化/人源化 | Graphinity | 等变GNN ΔΔG；研究框架/亲和力成熟辅助 | 已克隆 1 个仓库 | 无直接PDF候选 |
| A 开源可复现优先 | 识别/发现/结合预测 | alpseq | VHH Illumina NGS pipeline；展示库/免疫库入口 | 已克隆 1 个仓库 | not_pdf |
| B 非商业许可/新工具 | 识别/发现/结合预测 | NanoMAP | VHH repertoire处理和clone family/富集分析 | 已克隆 1 个仓库 | not_pdf |
| A 开源可复现优先 | 识别/发现/结合预测 | phage-seq + nbseq | phage display NGS后处理和候选表 | 已克隆 2 个仓库 | 无直接PDF候选 |
| A 开源可复现优先 | 识别/发现/结合预测 | ANARCI | 抗体编号/CDR定位；所有VHH流程基础 | 已克隆 1 个仓库 | http_403 |
| C 官方工具/未纳入本地代码 | 识别/发现/结合预测 | IgBLAST | VDJ/germline注释；需camelid自定义库 | 无本地公开代码 | 无直接PDF候选 |
| B 许可证/自定义库 | 识别/发现/结合预测 | MiXCR | 大规模AIRR/BCR/TCR分析；需VHH库适配 | 已克隆 1 个仓库 | 无直接PDF候选 |
| A 开源可复现优先 | 识别/发现/结合预测 | Immcantation / pRESTO / Change-O / airrflow | AIRR-seq生态；clone/lineage/SHM分析 | 已克隆 3 个仓库 | not_pdf |
| B germline发现补充 | 识别/发现/结合预测 | IgDiscover | germline发现；构建/校正VHH V基因库 | 已克隆 1 个仓库 | 无直接PDF候选 |
| A 开源可复现优先 | 识别/发现/结合预测 | DeepNano | Nb-Ag interaction sequence模型；候选预排序 | 已克隆 1 个仓库 | not_pdf |
| B 序列级预测需验证 | 识别/发现/结合预测 | NABP-BERT | Nb-Ag binding probability；序列级辅助筛选 | 已克隆 1 个仓库 | http_403 |
| B 非VHH专用预测 | 识别/发现/结合预测 | AbAgIntPre | Ab-Ag interaction预测；非VHH专用baseline | 已克隆 1 个仓库 | not_pdf |
| A 开源可复现优先 | 识别/发现/结合预测 | Paragraph | 结构型paratope预测；给docking约束/突变假设 | 已克隆 1 个仓库 | http_403 |
| B paratope补充 | 识别/发现/结合预测 | ParaPred | 序列型paratope预测；非VHH专用 | 已克隆 2 个仓库 | http_403 |
| C 网页服务为主 | 识别/发现/结合预测 | EpiPred / SAbPred | epitope/paratope网页workflow；假设生成 | 无本地公开代码 | http_403 |
| C 网页workflow | 识别/发现/结合预测 | AbAdapt | 抗体-抗原web workflow；建模+docking+预测 | 无本地公开代码 | http_403 |
| B epitope补充 | 识别/发现/结合预测 | EpiScan | 抗体特异epitope mapping；表位假设 | 已克隆 1 个仓库 | downloaded |
| B epitope补充 | 识别/发现/结合预测 | ImaPEp | paratope-epitope pair预测；表位辅助 | 已克隆 1 个仓库 | http_403 |
| A 开源可复现优先 | 性质预测/可开发性 | TNP / Therapeutic Nanobody Profiler | VHH developability profiler；性质预测主线 | 已克隆 1 个仓库 | downloaded |
| C 网页/standalone另取 | 性质预测/可开发性 | Aggrescan3D / A3D 2.0 | 结构聚集patch；VHH表面疏水风险 | 无本地公开代码 | http_403 |
| C 网页/外部工具 | 性质预测/可开发性 | CamSol | 溶解性profile；低溶解片段和突变建议 | 无本地公开代码 | 无直接PDF候选 |
| A 基础可复现/网页 | 性质预测/可开发性 | ProtParam / Compute pI/Mw | Mw/pI/GRAVY等基础物化字段 | 无本地公开代码 | 无直接PDF候选 |
| C 网页/外部工具 | 性质预测/可开发性 | IEDB / NetMHCIIpan | MHC-II epitope/免疫原性风险筛查 | 无本地公开代码 | 无直接PDF候选 |
| C 常规抗体网页工具 | 性质预测/可开发性 | TAP / Therapeutic Antibody Profiler | 常规抗体developability；VHH只作对照 | 无本地公开代码 | not_pdf |
| C 网页/外部工具 | 性质预测/可开发性 | Protein-Sol / Abpred | sequence-level solubility/表达辅助 | 无本地公开代码 | 无直接PDF候选 |
| C 网页服务为主 | 性质预测/可开发性 | DynaMut2 | 突变稳定性/柔性变化；结构依赖 | 无本地公开代码 | 无直接PDF候选 |
| C 外部许可证/二进制 | 性质预测/可开发性 | FoldX | 经验势能ΔΔG；突变稳定性/界面能辅助 | 无本地公开代码 | not_pdf |
| C 外部/商业或服务 | 性质预测/可开发性 | SOLart | 结构型溶解性/聚集风险补充 | 无本地公开代码 | 无直接PDF候选 |