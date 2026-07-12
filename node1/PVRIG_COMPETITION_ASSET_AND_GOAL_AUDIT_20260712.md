# PVRIG 抗体赛题资产盘点与目标重定义（2026-07-12）

## 0. 审计结论

当前状态应统一表述为：

```text
PIPELINE_READY_CANDIDATE_PORTFOLIO_NOT_READY
流程、工具、校准与批处理能力已具备；可提交的 50 条设计序列和 Top10 尚未形成。
```

| 项目 | 当前结论 |
| --- | --- |
| 当前时间 | 2026-07-12，Asia/Shanghai |
| 报名与第一轮序列截止 | 2026-07-26 18:00:00，审计时约剩 14.2 天 |
| 主路线 | VHH；现有生成、QC、结构、docking 和阳性校准均以 VHH 最成熟 |
| 流程状态 | 可批处理、可断点续跑、核心测试通过 |
| 当前候选状态 | 现有模型 Top50 是公开 ZYMScott 数据集中的原始序列，不是已经完成设计谱系的参赛分子 |
| Top50 实测 | 50 条全部通过阳性 CDR novelty；29 条通过完整序列 hard gate；21 条因奇数 Cys 和/或疏水连续段被拒 |
| 结构/docking 覆盖 | 上述 29 条中只有 4 条已有完整导入证据；2 high、1 single-baseline recheck、1 plausible，另 25 条未 docking |
| 实验真值 | 新候选表达、BLI/SPR、竞争和功能实验均为 0；所有新候选标签仍是计算优先级 |
| 最终判断 | **不能把现有 Top50 直接提交；也不能把当前 4 条计算候选称为已验证阳性** |

这次目标重定义后，项目的关键路径不再是继续扩大文献、继续训练更大的通用模型，或追求单一 docking 分数，而是：

> 在 2026-07-26 18:00 前，使用现有工具生成一批对 PVRIG 界面有明确设计条件、来源和修改谱系可追溯的 VHH；经过泄漏安全的序列门控、结合预筛、单体结构、PVRIG-PVRL2 阻断几何和组合多样性筛选，冻结 50 条有序候选，重点保证前 10 条的成功概率和家族多样性。

## 1. 比赛目标必须如何落地

### 1.1 最终交付目标

第一轮必须形成以下完整交付物：

1. 50 条按预测优先级从高到低排列的 VHH 序列。
2. 每条序列的设计类型：从头设计或优化改造。
3. 优化改造分子的起始分子、变更位点和设计理由；从头设计分子的 scaffold、目标结构、热点和生成参数。
4. 每条序列的 IMGT 编号、CDR1/2/3、官方 validator 结果、阳性 CDR 最大 identity、可开发性摘要和家族/聚类信息。
5. Top10 的单体结构、复合物 pose、8X6B/9E6Y 评分、阻断几何、人工 pose 复核和风险说明。
6. 不超过 1 页的方案摘要。
7. 可复现代码、配置、模型/权重来源、开源归属、输入 SHA256、运行命令和最终排序表。

### 1.2 生物学目标

目标不是“找任意 PVRIG binder”，而是同时提高以下成功概率：

```text
可表达/可纯化
  AND 真实结合 PVRIG
  AND 亲和力足够强
  AND 结合位置与角度能阻断 PVRIG-PVRL2
  AND 不因明显序列/结构风险在实验前被淘汰
```

必须始终分开四个概念：

- `binder`：可能结合 PVRIG。
- `pose quality`：复合物姿态是否结构合理。
- `affinity`：结合强度，最终由 Kd 排名体现。
- `blocker`：是否阻断 PVRIG-PVRL2，最终由 IC50/竞争或功能实验体现。

### 1.3 与比赛评分对齐

比赛初筛评分是：

```text
BLI 单浓度结合 70% + 表达量 20% + 纯度 10%
```

复筛评分是：

```text
Kd 排名 50% + IC50 排名 50%
```

因此计算排序不能只优化 docking，也不能只优化 sequence-only binder score。推荐采用两层决策：

