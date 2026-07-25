#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT=$(cd "$(dirname "$0")" && pwd)
LOCAL_BASE="${PVRIG_TOP200_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/pvrig_top200_seed_completion_bxcpu_spool_v1_20260725}"
COUNT="${PVRIG_TOP200_SYNC_SHARDS:-2}"
BATCH="${PVRIG_TOP200_SYNC_BATCH_SIZE:-40}"
POLL="${PVRIG_TOP200_SYNC_POLL_SECONDS:-15}"
NODE1_ROOT="${PVRIG_BXCPU_SYNC_NODE1_ROOT:-/data1/qlyu/projects/pvrig_top200_common4_seed_completion106_docking_results_v1_20260725}"

[[ "$COUNT" == 2 ]] || {
    echo "Top200 supplemental sync requires exactly two relay shards" >&2
    exit 64
}
command -v tmux >/dev/null
mkdir -p "$LOCAL_BASE"

for index in 0 1; do
    root=$(printf '%s/shard%02d' "$LOCAL_BASE" "$index")
    session=$(printf 'pvrig-top200-seedfill-sync-%02d' "$index")
    log="$root/state/sync.nohup.log"
    mkdir -p "$root/state"
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "$session already running"
        continue
    fi
    command=$(
        printf 'exec env PYTHONUNBUFFERED=1 PVRIG_BXCPU_SYNC_LOCAL_ROOT=%q PVRIG_BXCPU_SYNC_SHARD_COUNT=2 PVRIG_BXCPU_SYNC_SHARD_INDEX=%q PVRIG_BXCPU_SYNC_BATCH_SIZE=%q PVRIG_BXCPU_SYNC_POLL_SECONDS=%q PVRIG_BXCPU_SYNC_NODE1_ROOT=%q python3 %q >>%q 2>&1' \
            "$root" \
            "$index" \
            "$BATCH" \
            "$POLL" \
            "$NODE1_ROOT" \
            "$DEPLOY_ROOT/sync_top200_seed_completion_incremental.py" \
            "$log"
    )
    tmux new-session -d -s "$session" "$command"
    echo "$session started root=$root"
done
