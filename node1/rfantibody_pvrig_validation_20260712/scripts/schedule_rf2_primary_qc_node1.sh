#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_validation_20260712}
MAX_LOAD1=${MAX_LOAD1:-64}
POLL_SECONDS=${POLL_SECONDS:-60}
SCHEDULER_PID=$RUN_ROOT/manifests/rf2_primary_78_qc_scheduler.pid
SCHEDULER_LOG=$RUN_ROOT/logs/rf2_primary_78_qc_scheduler.log

mkdir -p "$RUN_ROOT"/{manifests,logs}
if [[ -s "$SCHEDULER_PID" ]] && kill -0 "$(cat "$SCHEDULER_PID")" 2>/dev/null; then
  echo "Targeted QC scheduler already running pid=$(cat "$SCHEDULER_PID")"
  exit 0
fi

(
  while true; do
    global_running=0
    if [[ -s "$RUN_ROOT/manifests/sequence_qc_fr4_restored.pid" ]] && \
       kill -0 "$(cat "$RUN_ROOT/manifests/sequence_qc_fr4_restored.pid")" 2>/dev/null; then
      global_running=1
    fi
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if [[ "$global_running" == 0 ]] && \
       awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
      echo "SCHEDULER_GATE_OK time=$(date -Is) load1=$load1"
      break
    fi
    echo "SCHEDULER_WAIT time=$(date -Is) load1=$load1 global_qc_running=$global_running"
    sleep "$POLL_SECONDS"
  done
  RUN_LABEL=rf2_primary_78_qc \
  INPUT="$RUN_ROOT/inputs/rf2_primary_78.fr4_restored.fasta" \
  OUT="$RUN_ROOT/qc/rf2_primary_78_full" \
  FAST_CHUNK_SIZE=78 CHUNK_JOBS=1 FULL_QC_LIMIT=0 FULL_CHUNK_SIZE=78 FULL_CHUNK_JOBS=1 \
  GEOMETRY_POOL_SIZE=78 GEOMETRY_LIMIT=50 GEOMETRY_CLUSTER_LIMIT=2 \
  WORKERS=4 TNP_NCORES=2 MAX_LOAD1="$MAX_LOAD1" \
  "$RUN_ROOT/scripts/run_sequence_qc_node1.sh"
) >> "$SCHEDULER_LOG" 2>&1 < /dev/null &

echo "$!" > "$SCHEDULER_PID"
echo "Started targeted QC scheduler pid=$! log=$SCHEDULER_LOG"

