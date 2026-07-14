# PVRIG V3-P2 Docking Gold V1.2 Development Protocol

- 文档日期：2026-07-14（Asia/Shanghai）
- 文档状态：`PROTOCOL_DESIGN_READY_IMPLEMENTATION_NOT_STARTED`
- V1.1 状态：`FAIL_DOCKING_GOLD_NOT_VALIDATED`
- P2 状态：`P2_TRAINING_BLOCKED`
- 适用范围：V1.2 development、smoke 与全新 formal holdout 的实现和验证合同

## 1. 决策摘要

V1.2 不是对 V1.1 的原地修补，而是一条新的、完整版本化的计算教师协议。它同时修正两个相互独立的 V1.1 否决原因：

1. `6_seletopclusts` 的 final pose 数不稳定，导致 52/160 run 只有 4-7 个 final pose，无法构建完整的 64/16 重复性账本。
2. PVRL2 参考界面遮挡计分错误纳入 `HETATM`，使当前 V1.1 连续指标和 A/B/C/E 阈值失去可用语义。

V1.2 的唯一推荐 pose 合同是：

> **所有 run 统一从 `4_emref` 按确定性 HADDOCK score 排序取固定 Top-8。不从 emref 条件式回填 final，不使用可变的 8-10 pose 分母。`6_seletopclusts` 仅作多样性诊断，不决定 Gold pose set。**

该选择有直接审计依据：V1.1 的 160/160 run 在 `emref` 都有至少 8 个输出，但 final 只有 108/160 run 达到 8 个输出。

V1.2 只有在以下顺序全部完成后才可放行 P2：

```text
版本边界冻结
→ 固定 emref Top-8 合同
→ ATOM-only PVRL2 scorer
→ 连续指标与阈值重校准
→ rules/toolchain/manifest 冻结
→ 8-run development smoke PASS
→ 52-run V1.1 failure-regression cohort PASS
→ 全新未触碰 64/16 formal holdout 一次性 PASS
→ P2_TRAINING_READY
```

## 2. 本文档不声称什么

本文档是 development protocol，不是实现完成证明。目前不声称：

- V1.2 scorer 已编写；
- V1.2 阈值已校准；
- 8-run smoke 已通过；
- 52 个失败 run 已修复；
- 全新 64/16 formal holdout 已选择或运行；
- P2 已获得训练资格。

后续任何实现都必须生成独立机器审计，而不能只修改本文档中的状态文字。

## 3. V1.1 全量审计基线

### 3.1 候选与运行规模

V1.1 Pilot64 包含：

| 账本 | 数量 | 证据 |
| --- | ---: | --- |
| 候选 | 64 | selection audit |
| unique sequence | 64 | selection audit |
| known positive | 11 | selection audit |
| matched control | 21 | selection audit |
| Teacher500 stratified | 32 | selection audit |
| replicate candidate | 16 | selection audit |
| main receptor run | 128 | 64 x 2 receptors |
| replicate receptor run | 32 | 16 x 2 receptors |
| 总 run | 160 | sync audit |

selection audit：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_dual_docking_pilot_selection_audit.json`

### 3.2 终态、DG-A 和失败分布

| V1.1 证据 | 结果 |
| --- | ---: |
| completion markers / parse errors | 160 / 0 |
| DG-A-complete run | 108/160 |
| incomplete run | 52/160 |
| main run PASS / FAIL | 87 / 41 |
| replicate receptor run PASS / FAIL | 21 / 11 |
| 双 main DG-A-complete candidate | 38/64 |
| 有效 replicate comparison | 8/16 |
| 已接受 V1.1 pose rows | 1,028 |
| contact failures | 0 |

sync audit：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_dual_docking_pilot_v2_sync_audit.json`