1. **硬门控**：合规、编号、完整性、CDR novelty、明显结构错误先排除。
2. **多目标排序**：分别保留 binding、blocking、expression/purity、structure、developability 和 diversity 轴，不把未校准的代理分数伪装成实验概率。

最终团队成绩取最优代表分子，意味着 Top10 的任务不是做 10 个近重复，而是用多个独立家族提高“至少一个分子成为强 binder + blocker”的概率。

## 2. 当前端到端流程

```text
PVRIG/PVRL2 结构与热点
  -> 多 scaffold / 多角度 target-conditioned VHH 生成
  -> 全库去重、标准 AA、长度和 ANARCI/IMGT 完整性
  -> official/local positive CDR novelty < 80%
  -> 模型/DeepNano 相对优先级预筛
  -> full QC：official validator + AbNatiV + Sapiens + developability
  -> 有界全局 diversity 和 geometry shortlist
  -> NanoBodyBuilder2 单体；IgFold/NanoNet 交叉检查
  -> HADDOCK3 生成 pose
  -> 同一批 pose 对 8X6B 和 9E6Y 两套 PVRIG-PVRL2 界面评分
  -> blocker-like 几何、阈值邻域稳定性、跨 seed/pose cluster 和人工目检
  -> Top50 组合优化；Top10 完整证据包
  -> 官方模板、1 页摘要、代码与复现冻结
```

当前各阶段状态：

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 赛题约束与目标结构 | READY | 8X6B、9E6Y、UniProt、IMGT、CDR identity 规则已固化 |
| 热点与机制标准 | READY WITH LIMITS | 26 个 hotspot rows；36 条机制标准、8 个案例/机制族 |
| 阳性/专利校准 | CALIBRATION ONLY | 30 条专利序列；11 条成功校准；不得提交 |
| mutant/control 校准 | CALIBRATION ONLY | 36 条全部完成结构和 docking；全是 exact/near-positive control |
| scaffold 库 | READY AS STARTING MATERIAL | 1965 raw、1591 clean、Top200 design-ready scaffold；它们不是 PVRIG binder |
| target-conditioned 生成 | TOOL READY, BATCH MISSING | RFantibody 三段 smoke 已通过，但尚无 PVRIG 正式生产设计批次 |
| sequence/QC cascade | READY | `vhh-large-scale-screen` 已生产部署，Top50 本轮实测 310 秒，不含 docking |
| 模型前筛 | LIMITED | 可做相对排序；V2.5 明确为 `DATA_NOT_READY_FOR_TARGET_MODEL` |
| 单体结构 | READY | NanoBodyBuilder2 主线，IgFold/NanoNet 可交叉验证 |
| 复合物与阻断几何 | READY WITH CALIBRATION LIMITS | HADDOCK3 主线；Boltz-2/Chai-1 可做异议检查 |
| 最终 50 条 | MISSING | 当前只有公开数据序列的审计池，不是完成设计的提交池 |
| Top10 | MISSING | 只有 4 条计算几何候选，且没有合规设计谱系 |
| 官方提交包 | MISSING | 本地未发现最终 50 模板、1 页摘要和冻结 release |

## 3. 已有核心资产

### 3.1 靶点和机制

- `data/structures/8X6B.pdb`：PVRIG-PVRL2 复合物结构。
- `data/structures/9E6Y.pdb`：第二套 PVRIG-PVRL2 复合物结构。
- `data/structures/PVRIG_hotspot_set_v1.csv`：26 行，21 core、2 secondary、3 soft hints。
- `data/structures/PVRIG_numbering_reconciliation.csv`：PDB、alignment、UniProt 编号协调。
- `docking/success_case_validation/success_case_mechanism_criteria_matrix.csv`：36 条判断标准，覆盖 8 个案例/机制族。
- `docking/success_case_validation/blocker_judgment_rules_v2.json`：当前几何规则和证据边界。

### 3.2 阳性、专利和泄漏排除

