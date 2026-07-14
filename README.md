# Nanobody / PVRIG 轻量工作区索引

这是 `/mnt/d/work/抗体` 本地工作区的轻量 Git 镜像，用于保存和共享纳米抗体 / PVRIG 项目中可复查、可阅读、可复现的代码、脚本、文档、报告和小型结构/表格文件。

本仓库刻意不上传大型数据集、模型权重、Conda/本地环境、缓存、对接运行中间产物和批量下载镜像。完整同步范围以 `docs/lightweight_sync_manifest.txt` 为准；最新文件数、体量和同步时间见 `docs/LIGHTWEIGHT_SYNC_STATUS.md`。

## 快速阅读入口

| 你想找什么 | 建议入口 |
| --- | --- |
| 当前赛题目标、资产缺口、Top50/Top10 readiness | `node1/PVRIG_COMPETITION_ASSET_AND_GOAL_AUDIT_20260712.md` |
| 项目进展、阶段结论、下一步 | `PROJECT_PROGRESS.md` |
| Phase I / Phase I-B 设计思路 | `docs/PHASE_I_PLAN.md`, `docs/PHASE_I_B_PLAN.md`, `docs/PHASE_I_EXPLORATION.md` |
| PVRIG-PVRL2 结构热点与脚本 | `data/structures/`, `scripts/extract_pvrig_interface.py`, `scripts/build_pvrig_hotspot_set.py` |
| 成功案例机制研究 | `机制/README.md`, `机制/PVRIG_PVRL2_机制当前结论.md`, `机制/case_studies/` |
| 阳性抗体与 scaffold 库 | `positives/`, `scaffolds/README.md` |
| docking / 校准 / 阈值分析 | `docking/calibration/`, `docking/case02_hr151_pvrig/reports/` |
| 固定128候选的双构象独立重对接 | `pvrig_v3_dual_conformation_redocking_20260714/README.md`, `pvrig_v3_dual_conformation_redocking_20260714/RUN_STATUS.md` |
| 本地模型复现说明 | `code/docs/NANOBODY_MODEL_REPRODUCTION_GUIDE_ZH.md`, `code/docs/DEEPNANO_DETAILED_ZH.md` |
| Node1 部署和 QC 流程 | `node1/NODE1_ANTIBODY_TOOLS_QUICKSTART.md`, `node1/VHH_COMPETITION_QC_PIPELINE_RUNBOOK.md` |
| 轻量同步规则 | `docs/LIGHTWEIGHT_SYNC_INVENTORY.md`, `scripts/sync_lightweight_to_github.sh` |
| 最新同步状态 | `docs/LIGHTWEIGHT_SYNC_STATUS.md` |

## 文件夹导览

### `code/`

纳米抗体结合/亲和力模型的轻量代码副本与中文复现说明。这里保留了 DeepNano、NABP-BERT、NABP-LSTM-Att、NanoBind、NanoBinder、Sequence-Based NABP 等模型的源码、配置、notebook、小型示例数据和论文/图片说明；大型权重、训练输出和下载后台目录不在仓库中。

- 复现总入口：`code/docs/NANOBODY_MODEL_REPRODUCTION_GUIDE_ZH.md`
- DeepNano：`code/docs/DEEPNANO_DETAILED_ZH.md`, `code/downloaded_models/DeepNano/`
- NABP-BERT：`code/docs/NABP_BERT_DETAILED_ZH.md`, `code/downloaded_models/NABP-BERT/`
- 基线/辅助脚本：`code/repro_helpers/sequence_based_gapped_kmer.py`

### `data/`

项目级小型数据索引、结构包、Phase 1 序列基线模型脚本和候选打分报告。大型语料、模型数据和训练产物被排除，仅保留可复查的小表格、PVRIG/PVRL2 结构文件、热点残基表和 smoke/eval 结果。

- 数据清点：`data/DATA_INVENTORY_DETAILED.md`
- 小模型计划：`data/PVRIG_VHH_SMALL_MODEL_PLAN.md`
- Phase2 5080 训练实验：`data/docs/phase2_5080_training/README.md`, `data/experiments/phase2_5080_v1/README.md`
- 结构与热点：`data/structures/8X6B.pdb`, `data/structures/9E6Y.pdb`, `data/structures/PVRIG_hotspot_set_v1.csv`
- 基线模型脚本：`data/scripts/train_phase1_sequence_baseline.py`, `data/scripts/score_pvrig_candidates_with_calibration.py`
- 报告：`data/reports/phase1_sequence_baseline_eval.md`, `data/reports/pvrig_candidate_calibrated_scoring_v0.md`

### `docking/`

PVRIG 成功案例、HR151/PVRIG 阳性对照、突变面板和阈值敏感性分析的轻量对接结果与运行脚本。这里保留输入、批处理清单、结果摘要、机制评分 CSV/JSON、后处理脚本和结论文档；HADDOCK3 工作目录、姿态大文件、远端日志和中间输出已排除。

