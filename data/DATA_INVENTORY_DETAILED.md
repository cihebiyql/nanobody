# 抗体/纳米抗体结合模型数据资产清点

更新时间：2026-07-07T18:00:06+08:00

## 0. 总览

- 工作目录：`/mnt/d/work/抗体/data`
- 数据根目录：`datasets/`
- 顶层条目：`51` 个，其中大多数是数据目录，`datasets/logs` 是日志目录。
- 总体积：`257.2 GiB`，约等于 `258G` 的磁盘占用。
- 文件总数：`27930` 个。
- 当前目标：为“纳米抗体/抗体 与 对应受体或抗原结合”的专用 AI 模型准备原始数据池。
- 机器可读清单：`datasets/DOWNLOAD_MANIFEST.tsv`。
- 机器可读校验：`datasets/VALIDATION_SUMMARY.tsv`。
- 原始目录画像：`datasets/INVENTORY_RAW_SUMMARY.json`。

### 校验概况

- `ok`: 156
- `present_size_only`: 19
- `done`: 9
- `missing`: 1
- `invalid_duplicate_probe`: 1

已知非问题项：
- `datasets/34_dips_plus/dataverse_db5/raw_db5.tar.gz` 是旧错误 DOI/404 占位；正确文件是 `datasets/34_dips_plus/dataverse_db5/DB5.tar.gz`。
- `datasets/35_nanolas/sequence.jsonl` 是旧的 page 参数错误探针；正确序列文件是 `datasets/35_nanolas/cursor_sequence/sequence_cursor.jsonl` 和 `.csv`。
- `datasets/24_hf_nanobody/GDPa1/*` 有门控/401 零字节占位，不能当完整数据。
- `datasets/19_graphinity/synthetic_foldx_ddg_mutated_pdbs.tar.gz` 约 208GB，未启动。
- `datasets/43_abag_champloo_zenodo/*real_shuffled_complexes.zip` 单包约 28-32GB，未默认启动。

## 1. 适合训练任务的高层分类

| 类别 | 已有数据 | 可训练任务 | 优先级 |
| --- | --- | --- | --- |
| 纳米抗体/VHH 真实序列 | INDI2、VHHCorpus-2M、PLAbDab-nano、NanoLAS、sdAb-DB、ANDD | VHH 语言模型、天然性、CDR/FR 分布、scaffold 过滤 | 高 |
| 抗体-抗原/纳米抗体-抗原结合标签 | ZYMScott VHH affinity、AbBiBench、SAbDab affinity 小表、sdAb-DB Kd、mCSM-AB、AbDesignDB、PPB/SKEMPI | binding score/Kd/ΔG/ΔΔG 回归和排序 | 高 |
| paratope/epitope 位点标签 | ZYMScott Paratope、NanoLAS active residue/ligand-binding-sites、AsEP、SAbDab/SAAINT/SNAC 结构 | 接触位点预测、界面掩码、结构监督 | 高 |
| 结构复合物 | SAbDab2、RosettaCommons SAbDab、FarmerTao SAbDab、Drylab structures、ABDB、SNAC、DIPS/DB5 | docking/interface encoder、结构配对、negative/decoy 构造 | 高 |
| 负例/decoy/突变效应 | MiniAbsolut、Graphinity、DIPS-Plus、AbAg-Champloo、SKEMPI、AbBiBench mutant structures | hard negative、ΔΔG、ranking、结构置信度校准 | 中高 |
| 模型/权重/代码 | IgFold、AntiFold、DiffAb、AIDA、VHHBERT、AbAffinity、DeepAAI、RFantibody 等 | baseline、特征抽取、复现已有模型 | 中高 |
| 治疗抗体/专利/OAS 背景 | PLAbDab、TheraSAbDab、CoV-AbDab、OAS | 去重、专利风险、天然性/开发性、背景预训练 | 中 |

## 2. 顶层目录总表

