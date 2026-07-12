#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_1000_20260712}
POLL_SECONDS=${POLL_SECONDS:-60}

mkdir -p "$RUN_ROOT/final" "$RUN_ROOT/logs"
echo $$ > "$RUN_ROOT/final/finalizer_pid"
date -Is > "$RUN_ROOT/final/finalizer_started_at.txt"

while true; do
  complete=0
  failed=0
  for set_id in A B C D; do
    set_dir="$RUN_ROOT/sets/set_$set_id"
    if [[ -s "$set_dir/complete.json" ]]; then
      complete=$((complete + 1))
    elif [[ -s "$set_dir/status/status.json" ]] && \
         grep -q '"state": "failed"' "$set_dir/status/status.json"; then
      failed=$((failed + 1))
    fi
  done

  printf '[%s] complete_sets=%s failed_sets=%s\n' "$(date -Is)" "$complete" "$failed"
  if (( failed > 0 )); then
    echo "At least one generation set failed; not finalizing." >&2
    exit 2
  fi
  if (( complete == 4 )); then
    break
  fi
  sleep "$POLL_SECONDS"
done

python3 "$RUN_ROOT/scripts/collect_sequences.py" --run-root "$RUN_ROOT"
date -Is > "$RUN_ROOT/final/finalizer_completed_at.txt"
echo '{"state":"complete","selected_records":1000}' > "$RUN_ROOT/final/finalizer_complete.json"
echo "[$(date -Is)] finalization complete"
