# PVRIG V3-P2 Docking Gold V1.2 最终验证报告

- 验证日期：2026-07-14（Asia/Shanghai）
- 适用协议：`DG_A_PVRIG_V1_2_DEV`
- 总体状态：`FAIL_DOCKING_GOLD_NOT_VALIDATED`
- family 校准状态：`FAIL_V1_2_FAMILY_CALIBRATION_NOT_FROZEN`
- 训练决策：`P2_TRAINING_BLOCKED`
- 声明边界：本报告验证的是计算 docking/阻断几何教师信号，不是 binder、Kd、affinity 或实验功能阻断真值

## 1. 最终结论

V1.2 已经完成并验证了一个重要但有限的子目标：

```text
fixed 4_emref Top-8 pose selection
+ ATOM-only PVRL2 occlusion
+ shared canonical H/internal-contact channel
+ 47-case / 376-pose / 752-row numeric closure
+ processor release manifest
+ byte-identical deterministic rebuild
= PASS as continuous calibration input
```

但 Docking Gold 的核心放行条件仍未通过：

```text
family-aware rule calibration
bootstrap modal-tier stability
required: >=9/11 anchors with modal-tier probability >=0.70
observed: 7/11
= FAIL
```

因此，当前只能说“连续几何输入已经可重建”，不能说“Docking Gold 已验证”。下列决策保持不变：

```text
pose_rule_threshold_freeze_eligible=false
single_8x6b_dock_run_method_freeze_eligible=false
dual_receptor_r_gold_freeze_eligible=false
formal_eligible=false
training_label_release_eligible=false
p2_training_blocked=true
```

不得把当前 A/B/C/E、G1-G5、`R_calibration_run_8x6b_dock` 或已恢复的 Pilot64 坐标当作正式训练 Gold。

## 2. V1.1 否决保持原样

V1.1 的历史否决没有被 V1.2 覆盖、改名或追溯修补。原始报告仍是：

`experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_1_FINAL_REJECTION_ZH.md`

当前 SHA256：

```text
a8a6da78010cd08ecd56601d321eea2ee1425554f03890f1b45c96ef63be5726
```

V1.1 的两个独立 veto 仍然有效：

1. 160 个请求 run 中只有 108 个满足当时的 DG-A 运行/输出合同；52 个 run 的 final selected models 只有 4-7，低于预注册下限 8。
2. V1.1 将 PVRL2 参考链中的 `HETATM` 水和配体计入遮挡；诊断重算中 156/156 行受影响，18/156 行分类改变。

V1.2 修复了第二个 veto 的测量语义，并用 fixed Top-8 规则恢复了可比分母；这不会使 V1.1 自动转为 PASS，也不会使 V1.2 跳过自己的稳定性门。

## 3. V1.2 实际使用的数据和几何语义

### 3.1 校准 cohort

| 层级 | 实际数量 |
| --- | ---: |
| case | 47 |
| success anchors | 11 |
| positive families | 5（151、20、30、38、39） |
| mutant/control cases | 36 |
| 每个 case 的 fixed pose | 8 |
| unique source poses | 376 |
| post-hoc baseline metric rows | 752（376 x 2） |
| residue-contact records | 752 |

11 个已知成功 anchor 用于 family-aware 校准、LOFO 和 bootstrap 稳定性审计。它们是 calibration-only / leakage-excluded 证据，不是正式候选或无偏测试集。36 个 mutant/control 用于配对敏感性分析，不被预设为 non-binder。

### 3.2 pose 选择

每个 case 只从 HADDOCK `4_emref/io.json` 选择 pose：

```text
ascending HADDOCK score
-> original io index
-> file name
-> first 8 poses
```

选择器不读取 `6_seletopclusts`、不使用下游阻断几何或 cluster size，也不 backfill。这解决了 V1.1 中可变 final-pose 分母不可比的问题。

### 3.3 单 docking receptor 边界

47-case cohort 的 source pose 全部来自：

```text
8X6B receptor docking
```

8X6B 和 9E6Y 在当前包中是同一批 pose 的两个 post-hoc PVRL2 参考界面评分通道，不是两次独立 receptor docking。因此当前最多能校准：

```text
R_calibration_run_8x6b_dock
```

不能定义、冻结或声称：

```text
R_gold
R_dual_receptor
mean(R_run_8X6B_dock, R_run_9E6Y_dock)
```

## 4. 已通过的 V1.2 工程与数值闭包

### 4.1 ATOM-only PVRL2 语义

V1.2 只使用 PVRL2 protein `ATOM` heavy atoms，所有 `HETATM` 都排除。实际库存为：