| 目录 | 大小 | 文件数 | 类型/定位 | 建模用途 | 校验状态 |
| --- | ---: | ---: | --- | --- | --- |
| `datasets/49_hf_broad_antibody` | 52.7GB | 116 | 广泛 HF 抗体/纳米抗体大合集 | 当前最核心的大型训练来源：序列、结构、paratope/epitope、affinity score、polyreactivity、SAbDab 结构归档。 | ok:98, present_size_only:16 |
| `datasets/19_graphinity` | 37.1GB | 11 | Graphinity 合成 ΔΔG/结构数据 | 蛋白复合物突变 ΔΔG、结构学习、泛化到抗体-抗原界面突变。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/08_indi2` | 25.1GB | 9128 | INDI2 纳米抗体大库 | VHH scaffold pool、天然性模型、CDR/FR 分布、语言模型预训练；大多数无特定受体结合标签。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/34_dips_plus` | 24.9GB | 11 | DIPS-Plus/DB5 蛋白复合物数据 | 通用蛋白复合物 docking/interface 训练、负例/正例结构学习。 | ok:9, missing:1 |
| `datasets/22_igfold_data` | 14.5GB | 7 | IgFold/OAS/AF-OAS 数据与结构包 | 抗体结构预测/预训练数据、paired/unpaired 抗体序列；Jaffe2022 为部分下载。 | present_size_only:1 |
| `datasets/44_negative_class_optimization_zenodo` | 14.5GB | 9 | MiniAbsolut/负类优化数据 | 抗体-抗原分类、负例构造、hard negative/decoy 训练。 | present_size_only:2, ok:1 |
| `datasets/27_asep` | 11.7GB | 5 | AsEP/表位预测数据 | 抗原表位/抗体-抗原界面预测、几何表面特征模型。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/18_snacdb` | 10.8GB | 4 | SNAC-DB 抗体-抗原复合物数据库 | 抗体-抗原复合物结构/注释，适合结构 benchmark 和界面学习。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/04_plabdab` | 9.3GB | 6 | PLAbDab 专利/文献抗体库 | 抗体序列背景、专利去重、VH/VL 配对建模、相似性排除；抗原标签需进一步解析。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/24_hf_nanobody` | 8.2GB | 153 | 早期 HuggingFace 纳米抗体集合 | VHH 序列、VHH affinity/功能设计、NbBench paratope/antigen embedding、病毒/细胞因子抗体任务。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/45_abbibench_zenodo_16557372` | 7.7GB | 2 | AbBiBench mutant structures | AbBiBench 突变结构；配合 14/49 的 binding_affinity 分数做结构-序列-分数监督。 | ok:1 |
| `datasets/51_hf_gap_fill` | 6.5GB | 10 | HF 补漏集合 | 结构包、指令式抗体设计语料、纳米抗体 polyreactivity、抗体-抗原 SAbDab 表。 | ok:7, done:3 |
| `datasets/33_saaint_db` | 5.1GB | 5 | SAAINT-DB 结构抗体数据库 | 结构抗体建模、抗体-抗原结构样本、affinity 关联需后续索引。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/10_github_repos` | 5.0GB | 6089 | 第一批模型仓库与代码数据 | 复现实验、读取原作者数据格式、抽取训练脚本、基线模型；含部分模型权重和样例 CSV/PDB。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/05_zenodo_andd` | 4.2GB | 13 | ANDD 纳米抗体数据库 | 纳米抗体-抗原/结构/注释来源；可抽取 VHH 序列、靶标、结构和文献信息。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/13_sabdab_structures` | 3.8GB | 164 | SAbDab/SAbDab2 结构 API 快照 | 抗体-抗原结构、single-domain 结构、结构训练/验证、抗体结构预处理。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/38_absolut_nird` | 3.6GB | 584 | Absolut/NIRD 合成抗体-抗原结构数据 | 合成 antibody-antigen binding/结构任务、负例/正例或模拟评分，适合大规模预训练/benchmark。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/32_ppb_affinity` | 2.9GB | 5 | PPB-Affinity 蛋白-蛋白亲和力 | 蛋白-蛋白结合亲和力、复合物结构；可做泛化 PPI/receptor-ligand 预训练。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/50_github_model_repos_extra` | 2.1GB | 4169 | 额外 GitHub 模型/数据仓库 | 模型复现、特征处理、可借鉴数据格式与 baseline；部分仓库含数据表。 | ok:19, done:1 |
| `datasets/46_hf_additional_nanobody` | 1.4GB | 30 | 额外 HF 纳米抗体数据 | 纳米抗体序列、接触图、polyreactivity、抗体-抗原训练表。 | ok:12 |
| `datasets/06_sabdab` | 835.8MB | 1 | SAbDab2 split 包 | 抗体-抗原结构 split、benchmark 划分；适合结构模型训练/验证。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/30_abdesign_db` | 778.7MB | 8 | AbDesignDB/突变设计数据 | 抗体突变、ELISA/affinity ratio、CDR、IMGT 映射、抗原/抗体序列；适合突变优化模型。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/12_oas_downloads` | 777.6MB | 33 | OAS 真实下载子集 | 抗体天然序列背景、语言模型/天然性评分、CDR 长度分布；无统一抗原标签。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/37_model_repos` | 601.7MB | 2 | AIDA 预训练权重 | 抗体-抗原结构/序列表征基线。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/43_abag_champloo_zenodo` | 559.4MB | 4 | AbAg-Champloo 结构准确性/置信度数据 | 抗体-抗原结构预测评估、模型置信度校准。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/16_antifold` | 540.6MB | 1 | AntiFold 模型权重 | 逆折叠/结构给定序列设计基线。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/52_github_late_model_repos` | 381.5MB | 680 | 后补 GitHub 抗体模型仓库 | 亲和力/交互预测模型代码、权重、训练数据格式和 baseline。 | ok:7, done:1 |
| `datasets/31_agab_naturalantibody` | 359.7MB | 45 | AgAb/NaturalAntibody parquet | 抗原-抗体/单域抗体背景数据；需进一步解析字段。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/15_covabdab` | 353.6MB | 4 | CoV-AbDab 新冠抗体库 | SARS-CoV/SARS-CoV-2 抗体序列、结构、靶标注释；可用于病毒抗体专项预训练/评估。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/25_vhh_models` | 327.4MB | 8 | VHH 预训练模型 | VHH 表征、embedding、下游微调初始化。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/35_nanolas` | 242.8MB | 4958 | NanoLAS 纳米抗体序列/活性位点 API | 纳米抗体 CDR、活性残基、配体结合位点、序列库；非常适合 VHH 位点监督/弱监督。 | done:4, invalid_duplicate_probe:1 |
| `datasets/20_diffab` | 231.0MB | 5 | DiffAb 权重 | 抗体设计/结构生成基线模型。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/42_abdb` | 224.5MB | 3 | AbDb/Martin 抗体结构归档 | 抗体结构/序列背景、非冗余抗体结构。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/47_antibody_complex_benchmarks` | 70.1MB | 2 | Zhaonan99 抗体-抗原复合物 benchmark | 抗体-抗原复合物结构 benchmark。 | ok:2 |
| `datasets/14_antibody_benchmark` | 60.1MB | 36 | AbBiBench 小型展开版 | 抗体序列到 binding_score 的监督；带 complex_structure，可做结构+序列联合建模。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/17_alphaseq` | 53.1MB | 1 | AlphaSeq 抗体实验数据 | 高通量抗体序列表型/选择数据；需解包确认字段。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/03_skempi` | 30.6MB | 3 | SKEMPI 2.0 蛋白互作突变亲和力 | 通用 PPI/突变效应监督；可训练 interface mutation ΔΔG 或 affinity change，但不是抗体专用。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/36_sdab_db` | 29.0MB | 1483 | sdAb-DB 单域抗体数据库 | 真实 sdAb/VHH 序列、目标抗原、Kd_nm、DOI；适合 VHH-抗原标签表。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/logs` | 19.7MB | 64 | 下载日志 | 审计和故障恢复。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/48_discovery` | 3.1MB | 7 | 发现记录/候选元数据 | 追踪已发现但未抓/延后/门控的数据源。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/23_naturalantibody` | 1.4MB | 5 | NaturalAntibody 网页缓存 | NaturalAntibody 数据入口和来源说明。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/00_structures` | 1.2MB | 9 | PVRIG/PVRL2 核心结构与序列 | 结构输入、界面抽取、靶点受体表示；不是大规模训练集，但可作为特定任务的受体/配体结构锚点。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/21_therasabdab` | 939.0KB | 5 | Thera-SAbDab 治疗性抗体表 | 临床/治疗性抗体序列、靶点、开发状态参考；可用于 developability 与去重。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/02_plabdab_nano` | 691.2KB | 4 | PLAbDab-nano 序列 | 纳米抗体真实序列、天然性、CDR/FR 分布、骨架背景；通常缺少统一抗原/亲和力标签。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/28_affinity_kd` | 324.8KB | 2 | SAbDab 抗体-蛋白 Kd 小表 | 抗体序列 + 抗原序列 + Kd/Y 连续标签；最直接可用于 Ab-Ag affinity baseline。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/09_model_datasets` | 242.2KB | 14 | 模型/数据库入口探针 | 来源记录和后续抓取线索。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/07_oas` | 190.0KB | 11 | OAS 页面与元数据探针 | 免疫组库来源发现；直接训练数据在 12_oas_downloads/22_igfold_data/49 等处。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/29_csm_ab` | 59.4KB | 6 | mCSM-AB 亲和力/ΔG 表 | 抗体-抗原复合物 ΔG/突变亲和力模型。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/01_small_tables` | 54.6KB | 4 | 早期网页探针与小表 | 来源发现和网页解析线索；不建议直接作为训练主表。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/41_antibody_benchmark_pierce` | 19.7KB | 1 | Pierce antibody benchmark cases | 抗体 benchmark case 元数据。 | 未单独校验；见文件存在性/来源脚本 |
| `datasets/11_huggingface` | 4.0KB | 0 | 空 HuggingFace 预留目录 | 无直接用途。 | 未单独校验；见文件存在性/来源脚本 |

## 3. 按类别详细介绍

### A. 结构与抗体-抗原复合物

#### `datasets/00_structures` — PVRIG/PVRL2 核心结构与序列

- 规模：1.2MB，文件数 9。
- 内容：PVRIG-PVRL2 相关结构 8X6B/9E6Y 的 CIF/PDB，以及 PVRIG/PVRL2 FASTA。
- 主要文件类型：.fasta:4, .cif:2, .pdb:2, .txt:1。
- 关键文件：`datasets/00_structures/8X6B.cif` (438.0KB); `datasets/00_structures/8X6B.pdb` (332.5KB); `datasets/00_structures/9E6Y.cif` (285.1KB); `datasets/00_structures/9E6Y.pdb` (193.2KB); `datasets/00_structures/SHA256SUMS.txt` (0.8KB)。
- 适合用途：结构输入、界面抽取、靶点受体表示；不是大规模训练集，但可作为特定任务的受体/配体结构锚点。
- 状态/注意：已落盘；适合用于 PVRIG 赛题建模中的 receptor context 和结构约束。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/06_sabdab` — SAbDab2 split 包

- 规模：835.8MB，文件数 1。
- 内容：SAbDab2 划分归档。
- 主要文件类型：.tar.gz:1。
- 关键文件：`datasets/06_sabdab/sabdab2_splits.tar.gz` (835.8MB)。
- 适合用途：抗体-抗原结构 split、benchmark 划分；适合结构模型训练/验证。
- 状态/注意：单 tar.gz 保存。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/13_sabdab_structures` — SAbDab/SAbDab2 结构 API 快照

- 规模：3.8GB，文件数 164。
- 内容：SAbDab2 API JSON、single-domain/full 结构 tgz、分页缓存。
- 主要文件类型：.json:57, .tgz:48, .headers:47, .html:4, .gz:3, .tsv:2。
- 关键文件：`datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz` (516.7MB); `datasets/13_sabdab_structures/sabdab_all_sd_h_structures.tgz` (511.1MB); `datasets/13_sabdab_structures/api/antibody-instances.json` (153.4MB); `datasets/13_sabdab_structures/full_all/full_structure_chunks/sabdab2_all_full_structures_chunk_0034_08251-08500.tgz` (84.8MB); `datasets/13_sabdab_structures/api/pdb.json` (84.3MB)。
- 适合用途：抗体-抗原结构、single-domain 结构、结构训练/验证、抗体结构预处理。
- 状态/注意：含 API JSON 和结构包，适合构建结构索引。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/18_snacdb` — SNAC-DB 抗体-抗原复合物数据库

- 规模：10.8GB，文件数 4。
- 内容：SNAC database zip 与 README/LICENSE。
- 主要文件类型：.md:2, .txt:1, .zip:1。
- 关键文件：`datasets/18_snacdb/SNAC-DataBase.zip` (10.8GB); `datasets/18_snacdb/README.md` (17.1KB); `datasets/18_snacdb/CHANGELOG.md` (5.9KB); `datasets/18_snacdb/LICENSE.txt` (1.1KB)。
- 适合用途：抗体-抗原复合物结构/注释，适合结构 benchmark 和界面学习。
- 状态/注意：大 zip 未展开；训练前需抽取结构表。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/27_asep` — AsEP/表位预测数据

