#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722;PKG=$ROOT/v2_17_expanded_union_top5_v1_20260722;PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python;OUT=$ROOT/training/v217_expanded_union_seed43
(cd "$PKG" && sha256sum -c SHA256SUMS_IMPLEMENTATION_V1);test ! -e "$OUT";printf '{"status":"RUNNING_V2_17_EXPANDED_UNION_OOF","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$ROOT/status/V2_17_LIVE_STATUS.json"
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8 "$PY" "$PKG/src/run_v217_expanded_union_top5_oof_v1.py" \
 --contract "$PKG/CONTRACT_V1.json" \
 --raw-multimodal /data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/prepared/canonical10644_multimodal_v1/canonical10644_multimodal_open_v1.tsv \
 --assignment /data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared/candidate_fold_assignment.tsv \
 --legacy-oof "$ROOT/inputs/TRAIN_INNER_OOF_PREDICTIONS.tsv" \
 --l1-oof "$ROOT/training/phase_a_seed43/L1/OOF_AGGREGATE/TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv" \
 --g3-oof "$ROOT/training/v215_raw_multimodal_seed43_l1/V2_15_RAW_MULTIMODAL_TOP5_OOF_PREDICTIONS.tsv" \
 --n1-oof "$ROOT/training/v214_listwise_seed43/N1/OOF_AGGREGATE/V214_N1_TRAIN9849_OOF_PREDICTIONS.tsv" \
 --n2-oof "$ROOT/training/v214_listwise_seed43/N2/OOF_AGGREGATE/V214_N2_TRAIN9849_OOF_PREDICTIONS.tsv" \
 --n3-oof "$ROOT/training/v214_listwise_seed43/N3/OOF_AGGREGATE/V214_N3_TRAIN9849_OOF_PREDICTIONS.tsv" \
 --output-dir "$OUT" > "$ROOT/status/V2_17_PRODUCTION.log" 2>&1
cp "$OUT/RUN_RECEIPT.json" "$ROOT/status/V2_17_TERMINAL.json"