- `positives/known_positive_antibodies.fasta`：Tab5 VH/VL 和 HR-151 VHH，共 3 条官方序列记录。
- `机制/data/sequences/PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta`：30 条专利 VHH/HCVR。
- `机制/data/literature/PVRIG_case02_success_validation_series.csv`：11 条优先校准序列。
- `docking/calibration/patent_success_validation/batch_status.csv`：11/11 已完成单体、HADDOCK 和 consensus。
- `docking/calibration/mutant_validation_panel/mutant_panel_status.csv`：36/36 已完成结构和 docking。
- `docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv`：7 exact positives + 29 near positives。

这些资产只能用于：

- 阳性校准；
- CDR 泄漏排除；
- 参数敏感性分析；
- 成功/失败机制对照；
- 流程回归测试。

它们不能进入参赛新候选序列。

### 3.3 scaffold 和生成

| 资产 | 数量 | 当前用途 |
| --- | ---: | --- |
| `scaffolds/raw_vhh_scaffold_pool.fasta` | 1965 | 受控导入原始池 |
| `scaffolds/clean_vhh_scaffold_library.fasta` | 1591 | 通过基础门控的 starting material |
| `scaffolds/top_200_vhh_scaffolds_for_design.fasta` | 200 | 优先用于多家族 target-conditioned 设计 |
| RFantibody | 3 个 wrapper | RFdiffusion backbone、ProteinMPNN sequence、RF2 filtering |

RFantibody 生产入口：

```text
/data/qlyu/software/RFantibody/bin/rfdiffusion
/data/qlyu/software/RFantibody/bin/proteinmpnn
/data/qlyu/software/RFantibody/bin/rf2
```

当前缺的不是工具，而是一个正式 PVRIG 设计批次及其完整 lineage。

### 3.4 数据和模型

- `data/model_data/index_v0_samples.csv`：37,711 行统一索引。
- `data/experiments/phase2_5080_v1/data_splits/evidence_registry_v2_5.csv`：10,324 行规范证据注册表。
- `data/experiments/phase2_5080_v1/checkpoints/`：Phase2 V1-V2.4 可恢复检查点。
- `data/experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv`：50 条相对排序。

模型必须按以下边界使用：

- V2.5 正式结论是 `DATA_NOT_READY_FOR_TARGET_MODEL`。
- 当前分数是候选集合内相对优先级，不是 binder probability 或 blocker probability。
- ZYMScott VHH affinity-seq 行没有 antigen sequence/context；不能把其原始序列和通用 affinity score解释成 PVRIG 靶向设计。
- 模型适合在大设计库中做廉价前筛，不适合单独产生最终阳性结论。

### 3.5 Node1 生产工具和资源

稳定入口：

```bash
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 '<command>'
```

核心生产入口：

```text
/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc
/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen
/data/qlyu/software/DeepNano/run_deepnano_predict.sh
/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3
/data/qlyu/anaconda3/envs/boltz/bin/boltz
/data/qlyu/software/envs/chai1/bin/chai-lab
```

2026-07-12 13:43 的只读快照：

- 8 张 RTX 4090，每张 24,564 MiB。
- GPU1-5 当时接近空闲；GPU0/6/7 有其他用户任务，运行前必须重新查询。
- 未发现正在运行的本项目 VHH/QC 任务。
- `/data` 可用约 20 TB，已使用 74%。
- `vhh-competition-qc --help` 和 `vhh-large-scale-screen --help` 均正常。
- 两个入口没有独立 `--version`；版本冻结应使用源码 SHA256。

生产源码指纹：

```text
vhh_competition_qc.py
5789246af86bfe4df87b767523e52fcf838988e76477f5b0ef1ca65cfd3db608

vhh_large_scale_screen.py
051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a
```

## 4. 本轮新增：现有模型 Top50 的 production cascade 审计

### 4.1 输入边界

本轮把 V2.4 排名的 50 条序列真实送入 node1 production cascade。输入文件：

