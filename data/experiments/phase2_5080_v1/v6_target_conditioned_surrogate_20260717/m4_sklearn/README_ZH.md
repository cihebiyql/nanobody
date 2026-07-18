# M4 sklearn 序列–结构融合基线

## 目的

M4 是一条独立于现有 PyTorch M3 训练器的小数据基线：

```text
126 个 VHH 单体结构特征
    → M2 weighted Ridge
pooled ESM sequence embedding
    → outer-train-only PCA
PCA sequence + standardized structure + cross-fitted M2
    → residual Ridge / ExtraTrees / HistGradientBoosting
    → M4 R_dual_min
```

目标只是逼近独立 8X6B/9E6Y Docking 的连续几何量 `R_dual_min`，不表示结合、亲和力、竞争、实验阻断或 Docking Gold。

## 防泄漏合同

- 外层划分直接使用 `v6_supervised1507.tsv` 中冻结的 whole-parent `outer_fold`。
- 外层 test 不参与 PCA 维数、head family 或 head hyperparameter 选择。
- 内层划分是确定性 whole-parent 划分。
- residual head 的 outer-train M2 输入是 cross-fitted prediction，不是 in-sample prediction。
- 内层评估时，inner-train residual 也用更内层的 whole-parent cross-fit M2 生成。
- 输入 TSV、table receipt、embedding receipt、embedding shards、candidate ID 和 sequence SHA256 必须全部闭合。

## 运行

```bash
python m4_sklearn/src/train_m4_sklearn_fusion.py \
  --input data/materialized_v1_1/v6_supervised1507.tsv \
  --table-receipt data/materialized_v1_1/v6_training_table_receipt.json \
  --embeddings /path/to/full1507_embedding_cache \
  --output-dir /path/to/m4_run
```

默认搜索 PCA 8/16/32 维，并在 Ridge、ExtraTrees 和 HistGradientBoosting 中做内层选择。所有比较使用完整 outer OOF prediction，报告 global Spearman、parent-centered Spearman、MAE 和 Top20 recall。

## 主要输出

- `fold_<k>/inner_selection.json`
- `fold_<k>/model.joblib`
- `fold_<k>/predictions.tsv`
- `fold_<k>/terminal.json`
- `oof_predictions.tsv`
- `summary.json`
- `terminal_receipt.json`

