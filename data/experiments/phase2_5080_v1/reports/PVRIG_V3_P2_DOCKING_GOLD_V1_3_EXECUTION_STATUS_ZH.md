# PVRIG V3-P2 Docking Gold V1.3 执行状态

**更新时间：** 2026-07-15  
**自动流程终态：** `COMPLETE_DEVELOPMENT_FAIL_STOPPED`  
**Docking 执行：** `30/30 PASS`  
**Development release：** `FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN`  
**必须保持的训练状态：** `P2_TRAINING_BLOCKED`

## 1. 结论

V1.3 已完整执行到独立 development release，不再等待远程 docking：

```text
30/30 new docking runs PASS
0 failure
0 invalid
0 missing
Node1 controller = 0
Node23 controller = 0
```

Selector/recovery、两次独立 native processor build、processor qualification、两次独立 calibration build 和 development release validation 都已技术闭包。

最终停止原因不是 docking 命令失败，而是预注册的 `bootstrap` modal-stability gate 未通过：11 个 positive anchors 中只有 6 个的 modal tier probability 达到 `>=0.70`。因此当前不得进入 development smoke、Formal Gold、Docking Gold label、training-label release 或 P2 training。

> 本文中的“Docking Gold V1.3”是协议/工作流名称，不表示本轮已发布 Docking Gold。

## 2. 目标和证据边界

本轮只验证：在固定 47-case development cohort 上，是否能用真正独立的 8X6B 和 9E6Y native docking，生成可重现的双受体计算几何证据。

冻结规模：

```text
47 cases
94 native main runs
2 receptors per case
Top-8 per run
752 canonical native poses
752 primary native metric rows
```

这些结果不是：

- binder 真值；
- affinity/Kd 真值；
- 实验 PVRIG-PVRL2 blocking 真值；
- 可直接用于训练的 Gold label；
- formal holdout 结论。

当前 anchor panel 仍为 `11 anchors / 5 families / 0 new independent families`，formal readiness 仍为 `FAIL_FORMAL_ANCHOR_READINESS_ZERO_NEW_FAMILIES`。即使 development method 通过，这一独立 formal veto 也不会被解锁。

## 3. 1–4 项执行结果

### 3.1 项目 1：冻结 V1.2 失败 RC

已完成并复验通过：

```text
PASS_V1_2_FAILED_RC_FREEZE_VALIDATED
54/54 artifacts
758/758 package files
46/46 semantic assertions
```

V1.2 历史结论保持不变：

```text
FAIL_DOCKING_GOLD_NOT_VALIDATED
P2_TRAINING_BLOCKED
```

关键产物：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_failed_rc_freeze_manifest.json`
- `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_FAILED_RC_FREEZE_ZH.md`

### 3.2 项目 2：冻结 V1.3 预注册和 anchor 边界

已完成：

- development preregistration：`phase2_v3_p2_v1_3_development_preregistration.json`
- anchor readiness：`phase2_v3_p2_v1_3_anchor_readiness_audit.json`
- formal readiness：`FAIL_FORMAL_ANCHOR_READINESS_ZERO_NEW_FAMILIES`

预注册要求所有 development gates 同时通过，不允许在看到结果后放宽 modal-stability 门槛。

### 3.3 项目 3：完成独立双受体 docking

完整闭包为：

```text
64 Pilot64 independent dual-receptor runs reused
+ 30 newly completed runs
= 94 native runs
```

30 个新 run 最终为 `30/30 PASS`，无 failure、invalid 或 missing。这些 9E6Y 结果来自独立 9E6Y receptor docking，不是将 8X6B pose 对齐后重评分。

运行期间完成 Node1 -> Node23 单写者迁移：

- Node1 旧 controller 先退役；
- Node23 继续剩余 run 并自然退出；
- 4 个迁移前 completion SHA 与 3 个 handoff phase SHA 始终匹配；
- 最终 Node1 和 Node23 均为 0 个 matching controller。

迁移收据：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_node23_migration_receipt.json`
- status：`PASS_NODE1_TO_NODE23_SINGLE_WRITER_HANDOFF`
- SHA256：`cdc62f40bee7f6038d80be20e7589caa02e19fd6830525044be097753caa625c`

Autorun 最终 remote snapshot：

```text
status=READY
host=node23
manifest=30
completion=30
pass=30
failure=0
invalid=0
missing=0
frozen completion hashes valid=true
handoff phase hashes valid=true
```

### 3.4 项目 4：recovery、processing、calibration 和 release validation

#### Selector / recovery

```text
status:       PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED
release_id:   v1_3_c7b747e410e83c8265b4a4d4
cases:        47
runs:         94
Top-8 poses:  752
8X6B:         376
9E6Y:         376
```

- inventory SHA256：`acba296d7a3737bafb5dc42b148d7b3ed05dfa71ee387d8025748bbe8ec5c3b2`
- selector CSV SHA256：`38dfad82898d72680648eedd0974180a114d10974303cba04e7d5031ebf67e02`
- selector audit SHA256：`2a769f36c153079eb11c9cbc4957a88466ef0d01b66097a2a8e892653ab055bf`

产物目录：

- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_dual47_top8_recovery/current/`

#### Native processor 双构建和资格验证

Primary 与 rebuild 均为：

```text
release_id:       native-407972116e8b245a771ee881
metric rows:      752
contact records:  752
aligned poses:    752
full inventory byte-identical: true
inventory SHA256: f359c1e324e3cf6e980459287fa675bbe786a91a9f16896a97a911376801d27e
```

资格验证：

```text
release_id:                  qualification-9c4cb7d3de1a7dd9391536b3
status:                      QUALIFIED_NATIVE_PROCESSOR_INPUT
calibration_input_eligible:  true
```

`calibration_input_eligible=true` 只说明这两个字节一致的 native processor release 可进入 calibrator；它不会使 Gold、training 或 P2 资格变为 true。

产物目录：

- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_native_processing/current/`
- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_native_processing_rebuild/current/`
- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_native_processor_qualification/current/`

