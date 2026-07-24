#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/data1/qlyu/projects/pvrig_node1_generated300k_screening_stage_v1_20260724/binding_prior_gpu_v1}
INPUT=${INPUT:-/data1/qlyu/projects/pvrig_node1_generated300k_screening_stage_v1_20260724/input/node1_generated_combined_exact_unique.fasta.gz}
PY=${PY:-/data1/qlyu/software/envs/deepnano/bin/python}
mkdir -p "$ROOT/runtime" "$ROOT/logs"

declare -a pids=()
for task_id in 0 1 2; do
  gpu=$((task_id + 1))
  task_name="deepnano_$(printf '%03d' "$task_id")"
  env ROOT="$ROOT" INPUT="$INPUT" MODEL=deepnano TASK_ID="$task_id" TASK_COUNT=3 \
    GPU="$gpu" PY="$PY" \
    nohup setsid "$ROOT/scripts/run_node1_binding_gpu_worker.sh" \
    >"$ROOT/logs/$task_name.log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" >"$ROOT/runtime/$task_name.pid"
  pids+=("$pid")
done

for task_id in 0 1 2 3; do
  gpu=$((task_id + 4))
  task_name="nanobind_$(printf '%03d' "$task_id")"
  env ROOT="$ROOT" INPUT="$INPUT" MODEL=nanobind TASK_ID="$task_id" TASK_COUNT=4 \
    GPU="$gpu" PY="$PY" \
    nohup setsid "$ROOT/scripts/run_node1_binding_gpu_worker.sh" \
    >"$ROOT/logs/$task_name.log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" >"$ROOT/runtime/$task_name.pid"
  pids+=("$pid")
done

"$PY" - "$ROOT" "${pids[@]}" <<'PY'
import json
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
pids = [int(value) for value in sys.argv[2:]]
payload = {
    "state": "RUNNING",
    "records": 300000,
    "deepnano_shards": 3,
    "nanobind_shards": 4,
    "gpu_assignment": {
        "deepnano": [1, 2, 3],
        "nanobind": [4, 5, 6, 7],
    },
    "pids": pids,
    "started_epoch": time.time(),
    "inference_semantics": "exact-length buckets; batch-composition invariant",
    "scientific_boundary": "weak binding priors; not Kd, IC50, or blocking evidence",
}
(root / "runtime" / "LAUNCH.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n"
)
PY

printf 'launched_pids=%s\n' "${pids[*]}"
