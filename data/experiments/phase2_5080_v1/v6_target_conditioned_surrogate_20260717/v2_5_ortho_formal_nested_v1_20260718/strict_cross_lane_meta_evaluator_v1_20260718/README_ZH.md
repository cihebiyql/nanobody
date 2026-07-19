# V2.5 ORTHO strict cross-lane meta evaluator

该执行器绑定冻结契约：

```text
0329a4749d9874f3bef7bda30d744d57b85b626783df9dc33a7fd931f3f75eb2
```

它不修改 V1.3 的 301-job 图，只在该图的 `TERMINAL.json=PASS`、301 jobs 闭合且最终 collector PASS 后运行。

## 实际计算

每个 outer parent fold：

1. 读取冻结的 E_SHARED inner H 选择。
2. 从 selected-H 的五个 inner job 中读取并 hash 校验原始 TSV，重建 E_SHARED scalar/contact2D inner OOF。
3. 使用冻结 126D 特征和 whole-parent inner manifests 重算 M2 alpha=10。
4. 使用 coarse-pose 32D fold-local scaler/PCA8/Ridge 重算 C2，并要求 alpha 与冻结选择一致。
5. contact median/IQR 仅在 outer-train inner-OOF 上拟合。
6. 拟合冻结的 M2-anchor constrained Huber meta。
7. 从 E_SHARED 三个 outer seed 的不可变 TSV 重建 scalar/contact 均值。
8. 重算 outer M2/C2，并要求 C2 与既有 frozen outer OOF 数值闭合。
9. 先写无 truth 的 outer prediction artifact，再读取 truth 计算正式 gate。

任一哈希、candidate、parent、fold、seed、selected-H、C2 alpha、exact-min 或 M2 reproduction 不闭合，执行器立即 fail-closed。

## 正式输出

```text
OUTER_PREDICTIONS_PRETRUTH.tsv
FORMAL_OUTER_OOF_PREDICTIONS.tsv
FORMAL_PARAMETERS.json
FORMAL_METRICS.json
FORMAL_EXECUTION_RECEIPT.json
```

任一 promotion gate 失败时结论为：

```text
DO_NOT_PROMOTE_EXACT_M2_FALLBACK
```

## Watcher

`watch_terminal_then_evaluate_v1.py` 仅轮询 V1.3 `TERMINAL.json` 和 final receipt。它先验证 `PACKAGE_MANIFEST.json` 的所有文件哈希，然后一次性启动 evaluator。

证据边界：仅为双受体计算 Docking 几何 surrogate，不是结合、Kd、实验阻断、Docking Gold 或提交真值；V4-F/test32 保持 sealed。