#### Development calibration 双构建

```text
release_id:              calc-2cec76b7f56f1f90171e4313
status:                  CALCULATED_PENDING_RELEASE_VALIDATION
computed_gate_outcome:   COMPUTED_GATES_NOT_SATISFIED
files per publication:   13
all files byte-identical: true
inventory SHA256:        ab70c9606ab9f12fd8e0bdadb827fd7019fb54260ee38856eb069750eb59b8b0
```

产物目录：

- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_native_dual_calibration/current/`
- `experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_native_dual_calibration_rebuild/current/`

## 4. Calibration 结果和失败门

中心规则得到：

```text
All 47 cases:
G1=5, G2=10, G3=29, G4=3, G5=0

11 positive anchors:
G1=3, G2=3, G3=4, G4=1, G5=0
```

主要稳定性指标：

| Gate | 结果 | 状态 |
| --- | ---: | --- |
| 5-family LOFO macro G1-G3 recall | `0.9333333333333333` | PASS |
| Bootstrap receptor consistency `>=0.70` | `11/11` | PASS |
| Bootstrap modal tier probability `>=0.70` | `6/11` | **FAIL** |

未达到 modal probability `0.70` 的 5 个 anchors：

| Anchor | Modal probability |
| --- | ---: |
| PVRIG-20 | `0.5660` |
| PVRIG-38 | `0.6900` |
| PVRIG-39 | `0.3965` |
| 20H5 | `0.4885` |
| 39H4 | `0.6595` |

预注册的 17 个 development gates 中，除 `bootstrap=false` 外其余 16 个均通过。但规则要求所有门同时通过，所以不能用其他门的良好结果抵消 bootstrap 失败。

这个结果表示：

- 双受体 docking 和 native geometry 计算链可重现；
- 大多数 positive anchors 能留在 G1-G3；
- 但对 5 个 anchors，bootstrap 重采样后的最常见 tier 不够稳定；
- 因此 V1.3 规则暂时不足以冻结为可释放训练标签的方法。

## 5. 独立 development release 终态

```text
release_id:                     development-741e929ea09c944b3e30829c
status:                         FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN
development_method_passed:      false
development_smoke_eligible:     false
formal_eligible:                false
docking_gold_release_eligible:  false
training_label_release_eligible:false
p2_training_ready:              false
training_state:                 P2_TRAINING_BLOCKED
```

- release file SHA256：`ce9b2a05f3c0aa913a9b39dde0b5d50e4138a80dc795f83c550adaeb378a59ba`
- 产物：`experiments/phase2_5080_v1/runs/pvrig_v3_p2/docking_gold_v1_3_development_release/current/pvrig_v1_3_development_release.json`

Autorun 已按照 fail-closed 合同在这一终态自动停止：

- 没有运行 development smoke；
- 没有运行 formal validation；
- 没有发布 Docking Gold 或 training label；
- 没有启动 P2 training；
- autorun state 中 `automatic_smoke_or_formal_commands=false`。

终态状态文件：

- `experiments/phase2_5080_v1/logs/pvrig_v1_3_production_autorun_state_v3.json`

## 6. 坐标 identity 金标验证

早期 544-pose 审计发现 HADDOCK pose 中 VHH C 端 `OXT` 可消失，同时只比较 `ATOM` 会静默忽略 pose-chain `HETATM` 漂移。因此 V1.3 在冻结 amendment 后仅允许“VHH 末端单个 OXT 存在/缺失”的 normalization，并对 A/B chain 的 heavy `HETATM` 使用 zero gate。

完整 752-pose production selector 复验：

```text
coordinate_or_score_modified=false
VHH terminal-OXT normalized identity exact: 752/752
PVRIG raw ATOM identity exact:             752/752
VHH heavy-HETATM zero gate:                752/752
PVRIG heavy-HETATM zero gate:              752/752
```

关键产物：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_atom_identity_difference_audit.json`
- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_atom_hetatm_identity_addendum_audit.json`
- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_atom_identity_normalization_amendment.json`
- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v2.json`

## 7. 最终验证

2026-07-15 在当前代码和产物上重新运行与终态直接相关的回归：

```text
autorun:             22/22 PASS
processor:             8/8 PASS
selector/recovery:    16/16 PASS
calibrator:             8/8 PASS
release validators:   11/11 PASS
--------------------------------
total:                65/65 PASS
```

测试覆盖 controller identity/alias 对抗、upstream hash 闭包、Top-8 禁止 backfill、坐标 identity、旧 Pilot64 manifest 兼容边界、processor 双构建字节一致性、bootstrap/LOFO 重算和 release validator 的 fail-closed 语义。

## 8. 后续原则

V1.3 已达到不可变的 development FAIL 终态，当前没有可继续的自动下游阶段。

如果后续继续研发，必须：

1. 建立新的方法版本和新的预注册；
2. 在不修改 V1.3 历史结论的前提下，分析并改善 modal tier stability；
3. 重新运行完整独立验证；
4. 仍需用新的独立生物学 family 解决 formal anchor readiness veto。

不允许：

- 看到 V1.3 结果后直接将 `0.70` 门槛改低并宣称原方法通过；
- 将 `QUALIFIED_NATIVE_PROCESSOR_INPUT` 误写为 Docking Gold；
- 将 G1-G3 计算几何分层当作实验 blocker 真值；
- 用当前 V1.3 标签启动 P2 training。