Gold audit：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_docking_gold_v2_audit.json`

### 3.3 stage-level 证据

V1.1 sync audit 中 160 个 run 的 stage output 分布为：

| stage | output count distribution |
| --- | --- |
| `seletop` | 160 x 10 |
| `flexref` | 153 x 10, 6 x 9, 1 x 8 |
| `emref` | 153 x 10, 6 x 9, 1 x 8 |
| `final` | 69 x 10, 26 x 9, 13 x 8, 11 x 7, 7 x 6, 9 x 5, 25 x 4 |

52 个 incomplete run 中：

| 字段 | 分布 |
| --- | --- |
| `emref` | 50 x 10, 2 x 9 |
| `final` | 11 x 7, 7 x 6, 9 x 5, 25 x 4 |
| final clusters | 4 x 4, 11 x 3, 12 x 2, 25 x 1 |

因此，52 个失败不是因为 emref 没有生成足够 pose，而是 final cluster selection 把一部分 run 收缩到 4-7 个 pose，其中 25 个 run 只剩 1 个 final cluster。

### 3.4 HETATM 语义缺陷

HETATM 诊断仅覆盖 8 个 revised-smoke run，不是完整 Pilot64 的 corrected Gold；但它已足以证明 V1.1 语义不可接受：

| 证据 | 结果 |
| --- | ---: |
| baseline x model rows | 156 |
| current metric/class reproduction | 156/156 |
| HETATM-affected rows | 156/156 |
| changed classes | 18/156（11.54%） |
| 8X6B PVRL2 HETATM | 58 HOH atoms |
| 9E6Y PVRL2 HETATM | 60 HOH + 24 EDO atoms |

HETATM audit：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_1_hetatm_contamination_audit.json`

## 4. 版本边界和不可洗白原则

### 4.1 永久保留 V1.1 FAIL

V1.1 的以下产物必须保留不变：

- scorer、classifier 和 rules；
- selection/run/content manifests；
- completion markers 和原始 run outputs；
- sync、postprocess、Gold 和 HETATM audits；
- `FAIL_DOCKING_GOLD_NOT_VALIDATED` 最终结论。

不得通过以下操作将 V1.1 “洗白”：

1. 在原 V1.1 CSV/JSON 上覆盖 ATOM-only 结果；
2. 将 108 个已通过 run 的当前 label 重命名为 V1.2 Gold；
3. 用 emref pose 条件式补齐 52 个失败 run，然后回写为 V1.1 PASS；
4. 将旧 Pilot64 重评分后宣称为“全新 formal holdout”；
5. 使用 protein-only sensitivity class 直接训练；
6. 不升级 protocol ID 却修改 pose 来源、scorer 或阈值。

### 4.2 V1.2 必须有独立身份

实现时至少区分两个独立角色：

```text
DG_A_PVRIG_V1_2_DEV       # 旧 Pilot64、校准、smoke 和 failure regression
DG_A_PVRIG_V1_2_FORMAL    # 全新未触碰 64/16 holdout
```

每个行级产物必须带有：

```text
protocol_id
source_protocol_id
candidate_id
sequence_sha256
receptor_id
seed_role
pose_selection_stage
pose_selection_rank
pose_sha256
scorer_sha256
rules_sha256
reuse_role
formal_eligible
```

一个行只有在 `protocol_id=DG_A_PVRIG_V1_2_FORMAL`、所有哈希闭包且 formal audit PASS 时才可进入 V1.2 formal 账本。

## 5. 108 可用 run 与 52 失败 run 的 development 复用

### 5.1 108 个 V1.1 DG-A-complete run

108 个 run 和其 1,028 个已接受 final pose rows 可用于：

- 复现 V1.1 与 ATOM-only 连续指标的差异；
- 开发 record-type inventory、数值闭包和行级 provenance；
- 估计 HETATM 去除对分布、极值和旧分类的影响；
- 比较 final variable-N 与 emref fixed-K 聚合的稳定性；
- 调试 V1.2 builder、audit 和失败报告。

它们不能直接用于：

- V1.2 formal repeatability 评估；
- V1.2 正式测试；
- fixed Top-8 V1.2 训练 label，因为当前 pose set 来自 `6_seletopclusts` 且分母为 8-10。

如需将其中的非 calibration 候选纳入 V1.2 development training，必须重新从哈希闭包的 `4_emref` 输出构建固定 Top-8，并完整重跑 V1.2 scorer、contact、aggregation 和 audit。来自 old Pilot64 的所有这类行仍必须标记 `reuse_role=development_only`、`formal_eligible=false`。

### 5.2 52 个 V1.1 incomplete run