- 规模：11.7GB，文件数 5。
- 内容：asep-dataset、benchmark、epipred、masif 包。
- 主要文件类型：.zip:2, .tar:2, .md:1。
- 关键文件：`datasets/27_asep/epipred.tar` (4.0GB); `datasets/27_asep/masif.tar` (3.4GB); `datasets/27_asep/asep-dataset.zip` (2.5GB); `datasets/27_asep/benchmark.zip` (1.8GB); `datasets/27_asep/README.md` (5.9KB)。
- 适合用途：抗原表位/抗体-抗原界面预测、几何表面特征模型。
- 状态/注意：大包未展开；适合 epitope/paratope benchmark。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/33_saaint_db` — SAAINT-DB 结构抗体数据库

- 规模：5.1GB，文件数 5。
- 内容：processed_pdb_models/unprocessed_mmcifs tar.gz。
- 主要文件类型：.tar.gz:4, .tsv:1。
- 关键文件：`datasets/33_saaint_db/unprocessed_mmcifs_20260226.tar.gz` (3.6GB); `datasets/33_saaint_db/processed_pdb_models_20260226.tar.gz` (1.5GB); `datasets/33_saaint_db/SAAINT_URLS.tsv` (0.3KB); `datasets/33_saaint_db/unprocessed_mmcifs_20251225.tar.gz` (0.0KB); `datasets/33_saaint_db/processed_pdb_models_20251225.tar.gz` (0.0KB)。
- 适合用途：结构抗体建模、抗体-抗原结构样本、affinity 关联需后续索引。
- 状态/注意：部分 20251225 包为 0 大小，占位；20260226 包为主数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/42_abdb` — AbDb/Martin 抗体结构归档

- 规模：224.5MB，文件数 3。
- 内容：LH_Protein_Martin、NR_LH_Protein_Martin 等 bz2 包。
- 主要文件类型：.bz2:2, .txt:1。
- 关键文件：`datasets/42_abdb/LH_Protein_Martin.tar.bz2` (163.3MB); `datasets/42_abdb/NR_LH_Protein_Martin.tar.bz2` (61.2MB); `datasets/42_abdb/Redundant_LH_Protein_Martin.txt` (22.9KB)。
- 适合用途：抗体结构/序列背景、非冗余抗体结构。
- 状态/注意：可用于结构预训练和去重。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/45_abbibench_zenodo_16557372` — AbBiBench mutant structures

- 规模：7.7GB，文件数 2。
- 内容：mutant_structure.tar.gz。
- 主要文件类型：.tar.gz:1, .txt:1。
- 关键文件：`datasets/45_abbibench_zenodo_16557372/mutant_structure.tar.gz` (7.7GB); `datasets/45_abbibench_zenodo_16557372/README.txt` (0.1KB)。
- 适合用途：AbBiBench 突变结构；配合 14/49 的 binding_affinity 分数做结构-序列-分数监督。
- 状态/注意：gzip 完整校验通过。 校验摘要：ok:1。

#### `datasets/47_antibody_complex_benchmarks` — Zhaonan99 抗体-抗原复合物 benchmark

- 规模：70.1MB，文件数 2。
- 内容：两个 antibody-antigen complex benchmark zip。
- 主要文件类型：.zip:2。
- 关键文件：`datasets/47_antibody_complex_benchmarks/Zhaonan99_Antibody_antigen_complex_structure_benchmark_dataset.zip` (38.5MB); `datasets/47_antibody_complex_benchmarks/Zhaonan99_Antibody_antigen_protein_complex_Benchmark_Dataset.zip` (31.6MB)。
- 适合用途：抗体-抗原复合物结构 benchmark。
- 状态/注意：zip 完整校验通过。 校验摘要：ok:2。

#### `datasets/51_hf_gap_fill` — HF 补漏集合

- 规模：6.5GB，文件数 10。
- 内容：Drylab antibody diffusion structures、RBD ORPO/SFT、harvey nanobody polyreactivity、peleke SAbDab。
- 主要文件类型：.csv:4, .tsv:3, .md:2, .zip:1。
- 关键文件：`datasets/51_hf_gap_fill/Drylab_Drylab-Tool-antibody-diffusion-properties/all_structures.zip` (6.5GB); `datasets/51_hf_gap_fill/bbdinosorry_antibody_rbd_orpo/antibody_rbd_orpo.csv` (21.5MB); `datasets/51_hf_gap_fill/hugging-science_harvey-nanobody-polyreactivity/data/test.csv` (20.3MB); `datasets/51_hf_gap_fill/silicobio_peleke_antibody-antigen_sabdab/sabdab_training_dataset.csv` (19.3MB); `datasets/51_hf_gap_fill/bbdinosorry_antibody_rbd_sft/sft_training_dataset.csv` (5.8MB)。
- 适合用途：结构包、指令式抗体设计语料、纳米抗体 polyreactivity、抗体-抗原 SAbDab 表。
- 状态/注意：新增；7 ok + 3 done，Drylab zip 校验通过。 校验摘要：ok:7, done:3。

### B. 纳米抗体/VHH/单域抗体序列与标签

#### `datasets/02_plabdab_nano` — PLAbDab-nano 序列

- 规模：691.2KB，文件数 4。
- 内容：VHH/VNAR/single-domain antibody 序列压缩表。
- 主要文件类型：.gz:3, .txt:1。
- 关键文件：`datasets/02_plabdab_nano/all_sequences.csv.gz` (343.3KB); `datasets/02_plabdab_nano/vhh_sequences.csv.gz` (326.2KB); `datasets/02_plabdab_nano/vnar_sequences.csv.gz` (17.3KB); `datasets/02_plabdab_nano/SHA256SUMS.txt` (0.3KB)。
- 适合用途：纳米抗体真实序列、天然性、CDR/FR 分布、骨架背景；通常缺少统一抗原/亲和力标签。
- 状态/注意：适合做 VHH 背景库和负采样/天然性建模。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/05_zenodo_andd` — ANDD 纳米抗体数据库

- 规模：4.2GB，文件数 13。
- 内容：ANDD Excel 表、PDB zip、质量报告及 v2 镜像。
- 主要文件类型：.md:4, .xlsx:2, .zip:2, .sh:1, .txt:1, .tsv:1。
- 关键文件：`datasets/05_zenodo_andd/v2_18151718/ANDD_pdb.zip` (2.1GB); `datasets/05_zenodo_andd/ANDD_pdb.zip` (2.1GB); `datasets/05_zenodo_andd/v2_18151718/ANDD_v2.xlsx` (12.7MB); `datasets/05_zenodo_andd/ANDD.xlsx` (12.1MB); `datasets/05_zenodo_andd/v2_18151718/Data_quality_control_report.pdf` (838.6KB)。
- 适合用途：纳米抗体-抗原/结构/注释来源；可抽取 VHH 序列、靶标、结构和文献信息。
- 状态/注意：主数据和 v2 版本均保存。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/08_indi2` — INDI2 纳米抗体大库

- 规模：25.1GB，文件数 9128。
- 内容：NaturalAntibody INDI2 full/selected/retry 数据，含 NGS、专利、GenBank、结构和文献来源的 VHH/纳米抗体序列。
- 主要文件类型：.tar.gz:5514, .crc:1674, .gz:1469, .parquet:371, .csv:35, .txt:31。
- 关键文件：`datasets/08_indi2/full/unpaired_ngs/annotated_reads/bioproject=PRJNA814713/part-00088-c40e0c0b-b789-4e19-a43e-6e03b490f3c7.c000.snappy.parquet` (256.8MB); `datasets/08_indi2/full/unpaired_ngs/annotated_reads/bioproject=PRJDB13473/part-00107-b74ea643-6c5c-4a45-acaa-62b85ffdc602.c000.snappy.parquet` (241.8MB); `datasets/08_indi2/full/unpaired_ngs/annotated_reads/bioproject=PRJNA814713/part-00079-10e71a98-06e2-43fd-91f6-b36eeb3737af.c000.snappy.parquet` (241.5MB); `datasets/08_indi2/full/unpaired_ngs/annotated_reads/bioproject=PRJDB11899/part-00024-e1e7d7de-ffe6-4537-bead-111d253e0f9a.c000.snappy.parquet` (241.1MB); `datasets/08_indi2/full/unpaired_ngs/annotated_reads/bioproject=PRJEB7678/part-00060-af38717c-3916-4d50-826c-183689549049.c000.snappy.parquet` (240.1MB)。
- 适合用途：VHH scaffold pool、天然性模型、CDR/FR 分布、语言模型预训练；大多数无特定受体结合标签。
- 状态/注意：25GB 级大库；适合训练背景模型和过滤器。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/24_hf_nanobody` — 早期 HuggingFace 纳米抗体集合

