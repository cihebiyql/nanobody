# V2.4 五参数非负共享斜率 FS stack 原型

## 结论

本目录实现一个**独立、未训练到正式数据、fail-closed** 的 V2.4 原型：

```text
pred_R8 = intercept_R8
        + beta_M2      * M2_R8
        + beta_neural  * neural_R8
        + beta_contact * contact_score_R8

pred_R9 = intercept_R9
        + beta_M2      * M2_R9
        + beta_neural  * neural_R9
        + beta_contact * contact_score_R9

beta_M2, beta_neural, beta_contact >= 0
R_dual = exact min(pred_R8, pred_R9)
```

自由参数严格为 5 个：两个受体截距，加三个跨受体共享的非负斜率。

训练权重冻结为：

```text
0.5 / teacher source
-> source 内 parent 等权
-> parent 内 candidate 等权
```

## 当前 V2.3 产物审计

Node1 根目录：

```text
/data1/qlyu/projects/pvrig_v6_residue_v2_3_four_lane_oof_v1_20260718
```

2026-07-18 实测四条 lane 的 collector 均完成 1507 行 OOF，但全部为
`DO_NOT_PROMOTE_RESIDUE_V2`：

| lane | OOF SHA256 |
|---|---|
| A_DOMAIN | `f8abef7fd3b1f1c5d5f74fd02b7ac962b6e1426040fd18b669f6d16c21d12527` |
| B_VHH3D | `3ca20570948b44ac9e0267ad45c99ec6071c70cbc221ee711d9425335196c7e4` |
| C_PATCH | `4018f6bbc94dcc6cd5498dc96bdd13aa20121ce3a338ac1898d6c894a09aff04` |
| D_FULL_PAIR | `253f924f994b0ff0a3a72a8460f812d029d06c5831386c219411dedd0413ccd3` |

现有 V2.3 OOF schema 只有：

```text
candidate_id
teacher_source
parent_framework_cluster
outer_fold
R_dual_min
m2_prediction
residue_prediction
```

它**没有** V2.4 五参数模型需要的：

```text
M2_R8 / M2_R9
neural_R8 / neural_R9
contact_score_R8 / contact_score_R9
```

因此本原型会明确拒绝 V2.3 dual-only OOF。不能从一个已经取过 `min` 的标量反推出两个受体通道，也不能把 V2.3 的 residue prediction 冒充 contact 分量。

本地当前只有 V2.3 collector 代码和测试，没有同步后的正式 OOF 数据文件；正式产物仍在 Node1 上。

机器可读审计：

```text
V2_3_OOF_INPUT_COMPATIBILITY_AUDIT.json
```

## Canonical V2.4 contracts

Verifier S0/S1 后，V1 prototype 文件仅保留作历史审计；canonical 实现为：

```text
src/fit_shared_nonnegative_stack_v2.py
feature_contract/src/validate_receptor_compact_evidence_v2.py
split_contract/src/build_whole_parent_nested_splits_v3.py
contact_contract/contact_score_formula_v1.json
```

### 生命周期角色

```text
INNER_OOF_BASE_FEATURE
OUTER_TEST_BASE_FEATURE
OUTER_TEST_META_PREDICTION
```

base-feature 角色没有 meta receipt；meta prediction receipt 必须反向绑定实际用于 fit 的 INNER_OOF evidence path、SHA256 和完整 outer-train parent closure。

### 六个 compact features

```text
M2_R8 / neural_R8 / contact_score_R8
M2_R9 / neural_R9 / contact_score_R9
```

M2、neural、contact 分别绑定 component receipt 和 training parents，且 training-parent digest 必须严格匹配 canonical split manifest。neural/contact 可以共享 checkpoint，但 contact 必须额外绑定冻结公式 receipt。

### Contact formula

```text
contact_score_Rr
= 0.5 * hotspot_contact_mass_Rr
+ 0.5 * interface_specificity_Rr
```

权重预注册、双受体共享，不查看 outer results 调整。

### Meta 数值合同

仍严格为 5 个可训练参数，并冻结：

```text
source -> parent -> candidate weights
shared-receptor weighted z-score scaling fit on meta-train only
ridge alpha = 1e-3（只惩罚三个共享斜率）
condition-number ceiling = 1e6
minimum feature scale = 1e-8
三个共享斜率非负
R_dual = exact min(R8, R9)
```

### Canonical split

```text
split_contract/prepared/
whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4/
```

基于当前 V2.4 labels，31-parent closure；inner parent counts 每 fold 相差不超过 1。旧 split V1/V2 及 pre-V2.4-label 产物均非 canonical。

## 当前状态边界

这些实现冻结 schema、provenance、split、contact formula 和数值门控，但尚未伪造尚未完成的 receptor-specific base predictions，也不代表 V2.4 已获得正式模型效果。

## 证据边界

输出仅表示：

```text
independent 8X6B/9E6Y docking geometry surrogate
```

不表示 PVRIG 结合概率、Kd、实验阻断概率或 Docking Gold。
