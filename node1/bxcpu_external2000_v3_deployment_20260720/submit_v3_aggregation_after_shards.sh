#!/usr/bin/env bash
# Usage: ./submit_v3_aggregation_after_shards.sh <array-job-id>
set -euo pipefail

[[ $# == 1 && "$1" =~ ^[0-9]+$ ]] || { echo "usage: $0 <array-job-id>" >&2; exit 64; }
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_NAME=pvrig_v29_external2000_sequences_v3_20260720
PUBLISH_ROOT="${PVRIG_V3_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
mkdir -p "$PUBLISH_ROOT"

exec sbatch \
    --dependency="afterany:${1}_1:${1}_2" \
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
    "$SCRIPT_DIR/aggregate_v3_after_shards.sh"
