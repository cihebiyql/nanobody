# PVRIG V3-P2 Docking Gold V1.1 最终验证与否决报告

- 验证日期：2026-07-14（Asia/Shanghai）
- 协议 ID：`DG_A_PILOT64_V1_1`
- 最终状态：`FAIL_DOCKING_GOLD_NOT_VALIDATED`
- 训练决策：`P2_TRAINING_BLOCKED`

## 1. 最终结论

V1.1 **不能被验证为 Docking Gold，不得用于 P2 正式训练、验证或测试**。

本次否决由两个相互独立的 veto 构成：

1. **完整性与重复性失败**：160 个请求 run 虽然全部进入控制器终态，但仅 108 个满足 DG-A 运行/输出合同；64 个候选中仅 38 个具有两条完整的 main receptor run，16 个预注册重复比较中仅 8 个有效。
2. **PVRL2 遮挡语义受 HETATM 污染**：当前后处理把参考 PVRL2 链中的水和配体 `HETATM` 计入 PVRL2 residue-pair occlusion；在只改为蛋白 `ATOM` 的诊断性重算中，156/156 行均受影响，18/156 行的分类发生变化。

任意一个 veto 都足以否决 V1.1；完成其中一条的修复不会自动解除另一条。只有新的 V1.2 协议通过全部预注册门槛后，才能开始 P2 训练。

## 2. 本次验证的对象和边界

本次验证的是冻结的 Pilot64 独立双受体 docking 协议：

```text
64 candidates x 2 main receptors                  = 128 main runs
16 preregistered replicate candidates x 2 receptors = 32 replicate runs
total                                               = 160 runs
```

它的声明边界为：

> computational docking gold from frozen independent 8X6B/9E6Y HADDOCK pipelines; not experimental binding, affinity, or blocking truth

因此，即使后续 V1.2 通过，所得 Gold 也只能被解释为“冻结计算协议下的 docking/几何教师信号”，不是 BLI、Kd、实验结合或功能阻断真值。

## 3. 冻结包与 provenance 闭包

选择、运行和内容 manifest 均与冻结哈希一致；这证明“验证的确是预注册包”，但不代表运行质量或标签语义已通过。

| 冻结锚点 | SHA256 |
| --- | --- |
| selection manifest | `e67fcab05d93cd3f274c76cc435e9f4b649ace255e230129865d913fa8be3755` |
| run manifest | `e8a420471f68f646c82063ea3254347859f155409cad413a971f37d30b3278a9` |
| package audit | `9a347b8200b5bb1d06c76e52cf34aa0393facc04e24314d45f333725e3f28280` |
| content manifest | `efa89e6b05406128b046b0189f236a2273ab3670fd783224d9b1bab786eba624` |

## 4. 实际运行账本

### 4.1 “160/160 完成”的正确含义

160/160 个 run 都有 completion marker，且 160/160 marker 均能成功解析。这只证明调度器/控制器对所有任务都形成了终态记录，**不等于 160/160 DG-A 完成**。

| 运行层证据 | 结果 |
| --- | ---: |
| 请求 run | 160 |
| completion marker | 160/160 |
| completion parse error | 0/160 |
| DG-A 运行/输出合同 PASS | 108/160 |
| 不完整 run | 52/160 |
| main run PASS / FAIL | 87 / 41 |
| replicate receptor run PASS / FAIL | 21 / 11 |
| 后处理 PASS / FAIL | 108 / 52 |
| 后处理状态 | `FAIL_POSTPROCESS_INCOMPLETE` |

52 个失败 run 均因 final selected-model 数低于预注册下限 8：

| final selected models | 失败 run 数 |
| ---: | ---: |
| 4 | 25 |
| 5 | 9 |
| 6 | 7 |
| 7 | 11 |
| **合计** | **52** |

这些 run 没有使用候选特定容差、降低最小 pose 数或从上游阶段回填模型。保持了协议完整性，但也意味着这 52 个 run 仍是 DG-C，必须重跑，不能补齐成 Gold。

