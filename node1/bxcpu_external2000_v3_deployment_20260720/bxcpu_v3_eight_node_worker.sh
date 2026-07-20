#!/usr/bin/env bash
# One of eight exclusive 64-core nodes. Resume-safe over the 3,814 V3 safe jobs.
set -euo pipefail
umask 027

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
BUNDLE_ARCHIVE="$HOME/pvrig_v29_external2000_sequences_v3_20260720.tar.zst"
PROJECT_NAME=pvrig_v29_external2000_sequences_v3_20260720
PUBLISH_ROOT="${PVRIG_V3_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
SHARD_INDEX="${SLURM_ARRAY_TASK_ID:-1}"
SHARD_COUNT=8
NODE_CONCURRENCY="${PVRIG_V3_NODE_CONCURRENCY:-16}"

[[ "$SHARD_INDEX" =~ ^[1-8]$ ]] || { echo "shard index must be 1..8" >&2; exit 64; }
[[ "$NODE_CONCURRENCY" == 16 ]] || { echo "worker requires 16 concurrent 4-core jobs per node" >&2; exit 64; }
[[ "${SLURM_CPUS_ON_NODE:-64}" == 64 ]] || { echo "expected a 64-core Slurm allocation" >&2; exit 65; }

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/eight_${SLURM_ARRAY_JOB_ID:-manual}_${SHARD_INDEX}"
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

# Preserve prior failed-attempt counts. Successful jobs are excluded dynamically below.
rsync -a "$PUBLISH_ROOT/status/jobs/" "$LOCAL_PROJECT/status/jobs/"
mapfile -t JOB_IDS < <(awk -F'\t' -v shard="$SHARD_INDEX" -v count="$SHARD_COUNT" \
    'NR > 1 && ((NR - 2) % count) == (shard - 1) { print $1 }' "$SAFE_MANIFEST")
expected=476
(( SHARD_INDEX <= 6 )) && expected=477
[[ ${#JOB_IDS[@]} -eq "$expected" ]] || { echo "unexpected shard size ${#JOB_IDS[@]} expected $expected" >&2; exit 65; }

published_success() {
    local job_id=$1
    local status="$PUBLISH_ROOT/status/jobs/$job_id.json"
    local result="$PUBLISH_ROOT/results/$job_id/job_result.json"
    [[ -f "$status" && -f "$result" ]] || return 1
    "$LOCAL_ENV/bin/python" - "$status" "$result" <<'PY' >/dev/null 2>&1
import json, sys
s = json.load(open(sys.argv[1]))
r = json.load(open(sys.argv[2]))
raise SystemExit(0 if s.get("status") == "SUCCESS" and r.get("state") == "SUCCESS" else 1)
PY
}

run_one() {
    local job_id=$1
    local log="$PUBLISH_ROOT/worker_logs/${job_id}.log"
    local rc=1
    local call
    if published_success "$job_id"; then
        return 100
    fi
    [[ -f "$PUBLISH_ROOT/status/jobs/$job_id.json" ]] && \
        cp -f "$PUBLISH_ROOT/status/jobs/$job_id.json" "$LOCAL_PROJECT/status/jobs/$job_id.json"
    for call in 1 2; do
        if "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" "$job_id" --max-attempts 2 \
            >>"$log" 2>&1; then
            rc=0
            break
        else
            rc=$?
        fi
        attempts=$("$LOCAL_ENV/bin/python" - "$LOCAL_PROJECT/status/jobs/$job_id.json" <<'PY'
import json, sys
try: print(int(json.load(open(sys.argv[1])).get("attempts", 0)))
except Exception: print(0)
PY
)
        (( attempts < 2 )) || break
    done
    [[ -f "$LOCAL_PROJECT/status/jobs/$job_id.json" ]] && \
        rsync -a "$LOCAL_PROJECT/status/jobs/$job_id.json" "$PUBLISH_ROOT/status/jobs/"
    [[ -d "$LOCAL_PROJECT/results/$job_id" ]] && \
        rsync -a "$LOCAL_PROJECT/results/$job_id" "$PUBLISH_ROOT/results/"
    [[ -d "$LOCAL_PROJECT/runs/$job_id" ]] && \
        rsync -a "$LOCAL_PROJECT/runs/$job_id" "$PUBLISH_ROOT/runs/"
    return "$rc"
}

failures=0
skipped=0
pids=()
job_for_pid=()
drain_batch() {
    local i pid rc
    for i in "${!pids[@]}"; do
        pid=${pids[$i]}
        if wait "$pid"; then
            rc=0
        else
            rc=$?
        fi
        if [[ "$rc" == 100 ]]; then
            skipped=$((skipped + 1))
        elif [[ "$rc" != 0 ]]; then
            failures=$((failures + 1))
        fi
    done
    pids=()
    job_for_pid=()
}

for job_id in "${JOB_IDS[@]}"; do
    run_one "$job_id" &
    pids+=("$!")
    job_for_pid+=("$job_id")
    if [[ ${#pids[@]} -eq "$NODE_CONCURRENCY" ]]; then
        drain_batch
    fi
done
[[ ${#pids[@]} -eq 0 ]] || drain_batch

marker="$PUBLISH_ROOT/markers/v3_8shard_${SHARD_INDEX}.done"
printf 'array_job=%s shard=%s assigned=%s skipped_existing_success=%s failures=%s completed_at=%s\n' \
    "${SLURM_ARRAY_JOB_ID:-manual}" "$SHARD_INDEX" "${#JOB_IDS[@]}" "$skipped" "$failures" "$(date -u +%FT%TZ)" > "$marker"
exit "$failures"
