#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
STATUS=$ROOT/status
OUT=$ROOT/training/phase_b_multiseed
mkdir -p "$STATUS"
while true; do
  running=0
  if [[ -f "$STATUS/PHASE_B_SUPERVISOR.pid" ]]; then
    pid=$(cat "$STATUS/PHASE_B_SUPERVISOR.pid"); kill -0 "$pid" 2>/dev/null && running=1 || true
  fi
  cells=$(find "$OUT" -mindepth 4 -maxdepth 4 -name RESULT.json 2>/dev/null | wc -l)
  aggregates=$(find "$OUT" -name OOF_RECEIPT.json 2>/dev/null | wc -l)
  terminal=false; [[ -f "$STATUS/PHASE_B_TERMINAL.json" ]] && terminal=true
  gpu=$(nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits | awk -F', ' '$1==3||$1==4||$1==5{printf "%s:%s:%s:%s;",$1,$2,$3,$4}')
  printf '{"timestamp":"%s","supervisor_running":%s,"completed_cells":%s,"completed_seed_aggregates":%s,"terminal":%s,"gpu":"%s"}\n' \
    "$(date --iso-8601=seconds)" "$running" "$cells" "$aggregates" "$terminal" "$gpu" > "$STATUS/PHASE_B_MONITOR.json.tmp"
  mv "$STATUS/PHASE_B_MONITOR.json.tmp" "$STATUS/PHASE_B_MONITOR.json"
  [[ "$terminal" == true || "$running" -eq 0 ]] && exit 0
  sleep 60
done