### 4.2 候选层与重复性结果

| Gold builder 证据 | 结果 |
| --- | ---: |
| selection candidates | 64 |
| run manifest rows | 160 |
| receptor rows | 160 |
| 接受的 pose rows | 1,028 |
| contact failures | 0 |
| 两条 main receptor run 均 DG-A 完整的候选 | 38/64 |
| replicate receptor run DG-A 完整 | 21/32 |
| 可建立 replicate candidate aggregate | 9 |
| 有效 replicate comparison | 8/16 |
| `R_gold` Spearman | `null`（未估计） |
| quadratic weighted kappa | `null`（未估计） |
| linear weighted kappa | `null`（未估计） |

只有以下 8 个预注册候选形成有效的 main-versus-replicate 比较：

```text
P2PILOT_001
P2PILOT_006
P2PILOT_008
P2PILOT_012
P2PILOT_033
P2PILOT_037
P2PILOT_057
P2PILOT_060
```

这 8 对比较的 main 和 replicate stable tier 全部为 G1。因此：

- 预注册要求的 16 对比较只存在 8 对，comparison ID 集合不闭包；
- stable-tier expected disagreement 为 0，没有可用于估计 kappa 的类别变异；
- 审计因而没有估计 Spearman 和 weighted kappa。

`null` 表示“未估计/不可估计”，**不是数值 0，也不能解释为通过或接近门槛**。

## 5. 预注册门槛判定

| 门槛 | 结果 | 解释 |
| --- | --- | --- |
| `package_provenance_closure` | PASS | 冻结包哈希闭包 |
| `manifest_contract` | PASS | run/selection contract 可解析 |
| `contact_failures_zero` | PASS | 已接受 pose 的 contact 提取无失败 |
| `per_candidate_failure_tolerance_override_false` | PASS | 无候选特定豁免 |
| `tolerance_relaxation_false` | PASS | 无临时降低门槛 |
| `main_dg_a_64_of_64` | **FAIL** | 仅 38/64 候选双 main 完整 |
| `replicate_receptor_runs_32_of_32` | **FAIL** | 仅 21/32 完整 |
| `comparison_rows_16` | **FAIL** | 仅 8/16 有效比较 |
| `comparison_pilot_id_set_exact` | **FAIL** | 预期与观测 ID 集合不一致 |
| `comparison_both_sides_dg_a` | **FAIL** | 全部 16 对未能同时满足两侧 DG-A |
| `repeat_R_gold_spearman_ge_0_70` | **FAIL** | 比较合同未闭包，值为 `null` |
| `stable_tier_expected_disagreement_gt_0` | **FAIL** | 8 个有效对均为 G1/G1 |
| `stable_tier_quadratic_kappa_ge_0_60` | **FAIL** | 值为 `null` |

这些 PASS 门证明审计未篡改预注册包、未放宽标准；它们不能抵消 8 个正式失败门。

## 6. 独立 veto：HETATM 污染

### 6.1 诊断范围和可复现性

HETATM 审计是只读诊断，范围为 `P2PILOT_001` 和 `P2PILOT_033` 的 8 个 revised-smoke run，不是对完整 Pilot64 的重标。

| 诊断证据 | 结果 |
| --- | ---: |
| smoke runs | 8 |
| baseline x model rows | 156 |
| unique aligned poses | 156 |
| 当前 V1.1 metrics 精确复现 | 156/156 |
| 当前 V1.1 classes 精确复现 | 156/156 |
| 受 HETATM 影响的 total occlusion | 156/156 |
| 受 HETATM 影响的 CDR3 occlusion | 156/156 |
| CDR3 fraction 改变 | 156/156 |
| 分类改变 | 18/156（11.54%） |

重算仅将参考 PVRL2 原子过滤从 `ATOM + HETATM` 改为蛋白 `ATOM`；altloc、坐标、CDR 范围、4.5 A cutoff 和 hotspot 均保持不变。因此该对照能够把差异定位到参考链 record-type 语义。

