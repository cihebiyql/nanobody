# Stack V1 superseded

`fit_shared_nonnegative_stack_v1.py` 仅验证五参数与非负共享斜率，没有冻结 scaling、ridge 和 condition-number ceiling，不再作为 canonical meta stack。

Canonical 替代：

```text
src/fit_shared_nonnegative_stack_v2.py
```

V2 仍只有 5 个可训练参数，但固定：

```text
shared-receptor weighted z-score scaling
ridge alpha = 1e-3（仅惩罚三个共享斜率）
condition number ceiling = 1e6
minimum feature scale = 1e-8
```