- 规模：8.2GB，文件数 153。
- 内容：AVIDa、NbBench、VHHCorpus-2M、ZYMScott、carb1n 等纳米抗体/抗体相关 HF 数据。
- 主要文件类型：.csv:48, .pdb:26, .md:20, [noext]:19, .tsv:18, .jsonl:6。
- 关键文件：`datasets/24_hf_nanobody/NbBench/Paratope/antigen_embeddings.pt` (7.0GB); `datasets/24_hf_nanobody/VHHCorpus-2M/VHHCorpus-2M.csv` (324.1MB); `datasets/24_hf_nanobody/VHHCorpus-2M/train.csv` (278.3MB); `datasets/24_hf_nanobody/NbBench/hIL6/test.csv` (157.4MB); `datasets/24_hf_nanobody/AVIDa-hIL6/AVIDa-hIL6.csv` (99.8MB)。
- 适合用途：VHH 序列、VHH affinity/功能设计、NbBench paratope/antigen embedding、病毒/细胞因子抗体任务。
- 状态/注意：含 GDPa1 gated/401 零字节占位，报告中已标记。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/25_vhh_models` — VHH 预训练模型

- 规模：327.4MB，文件数 8。
- 内容：VHHBERT safetensors 与 tokenizer/config，自然抗体相关小文件。
- 主要文件类型：.json:3, [noext]:1, .tsv:1, .safetensors:1, .md:1, .txt:1。
- 关键文件：`datasets/25_vhh_models/VHHBERT/model.safetensors` (327.4MB); `datasets/25_vhh_models/VHHBERT/README.md` (1.5KB); `datasets/25_vhh_models/VHHBERT/.gitattributes` (1.5KB); `datasets/25_vhh_models/VHHBERT/tokenizer_config.json` (1.2KB); `datasets/25_vhh_models/VHHBERT/config.json` (0.6KB)。
- 适合用途：VHH 表征、embedding、下游微调初始化。
- 状态/注意：模型，不是原始标签数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/35_nanolas` — NanoLAS 纳米抗体序列/活性位点 API

- 规模：242.8MB，文件数 4958。
- 内容：entry、ligand-binding-sites、active-residue、sequence_cursor 等 JSONL/CSV。
- 主要文件类型：.json:4926, .js:12, .csv:5, .jsonl:5, [noext]:4, .py:3。
- 关键文件：`datasets/35_nanolas/sequence.json` (59.4MB); `datasets/35_nanolas/sequence.jsonl` (49.8MB); `datasets/35_nanolas/sequence.csv` (36.7MB); `datasets/35_nanolas/cursor_sequence/sequence_cursor.jsonl` (6.5MB); `datasets/35_nanolas/cursor_sequence/sequence_cursor.csv` (4.8MB)。
- 适合用途：纳米抗体 CDR、活性残基、配体结合位点、序列库；非常适合 VHH 位点监督/弱监督。
- 状态/注意：sequence.jsonl 是错误 page 探针；使用 cursor_sequence。 校验摘要：done:4, invalid_duplicate_probe:1。

#### `datasets/36_sdab_db` — sdAb-DB 单域抗体数据库

- 规模：29.0MB，文件数 1483。
- 内容：sdAb entries、affinity rows、FASTA、HTML detail pages。
- 主要文件类型：.html:1468, .txt:8, .py:3, .csv:2, .fasta:1, .json:1。
- 关键文件：`datasets/36_sdab_db/sdab_db_entries.csv` (1019.6KB); `datasets/36_sdab_db/sdab_db_affinity_rows.csv` (306.3KB); `datasets/36_sdab_db/sdab_db_sequences.fasta` (180.9KB); `datasets/36_sdab_db/pages/_Browse.html` (39.9KB); `datasets/36_sdab_db/pages/source_searches/Camelus_dromedarius_page_002.html` (38.3KB)。
- 适合用途：真实 sdAb/VHH 序列、目标抗原、Kd_nm、DOI；适合 VHH-抗原标签表。
- 状态/注意：表头已确认，直接可建小型监督集。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/46_hf_additional_nanobody` — 额外 HF 纳米抗体数据

- 规模：1.4GB，文件数 30。
- 内容：Dannyang Nanobody Sequence、nanobody contact maps、polyreactivity、peleke SAbDab。
- 主要文件类型：[noext]:6, .json:6, .tsv:6, .md:5, .csv:5, .parquet:2。
- 关键文件：`datasets/46_hf_additional_nanobody/Dannyang_Nanobody_Sequence_Dataset/clu90_train.csv` (981.4MB); `datasets/46_hf_additional_nanobody/alexchilton_nanobody-contact-maps/data/train-00000-of-00001.parquet` (383.3MB); `datasets/46_hf_additional_nanobody/harvey-nanobody-polyreactivity/data/test.csv` (20.3MB); `datasets/46_hf_additional_nanobody/peleke_antibody-antigen_sabdab/sabdab_training_dataset.csv` (19.3MB); `datasets/46_hf_additional_nanobody/Dannyang_Nanobody_Sequence_Dataset/clu90_validation.csv` (6.4MB)。
- 适合用途：纳米抗体序列、接触图、polyreactivity、抗体-抗原训练表。
- 状态/注意：parquet magic/CSV 行数已校验。 校验摘要：ok:12。

#### `datasets/49_hf_broad_antibody` — 广泛 HF 抗体/纳米抗体大合集

- 规模：52.7GB，文件数 116。
- 内容：AbBiBench、SAbDab、VHHCorpus、PRISM antibody、ZYMScott VHH affinity/paratope、RBD antibody、polyreactivity 等。
- 主要文件类型：.csv:42, .md:20, .parquet:14, .pdb:13, .tsv:9, .py:4。
- 关键文件：`datasets/49_hf_broad_antibody/RomeroLab-Duke_prism-antibody-data/unpaired_anarci_relabeled.parquet` (21.1GB); `datasets/49_hf_broad_antibody/ZYMScott_Paratope/antigen_embeddings.pt` (7.0GB); `datasets/49_hf_broad_antibody/FarmerTao_SAbDab_2025.8/all_structures.zip` (6.4GB); `datasets/49_hf_broad_antibody/RosettaCommons_SAbDab/sabdab_dataset_curated.tar.gz` (4.8GB); `datasets/49_hf_broad_antibody/Zoey13891350636_RBD_Antibody/SARS-CoV-2-RBD_MAP_Moderna_scores.csv` (3.7GB)。
- 适合用途：当前最核心的大型训练来源：序列、结构、paratope/epitope、affinity score、polyreactivity、SAbDab 结构归档。
- 状态/注意：本轮重点新增；多数关键文件已通过 magic/gzip/zip/行数校验。 校验摘要：ok:98, present_size_only:16。

### C. 结合亲和力、突变效应、打分监督

#### `datasets/03_skempi` — SKEMPI 2.0 蛋白互作突变亲和力

- 规模：30.6MB，文件数 3。
- 内容：蛋白-蛋白复合物突变前后亲和力、kon/koff、ΔΔG 可推导字段和 PDB 结构包。
- 主要文件类型：.txt:1, .tgz:1, .csv:1。
- 关键文件：`datasets/03_skempi/SKEMPI2_PDBs.tgz` (29.1MB); `datasets/03_skempi/skempi_v2.csv` (1.5MB); `datasets/03_skempi/SHA256SUMS.txt` (0.2KB)。
- 适合用途：通用 PPI/突变效应监督；可训练 interface mutation ΔΔG 或 affinity change，但不是抗体专用。
- 状态/注意：表头已确认，字段含 Affinity_mut/wt、Mutation、PDB。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/14_antibody_benchmark` — AbBiBench 小型展开版

