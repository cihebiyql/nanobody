#!/usr/bin/env bash
set -Eeuo pipefail
: "${REMOTE_ROOT:?REMOTE_ROOT is required}"
: "${FULL_JOB_ID:?FULL_JOB_ID is required}"
: "${LOCAL_ROOT:?LOCAL_ROOT is required}"
NODE1_TARGET=${NODE1_TARGET:-/data1/qlyu/projects/pvrig_prestructure50k_nbb2_v1_20260722}
POLL_SECONDS=${POLL_SECONDS:-60}
if [[ "$REMOTE_ROOT" == '\$HOME/'* ]]; then
  remote_home=$(ssh bxcpu 'printf %s "$HOME"')
  REMOTE_ROOT="$remote_home/${REMOTE_ROOT#\$HOME/}"
fi
mkdir -p "$LOCAL_ROOT" "$LOCAL_ROOT/state"

remote="$REMOTE_ROOT/prestructure50k_v1/archives_${FULL_JOB_ID}"
while true; do
  local_ack=0
  for node in $(seq 0 7); do
    id=$(printf '%03d' "$node")
    ready="$LOCAL_ROOT/node_${id}.READY.json"
    archive="$LOCAL_ROOT/node_${id}.tar.gz"
    if [[ -s "$LOCAL_ROOT/state/node_${id}.LOCAL_ACK" ]]; then
      local_ack=$((local_ack + 1))
      continue
    fi
    if ! ssh bxcpu "test -s '$remote/node_${id}.READY.json'"; then continue; fi
    if [[ ! -s "$archive" ]]; then
      scp "bxcpu:$remote/node_${id}.READY.json" "$ready.partial"
      scp "bxcpu:$remote/node_${id}.sha256" "$LOCAL_ROOT/node_${id}.sha256.partial"
      scp "bxcpu:$remote/node_${id}.tar.gz" "$archive.partial"
      mv "$ready.partial" "$ready"
      mv "$LOCAL_ROOT/node_${id}.sha256.partial" "$LOCAL_ROOT/node_${id}.sha256"
      mv "$archive.partial" "$archive"
    fi
    (cd "$LOCAL_ROOT" && sha256sum -c "node_${id}.sha256")
    date -Is > "$LOCAL_ROOT/state/node_${id}.LOCAL_ACK"
    local_ack=$((local_ack + 1))
  done
  [[ "$local_ack" -eq 8 ]] && break
  sleep "$POLL_SECONDS"
done
date -Is > "$LOCAL_ROOT/LOCAL_TRANSFER_COMPLETE"

for node in $(seq 0 7); do
  id=$(printf '%03d' "$node")
  ready="$LOCAL_ROOT/node_${id}.READY.json"
  archive="$LOCAL_ROOT/node_${id}.tar.gz"
  while true; do
    [[ -s "$LOCAL_ROOT/state/node_${id}.NODE1_ACK" ]] && break
    if timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=10 node1 \
      "mkdir -p '$NODE1_TARGET'" >/dev/null 2>&1; then
      if rsync -a --partial "$ready" "$LOCAL_ROOT/node_${id}.sha256" "$archive" \
          "node1:$NODE1_TARGET/" && \
         ssh node1 "cd '$NODE1_TARGET' && sha256sum -c 'node_${id}.sha256'"; then
        date -Is > "$LOCAL_ROOT/state/node_${id}.NODE1_ACK"
        break
      fi
    fi
    sleep 300
  done
done
date -Is > "$LOCAL_ROOT/TRANSFER_COMPLETE"