### 6.2 参考链污染清单

| baseline | PVRL2 chain | protein `ATOM` | `HETATM` | 组成 |
| --- | --- | ---: | ---: | --- |
| 8X6B | A | 963 atoms / 126 residues | 58 atoms / 58 residues | 58 HOH |
| 9E6Y | D | 1,002 atoms / 130 residues | 84 atoms / 66 residues | 60 HOH + 24 EDO atoms（6 EDO residues） |

当前语义把上述水和 EDO 与 VHH 的近接计为“VHH 遮挡 PVRL2 残基对”，这不符合目标指标的生物学含义。

### 6.3 对当前分类的影响

| 当前 V1.1 -> protein-only sensitivity | 行数 |
| --- | ---: |
| `BLOCKER_LIKE_A -> BLOCKER_PLAUSIBLE_B` | 4 |
| `BLOCKER_PLAUSIBLE_B -> EVIDENCE_INFERENCE_ONLY_E` | 14 |
| **分类改变合计** | **18** |

这个缺陷位于 **PVRL2 参考界面的后处理/遮挡计分**，而不是 VHH-PVRIG docking 坐标本身。因此部分 pose 坐标可在严格受限的开发通道中复用，但当前 occlusion 数值、A/B/C/E 类别和由它们派生的 Gold 标签不可复用。

**特别注意：**当前 protein-only 结果只是 sensitivity analysis。它仍套用了在被污染语义下建立的旧阈值，所以它不是 V1.2 标签、不是 corrected Gold，也不得直接进入训练。

## 7. V1.1 数据处置和复用政策

| 数据/产物 | 允许的用途 | 禁止的用途 |
| --- | --- | --- |
| V1.1 审计、报告、manifest 和哈希 | 原样冻结，作为被否决版本的 provenance | 覆盖、静默修补或改写历史结论 |
| 108 个 DG-A-complete run 的原始 pose ensemble | 仅作 V1.2 ATOM-only 重评分、阈值重校准等 development-only 输入 | 当作冻结 Gold 标签或 formal holdout |
| 1,028 个已接受 pose rows | 开发期诊断和重评分 | 作为 V1.1 Gold 训练行 |
| 38 个双 main 完整候选 | 开发期聚合方法、阈值和失败模式研究 | 作为已验证 Gold candidate set |
| 8-run / 156-row HETATM smoke | sensitivity 与校准开发 | 当作 corrected Gold 或 V1.2 target |
| 52 个不完整 run | 失败原因诊断 | 回填、降门槛或进入训练；必须重跑 |
| 整个 Pilot64 | V1.2 protocol development | V1.2 新的 formal holdout |

整个 Pilot64 的结果已经影响了缺陷发现和 V1.2 修订策略，因此不再是“未触碰”数据。不能把旧 Pilot64 重算后重新命名为 V1.2 formal holdout。

## 8. V1.2 必须执行的修复计划

### Stage 0：冻结 V1.1 否决证据

1. 保留 V1.1 scorer、classifier、rules、run outputs、审计和报告不变。
2. 不在旧文件上修补以制造“原版已通过”的错误印象。
3. 将 V1.1 状态持续标记为 `FAIL_DOCKING_GOLD_NOT_VALIDATED` 和 `P2_TRAINING_BLOCKED`。

### Stage 1：新建版本化 ATOM-only scorer

1. 新建 V1.2 scorer，不覆盖 V1.1 实现。
2. 参考 PVRL2 只解析蛋白 `ATOM` heavy atoms。
3. 显式排除所有 `HETATM`，包括 HOH、EDO 及其他非蛋白记录。
4. 输出 `ATOM/HETATM`、residue name、chain 和 atom/residue 数量清单，使记录类型可审计。
5. 增加数值闭包测试：total、CDR3、fraction、hotspot 和分类输入都必须能从行级证据重建。