52 个 run 当前的 4-7 个 final pose 只可用于：

- 定位 cluster collapse 与 variable-N 失败模式；
- 审计 receptor/seed-role 失败分布；
- 开发“不许回填”和“少于 K 整个 run 失败”的机器门。

它们不得以 4-7 可变分母进入校准、训练或重复性评估。

V1.2 要求在 scorer 和 pose-selection contract 冻结后，将这 52 个 run 作为一个完整 failure-regression cohort 重跑。这次重跑必须：

1. 使用同一个 V1.2 development package、全局配置、固定 K 和 scorer/rules 哈希；
2. 全部 52/52 run 产生恰好 8 个 canonical emref pose；
3. 不得因 candidate、receptor 或 seed-role 改变容差、K 或排序法；
4. 无 emref/flexref/rigidbody 跨 stage 回填；
5. 生成独立 V1.2 completion/postprocess audit；
6. 仍然标记 `development_only`，不得成为 formal holdout。

重跑前可以读取旧 `4_emref/io.json` 和坐标作实现开发；但不得将这种事后恢复写回 V1.1 Gold。

### 5.3 cohort 级别的训练边界

old Pilot64 中：

- 11 个 known positive 和 21 个 matched control 永久保持 `calibration_only`；
- 32 个 Teacher500 stratified 候选只有在 V1.2 fixed-Top-8 全流程 PASS 后，才可按新的 development split 进入训练/调参；
- old Pilot64 中原有的 `test` 或其他名称不再具有 formal 含义，因为其结果已用于 V1.2 协议修订。

## 6. final-pose 选择策略比较

### 6.1 方案 A：保持 final `>=8`

**优点：**

- 保留 V1.1 `clustfcc -> seletopclusts` 的 cluster-aware 产物；
- 与当前 108 个通过 run 的输出语义最接近。

**不可接受的问题：**

- 已实测失败 52/160 run；
- final 分母在 8-10 之间变动，Top-K fraction 和 median 的采样语义不一致；
- 失败与 cluster collapse 相关，会选择性丢失某些低多样性 pose ensemble；
- 无法保证 64/16 正式账本完整。

**决策：拒绝。**

### 6.2 方案 B：final 不足时从 emref 补到 8

**优点：**

- 表面上可以保留 final cluster representatives，同时补齐 52 个失败 run；
- 可减少全量重跑成本。

**不可接受的问题：**

- 同一列 label 混合两种 pose 选择分布：final cluster rank 和 emref energy rank；
- 只有 final 不足的候选才走 backfill 分支，选择算法与候选本身绑定；
- 回填 pose 没有与 final pose 可比的统一 rank；
- 会使 repeatability 同时测量随机性和“是否触发回填”的离散差异；
- 构成对 V1.1 失败的事后补齐，违反不可洗白原则。

**决策：拒绝。**

### 6.3 方案 C：所有 run 统一 fixed Top-K

**优点：**

- 所有候选、receptor 和 seed-role 共享一个 pose 来源阶段和排序规则；
- 分母固定，Top-K fraction、median、contact frequency 和重复性直接可比；
- V1.1 audit 已证明 160/160 run 的 emref 都有至少 8 个输出；
- cluster collapse 可作为模型不确定性/多样性特征保留，而不是把整个候选变成缺失值。

**代价：**

- 不再由 final clustering 强制 pose diversity；
- 必须重新校准所有 candidate-level aggregation 和 tier 阈值；
- 旧 V1.1 final pose 不能直接成为 V1.2 canonical pose set。

**决策：唯一推荐。**

## 7. V1.2 canonical pose-selection contract

### 7.1 固定来源和 K

```text
source_stage = 4_emref
K = 8
selection = deterministic lowest HADDOCK score
final_cluster_output_role = diagnostic_only
```

每个 run 必须恰好输出 8 个 canonical pose。不得对某些 run 取 9 或 10 个，也不得对少数 run 降低 K。

### 7.2 确定性排序

