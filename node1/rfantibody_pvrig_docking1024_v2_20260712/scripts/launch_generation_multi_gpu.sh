#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
GPU_IDS=${GPU_IDS:-1,2,3,4,5,7}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-1000}
GPU_WAIT_SECONDS=${GPU_WAIT_SECONDS:-60}
MAX_LOAD1=${MAX_LOAD1:-56}
ARM_TABLE=${ARM_TABLE:-$RUN_ROOT/config/generation_arms.tsv}
mkdir -p "$RUN_ROOT/logs/generation" "$RUN_ROOT/status/generation"

python3 - "$RUN_ROOT" "$ARM_TABLE" <<'PY'
import csv
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "inputs/scaffolds/scaffold_manifest.json").read_text())
by_id = {row["scaffold_id"]: row for row in manifest["variants"]}
with open(sys.argv[2], newline="", encoding="utf-8") as handle:
    arms = list(csv.DictReader(handle, delimiter="\t"))
for arm in arms:
    scaffold = root / arm["framework_relpath"]
    row = by_id[arm["scaffold_id"]]
    digest = hashlib.sha256(scaffold.read_bytes()).hexdigest()
    if digest != row["sha256"]:
        raise SystemExit(f"scaffold SHA mismatch: {scaffold}")
    text = scaffold.read_text(encoding="ascii", errors="replace")
    if not all(f" {label}" in text for label in ("H1", "H2", "H3")):
        raise SystemExit(f"scaffold labels missing: {scaffold}")
    if arm["scaffold_lane"] == "primary_vhhified" and not row["sequence"].endswith("VTVSS"):
        raise SystemExit(f"primary scaffold lacks VTVSS: {scaffold}")
print(f"generation preflight passed for {len(arms)} arms")
PY

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

wait_for_load() {
  while true; do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if awk -v load="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(load < limit) }'; then
      return
    fi
    echo "LOAD_GATE_WAIT load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
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
    wait_for_load
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
expected_arms=$(awk 'NR > 1 { count++ } END { print count+0 }' "$ARM_TABLE")
complete_arms=$(find "$RUN_ROOT/generation/arms" -mindepth 2 -maxdepth 2 -type f -name complete.json 2>/dev/null | wc -l | tr -d ' ')
if [[ "$rc" -eq 0 && "$complete_arms" -eq "$expected_arms" ]]; then
  date -Is > "$RUN_ROOT/status/generation/all.complete"
else
  echo "Generation is not globally complete: complete_arms=$complete_arms expected_arms=$expected_arms rc=$rc" >&2
  rc=4
fi
exit "$rc"
