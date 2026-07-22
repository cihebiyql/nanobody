#!/usr/bin/env bash
set -u
SRC=/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_prestructure50k_multimetric_v1_20260722
DST=/data1/qlyu/projects/pvrig_prestructure50k_multimetric_v1_20260722
while true; do
  if timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=10 node1 "mkdir -p '$DST'" >/dev/null 2>&1 &&      rsync -a --partial --exclude sync_node1_retry.sh --exclude node1_sync.log "$SRC/" "node1:$DST/" &&      ssh node1 "cd '$DST' && sha256sum -c SHA256SUMS"; then
    date -Is > "$SRC/NODE1_SYNC_COMPLETE"
    exit 0
  fi
  printf '%s node1 unavailable; retrying\n' "$(date -Is)" >> "$SRC/node1_sync.log"
  sleep 300
done
