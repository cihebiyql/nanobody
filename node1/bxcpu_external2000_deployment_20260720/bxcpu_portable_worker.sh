#!/usr/bin/env bash
# Run a contiguous, safe-only slice locally on a Slurm compute node.
set -euo pipefail
umask 027

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
BUNDLE_ARCHIVE="$HOME/pvrig_v29_external2000_sequences_v2_20260720.tar.zst"
PROJECT_NAME=pvrig_v29_external2000_sequences_v2_20260720
PUBLISH_ROOT="${PVRIG_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
ARRAY_INDEX="${SLURM_ARRAY_TASK_ID:-1}"
BATCH_SIZE="${PVRIG_JOB_BATCH_SIZE:-8}"

[[ "$ARRAY_INDEX" =~ ^[1-9][0-9]*$ && "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]] || {
    echo "invalid array index or batch size" >&2
    exit 64
}

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/${SLURM_JOB_ID:-manual}_${ARRAY_INDEX}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
LOCAL_SOURCE="$WORK_BASE/haddock3-source"
LOCAL_PROJECT="$WORK_BASE/$PROJECT_NAME"
mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$LOCAL_SOURCE" "$PUBLISH_ROOT/status/jobs" "$PUBLISH_ROOT/results" "$PUBLISH_ROOT/runs"

for archive in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz; do
    tar -xzf "$CACHE_ROOT/$archive" -C "$LOCAL_ENV"
done
tar -xzf "$CACHE_ROOT/haddock3_source_2025.11.0.tar.gz" -C "$LOCAL_SOURCE"

export PATH="$LOCAL_ENV/bin:$PATH"
export PYTHONPATH="$LOCAL_SOURCE/src${PYTHONPATH:+:$PYTHONPATH}"
"$LOCAL_ENV/bin/python" -m haddock.clis.cli --version | head -n 1 | grep -Fx 'cli.py - 2025.11.0'
"$LOCAL_ENV/bin/zstd" -dc "$BUNDLE_ARCHIVE" | tar -xf - -C "$WORK_BASE"

SAFE_MANIFEST="$LOCAL_PROJECT/manifests/external_ready_now_jobs.tsv"
[[ $(wc -l < "$SAFE_MANIFEST") -eq 3815 ]] || { echo "unexpected safe manifest" >&2; exit 65; }
first_line=$((2 + (ARRAY_INDEX - 1) * BATCH_SIZE))
last_line=$((first_line + BATCH_SIZE - 1))
failures=0

while IFS=$'\t' read -r job_id _; do
    [[ -n "$job_id" ]] || continue
    export PVRIG_PROJECT_ROOT="$LOCAL_PROJECT"
    export PVRIG_HADDOCK_CMD="$LOCAL_ENV/bin/python -m haddock.clis.cli haddock3.cfg"
    if ! "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" "$job_id" --max-attempts 2; then
        failures=1
    fi
    [[ -f "$LOCAL_PROJECT/status/jobs/$job_id.json" ]] && \
        rsync -a "$LOCAL_PROJECT/status/jobs/$job_id.json" "$PUBLISH_ROOT/status/jobs/"
    [[ -d "$LOCAL_PROJECT/results/$job_id" ]] && \
        rsync -a "$LOCAL_PROJECT/results/$job_id" "$PUBLISH_ROOT/results/"
    [[ -d "$LOCAL_PROJECT/runs/$job_id" ]] && \
        rsync -a "$LOCAL_PROJECT/runs/$job_id" "$PUBLISH_ROOT/runs/"
done < <(sed -n "${first_line},${last_line}p" "$SAFE_MANIFEST")

exit "$failures"
