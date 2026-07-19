# V2.5 正式训练与 strict-meta 终态证据

## 结论

V2.5 的 301 个正式任务和 V1.1 strict cross-lane meta evaluator 均已终态完成，证据闭环验证为：

```text
19 / 19 checks PASS
301 / 301 jobs completed
1,507 candidates
31 parent clusters
5 whole-parent outer folds
V4-F/test32 access = 0
exact-min max absolute error = 0
```

训练和评价流程本身成功，但新融合模型没有通过冻结的晋级门，因此正式决定为：

```text
DO_NOT_PROMOTE_EXACT_M2_FALLBACK
selected production model = M2_FROZEN_ALPHA10
```

这不是运行失败，而是严格评价后的科学失败：新模型有小幅点估计增益，但证据不足以替换 M2。

## 核心指标

| 模型 | Rdual Spearman | MAE | RMSE |
|---|---:|---:|---:|
| M2 frozen | 0.609401 | 0.032359 | 0.042907 |
| M2 + C2 | 0.613786 | 0.032165 | 0.042624 |
| M2 + C2 + E-shared + contact2D | **0.618525** | 0.031890 | 0.042295 |
| M2 + C2 + E-shared, no contact | 0.618492 | **0.031888** | **0.042293** |
| E-shared neural lane alone | 0.567017 | 0.031692 | 0.041329 |
| B clean-attention lane alone | 0.529213 | 0.032276 | 0.042029 |
| E detached lane alone | 0.441888 | 0.034498 | 0.044036 |

相对 M2，primary stack 的变化为：

```text
Spearman +0.009124
MAE      -0.000469
RMSE     -0.000613
```

但冻结晋级条件中以下两项失败：

```text
Rdual_spearman = FAIL
parent_bootstrap = FAIL
```

31-parent paired bootstrap 的 Spearman 改善区间为：

```text
mean = +0.010152
95% CI = [-0.002969, +0.025389]
```

区间下界仍低于 0，因此不能声称稳定超过 M2。仅 20/31 parents 的 Rdual MAE 增量非负。

## Contact 分支的当前证据

Primary contact2D stack 与 no-contact stack 几乎相同：

```text
contact2D Spearman = 0.6185247481
no-contact Spearman = 0.6184917193
差值约 0.000033
```

这说明当前 contact summary 尚未提供可确认的独立增量，后续必须依赖冻结的因果消融、role-isolated 训练和更直接的 coarse-pose/approach-angle 信息，而不是简单增大网络。

## 哈希和防泄漏闭环

验证包括：

- Node1 与本地 13 个同步文件逐文件 SHA256 完全一致；
- PRETRUTH prediction、parameters 和 receipt 哈希闭合；
- FORMAL receipt 中所有 artifact 哈希闭合；
- runtime terminal/result/job-graph 哈希闭合；
- contract 和 evaluator package manifest 哈希闭合；
- 12,056 行正式预测与 PRETRUTH 预测逐键、逐字符串完全一致；
- 每个模型均为 1,507 行，候选集合相同；
- formal truth、formal prediction 和 selected production prediction 的 exact-min 误差均为 0；
- terminal、graph、runtime result、watcher、PRETRUTH receipt、FORMAL receipt 均记录 `v4_f_test32_access_count=0`。

注意：`GRAPH_STATUS.json` 保留了 scheduler 最后一次写入的 `status=RUNNING`，但同一文件为 `completed=301, pending=0, running=0`；权威终态文件 `TERMINAL.json` 为 `status=PASS, returncode=0`。

## 本地证据

```text
VERIFICATION_REPORT.json
verify_formal_terminal_evidence_v1.py
REMOTE_SHA256SUMS.txt
LOCAL_SHA256SUMS_RELATIVE.txt
LOCAL_FILE_INVENTORY.tsv
remote_snapshot/
```

验证命令：

```bash
python3 verify_formal_terminal_evidence_v1.py
```

## 证据边界

这些结果只表示：

```text
open-development whole-parent OOF surrogate
of independent 8X6B/9E6Y computational Docking geometry
```

它们不表示结合、亲和力、实验阻断、Docking Gold、sealed V4-F 证据或最终提交真值。
