#!/usr/bin/env bash
# Submit exactly two exclusive 64-core amd_256q nodes for the V3 safe subset.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_NAME=pvrig_v29_external2000_sequences_v3_20260720
PUBLISH_ROOT="${PVRIG_V3_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
mkdir -p "$PUBLISH_ROOT"

exec sbatch \
    --partition=amd_256q \
    --job-name=pvrig-v3-ext2000 \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=64 \
    --mem=230G \
    --exclusive \
    --time=24:00:00 \
    --array=1-2%2 \
    --output="$PUBLISH_ROOT/slurm-%x-%A_%a.out" \
    --error="$PUBLISH_ROOT/slurm-%x-%A_%a.err" \
    --export=ALL,PVRIG_V3_NODE_CONCURRENCY=16 \
    "$SCRIPT_DIR/bxcpu_v3_two_node_worker.sh"