| baseline | PVRL2 chain | 纳入的 protein `ATOM` | 排除的 `HETATM` |
| --- | --- | ---: | ---: |
| 8X6B | A | 963 heavy atoms / 126 residues | 58 atoms / 58 HOH residues |
| 9E6Y | D | 1,002 heavy atoms / 130 residues | 84 atoms / 66 residues：60 HOH + 24 EDO atoms（6 EDO residues） |

两个 baseline 的 ATOM-only inventory gate 均通过，不再把水或 EDO 与 VHH 的近接解释为 PVRL2 残基对遮挡。

### 4.2 shared canonical H/internal-contact 修复

PVRIG-VHH internal contact 和 hotspot 通道 `H` 对刚体对齐应当不变。早期预检发现，把 pose 分别对齐到 8X6B/9E6Y 后再从三位小数 PDB 重算，会在 4.5 A 边界产生量化翻转：

```text
5/376 poses: PVRIG-VHH contact-pair count baseline 不一致
2/376 poses: PVRIG contact-residue count 不一致
1/376 poses: hotspot overlap 14 -> 13
1/376 poses: H 0.5982142857 -> 0.5535714286
```

V1.2 现在对每个 raw `4_emref` pose 只计算一次 canonical internal-contact，使用 8X6B source numbering 和 `pdb_8x6b_ref` hotspot 列，然后在两个 post-hoc baseline 中共享。实测 376/376 pose 通过 cross-baseline equality hard gate。

保留 baseline-specific 的只有 PVRL2 遮挡：

```text
H <- shared canonical internal-contact channel
O_8, P_8 <- 8X6B PVRL2 reference
O_9, P_9 <- 9E6Y PVRL2 reference
```

### 4.3 连续指标闭包

专用输出目录：

`experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_top8_calibration`

| 产物 | 数量 | SHA256 |
| --- | ---: | --- |
| pose materialization manifest | 376 rows | `2358316c9e8d0d71d75993bab1a93bd0c3508621da9286421aca89008d3b1522` |
| continuous metrics | 752 rows | `9a18d3f8002f6f827b33e0ec7144506add4e925e9907a872d992f01a36f347c2` |
| residue contacts | 752 records | `cc29c580d3e0256536c3d2191b83a32cfd8bc7870c5315cd2ff4cae234199052` |
| package audit | 1 file | `6d7e67fdf6c25d14723e762e00cbf8058a01661815198ed313079212ea9330d4` |
| aligned PDB | 752 files | 逐文件哈希已写入 audit |
| 完整 package | 758 files | 包含 757 个非自指审计文件 + audit |

发布采用完整目录原子替换，发布后验证全路径/全哈希集，不保留 stale 或未入哈希的旧文件。`*_min_distance_a` 仅在对应 region 零 contact 时允许 null，并由零 atom/residue-pair 计数联合约束。

### 4.4 外部 release manifest

Processor 不使用自己生成的布尔值证明自己已冻结。外部 manifest：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_processor_release_manifest.json`

状态为 `FROZEN_V1_2_TOP8_PROCESSOR_RELEASE`，SHA256 为：

```text
a4c876594434076a86b75a073ff4ac02914c88ea20b97c946e299f72c7552cd7
```

该 manifest 绑定 processor/test、selector CSV/audit/implementation、positive/mutant manifests、aligner、V1.2 pose/region scorers、scoring helper、hotspot、numbering reconciliation 和 8X6B/9E6Y references。

### 4.5 字节级确定性

同一冻结输入完成两次真实全量重建，每次 758 个文件，路径集和 SHA256 集字节一致：

```text
status = PASS_V1_2_TOP8_BYTE_DETERMINISTIC_REBUILD
byte_identical = true
rebuild_count = 2
file_count_each = 758
rebuild_1_listing_sha256 = 82d0b2f4879b26c5b1490f1f59f558ff31f1e29570e813e3c14703a153cabf48
rebuild_2_listing_sha256 = 82d0b2f4879b26c5b1490f1f59f558ff31f1e29570e813e3c14703a153cabf48
```

确定性审计：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_deterministic_rebuild_audit.json`

SHA256：

```text
9adb33341e18431175ce04bcc523001bb430e1224899eb779fa2083e74cf8938
```

这些证据支持 `pose_rule_threshold_fit_input_eligible=true`，不支持阈值、tier 或 Gold 标签已冻结。

## 5. family-aware 校准：9/10 gates 通过，但总决策必须 FAIL

### 5.1 中心阈值

V1.2 按 family-balanced positive-part q20/q50 产生 5 个通道阈值：