### Stage 2：重新校准指标和阈值

1. 在 ATOM-only 语义下重算连续遮挡量、CDR3 贡献、hotspot overlap 和双 baseline 组合。
2. 使用已知成功案例和匹配 decoy/control 进行重校准，而不是直接沿用 V1.1 A/B/C/E 阈值。
3. 同时检查连续指标分布、极值、稳定性和双 baseline 的分歧模式。
4. 将阈值、计分函数、聚合规则、软件哈希和数据范围纳入新的预注册。
5. 不得把本次 protein-only sensitivity class 直接作为新标签。

### Stage 3：发展期重评分与失败 run 重跑

1. 对 108 个 DG-A-complete run 的 pose 使用冻结后的 V1.2 scorer 重评分，仅作开发和校准数据。
2. 对 52 个不完整 run 在同一全局冻结的 revised docking protocol 下重跑。
3. 禁止 candidate-specific tolerance、降低 8-pose 下限或从上游阶段回填。
4. 将失败率、final selected-model 分布和 receptor/seed-role 差异作为新协议的运行质量证据。

### Stage 4：重跑八运行 smoke

1. scorer、阈值和协议全部冻结后，重跑一个 8-run smoke。
2. 要求原子记录清单、行级计数、聚合结果和哈希闭包全部通过。
3. smoke 只能证明实现与数值闭包，不代替正式 holdout 重复性验证。

### Stage 5：预注册新的未触碰 holdout

1. 在 docking 开始前冻结一个未用于 V1.2 修订、阈值设定或调试的新 holdout。
2. 建议继续使用 **64 个候选 + 16 个 replicate candidates** 的合同，便于与 V1.1 比较；最终规模必须在运行前预注册。
3. 新 holdout 必须保持 candidate、parent/cluster、replicate ID、receptor、seed-role 和生成方法的清晰 provenance。
4. 旧 Pilot64 只是 development set，不可充当该 holdout。

### Stage 6：V1.2 正式验证门

V1.2 必须同时满足：

```text
all main candidates DG-A complete
all replicate receptor runs DG-A complete
comparison ID set exactly equals the preregistered set
exactly 16 valid replicate comparisons
contact/geometry failures = 0
candidate-specific tolerance override = false
tolerance relaxation = false
R_gold Spearman >= 0.70
stable-tier expected disagreement > 0
stable-tier quadratic weighted kappa >= 0.60
```

如果 tier 分布再次没有预期分歧，不得把 kappa 的 `null` 替换为 0、1 或“完全一致”。应当回到预注册设计，在不查看 formal 结果的前提下保证重复样本覆盖可辨别的 tier 范围。

### Stage 7：训练放行

仅当新的 V1.2 validation audit 返回 PASS，且数据 manifest、teacher outputs、split、代码和哈希全部冻结后，才允许：

```text
P2_TRAINING_BLOCKED -> P2_TRAINING_READY
```

在此之前，不得启动 P2 正式训练，也不得使用 V1.1 行训练一个“临时模型”后反过来调整 V1.2 formal holdout。

## 9. 建议的立即执行顺序

```text
1. 锁定 V1.1 FAIL 产物与本报告
2. 实现并测试版本化 ATOM-only PVRL2 scorer
3. 在 development/calibration 数据上重算连续指标并重标 A/B/C/E 阈值
4. 冻结 V1.2 scorer、rules、docking protocol 和预注册
5. 重跑 8-run smoke，验证 record inventory 与数值闭包
6. 用统一协议重跑 52 个旧失败 run，仅作 development closure
7. 在 docking 前冻结全新的 formal holdout 及 64/16 合同
8. 一次性运行 V1.2 formal validation
9. 只有全部门槛 PASS 才开始 P2 训练
```

当前最优先的任务不是训练模型，也不是扩大标签量，而是先把 **ATOM-only 语义、重校准阈值、运行完整性和未触碰 holdout** 四件事同时做成可审计的 V1.2 协议。

