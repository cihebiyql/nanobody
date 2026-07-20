#!/usr/bin/env bash
# Default: 477 workers x 8 jobs = 3814 safe-now jobs.  This script does not submit by itself.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_NAME=pvrig_v29_external2000_sequences_v2_20260720
ARRAY_SPEC="${1:-1-477%32}"
BATCH_SIZE="${PVRIG_JOB_BATCH_SIZE:-8}"
mkdir -p "$HOME/${PROJECT_NAME}_bxcpu_results"

exec sbatch \
    --partition=amd_256q \
    --job-name=pvrig-ext2000 \
    --cpus-per-task=4 \
    --mem=16G \
    --time=24:00:00 \
    --array="$ARRAY_SPEC" \
    --output="$HOME/${PROJECT_NAME}_bxcpu_results/slurm-%x-%A_%a.out" \
    --error="$HOME/${PROJECT_NAME}_bxcpu_results/slurm-%x-%A_%a.err" \
    --export=ALL,PVRIG_JOB_BATCH_SIZE="$BATCH_SIZE",PVRIG_DEPLOY_ROOT="$SCRIPT_DIR" \
    "$SCRIPT_DIR/bxcpu_portable_worker.sh"
