#!/usr/bin/env bash
set -euo pipefail

PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
ROOT=/data1/qlyu/projects/pvrig_v2_7_100k_multi_model_early_enrichment_v1_20260719
OUTPUT=/data1/qlyu/projects/pvrig_v2_7_sequence_stage0_open_inner_runtime_v1_2_20260719
DATA=/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718
CACHE=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/runtime
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8
export OPENBLAS_NUM_THREADS=8

test ! -e "$OUTPUT"
"$PYTHON" -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v | tee "$ROOT/TEST_RESULTS.log"
"$PYTHON" "$ROOT/src/run_sequence_stage0_open_inner_v1.py" \
  --training-tsv "$DATA/inputs/split_training/outer_0_inner_0.tsv" \
  --expected-training-tsv-sha256 5abacbe69e85a5f6e3a13d6af23ae7e2b2903d59554dbce46e14ea165acc4d21 \
  --split-manifest "$DATA/plan/trainer_splits/outer_0_inner_0.json" \
  --esm2-650m-cache "$CACHE/full1507_esm2_650m_embeddings_v1" \
  --esm2-3b-cache "$CACHE/full1507_esm2_3b_embeddings_v1" \
  --output-dir "$OUTPUT" \
  --seed 43
