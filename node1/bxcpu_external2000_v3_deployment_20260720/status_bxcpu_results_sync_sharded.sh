#!/usr/bin/env bash
set -euo pipefail
BASE=${PVRIG_BXCPU_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/bxcpu_incremental_spool_20260720}
COUNT=${PVRIG_BXCPU_SYNC_SHARDS:-8}
running=0 delivered=0 pruned=0
for ((i=0; i<COUNT; i++)); do
    session=$(printf 'pvrig-bxcpu-result-sync-%02d' "$i")
    root=$(printf '%s/shard%02d' "$BASE" "$i")
    d=$(find "$root/state" -maxdepth 1 -name 'stage2*.delivered_job_ids.txt' -type f -exec cat {} + 2>/dev/null | sort -u | wc -l)
    p=$(find "$root/state" -maxdepth 1 -name 'stage2*.pruned_job_ids.txt' -type f -exec cat {} + 2>/dev/null | sort -u | wc -l)
    state=STOPPED
    if tmux has-session -t "$session" 2>/dev/null; then state=RUNNING; running=$((running+1)); fi
    printf 'shard=%02d state=%s delivered=%d pruned=%d\n' "$i" "$state" "$d" "$p"
    delivered=$((delivered+d)); pruned=$((pruned+p))
done
printf 'TOTAL running=%d/%d delivered=%d pruned=%d\n' "$running" "$COUNT" "$delivered" "$pruned"
