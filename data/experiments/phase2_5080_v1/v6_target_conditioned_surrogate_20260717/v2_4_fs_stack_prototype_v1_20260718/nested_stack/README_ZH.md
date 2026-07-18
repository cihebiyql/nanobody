# V2.4 strict double whole-parent cross-fit stack

## 目的

本目录只解决二级 5 参数 nonnegative stack 的严格执行问题：二级模型的训练行必须来自 `outer-train` 内部再次 whole-parent OOF 的 base predictions，最终评价行必须来自从未参与该 outer meta 拟合的 `outer-test` parents。

```text
每个 outer fold / 每个 B,C,D lane

5 个 inner whole-parent base train/score
        -> 合并 INNER_OOF_BASE_FEATURE
        -> feature contract V2 验证

outer-train 全量 refit base
        -> OUTER_TEST_BASE_FEATURE
        -> feature contract V2 验证

validated inner OOF base evidence
        -> 5 参数 shared nonnegative stack
        -> score validated outer-test base evidence
        -> OUTER_TEST_META_PREDICTION
        -> feature contract V2 验证
```

禁止流程：

```text
全体 outer-OOF 行 -> 在同一批行 fit meta -> 在同一批行报告 meta 性能
outer-test label -> meta fit / scaling / model selection
A_VHH_ONLY diagnostic contact score -> stack contact feature
V4-F / test32 -> 任何 planning、fit 或评价
```

## 作业数量与资源

stack-eligible lanes：

```text
B_TARGET_NO_CONTACT -> physical GPU 2
C_SPLIT_MARGINAL    -> physical GPU 4
D_SPLIT_PAIR        -> physical GPU 5
```

`A_VHH_ONLY` 被明确排除，因为其 contact 输出是 VHH marginal diagnostic，不是 PVRIG target contact composite；GPU 1 留空或仅用于独立 diagnostic，不进入 stack。

固定规模：

| 作业 | 数量 |
|---|---:|
| inner base GPU jobs | 5 outer x 5 inner x 3 lanes = 75 |
| outer refit GPU jobs | 5 outer x 3 lanes = 15 |
| GPU training total | 90 |
| CPU assemble/validate/fit/materialize | 105 |
| DAG total | 195 |

同一 lane/GPU 同时最多 1 个训练，B/C/D 最多 3 个 GPU jobs 并发。每个训练进程沿用 8 CPU thread 上限。

## 文件

```text
build_strict_nested_crossfit_plan_v1.py
    校验 canonical 1507/31-parent outer+inner manifests；
    物化 25 个 inner + 5 个 outer trainer split JSON；
    生成 DAG；
    汇总已完成 base outputs；
    物化 inner/outer base evidence 和 outer meta evidence。

run_strict_nested_crossfit_graph_v1.py
    --status 只读检查；
    --execute 仅接受 post-calibration frozen、execution_authorized graph，
    并需要显式 authorization token。

prepared/strict_double_crossfit_dryrun_v3/
    当前本地 dry-run DAG；仍由 prefreeze manifest 生成，故不可执行。
```

## 当前状态

当前 graph 状态：

```text
DRY_RUN_PENDING_POSTCALIBRATION_FREEZE_DO_NOT_EXECUTE
```

它证明 split、parent/source/hash closure 和作业依赖可闭合，但不会启动训练。正式运行前必须：

1. 完成 open-only contact-gradient calibration；
2. 生成 post-calibration implementation freeze；
3. deployment manifest 写入冻结的 `lane_outer_extra_argv` 并设置 `production_authorized=true`；
4. 使用该新 manifest 重新生成 graph；
5. 将 planner、runner、feature validator V2、stack fitter V2、canonical inner manifest 与 30 个 trainer split JSON 纳入同一 Node1 bundle hash closure；
6. `--status` 确认 195 jobs pending 且 V4-F access=0；
7. 才能显式执行。

## 证据边界

输出只是 independent 8X6B/9E6Y docking geometry surrogate 的 open-development whole-parent OOF 证据，不代表 binding、Kd、实验阻断、Docking Gold 或提交真值。
