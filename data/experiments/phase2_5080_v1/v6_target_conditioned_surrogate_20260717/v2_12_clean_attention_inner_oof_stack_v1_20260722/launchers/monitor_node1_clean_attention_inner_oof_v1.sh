#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722
OUT=$ROOT/training/oof_seed43_v1
STATUS=$ROOT/status

mkdir -p "$STATUS"
while true; do
  now=$(date --iso-8601=seconds)
  supervisor_pid=$(cat "$STATUS/SUPERVISOR.pid" 2>/dev/null || true)
  supervisor_running=false
  [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null && supervisor_running=true
  terminal=false; [[ -f "$STATUS/TERMINAL.json" ]] && terminal=true
  fold_results=$(find "$OUT" -mindepth 2 -maxdepth 2 -name RESULT.json 2>/dev/null | wc -l)
  fold_histories=$(find "$OUT" -mindepth 2 -maxdepth 2 -name epoch_history.json 2>/dev/null | wc -l)
  epochs=""
  for fold in 0 1 2 3 4; do
    h="$OUT/fold_${fold}/epoch_history.json"
    if [[ -f "$h" ]]; then n=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("epochs",[])))' "$h"); else n=0; fi
    epochs+="${fold}:${n};"
  done
  gpu_csv=$(nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits | awk -F', ' '$1==3||$1==4||$1==5||$1==6{printf "%s:%s:%s:%s;",$1,$2,$3,$4}')
  load1=$(awk '{print $1}' /proc/loadavg)
  cat > "$STATUS/LIVE_STATUS.json.tmp" <<EOF
{"timestamp":"$now","supervisor_pid":"$supervisor_pid","supervisor_running":$supervisor_running,"fold_results":$fold_results,"fold_histories":$fold_histories,"epochs":"$epochs","terminal_receipt":$terminal,"gpu_index_used_free_util":"$gpu_csv","load1":"$load1"}
EOF
  mv "$STATUS/LIVE_STATUS.json.tmp" "$STATUS/LIVE_STATUS.json"
  if [[ "$terminal" == true || "$supervisor_running" == false ]]; then exit 0; fi
  sleep 60
done
