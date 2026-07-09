# PVRIG 比赛 VHH 提交前 QC / 筛选体系升级方案

更新时间：2026-07-08  
本地目录：`/mnt/d/work/抗体/node1`  
远端：`node1`，用户：`qlyu`  
目标：把现有“PVRIG-PVRL2 阻断 docking”后置到完整 VHH 赛前 QC 体系中，先保证可提交、不过阳性 CDR 查重、像真实 VHH、可表达/可纯化、可开发性和结构合理，再进入 binding/blocking 排序。

实施状态：2026-07-08 已部署 `vhh-competition-qc` 上层入口并跑通小规模 smoke；具体入口、命令、速度和验证证据见 `VHH_COMPETITION_QC_PIPELINE_RUNBOOK.md`。

复查修正：当前可确认的是“官方合规、CDR novelty、队内 diversity、VHH-screen、NanoBodyBuilder2 结构 smoke、docking summary import、portfolio 输出”已连通；不能表述为“新候选 HADDOCK3 docking 已被 `vhh-competition-qc` 自动端到端跑通”。新候选 docking/occlusion 仍是单独重计算流程，`vhh-competition-qc` 负责导入 summary 并统一排名。

## 0. 一句话结论

当前已经有一条可运行的 **VHH 四层筛选线**、一条 **PVRIG blocker docking/occlusion 校准线**，并已新增比赛级 `vhh-competition-qc` 上层入口。该入口补齐了官方提交校验、CDR 新颖性、队内多样性、表达/纯度代理分、统一 final score 和 Top N portfolio 输出。

建议下一步新增一个上层入口：

```text
vhh-competition-qc
  = 官方 hard gates
  + 现有 vhh-screen 四层 QC
  + CDR 阳参/队内新颖性
  + developability / expression / purity proxy
  + optional structure + docking/blocking
  + final_score + Top 50 portfolio
```

## 1. 已核对的比赛硬依据

来源：2026 上海国际计算生物学创新大赛官方页和官方链接的 `ab-data-validator`。

| 规则点 | 可执行解释 | 本地处理建议 |
| --- | --- | --- |
| 接受 IgG 或 VHH | VHH 只需提交 1 条 VHH 氨基酸序列；IgG 才需要 VH+VL | 当前目标按 VHH-only 实施；后续 IgG 另开格式 |
| 目标机制 | 候选抗体应结合 PVRIG 胞外区，优先靶向 PVRIG-PVRL2 界面并阻断 | binding 和 blocking 分开打分，不能只看 docking 总分 |
| CDR 相似性 | VHH 的 3 个 CDR 与任一阳性参照对应 CDR 原则上均应低于 80% | 作为 hard gate；内部推荐用 `<75%` 作为更安全优先线 |
| CDR 计算方法 | ANARCI 按 IMGT 确定 CDR；MUSCLE 比对；Hamming / Identity | 优先直接复刻官方 `ab-data-validator`，再输出自己的可读 CDR 表 |
| 阳性参照范围 | 不只官网示例；还包括主办方掌握和公开可检索相关抗体 | 使用官方 validator 内置阳参 + 本项目成功案例/专利阳参库 |
| 报名阶段评估 | 序列合理性、表达/纯化/稳定性基础、CDR 相似性、创新性、可开发性、PTM 风险 | 把这些拆成 hard gates + ranking scores，不让 docking 一票决定 |
| 初筛评分 | BLI 0.7 + 表达量 0.2 + 纯度 0.1 | 本地构造 `initial_screen_proxy_score` |
| 复筛评分 | Kd 排序 0.5 + IC50 排序 0.5 | 本地构造 `rescreen_proxy_score`，Kd 类似 binding，IC50 类似 blocking |

官方 validator 关键实现锚点：

- 输入 Excel 中 `VL` 为空时视为 nanobody，仅检查和比较重链 CDR。
- IMGT CDR 区间：`CDR1 27-38`，`CDR2 56-65`，`CDR3 105-117`。
- 任一可比较 CDR 的 `identity >= 0.8` 判失败。
- identity 计算为 MUSCLE 对齐后的 `匹配列数 / 总对齐列数`，gap 列计入总数。

## 2. 当前本地已经覆盖的能力

### 2.1 node1 工具入口

已经复查可用：

```text
/data/qlyu/software/vhh_eval_tools/bin/vhh-screen
/data/qlyu/software/vhh_eval_tools/bin/vhh-eval
/data/qlyu/software/vhh_eval_tools/bin/TNP
/data/qlyu/software/vhh_eval_tools/bin/Paragraph
/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3
```

