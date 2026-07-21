# V2.11 canonical1358 多模态融合

## 内容

- `src/materialize_canonical_multimodal_v1.py`：开放数据的 126D/C2/ESM2 cache 闭合；
- `src/run_canonical_multimodal_fusion_v1.py`：whole-parent OOF base 和 train-only meta fitting；
- `MULTIMODAL_FUSION_CONTRACT_V1.json`：冻结模型、split、指标和禁止项；
- `PLAN_ZH.md`：执行目的和后续接入顺序。

## Materialize

```bash
PY=experiments/phase2_5080_v1/.venv-phase2-5080/bin/python
ROOT=experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717
V211=$ROOT/v2_11_canonical1358_multimodal_fusion_v1_20260721

$PY $V211/src/materialize_canonical_multimodal_v1.py \
  --teacher $ROOT/v2_10_canonical10644_training_v1_20260721/prepared/primary_D1_canonical10644_teacher.tsv \
  --split-manifest $ROOT/v2_10_canonical10644_training_v1_20260721/prepared/primary_D1_canonical10644_split_manifest.json \
  --structure-v4d experiments/phase2_5080_v1/prepared/pvrig_v4_d_open258_structure_features_v1/open258_structure_features_v1.tsv \
  --structure-v4h experiments/phase2_5080_v1/prepared/pvrig_v4_h_research1320_structure_features_v1/research1320_structure_features_v1.tsv \
  --coarse-pose $ROOT/v2_5_coarse_pose_pilot_v1_20260718/prepared/open1507_v1/open1507_coarse_pose_features_36d.tsv \
  --esm2-650m-cache /path/to/all13322_esm2_650m_cache \
  --output-dir /new/nonexistent/canonical1358_materialized
```

生产执行时应补齐所有 `--expected-*-sha256` 参数。输出目录必须不存在。

## Train and evaluate

```bash
TABLE=/path/canonical1358_materialized/canonical_multimodal_open.tsv
TABLE_SHA=$(sha256sum "$TABLE" | awk '{print $1}')
RECEIPT=/path/canonical1358_materialized/MATERIALIZATION_RECEIPT.json
RECEIPT_SHA=$(sha256sum "$RECEIPT" | awk '{print $1}')

$PY $V211/src/run_canonical_multimodal_fusion_v1.py \
  --multimodal-tsv "$TABLE" \
  --expected-multimodal-sha256 "$TABLE_SHA" \
  --materialization-receipt "$RECEIPT" \
  --expected-materialization-receipt-sha256 "$RECEIPT_SHA" \
  --esm2-650m-cache /path/to/all13322_esm2_650m_cache \
  --output-dir /new/nonexistent/canonical1358_fusion_run \
  --full-stage0-prediction 43=/path/v2_10/seed_43/OPEN_SCORE_PREDICTIONS.tsv \
  --full-stage0-prediction 97=/path/v2_10/seed_97/OPEN_SCORE_PREDICTIONS.tsv \
  --full-stage0-prediction 193=/path/v2_10/seed_193/OPEN_SCORE_PREDICTIONS.tsv
```

如果 full9849 prediction 暂时未提供，runner 仍完成 matched1358 的严格融合，并在 receipt 中记录 `NOT_PROVIDED`。

## 输出

- `TRAIN_INNER_OOF_PREDICTIONS.tsv`；
- `OPEN_DEVELOPMENT_PREDICTIONS.tsv`；
- `METRICS.json`；
- `MODEL_ARTIFACT.pkl`；
- `RUN_RECEIPT.json`；
- `SHA256SUMS`。

## 测试

```bash
T=$V211/tests
PYTHONPATH=$T $PY -m unittest discover -s $T -p 'test_*.py' -v
```

本地系统 `python3` 不包含项目所需的 SciPy/scikit-learn；测试和训练使用 `.venv-phase2-5080`。
