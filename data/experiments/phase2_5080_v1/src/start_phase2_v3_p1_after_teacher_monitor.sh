#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MONITOR="$ROOT/src/monitor_phase2_v3_p1_after_teacher.sh"
PID_FILE=${PID_FILE:-$ROOT/logs/phase2_v3_p1_after_teacher_monitor.pid}

pid=$(cat "$PID_FILE" 2>/dev/null || true)
if [[ $pid =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
  echo "PHASE2_V3_P1_WATCHER_ALREADY_RUNNING pid=$pid"
  exit 0
fi
setsid -f bash "$MONITOR" </dev/null >/dev/null 2>&1
for _ in $(seq 1 30); do
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if [[ $pid =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "PHASE2_V3_P1_WATCHER_STARTED pid=$pid"
    exit 0
  fi
  sleep 1
done
echo "Formal V3-P watcher did not start" >&2
exit 7
