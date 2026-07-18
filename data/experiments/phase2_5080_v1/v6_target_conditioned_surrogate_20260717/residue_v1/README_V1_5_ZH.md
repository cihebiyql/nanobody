# residue_v1 V1.5：修复 formal promotion evidence 版本标签

V1.5 是 V1.4 的最小预生产修正版。V1.4 的 trainer、collector 和 freeze 字节均保持不变。

## 修复原因

V1.4 collector 的 schema、输出文件名和 freeze 已升级到 V1.4，但 promotion status
仍错误沿用：

```text
PROMOTE_RESIDUE_V1_3_OVER_M2
DO_NOT_PROMOTE_RESIDUE_V1_3
```

这不会改变数值计算，却会让正式 promotion evidence 的版本身份错误。V1.4 因此被标记为
`SUPERSEDED_PREPRODUCTION`。

## V1.5 唯一逻辑边界

训练、bootstrap、promotion gate、governance 和 collector matrix 均不改变。V1.5 只修正版本化证据：

```text
collector schema: pvrig_v6_residue_v1_5_oof_collector
trainer schema:   pvrig_v6_nested_residue_surrogate_v1_5
positive status:  PROMOTE_RESIDUE_V1_5_OVER_M2
negative status:  DO_NOT_PROMOTE_RESIDUE_V1_5
OOF output:       residue_v1_5_nested_oof_predictions.tsv
freeze schema:    pvrig_v6_residue_v1_5_implementation_freeze
```

原 V1.4 collector matrix 原样复用，canonical SHA256 仍为：

```text
6d0f3cbcc155564f0ba9e4dadd8d646405bc31072e4e3ab25b11316edb4d2116
```

其中 repetitions=1000、seed=20260718。新增测试分别覆盖 promotion gate 通过和不通过，
并精确断言 V1.5 positive/negative status，防止旧版本标签再次泄漏。

## 入口

```text
src/train_nested_residue_surrogate_v1_5.py
src/collect_residue_oof_v1_5.py
IMPLEMENTATION_FREEZE_V1_5.json
RESIDUE_V1_5_CONTRACT.json
```

当前仅完成本地 CPU 契约验证，未启动远程训练或 collector 生产运行。
