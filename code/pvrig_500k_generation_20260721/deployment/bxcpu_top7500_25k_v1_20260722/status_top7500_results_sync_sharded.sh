#!/usr/bin/env bash
set -euo pipefail
BASE=${PVRIG_BXCPU_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/pvrig_top7500_25k_bxcpu_incremental_spool_20260722}
COUNT=${PVRIG_BXCPU_SYNC_SHARDS:-4}
running=0 delivered=0 pruned=0
for ((i=0; i<COUNT; i++)); do
    session=$(printf 'pvrig-top7500-result-sync-%02d' "$i")
    root=$(printf '%s/shard%02d' "$BASE" "$i")
    dfile=$(printf '%s/state/top7500_25k.shard%02dof%02d.delivered_job_ids.txt' "$root" "$i" "$COUNT")
    pfile=$(printf '%s/state/top7500_25k.shard%02dof%02d.pruned_job_ids.txt' "$root" "$i" "$COUNT")
    d=$([[ -f "$dfile" ]] && wc -l <"$dfile" || echo 0)
    p=$([[ -f "$pfile" ]] && wc -l <"$pfile" || echo 0)
    state=STOPPED
    if tmux has-session -t "$session" 2>/dev/null; then state=RUNNING; running=$((running+1)); fi
    printf 'shard=%02d state=%s delivered=%d pruned=%d\n' "$i" "$state" "$d" "$p"
    delivered=$((delivered+d)); pruned=$((pruned+p))
done
printf 'TOTAL running=%d/%d delivered=%d pruned=%d\n' "$running" "$COUNT" "$delivered" "$pruned"
