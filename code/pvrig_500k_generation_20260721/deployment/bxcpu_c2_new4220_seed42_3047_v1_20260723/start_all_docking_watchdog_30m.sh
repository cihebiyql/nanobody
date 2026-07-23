#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
SESSION=pvrig-all-docking-watchdog-30m
mkdir -p "$DEPLOY/watchdog_runtime"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "$SESSION already running"
    exit 0
fi
tmux new-session -d -s "$SESSION" "exec '$DEPLOY/run_all_docking_watchdog_30m.sh'"
echo "$SESSION started"
