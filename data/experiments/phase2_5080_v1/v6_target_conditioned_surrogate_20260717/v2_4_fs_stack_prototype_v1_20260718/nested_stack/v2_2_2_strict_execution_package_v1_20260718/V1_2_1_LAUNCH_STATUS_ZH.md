# V2.2.2 strict nested stack V1.2.1 启动状态

## 当前结论

```text
PASS_LAUNCHED_AND_FIRST_INNER_TRIPLE_COMPLETE
```

Node1 运行路径：

```text
package:
/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718

runtime:
/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_1_20260718

smoke:
/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_smoke_v1_2_1_20260718
```

进程：

```text
launcher PID 891011
runner   PID 891012
```

job graph：

```text
SHA256 2dab5078ad81f3b3c02fc995ce0a7b556e638d905c20d73d5eeebe81b86a0f57
195 total = 90 GPU + 105 CPU
GPU allowlist = 2, 4, 5
V4-F/test32 access = 0
```

## 启动前真实 smoke

`outer_0_inner_0` 的 B/C/D 三个 lane 均通过完整真实输入加载，但未创建优化器或执行训练：

```text
1269 rows
28 parents
1085 train rows
184 score rows
optimizer steps = 0
status = PASS_THREE_LANE_REAL_INNER_PREOPTIMIZER_SMOKE
```

## 首批真实训练结果

`outer_0_inner_0` 的三个 lane 均已产生 `RESULT.json`：

| lane | status | epochs | optimizer steps | score rows |
|---|---|---:|---:|---:|
| B_TARGET_NO_CONTACT | PASS_OPEN_BASE_SPLIT_COMPLETE | 8 | 544 | 184 |
| C_SPLIT_MARGINAL | PASS_OPEN_BASE_SPLIT_COMPLETE | 8 | 544 | 184 |
| D_SPLIT_PAIR | PASS_OPEN_BASE_SPLIT_COMPLETE | 8 | 544 | 184 |

调度器已继续提交 `outer_0_inner_1` 的三路任务。

## 保留的 fail-closed 恢复链

### V1

```text
FAIL: split_parent_exact_closure
```

原因：inner split 只包含 outer-train parents，但命令向冻结 trainer 传入了全 1507 条、31 parents 的训练表。

### V1.1

```text
FAIL: contact_candidate_not_in_training
```

训练 TSV 已按 split 过滤，但 marginal/pair contact targets 仍为全 1507 条。

### V1.2 pre-optimizer smoke

```text
FAIL: graph_candidate_exact_closure
```

训练表与 marginal/pair 已同步，但 label-free monomer graph manifest 仍为全 1507 条。

### V1.2.1 最小恢复

对每个冻结 split 同步：

```text
training candidates
marginal contact candidates
pair contact candidates
label-free graph manifest candidates
```

Graph NPZ 的原始特征数值未变，只将 manifest/receipt 限制为冻结 `train ∪ score` 候选；未修改 trainer、split 成员、标签数值、lane weight、模型、损失或超参数。

## 本地证据

```text
remote_evidence_v1_2_1_launch_v2/
```

该目录包含 V1/V1.1 终态和日志、V1.2 smoke failure、V1.2.1 smoke PASS、launch receipt、首批三个 `RESULT.json` 及 `SHA256SUMS`。

证据边界仍为：独立 8X6B/9E6Y computational Docking geometry surrogate；不是结合概率、Kd、实验阻断、Docking Gold 或提交证据。
