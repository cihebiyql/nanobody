#!/usr/bin/env bash
set -euo pipefail
ROOT=${PVRIG_BXCPU_SYNC_LOCAL_ROOT:-/mnt/d/work/抗体/node1/bxcpu_incremental_spool_20260720}
PIDFILE="$ROOT/state/sync.pid"
SESSION=pvrig-bxcpu-result-sync
if tmux has-session -t "$SESSION" 2>/dev/null; then
    pid=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' | head -1)
    echo "RUNNING pid=$pid tmux=$SESSION"
else
    echo "NOT_RUNNING"
fi
cat "$ROOT/state/SYNC_STATUS.json" 2>/dev/null || true
tail -10 "$ROOT/state/sync.nohup.log" 2>/dev/null || true
