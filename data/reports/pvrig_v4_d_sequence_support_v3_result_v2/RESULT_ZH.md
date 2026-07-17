# PVRIG V4-D Sequence Support V3 V2 生产结果

## 结论

本次冻结的 label-free Support V3 V2 生产计算按预注册规则终止为：

```text
FAIL_RESEARCH_RANKING_AND_DIRECT_DOCKING_ROUTING_ONLY
```

这不是程序崩溃。3,000 条需要重新计算的 null 序列、1,000 条 channel-splice、ESM2 cache、三 seed V2.3 contact 特征与全部 gate 均完成；由于 nested-validation 和 deployment coverage 未达冻结门槛，程序返回码为 2，并拒绝发布正式 support table。

## 冻结门结果

- Nested IN_DOMAIN：`0.5884955752`，要求 `>=0.80`，失败。
- 最差 parent：`C0116 = 0.1538461538`，每个 parent 要求 `>=0.60`，失败。
- Deployment IN_DOMAIN：`1733 / 6861 = 0.2525870864`，要求 `>=4117` 且 `>=0.60`，失败。
- CDR composition shuffle：IN_DOMAIN `0/1000`，通过。
- Cross-parent CDR graft：IN_DOMAIN `0/1000`，通过。
- Channel splice：IN_DOMAIN `0/1000`，通过。
- Unseen-parent chimera：NEAR_DOMAIN `10/1000 = 0.01`，通过。

## 边界

- Docking/实验标签路径读取数：`0`。
- V4-F 标签路径读取数：`0`。
- 正式 `candidate7087_sequence_support_v3.csv` 未发布。
- 不允许降低门槛、把 NEAR_DOMAIN 改称 exploitation-supported，或覆盖本次失败结果。
- 当前只能用于 research ranking 与 direct-Docking routing；若要扩大 exploitation coverage，应新增 parent-cluster teacher coverage，或预注册新的 Support V4 表征，而不是事后改 V3 门槛。
