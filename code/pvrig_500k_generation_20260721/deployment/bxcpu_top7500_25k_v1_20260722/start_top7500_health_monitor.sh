#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
BASE=${PVRIG_TOP7500_MONITOR_ROOT:-/mnt/d/work/抗体/node1/pvrig_top7500_25k_bxcpu_incremental_spool_20260722/monitor}
SESSION=pvrig-top7500-health-monitor
mkdir -p "$BASE"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "$SESSION already running"
    exit 0
fi
command=$(printf 'exec %q >>%q 2>&1' "$DEPLOY/run_top7500_health_monitor.sh" "$BASE/monitor.log")
tmux new-session -d -s "$SESSION" "$command"
echo "$SESSION started"
