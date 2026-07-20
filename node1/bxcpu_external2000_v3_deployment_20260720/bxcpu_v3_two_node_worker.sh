#!/usr/bin/env bash
# One exclusive 64-core node. Two Slurm array tasks split the 3,814 safe jobs.
set -euo pipefail
umask 027

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
BUNDLE_ARCHIVE="$HOME/pvrig_v29_external2000_sequences_v3_20260720.tar.zst"
PROJECT_NAME=pvrig_v29_external2000_sequences_v3_20260720
PUBLISH_ROOT="${PVRIG_V3_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
SHARD_INDEX="${SLURM_ARRAY_TASK_ID:-1}"
SHARD_COUNT=2
NODE_CONCURRENCY="${PVRIG_V3_NODE_CONCURRENCY:-16}"

[[ "$SHARD_INDEX" =~ ^[12]$ ]] || { echo "shard index must be 1 or 2" >&2; exit 64; }
[[ "$NODE_CONCURRENCY" == 16 ]] || { echo "V3 worker requires 16 concurrent 4-core jobs per node" >&2; exit 64; }
[[ "${SLURM_CPUS_ON_NODE:-64}" == 64 ]] || { echo "expected a 64-core Slurm allocation" >&2; exit 65; }

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/${SLURM_JOB_ID:-manual}_${SHARD_INDEX}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
LOCAL_SOURCE="$WORK_BASE/haddock3-source"
NUMPY_OVERLAY="$WORK_BASE/numpy-el7-overlay"
LOCAL_PROJECT="$WORK_BASE/$PROJECT_NAME"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$LOCAL_SOURCE" "$NUMPY_OVERLAY" "$LOCAL_SCRATCH" \
    "$PUBLISH_ROOT/status/jobs" "$PUBLISH_ROOT/results" "$PUBLISH_ROOT/runs" \
    "$PUBLISH_ROOT/worker_logs" "$PUBLISH_ROOT/markers" "$PUBLISH_ROOT/reports"

for archive in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz; do
    tar -xzf "$CACHE_ROOT/$archive" -C "$LOCAL_ENV"
done
tar -xzf "$CACHE_ROOT/haddock3_source_2025.11.0.tar.gz" -C "$LOCAL_SOURCE"
tar -xzf "$CACHE_ROOT/numpy_el7_overlay_2.0.1.tar.gz" -C "$NUMPY_OVERLAY"

export PATH="$LOCAL_ENV/bin:$PATH"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$NUMPY_OVERLAY/lib/python3.11/site-packages:$LOCAL_SOURCE/src"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_MAX_THREADS=1
"$LOCAL_ENV/bin/python" -m haddock.clis.cli --version | head -n 1 | grep -Fx 'cli.py - 2025.11.0'
"$LOCAL_ENV/bin/python" -c 'import numpy; assert numpy.__version__ == "2.0.1"'
"$LOCAL_ENV/bin/zstd" -dc "$BUNDLE_ARCHIVE" | tar -xf - -C "$WORK_BASE"

SAFE_MANIFEST="$LOCAL_PROJECT/manifests/external_ready_now_jobs.tsv"
[[ $(wc -l < "$SAFE_MANIFEST") -eq 3815 ]] || { echo "unexpected safe manifest" >&2; exit 65; }
[[ -f "$LOCAL_PROJECT/reports/reference_normalization_summary.json" ]] || { echo "missing V3 score reference" >&2; exit 65; }
[[ -f "$LOCAL_PROJECT/scripts/aggregate_external2000_results.py" ]] || { echo "missing V3 external aggregator" >&2; exit 65; }

mapfile -t JOB_IDS < <(awk -F'\t' -v shard="$SHARD_INDEX" -v count="$SHARD_COUNT" \
    'NR > 1 && ((NR - 2) % count) == (shard - 1) { print $1 }' "$SAFE_MANIFEST")
[[ ${#JOB_IDS[@]} -eq 1907 ]] || { echo "unexpected V3 shard size: ${#JOB_IDS[@]}" >&2; exit 65; }

export PVRIG_PROJECT_ROOT="$LOCAL_PROJECT"
export PVRIG_LOCAL_SCRATCH_ROOT="$LOCAL_SCRATCH"
export PVRIG_HADDOCK_CMD="$LOCAL_ENV/bin/python -m haddock.clis.cli haddock3.cfg"

run_one() {
    local job_id=$1
    local rc=0
    if "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" "$job_id" --max-attempts 2 \
        >"$PUBLISH_ROOT/worker_logs/${job_id}.log" 2>&1; then
        rc=0
    else
        rc=$?
    fi
    [[ -f "$LOCAL_PROJECT/status/jobs/$job_id.json" ]] && \
        rsync -a "$LOCAL_PROJECT/status/jobs/$job_id.json" "$PUBLISH_ROOT/status/jobs/"
    [[ -d "$LOCAL_PROJECT/results/$job_id" ]] && \
        rsync -a "$LOCAL_PROJECT/results/$job_id" "$PUBLISH_ROOT/results/"
    [[ -d "$LOCAL_PROJECT/runs/$job_id" ]] && \
        rsync -a "$LOCAL_PROJECT/runs/$job_id" "$PUBLISH_ROOT/runs/"
    return "$rc"
}

failures=0
pids=()
drain_batch() {
    local pid
    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            failures=$((failures + 1))
        fi
    done
    pids=()
}

for job_id in "${JOB_IDS[@]}"; do
    run_one "$job_id" &
    pids+=("$!")
    if [[ ${#pids[@]} -eq "$NODE_CONCURRENCY" ]]; then
        drain_batch
    fi
done
[[ ${#pids[@]} -eq 0 ]] || drain_batch

marker="$PUBLISH_ROOT/markers/v3_shard_${SHARD_INDEX}.done"
printf 'shard=%s failures=%s completed_at=%s\n' "$SHARD_INDEX" "$failures" "$(date -u +%FT%TZ)" > "$marker"

if [[ "$SHARD_INDEX" == 1 ]]; then
    other_marker="$PUBLISH_ROOT/markers/v3_shard_2.done"
    for ((minute = 0; minute < 1440; minute++)); do
        [[ -f "$other_marker" ]] && break
        sleep 60
    done
    [[ -f "$other_marker" ]] || { echo "timed out waiting for shard 2" >&2; exit 70; }
    rsync -a "$PUBLISH_ROOT/status/jobs/" "$LOCAL_PROJECT/status/jobs/"
    rsync -a "$PUBLISH_ROOT/results/" "$LOCAL_PROJECT/results/"
    set +e
    "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/aggregate_external2000_results.py" --root "$LOCAL_PROJECT"
    aggregate_rc=$?
    set -e
    [[ "$aggregate_rc" == 0 || "$aggregate_rc" == 1 ]] || exit "$aggregate_rc"
    rsync -a "$LOCAL_PROJECT/reports/external_job_results.tsv" \
        "$LOCAL_PROJECT/reports/external_pose_scores.tsv" \
        "$LOCAL_PROJECT/reports/external_candidate_dual.tsv" \
        "$LOCAL_PROJECT/reports/EXTERNAL2000_AGGREGATION.json" "$PUBLISH_ROOT/reports/"
fi

exit "$failures"
