#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:?RUN_ROOT is required}
GPU_IDS=${GPU_IDS:-1,2,3,4,5,6,7}
WORKERS_PER_GPU=${WORKERS_PER_GPU:-3}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-20000}
GPU_WAIT_SECONDS=${GPU_WAIT_SECONDS:-20}
MAX_LOAD1=${MAX_LOAD1:-180}
ARM_TABLE=${ARM_TABLE:-$RUN_ROOT/config/generation_arms_primary.tsv}
ARM_OUTPUT_BASE=${ARM_OUTPUT_BASE:-$RUN_ROOT/generation/arms}
STATUS_NAMESPACE=${STATUS_NAMESPACE:-generation}
STATUS_DIR="$RUN_ROOT/status/$STATUS_NAMESPACE"
LOG_DIR="$RUN_ROOT/logs/$STATUS_NAMESPACE"
mkdir -p "$LOG_DIR" "$STATUS_DIR" "$ARM_OUTPUT_BASE"

# A controller must never start a second launcher against the same namespace.
# Keep the lock FD open for the full launcher lifetime.
exec 9>"$STATUS_DIR/launcher.lock"
if ! flock -n 9; then
  echo "launcher already active for namespace=$STATUS_NAMESPACE" >&2
  exit 3
fi

if [[ ! "$WORKERS_PER_GPU" =~ ^[1-9][0-9]*$ ]]; then
  echo "WORKERS_PER_GPU must be a positive integer" >&2
  exit 2
fi

python3 - "$RUN_ROOT" "$ARM_TABLE" <<'PY'
import csv, hashlib, json, sys
from pathlib import Path
root=Path(sys.argv[1])
manifest=json.loads((root/'inputs/scaffolds/scaffold_manifest.json').read_text())
by_id={row['scaffold_id']:row for row in manifest['variants']}
with open(sys.argv[2], newline='', encoding='utf-8') as handle:
    arms=list(csv.DictReader(handle, delimiter='\t'))
if not arms:
    raise SystemExit('empty arm table')
for arm in arms:
    scaffold=root/arm['framework_relpath']
    digest=hashlib.sha256(scaffold.read_bytes()).hexdigest()
    if digest != by_id[arm['scaffold_id']]['sha256']:
        raise SystemExit('scaffold SHA mismatch: {}'.format(scaffold))
print('multiworker preflight passed for {} arms'.format(len(arms)))
PY

wait_for_gpu() {
  local gpu=$1
  while true; do
    local used
    used=$(nvidia-smi --id="$gpu" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
    if [[ "$used" -lt "$GPU_MEMORY_GATE_MB" ]]; then return; fi
    echo "GPU_GATE_WAIT gpu=$gpu memory_used_mb=$used threshold=$GPU_MEMORY_GATE_MB time=$(date -Is)"
    sleep "$GPU_WAIT_SECONDS"
  done
}

wait_for_load() {
  while true; do
    local load1
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if awk -v current="$load1" -v limit="$MAX_LOAD1" 'BEGIN { exit !(current < limit) }'; then return; fi
    echo "LOAD_GATE_WAIT load1=$load1 threshold=$MAX_LOAD1 time=$(date -Is)"
    sleep "$GPU_WAIT_SECONDS"
  done
}

run_worker() {
  local gpu=$1 slot=$2
  local log="$LOG_DIR/gpu_${gpu}_worker_${slot}.log"
  exec > >(tee -a "$log") 2>&1
  echo "GPU_WORKER_START gpu=$gpu slot=$slot workers_per_gpu=$WORKERS_PER_GPU time=$(date -Is)"
  local ordinal=0
  while IFS=$'\t' read -r arm_id configured_gpu _; do
    [[ "$arm_id" == arm_id ]] && continue
    [[ "$configured_gpu" == "$gpu" ]] || continue
    if (( ordinal % WORKERS_PER_GPU != slot )); then
      ordinal=$((ordinal + 1))
      continue
    fi
    ordinal=$((ordinal + 1))
    if [[ -s "$ARM_OUTPUT_BASE/$arm_id/complete.json" ]]; then
      echo "ARM_SKIP_COMPLETE arm=$arm_id gpu=$gpu slot=$slot"
      continue
    fi
    wait_for_load
    wait_for_gpu "$gpu"
    RUN_ROOT="$RUN_ROOT" ARM_TABLE="$ARM_TABLE" ARM_OUTPUT_BASE="$ARM_OUTPUT_BASE" \
      OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
      bash "$RUN_ROOT/scripts/run_generation_arm.sh" "$arm_id" "$gpu"
  done < "$ARM_TABLE"
  date -Is > "$STATUS_DIR/gpu_${gpu}_worker_${slot}.complete"
  echo "GPU_WORKER_COMPLETE gpu=$gpu slot=$slot time=$(date -Is)"
}

IFS=',' read -r -a gpu_array <<< "$GPU_IDS"
pids=()
for gpu in "${gpu_array[@]}"; do
  for ((slot=0; slot<WORKERS_PER_GPU; slot++)); do
    pid_file="$STATUS_DIR/gpu_${gpu}_worker_${slot}.pid"
    if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
      echo "worker already running gpu=$gpu slot=$slot pid=$(cat "$pid_file")"
      continue
    fi
    run_worker "$gpu" "$slot" &
    pid=$!
    echo "$pid" > "$pid_file"
    pids+=("$pid")
  done
done

rc=0
for pid in "${pids[@]}"; do wait "$pid" || rc=1; done
expected=$(awk 'NR>1{n++} END{print n+0}' "$ARM_TABLE")
complete=$(python3 - "$ARM_OUTPUT_BASE" "$ARM_TABLE" <<'PY'
import csv,sys
from pathlib import Path
root=Path(sys.argv[1])
with open(sys.argv[2], newline='', encoding='utf-8') as handle:
    arms=list(csv.DictReader(handle, delimiter='\t'))
print(sum((root/row['arm_id']/'complete.json').is_file() for row in arms))
PY
)
if [[ "$rc" -ne 0 || "$complete" -ne "$expected" ]]; then
  echo "multiworker generation incomplete complete=$complete expected=$expected rc=$rc" >&2
  exit 4
fi
date -Is > "$STATUS_DIR/all.complete"
