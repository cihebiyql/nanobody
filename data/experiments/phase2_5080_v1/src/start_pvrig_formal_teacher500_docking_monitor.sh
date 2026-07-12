#!/usr/bin/env bash
# Start the formal Teacher500 docking monitor independently of this shell.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MONITOR="$ROOT/src/monitor_pvrig_formal_teacher500_docking.sh"
PID_FILE=${PID_FILE:-$ROOT/logs/pvrig_formal_teacher500_docking_monitor.pid}
START_TIMEOUT_SECONDS=${START_TIMEOUT_SECONDS:-30}

monitor_is_running() {
  local pid=${1:-}
  [[ $pid =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ $(tr '\0' ' ' <"/proc/$pid/cmdline") == *monitor_pvrig_formal_teacher500_docking.sh* ]]
}

existing_pid=$(cat "$PID_FILE" 2>/dev/null || true)
if monitor_is_running "$existing_pid"; then
  echo "FORMAL_TEACHER500_DOCKING_MONITOR_ALREADY_RUNNING pid=$existing_pid"
  exit 0
fi

setsid -f bash "$MONITOR" </dev/null >/dev/null 2>&1
for ((elapsed = 0; elapsed < START_TIMEOUT_SECONDS; elapsed++)); do
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if monitor_is_running "$pid"; then
    echo "FORMAL_TEACHER500_DOCKING_MONITOR_STARTED pid=$pid"
    exit 0
  fi
  sleep 1
done

echo "Formal Teacher500 docking monitor did not start within ${START_TIMEOUT_SECONDS}s" >&2
exit 7
