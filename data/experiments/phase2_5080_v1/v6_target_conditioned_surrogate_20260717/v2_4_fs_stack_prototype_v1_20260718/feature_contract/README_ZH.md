# V2.4 receptor-specific compact inner-OOF evidence contract

## 用途

本目录只冻结并验证 V2.4 stack 所需的 compact inner-OOF 证据格式，不训练任何模型。

严格 compact feature 只有六列：

```text
M2_R8
neural_R8
contact_score_R8
M2_R9
neural_R9
contact_score_R9
```

不允许加入 gap、dual prediction、派生差值或额外 contact 汇总作为第七个特征。

## 每行必须封闭的证据

除六个特征外，每行必须包含：

- candidate、teacher source、parent framework cluster；
- outer fold 和 inner fold；
- 真值 `R_8X6B`、`R_9E6Y`、`R_dual_min`；
- base-training parent set digest、receipt 和 artifact path；
- scaler-fit parent set digest、receipt 和 artifact path；
- meta-fit parent set digest、receipt 和 artifact path。

`R_dual_min` 必须与 `numpy.minimum(R_8X6B, R_9E6Y)` 的 float64 字节完全一致。

## Fail-closed 条件

validator 会拒绝：

1. 旧 V2.3 dual-only OOF；
2. 少列、多列或列顺序变化；
3. 任一非有限数值或缺失值；
4. candidate parent 出现在 base-training parents；
5. candidate parent 出现在 scaler-fit parents；
6. candidate parent 出现在 meta-fit parents；
7. row/manifest 的 fold、digest、receipt 或 path 不一致；
8. 任意 V4-F source 或 artifact path；
9. 非绝对 artifact path；
10. truth dual 不是双受体真值的 exact minimum。

parent set digest 统一定义为：parent ID 排序、去重、每个 ID 后加换行，再计算 SHA256。

## 文件

```text
schema/receptor_compact_inner_oof_schema_v1.json
src/validate_receptor_compact_inner_oof_v1.py
tests/test_validate_receptor_compact_inner_oof_v1.py
```

运行测试：

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python -m unittest -v \
  experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/\
v2_4_fs_stack_prototype_v1_20260718/feature_contract/tests/\
test_validate_receptor_compact_inner_oof_v1.py
```

验证真实交付：

```bash
python src/validate_receptor_compact_inner_oof_v1.py \
  --evidence-tsv receptor_compact_inner_oof.tsv \
  --provenance-json fold_provenance.json \
  --report-json validation_report.json
```

当前只提供 schema 和 validator；在 receptor-specific base predictions 尚未生成前，不会伪造或填补六个 compact features。
