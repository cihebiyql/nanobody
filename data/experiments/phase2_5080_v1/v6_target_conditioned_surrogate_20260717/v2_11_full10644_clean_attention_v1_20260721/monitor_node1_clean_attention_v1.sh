#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722
STATUS=$ROOT/status
OUT=$ROOT/training/4seed_v1
SUPERVISOR_PID_FILE=$STATUS/SUPERVISOR.pid

mkdir -p "$STATUS"
while true; do
  now=$(date --iso-8601=seconds)
  supervisor_pid=$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)
  supervisor_running=false
  [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null && supervisor_running=true
  seed_results=$(find "$OUT" -mindepth 2 -maxdepth 2 -name RESULT.json 2>/dev/null | wc -l)
  seed_histories=$(find "$OUT" -mindepth 2 -maxdepth 2 -name epoch_history.json 2>/dev/null | wc -l)
  terminal=false
  [[ -f "$STATUS/TERMINAL.json" ]] && terminal=true
  gpu_csv=$(nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits | awk -F', ' '$1==3||$1==4||$1==5||$1==6{printf "%s:%s:%s:%s;",$1,$2,$3,$4}')
  cat > "$STATUS/LIVE_STATUS.json.tmp" <<EOF
{"timestamp":"$now","supervisor_pid":"$supervisor_pid","supervisor_running":$supervisor_running,"seed_results":$seed_results,"seed_histories":$seed_histories,"terminal_receipt":$terminal,"gpu_index_used_free_util":"$gpu_csv"}
EOF
  mv "$STATUS/LIVE_STATUS.json.tmp" "$STATUS/LIVE_STATUS.json"
  if [[ "$terminal" == true || "$supervisor_running" == false ]]; then exit 0; fi
  sleep 60
done
