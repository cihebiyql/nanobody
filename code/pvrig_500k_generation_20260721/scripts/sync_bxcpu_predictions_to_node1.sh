#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE="${SOURCE:?SOURCE is required}"
TARGET="${TARGET:-/data1/qlyu/projects/pvrig_500k_model_predictions_bxcpu_v1_20260721}"
LOG="${LOG:-$SOURCE/node1_sync.log}"

while [[ ! -s "$SOURCE/READY.json" ]]; do sleep 30; done
for attempt in $(seq 1 288); do
  if timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=10 node1 "mkdir -p '$TARGET'" >>"$LOG" 2>&1; then
    if rsync -a --partial --info=stats1 "$SOURCE/" "node1:$TARGET/" >>"$LOG" 2>&1 && \
       ssh -o BatchMode=yes node1 "cd '$TARGET' && sha256sum -c SHA256SUMS" >>"$LOG" 2>&1; then
      date -Is > "$SOURCE/NODE1_SYNC_COMPLETE"
      exit 0
    fi
  fi
  printf '%s attempt=%s node1 unavailable or sync failed\n' "$(date -Is)" "$attempt" >>"$LOG"
  sleep 300
done
exit 1