- `competition_qc/pvrig_top50_audit_20260712/top50_model_ranked_public_sequences.fasta`
- `competition_qc/pvrig_top50_audit_20260712/top50_model_provenance.csv`
- `competition_qc/pvrig_top50_audit_20260712/top50_model_binder_summary.csv`

远端运行：

```text
/data/qlyu/software/vhh_eval_tools/runs/pvrig_v24_top50_audit_20260712
```

本地结果快照：

```text
competition_qc/pvrig_top50_audit_20260712/cascade/
```

这些输入全部来自公开 `ZYMScott_vhh_affinity-seq/test.csv`，用途是审计已有流程和寻找可能的优化起点；它们不是已经完成从头设计或优化改造的提交分子。

### 4.2 实测漏斗

```text
50 input / 50 unique
  -> 50 CDR novelty PASS
  -> 29 fast hard-pass
  -> 29 official validator PASS + full QC hard-pass
  -> 29 geometry shortlist
  -> 4 existing docking imports
       2 FINAL_POSITIVE_HIGH
       1 FINAL_RECHECK_SINGLE_BASELINE
       1 FINAL_POSITIVE_PLAUSIBLE
  -> 25 FINAL_INCOMPLETE_NEEDS_DOCKING
```

- sequence cascade 墙钟时间：310 秒，不含结构和 docking。
- 21 条 hard reject：11 `odd_cysteine_count`，10 `odd_cysteine_count;hydrophobic_run`。
- 29 条 full pass 中：17 `REVIEW_DEVELOPABILITY`，12 `REVIEW_RISK`；没有一条可绕过人工审查。
- 29 条 AbNatiV VHH score 范围约 0.589-0.714，整体低于 11 条已知阳性校准范围中位数，但不能据此判定不阻断。

### 4.3 已有 4 条 docking 候选

| 排名 | 候选 | 最终计算标签 | AbNatiV | developability | expression/purity proxy | 主要风险 |
| ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | `zym_test_8787` | `FINAL_POSITIVE_HIGH` | 0.631 | 51 | 80 | `REVIEW_RISK` |
| 2 | `zym_test_108006` | `FINAL_POSITIVE_HIGH` | 0.714 | 43 | 65 | hydrophobic run |
| 3 | `zym_test_3633872` | `FINAL_RECHECK_SINGLE_BASELINE` | 0.659 | 53 | 80 | baseline disagreement |
| 4 | `zym_test_359954` | `FINAL_POSITIVE_PLAUSIBLE` | 0.603 | 22 | 30 | hydrophobic run；开发性弱 |

这 4 条证明“序列 -> full QC -> 单体 -> HADDOCK3 -> 双界面评分 -> finalize”可以跑通。它们仍不构成当前提交 Top4，原因是：

1. 序列是公开数据集原始序列，不是已声明的从头设计。
2. 未做优化改造，也没有可提交的 mutation lineage。
3. 没有 PVRIG 实验 binding 或 blocking 真值。
4. 2 条 high 仍有开发性风险。
5. docking 阈值敏感性和 mutant retained-A 说明几何标签不能单独替代人工复核。

## 5. docking 判断标准的真实稳健性

当前 A 类默认阈值：

```text
hotspot overlap >= 14
total PVRL2 occlusion >= 500
CDR3 occlusion >= 100
CDR3 fraction >= 0.15
```

应保留这些阈值作为统一、可复现的计算参照，但不能把它们当实验真值 hard gate：

- 11 条成功校准共 109 个 pose rows，只有 1/11 个 case 在默认设置下出现双 baseline A/A；9/11 主要是 single-baseline recheck。
- 专利成功集 81 个阈值组合中，A/A pose 数范围为 0-17，只有 4/81 保持默认 case-level calls。
- 36 条 mutant/control 共 357 个 pose rows，默认有 8 个 A/A pose；部分 disruptive mutant 仍保留 A 信号。
- mutant 阈值网格中 A/A pose 数范围为 0-70，说明单一截点不稳定。

因此最终结构判断应改成五项证据联合：

