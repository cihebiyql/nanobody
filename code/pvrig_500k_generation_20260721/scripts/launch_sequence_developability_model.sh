#!/usr/bin/env bash
set -Eeuo pipefail

: "${MODEL:?MODEL must be sapiens or abnativ}"
: "${ROOT:?ROOT is required}"
: "${INPUT:?INPUT is required}"
: "${TASK_COUNT:?TASK_COUNT is required}"

ENV_ROOT=${ENV_ROOT:-/data/qlyu/software/envs/vhh-eval}
CPUS_PER_TASK=${CPUS_PER_TASK:-1}
SUBPROCESSES_PER_TASK=${SUBPROCESSES_PER_TASK:-1}
PY="$ENV_ROOT/bin/python"
mkdir -p "$ROOT/runtime" "$ROOT/logs"

case "$MODEL" in
  sapiens)
    WORKER="$ROOT/scripts/run_bxcpu_sapiens_worker.sh"
    OUT_ROOT="$ROOT/results/sapiens_full"
    ;;
  abnativ)
    WORKER="$ROOT/scripts/run_bxcpu_abnativ_worker.sh"
    OUT_ROOT="$ROOT/results/abnativ_full"
    ;;
  *)
    echo "Unsupported MODEL=$MODEL" >&2
    exit 2
    ;;
esac

pids=()
for ((task_id = 0; task_id < TASK_COUNT; task_id++)); do
  task_name="${MODEL}_$(printf '%03d' "$task_id")"
  receipt="$OUT_ROOT/task_$(printf '%03d' "$task_id")/COMPLETE.json"
  if [[ -s "$receipt" ]]; then
    continue
  fi
  env \
    ROOT="$ROOT" \
    INPUT="$INPUT" \
    TASK_ID="$task_id" \
    TASK_COUNT="$TASK_COUNT" \
    ENV_ROOT="$ENV_ROOT" \
    OUT_ROOT="$OUT_ROOT" \
    CPUS="$CPUS_PER_TASK" \
    SUBPROCESSES_PER_TASK="$SUBPROCESSES_PER_TASK" \
    nohup setsid "$WORKER" \
    >"$ROOT/logs/$task_name.log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" >"$ROOT/runtime/$task_name.pid"
  pids+=("$pid")
done

"$PY" - "$ROOT/runtime/${MODEL}_LAUNCH.json" "$MODEL" "$TASK_COUNT" \
  "$CPUS_PER_TASK" "$SUBPROCESSES_PER_TASK" "${pids[@]}" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
model = sys.argv[2]
task_count = int(sys.argv[3])
cpus_per_task = int(sys.argv[4])
subprocesses_per_task = int(sys.argv[5])
pids = [int(value) for value in sys.argv[6:]]
payload = {
    "state": "RUNNING",
    "model": model,
    "task_count": task_count,
    "cpus_per_task": cpus_per_task,
    "subprocesses_per_task": subprocesses_per_task,
    "launched_pids": pids,
    "started_epoch": time.time(),
    "scientific_boundary": (
        "human-likeness/developability proxy; not measured purity or expression"
        if model == "sapiens"
        else "VHH nativeness/developability proxy; not measured purity or expression"
    ),
}
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(temporary, path)
PY

printf 'model=%s launched=%s task_count=%s\n' "$MODEL" "${#pids[@]}" "$TASK_COUNT"