1. 从 `4_emref/io.json` 读取输出顺序、`file_name`、`score`、`seed` 和上游来源字段。
2. `score` 必须是有限数值；缺失、NaN 或 infinity 使整个 run FAIL。
3. 按 `score` 升序（越低越优）排序。
4. score 相同时，先按原 `io.json` output index，再按 `file_name` 字典序打破平局。
5. 取排序后前 8 个 pose，并记录从 1 开始的 canonical rank。
6. 不得在查看遮挡、hotspot、contact 或 tier 后更改选择顺序。

### 7.3 输出闭包

每个 canonical pose 至少记录：

```text
run_id
candidate_id
receptor_id
seed_role
source_stage
source_output_index
source_file_name
source_score
source_seed
canonical_rank
pose_sha256
pose_coordinate_path
```

必须检查：

- pose 文件存在、非空且 SHA256 闭包；
- PDB 可解析，VHH 和 PVRIG 蛋白链存在；
- 8 个 canonical rank 唯一且严格为 1..8；
- `io.json` model set 与坐标文件一一对应；
- contact/geometry 输出恰好覆盖全部 8 pose x 2 baselines。

任一条失败时，整个 run FAIL。不得从 `flexref`、`rigidbody` 或 `6_seletopclusts` 补 pose。

### 7.4 多样性作为证据，不作为缺失开关

对 fixed Top-8 另行计算：

```text
unique_geometry_count
pose_cluster_count
pose_cluster_entropy
largest_cluster_fraction
top1_vs_median_score_gap
geometry_metric_dispersion
```

不再要求“至少 2 个 final cluster 才有 label”。如果 Top-8 收敛到一个几何盆地，该现象应作为低多样性/高确定性证据进入聚合报告，而不是丢弃整个候选。

## 8. ATOM-only 语义、重校准和规则冻结顺序

顺序不得交换。

### Step 1：冻结 pose-selection schema

先冻结第 7 节的 fixed Top-8 输入合同。否则后续阈值校准会同时混入 pose 选择改动。

### Step 2：实现版本化 ATOM-only scorer

V1.2 PVRL2 遮挡计分必须：

1. 对参考 PVRL2 只解析蛋白 `ATOM` heavy atoms；
2. 排除全部 `HETATM`，包括 HOH、EDO 和其他非蛋白记录；
3. 输出 chain/record/residue/atom inventory；
4. 对 8X6B PVRL2 chain A 记录 963 protein atoms / 126 protein residues，并显式证明 58 HOH atoms 未进入 occlusion；
5. 对 9E6Y PVRL2 chain D 记录 1,002 protein atoms / 130 protein residues，并显式证明 60 HOH + 24 EDO atoms 未进入 occlusion；
6. 对 total、CDR1/2/3、fraction、hotspot 和 residue-pair 输出建立行级数值闭包。

### Step 3：先复现，后重标

1. 在只读 V1.1 输出上复现当前 metrics/classes，证明新 audit 没有其他漂移。
2. 仅切换 PVRL2 的 `ATOM` 语义后重算连续 metrics。
3. 该阶段产出只能命名为 `sensitivity/development`，不得命名为 corrected Gold。

### Step 4：使用 V1.2 canonical pose 重建 calibration table

校准表必须从 fixed Top-8 + ATOM-only 全流程重建，而不能只替换旧表中的几个列。

校准角色为：

- 11 个 known positive：success anchors 和 family-level sensitivity；
- 21 个 matched control：matched decoy/control 分离；
- 32 个 Teacher500 stratified：扩展几何分布，不当作实验阳性。

以上数据均已暴露于协议开发，只能用于 development/calibration。

### Step 5：重新拟合聚合与 tier 规则

必须重新校准：

```text
hotspot overlap
total PVRL2 occlusion
CDR1/2/3 occlusion
CDR3 occlusion fraction
Top-8 A/B-support fraction
dual-baseline agreement/disagreement
pose-level dispersion
cluster/diversity diagnostics
candidate-level R_gold
stable tier G1-G5
```

规则设计必须保留“结合先验”和“阻断几何”的分离，不得将 `A/A=1，其他=0` 作为唯一标签。

数值阈值不在本设计文档中事先伪造。它们必须由 V1.2 calibration audit 给出，并在 smoke 和 formal holdout 前冻结。

### Step 6：冻结 release candidate

冻结项至少包括：

