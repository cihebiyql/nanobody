# PVRIG V3-P2 Docking Gold V1.3 Anchor Readiness 审计

## 1. 结论

本次审计的机器状态为：

```text
FAIL_FORMAL_ANCHOR_READINESS_ZERO_NEW_FAMILIES
P2_TRAINING_BLOCKED
```

当前本地注册的 PVRIG blocker-VHH 校准证据仍为：

```text
11 anchors
5 existing families
36 perturbation/control cases
0 newly eligible independent blocker-VHH families
```

因此，V1.3 可以作为 **development-only 的独立双 receptor 方法实验**继续执行，但无论 V1.3 development 的 completeness、LOFO、bootstrap 或 receptor-consistency 是否通过，都不得把结果升级成 formal Docking Gold 或 P2 训练标签。

机器审计：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_anchor_readiness_audit.json`

## 2. 当前 11 个 anchor 的 family 结构

| family | anchor 数 | anchor |
| --- | ---: | --- |
| 151 | 3 | PVRIG-151/HR-151、151H7、151H8 |
| 20 | 2 | PVRIG-20、20H5 |
| 30 | 2 | PVRIG-30、30H2 |
| 38 | 1 | PVRIG-38 |
| 39 | 3 | PVRIG-39、39H2、39H4 |

Family 38 仍是 singleton。V1.2 bootstrap 中不稳定的具体 anchor 包括 PVRIG-38、PVRIG-39、20H5 和 39H4；这说明当前样本结构不足以支撑稳定的 formal tier freeze，但不能据此删除困难 anchor、改阈值或把 mutant 当作新 family。

## 3. 什么才算“新增合格独立 family”

一个新 family 必须同时满足：

1. 有可解析的 PVRIG VHH 序列；
2. 有可追溯的实验 PVRIG binding 证据；
3. 有与 PVRIG-PVRL2 机制相关的 competition、blocking 或 functional-inhibition 证据；
4. 有足够的来源和 lineage provenance，可执行 family assignment 与 leakage exclusion；
5. 不是现有 family 的 humanized variant、点突变、alanine scan、重复构建、重复测量、docking seed 或 pose。

以下对象不会增加 family 或 anchor 数：

- 当前 36 个 perturbation/control；
- Teacher500 或其他仅由生成模型/序列模型提出的候选；
- 只得到 docking geometry、没有实验 blocker 证据的候选；
- 同一序列的不同 receptor docking、不同随机 seed 或不同 pose；
- 因设计意图被主观视为“破坏性”的 mutant。

这里的“0 个新 family”只针对当前已注册的本地证据集，不声称外部文献、专利或未导入的内部实验中不存在其他 PVRIG blocker family。

## 4. 下一次 formal 的最低准入合同

下一次 formal 方法必须在任何 formal threshold fit 之前，同时满足：

```text
blocker families >= 8
anchors per family >= 2
total anchors >= 16
families unseen relative to V1.2 >= 3
```

这四项是逻辑与，不是任选其一。

按当前 family 计数 `3/2/2/1/3`，仅达到名义上的 16 条总数仍不够。当前状态下，最少需要：

```text
3 个全新 family x 每 family 2 anchors = 6
+ 为 singleton family 38 增加 1 个独立 anchor
= 至少 7 个新增合格 anchors
```

因此，在保留当前 11 条的前提下，真正满足全部条件的最小可行总数是 18，而不是 16。

## 5. 对 V1.3 的无条件 veto

V1.3 明确使用同一批 11 anchors / 5 families 来开发独立双 receptor 的测量与聚合方法。因 `new_eligible_independent_family_count=0`，以下字段必须始终为 false：

```text
formal_eligible
docking_gold_release_eligible
training_label_release_eligible
p2_training_ready
```

即使 V1.3 development 全部门通过，也只能得到：

```text
PASS_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD
R_dual_dev
```

不能得到：

```text
R_gold
formal Docking Gold
P2 training labels
P2_TRAINING_READY
```

## 6. 合理的下一步

1. 先执行 V1.3 development-only 双 receptor 校准，验证 native-only 处理、五通道阈值、dual aggregation 和 receptor consistency 是否可运行且稳定。
2. 并行建立新 family evidence registry，但在证据满足前不进入 formal。
3. 每个新 family 至少准备 2 个真正独立、序列解析且有实验 blocker 证据的 anchor。
4. 新 anchor 清单冻结后，另起 formal 版本和新的预注册；V1.3 development 结果不能自动继承 formal 身份。
5. Formal cohort 必须包含至少 3 个 V1.2 未见 family，并执行完整 family-level leakage exclusion。

## 7. 证据边界

本审计绑定：

- `../docking/calibration/patent_success_validation/batch_manifest.csv`；
- `../docking/calibration/mutant_validation_panel/mutant_panel.csv`；
- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_failed_rc_freeze_manifest.json`；
- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_2_family_calibration/pvrig_v1_2_family_calibration_audit.json`。

精确 SHA256 和字节数写在机器审计中。本报告只判断 anchor readiness，不给出 binder、Kd、affinity、实验 blocking、geometry tier 或训练标签结论。
