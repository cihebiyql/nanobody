# V2.4 role-separated compact evidence contract

## Canonical V2

V1 已因 inner base feature 与 meta-fit receipt 形成循环而标记 superseded。当前 canonical schema/validator：

```text
schema/receptor_compact_evidence_schema_v2.json
src/validate_receptor_compact_evidence_v2.py
```

三个角色严格互斥：

```text
INNER_OOF_BASE_FEATURE
OUTER_TEST_BASE_FEATURE
OUTER_TEST_META_PREDICTION
```

前两个角色只携带六个 receptor-specific compact features，不允许出现 meta receipt：

```text
M2_R8 / neural_R8 / contact_score_R8
M2_R9 / neural_R9 / contact_score_R9
```

第三个角色只携带双受体 meta prediction、exact-min dual 和 meta receipt，不重复携带六个 base features。

## Component provenance

M2、neural、contact 分别绑定：

- component receipt；
- artifact/checkpoint path；
- training-parent 完整列表及 SHA256；
- outer/inner fold。

每个 component training-parent digest 必须严格等于对应 split manifest 行的 train-parent digest，candidate parent 必须被排除。

neural 与 contact 可以共享 checkpoint/receipt；如果共享，则 artifact path 和 training-parent digest 必须完全一致。contact 仍必须独立绑定冻结公式 receipt：

```text
../contact_contract/contact_score_formula_v1.json
```

## Meta proof closure

`OUTER_TEST_META_PREDICTION` 的 meta receipt 必须额外绑定：

- 实际用于 fit 的 `INNER_OOF_BASE_FEATURE` evidence path + SHA256；
- 该文件实际观察到的 parent closure；
- closure 必须等于 outer-train parent set；
- scaling-fit parent set 必须等于同一 outer-train set；
- 固定 scaling、ridge、condition ceiling、5 参数和非负共享斜率合同。

这样不能只提交一个 meta parent list 来声称 OOF fit；validator 会重新读取 inner-OOF evidence 并核对 role、outer fold、candidate uniqueness 和 parent closure。

## 禁止

- V1 dual-only 或 V1 meta-cyclic schema；
- in-sample component/meta parent；
- component parent set 与 split train 不一致；
- V4-F source/path；
- 未冻结或改权的 contact formula；
- truth/prediction dual 不是 float64 exact minimum。

V1 文件保留作历史审计，详见 `SUPERSEDED_V1.md`，不得用于新 base trainer。
