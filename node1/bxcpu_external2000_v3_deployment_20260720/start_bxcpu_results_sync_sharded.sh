#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
BASE=${PVRIG_BXCPU_SYNC_LOCAL_BASE:-/mnt/d/work/抗体/node1/bxcpu_incremental_spool_20260720}
COUNT=${PVRIG_BXCPU_SYNC_SHARDS:-8}
BATCH=${PVRIG_BXCPU_SYNC_BATCH_SIZE:-20}
STABLE=${PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS:-180}
POLL=${PVRIG_BXCPU_SYNC_POLL_SECONDS:-15}

python3 - "$BASE" "$COUNT" <<'PY'
import hashlib, pathlib, sys
base=pathlib.Path(sys.argv[1]); count=int(sys.argv[2])
for campaign in ("stage2", "stage3_node20"):
    for kind in ("delivered", "pruned"):
        source=base/"state"/f"{campaign}.{kind}_job_ids.txt"
        existing=[x for x in source.read_text().splitlines() if x] if source.exists() else []
        for index in range(count):
            root=base/f"shard{index:02d}"
            state=root/"state"; state.mkdir(parents=True, exist_ok=True)
            target=state/f"{campaign}.shard{index:02d}of{count:02d}.{kind}_job_ids.txt"
            if target.exists():
                continue
            selected=[job for job in existing if int(hashlib.sha256(job.encode()).hexdigest()[:16],16)%count==index]
            target.write_text("\n".join(selected)+("\n" if selected else ""))
PY

for ((i=0; i<COUNT; i++)); do
    root=$(printf '%s/shard%02d' "$BASE" "$i")
    session=$(printf 'pvrig-bxcpu-result-sync-%02d' "$i")
    log="$root/state/sync.nohup.log"
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "$session already running"
        continue
    fi
    command=$(printf 'exec env PVRIG_BXCPU_SYNC_LOCAL_ROOT=%q PVRIG_BXCPU_SYNC_SHARD_COUNT=%q PVRIG_BXCPU_SYNC_SHARD_INDEX=%q PVRIG_BXCPU_SYNC_BATCH_SIZE=%q PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS=%q PVRIG_BXCPU_SYNC_POLL_SECONDS=%q python3 %q >>%q 2>&1' \
        "$root" "$COUNT" "$i" "$BATCH" "$STABLE" "$POLL" \
        "$DEPLOY/sync_bxcpu_results_incremental.py" "$log")
    tmux new-session -d -s "$session" "$command"
    echo "$session started"
done

