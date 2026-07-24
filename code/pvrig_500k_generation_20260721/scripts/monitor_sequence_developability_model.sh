#!/usr/bin/env bash
set -Eeuo pipefail

: "${MODEL:?MODEL must be sapiens or abnativ}"
: "${ROOT:?ROOT is required}"
: "${TASK_COUNT:?TASK_COUNT is required}"
: "${EXPECTED_RECORDS:?EXPECTED_RECORDS is required}"

ENV_ROOT=${ENV_ROOT:-/data/qlyu/software/envs/vhh-eval}
PY="$ENV_ROOT/bin/python"
mkdir -p "$ROOT/runtime" "$ROOT/logs" "$ROOT/aggregated"

case "$MODEL" in
  sapiens)
    RESULT_ROOT="$ROOT/results/sapiens_full"
    AGGREGATOR="$ROOT/scripts/aggregate_bxcpu_sapiens_results.py"
    OUTPUT="$ROOT/aggregated/sapiens_all.tsv.gz"
    ;;
  abnativ)
    RESULT_ROOT="$ROOT/results/abnativ_full"
    AGGREGATOR="$ROOT/scripts/aggregate_bxcpu_abnativ_results.py"
    OUTPUT="$ROOT/aggregated/abnativ_all.tsv.gz"
    ;;
  *)
    echo "Unsupported MODEL=$MODEL" >&2
    exit 2
    ;;
esac

write_progress() {
  local state="$1" complete="$2" active="$3" message="$4"
  "$PY" - "$ROOT/runtime/${MODEL}_PROGRESS.json" "$MODEL" "$state" \
    "$complete" "$active" "$TASK_COUNT" "$message" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "model": sys.argv[2],
    "state": sys.argv[3],
    "completed_tasks": int(sys.argv[4]),
    "active_tasks": int(sys.argv[5]),
    "total_tasks": int(sys.argv[6]),
    "message": sys.argv[7],
    "updated_epoch": time.time(),
    "scientific_boundary": "developability proxy; not measured purity or expression",
}
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(temporary, path)
PY
}

while true; do
  complete=$(find "$RESULT_ROOT" -name COMPLETE.json 2>/dev/null | wc -l)
  active=0
  for pid_file in "$ROOT"/runtime/"${MODEL}"_*.pid; do
    [[ -e "$pid_file" ]] || continue
    pid=$(<"$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      active=$((active + 1))
    fi
  done
  if [[ "$complete" -eq "$TASK_COUNT" ]]; then
    break
  fi
  if [[ "$active" -eq 0 ]]; then
    write_progress FAILED "$complete" "$active" "workers ended before all receipts appeared"
    exit 1
  fi
  write_progress RUNNING "$complete" "$active" "waiting for model shards"
  sleep 20
done

write_progress AGGREGATING "$complete" 0 "strict ID/count aggregation"
"$PY" "$AGGREGATOR" "$RESULT_ROOT" \
  -o "$OUTPUT" \
  --expected-records "$EXPECTED_RECORDS" \
  >"$ROOT/logs/${MODEL}_aggregate.stdout" \
  2>"$ROOT/logs/${MODEL}_aggregate.stderr"
write_progress COMPLETE "$complete" 0 "aggregate complete and hash-verified"
