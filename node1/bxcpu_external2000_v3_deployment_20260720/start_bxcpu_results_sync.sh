#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
LOCAL_ROOT=${PVRIG_BXCPU_SYNC_LOCAL_ROOT:-/mnt/d/work/抗体/node1/bxcpu_incremental_spool_20260720}
mkdir -p "$LOCAL_ROOT/state"
PIDFILE="$LOCAL_ROOT/state/sync.pid"
LOG="$LOCAL_ROOT/state/sync.nohup.log"
SESSION=pvrig-bxcpu-result-sync

if tmux has-session -t "$SESSION" 2>/dev/null; then
    pid=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' | head -1)
    echo "$pid" >"$PIDFILE"
    echo "sync already running pid=$pid tmux=$SESSION"
    exit 0
fi

command=$(printf 'exec env PVRIG_BXCPU_SYNC_BATCH_SIZE=%q PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS=%q PVRIG_BXCPU_SYNC_POLL_SECONDS=%q python3 %q >>%q 2>&1' \
    "${PVRIG_BXCPU_SYNC_BATCH_SIZE:-5}" \
    "${PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS:-600}" \
    "${PVRIG_BXCPU_SYNC_POLL_SECONDS:-60}" \
    "$DEPLOY/sync_bxcpu_results_incremental.py" "$LOG")
tmux new-session -d -s "$SESSION" "$command"
pid=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' | head -1)
echo "$pid" >"$PIDFILE"
sleep 2
tmux has-session -t "$SESSION"
echo "sync started pid=$pid tmux=$SESSION log=$LOG"
