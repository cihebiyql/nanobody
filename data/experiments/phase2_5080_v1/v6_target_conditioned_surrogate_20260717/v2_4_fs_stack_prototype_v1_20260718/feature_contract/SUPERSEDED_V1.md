# V1 feature contract superseded

V1 将 inner base-feature evidence 与 meta-fit receipt 放在同一行，形成生命周期循环，不再用于 V2.4。

V2 将证据拆为三个互斥角色：

```text
INNER_OOF_BASE_FEATURE
OUTER_TEST_BASE_FEATURE
OUTER_TEST_META_PREDICTION
```

前两个角色的 exact schema 中不存在 meta receipt。只有第三个角色可以绑定 meta model receipt。

Canonical validator：

```text
src/validate_receptor_compact_evidence_v2.py
```