- 规模：60.1MB，文件数 36。
- 内容：AbBiBench binding_affinity CSV 和 PDB 复合物结构。
- 主要文件类型：.csv:17, .pdb:13, [noext]:2, .json:2, .tsv:1, .md:1。
- 关键文件：`datasets/14_antibody_benchmark/AbBiBench/binding_affinity/4fqi_h1_benchmarking_data.csv` (15.5MB); `datasets/14_antibody_benchmark/AbBiBench/binding_affinity/4fqi_h3_benchmarking_data.csv` (14.8MB); `datasets/14_antibody_benchmark/AbBiBench/binding_affinity/5a12_vegf_benchmarking_data.csv` (12.5MB); `datasets/14_antibody_benchmark/AbBiBench/binding_affinity/aayl52_LC_benchmarking_data.csv` (3.1MB); `datasets/14_antibody_benchmark/AbBiBench/binding_affinity/aayl50_LC_benchmarking_data.csv` (2.7MB)。
- 适合用途：抗体序列到 binding_score 的监督；带 complex_structure，可做结构+序列联合建模。
- 状态/注意：表头已确认：heavy_chain_seq/light_chain_seq/binding_score。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/17_alphaseq` — AlphaSeq 抗体实验数据

- 规模：53.1MB，文件数 1。
- 内容：AlphaSeq_Antibody_Dataset v2 zip。
- 主要文件类型：.zip:1。
- 关键文件：`datasets/17_alphaseq/AlphaSeq_Antibody_Dataset-v2.0.0.zip` (53.1MB)。
- 适合用途：高通量抗体序列表型/选择数据；需解包确认字段。
- 状态/注意：适合做序列-实验分数建模。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/19_graphinity` — Graphinity 合成 ΔΔG/结构数据

- 规模：37.1GB，文件数 11。
- 内容：Synthetic FoldX/Flex ddG parquet/WT/mutated PDB 包；208GB mutated FoldX 主包被延后。
- 主要文件类型：.tar.gz:9, .html:1, .tsv:1。
- 关键文件：`datasets/19_graphinity/Synthetic_FoldX_ddG-varying_dataset_size-test-parquets.tar.gz` (20.9GB); `datasets/19_graphinity/synthetic_flexddg_ddg_mutated_pdbs.tar.gz` (7.7GB); `datasets/19_graphinity/synthetic_flexddg_ddg_wt_pdbs.tar.gz` (7.7GB); `datasets/19_graphinity/synthetic_foldx_ddg_wt_pdbs.tar.gz` (302.6MB); `datasets/19_graphinity/Synthetic_FoldX_ddG-example_train-parquets.tar.gz` (184.7MB)。
- 适合用途：蛋白复合物突变 ΔΔG、结构学习、泛化到抗体-抗原界面突变。
- 状态/注意：已抓 37GB，小心还有 208GB 延后项。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/28_affinity_kd` — SAbDab 抗体-蛋白 Kd 小表

- 规模：324.8KB，文件数 2。
- 内容：antibody_affinity_protein_sabdab.csv。
- 主要文件类型：.csv:1, .py:1。
- 关键文件：`datasets/28_affinity_kd/antibody_affinity_protein_sabdab.csv` (320.4KB); `datasets/28_affinity_kd/get_antibody_affinity_data.py` (0.4KB)。
- 适合用途：抗体序列 + 抗原序列 + Kd/Y 连续标签；最直接可用于 Ab-Ag affinity baseline。
- 状态/注意：表头已确认，规模小但标签明确。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/29_csm_ab` — mCSM-AB 亲和力/ΔG 表

- 规模：59.4KB，文件数 6。
- 内容：training、single/multiple mutation、DOCKGROUND/ZDOCK CSV。
- 主要文件类型：.csv:5, .txt:1。
- 关键文件：`datasets/29_csm_ab/2_single-point_mutations.csv` (26.0KB); `datasets/29_csm_ab/3_multiple-point_mutations.csv` (15.4KB); `datasets/29_csm_ab/1_training.csv` (12.8KB); `datasets/29_csm_ab/5_ZDOCK_bm4.csv` (0.8KB); `datasets/29_csm_ab/4_DOCKGROUND.csv` (0.4KB)。
- 适合用途：抗体-抗原复合物 ΔG/突变亲和力模型。
- 状态/注意：小型结构亲和力 benchmark。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/30_abdesign_db` — AbDesignDB/突变设计数据

- 规模：778.7MB，文件数 8。
- 内容：abdesign.tar.gz、datasets_mut/wt CSV。
- 主要文件类型：.csv:2, .txt:2, .tar.gz:1, .tsv:1, [noext]:1, .md:1。
- 关键文件：`datasets/30_abdesign_db/abdesign.tar.gz` (769.9MB); `datasets/30_abdesign_db/datasets_mut.csv` (8.4MB); `datasets/30_abdesign_db/datasets_wt.csv` (322.7KB); `datasets/30_abdesign_db/LICENSE.txt` (18.9KB); `datasets/30_abdesign_db/README.md` (6.5KB)。
- 适合用途：抗体突变、ELISA/affinity ratio、CDR、IMGT 映射、抗原/抗体序列；适合突变优化模型。
- 状态/注意：表头已确认，字段非常丰富。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/32_ppb_affinity` — PPB-Affinity 蛋白-蛋白亲和力

- 规模：2.9GB，文件数 5。
- 内容：PPB-Affinity.xlsx、PDB.zip、AF/samples_deleted。
- 主要文件类型：.zip:3, .xlsx:1, .tsv:1。
- 关键文件：`datasets/32_ppb_affinity/PDB.zip` (2.9GB); `datasets/32_ppb_affinity/PPB-Affinity-AF.zip` (3.1MB); `datasets/32_ppb_affinity/samples_deleted.zip` (2.0MB); `datasets/32_ppb_affinity/PPB-Affinity.xlsx` (1.1MB); `datasets/32_ppb_affinity/PPB_AFFINITY_URLS.tsv` (0.4KB)。
- 适合用途：蛋白-蛋白结合亲和力、复合物结构；可做泛化 PPI/receptor-ligand 预训练。
- 状态/注意：不是抗体专用，但对受体结合模型有价值。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/38_absolut_nird` — Absolut/NIRD 合成抗体-抗原结构数据

- 规模：3.6GB，文件数 584。
- 内容：大量 small_le50mb zip、MD5、说明文档。
- 主要文件类型：.md5:361, .zip:209, .py:6, .tsv:3, .txt:3, .docx:1。
- 关键文件：`datasets/38_absolut_nird/small_le50mb/Structures/SUDLR1b2e8727c5314fd6dcd1baef85de7edf-10-11-add13bf040af130eedca46409a50c9ceStructures.txt.zip` (46.9MB); `datasets/38_absolut_nird/small_le50mb/Structures/2ee8ec06b84f110c83aa430342221531-10-11-c61ece3ab6dc88365a9e7ac7c44683bcStructures.txt.zip` (46.3MB); `datasets/38_absolut_nird/small_le50mb/Structures/64405938124084acdccd7bba13716acf-10-11-df147066b142a67bf253a1feafe9c254Structures.txt.zip` (46.1MB); `datasets/38_absolut_nird/small_le50mb/Structures/032b117b995e693f21189f10145f36e2-10-11-269b80f99ba88701658ce3528bc65fa9Structures.txt.zip` (44.7MB); `datasets/38_absolut_nird/small_le50mb/Structures/SULULcba6d4ff1f902bb3b291902e082a58b2-10-11-50650b72ae40c63b5ec86afaf6e7167bStructures.txt.zip` (44.6MB)。
- 适合用途：合成 antibody-antigen binding/结构任务、负例/正例或模拟评分，适合大规模预训练/benchmark。
- 状态/注意：只抓小于 50MB 分块，避免超大包。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/44_negative_class_optimization_zenodo` — MiniAbsolut/负类优化数据

- 规模：14.5GB，文件数 9。
- 内容：MiniAbsolut lrzip、Porebski negative-class tar、checkpoint。
- 主要文件类型：.lrz:5, .md:2, .ckpt:1, .tar.gz:1。
- 关键文件：`datasets/44_negative_class_optimization_zenodo/11191740/Frozen_MiniAbsolut_ML.tar.lrz` (9.2GB); `datasets/44_negative_class_optimization_zenodo/11191740/Frozen_MiniAbsolut_ML_shuffled.tar.lrz` (1.7GB); `datasets/44_negative_class_optimization_zenodo/10123621/checkpoint-bsf24_bert_base-epoch=00-val_loss=0.13.ckpt` (988.0MB); `datasets/44_negative_class_optimization_zenodo/11191740/MiniAbsolut_Splits.tar.lrz` (961.7MB); `datasets/44_negative_class_optimization_zenodo/11191740/MiniAbsolut.tar.lrz` (666.6MB)。
- 适合用途：抗体-抗原分类、负例构造、hard negative/decoy 训练。
- 状态/注意：lrzip 未安装，仅 size-only；Porebski tar.gz 校验通过。 校验摘要：present_size_only:2, ok:1。

