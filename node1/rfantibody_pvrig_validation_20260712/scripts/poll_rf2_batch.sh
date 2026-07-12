#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST=${REMOTE_HOST:-node1}
RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
BATCH_ROOT=${BATCH_ROOT:-$RUN_ROOT/rf2/batch_10recycle_blind}

ssh.exe "$REMOTE_HOST" "BATCH_ROOT='$BATCH_ROOT' bash -s" <<'REMOTE'
set -euo pipefail
echo "time=$(date -Is) loadavg=$(cat /proc/loadavg)"
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
for shard in "$BATCH_ROOT"/shards/gpu_*; do
  [[ -d "$shard" ]] || continue
  name=$(basename "$shard")
  input_count=$(find "$shard/input" -maxdepth 1 -type l -name '*.pdb' 2>/dev/null | wc -l)
  output_count=$(find "$shard/output" -maxdepth 1 -type f -name '*_best.pdb' 2>/dev/null | wc -l)
  status=NOT_STARTED
  if [[ -s "$shard/rf2.pid" ]]; then
    pid=$(cat "$shard/rf2.pid")
    if kill -0 "$pid" 2>/dev/null; then
      status="RUNNING pid=$pid"
    elif [[ -s "$shard/rf2.exit_code" ]]; then
      status="EXITED rc=$(cat "$shard/rf2.exit_code")"
    else
      status="EXITED_NO_CODE pid=$pid"
    fi
  fi
  echo "$name status=$status inputs=$input_count outputs=$output_count"
  [[ -f "$shard/logs/rf2.log" ]] && tail -n 2 "$shard/logs/rf2.log" | sed "s/^/$name log: /"
done
REMOTE

