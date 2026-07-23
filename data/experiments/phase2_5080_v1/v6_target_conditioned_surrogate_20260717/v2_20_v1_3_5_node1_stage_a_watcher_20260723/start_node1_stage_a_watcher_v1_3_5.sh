#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="pvrig-v220-v135-node1-stagea"
RUNTIME="$ROOT/runtime"
MONITOR="$ROOT/monitor_and_launch_stage_a_v1_3_5.sh"

mkdir -p "$RUNTIME"
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "session_exists:$SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "bash '$MONITOR' >>'$RUNTIME/WATCHER.log' 2>&1"
tmux has-session -t "$SESSION" 2>/dev/null
printf 'started:%s\n' "$SESSION"