| channel | metric | L raw | U raw | transform |
| --- | --- | ---: | ---: | --- |
| canonical shared | H | 0.49107143 | 0.61160714 | identity |
| 8X6B | O | 400 | 489 | log1p once |
| 8X6B | P | 0.39877301 | 0.45871560 | identity |
| 9E6Y | O | 398 | 487 | log1p once |
| 9E6Y | P | 0.39658849 | 0.46721311 | identity |

`O` 的 raw 单位是 residue-pair count，membership 只允许执行一次 `log1p`。这些是当前失败 RC 的校准结果，不是可发布 Gold 规则。

### 5.2 中心分层和 LOFO

| 对象 | G1 | G2 | G3 | G4 | G5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 11 success anchors | 4 | 1 | 6 | 0 | 0 |
| 47 all cases | 12 | 6 | 28 | 1 | 0 |

Leave-one-family-out 本身通过：

```text
5/5 families retain at least one G1-G3 anchor
macro-family G1-G3 recall = 1.0
11/11 anchor tier shifts <= 1
maximum absolute tier shift = 1
```

这说明中心估计在 LOFO 检查中没有明显崩溃，但不能替代 bootstrap 门。

### 5.3 唯一失败门：bootstrap modal-tier stability

预注册 bootstrap：

```text
seed = 20260714
B = 2000
hierarchy = family with replacement, then case within family with replacement
threshold rows = 20,000
anchor evaluation rows = 22,000
undefined replicates = 33
defined replicates = 1,967
```

33 个 replicate 中 canonical H 出现 `U == L`，被正确记为 undefined，没有被偷换为阶跃 membership。

核心 acceptance gate：

```text
modal-tier probability >= 0.70
required anchors = at least 9 of 11
observed anchors = 7 of 11
result = FAIL
```

未通过 modal-tier 概率门的 4 个 anchor：

| anchor | family | modal tier | modal probability | P(G1-G3) |
| --- | --- | --- | ---: | ---: |
| `case02_pos_04_PVRIG-38` | 38 | G3 | 0.4565 | 0.9830 |
| `case02_pos_05_PVRIG-39` | 39 | G3 | 0.5035 | 0.9835 |
| `case02_pos_06_20H5` | 20 | G1 | 0.5845 | 0.9830 |
| `case02_pos_09_39H4` | 39 | G3 | 0.5330 | 0.9835 |

所有 family 的 G1-G3 retention gate 均通过，但“大概仍在 G1-G3”不等于“具体 tier 足够稳定”。预注册门要求后者，因此不得用 retention PASS 抵消 modal-tier FAIL。

### 5.4 10 个 acceptance gates

| gate | 结果 |
| --- | --- |
| upstream provenance | PASS |
| pose and metric closure | PASS |
| ATOM-only inventory | PASS |
| threshold validity | PASS |
| family balance | PASS |
| 54-row sensitivity grid closure | PASS |
| LOFO | PASS |
| bootstrap | **FAIL** |
| mutant sensitivity | PASS |
| claim boundary | PASS |

合计 9/10 PASS，`failed_gates=["bootstrap"]`。这是一票否决门，不是可以用平均分或其他门的数量抵消的软指标。

### 5.5 mutant 和 robustness 不改变结论

29 个 exact-base mutant paired deltas 中：

```text
delta_R < 0: 19
delta_R > 0: 10
binary_negative_label_assigned = false for all
median(delta_R) = -0.131217
```

这说明不能因为某个序列是人工破坏性突变就把它直接当成二元负样本。54 行 robustness grid 全部保留，`best_row_selected=false`；不得从中选择事后最好看的一行替代中心规则。

family 校准审计：

`experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_family_calibration/pvrig_v1_2_family_calibration_audit.json`

SHA256：

```text
8aef0ed8ba8e2dbaf46f5dffa3940d7da8283469cfe6aa8d98b521518976eac7
```

### 5.6 family 校准的确定性复核边界

独立使用冻结参数重跑 B=2000 family calibration，临时重建耗时 12.60 秒，峰值内存 181,304 KB。重建的 9 个 data/rules 文件和外部中文报告均与正式产物字节一致。

临时 audit 与正式 audit 的唯一差异是 `$.report.relpath`：临时运行必然写入临时报告路径。将该路径字段归一化后，audit 恢复正式 SHA256：

```text
8aef0ed8ba8e2dbaf46f5dffa3940d7da8283469cfe6aa8d98b521518976eac7
```

因此 family calibration 的数值结果和 FAIL 决策可确定性重建；audit 的原始字节级比较必须区分“内容不确定”与“输出路径不同”，不得把后者误报为数值重建失败。

