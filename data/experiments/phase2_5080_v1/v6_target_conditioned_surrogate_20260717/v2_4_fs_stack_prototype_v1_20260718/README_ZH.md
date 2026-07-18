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

## 输入合同

特征 TSV 必须包含：

```text
candidate_id
teacher_source
parent_framework_cluster
outer_fold
R_8X6B
R_9E6Y
M2_R8
M2_R9
neural_R8
neural_R9
contact_score_R8
contact_score_R9
feature_outer_fold
base_training_parent_set_sha256
base_model_receipt_sha256
```

fold provenance JSON 必须同时封闭：

1. stack outer fold 的 meta-training parent 与 score parent 完全分离；
2. 每条 compact feature 对应的 base model training-parent 集合；
3. 当前候选 parent 不得出现在产生其 compact feature 的 base-training parent 集合中；
4. parent 集合使用排序、去重、逐行换行后的 SHA256；
5. 行内 fold、parent-set digest 和 receipt 必须与 manifest 完全一致。

## 文件

```text
src/fit_shared_nonnegative_stack_v1.py
tests/test_fit_shared_nonnegative_stack_v1.py
feature_contract/
split_contract/
```

`feature_contract/` 冻结并验证 receptor-specific compact inner-OOF 的六特征输入及 base/scaler/meta 三层 parent provenance；它不依赖尚未完成的模型训练。

`split_contract/` 沿用训练表已有 outer fold，生成 deterministic whole-parent outer development/inner OOF manifests，并强制 31-parent closure。

运行测试：

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python -m unittest -v \
  experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/\
v2_4_fs_stack_prototype_v1_20260718/tests/test_fit_shared_nonnegative_stack_v1.py
```

命令行原型：

```bash
python src/fit_shared_nonnegative_stack_v1.py \
  --fit-tsv nested_meta_train_features.tsv \
  --score-tsv outer_test_features.tsv \
  --provenance-json fold_provenance.json \
  --outer-fold 0 \
  --output-dir output/fold_0
```

输出：

```text
model.json
outer_test_predictions.tsv
receipt.json
```

## 下一步数据要求

要在正式 V2.4 上使用该原型，新的 base branches 必须重新导出 receptor-specific nested OOF compact features：

1. M2：`M2_R8`、`M2_R9`；
2. neural：`neural_R8`、`neural_R9`；
3. contact：每个受体严格一个预注册标量；
4. 每条 feature 必须绑定其 base-training parent set 和 receipt；
5. outer-test 的 base features 必须只由 outer-train parents 训练得到。

在这些数据生成前，本目录只证明拟合器、权重、exact-min 和 provenance gate 的实现，不代表 V2.4 已获得真实效果。

## 证据边界

输出仅表示：

```text
independent 8X6B/9E6Y docking geometry surrogate
```

不表示：

```text
PVRIG 结合概率
Kd
实验阻断概率
Docking Gold
```
