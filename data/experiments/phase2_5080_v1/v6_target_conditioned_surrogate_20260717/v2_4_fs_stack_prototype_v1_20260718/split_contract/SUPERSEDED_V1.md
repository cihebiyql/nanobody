# V1 split contract superseded

`build_whole_parent_nested_splits_v1.py` 及其 seed1931 v1 产物不再是 canonical split。

原因：V1 优先平衡 candidate count，但未限制每个 inner fold 的 parent count；在真实 fold 0 上可出现 `12/4/4/4/4` parent 分配。有效统计单位是 31 个 parent，因此该分配不再用于 base trainer。

Canonical 替代版：

```text
src/build_whole_parent_nested_splits_v3.py
prepared/whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4/
```