## 6. Pilot64 坐标已恢复，但评分与标签仍被禁止

V1.2 recovery adapter 已从远端哈希闭包地恢复 `4_emref` 资产。它只按：

```text
ascending_haddock_score
original_io_index
file_name
```

选取 Top-8，不读 `6_seletopclusts`，不 backfill。当前恢复结果是坐标/配置/哈希资产，目录中没有 score、metric、tier、label 或 Gold 产物。

### 6.1 smoke8

| 证据 | 结果 |
| --- | ---: |
| selected runs | 8 |
| source poses | 78 |
| selected Top-8 poses | 64 |
| remote/local file hash chain | equal |
| formal eligible | false |

Selector CSV SHA256：

```text
41469d9b60b8a969c0f11b1b1bb6aba43f54508dbb6449b9fbcf7a1fe6630f6f
```

Recovery audit SHA256：

```text
f625886b2d7ee23314a12cac09e82983ed06e8d799cbd2c8b21df39384cb4206
```

### 6.2 failed52

| 证据 | 结果 |
| --- | ---: |
| selected runs | 52 |
| source poses | 518 |
| selected Top-8 poses | 416 |
| remote/local file hash chain | equal |
| formal eligible | false |

Selector CSV SHA256：

```text
e7a2194a55788cd610df9d73e92ba3d5ac14de994cee468244c07e7950219544
```

Recovery audit SHA256：

```text
ae80655146a3be193bb5cfc107adc8efa3efe523fba7ba88b3faa25f013d8daa
```

### 6.3 为什么不继续评分

如果在已知 bootstrap 失败后仍对 smoke8/failed52 输出 A/B/C/E、G1-G5 或 Gold label，就等于把未冻结规则扩散到更大数据集，并为后续调参增加泄漏。因此本轮在“恢复可审计坐标资产”处停止是正确决策，不是尚未完成的运行错误。

## 7. 科学声明边界

### 7.1 可以声称

1. fixed `4_emref` Top-8 选择规则已实现并完成 47-case 闭包。
2. ATOM-only PVRL2 遮挡语义已排除 V1.1 的 HOH/EDO `HETATM` 污染。
3. raw-pose shared canonical H 消除了对齐后 PDB 量化导致的 internal-contact 假差异。
4. 47 case、376 pose、752 baseline metric rows 和 752 contact records 数值闭包。
5. 连续指标包可以字节级确定性重建。
6. family-aware 中心规则的 LOFO 表现良好，但 bootstrap 显示具体 tier 不足够稳定。

### 7.2 不可以声称

1. 不可声称 Docking Gold 已验证或已可用于 P2 训练。
2. 不可把当前 G1-G5 当成冻结标签。
3. 不可把 success anchors 当成无泄漏的训练或测试数据。
4. 不可把 mutant 当成 binder/non-binder 二元负样本。
5. 不可把 9E6Y post-hoc baseline 评分说成独立 9E6Y receptor docking。
6. 不可定义 dual-receptor `R_gold`。
7. 不可把计算几何 teacher 解释为实验 binding、affinity、Kd 或 blocking truth。
8. 不可对已恢复 smoke8/failed52 资产生成正式 Gold label。

## 8. 下一步：新版本必须先预注册，再生成新标签

当前失败不允许在 V1.2 内事后降低 0.70 门、修改 q20/q50、support fraction、minimum supporting poses，或从 54-row grid 中选择最有利的组合。正确分支是创建独立的 `V1.3` 或 `V1.2.1` 预注册。

### Stage 1：冻结当前失败 RC

1. 保留 V1.1 rejection、V1.2 method/amendment、processor release manifest、Top-8 package、family audit 和本报告的哈希。
2. 当前 rules JSON 持续标记 `threshold_freeze_eligible=false`。
3. 不改写历史 FAIL，不将当前 RC 重命名为 PASS。

### Stage 2：在查看新结果前预注册方法修订

新文档必须先写明：

1. 是增加/扩大独立 success-anchor families，还是修改 tier 稳定性表示；两者的科学理由和停止条件必须事先写定。
2. family/case 纳入与排除规则、泄漏规则、样本数和完整 manifest。
3. 阈值分位数、support、rank weight、bootstrap hierarchy/seed/B 和 acceptance gates。
4. 是保留原 `9/11 at 0.70` 门，还是换用新门；如果更换，必须在任何新校准输出产生前给出理由，不得围绕 V1.2 失败 anchor 调参。

