#!/usr/bin/env bash
set -euo pipefail
DEPLOY=$(cd "$(dirname "$0")" && pwd)
NAME=pvrig_v29_bxcpu_stage3_node20_v1_20260720
ROOT="${PVRIG_STAGE3_PUBLISH_ROOT:-$HOME/${NAME}_bxcpu_results}"
ARCHIVE="$HOME/$NAME.tar.zst"
EXPECTED=9f9149b0048182ada1d7765d63115cc607a674434dd4d11e3713b733c20c407f
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$EXPECTED" ]] || {
    echo archive_hash_mismatch >&2
    exit 65
}
mkdir -p "$ROOT" "$ROOT/markers"
exec 9>"$ROOT/markers/stage3_submission.lock"
flock -n 9 || exit 0
[[ ! -s "$ROOT/markers/stage3_node20_submission.receipt" ]] || exit 0
active=$(squeue -h -u "$USER" -n pvrig-v29-s3-node20 | wc -l)
[[ "$active" -eq 0 ]] || { echo "Stage3 already active: $active" >&2; exit 66; }
array=$(sbatch --parsable --partition=amd_256q --job-name=pvrig-v29-s3-node20 \
    --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G --exclusive --time=04:00:00 \
    --array=1-8%8 --output="$ROOT/slurm-%x-%A_%a.out" --error="$ROOT/slurm-%x-%A_%a.err" \
    --export=ALL,PVRIG_V3_NODE_CONCURRENCY=16,PVRIG_V3_PUBLISH_ROOT="$ROOT" \
    "$DEPLOY/bxcpu_stage3_node20_eight_node_worker.sh")
array=${array%%;*}
dependency=afterany
for shard in {1..8}; do dependency+=":${array}_${shard}"; done
aggregate=$(sbatch --parsable --dependency="$dependency" --partition=amd_256q \
    --job-name=pvrig-v29-s3-agg --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=4G \
    --exclusive --time=02:00:00 --output="$ROOT/slurm-%x-%j.out" \
    --error="$ROOT/slurm-%x-%j.err" "$DEPLOY/aggregate_stage3_node20_after_shards.sh")
aggregate=${aggregate%%;*}
printf 'array_job_id=%s\naggregate_job_id=%s\nsubmitted_at=%s\n' \
    "$array" "$aggregate" "$(date -u +%FT%TZ)" \
    | tee "$ROOT/markers/stage3_node20_submission.receipt"
