#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT=${PACKAGE_ROOT:?PACKAGE_ROOT is required}
MONOMER_MAX_LOAD1=${MONOMER_MAX_LOAD1:-64}
DOCKING_MAX_LOAD1=${DOCKING_MAX_LOAD1:-48}
POLL_SECONDS=${POLL_SECONDS:-60}
LOG=$PACKAGE_ROOT/controller.log

wait_for_load() {
  local limit=$1 label=$2
  while true; do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if awk -v load="$load1" -v limit="$limit" 'BEGIN { exit !(load < limit) }'; then
      echo "LOAD_GATE_OK label=$label load1=$load1 time=$(date -Is)"
      return
    fi
    echo "LOAD_GATE_WAIT label=$label load1=$load1 threshold=$limit time=$(date -Is)"
    sleep "$POLL_SECONDS"
  done
}

run_phase() {
  local mode=$1 limit=$2
  local pids=()
  for shard in 0 1 2 3; do
    shard_root=$PACKAGE_ROOT/shard_$shard
    [[ -s "$shard_root/manifests/runtime_candidates.tsv" ]] || continue
    gpu=$((shard + 1))
    (
      DOCKING_SHARD_ROOT="$shard_root" DOCKING_MODE="$mode" DOCKING_GPU_ID="$gpu" \
      DOCKING_MAX_LOAD1="$limit" DOCKING_LOAD_WAIT_SECONDS="$POLL_SECONDS" \
      bash "$PACKAGE_ROOT/run_nbb2_haddock_shard_node1.sh"
    ) >"$shard_root/logs/controller_${mode}.log" 2>&1 &
    pids+=("$!")
  done
  status=0
  for pid in "${pids[@]}"; do wait "$pid" || status=1; done
  [[ "$status" == 0 ]] || return 1
  touch "$PACKAGE_ROOT/${mode}.complete"
}

exec > >(tee -a "$LOG") 2>&1
echo "DOCKING_CONTROLLER_START time=$(date -Is)"
wait_for_load "$MONOMER_MAX_LOAD1" monomer
run_phase monomer "$MONOMER_MAX_LOAD1"
wait_for_load "$DOCKING_MAX_LOAD1" docking
run_phase docking "$DOCKING_MAX_LOAD1"
echo "DOCKING_CONTROLLER_COMPLETE time=$(date -Is)"