```text
pose-selection schema + implementation SHA256
ATOM-only scorer SHA256
reference PDB SHA256
hotspot/reconciliation SHA256
calibration manifest + sequence hashes
continuous metric definitions
aggregation implementation SHA256
rules JSON SHA256
all thresholds
protocol ID
8-run smoke manifest
formal holdout selection rules
```

一旦 release candidate 进入 8-run smoke，任何修改都必须生成新的 RC 标识和哈希，并从完整 8-run smoke 重新开始。

## 9. 8-run development smoke 通过门

### 9.1 冻结范围

建议继续使用已知、已暴露的 development smoke ID，避免消耗新 holdout：

```text
P2PILOT_001 x {8X6B, 9E6Y} x {main, replicate}
P2PILOT_033 x {8X6B, 9E6Y} x {main, replicate}
= 8 runs
```

它们只检查实现闭包，不检查 formal 泛化。

### 9.2 全部必须 PASS 的门

| smoke gate | 通过条件 |
| --- | --- |
| manifest closure | 8/8 run 的 sequence/config/receptor/restraint/seed/hash 全部匹配 |
| runtime completion | 8/8 run 终态为 PASS，无 parse error |
| canonical pose count | 每个 run 恰好 8 pose，合计 64 canonical poses |
| canonical rank | 每个 run 严格为 1..8，无重复/缺失 |
| selection source | 64/64 pose 均来自 `4_emref` |
| score ordering | 64/64 pose 符合冻结排序与 tie-break |
| no backfill | 0 个 pose 来自其他 stage |
| dual-baseline rows | 64 pose x 2 baselines = 128 行，无缺失/重复 |
| contact/geometry | 0 failures，行级闭包成立 |
| PVRL2 record type | occlusion 中 `HETATM` 计数为 0 |
| 8X6B inventory | 963 protein atoms / 126 residues；58 HOH atoms 显式排除 |
| 9E6Y inventory | 1,002 protein atoms / 130 residues；60 HOH + 24 EDO atoms 显式排除 |
| deterministic rebuild | 在排除时间戳后，两次构建主 CSV/JSON 的 SHA256 一致 |
| override | candidate-specific tolerance/backfill/threshold override 全为 false |
| claim boundary | 每个产物明确为 computational docking geometry，非实验真值 |

smoke 不要求产生特定数量的 G1/G2，也不以“结果看起来合理”代替数值闭包。

### 9.3 失败处置

任一门失败：

1. 当前 V1.2 RC 标记 FAIL；
2. 在 development 分支修改；
3. 升级 RC 哈希/标识；
4. 重跑全部 8-run smoke；
5. 不得只重跑或豁免失败的单个 run。

## 10. 52-run failure-regression 门

8-run smoke PASS 后，使用冻结 RC 对 V1.1 的全部 52 个失败 run 执行 development rerun。

通过条件：

```text
52/52 runtime completion PASS
52/52 exactly 8 canonical emref poses
416/416 canonical poses hash-closed
832/832 pose x baseline geometry rows present
contact/geometry failures = 0
cross-stage backfill = 0
candidate-specific override = 0
protocol/hash mismatch = 0
```

这个 cohort 是 V1.2 对已知最困难运行的 regression test。它的结果可用于 development，但不可成为 formal 重复性评估。

如果其中任一 run 在 emref 少于 8 个合法 pose，必须判定整个 failure-regression gate FAIL；不得从其他 stage 补齐。

## 11. 全新未触碰 64/16 formal holdout

### 11.1 规模和运行合同

V1.2 正式验证保留与 V1.1 可比的规模：

```text
64 new candidates x 2 main receptors = 128 main runs
16 preregistered candidates x 2 replicate receptors = 32 replicate runs
total = 160 runs
```

这 64 个候选必须在 docking 前选定、冻结和哈希化。

### 11.2 与 development 数据的零泄漏要求

新 holdout 必须与以下全部隔离：

- old Pilot64 的 64 个 sequence hashes；
- 11 known positives、21 matched controls 及其校准衍生物；
- V1.2 calibration 和 8-run smoke 的全部 sequence hashes；
- old Pilot64、calibration 和 smoke 的 parent framework cluster；
- 已使用的 source candidate ID、design batch/seed 和 monomer structure hash；
- 任何在 V1.2 阈值、scorer、pose-selection 或 rules 决策中被查看过的 candidate-level docking result。

