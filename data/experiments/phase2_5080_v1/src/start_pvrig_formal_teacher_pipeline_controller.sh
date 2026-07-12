#!/usr/bin/env bash
# Start the formal teacher controller in a session independent of this shell.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONTROLLER="$ROOT/src/monitor_pvrig_formal_teacher_pipeline.sh"
PID_FILE=${PID_FILE:-$ROOT/logs/pvrig_formal_teacher_pipeline_controller.pid}
START_TIMEOUT_SECONDS=${START_TIMEOUT_SECONDS:-30}

controller_is_running() {
  local pid=${1:-}
  [[ $pid =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ $(tr '\0' ' ' <"/proc/$pid/cmdline") == *monitor_pvrig_formal_teacher_pipeline.sh* ]]
}

existing_pid=$(cat "$PID_FILE" 2>/dev/null || true)
if controller_is_running "$existing_pid"; then
  echo "FORMAL_TEACHER_CONTROLLER_ALREADY_RUNNING pid=$existing_pid"
  exit 0
fi

setsid -f bash "$CONTROLLER" </dev/null >/dev/null 2>&1

for ((elapsed = 0; elapsed < START_TIMEOUT_SECONDS; elapsed++)); do
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if controller_is_running "$pid"; then
    echo "FORMAL_TEACHER_CONTROLLER_STARTED pid=$pid"
    exit 0
  fi
  sleep 1
done

echo "Formal teacher controller did not start within ${START_TIMEOUT_SECONDS}s" >&2
exit 7
