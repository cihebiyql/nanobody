#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
GPU_IDS=${GPU_IDS:-1,2,3,4,5,7}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-1000}
GPU_WAIT_SECONDS=${GPU_WAIT_SECONDS:-60}
ARM_TABLE=${ARM_TABLE:-$RUN_ROOT/config/generation_arms.tsv}
mkdir -p "$RUN_ROOT/logs/generation" "$RUN_ROOT/status/generation"

wait_for_gpu() {
  local gpu=$1
  while true; do
    used=$(nvidia-smi --id="$gpu" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
    if [[ "$used" -lt "$GPU_MEMORY_GATE_MB" ]]; then
      return
    fi
    echo "GPU_GATE_WAIT gpu=$gpu memory_used_mb=$used time=$(date -Is)"
    sleep "$GPU_WAIT_SECONDS"
  done
}

run_gpu_lane() {
  local gpu=$1
  local log="$RUN_ROOT/logs/generation/gpu_${gpu}.log"
  exec > >(tee -a "$log") 2>&1
  echo "GPU_LANE_START gpu=$gpu time=$(date -Is)"
  while IFS=$'\t' read -r arm_id configured_gpu _; do
    [[ "$arm_id" == arm_id ]] && continue
    [[ "$configured_gpu" == "$gpu" ]] || continue
    if [[ -s "$RUN_ROOT/generation/arms/$arm_id/complete.json" ]]; then
      echo "ARM_SKIP_COMPLETE arm=$arm_id gpu=$gpu"
      continue
    fi
    wait_for_gpu "$gpu"
    bash "$RUN_ROOT/scripts/run_generation_arm.sh" "$arm_id" "$gpu"
  done < "$ARM_TABLE"
  date -Is > "$RUN_ROOT/status/generation/gpu_${gpu}.complete"
  echo "GPU_LANE_COMPLETE gpu=$gpu time=$(date -Is)"
}

IFS=',' read -r -a gpu_array <<< "$GPU_IDS"
pids=()
for gpu in "${gpu_array[@]}"; do
  pid_file="$RUN_ROOT/status/generation/gpu_${gpu}.pid"
  if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "GPU lane $gpu already running pid=$(cat "$pid_file")"
    continue
  fi
  run_gpu_lane "$gpu" &
  pid=$!
  echo "$pid" > "$pid_file"
  pids+=("$pid")
done

rc=0
for pid in "${pids[@]}"; do
  wait "$pid" || rc=1
done
if [[ "$rc" -eq 0 ]]; then
  date -Is > "$RUN_ROOT/status/generation/all.complete"
fi
exit "$rc"