闭包审计必须对每个重叠类型输出计数和 offending IDs，所有重叠计数必须为 0。

### 11.3 选择不得使用 formal label

在 docking 前可以按以下先验字段分层：

```text
parent framework cluster
design method
target patch
CDR3 length bin
design mode
pre-docking sequence/QC strata
```

不得按 V1.2 docking score、tier 或任何 formal 后处理结果选择 64 个候选或 16 个 replicate candidate。

16 个 replicate candidate 必须在 manifest 冻结时同时冻结，并覆盖尽可能多的先验 strata。不得在看到 main tier 后再挑选 replicate。

### 11.4 职责分离

至少分离：

| 角色 | 可见信息 | 禁止操作 |
| --- | --- | --- |
| protocol developer | development/calibration/smoke 结果 | 在 formal 开始后改 scorer/rules/K |
| holdout selector | pre-docking provenance/QC | 查看 formal docking label 后改 cohort |
| execution operator | 冻结 package 和 runtime status | candidate-specific 更改 seed/tolerance/K |
| independent evaluator | 全部 sealed outputs | 向 trainer 泄漏 candidate-level labels |
| P2 trainer | PASS/FAIL 放行结论 | 在正式评估前读取 holdout labels |

### 11.5 一次性验证原则

1. formal 开始前冻结 selection/run/content manifests、protocol ID、全部代码/规则/参考哈希和随机种子。
2. 允许仅在尚未产生可见聚合结果时，使用原 seed/config 恢复被系统级中断的任务；所有 resume 必须留审计。
3. 一旦任何 candidate-level Gold/tier/repeatability 结果被解密，不得重跑单个候选、改 seed、改 K 或改阈值。
4. 任意 formal gate 失败则整体拒绝。如需改协议，必须升级版本并准备另一个全新未触碰 holdout。
5. 旧 Pilot64 不得在任何情况下变成 V1.2 formal holdout。

## 12. V1.2 formal 验证门

全新 64/16 holdout 必须同时通过：

| formal gate | 通过条件 |
| --- | --- |
| package provenance | selection/run/content manifests 与冻结 SHA256 全部闭包 |
| leakage | sequence/parent/provenance 预注册重叠计数全部为 0 |
| main completeness | 64/64 candidate 的两条 main receptor run 全部 DG-A-complete |
| replicate completeness | 32/32 replicate receptor run 全部 DG-A-complete |
| canonical pose count | 每个 run 恰好 8 个 emref pose，无跨 stage 回填 |
| comparison set | 恰好 16 个 comparison rows，ID 集合与预注册完全一致 |
| comparison validity | 16/16 main/replicate 两侧均 DG-A-complete |
| contact/geometry | failures = 0 |
| override | candidate-specific override = false |
| tolerance | tolerance relaxation = false |
| repeatability | `R_gold` Spearman >= 0.70 |
| tier estimability | expected tier disagreement > 0 |
| tier agreement | quadratic weighted kappa >= 0.60 |
| metric null handling | 任一必需指标为 `null` 则 FAIL，不得替换为 0 或 1 |
| claim boundary | 仅声称 computational docking geometry Gold |

如果 16 个 replicate 的 tier 无变异，kappa 不可估计，必须 FAIL。不得以“全部相同所以完全一致”的口径绕过预注册门。

## 13. P2 训练放行条件

P2 从 `BLOCKED` 切换为 `READY` 必须同时满足：

```text
V1.1 rejection artifacts preserved unchanged
V1.2 fixed-emref-Top-8 contract frozen
V1.2 ATOM-only scorer numeric closure PASS
V1.2 calibration audit PASS
V1.2 rules/thresholds/toolchain hashes frozen
8-run smoke PASS
52-run failure-regression PASS
fresh 64/16 formal holdout audit PASS
formal holdout labels remain sealed from trainer
training manifests contain no V1.1 label rows
calibration-only positives/controls excluded from ordinary training
```

具体数据资格：

