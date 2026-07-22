#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_18_pose_aux_crossfit_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
RAW=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/prepared/canonical10644_multimodal_v1/canonical10644_multimodal_open_v1.tsv
STRICT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/inputs/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv
L1=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_a_seed43/L1/OOF_AGGREGATE/TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv
AUX=$ROOT/prepared/V29_TRAIN6872_POSE_AUX_TARGETS.tsv
OUT=$ROOT/training/strict_oof_v1_1
STATUS=$ROOT/status

mkdir -p "$STATUS" "$ROOT/logs" "$ROOT/training"
test ! -e "$OUT"

check() {
  local expected=$1 path=$2
  local observed
  observed=$(sha256sum "$path" | awk '{print $1}')
  [[ "$observed" == "$expected" ]] || { echo "hash_mismatch:$path:$observed:$expected" >&2; exit 4; }
}

check 5c46c393e5bf7c26e6089d318b88410f170a6c8556ae4910afd63f552fcdc8f6 "$RAW"
check 2e0096a04cbedf724553e1ed11f82f768a2db0687e55b4feb0d50f58658da3da "$STRICT"
check d441a47e938a0c490cead10c80e6b71bd1a22abe9e22803ed1af43ec04f60669 "$L1"
check f7a9f1614b7f26c1d4d16c67e02a64fb6814c94b09237a60bbf59a0294f30bd0 "$AUX"
check 91a50f13445f874525bc0a28f58e874cc44aaced4c8167822c58a4c733b65908 "$ROOT/src/run_v218_pose_aux_crossfit_oof_v1_1.py"

printf '{"status":"RUNNING_V2_18_POSE_AUX_STRICT_OOF_V1_1","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/LIVE_STATUS_V1_1.json"
OMP_NUM_THREADS=32 MKL_NUM_THREADS=32 OPENBLAS_NUM_THREADS=32 NUMEXPR_NUM_THREADS=32 \
"$PY" "$ROOT/src/run_v218_pose_aux_crossfit_oof_v1_1.py" \
  --raw "$RAW" \
  --strict-oof "$STRICT" \
  --l1-oof "$L1" \
  --pose-aux "$AUX" \
  --output-dir "$OUT" > "$ROOT/logs/strict_oof_v1_1.log" 2>&1

cp "$OUT/RUN_RECEIPT.json" "$STATUS/TERMINAL_V1_1.json"