本地还存在官方 validator 源码与环境：

```text
/mnt/d/work/抗体/tools/ab-data-validator
/mnt/d/work/抗体/.conda-envs/ab-data-validator/bin/ANARCI
/mnt/d/work/抗体/.conda-envs/ab-data-validator/bin/muscle
```

注意：当前本地 `ab-data-validator` 尚未安装成直接 CLI；可临时用：

```bash
cd /mnt/d/work/抗体/tools/ab-data-validator
PYTHONPATH=src /mnt/d/work/抗体/.conda-envs/ab-data-validator/bin/python \
  -m ab_data_validator.cli --help
```

### 2.2 已有 `vhh-screen` 四层体系

文档：`VHH_SCREENING_SYSTEM_NODE1.md`  
入口：`/data/qlyu/software/vhh_eval_tools/bin/vhh-screen`

| 层级 | 已覆盖内容 | 状态 |
| --- | --- | --- |
| L1 编号和结构完整性 | ANARCI/AbNumber IMGT+Kabat、heavy chain、FR/CDR 完整、长度、保守 Cys、FR4 motif、CDR 长度 | 已跑通 |
| L2 VHH 特征 | FR2 hallmark、H44/H45 hydrophilic substitutions、VH-VL 接触面疏水性、AbNatiV VHH score | 已跑通 |
| L3 可开发性 | TNP flags、ProtParam、pI/charge、N-glyc、Cys、deamidation/isomerization/clipping、hydrophobic run、多反应性 proxy | 已跑通 |
| L4 结构稳定性 | IgFold/NanoNet/NanoBodyBuilder2 结构生成、覆盖率、FR RMSD、CDR3 anchor 几何记录 | 已跑通，默认按需启用 |

已有 smoke 证据：

```text
/data/qlyu/software/vhh_eval_tools/tests/vhh_screen_smoke_20260707_180843
/data/qlyu/software/vhh_eval_tools/tests/vhh_screen_bad_gate_20260707_181148
```

### 2.3 已有 PVRIG blocker 结构校准线

文档：`/mnt/d/work/抗体/docking/success_case_validation/POSITIVE_MECHANISM_STRUCTURAL_VALIDATION_AUDIT.md`

已经真正跑过完整结构链的是：

```text
11 条 WO2021180205A1 VHH 阳性校准序列
NanoBodyBuilder2 monomer -> HADDOCK3 -> 8X6B/9E6Y PVRL2 occlusion -> consensus
```

A 类 blocker-like 阈值：

```text
hotspot_overlap_count >= 14
total_vhh_pvrl2_residue_pair_occlusion >= 500
cdr3_pvrl2_residue_pair_occlusion >= 100
cdr3_occlusion_fraction >= 0.15
```

该 docking/occlusion 线应该作为后段 `Gate 8`，不能替代前面的合规、相似性、VHH framework 和 developability。

## 3. 实施后剩余缺口矩阵

| 剩余缺口 | 为什么重要 | 建议动作 | 优先级 |
| --- | --- | --- | --- |
| 新候选 HADDOCK3 端到端未并入 `vhh-competition-qc` | HADDOCK 是重计算长任务，默认 QC 只导入 summary | 保持单独 docking workflow；为 Top hits 增加批量调度脚本和状态检查，再导入 `--docking-summary` | P0 |
| 大批量 Top 50/Reserve 20 尚未压力测试 | 当前 smoke 只有 1-4 条；不能证明比赛规模吞吐 | 用 50-100 条候选做一次非结构批量 benchmark，再对 Top 10 做结构 benchmark | P0 |
| 阶段级速度/稳定性证据仍需积累 | 小样本可连通，但不足以证明长任务稳定 | 已新增 `stage_timings.tsv`；后续每批保留 timing 和失败恢复记录 | P0 |
| PTM surface exposure 未接结构 | 当前有 motif，但不知道是否暴露 | 结构后用 DSSP/freesasa/简单邻域 SASA，把 N-glyc、Met/Trp、NG/DG 风险映射到 surface | P1 |
| MolProbity/clash 没自动化 | 结构合理性不只看跨工具 RMSD | 可先加 `phenix.molprobity`/MolProbity 或轻量 clash detector；没有软件时用 CA/CB 几何 sanity fallback | P1 |
| CamSol/Aggrescan3D 未部署 | 溶解性/聚集风险更直接 | 继续尝试独立 env；失败时保留 TNP + ProtParam + hydrophobic patch proxy 作为 fallback | P1 |
| specificity/off-target 只有 proxy | 官网提到特异性，计算上难证明 | 先做负向 flags：极端正电、疏水 CDR3、polybasic、polyreactivity proxy；后续加家族负靶点 docking | P2 |
| Chai/Boltz/Paragraph 与 QC 表仍是轻量导入 | 当前只稳定支持 summary 回填，不自动调度所有复合物预测 | 为各复合物工具统一 summary schema，避免把未跑结果当成证据 | P2 |