### D. 背景抗体库、治疗抗体和天然性

#### `datasets/04_plabdab` — PLAbDab 专利/文献抗体库

- 规模：9.3GB，文件数 6。
- 内容：paired/unpaired antibody sequences 和模型归档。
- 主要文件类型：.gz:2, .tar.gz:2, .bib:1, .txt:1。
- 关键文件：`datasets/04_plabdab/plabdab_data.tar.gz` (4.7GB); `datasets/04_plabdab/plabdab_models.tar.gz` (4.5GB); `datasets/04_plabdab/unpaired_sequences.csv.gz` (41.9MB); `datasets/04_plabdab/paired_sequences.csv.gz` (10.9MB); `datasets/04_plabdab/plabdab.bib` (0.7KB)。
- 适合用途：抗体序列背景、专利去重、VH/VL 配对建模、相似性排除；抗原标签需进一步解析。
- 状态/注意：大包未展开；作为原始归档保存。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/07_oas` — OAS 页面与元数据探针

- 规模：190.0KB，文件数 11。
- 内容：OAS 下载页、paired/unpaired 文档和索引缓存。
- 主要文件类型：.html:7, .json:2, .md:1, .txt:1。
- 关键文件：`datasets/07_oas/OAS_unpaired_downloads.html` (47.2KB); `datasets/07_oas/OAS_doc_paired.html` (47.0KB); `datasets/07_oas/OAS_doc.html` (32.6KB); `datasets/07_oas/OAS_paired_downloads.html` (28.9KB); `datasets/07_oas/OAS_home.html` (9.0KB)。
- 适合用途：免疫组库来源发现；直接训练数据在 12_oas_downloads/22_igfold_data/49 等处。
- 状态/注意：网页/JSON 辅助材料。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/12_oas_downloads` — OAS 真实下载子集

- 规模：777.6MB，文件数 33。
- 内容：OAS heavy-chain CSV.gz 子集和索引。
- 主要文件类型：.gz:30, .bin:1, .html:1, .txt:1。
- 关键文件：`datasets/12_oas_downloads/SRR3544217_1_Heavy_Missing_c_domain.csv.gz` (137.8MB); `datasets/12_oas_downloads/SRR3544218_1_Heavy_Missing_c_domain.csv.gz` (137.5MB); `datasets/12_oas_downloads/SRR3544222_1_Heavy_Missing_c_domain.csv.gz` (126.0MB); `datasets/12_oas_downloads/SRR3544221_1_Heavy_Missing_c_domain.csv.gz` (125.5MB); `datasets/12_oas_downloads/SRR3544220_1_Heavy_Missing_c_domain.csv.gz` (113.2MB)。
- 适合用途：抗体天然序列背景、语言模型/天然性评分、CDR 长度分布；无统一抗原标签。
- 状态/注意：已下载有限子集，不是全 OAS。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/15_covabdab` — CoV-AbDab 新冠抗体库

- 规模：353.6MB，文件数 4。
- 内容：CoV-AbDab CSV、ANARCI 编号 JSON、PDB structures 包。
- 主要文件类型：.csv:1, .json:1, .tar.gz:1, .bib:1。
- 关键文件：`datasets/15_covabdab/CoV-AbDab_PDBStructures_080224.tar.gz` (290.4MB); `datasets/15_covabdab/CoV-AbDab_ANARCINumberings_080224.json` (55.1MB); `datasets/15_covabdab/CoV-AbDab_080224.csv` (8.1MB); `datasets/15_covabdab/covabdab.bib` (1.9KB)。
- 适合用途：SARS-CoV/SARS-CoV-2 抗体序列、结构、靶标注释；可用于病毒抗体专项预训练/评估。
- 状态/注意：适合冠状病毒抗体子任务，不是通用 VHH 专用。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/21_therasabdab` — Thera-SAbDab 治疗性抗体表

- 规模：939.0KB，文件数 5。
- 内容：治疗性抗体序列/结构在线下载 CSV/XLSX。
- 主要文件类型：.csv:2, .xlsx:2, .txt:1。
- 关键文件：`datasets/21_therasabdab/TheraSAbDab_SeqStruc_OnlineDownload.csv` (621.4KB); `datasets/21_therasabdab/TheraSAbDab_SeqStruc_OnlineDownload.xlsx` (313.5KB); `datasets/21_therasabdab/FAILED_DOWNLOADS.txt` (0.1KB); `datasets/21_therasabdab/TheraSAbDab_INNwithnoSeq.xlsx` (0.0KB); `datasets/21_therasabdab/TheraSAbDab_INNwithnoSeq.csv` (0.0KB)。
- 适合用途：临床/治疗性抗体序列、靶点、开发状态参考；可用于 developability 与去重。
- 状态/注意：小型高价值元数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/23_naturalantibody` — NaturalAntibody 网页缓存

- 规模：1.4MB，文件数 5。
- 内容：ASD/AgAb/AbDesign/therapeutics/NGS 页面。
- 主要文件类型：.html:5。
- 关键文件：`datasets/23_naturalantibody/asd_agab.html` (302.4KB); `datasets/23_naturalantibody/abdesign.html` (285.9KB); `datasets/23_naturalantibody/antibody_data.html` (278.3KB); `datasets/23_naturalantibody/therapeutics.html` (260.6KB); `datasets/23_naturalantibody/ngs.html` (257.7KB)。
- 适合用途：NaturalAntibody 数据入口和来源说明。
- 状态/注意：辅助网页材料。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/31_agab_naturalantibody` — AgAb/NaturalAntibody parquet

- 规模：359.7MB，文件数 45。
- 内容：AgAb ASD parquet 分片和元数据。
- 主要文件类型：.crc:21, .parquet:20, .tsv:2, .py:1, .json:1。
- 关键文件：`datasets/31_agab_naturalantibody/asd/part-00016-883dd12e-3f06-4505-b326-04b6c16a7852-c000.snappy.parquet` (20.2MB); `datasets/31_agab_naturalantibody/asd/part-00015-af04209c-672a-4fd7-9cc5-1fdaeaf06aa0-c000.snappy.parquet` (18.3MB); `datasets/31_agab_naturalantibody/asd/part-00006-b818506c-2926-406c-936b-66da5c9acdbc-c000.snappy.parquet` (18.2MB); `datasets/31_agab_naturalantibody/asd/part-00000-3a065afd-b2fa-4875-a6e5-911e95e3f86c-c000.snappy.parquet` (18.2MB); `datasets/31_agab_naturalantibody/asd/part-00009-6b319ece-d8eb-4e15-b579-4e98d3a456a1-c000.snappy.parquet` (18.2MB)。
- 适合用途：抗原-抗体/单域抗体背景数据；需进一步解析字段。
- 状态/注意：适合补充真实抗体/抗原配对背景。 校验摘要：未单独校验；见文件存在性/来源脚本。

### E. 模型仓库、权重、复现材料

#### `datasets/10_github_repos` — 第一批模型仓库与代码数据

- 规模：5.0GB，文件数 6089。
- 内容：AbAgIntPre、NABP-BERT、MuLAAIP、NanoDesigner、AIDA、AVIDa、Graphinity、RFantibody、IgFold 等代码仓库及部分权重/样例数据。
- 主要文件类型：.pdb:1573, .py:1190, [noext]:626, .sample:468, .csv:441, .txt:374。
- 关键文件：`datasets/10_github_repos/Absolut/.git/objects/pack/pack-c1a9d810f20df14e6475e4502c800f4a9e7fa92e.pack` (423.1MB); `datasets/10_github_repos/graphinity/.git/objects/pack/pack-5f99a539c2bbd61c96f04ccefc3878f6b96bd01a.pack` (218.9MB); `datasets/10_github_repos/NanoBind/output/checkpoint/NanoBind_pro(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model` (137.5MB); `datasets/10_github_repos/SAAINT/.git/objects/pack/pack-0188d18999a40f8498f08f66e6d800aaf6cd6fa4.pack` (128.8MB); `datasets/10_github_repos/NanoBind/.git/objects/pack/pack-31c06852c4f4cdbe47b8847a4bebfc704ae0f323.pack` (107.4MB)。
- 适合用途：复现实验、读取原作者数据格式、抽取训练脚本、基线模型；含部分模型权重和样例 CSV/PDB。
- 状态/注意：有 .git 与代码环境文件；训练前需区分源码、权重和数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/16_antifold` — AntiFold 模型权重

- 规模：540.6MB，文件数 1。
- 内容：AntiFold antibody inverse folding 权重 model.pt。
- 主要文件类型：.pt:1。
- 关键文件：`datasets/16_antifold/model.pt` (540.6MB)。
- 适合用途：逆折叠/结构给定序列设计基线。
- 状态/注意：模型权重，不是训练数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/20_diffab` — DiffAb 权重

