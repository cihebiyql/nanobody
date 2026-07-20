#!/usr/bin/env bash
# Submit eight exclusive 64-core nodes plus one dependent shard-specific aggregator.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_NAME=pvrig_v29_external2000_sequences_v3_20260720
PUBLISH_ROOT="${PVRIG_V3_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
mkdir -p "$PUBLISH_ROOT" "$PUBLISH_ROOT/markers"

active=$(squeue -h -u "$USER" -n pvrig-v3-ext2000,pvrig-v3-ext8,pvrig-v3-aggregate | wc -l)
[[ "$active" -eq 0 ]] || { echo "refusing launch: $active old campaign jobs still active" >&2; exit 66; }

array_id=$(sbatch --parsable \
    --partition=amd_256q \
    --job-name=pvrig-v3-ext8 \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=64 \
    --mem=230G \
    --exclusive \
    --time=24:00:00 \
    --array=1-8%8 \
    --output="$PUBLISH_ROOT/slurm-%x-%A_%a.out" \
    --error="$PUBLISH_ROOT/slurm-%x-%A_%a.err" \
    --export=ALL,PVRIG_V3_NODE_CONCURRENCY=16 \
    "$SCRIPT_DIR/bxcpu_v3_eight_node_worker.sh")
array_id=${array_id%%;*}

dependency=afterany
for shard in {1..8}; do dependency+=":${array_id}_${shard}"; done
agg_id=$(sbatch --parsable \
    --dependency="$dependency" \
    --partition=amd_256q \
    --job-name=pvrig-v3-aggregate \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=1 \
    --mem=4G \
    --exclusive \
    --time=02:00:00 \
    --output="$PUBLISH_ROOT/slurm-%x-%j.out" \
    --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
    "$SCRIPT_DIR/aggregate_v3_after_shards.sh")
agg_id=${agg_id%%;*}

printf 'array_job_id=%s\naggregate_job_id=%s\nsubmitted_at=%s\n' \
    "$array_id" "$agg_id" "$(date -u +%FT%TZ)" | tee "$PUBLISH_ROOT/markers/v3_8node_submission.receipt"
