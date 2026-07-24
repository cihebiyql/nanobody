#!/usr/bin/env bash
set -euo pipefail

BASE="${PVRIG_TOP5000_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/pvrig_top5000_multimodal_4seed_bxcpu_incremental_spool_20260724}"
COUNT="${PVRIG_TOP5000_SYNC_SHARDS:-4}"
[[ "$COUNT" == 4 ]] || {
    echo "status contract requires exactly four sync shards" >&2
    exit 64
}

running=0
delivered=0
pruned=0
spool_bytes=0
for ((index = 0; index < COUNT; index++)); do
    session=$(printf 'pvrig-top5000-mm-sync-%02d' "$index")
    root=$(printf '%s/shard%02d' "$BASE" "$index")
    delivered_file=$(printf '%s/state/top5000_multimodal.shard%02dof04.delivered_job_ids.txt' "$root" "$index")
    pruned_file=$(printf '%s/state/top5000_multimodal.shard%02dof04.pruned_job_ids.txt' "$root" "$index")
    delivered_count=$([[ -f "$delivered_file" ]] && wc -l <"$delivered_file" || echo 0)
    pruned_count=$([[ -f "$pruned_file" ]] && wc -l <"$pruned_file" || echo 0)
    bytes=$([[ -d "$root" ]] && du -sb "$root" | awk '{print $1}' || echo 0)
    state=STOPPED
    if tmux has-session -t "$session" 2>/dev/null; then
        state=RUNNING
        running=$((running + 1))
    fi
    printf 'shard=%02d state=%s delivered=%d pruned=%d spool_bytes=%d\n' \
        "$index" "$state" "$delivered_count" "$pruned_count" "$bytes"
    delivered=$((delivered + delivered_count))
    pruned=$((pruned + pruned_count))
    spool_bytes=$((spool_bytes + bytes))
done
printf 'TOTAL running=%d/4 delivered=%d/40000 pruned=%d/40000 spool_bytes=%d\n' \
    "$running" "$delivered" "$pruned" "$spool_bytes"