1. 双 baseline 类别和连续几何数值。
2. 阈值邻域是否稳定，而不是只看一个 cutoff。
3. 多 seed / 多 pose cluster 是否重复出现相同界面。
4. 与已知阳性、disruptive mutant 和 binder-only 对照的相对排序。
5. 人工检查是否真正遮挡 PVRL2、是否有明显碰撞或错误接触角。

`FINAL_POSITIVE_HIGH` 的准确释义是“当前最高计算优先级”，不是“实验阳性”。

## 6. 24 条 prospective panel 的正确定位

`data/experiments/phase2_5080_v1/data_splits/pvrig_v2_5_prospective_assay_panel.csv` 包含：

| 角色 | 数量 |
| --- | ---: |
| known positive reference | 5 |
| conservative mutant | 5 |
| paratope-disruptive mutant | 5 |
| public candidate screen | 6 |
| proposed negative-control mutant | 3 |

因此：

- 它是未来建立 PVRIG binding/nonblocking/nonbinding 真值的研究校准 panel。
- 它不是 24 条新参赛候选。
- 其中只有 6 条属于非阳性候选，而且仍是公开 ZYM 原始序列。
- 当前 24/24 都是 `PENDING_EXPRESSION_QC`，实验结果为 0。

比赛截止使优先级发生变化：初次提交前，prospective assay 不是生成 50 条的替代品。如果实验已经有明确排期可以并行推进；否则不能让它阻塞参赛设计批次。

## 7. 50 条和 Top10 应如何组成

### 7.1 50 条全体要求

每条必须同时满足：

- 标准 20 AA、单条完整 VHH、IMGT/ANARCI 成功。
- FR1/2/3/4 与 CDR1/2/3 完整。
- 任一 CDR 对官方、公开专利和本地阳参的 identity `<0.80`；`0.75-0.80` 原则上不放入 Top10。
- 有明确 design lineage 和序列 SHA256。
- 通过 official validator 和本地 hard gate。
- 有至少一个 target-conditioned binding 优先级来源。
- 有单体结构和结构 QC。
- 有 PVRIG 界面/阻断几何证据；若尚未完成 full docking，必须明确标为 reserve，不能混入高置信层。
- 不含已知阳性、阳性近邻、mutant calibration 或简单泄漏变体。

### 7.2 Top10 组合约束

建议 Top10 至少满足：

- 至少 5 个 CDR3/全序列聚类，至少 4 个 scaffold/复合物角度家族。
- 同一近邻家族最多 2 条。
- 4 条机制优先：双 baseline 或跨阈值邻域稳定的 blocker-like pose。
- 3 条平衡优先：binding 支持强、表达/纯度代理好、blocking 至少 plausible。
- 2 条替代角度：覆盖不同 PVRIG 接触子区或不同进攻角度。
- 1 条高风险/高回报探索，但不能违反 hard gate。

不要求 Top10 全部必须是当前二元 `FINAL_POSITIVE_HIGH`。已知阳性校准显示该标签敏感性不足；更稳健的做法是保留连续几何、跨基线稳定性、binding 和 developability 的 Pareto 前沿，再做组合优化。

### 7.3 推荐证据层级

| 层级 | 定义 | 是否可进 Top10 |
| --- | --- | --- |
| A | hard gate 全过；binding 多源一致；双 baseline/多 seed 阻断几何稳定；开发性可接受；人工 pose 通过 | 优先 |
| B | hard gate 全过；binding 强；单 baseline 或 B 类 blocking，但解释合理且结构风险低 | 可作为组合对冲 |
| C | hard gate 全过；结构/开发性好，但 blocking 证据不完整 | 仅 reserve |
| D | hard fail、阳性泄漏、设计谱系缺失或明显结构错误 | 排除 |

## 8. 剩余 14 天的执行优先级

### 7.1 关键路径

