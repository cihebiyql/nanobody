# PVRIG V4-C 失败与恢复边界

## 结论

V4-C 需要区分三件不同的事：

1. Node1 generic-prior 首次运行发生过工程性 fail-closed；该问题已经用严格相等性验证恢复。
2. Dual128 Docking evaluator 在 Decimal 修正后是 `PASS`，说明计算评价器可以稳定运行。
3. 科学外推和生成授权仍然失败：P2/P3/P4 enrichment 为 `FAIL`，7,087 大库的冻结序列支持为 `0/7087`。

因此，V4-C 和 `dual128_generic_prior.csv` 只能保留为开发证据/弱 binding prior，不能授权对 7,087 候选进行 surrogate exploitation、P2/P3/P4 条件生成或阻断结论。

## 1. Generic-prior 初始工程失败

Node1 远端目录：

- `/data/qlyu/projects/pvrig_v4c_generic_prior_20260715`

初始 scorer 明确失败：

```text
ValueError: Candidate embedding config differs from frozen mean-pooled checkpoint
```

失败日志已同步：

- `experiments/phase2_5080_v1/audits/pvrig_v4_c_failure_boundaries_v1/node1_generic_prior_initial_failure.log`
- SHA-256：`58b3de652c4d06835052cb106d68d22d6ed94741d4e54de52f7eefec7f2aee22`

该失败是正确的 fail-closed 行为：scorer 没有在 embedding config hash 不匹配时继续输出分数。

## 2. 工程恢复方式

根因是 embedding config hash 包含运行路径差异，而不是 checkpoint 权重、序列或固定 PVRIG target embedding 发生变化。恢复时没有关闭校验，也没有修改 checkpoint；先验证新旧固定 target embedding：

```text
max_abs_delta  = 0.0
mean_abs_delta = 0.0
```

之后才生成 checkpoint-compatible manifest：

- `embedding_manifest_v3_checkpoint_compatible.csv`
- SHA-256：`06b16d5725fd14c2c99b13b7dc63a261bd2ac93d697fbbf484041d96ba8079d3`
- recovery status：`PASS_REBOUND_AFTER_EXACT_TARGET_EMBEDDING_MATCH`

修复后 128 条 Dual128 候选全部得到 generic prior：

- `experiments/phase2_5080_v1/prepared/pvrig_v4_c/dual128_generic_prior.csv`
- SHA-256：`82c2b20cc14fa5bfd7d090dc1690abd96ee5d02b8d96ac6e9f755e879e84a09f`
- scoring status：`PASS_PVRIG_FORMAL_CANDIDATES_SCORED`

这说明该工程故障已经恢复，不需要重新跑同一批 generic-prior scoring。

## 3. 仍然成立的科学失败边界

### 3.1 Dual128 evaluator

Decimal 修正后的 evaluator：

- status：`PASS`
- unlockable：`true`
- evidence mode：`production_pose_backed`
- SHA-256：`31684c8f293bf0118251ead9b4e1da5f17d5b2dc8c2f10233c1fa76c1cbf4267`

这只说明 evaluator 与 Dual128 Docking 证据稳定，不说明模型能外推到大库。

### 3.2 P2/P3/P4 enrichment

- status：`FAIL`
- eligible phases：空列表
- SHA-256：`420896c3660b51dee8990602146de20f39f19ce4706d8d5f00aebcd777181418`

因此不能依据 Dual128 的 P2/P3/P4 结果生成下一批 phase-conditioned 序列。

### 3.3 7,087 候选支持域

冻结 support audit：

```text
in_support_count    = 0
in_support_fraction = 0.0
broad_use_gate      = FAIL
```

Dual128 主要覆盖 3 个 scaffold/domain，而比赛候选库覆盖更广 parent/domain。`0/7087` 是域支持失败，不是“模型分数低”。不能通过调低阈值把它改成可部署。

## 4. 对当前路线的约束

- `dual128_generic_prior.csv` 只作 weak generic binding prior/tie-breaker；不是 PVRIG binder 概率、Kd 或 blocker score。
- Dual128 结果继续作为 protocol-transfer 和 evaluator regression 证据。
- 不重跑同版本 V4-C 来事后修改 threshold、split、anchor 或 phase 定义。
- 当前 V4-D FullQC290 是新的同域 direct-docking campaign；它不修饰 V4-C 的历史结论。
- V4-D 可以产生 290 条的新计算几何证据，但其结果仍需与 Full QC、开发性、结构可靠性和多样性分开记录。

## 5. 机器可读记录

- `experiments/phase2_5080_v1/audits/pvrig_v4_c_failure_boundaries_v1/pvrig_v4_c_failure_boundaries.json`
- SHA-256：`2024efcfef0131ae8427a1acab3ac3441ab2781195cef286dc692afa9055a851`
- status：`PASS_FAILURE_BOUNDARIES_RECORDED`

本记录不建立 PVRIG binding、affinity、Kd、competition 或实验 blocking 结论。
