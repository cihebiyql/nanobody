#!/usr/bin/env bash
# Submit only the node21-safe subset.  Default throttling is intentionally conservative.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT="${PVRIG_PROJECT_ROOT:-$HOME/pvrig_v29_external2000_sequences_v2_20260720}"
ENV_ROOT="${PVRIG_HADDOCK_ENV:-$HOME/.local/opt/haddock3-2025.11.0}"
HADDOCK_SOURCE="${PVRIG_HADDOCK_SOURCE:-$HOME/.local/opt/haddock3-source-2025.11.0/src}"
ARRAY_SPEC="${1:-1-3814%64}"

[[ -f "$PROJECT_ROOT/manifests/external_ready_now_jobs.tsv" ]] || {
    echo "safe manifest not found under $PROJECT_ROOT" >&2
    exit 66
}
[[ $(wc -l < "$PROJECT_ROOT/manifests/external_ready_now_jobs.tsv") -eq 3815 ]] || {
    echo "safe manifest count is not 3814 jobs" >&2
    exit 65
}
[[ -x "$ENV_ROOT/bin/haddock3" ]] || { echo "HADDOCK environment missing: $ENV_ROOT" >&2; exit 69; }
[[ -d "$HADDOCK_SOURCE/haddock" ]] || { echo "HADDOCK source missing: $HADDOCK_SOURCE" >&2; exit 69; }
mkdir -p "$PROJECT_ROOT/logs/slurm"

exec sbatch \
    --partition=amd_256q \
    --job-name=pvrig-ext2000 \
    --cpus-per-task=4 \
    --mem=16G \
    --time=24:00:00 \
    --array="$ARRAY_SPEC" \
    --output="$PROJECT_ROOT/logs/slurm/%x-%A_%a.out" \
    --error="$PROJECT_ROOT/logs/slurm/%x-%A_%a.err" \
    --export=ALL,PVRIG_PROJECT_ROOT="$PROJECT_ROOT",PVRIG_HADDOCK_ENV="$ENV_ROOT",PVRIG_HADDOCK_SOURCE="$HADDOCK_SOURCE" \
    "$SCRIPT_DIR/bxcpu_external2000_job.sh"
