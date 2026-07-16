# PVRIG V4-D Decimal 阈值协议修订记录

## 1. 修订结论

V4-D 在产生任何独立双构象 Docking 结果之前完成了后处理协议修订。修订只改变缩放阈值的数值实现，不改变候选、数据划分、单体结构、Docking 作业矩阵、科学阈值或 protocol core。

- 修订 ID：`v2_prelaunch_decimal_threshold_correction_20260716`
- 新 evaluator gate：`pvrig_v4_d_evaluator_stability_v3_decimal_thresholds`
- 边界策略：包含性 `>=`
- 缩放算法：`float(Decimal(str(value)) * Decimal(str(scale)))`
- 典型修复：`100.0 * 1.1` 不再膨胀为 `110.00000000000001`
- 回归边界：其他 A 类条件满足时，`CDR3 occlusion = 110.0` 在 `1.1x` 下通过；`109.999999999` 不通过 A 类。

## 2. 修订时点

修订前在 node1/node23 的共享项目中确认：

- `status/jobs`：0 个文件
- `results`：0 个文件
- `runs`：0 个文件
- `failed_attempts`：0 个文件
- V4-D 活跃进程：0
- 状态汇总：`2022 PENDING`

因此，本次修订发生在任何 V4-D 新 Docking 标签、pose 或作业结果产生之前。

## 3. 变更文件

实际运行时变更：

- `config/evaluator_stability_gate.json`
- `scripts/aggregate_results.py`
- `tests/test_stability_gate.py`
- `PROTOCOL_LOCK.json`
- `manifests/protocol_manifest.json`
- `governance/phase2_v4_d_preregistration.json`
- `scripts/monitor_phase2_v4_d_after_v4_c_remote.sh`

本地可复现 staging 逻辑同步变更：

- `experiments/phase2_5080_v1/src/stage_phase2_v4_d_fullqc290_remote.py`

`aggregate_results.py` 的所有缩放分类阈值都改为 Decimal 字符串乘法，包括 A 类、C 类和 B 类使用的 hotspot、total occlusion、CDR3 occlusion 与 CDR3 fraction 阈值。evaluator 输出新增 `stability_gate_id` 和 `numeric_comparison`，使结果文件能自证所用数值协议。

## 4. 不变量校验

以下冻结对象在修订前后保持不变：

| 对象 | SHA-256 |
|---|---|
| protocol core 内容哈希 | `91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7` |
| `PROTOCOL_CORE_LOCK.json` | `767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24` |
| 2022-job manifest | `96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737` |
| 290-candidate manifest | `c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd` |
| candidate monomer manifest | `ebc07ccb7ba36dee84714fbf27911e82b560d1cc184a8d45e054d8577f1d70f0` |
| FullQC290 split manifest | `c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd` |
| split audit | `e0fa1b2558e8dd1f6c934f709822706beb26ae69e4859fad3bdc4d5abaa3df37` |

## 5. 新后处理锁

| 对象 | SHA-256 |
|---|---|
| evaluator gate config | `fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774` |
| `aggregate_results.py` | `b339c278c7146b5b1a6d1b0f106e06786ad6cfc6440998f3bbd7b272c7b18e4b` |
| `test_stability_gate.py` | `1e9913f607e1f99f4b9601b368c697897f1381fdfdaedbc2531a566a3073f0d6` |
| final protocol 内容哈希 | `a24eaf37730bc569067d64cdc1a43a763b70878d13d50e804bf3000ce43f5e84` |
| `PROTOCOL_LOCK.json` | `56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574` |
| preregistration v2 | `b7a1e4fed9b4e625f505c0afbeee1a95ceedfa9986ae83f369f497d2e4f71222` |
| prelaunch protocol validation | `eb181f76b9318b16da0821e03ae2ede5a7bd8e5c2ab5c53ca1a84999fb37246c` |
| watcher | `64faa6729198b17732168e296e44de5f4a1bf7159a5493cdbee3b817582f7ec3` |

## 6. 验证结果

- Decimal 定向测试：`2/2 PASS`
- V4-D runtime 全套单元测试：`34/34 PASS`
- `validate_protocol.py --expected-total-jobs 2022`：`PASS`
- watcher 启动前 12 项 SHA-256 校验：全部 `OK`
- watcher 读取上游 V3 evaluator：`READY evaluator_pass`
- node23 预检：64 逻辑 CPU、本地 ext scratch、约 500 GB 可用空间、启动前无 HADDOCK/CNS 进程

## 7. 归档位置

远端原协议：

- `/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715/governance/protocol_revisions/v1_pre_decimal_correction_20260716`

远端修订后协议：

- `/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715/governance/protocol_revisions/v2_decimal_correction_prelaunch_20260716`

本地审计副本：

- `experiments/phase2_5080_v1/audits/pvrig_v4_d_protocol_revision_v2_decimal_20260716`

归档目录均包含 `SHA256SUMS`；本地归档还保存了修订后的 staging 源码哈希。

## 8. 当前执行状态与证据边界

2026-07-16 11:17（Asia/Shanghai），watcher 在 node23 通过所有预检后启动 `smoke_then_full`，PID 为 `261601`。流程先运行 4 个固定 smoke jobs；只有 `SMOKE_VALIDATION.json` 为 `PASS` 时才进入 2022-job 全量控制器。

V4-D 输出只代表双构象计算几何、pose 一致性和不确定性证据，不是结合概率、Kd、真实亲和力、竞争实验或实验阻断结论。