- 规模：231.0MB，文件数 5。
- 内容：DiffAb fixbb/codesign/structure_pred 权重。
- 主要文件类型：.pt:4, .md:1。
- 关键文件：`datasets/20_diffab/structure_pred.pt` (58.6MB); `datasets/20_diffab/codesign_single.pt` (58.6MB); `datasets/20_diffab/codesign_multicdrs.pt` (58.6MB); `datasets/20_diffab/fixbb.pt` (55.4MB); `datasets/20_diffab/README.md` (0.3KB)。
- 适合用途：抗体设计/结构生成基线模型。
- 状态/注意：模型权重，不是训练数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/22_igfold_data` — IgFold/OAS/AF-OAS 数据与结构包

- 规模：14.5GB，文件数 7。
- 内容：IgFold 相关 OAS_paired、AF-OAS、SAbDab、Jaffe2022 等包。
- 主要文件类型：.zip:3, .tar.gz:2, .sh:1, .tsv:1。
- 关键文件：`datasets/22_igfold_data/Jaffe2022.tar.gz` (6.8GB); `datasets/22_igfold_data/OAS_paired.tar.gz` (5.9GB); `datasets/22_igfold_data/zenodo_7820263/af_oas_paired.zip` (923.7MB); `datasets/22_igfold_data/zenodo_7820263/af_oas_unpaired.zip` (767.5MB); `datasets/22_igfold_data/zenodo_7820263/sabdab.zip` (143.4MB)。
- 适合用途：抗体结构预测/预训练数据、paired/unpaired 抗体序列；Jaffe2022 为部分下载。
- 状态/注意：含 partial 标记；训练前需识别完整包。 校验摘要：present_size_only:1。

#### `datasets/37_model_repos` — AIDA 预训练权重

- 规模：601.7MB，文件数 2。
- 内容：PBALM/GearNet 预训练权重。
- 主要文件类型：.pth:1, .tar.gz:1。
- 关键文件：`datasets/37_model_repos/AIDA_pretrained/pretrained_PBALM.tar.gz` (524.8MB); `datasets/37_model_repos/AIDA_pretrained/mc_gearnet_edge.pth` (77.0MB)。
- 适合用途：抗体-抗原结构/序列表征基线。
- 状态/注意：模型权重。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/43_abag_champloo_zenodo` — AbAg-Champloo 结构准确性/置信度数据

- 规模：559.4MB，文件数 4。
- 内容：RMSD、topmodel accuracy、ipTM confidence zips。
- 主要文件类型：.zip:3, .png:1。
- 关键文件：`datasets/43_abag_champloo_zenodo/rmsd_between_replicas.zip` (542.6MB); `datasets/43_abag_champloo_zenodo/topmodel_structure_accuracy.zip` (15.2MB); `datasets/43_abag_champloo_zenodo/ab_ag_champloo_graphical_abstract.png` (1.4MB); `datasets/43_abag_champloo_zenodo/iptm_confidence_scores.zip` (147.3KB)。
- 适合用途：抗体-抗原结构预测评估、模型置信度校准。
- 状态/注意：real_shuffled_complexes 大包未启动。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/50_github_model_repos_extra` — 额外 GitHub 模型/数据仓库

- 规模：2.1GB，文件数 4169。
- 内容：SE3Bind、AAPred、TransABseq、polyreactivity 等额外 repo zip/unpacked。
- 主要文件类型：.py:1061, .png:824, .json:804, .csv:345, .yaml:264, .pdb:189。
- 关键文件：`datasets/50_github_model_repos_extra/zips/choderalab_antibody-mutations-master.zip` (602.3MB); `datasets/50_github_model_repos_extra/zips/aish-1509_AAPred-main.zip` (70.6MB); `datasets/50_github_model_repos_extra/unpacked/cuifengLI_TransABseq-main/TransABseq-main/save_model/model_CV1_161(xgboost).h5` (62.2MB); `datasets/50_github_model_repos_extra/zips/cuifengLI_TransABseq-main.zip` (61.9MB); `datasets/50_github_model_repos_extra/unpacked/marcsingleton_polyreactivity_prediction-main/polyreactivity_prediction-main/data/raw/high_polyreactivity_high_throughput.csv` (56.5MB)。
- 适合用途：模型复现、特征处理、可借鉴数据格式与 baseline；部分仓库含数据表。
- 状态/注意：19 个 repo archive 校验通过；FAILED.tsv 保留历史 main 404 记录，fallback 已恢复。 校验摘要：ok:19, done:1。

#### `datasets/52_github_late_model_repos` — 后补 GitHub 抗体模型仓库

- 规模：381.5MB，文件数 680。
- 内容：AbAffinity、DeepAAI、RLEAAI、MambaAAI、AbAgCDM 等。
- 主要文件类型：.py:223, .npy:220, .pyc:66, .csv:34, [noext]:30, .txt:20。
- 关键文件：`datasets/52_github_late_model_repos/zips/harshitsinghsnu_AbAffinity-main.zip` (66.1MB); `datasets/52_github_late_model_repos/zips/zhouyu9931_RLEAAI-main.zip` (51.3MB); `datasets/52_github_late_model_repos/unpacked/harshitsinghsnu_AbAffinity-main/AbAffinity-main/data/allcdr_mutation_650M.pkl` (31.3MB); `datasets/52_github_late_model_repos/unpacked/zhouyu9931_RLEAAI-main/RLEAAI-main/ckp/SARS-CoV-2.pth` (24.2MB); `datasets/52_github_late_model_repos/unpacked/zhouyu9931_RLEAAI-main/RLEAAI-main/ckp/HIV.pth` (24.2MB)。
- 适合用途：亲和力/交互预测模型代码、权重、训练数据格式和 baseline。
- 状态/注意：新增；7 个 zip 全部校验通过并解压。 校验摘要：ok:7, done:1。

### F. 采集过程与辅助索引

#### `datasets/01_small_tables` — 早期网页探针与小表

- 规模：54.6KB，文件数 4。
- 内容：sdAb-DB 页面等早期探针缓存。
- 主要文件类型：.html:3, .txt:1。
- 关键文件：`datasets/01_small_tables/sdab_db__Browse.html` (39.9KB); `datasets/01_small_tables/sdab_db_home.html` (5.4KB); `datasets/01_small_tables/sdab_db__Advanced_Search.html` (5.0KB); `datasets/01_small_tables/SHA256SUMS.txt` (0.3KB)。
- 适合用途：来源发现和网页解析线索；不建议直接作为训练主表。
- 状态/注意：小型辅助材料。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/09_model_datasets` — 模型/数据库入口探针

- 规模：242.2KB，文件数 14。
- 内容：TheraSAbDab、CoV-AbDab、SNACDB 等网页/README 探针。
- 主要文件类型：.txt:5, .html:5, .md:4。
- 关键文件：`datasets/09_model_datasets/therasabdab_probe.html` (96.6KB); `datasets/09_model_datasets/CoV-AbDab.html` (70.8KB); `datasets/09_model_datasets/SNACDB_readme.txt` (18.0KB); `datasets/09_model_datasets/zenodo_15870002_jina.md` (13.7KB); `datasets/09_model_datasets/STCRDab.html` (12.3KB)。
- 适合用途：来源记录和后续抓取线索。
- 状态/注意：辅助索引，不作为主训练集。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/11_huggingface` — 空 HuggingFace 预留目录

- 规模：4.0KB，文件数 0。
- 内容：早期 HF 预留目录，当前无文件。
- 主要文件类型：无。
- 关键文件：无文件或仅占位目录。
- 适合用途：无直接用途。
- 状态/注意：可保留或后续清理。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/41_antibody_benchmark_pierce` — Pierce antibody benchmark cases

