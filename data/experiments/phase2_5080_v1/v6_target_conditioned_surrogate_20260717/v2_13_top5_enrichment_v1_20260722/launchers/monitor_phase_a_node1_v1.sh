#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
STATUS=$ROOT/status
OUT=$ROOT/training/phase_a_seed43
mkdir -p "$STATUS"
while true; do
  terminal=false; [[ -f "$STATUS/TERMINAL.json" ]] && terminal=true
  running=0
  if [[ -f "$STATUS/SUPERVISOR.pid" ]]; then
    pid=$(cat "$STATUS/SUPERVISOR.pid"); kill -0 "$pid" 2>/dev/null && running=1 || true
  fi
  folds=$(find "$OUT" -mindepth 3 -maxdepth 3 -name RESULT.json 2>/dev/null | wc -l)
  lanes=$(find "$OUT" -mindepth 3 -maxdepth 3 -name OOF_RECEIPT.json 2>/dev/null | wc -l)
  gpu=$(nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits | awk -F', ' '$1==3||$1==4||$1==5{printf "%s:%s:%s:%s;",$1,$2,$3,$4}')
  printf '{"timestamp":"%s","supervisor_running":%s,"completed_folds":%s,"completed_lanes":%s,"terminal":%s,"gpu":"%s"}\n' \
    "$(date --iso-8601=seconds)" "$running" "$folds" "$lanes" "$terminal" "$gpu" > "$STATUS/LIVE_STATUS.json.tmp"
  mv "$STATUS/LIVE_STATUS.json.tmp" "$STATUS/LIVE_STATUS.json"
  [[ "$terminal" == true || "$running" -eq 0 ]] && exit 0
  sleep 60
done
