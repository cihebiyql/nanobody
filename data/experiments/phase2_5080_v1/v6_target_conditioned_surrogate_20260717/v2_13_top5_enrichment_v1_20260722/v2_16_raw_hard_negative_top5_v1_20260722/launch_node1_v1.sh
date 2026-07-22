#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
PKG=$ROOT/v2_16_raw_hard_negative_top5_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
OUT=$ROOT/training/v216_raw_hard_negative_seed43_l1
RAW=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/prepared/canonical10644_multimodal_v1/canonical10644_multimodal_open_v1.tsv
ASSIGN=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared/candidate_fold_assignment.tsv
LEGACY=$ROOT/inputs/TRAIN_INNER_OOF_PREDICTIONS.tsv
L1=$ROOT/training/phase_a_seed43/L1/OOF_AGGREGATE/TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv
(cd "$PKG" && sha256sum -c SHA256SUMS_IMPLEMENTATION_V1)
test ! -e "$OUT"
printf '{"status":"RUNNING_V2_16_RAW_HARD_NEGATIVE_OOF","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$ROOT/status/V2_16_LIVE_STATUS.json"
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8 \
"$PY" "$PKG/src/run_v216_raw_hard_negative_top5_oof_v1.py" --contract "$PKG/CONTRACT_V1.json" --raw-multimodal "$RAW" --assignment "$ASSIGN" --legacy-oof "$LEGACY" --l1-oof "$L1" --output-dir "$OUT" > "$ROOT/status/V2_16_PRODUCTION.log" 2>&1
cp "$OUT/RUN_RECEIPT.json" "$ROOT/status/V2_16_TERMINAL.json"
