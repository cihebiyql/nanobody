# V2.5 ORTHO strict cross-lane meta evaluator V1.1

V1.1 不修改冻结契约、V1.3 的 301-job 训练图或旧 V1 包。它仅修复评估执行层的契约闭合问题，继续绑定：

```text
0329a4749d9874f3bef7bda30d744d57b85b626783df9dc33a7fd931f3f75eb2
```

## 相对 V1 的修复

1. outer/inner manifest 显式执行 whole-parent isolation gate。
2. SLSQP 除 success/约束/目标值外，增加 projected-KKT residual gate；失败精确回退 M2。
3. parent-macro 完整输出 MAE、RMSE、within-parent Spearman。
4. 原始神经预测 exact-min 容差严格使用冻结的 `1e-12`。
5. outer prediction 和所有 fold/meta 参数先写入 PRETRUTH artifact，并生成独立 hash receipt；之后才访问 outer truth 字段。
6. watcher 任一上游或 evaluator 错误都会原子写入 `FAILED_CLOSED`，不再遗留伪 RUNNING/WAITING 状态。
7. 输出冻结契约要求的 B、E_DETACHED、E_SHARED standalone diagnostics，以及 M2+C2、无 contact 两个 stack ablation。
8. 任何 formal promotion gate 失败都会发布显式的 `SELECTED_PRODUCTION_PREDICTIONS.tsv`，其内容来自 exact M2 fallback；outer primary feature 缺失也强制此 fallback。

哈希或身份篡改仍然 fail-closed，不会被“feature fallback”掩盖。

V4-F/test32 access count 固定为 0；证据边界仍仅为双受体计算 Docking 几何 surrogate。