fixed Top-8、ATOM-only、shared canonical H、conditional-null、完整发布替换和外部 release manifest 应作为新版本的不变工程基线，不应因当前稳定性失败而回退。

### Stage 3：建立更强的校准证据

1. 优先增加独立阳性 family，特别避免某个 family 只有单一 anchor 导致重采样阶跃。
2. 新 anchor 必须有可审计 provenance，并与正式候选/测试数据严格隔离。
3. 如继续使用 mutant，其标签仍必须来自重新建模和 docking，不得用突变设计意图代替计算或实验证据。
4. 保留 positive anchors 的 calibration-only / leakage-excluded 状态。

### Stage 4：重跑 family calibration，并严格执行新预注册门

1. 使用新冻结 manifest 重建连续指标和 family-aware 校准。
2. 要求 provenance、closure、ATOM-only、threshold validity、family balance、LOFO、bootstrap、mutant sensitivity 和 claim boundary 全部通过。
3. 任一预注册 veto 失败都继续保持 `P2_TRAINING_BLOCKED`。

### Stage 5：只有规则通过后才扩大评分

新 family rule 通过后，再依次执行：

```text
8-run smoke scoring
-> 52-run regression scoring
-> rebuilt Pilot64 aggregation
-> independent 9E6Y-receptor docking
-> new untouched formal holdout
```

smoke/regression 只是实现和回归证据，不能代替 independent dual-receptor 和 formal-holdout 验证。

### Stage 6：最终放行

只有在下列证据全部冻结后才可以解除训练阻塞：

```text
family-aware rules PASS
8-run smoke PASS
52-run regression PASS
rebuilt Pilot64 contract PASS
independent 8X6B and 9E6Y receptor runs PASS
dual-receptor R_gold definition and repeatability PASS
new untouched formal holdout PASS
manifest/code/reference/output hash closure PASS
```

然后才能执行：

```text
P2_TRAINING_BLOCKED -> P2_TRAINING_READY
```

## 9. 最终处置表

| 产物 | 当前允许用途 | 当前禁止用途 |
| --- | --- | --- |
| V1.1 rejection 包 | 历史 provenance、失败模式和回归证据 | 覆盖或改写为 PASS |
| V1.2 fixed Top-8 continuous package | 新预注册校准的连续 pose 输入 | 直接作为 Gold tier/label |
| V1.2 family rules/tiers | 失败 RC 分析、方法诊断 | P2 训练、正式候选打标 |
| success anchors | 机制校准、LOFO、bootstrap | 正式候选、无泄漏 test |
| mutant paired deltas | 连续敏感性 | 二元 non-binder 标签 |
| smoke8/failed52 recovered assets | 哈希闭包的坐标和待用输入 | 当前 A/B/C/E、G1-G5 或 Gold label |
| 8X6B-docked + 9E6Y post-hoc scores | 单 docking ensemble 的两参考界面分析 | dual-receptor `R_gold` |

## 10. 审计证据索引

| 证据 | 路径 |
| --- | --- |
| V1.1 最终否决 | `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_1_FINAL_REJECTION_ZH.md` |
| V1.2 校准方法 | `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_CALIBRATION_METHOD_ZH.md` |
| shared-H/来源修订 | `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_CALIBRATION_METHOD_AMENDMENT_1_ZH.md` |
| Top-8 selection audit | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_calibration_emref_top8_selection_audit.json` |
| processor release manifest | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_processor_release_manifest.json` |
| Top-8 continuous package audit | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_top8_calibration/pvrig_v1_2_top8_calibration_audit.json` |
| deterministic rebuild audit | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_deterministic_rebuild_audit.json` |
| family calibration audit | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_family_calibration/pvrig_v1_2_family_calibration_audit.json` |
| family calibration report | `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_FAMILY_CALIBRATION_ZH.md` |
| smoke8 recovery audit | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_pilot64_smoke8_emref_recovery_audit.json` |
| failed52 recovery audit | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_pilot64_failed52_emref_recovery_audit.json` |

## 11. 最终状态块

```text
V1.1 historical rejection:
  unchanged

V1.2 fixed Top-8 continuous input:
  PASS

V1.2 family-aware rule calibration:
  FAIL (bootstrap 7/11, required >=9/11)

Smoke8 / failed52:
  coordinate assets recovered and hash-closed
  scoring and Gold labeling blocked

Independent 9E6Y receptor docking:
  not validated

Dual-receptor R_gold:
  not defined or frozen

Formal holdout:
  not started under a validated rule

Overall:
  FAIL_DOCKING_GOLD_NOT_VALIDATED
  P2_TRAINING_BLOCKED
```
