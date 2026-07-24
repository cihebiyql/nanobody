#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT=$(cd "$(dirname "$0")" && pwd)
PROJECT_NAME="${PVRIG_TOP5000_PROJECT_NAME:-pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724}"
BASE="${PVRIG_TOP5000_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/pvrig_top5000_multimodal_4seed_bxcpu_incremental_spool_20260724}"
COUNT="${PVRIG_TOP5000_SYNC_SHARDS:-4}"
BATCH="${PVRIG_TOP5000_SYNC_BATCH_SIZE:-60}"
STABLE="${PVRIG_TOP5000_SYNC_STABLE_AGE_SECONDS:-90}"
POLL="${PVRIG_TOP5000_SYNC_POLL_SECONDS:-10}"
MAX_SPOOL_GIB="${PVRIG_TOP5000_SYNC_MAX_SPOOL_GIB_PER_SHARD:-4}"
MIN_FREE_GIB="${PVRIG_TOP5000_SYNC_MIN_LOCAL_FREE_GIB:-10}"
BXCPU_RESULT_ROOT="${PVRIG_TOP5000_BXCPU_RESULT_ROOT:-/publicfs04/fs04-al/home/als001821/${PROJECT_NAME}_bxcpu_results}"
NODE1_RESULT_ROOT="${PVRIG_TOP5000_NODE1_RESULT_ROOT:-/data/qlyu/projects/pvrig_node1_generated100k_multimodal_top5000_4seed_docking_results_v1_20260724}"
BXCPU_SSH="${PVRIG_BXCPU_SSH:-/mnt/c/Windows/System32/OpenSSH/ssh.exe}"
NODE1_SSH="${PVRIG_NODE1_SSH:-/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe}"

[[ "$COUNT" == 4 ]] || {
    echo "top5000 incremental sync requires exactly four shards" >&2
    exit 64
}
[[ "$BATCH" =~ ^[0-9]+$ && "$BATCH" -ge 40 && "$BATCH" -le 80 ]] || {
    echo "batch size must be in the measured-safe range 40..80" >&2
    exit 64
}
[[ "$STABLE" =~ ^[0-9]+$ && "$STABLE" -ge 60 && "$STABLE" -le 120 ]] || {
    echo "stable age must be in the measured-safe range 60..120 seconds" >&2
    exit 64
}
command -v tmux >/dev/null
command -v python3 >/dev/null
[[ -x "$BXCPU_SSH" ]] || {
    echo "bxcpu SSH executable is unavailable: $BXCPU_SSH" >&2
    exit 69
}
[[ -x "$NODE1_SSH" ]] || {
    echo "Node1 SSH executable is unavailable: $NODE1_SSH" >&2
    exit 69
}
mkdir -p "$BASE"

for ((index = 0; index < COUNT; index++)); do
    root=$(printf '%s/shard%02d' "$BASE" "$index")
    session=$(printf 'pvrig-top5000-mm-sync-%02d' "$index")
    log="$root/state/sync.nohup.log"
    mkdir -p "$root/state"
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "$session already running"
        continue
    fi
    command=$(
        printf 'exec env PYTHONUNBUFFERED=1 PVRIG_TOP5000_PROJECT_NAME=%q PVRIG_TOP5000_SYNC_LOCAL_ROOT=%q PVRIG_TOP5000_SYNC_SHARD_COUNT=4 PVRIG_TOP5000_SYNC_SHARD_INDEX=%q PVRIG_TOP5000_SYNC_BATCH_SIZE=%q PVRIG_TOP5000_SYNC_STABLE_AGE_SECONDS=%q PVRIG_TOP5000_SYNC_POLL_SECONDS=%q PVRIG_TOP5000_SYNC_MAX_SPOOL_GIB_PER_SHARD=%q PVRIG_TOP5000_SYNC_MIN_LOCAL_FREE_GIB=%q PVRIG_TOP5000_BXCPU_RESULT_ROOT=%q PVRIG_TOP5000_NODE1_RESULT_ROOT=%q PVRIG_BXCPU_SSH=%q PVRIG_NODE1_SSH=%q python3 %q >>%q 2>&1' \
            "$PROJECT_NAME" \
            "$root" \
            "$index" \
            "$BATCH" \
            "$STABLE" \
            "$POLL" \
            "$MAX_SPOOL_GIB" \
            "$MIN_FREE_GIB" \
            "$BXCPU_RESULT_ROOT" \
            "$NODE1_RESULT_ROOT" \
            "$BXCPU_SSH" \
            "$NODE1_SSH" \
            "$DEPLOY_ROOT/sync_top5000_results_incremental.py" \
            "$log"
    )
    tmux new-session -d -s "$session" "$command"
    echo "$session started root=$root batch=$BATCH stable_age=$STABLE max_spool_gib=$MAX_SPOOL_GIB"
done
