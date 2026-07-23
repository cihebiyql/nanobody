#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
BASE=${PVRIG_BXCPU_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/pvrig_c2_new6220_dualseed_bxcpu_incremental_spool_20260723}
COUNT=${PVRIG_BXCPU_SYNC_SHARDS:-4}
BATCH=${PVRIG_BXCPU_SYNC_BATCH_SIZE:-40}
STABLE=${PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS:-180}
POLL=${PVRIG_BXCPU_SYNC_POLL_SECONDS:-10}
RESERVE_GIB=${PVRIG_BXCPU_SYNC_MIN_LOCAL_FREE_GIB:-20}

for ((index=0; index<COUNT; index++)); do
    root=$(printf '%s/shard%02d' "$BASE" "$index")
    session=$(printf 'pvrig-c2-new6220-sync-%02d' "$index")
    log="$root/state/sync.nohup.log"
    mkdir -p "$root/state"
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "$session already running"
        continue
    fi
    command=$(printf 'exec env PVRIG_BXCPU_SYNC_LOCAL_ROOT=%q PVRIG_BXCPU_SYNC_SHARD_COUNT=%q PVRIG_BXCPU_SYNC_SHARD_INDEX=%q PVRIG_BXCPU_SYNC_BATCH_SIZE=%q PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS=%q PVRIG_BXCPU_SYNC_POLL_SECONDS=%q PVRIG_BXCPU_SYNC_MIN_LOCAL_FREE_GIB=%q python3 %q >>%q 2>&1' \
        "$root" "$COUNT" "$index" "$BATCH" "$STABLE" "$POLL" "$RESERVE_GIB" \
        "$DEPLOY/sync_c2_new6220_results_incremental.py" "$log")
    tmux new-session -d -s "$session" "$command"
    echo "$session started"
done