## 10. 证据产物与 SHA256

| 产物 | SHA256 |
| --- | --- |
| `audits/phase2_v3_p2_docking_gold_v2_audit.json` | `fc9d0dfb0d4419c08e2a9bad9053a80be539fe12b2b7944da688e5525fb9f4ab` |
| `reports/PVRIG_V3_P2_DOCKING_GOLD_V2_VALIDATION_ZH.md` | `5f146d41231860b75890df901f224af758dcb5ffdcdc748af8505ea59a558894` |
| `audits/phase2_v3_p2_dual_docking_pilot_v2_sync_audit.json` | `e70297e1373d7a5cde9e9da113ffae338f15c46e119aebd2f8313a0d2f10d566` |
| `audits/phase2_v3_p2_dual_docking_pilot_v2_postprocess_audit.json` | `d32d4873df425d36f5973fda6cc40daa40d2884e926d27171aa95f1b04e592ab` |
| `audits/phase2_v3_p2_v1_1_hetatm_contamination_audit.json` | `c53a12545de2ad827e39caaae7767d4ae442d16cd9b09cdc22479b0fd7527f45` |
| `reports/PVRIG_V3_P2_V1_1_HETATM_CONTAMINATION_REJECTION_ZH.md` | `69b4709dae1ad5bd87ce09eef3a89e795866fa0b0e0252d8e434eeb85e11a0b9` |
| `audits/phase2_v3_p2_v1_1_hetatm_contamination_rows.csv` | `c0fcaabdc2760d93ca94f8e9291bf90b7a011e1dd0cd2f7820b567d492af2daa` |

上表路径均相对于 `experiments/phase2_5080_v1/`。

关键实现哈希：

| 实现 | SHA256 |
| --- | --- |
| 当前 V1.1 occlusion scorer | `c5e419daec19e6e38b6a52bfc63e0d6100c9c16f27b46a60235dc0f6a438982f` |
| 当前 V1.1 classifier | `c5f6f96d4821863dd14dc201807d8c863226876507df36a9e78b7a47e7df2654` |
| 当前 rules JSON | `60424c514d0e1c4f32bfec28631b969ed511c89babb4a73dcecf504e1e6a16a5` |

工程验证：

- Docking Gold、postprocess、package 和 HETATM 审计的定向测试：39/39 PASS。
- `experiments/phase2_5080_v1/src` 全量 `unittest discover`：340/340 PASS。
- 五个本次关键 Python 脚本 `py_compile` PASS。
- `git diff --check` PASS；Node1 全量 controller 退出后无残留 controller/HADDOCK 进程。

## 11. 复现命令

以下命令从仓库根目录 `/mnt/d/work/抗体/data` 运行：

```bash
python experiments/phase2_5080_v1/src/sync_phase2_v3_p2_dual_docking_pilot.py \
  --inventory-only || true

python experiments/phase2_5080_v1/src/process_phase2_v3_p2_dual_docking_pilot.py || true

python experiments/phase2_5080_v1/src/build_phase2_v3_p2_docking_gold.py
# 预期退出码：2，因为 Gold 验证被否决。

python experiments/phase2_5080_v1/src/audit_phase2_v3_p2_v1_1_hetatm_contamination.py
```

HETATM 审计脚本的默认 `EXPECTED_RUN_IDS` 故意只覆盖上述 8 个 revised-smoke run。它不应被描述成“已用 ATOM-only 规则修正全 Pilot64”。

## 12. 最终决策记录

```text
V1.1 Docking Gold: REJECTED
Formal status: FAIL_DOCKING_GOLD_NOT_VALIDATED
P2 training: BLOCKED
Current V1.1 labels: NOT TRAINING-ELIGIBLE
Protein-only sensitivity labels: NOT CORRECTED GOLD
Next admissible version: V1.2 after ATOM-only rescoring,
threshold recalibration, complete repeatability validation,
and a fresh untouched holdout
```
