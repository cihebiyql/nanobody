#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
TABLE=$ROOT/prepared/canonical10644_multimodal_v1/canonical10644_multimodal_open_v1.tsv
TABLE_SHA=5c46c393e5bf7c26e6089d318b88410f170a6c8556ae4910afd63f552fcdc8f6
RECEIPT=$ROOT/prepared/canonical10644_multimodal_v1/canonical10644_multimodal_materialization_v1.receipt.json
RECEIPT_SHA=fe21802df89437032b1aa949a0e47078aeb317df277cf511e8415c35d88307cc
CACHE=/data1/qlyu/projects/pvrig_v29_expanded_training_v2_9_20260720/runtime/all13322_esm2_650m_embeddings_v1
OUT=$ROOT/training/canonical10644_multimodal_v1
STATUS=$ROOT/status/TRAINING_TERMINAL.json

sha256sum -c <<EOF
$TABLE_SHA  $TABLE
$RECEIPT_SHA  $RECEIPT
5745937c935f3467aa9b956c464a36e63314ae44d8b2f4b85bf9da1ead2d98c2  $ROOT/src/run_full10644_multimodal_fusion_v1.py
EOF

exec env PYTHONUNBUFFERED=1 OMP_NUM_THREADS=16 MKL_NUM_THREADS=16 \
  OPENBLAS_NUM_THREADS=16 NUMEXPR_NUM_THREADS=16 \
  "$PY" "$ROOT/src/run_full10644_multimodal_fusion_v1.py" \
    --multimodal-tsv "$TABLE" \
    --expected-multimodal-sha256 "$TABLE_SHA" \
    --materialization-receipt "$RECEIPT" \
    --expected-materialization-receipt-sha256 "$RECEIPT_SHA" \
    --esm2-650m-cache "$CACHE" \
    --output-dir "$OUT" \
    --folds 5 \
    --seed 193 \
    --full-stage0-prediction "43=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/training/stage0_sequence_v2_10_3seed_v1/seed_43/OPEN_SCORE_PREDICTIONS.tsv" \
    --full-stage0-prediction "97=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/training/stage0_sequence_v2_10_3seed_v1/seed_97/OPEN_SCORE_PREDICTIONS.tsv" \
    --full-stage0-prediction "193=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/training/stage0_sequence_v2_10_3seed_v1/seed_193/OPEN_SCORE_PREDICTIONS.tsv"