## 4. 推荐的比赛版 Gate 顺序

### Gate 0：输入标准化

输入：`candidates.fasta` 或候选表。输出标准化 FASTA、官方 Excel、候选 ID 映射。

硬规则：

```text
standard_aa_only = true
no_X_B_Z_U_stop = true
length 110-140 preferred, 95-160 hard envelope
sequence_id unique
sequence normalized uppercase
```

### Gate 1：官方合规 / 编号

执行：

```text
ab-data-validator official hard gate
vhh-screen L1 numbering_integrity
```

失败即淘汰：

```text
ANARCI/IMGT 编号失败
CDRH1/2/3 缺失
FR/CDR 边界不稳定
保守 Cys 缺失
FR4 明显不完整
```

### Gate 2：CDR 新颖性

输出：

```text
candidate_id
IMGT_CDR1/2/3
max_identity_to_official_positive_CDR1/2/3
max_identity_to_local_PVRIG_positive_CDR1/2/3
max_identity_to_team_CDR1/2/3
pass_similarity_filter
nearest_positive_name
nearest_team_neighbor
```

硬规则：任一阳参对应 CDR `identity >= 0.80` 淘汰。内部推荐排序时将 `0.75-0.80` 标成 `REVIEW_NOVELTY_MARGIN`。

### Gate 3：VHH framework health

执行：`vhh-screen L2`。

重点：

```text
FR2 hallmark residues
H44/H45 hydrophilic substitutions
VH-VL interface hydrophobic count
AbNatiV VHH score
single_domain_suitability
```

建议：这一层不要太宽松。若不像 VHH，即使 docking 好也降级或淘汰。

### Gate 4：PTM / liability

执行：`vhh-screen L3` 中的 motif scanner，后续接 structure exposure。

硬/软规则：

```text
unpaired / odd Cys: hard fail or severe review
N[^P][ST]: warn; CDR 内或暴露时 severe
NG/NS/NT/NN, DG/DS/DD/DT, DP: warn
Met/Trp in CDR: warn; 暴露时 severe
5+ hydrophobic run: hard fail or severe review
low complexity repeat: severe review
```

### Gate 5：developability / expression-purity proxy

执行：TNP + ProtParam + 自定义 risk combiner。

建议拆分两个字段：

```text
developability_score
expression_purity_risk_score
```

表达/纯度代理分不等同实验表达量，但要尽量对应官方初筛：

```text
expression_proxy: pI/charge/GRAVY/hydrophobic run/Cys/TNP flags/low complexity
purity_proxy: aggregation risk, hydrophobic patch, Cys, predicted monomer sanity, TNP PSH/PPC/PNC
```

### Gate 6：结构合理性

执行：NanoBodyBuilder2 主模型；IgFold/NanoNet 交叉验证。

输出：

```text
nanobodybuilder2_pdb
igfold_pdb
nanonet_pdb
coverage
FR_RMSD_cross_tool
CDR3_anchor_distance
structure_quality_flag
```

后续增强：MolProbity/clash、SASA、PTM exposure、Paragraph paratope。

### Gate 7：binding proxy

第一层可用 DeepNano / Chai / Boltz / docking interface contact 的组合；不要把任一工具单独当 Kd。

输出：

```text
binding_score
interface_contact_score
PVRIG_hotspot_overlap
pose_confidence
```

### Gate 8：blocking / PVRL2 competition proxy

执行已有成功案例校准线：

```text
NanoBodyBuilder2 monomer
HADDOCK3 with hotspot/CDR restraints
8X6B PVRL2 overlay occlusion
9E6Y PVRL2 overlay occlusion
consensus blocker class
```

输出：

```text
PVRL2_competition_score
blocker_class
hotspot_overlap_count
total_vhh_pvrl2_residue_pair_occlusion
cdr3_pvrl2_residue_pair_occlusion
cdr3_occlusion_fraction
```

### Gate 9：Top 50 portfolio

不是只取 final_score 前 50，要加入多样性约束：