- 突变校准：`docking/calibration/mutant_validation_panel/README.md`
- 专利成功序列校准：`docking/calibration/patent_success_validation/PATENT_SUCCESS_SERIES_CALIBRATION.md`
- HR151 阳性对照：`docking/case02_hr151_pvrig/reports/`
- 通用脚本：`docking/scripts/`
- 成功案例判据：`docking/success_case_validation/`

### `docs/`

跨目录的项目说明、阶段计划和轻量同步审计资料。适合作为新读者了解项目边界、同步策略和当前阶段目标的入口。

- 阶段计划：`docs/PHASE_I_PLAN.md`, `docs/PHASE_I_B_PLAN.md`
- 探索记录：`docs/PHASE_I_EXPLORATION.md`
- 同步审计：`docs/LIGHTWEIGHT_SYNC_INVENTORY.md`
- 精确文件清单：`docs/lightweight_sync_manifest.txt`

### `node1/`

Node1 机器/环境上的工具部署、运行手册和竞赛 QC 管线说明。适合查看如何在节点上复现工具链、运行 DeepNano/RFantibody/TNP/ProtParam 等组件，以及如何执行 VHH 竞赛筛选流程。

- 快速开始：`node1/NODE1_ANTIBODY_TOOLS_QUICKSTART.md`
- SSH/节点说明：`node1/NODE1_SSH.md`
- QC 管线：`node1/VHH_COMPETITION_QC_PIPELINE_RUNBOOK.md`, `node1/competition_qc/vhh_competition_qc.py`
- 工具部署：`node1/DEEPNANO_NODE1_DEPLOYMENT.md`, `node1/RFANTIBODY_NODE1_DEPLOYMENT.md`, `node1/VHH_EVALUATION_TOOLS_NODE1_DEPLOYMENT.md`

### `positives/`

已知 PVRIG 阳性抗体/纳米抗体的序列、CDR、机制参考和相似性排除表。用于阳性对照、机制校准、CDR novelty 检查和 scaffold/候选序列筛选。

- 序列：`positives/known_positive_antibodies.fasta`
- CDR 表：`positives/known_positive_CDR_table.csv`
- 元数据：`positives/positive_antibody_metadata.csv`
- 机制与排除：`positives/mechanism_reference_table.csv`, `positives/positive_CDR_similarity_exclusion_table.csv`

### `pvrig_v3_dual_conformation_redocking_20260714/`

固定的 PVRIG 双构象独立 HADDOCK3 评价器。它冻结128条候选和47条协议回归控制，分别对 8X6B、9E6Y 执行3个显式 seed 的真正独立重对接，并在 native/cross 两个参考系形成2x2几何评分。该目录修复旧流程的跨构象残基编号漂移和 `HETATM` 污染问题；在控制组稳定性门禁通过前，下一批 P2/P3/P4 序列生成被硬锁定。

- 协议与复现入口：`pvrig_v3_dual_conformation_redocking_20260714/README.md`
- 当前运行状态：`pvrig_v3_dual_conformation_redocking_20260714/RUN_STATUS.md`
- 协议参数：`pvrig_v3_dual_conformation_redocking_20260714/config/protocol_spec.json`
- 固定输入和任务：`pvrig_v3_dual_conformation_redocking_20260714/inputs/`, `pvrig_v3_dual_conformation_redocking_20260714/manifests/`

### `reports/`

项目分析报告、验证记录、图片资产、PLAbDab-nano 访问/许可判断、QC 指标范围和团队 worker 输出。适合查看“已经验证了什么”和“哪些结论有证据”。

- 总体验证：`reports/leader_verification.md`
- 外部来源证据：`reports/external_source_evidence.md`
- 机制图片说明：`reports/pvrig_pvrl2_binding_mechanism_visual_notes.md`
- QC 范围：`reports/qc_positive_metric_ranges/`
- 团队记录：`reports/team/`
- 阳性验证：`reports/validator/KNOWN_POSITIVE_VALIDATION.md`

### `scaffolds/`

VHH scaffold 库和筛选结果。包含原始 scaffold 池、清洗后的 scaffold FASTA、Top 200 设计用 scaffold、质量表、聚类表和来源登记。

- 入口：`scaffolds/README.md`
- 清洗库：`scaffolds/clean_vhh_scaffold_library.fasta`
- 设计候选：`scaffolds/top_200_vhh_scaffolds_for_design.csv`, `scaffolds/top_200_vhh_scaffolds_for_design.fasta`
- 质量与来源：`scaffolds/vhh_scaffold_quality_table.csv`, `scaffolds/source_registry.csv`

### `scripts/`

根项目的可复现脚本。包括 PVRIG interface/hotspot 提取、机制视图生成、PLAbDab-nano scaffold 导入、编号协调、阳性验证、阶段输出校验和轻量 Git 同步。

- 同步脚本：`scripts/sync_lightweight_to_github.sh`
- 清单生成：`scripts/build_lightweight_sync_manifest.py`
- 结构/热点：`scripts/extract_pvrig_interface.py`, `scripts/build_pvrig_hotspot_set.py`
- 机制视图：`scripts/build_pvrig_mechanism_view.py`
- 验证：`scripts/run_known_positive_validator.py`, `scripts/verify_phase_i_outputs.py`