| 日期 | 必须完成 | 退出条件 |
| --- | --- | --- |
| 7/12-7/13 | 冻结赛题规则、官方模板、设计 lineage schema、目标结构和多角度配置 | 生成输入和最终字段不再变动 |
| 7/12-7/16 | 用 RFantibody + Top200 scaffold 生成多家族 PVRIG target-conditioned 设计；建议形成 1,000-5,000 条序列池 | 至少数百条 unique、可追溯的新设计通过基础 FASTA 检查 |
| 7/14-7/18 | `vhh-large-scale-screen` 全库 fast/full；模型/DeepNano 只做相对前筛 | 至少 100-300 条 designed hard-pass 候选 |
| 7/16-7/21 | 单体结构、交叉稳定性和 bounded complex shortlist | 至少 50-100 条单体通过；30-50 条进入复合物阶段 |
| 7/18-7/23 | HADDOCK3、多基线评分、阈值邻域、pose cluster 和人工复核 | Top20 有结构竞争证据；Top10 有完整复核 |
| 7/22-7/24 | 组合优化并冻结 Top50/Top10；补齐 lineage、风险和排序理由 | 50 条全部通过提交 hard gate；Top10 多家族 |
| 7/24-7/25 | 生成官方模板、1 页摘要、代码/配置/权重归属、复现 release | 全新目录一键重放得到相同排序和 SHA |
| 7/26 | 只做上传、格式检查和缓冲；内部截止建议 16:00 | 平台提交成功并保存回执 |

### 7.2 截止前明确不做

- 不再扩大与最终 50 条无关的文献或工具清单。
- 不等待仍在安装的新工具。
- 没有新实验标签时，不把 V2.6/更大模型训练放在关键路径上。
- 不对 500 条公开原始序列全部做昂贵 docking。
- 不为了得到更多 `FINAL_POSITIVE_HIGH` 而事后调阈值。
- 不把阳性或其近邻放进提交候选。

## 9. 最终验收标准

只有全部满足时，才能把状态改成 `SUBMISSION_READY`：

1. 最终候选正好 50 条，ID、序列、排序和 SHA256 唯一。
2. 50/50 official validator、ANARCI/IMGT 和 CDR novelty hard gate 通过。
3. 50/50 有设计类型和 lineage；没有一条只是未修改的公开数据序列。
4. 已知阳性、专利序列和 36 条 mutant/control 与提交集严格隔离。
5. 50 条均有 developability 和表达/纯度风险摘要。
6. Top10 全部有单体结构、candidate-specific pose、8X6B/9E6Y 结果和人工复核。
7. Top10 至少 5 个聚类、至少 4 个 scaffold/角度家族、同家族不超过 2 条。
8. 排序表分别保留 binding、blocking、structure、developability、expression/purity 和 diversity，不伪造实验概率。
9. 官方作品模板和 1 页摘要完成，开源来源和创新点明确。
10. 在干净输出目录重放一次，结果数量、顺序和 SHA256 一致。

## 10. 本轮持久化证据

- 总审计：`node1/PVRIG_COMPETITION_ASSET_AND_GOAL_AUDIT_20260712.md`
- 机器可读资产：`node1/competition_qc/pvrig_competition_asset_inventory_20260712.csv`
- 机器可读 readiness：`node1/competition_qc/pvrig_competition_readiness_20260712.json`
- Top50 输入和 provenance：`node1/competition_qc/pvrig_top50_audit_20260712/`
- Top50 cascade 快照：`node1/competition_qc/pvrig_top50_audit_20260712/cascade/`

## 11. 新的项目优先级排序

1. **生成可申报的新设计序列**：当前最大缺口。
2. **把 designed hard-pass 数量提高到至少 100-300**：确保最终能选出 50 条。
3. **集中结构和 docking 预算到 Top30-50**：优先保证 Top10。
4. **完成提交模板和复现 release**：不能留到截止当天。
5. **prospective wet panel 并行但不阻塞第一轮提交**。
6. **有真实实验反馈后再进入 V2.6**。

最终应以比赛结果为导向：最重要的不是“我们跑过多少工具”，而是能否交付一组来源合法、设计可解释、序列合规、具有真实结合和阻断成功概率、且可由代码重现排序的 50 条 VHH。
