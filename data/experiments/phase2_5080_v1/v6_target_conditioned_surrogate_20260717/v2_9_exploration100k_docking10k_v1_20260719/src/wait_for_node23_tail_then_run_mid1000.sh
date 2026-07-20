#!/usr/bin/env bash
set -euo pipefail
TAIL=/data/qlyu/projects/pvrig_v29_monomers_tail4000_node23_v1_20260720
ROOT=/data/qlyu/projects/pvrig_v29_monomers_mid1000_node23_v1_20260720
PY=/data/qlyu/anaconda3/envs/boltz/bin/python
NBB2=/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2
LOG="$ROOT/logs/wait_and_run.log"

while [[ ! -s "$TAIL/run/status/COMPLETE.json" ]]; do
  printf '%s waiting_for_tail4000_complete\n' "$(date -Is)" >> "$LOG"
  sleep 30
done

printf '%s tail4000_complete_starting_mid1000\n' "$(date -Is)" >> "$LOG"
exec "$PY" "$ROOT/src/run_v29_monomers_v1.py" \
  --manifest "$ROOT/input/node23_mid1000.tsv" \
  --output-root "$ROOT/run" \
  --nbb2 "$NBB2" \
  --expected-count 1000 \
  --gpus 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 \
  --threads-per-worker 1 >> "$LOG" 2>&1