- 规模：19.7KB，文件数 1。
- 内容：antibody_benchmark_cases.xlsx。
- 主要文件类型：.xlsx:1。
- 关键文件：`datasets/41_antibody_benchmark_pierce/antibody_benchmark_cases.xlsx` (15.7KB)。
- 适合用途：抗体 benchmark case 元数据。
- 状态/注意：小型表，需人工确认字段。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/48_discovery` — 发现记录/候选元数据

- 规模：3.1MB，文件数 7。
- 内容：HF/GitHub/Zenodo 搜索结果、候选 metadata。
- 主要文件类型：.json:4, .jsonl:3。
- 关键文件：`datasets/48_discovery/hf_candidate_metadata.jsonl` (2.8MB); `datasets/48_discovery/zenodo_gap_search.json` (209.9KB); `datasets/48_discovery/hf_gap_candidate_metadata.jsonl` (45.4KB); `datasets/48_discovery/huggingface_dataset_search_broad.json` (43.9KB); `datasets/48_discovery/github_repo_search.json` (21.5KB)。
- 适合用途：追踪已发现但未抓/延后/门控的数据源。
- 状态/注意：不是训练数据，是采集审计材料。 校验摘要：未单独校验；见文件存在性/来源脚本。

#### `datasets/logs` — 下载日志

- 规模：19.7MB，文件数 64。
- 内容：各阶段 wget/aria2/API 抓取日志和 PID 记录。
- 主要文件类型：.log:57, .pid:5, .txt:2。
- 关键文件：`datasets/logs/hf_datasets_20260706T222330.log` (13.8MB); `datasets/logs/hf_additional_nanobody_20260707T112800.log` (2.2MB); `datasets/logs/13_sabdab_structures_20260706T222547.log` (1.6MB); `datasets/logs/08_indi2_full_parallel_20260706T224641.log` (504.9KB); `datasets/logs/20_diffab_20260706T221931.log` (366.0KB)。
- 适合用途：审计和故障恢复。
- 状态/注意：非训练数据。 校验摘要：未单独校验；见文件存在性/来源脚本。

## 4. 当前最适合先做成训练样本表的数据

### 4.1 直接监督：抗体/纳米抗体序列 + 抗原/受体 + 连续或离散标签

| 数据 | 现有路径 | 标签 | 备注 |
| --- | --- | --- | --- |
| ZYMScott VHH affinity-score/seq | `datasets/49_hf_broad_antibody/ZYMScott_vhh_affinity-score/`、`ZYMScott_vhh_affinity-seq/` | `score` 连续分数，含 `seq/CDR1/CDR2/CDR3` | 最贴近 VHH affinity 排序；需要确认 score 方向。 |
| AbBiBench binding_affinity | `datasets/14_antibody_benchmark/AbBiBench/binding_affinity/`、`datasets/49_hf_broad_antibody/AbBibench_.../binding_affinity/` | `binding_score`，heavy/light chain | 有结构 PDB，可做序列+结构。 |
| SAbDab affinity small table | `datasets/28_affinity_kd/antibody_affinity_protein_sabdab.csv` | `Y` Kd/亲和力数值 | 小但字段直接，适合 sanity check。 |
| sdAb-DB affinity rows | `datasets/36_sdab_db/sdab_db_affinity_rows.csv` | `kd_nm`、antigen、sequence | 单域抗体/VHH 最直接的真实标签之一；含 Unknown 需清洗。 |
| mCSM-AB | `datasets/29_csm_ab/*.csv` | `∆G(Kcal/mol)` | 结构复合物亲和力/能量标签。 |
| AbDesignDB | `datasets/30_abdesign_db/datasets_mut.csv` | ELISA/affinity ratio、mutation、CDR | 适合突变优化和 CDR 改造。 |
| SKEMPI | `datasets/03_skempi/skempi_v2.csv` | mutant/wt affinity、kinetics | 泛 PPI 突变效应，可做预训练。 |
| PPB-Affinity | `datasets/32_ppb_affinity/PPB-Affinity.xlsx` + `PDB.zip` | 蛋白-蛋白亲和力 | 泛受体-配体结合预训练。 |
| AlphaSeq/Graphinity/MiniAbsolut | `datasets/17_alphaseq/`、`19_graphinity/`、`44_negative_class_optimization_zenodo/` | 高通量分数、ΔΔG、正负/decoy | 需要解包和统一标签语义。 |

### 4.2 位点监督：paratope/epitope/interface

| 数据 | 现有路径 | 标签 | 备注 |
| --- | --- | --- | --- |
| ZYMScott Paratope | `datasets/49_hf_broad_antibody/ZYMScott_Paratope/` | `paratope`、`epitope` 0/1 序列掩码，含 nanobody/antigen sequence | 最适合训练 VHH-抗原接触位点。 |
| NanoLAS | `datasets/35_nanolas/active-residue.jsonl`、`ligand-binding-sites.jsonl`、`cursor_sequence/sequence_cursor.csv` | active residue、binding site、CDR | 适合纳米抗体位点/功能弱监督。 |
| AsEP | `datasets/27_asep/` | epitope/paratope benchmark | 需要解包后建立统一索引。 |
| SAbDab/SAAINT/SNAC/ABDB | `datasets/13_sabdab_structures/`、`33_saaint_db/`、`18_snacdb/`、`42_abdb/` | 可从结构中计算接触残基 | 需要用 Bio.PDB/MDAnalysis 提取界面。 |

### 4.3 背景和预训练：真实抗体/纳米抗体序列

| 数据 | 现有路径 | 用途 |
| --- | --- | --- |
| INDI2 | `datasets/08_indi2/` | VHH/纳米抗体大规模真实序列、scaffold/naturalness。 |
| VHHCorpus-2M | `datasets/49_hf_broad_antibody/COGNANO_VHHCorpus-2M/`、`datasets/24_hf_nanobody/VHHCorpus-2M/` | 2M 级 VHH 序列预训练/分布统计。 |
| PLAbDab/PLAbDab-nano | `datasets/04_plabdab/`、`datasets/02_plabdab_nano/` | 专利/文献抗体和单域抗体背景、查重。 |
| OAS/OAS paired | `datasets/12_oas_downloads/`、`datasets/22_igfold_data/` | 抗体天然序列和 paired 背景。 |
| sdAb-DB/NanoLAS/ANDD | `datasets/36_sdab_db/`、`datasets/35_nanolas/`、`datasets/05_zenodo_andd/` | 单域抗体真实序列、目标、文献/结构注释。 |

## 5. 建议的统一训练索引字段

下一步不要直接拿目录训练，建议先生成一个规范化样本索引表，例如：

```text
sample_id
source_dataset
source_file
antibody_format        # VHH / VH-VL / Fab / IgG / protein binder / unknown
heavy_or_vhh_sequence
light_sequence
cdr1 / cdr2 / cdr3
antigen_or_receptor_name
antigen_or_receptor_sequence
pdb_id
structure_path
label_type             # Kd / binding_score / ddG / binary / paratope_mask / epitope_mask / polyreactivity
label_value
label_unit
label_direction        # larger_is_better / smaller_is_better / unknown
split                  # train / val / test / unknown
is_negative_or_decoy
license_or_source_note
quality_flag
```

## 6. 需要清洗/注意的事项

- 分数方向不统一：`Kd` 越小越好，`binding_score`/`score` 方向需要逐源确认。
- 抗体格式不统一：VHH、VH/VL、Fab、IgG、普通蛋白 binder 混在一起；必须加 `antibody_format`。
- 抗原/受体字段不统一：有的只有 antigen name，有的有 sequence，有的只有 PDB chain。
- 结构文件多为压缩包，训练前要建立 `structure_path` 索引，避免每次随机解压。
- 大型背景库如 INDI/OAS/VHHCorpus 多数没有具体结合标签，应作为预训练/天然性/负采样背景，而不是 PVRIG 或任意靶点阳性。
- 专利/公开库可能有重复序列，后续要做 CDR 级和全序列去重。
- `VALIDATION_SUMMARY.tsv` 中 `present_size_only` 表示二进制模型或 lrzip 等未做内容级解压校验，不代表不可用。

## 7. 续传和复查命令

```bash
cd /mnt/d/work/抗体/data
bash datasets/RESUME_ACTIVE_DOWNLOADS.sh
python3 datasets/generate_download_report.py
column -ts $'\t' datasets/DOWNLOAD_MANIFEST.tsv | less -S
column -ts $'\t' datasets/VALIDATION_SUMMARY.tsv | less -S
```