### `tests/`

根项目轻量回归测试，主要覆盖结构界面提取和 PVRIG 编号协调逻辑。

- `tests/test_extract_pvrig_interface.py`
- `tests/test_reconcile_pvrig_numbering.py`

### `tools/`

本地工具和工具调研产物的轻量部分。`tools/ab-data-validator/` 是可运行的抗体数据校验工具源码与测试；`tools/nanobody_tool_survey/` 保留工具调研报告、元数据和资产下载脚本，排除了大规模第三方代码镜像和论文镜像。

- 数据校验工具：`tools/ab-data-validator/README.md`, `tools/ab-data-validator/src/ab_data_validator/`
- 校验测试：`tools/ab-data-validator/tests/`
- 工具调研报告：`tools/nanobody_tool_survey/report/nanobody_tool_survey_full.md`
- 工具资产清点：`tools/nanobody_tool_survey/report/asset_inventory.md`

### `visualization/`

PVRIG-PVRL2 机制和结构界面的轻量可视化入口。包含一个 Python panel viewer、HTML 机制视图和 PyMOL 脚本。

- `visualization/pvrig_panel_viewer.py`
- `visualization/pvrig_pvrl2_mechanism_view.html`
- `visualization/pvrig_pvrl2_mechanism_view.pml`

### `机制/`

中文机制研究工作区，围绕 PVRIG-PVRL2 阻断机制、成功案例、专利序列、结构证据、文献证据和可视化展开。这里是理解“为什么某些 PVRIG 设计可能有效”的主要阅读区。

- 总入口：`机制/README.md`, `机制/共享阅读入口.md`
- 当前结论：`机制/PVRIG_PVRL2_机制当前结论.md`
- 成功案例：`机制/success_cases/PVRIG成功案例机制研究_v1.md`
- 分案例机制：`机制/case_studies/`
- 文献/专利/序列/结构数据：`机制/data/`
- 可视化：`机制/visualization/`, `机制/figures/`

## 根目录文件

| 文件 | 用途 |
| --- | --- |
| `PROJECT_PROGRESS.md` | 项目进展账本，建议优先阅读。 |
| `README.md` | 当前目录导览和检索入口。 |
| `.gitignore` | 默认忽略所有新增文件，防止误传大数据/权重/运行产物。 |
| `.gitattributes` | 统一文本/结构/表格文件的 Git 属性。 |

## 检索建议

- 按主题查找：用 `rg "PVRIG-151|HR151|PVRIG_hotspot|DeepNano|NABP-BERT|scaffold|QC"`。
- 按入口阅读：先看各目录的 `README.md` 或本 README 中列出的代表文件。
- 按同步范围核对：查看 `docs/lightweight_sync_manifest.txt`，它列出当前 Git 镜像实际跟踪的所有文件。
- 按证据强度阅读：优先看 `reports/`, `data/reports/`, `docking/calibration/`, `机制/data/literature/` 中的摘要表和结论文档。

## 轻量同步策略

- 构建 allowlist：`scripts/build_lightweight_sync_manifest.py`
- 同步到 GitHub：`scripts/sync_lightweight_to_github.sh`
- 最新仓库可见进展：`docs/LIGHTWEIGHT_SYNC_STATUS.md`
- 启动周期自动同步：`scripts/lightweight_sync_daemon.sh start`
- 查看/停止自动同步：`scripts/lightweight_sync_daemon.sh status`, `scripts/lightweight_sync_daemon.sh stop`
- 自动同步默认每 120 秒执行一次，可用 `NANOBODY_SYNC_INTERVAL` 调整；日志和状态写入本地 `.omx/`，不上传运行日志。
- 默认单文件阈值：5 MiB，可用 `NANOBODY_SYNC_MAX_BYTES` 覆盖。
- Git 默认忽略新文件；同步脚本只强制加入 manifest 选中的轻量文件。
- 手动和自动同步共用 `.git/lightweight-sync.lock`，避免并发提交/推送冲突。
- 嵌套 Git 工作树会被同步脚本临时绕过 `.git/` 边界以加入轻量源码，但内部 `.git/` 目录不会被提交。

## 明确不在仓库中的内容

- 大型下载语料：如 `data/datasets/`。
- 模型权重、训练数据和输出：如 `data/models/`, `data/model_data/`, `data/experiments/**/checkpoints`, `data/experiments/**/prepared`, `data/experiments/**/runs`, 部分 `code/downloaded_models/**/data` 或权重目录。
- 本地环境和缓存：如 `.conda-envs/`, `.local/`, 任意 `.omx/`, `__pycache__/`, `.pytest_cache/`。
- docking/HADDOCK3 大型运行目录、姿态批量输出、远端日志和中间文件。
- 第三方大规模工具/论文镜像：如 `tools/nanobody_tool_survey/code/`, `tools/nanobody_tool_survey/papers/`。

更多同步清点与排除理由见 `docs/LIGHTWEIGHT_SYNC_INVENTORY.md`。
