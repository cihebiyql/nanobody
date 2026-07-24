#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/data1/qlyu/projects/pvrig_node1_generated300k_screening_stage_v1_20260724/binding_prior_gpu_v1}
INPUT=${INPUT:-/data1/qlyu/projects/pvrig_node1_generated300k_screening_stage_v1_20260724/input/node1_generated_combined_exact_unique.fasta.gz}
PY=${PY:-/data1/qlyu/software/envs/deepnano/bin/python}
OUTPUT=${OUTPUT:-$ROOT/results/binding_priors_300k.tsv.gz}
mkdir -p "$ROOT/runtime" "$(dirname "$OUTPUT")"

write_progress() {
  local state="$1" completed="$2" active="$3" message="$4"
  "$PY" - "$ROOT/runtime/PROGRESS.json" "$state" "$completed" "$active" "$message" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "state": sys.argv[2],
    "completed_shards": int(sys.argv[3]),
    "total_shards": 7,
    "active_workers": int(sys.argv[4]),
    "message": sys.argv[5],
    "updated_epoch": time.time(),
    "scientific_boundary": "weak binding priors; not Kd, IC50, or blocking evidence",
}
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(temporary, path)
PY
}

while true; do
  completed=$(find "$ROOT/deepnano" "$ROOT/nanobind" -name COMPLETE.json 2>/dev/null | wc -l)
  active=0
  for pid_file in "$ROOT"/runtime/deepnano_*.pid "$ROOT"/runtime/nanobind_*.pid; do
    [[ -e "$pid_file" ]] || continue
    pid=$(<"$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      active=$((active + 1))
    fi
  done
  if [[ "$completed" -eq 7 ]]; then
    break
  fi
  if [[ "$active" -eq 0 ]]; then
    write_progress FAILED "$completed" "$active" "workers ended before all shard receipts appeared"
    exit 1
  fi
  write_progress RUNNING "$completed" "$active" "waiting for DeepNano/NanoBind GPU shards"
  sleep 30
done

write_progress AGGREGATING 7 0 "strict ID/count aggregation"
"$PY" "$ROOT/scripts/aggregate_node1_binding_prior_gpu_v1.py" \
  "$ROOT" "$INPUT" \
  -o "$OUTPUT" \
  --expected-records 300000 \
  >"$ROOT/logs/aggregate.stdout" 2>"$ROOT/logs/aggregate.stderr"
write_progress COMPLETE 7 0 "binding-prior table aggregated and hash-verified"
