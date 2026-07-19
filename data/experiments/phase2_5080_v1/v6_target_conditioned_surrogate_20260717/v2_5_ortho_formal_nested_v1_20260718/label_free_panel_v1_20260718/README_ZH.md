# V2.5 open1507 label-free replay panel

本工具从冻结的 open1507 source 表中只提取：

```text
candidate_id
sequence
sequence_sha256
parent_framework_cluster
outer_fold
```

输出严格只有这五列，不保留任何 Docking teacher、contact label、M2/C2 feature 或实验字段。
它仅用于 V2.5 outer-refit checkpoint 的 label-free contact 重放。

校验包括 1,507 candidates、31 whole-parent clusters、五个 outer folds、sequence SHA256、
parent 不跨 fold、source hash 和 V4-F/test32 防火墙。