```text
1. 先排除 hard fail
2. 每个 CDR3/全序列/embedding cluster 限额
3. 优先保留不同 CDR3 长度和不同 epitope/pose family
4. 同 cluster 内取 developability 更好、风险更低者
5. 输出 Top 50 + 备用 20 条 reserve
```

## 5. 建议最终输出字段

统一主表：`portfolio_ranked.tsv`

```text
candidate_id
sequence
length
submission_type
source_type
parent_name_if_optimized
standard_aa_only
official_validator_pass
official_validator_failed_reason
ANARCI_status
imgt_chain_type
IMGT_CDR1
IMGT_CDR2
IMGT_CDR3
CDR1_length
CDR2_length
CDR3_length
max_CDR_identity_to_official_positive
max_CDR_identity_to_local_positive
max_CDR_identity_to_team
nearest_positive_name
nearest_team_neighbor
pass_similarity_filter
intra_team_cluster_id
fr2_hallmark_score
single_domain_suitability
AbNatiV_VHH_score
has_unusual_cysteine
has_N_glycosylation_motif
deamidation_risk_count
oxidation_risk_count
isomerization_risk_count
clipping_risk_count
pI
net_charge_pH7
MW
GRAVY
instability_index
TNP_flags
CamSol_score_optional
Aggrescan3D_score_optional
structure_quality_flag
NanoBodyBuilder2_confidence_or_coverage
FR_RMSD_cross_tool
PTM_surface_exposure_flag
Paragraph_paratope_summary
binding_score
PVRIG_interface_contact_score
PVRL2_competition_score
blocker_class
developability_score
expression_purity_risk_score
structure_score
novelty_score
diversity_score
initial_screen_proxy_score
rescreen_proxy_score
final_score
rank
recommendation
reason_summary
```

## 6. 建议评分逻辑

### 6.1 Hard gate 优先

以下任一项失败，不进入 final_score 排名：

```text
非法氨基酸 / 异常字符
ANARCI/IMGT 无法编号
CDRH1/2/3 缺失
FR/CDR 明显不完整
阳参 CDR identity >= 0.80
明显非 VHH / single_domain_suitability = poor
奇数 Cys 或严重异常 Cys
严重 hydrophobic run / 结构崩坏
```

### 6.2 分数建议

用于通过 hard gate 后排序：

```text
final_score =
  0.20 * binding_score
+ 0.20 * blocking_score
+ 0.20 * developability_score
+ 0.15 * expression_purity_risk_score
+ 0.10 * structure_quality_score
+ 0.10 * novelty_score
+ 0.05 * diversity_score
```

比赛湿实验代理分另算：

```text
initial_screen_proxy_score =
  0.70 * predicted_BLI_binding_score
+ 0.20 * expression_proxy_score
+ 0.10 * purity_proxy_score

rescreen_proxy_score =
  0.50 * affinity_proxy_Kd_score
+ 0.50 * blocking_proxy_IC50_score
```

排序策略：

- `final_score` 用于综合提交排序。
- `initial_screen_proxy_score` 用于避免“docking 好但表达/纯度风险高”。
- `rescreen_proxy_score` 用于优先挑真正可能有 Kd/IC50 表现的候选。
- Top 50 最终选择要受 `diversity_score` 和 cluster 限额约束。

## 7. 分阶段实施计划

### Phase 0：标准与 reference 固化（半天）

目标：把官方和本地阳参作为可复查输入。

产物：

```text
competition_qc/references/official_positive_library.csv
competition_qc/references/local_pvrig_positive_vhh_cdrs.csv
competition_qc/references/rule_config.yaml
competition_qc/README.md
```

内容：

- 从 `ab-data-validator` 内置 `positive.csv` 生成官方阳参 CDR 表。
- 合并本项目 WO2021180205A1 / HR-151 / PVRIG-20/30/38/39/151 等本地阳性校准 CDR。
- 记录 CDR identity 阈值、推荐安全阈值和 hard/warn 规则。

### Phase 1：官方 hard gate + novelty 模块（1 天）

目标：让每个候选先过主办方风格查验。

新增入口：

```text
/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc
```

核心步骤：

```text
FASTA -> official Excel
run ab-data-validator
run vhh-screen L1-L3
extract CDR novelty table
merge official_failed_reasons + screen_summary.tsv
```

验收：

- HR-151/WO 阳性作为候选时应触发 high CDR identity 或 leakage/review。
- 非抗体序列应在 L1/official gate 失败。
- 好的 smoke VHH 能输出完整 CDR/new novelty 表。

### Phase 2：developability / expression-purity 分数（1 天）

