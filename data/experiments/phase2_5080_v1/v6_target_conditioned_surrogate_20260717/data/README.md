# V6 target-conditioned surrogate：训练数据

本目录由 `build_v6_training_dataset.py` 确定性生成。监督目标仅表示独立
8X6B/9E6Y Docking 的连续计算几何，不表示结合、亲和力、竞争实验、真实阻断或
Docking Gold。

## 输入

1. V4-D `OPEN_TRAIN`：226 条 multi-seed 双受体 teacher；
2. V4-H Stage 1 terminal：1,281 条 dual single-seed teacher；
3. V4-H Stage 1 的 39 条技术不完整候选仅进入无监督表；
4. V4-D `OPEN_DEVELOPMENT32` 仅生成 candidate、sequence SHA256 和 parent
   排除集合，其目标不输出。

## 输出

- `v6_supervised1507.tsv`：1,507 条监督记录、31 个 parent；保留序列、来源、
  `source_dataset`、campaign、可靠性权重、`R_8X6B`、`R_9E6Y`、
  `R_dual_min` 和 whole-parent fold。
- `v6_unsupervised_incomplete39.tsv`：39 条技术不完整记录。该表的 schema 不含
  任何 R target 或负标签字段。
- `v6_whole_parent_fold_assignments.tsv`：31 个 parent 的确定性五折分配。
- `V6_DATASET_RECEIPT.json`：输入/输出 SHA256、计数、排除检查和 fold 统计。

可靠性权重固定为：V4-D multi-seed `1.00`，V4-H Stage1 single-seed `0.65`。
权重表达计算 teacher 重复性的差异，不代表生物学置信度。

## 复现

```bash
python3 experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/data/build_v6_training_dataset.py
python3 -m unittest discover \
  -s experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/tests \
  -p 'test_build_v6_training_dataset.py' -v
```

Builder fail-closed 检查：输入计数、字段、candidate 唯一性、序列 SHA256、
`R_dual_min=min(R8,R9)`、Stage1 metadata join、multi/single-seed 状态、31 个
supervised parents，以及训练集合与 `OPEN_DEVELOPMENT32` 的 candidate、sequence、
parent 三重零重叠。
