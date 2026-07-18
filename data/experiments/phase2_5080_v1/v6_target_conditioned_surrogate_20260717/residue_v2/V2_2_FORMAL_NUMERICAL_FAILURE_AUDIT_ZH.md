# Residue V2.2 正式运行数值失败审计

## 决定

V2.2 的 Node1 production freeze 和 4/4 smoke 均通过，但 `C_PATCH` 和
`D_FULL_PAIR` 在 formal fold0 中 fail-closed：

```text
FAIL_V2_2_BF16_PAIR_ENTROPY_NONFINITE_DO_NOT_RESUME
```

V2.2 的 partial runtime 不可恢复、不可复用 checkpoint，也不可用于性能比较。
launcher 和尚在运行的 A/B child processes 已一起 SIGTERM，失败目录原样保留。

## 根因证据

`residue_model_v2.py` 的 pair-summary binary entropy 在 BF16 中使用：

```python
clipped = probabilities.clamp(min=1e-6, max=1.0 - 1e-6)
```

BF16 不能表示 `1 - 1e-6`，上界会舍入为 `1.0`。当 pair logit 饱和使
sigmoid 输出 exact `1.0` 时，entropy 中的 `0 * log(0)` 产生 NaN。

Node1 同一 formal C 批次的诊断显示：

- pair logits 全部 finite；
- `pair_summary` 112 个 cell 中 1 个 NaN；
- `residual` 和 `prediction` 各 3 个 NaN；
- `dual` per-candidate loss 8 条中 1 条 NaN；
- 最终在 `source_balanced_component` 触发 `component_loss_nonfinite`。

该路径只存在于使用 target graph/cross-interaction 的 C/D lane，与 A/B 未出现
同样失败一致。该问题不是 contact loss 权重、teacher 标签、阈值或
promotion gate 导致。

## 版本边界

- V2.2 freeze SHA256：
  `2659325b58d2c1e8faeb6f20b71cb63a6216a21ef5803d71886aa100c2eff471`
- V2.2 不回写、不修补。
- 修复只能以 V2.3 technical-numerics supersession 开始。
- 诊断不读取任何 prediction metric，V4-F/test32 access count 仍为 0。