| 数据 | P2 训练资格 |
| --- | --- |
| V1.1 1,028 pose rows | 无；只可诊断/开发 |
| V1.1 108 complete run 的 final labels | 无 |
| V1.1 52 incomplete run 的 4-7 pose labels | 无 |
| V1.2 重建后的 non-calibration development rows | 可，前提是 fixed Top-8 全合同 PASS 且不在 formal holdout |
| 11 known positive + 21 matched control | 仅 calibration/anchor，不进入普通训练 |
| 全新 64/16 formal holdout | 不训练、不调参；保持 sealed 用于正式评估 |

只有独立 evaluator 发布一份机器可读且全部门为 PASS 的 V1.2 validation audit 后，才能记录：

```text
P2_TRAINING_BLOCKED -> P2_TRAINING_READY
```

任何“先用 V1.1/protein-only sensitivity 训练一个临时模型，再用模型辅助选 formal holdout”的路径都构成泄漏，必须禁止。

## 14. 实施阶段与停止条件

| 阶段 | 主产物 | 停止/前进条件 |
| --- | --- | --- |
| D0 V1.1 freeze | 否决包与哈希账本 | 任一 V1.1 产物漂移则停止 |
| D1 pose selector | fixed emref Top-8 schema/tests/audit | 稳定排序与 1..8 闭包 PASS |
| D2 scorer | ATOM-only scorer + record inventory | HETATM=0 且数值闭包 PASS |
| D3 calibration | 新连续指标分布和规则审计 | 阈值/rules 冻结 |
| D4 smoke | 8-run audit | 全部 smoke gates PASS |
| D5 regression | 52-run audit | 52/52 PASS，无回填/豁免 |
| F0 holdout freeze | 全新 64/16 manifests | 零泄漏且哈希闭包 |
| F1 formal run | sealed 160-run outputs | 不调参、不改协议 |
| F2 independent audit | formal PASS/FAIL | 全门 PASS 才放行 P2 |

如任一阶段未达到停止条件，不得进入下游阶段。

## 15. 审计证据与哈希

以下路径均相对于仓库根目录 `/mnt/d/work/抗体/data`。

| 证据 | SHA256 | 本文使用的信息 |
| --- | --- | --- |
| `experiments/phase2_5080_v1/audits/phase2_v3_p2_dual_docking_pilot_selection_audit.json` | `44a295f952a1d1a52328dba1bf30801720bf735f14f1e3c944e9dfc434a4d457` | 64 candidates、11 positives、21 controls、32 Teacher500、16 replicates |
| `experiments/phase2_5080_v1/audits/phase2_v3_p2_dual_docking_pilot_v2_sync_audit.json` | `e70297e1373d7a5cde9e9da113ffae338f15c46e119aebd2f8313a0d2f10d566` | 160 runs、108/52、stage output distributions |
| `experiments/phase2_5080_v1/audits/phase2_v3_p2_dual_docking_pilot_v2_postprocess_audit.json` | `d32d4873df425d36f5973fda6cc40daa40d2884e926d27171aa95f1b04e592ab` | 108 PASS / 52 FAIL postprocess |
| `experiments/phase2_5080_v1/audits/phase2_v3_p2_docking_gold_v2_audit.json` | `fc9d0dfb0d4419c08e2a9bad9053a80be539fe12b2b7944da688e5525fb9f4ab` | 38/64 main、21/32 replicate receptors、8/16 comparisons、formal FAIL |
| `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_1_hetatm_contamination_audit.json` | `c53a12545de2ad827e39caaae7767d4ae442d16cd9b09cdc22479b0fd7527f45` | 156/156 affected、18/156 class changes、reference inventory |

## 16. 最终 development 决策记录

```text
V1.1 remains permanently rejected.
Old Pilot64 is development-only and can never become V1.2 formal holdout.
Canonical V1.2 pose source is 4_emref.
Canonical K is exactly 8 for every run.
Conditional backfill is forbidden.
6_seletopclusts is diagnostic-only.
PVRL2 occlusion uses protein ATOM heavy atoms only.
All continuous metrics and tier thresholds must be recalibrated before freeze.
The frozen 8-run smoke must pass in full.
All 52 prior failure runs must pass the development regression gate.
A fresh untouched 64/16 holdout is validated exactly once.
P2 training remains blocked until every V1.2 gate passes.
```
