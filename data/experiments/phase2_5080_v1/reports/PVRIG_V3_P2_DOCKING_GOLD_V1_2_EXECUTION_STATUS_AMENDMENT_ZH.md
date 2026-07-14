# PVRIG V3-P2 Docking Gold V1.2 执行与状态修订

- 修订日期：2026-07-14（Asia/Shanghai）
- 协议 ID：`DG_A_PVRIG_V1_2_DEV`
- 文件性质：V1.2 执行结果的状态修订，不是新的阈值预注册
- 当前总状态：`FAIL_DOCKING_GOLD_NOT_VALIDATED`
- 训练决策：`P2_TRAINING_BLOCKED`

## 1. 修订结论

V1.2 的 47-case 包已经验证了固定 `4_emref` Top-8 姿态、ATOM-only 连续几何量、输入 provenance 和字节级确定性。它因而可以冻结为**校准规则的连续 pose 输入**，但不能冻结 family-aware 阈值、A/B/C/E 或 G1-G5 类别、单 run 评分方法、双受体 `R_gold` 或训练标签。

```text
PASS: fixed 4_emref Top-8 continuous pose inputs
FAIL: family-aware rule and tier stability
FAIL: Docking Gold label release
BLOCKED: P2 training
```

唯一未通过的 family-aware acceptance gate 是 bootstrap：预注册要求至少 `9/11` 个 success anchor 的 modal-tier probability `>=0.70`，实测为 `7/11`。因此，即使其余 9 个 gate 通过，也不得解除 `P2_TRAINING_BLOCKED`。

## 2. 与既有文档的关系

本修订不覆盖、不回写、不弱化以下既有结论：

| 既有文档 | 状态 | SHA256 |
| --- | --- | --- |
| `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_1_FINAL_REJECTION_ZH.md` | V1.1 最终否决保持有效 | `a8a6da78010cd08ecd56601d321eea2ee1425554f03890f1b45c96ef63be5726` |
| `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_CALIBRATION_METHOD_ZH.md` | V1.2 原始方法预注册保持原样 | `ed1651b11eb865fdfa30cce6b69da4cdebc13f4982c53915cfa2bd838c4bbb25` |
| `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_CALIBRATION_METHOD_AMENDMENT_1_ZH.md` | 输入不变性和来源修订保持有效 | `31943ef53535beef066c48f1da24bb59e90aa03c774637342945317b483adbbc` |

本文仅记录运行后的决策边界：连续输入层通过，规则和标签层失败。

## 3. 47-case 包实际冻结的内容

47-case 处理包闭包为：

```text
47 cases
376 fixed Top-8 poses
752 pose x baseline continuous-metric rows
752 residue-contact records
source docking receptor = 8X6B
9E6Y = post-hoc reference scoring of the same poses
thresholds_or_classes_applied = false
```

对应的 upstream audit 显式记录：

```text
status = PASS_V1_2_TOP8_CALIBRATION_CONTINUOUS_METRICS_BUILT
pose_rule_threshold_freeze_eligible = true
threshold_freeze_eligible = false
dual_receptor_r_gold_freeze_eligible = false
formal_eligible = false
```

其中 `pose_rule_threshold_freeze_eligible=true` 的含义只是“该连续 pose 包可作阈值拟合输入”，不表示拟合后的阈值或 tier 规则已经通过。

两次全量重建的 758 个包文件路径和 SHA256 完全相同，但该确定性仅证明连续输入可重建，不能替代 family 稳定性门槛。

| 关键证据 | 路径 | SHA256 |
| --- | --- | --- |
| Top-8 package audit | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_top8_calibration/pvrig_v1_2_top8_calibration_audit.json` | `6d7e67fdf6c25d14723e762e00cbf8058a01661815198ed313079212ea9330d4` |
| continuous metrics | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_top8_calibration/pvrig_v1_2_top8_continuous_metrics.csv` | `9a18d3f8002f6f827b33e0ec7144506add4e925e9907a872d992f01a36f347c2` |
| residue contacts | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_top8_calibration/pvrig_v1_2_top8_residue_contacts.jsonl` | `cc29c580d3e0256536c3d2191b83a32cfd8bc7870c5315cd2ff4cae234199052` |
| processor release manifest | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_processor_release_manifest.json` | `a4c876594434076a86b75a073ff4ac02914c88ea20b97c946e299f72c7552cd7` |
| deterministic rebuild audit | `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_top8_deterministic_rebuild_audit.json` | `9adb33341e18431175ce04bcc523001bb430e1224899eb779fa2083e74cf8938` |

## 4. Family-aware 规则为何不能冻结

正式 family-aware 校准使用 seed `20260714` 和 `B=2000` 次 bootstrap，产生 20,000 行 threshold 和 22,000 行 anchor evaluation。其中 33 次 replicate 的 canonical shared-H 出现 `U==L`，被按预注册规则记为 undefined。

中心校准的 LOFO 和 family retention 通过，但 bootstrap modal-tier 稳定性未通过：

| anchor | family | modal tier | modal-tier probability |
| --- | --- | --- | ---: |
| `case02_pos_04_PVRIG-38` | 38 | G3 | 0.4565 |
| `case02_pos_05_PVRIG-39` | 39 | G3 | 0.5035 |
| `case02_pos_06_20H5` | 20 | G1 | 0.5845 |
| `case02_pos_09_39H4` | 39 | G3 | 0.5330 |