目标：把 TNP/ProtParam/liability 变成可排序字段。

产物：

```text
developability_scores.tsv
expression_purity_proxy.tsv
risk_reason_summary.md
```

内容：

- TNP flags -> 0-100 developability score。
- pI、charge、GRAVY、instability、Cys、hydrophobic run、low complexity -> expression/purity risk。
- PTM motif 按 FR/CDR 位置加权；CDR 内风险更重。

### Phase 3：结构后处理增强（1-2 天）

目标：补上结构合理性、PTM 暴露和 paratope 约束。

内容：

- 对 Top N 跑 NanoBodyBuilder2 + IgFold/NanoNet。
- 计算 coverage、FR RMSD、CDR anchor、简单 clash。
- 尝试 freesasa/DSSP，映射 N-glyc/Met/Trp/NG/DG 是否表面暴露。
- Paragraph 输出 paratope probability，用于 HADDOCK restraints。

### Phase 4：binding/blocking 统一回填（1-3 天，按候选数）

目标：把已有 PVRIG docking 校准线纳入主表。

内容：

- 对 Top hits 生成候选工作目录。
- 跑 NanoBodyBuilder2 -> HADDOCK3 -> 8X6B/9E6Y overlay -> consensus。
- 回填 `binding_score`、`blocking_score`、`blocker_class`。
- 对 `BINDER_LIKE_C` 降权；对 `BLOCKER_LIKE_A` 加分；`BLOCKER_PLAUSIBLE_B` 保留复核。

### Phase 5：Top 50 portfolio selector（半天）

目标：输出可提交组合，而不是单条排序。

产物：

```text
portfolio_ranked.tsv
submission_top50.xlsx
submission_top50.fasta
reserve_20.tsv
portfolio_report.md
```

规则：

- hard fail 全部排除。
- 每个近重复 cluster 限额。
- 每类 CDR3 length / pose family 保留多样性。
- 同 cluster 内优先低 PTM、低聚集、结构稳定者。

## 8. 推荐最小可执行版本

如果要先快跑，不等 CamSol/Aggrescan3D/MolProbity：

```text
1. 官方 ab-data-validator hard gate
2. vhh-screen L1-L3
3. CDR novelty + team diversity
4. TNP/ProtParam/liability -> developability + expression/purity proxy
5. Top 100 再跑结构 L4
6. Top 30-80 再跑 PVRIG docking/blocking
7. portfolio selector 选 Top 50 + reserve 20
```

这版已经能覆盖比赛报名阶段最核心风险：可提交、CDR 不撞阳性、像 VHH、不过度聚集/疏水/电荷异常、PTM 风险可解释、结构合理、且不是只看 docking。

## 9. 关键边界和注意事项

- AbNatiV、TNP、CamSol、Aggrescan3D、NanoBodyBuilder2 等是内部辅助证据，不是主办方明文 hard threshold；最终文档中要写成“内部风险分”。
- `CDR identity <80%` 是最接近硬门槛的规则；不要卡边，推荐 Top 50 尽量低于 75%。
- binding 和 blocking 必须分开。PVRIG binder 不等于 PVRIG-PVRL2 blocker。
- docking/overlay 是机制假设，不是实验 IC50；`BLOCKER_LIKE_A` 也只能写成结构上 blocker-like。
- 优化改造序列需要保留 parent/start molecule 信息；从头设计也要明确标注。
- Top 50 要像 portfolio，不要像 50 条同源近重复序列。

## 10. 参考来源

- 2026 上海国际计算生物学创新大赛官方页：`https://www.bioshanghaiweek.com/2026/SICBC?lan=cn&section=5`
- 官方链接校验器：`https://github.com/clickmab-bio/ab-data-validator`
- ANARCI：`https://opig.stats.ox.ac.uk/webapps/sabdab-sabpred/sabpred/anarci/`
- IMGT numbering：`https://www.imgt.org/IMGTScientificChart/Numbering/IMGTIGVLsuperfamily.html`
- MUSCLE v5：`https://drive5.com/muscle5/`
- TNP：`https://opig.stats.ox.ac.uk/webapps/tnp`
- TAP：`https://opig.stats.ox.ac.uk/webapps/sabdab-sabpred/sabpred/tap`
- ImmuneBuilder / NanoBodyBuilder2：`https://github.com/oxpig/ImmuneBuilder`
- CamSol：`https://www-vendruscolo.ch.cam.ac.uk/camsolmethod.html`
- Aggrescan3D：`https://biocomp.chem.uw.edu.pl/A3D2/`
