#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_1000_20260712}
CONFIG=${CONFIG:-$RUN_ROOT/config/hotspot_sets.tsv}
SCRIPT=${SCRIPT:-$RUN_ROOT/scripts/run_set.sh}

mkdir -p "$RUN_ROOT/logs"

tail -n +2 "$CONFIG" | while IFS=$'\t' read -r set_id gpu hotspots _rest; do
  set_dir="$RUN_ROOT/sets/set_$set_id"
  if [[ -s "$set_dir/complete.json" ]]; then
    echo "set $set_id already complete; skipping launch"
    continue
  fi
  pid_file="$set_dir/status/launcher_pid"
  if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "set $set_id already running with pid $(cat "$pid_file")"
    continue
  fi
  mkdir -p "$set_dir/status"
  nohup bash "$SCRIPT" "$set_id" "$gpu" "$hotspots" \
    > "$RUN_ROOT/logs/set_${set_id}.log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" > "$pid_file"
  echo "launched set=$set_id gpu=$gpu pid=$pid hotspots=$hotspots"
done