因而审计结论是：

```text
status = FAIL_V1_2_FAMILY_CALIBRATION_NOT_FROZEN
acceptance gates = 9/10 PASS
failed_gates = ["bootstrap"]
anchors modal probability >= 0.70 = 7/11
required = 9/11

pose_rule_threshold_freeze_eligible = false
single_8x6b_dock_run_method_freeze_eligible = false
dual_receptor_r_gold_freeze_eligible = false
training_label_release_eligible = false
formal_eligible = false
p2_training_blocked = true
```

主审计与人类可读报告为：

| 证据 | 路径 | SHA256 |
| --- | --- | --- |
| family calibration audit | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_family_calibration/pvrig_v1_2_family_calibration_audit.json` | `8aef0ed8ba8e2dbaf46f5dffa3940d7da8283469cfe6aa8d98b521518976eac7` |
| family calibration report | `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_FAMILY_CALIBRATION_ZH.md` | `1c744b210ccbc86b5d912c3239fa3fa2392b69430178ee57508db855e975aed3` |
| non-frozen diagnostic rules | `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_family_calibration/pvrig_v1_2_family_rules.json` | `7efdf44939816b7c81d3f968c661f50c381b86319a6535cdd537035d6f95b4c8` |

`pvrig_v1_2_family_rules.json` 是失败校准的可追溯诊断产物，不是可发布或可训练的冻结规则。

## 5. Smoke8 和 failed52 恢复资产的允许边界

Pilot64 恢复层已从 `4_emref` 实际物化坐标，并按固定 Top-8 顺序完成 remote/local hash closure：

| cohort | runs | source poses | selected Top-8 poses | selector SHA256 | recovery audit SHA256 |
| --- | ---: | ---: | ---: | --- | --- |
| smoke8 | 8 | 78 | 64 | `41469d9b60b8a969c0f11b1b1bb6aba43f54508dbb6449b9fbcf7a1fe6630f6f` | `f625886b2d7ee23314a12cac09e82983ed06e8d799cbd2c8b21df39384cb4206` |
| failed52 | 52 | 518 | 416 | `e7a2194a55788cd610df9d73e92ba3d5ac14de994cee468244c07e7950219544` | `ae80655146a3be193bb5cfc107adc8efa3efe523fba7ba88b3faa25f013d8daa` |

对应审计路径：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_pilot64_smoke8_emref_recovery_audit.json`
- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_pilot64_failed52_emref_recovery_audit.json`

恢复审计中的 `inventory_only=false` 表示执行时不只是列清单，而是已实际同步并选取坐标。它**不表示获得了评分或标签授权**。在当前科学决策中，这两批资产的可用性仍仅限于：

```text
coordinate inventory / provenance-preserved recovery asset
```

在新的预注册方法通过之前，明确禁止：

1. 对 smoke8 或 failed52 运行 A/B/C/E 分类、G1-G5 分层或当前 `R_calibration_run_8x6b_dock`。
2. 从已恢复坐标生成任何 Docking Gold、teacher label、训练标签或正负样本。
3. 使用它们解除 `P2_TRAINING_BLOCKED`，进入正式 smoke 评分、52-run 标签生成、dual-receptor `R_gold` 或 formal holdout。

## 6. 禁止事后调参

当前结果已经揭示 bootstrap 失败，因此不得在 V1.2 名义下事后修改或选择：

- q20/q50 阈值定义；
- support 规则、minimum pose 数或 Top-K 规则；
- bootstrap 层级、seed、replicate 数、0.70 门槛或 9/11 要求；
- 基于已见结果从 54 行 robustness grid 中挑选“最好看”的组合；
- 任何使当前 RC 从 FAIL 变成 PASS 的无版本号修补。

这些改动如有科学必要，必须作为新版本（例如 V1.3 或 V1.2.1）重新预注册，并在生成新的 smoke/regression 评分之前冻结数据、规则、验收门和失败处置。

## 7. 后续唯一允许的科学路径

1. 原样保留 47-case 连续输入包、失败的 family calibration 产物、smoke8/failed52 坐标资产和全部哈希证据。
2. 为新版本独立说明是否扩大 anchor family、增加校准数据，或更换稳定性表示；不得把已见 bootstrap 结果当作无偏的新验证证据。
3. 在任何下游评分前冻结新的 method、anchor manifest、split、阈值算法、bootstrap gate 和 acceptance contract。
4. 只有新预注册方法通过全部 gate，才能依次解锁 smoke/regression 评分、Gold 标签生成和 P2 训练评审。

## 8. 最终状态块

```text
FAIL_DOCKING_GOLD_NOT_VALIDATED
P2_TRAINING_BLOCKED

47-case continuous pose input: FROZEN AND REPRODUCIBLE
family-aware rule: NOT FROZEN
smoke8/failed52: RECOVERED COORDINATE ASSETS ONLY
A/B/C/E or G1-G5 scoring: PROHIBITED
Docking Gold / teacher labels: PROHIBITED
formal holdout: PROHIBITED
post-hoc threshold or gate tuning: PROHIBITED
```

> Claim boundary: 当前证据最多是单一 8X6B docking ensemble 上固定 Top-8 pose 的可重建计算几何输入，9E6Y 只是对同一批 pose 的 post-hoc reference scoring。它不是独立双受体 docking，不是 binder、affinity、Kd 或实验 blocking 真值，也尚未成为可发布的 Docking Gold teacher。
