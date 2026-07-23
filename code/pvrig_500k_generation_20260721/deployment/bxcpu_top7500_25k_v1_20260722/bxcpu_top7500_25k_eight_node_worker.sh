#!/usr/bin/env bash
set -euo pipefail
umask 027

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
PROJECT_NAME=pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722
BUNDLE_ARCHIVE="$HOME/${PROJECT_NAME}.tar.zst"
EXPECTED_ARCHIVE_SHA256="${PVRIG_TOP7500_ARCHIVE_SHA256:-359a695f4d6d823ae7f0cf76abaf45e7665ec404bf4a38f5179d66abc86f6919}"
PUBLISH_ROOT="${PVRIG_TOP7500_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
SHARD_INDEX="${SLURM_ARRAY_TASK_ID:-1}"
SHARD_COUNT=8
NODE_CONCURRENCY="${PVRIG_TOP7500_NODE_CONCURRENCY:-16}"

[[ "$SHARD_INDEX" =~ ^[1-8]$ ]] || { echo "shard index must be 1..8" >&2; exit 64; }
[[ "$NODE_CONCURRENCY" == 16 ]] || { echo "worker requires 16 concurrent 4-core jobs" >&2; exit 64; }
[[ "${SLURM_CPUS_ON_NODE:-64}" == 64 ]] || { echo "expected 64 allocated CPUs" >&2; exit 65; }
[[ $(sha256sum "$BUNDLE_ARCHIVE" | awk '{print $1}') == "$EXPECTED_ARCHIVE_SHA256" ]] || {
    echo "bundle SHA256 mismatch" >&2; exit 65;
}

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/${SLURM_ARRAY_JOB_ID:-manual}_${SHARD_INDEX}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
LOCAL_SOURCE="$WORK_BASE/haddock3-source"
NUMPY_OVERLAY="$WORK_BASE/numpy-el7-overlay"
LOCAL_PROJECT="$WORK_BASE/$PROJECT_NAME"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$LOCAL_SOURCE" "$NUMPY_OVERLAY" "$LOCAL_SCRATCH" \
    "$PUBLISH_ROOT/status/jobs" "$PUBLISH_ROOT/results" "$PUBLISH_ROOT/worker_logs" \
    "$PUBLISH_ROOT/compressed_queue" "$PUBLISH_ROOT/markers" "$PUBLISH_ROOT/reports"

for archive in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz; do
    tar -xzf "$CACHE_ROOT/$archive" -C "$LOCAL_ENV"
done
tar -xzf "$CACHE_ROOT/haddock3_source_2025.11.0.tar.gz" -C "$LOCAL_SOURCE"
tar -xzf "$CACHE_ROOT/numpy_el7_overlay_2.0.1.tar.gz" -C "$NUMPY_OVERLAY"

export PATH="$LOCAL_ENV/bin:$PATH"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$NUMPY_OVERLAY/lib/python3.11/site-packages:$LOCAL_SOURCE/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
"$LOCAL_ENV/bin/python" -m haddock.clis.cli --version | head -n 1 | grep -Fx 'cli.py - 2025.11.0'
"$LOCAL_ENV/bin/python" -c 'import numpy; assert numpy.__version__ == "2.0.1"'
"$LOCAL_ENV/bin/zstd" -dc "$BUNDLE_ARCHIVE" | tar -xf - -C "$WORK_BASE"

SHARD_ZERO=$((SHARD_INDEX - 1))
SAFE_MANIFEST=$(printf '%s/manifests/shards_recommended_8/shard_%02d.tsv' "$LOCAL_PROJECT" "$SHARD_ZERO")
[[ -f "$SAFE_MANIFEST" ]] || { echo "missing shard manifest: $SAFE_MANIFEST" >&2; exit 65; }
[[ -f "$LOCAL_PROJECT/reports/reference_normalization_summary.json" ]] || { echo missing_reference_summary >&2; exit 65; }
[[ -f "$LOCAL_PROJECT/scripts/run_job.py" ]] || { echo missing_run_job >&2; exit 65; }
mapfile -t JOB_IDS < <(awk -F'\t' 'NR>1{print $1}' "$SAFE_MANIFEST")
expected=3124
(( SHARD_INDEX <= 4 )) && expected=3126
[[ ${#JOB_IDS[@]} -eq "$expected" ]] || {
    echo "unexpected shard size ${#JOB_IDS[@]} expected $expected" >&2; exit 65;
}

published_success() {
    local job_id=$1 status="$PUBLISH_ROOT/status/jobs/$job_id.json" result="$PUBLISH_ROOT/results/$job_id/job_result.json"
    [[ -f "$status" && -f "$result" ]] || return 1
    "$LOCAL_ENV/bin/python" - "$status" "$result" "$PUBLISH_ROOT/compressed_queue/$job_id.tar.gz" <<'PY' >/dev/null 2>&1
import json, pathlib, sys
s=json.load(open(sys.argv[1])); r=json.load(open(sys.argv[2])); compact=pathlib.Path(sys.argv[3])
ok=s.get("status")=="SUCCESS" and r.get("state")=="SUCCESS"
ok=ok and (compact.is_file() or r.get("offloaded_to_node1") is True)
raise SystemExit(0 if ok else 1)
PY
}

publish_status_last() {
    local job_id=$1 src="$LOCAL_PROJECT/status/jobs/$job_id.json"
    [[ -f "$src" ]] || return 0
    local tmp="$PUBLISH_ROOT/status/jobs/.$job_id.json.partial.$$"
    cp -f "$src" "$tmp"
    mv -f "$tmp" "$PUBLISH_ROOT/status/jobs/$job_id.json"
}

run_one() {
    local job_id=$1 log="$PUBLISH_ROOT/worker_logs/${job_id}.log" rc=1 call attempts tmp_result tmp_compact
    if published_success "$job_id"; then return 100; fi
    [[ -f "$PUBLISH_ROOT/status/jobs/$job_id.json" ]] && \
        cp -f "$PUBLISH_ROOT/status/jobs/$job_id.json" "$LOCAL_PROJECT/status/jobs/$job_id.json"
    for call in 1 2; do
        if PVRIG_PROJECT_ROOT="$LOCAL_PROJECT" PVRIG_LOCAL_SCRATCH_ROOT="$LOCAL_SCRATCH" \
            "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" "$job_id" --max-attempts 2 >>"$log" 2>&1; then
            rc=0; break
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

    if [[ "$rc" == 0 ]]; then
        tmp_result="$PUBLISH_ROOT/results/.$job_id.partial.$$"
        rm -rf "$tmp_result"
        cp -a "$LOCAL_PROJECT/results/$job_id" "$tmp_result"
        rm -rf "$PUBLISH_ROOT/results/$job_id"
        mv "$tmp_result" "$PUBLISH_ROOT/results/$job_id"

        tmp_compact="$PUBLISH_ROOT/compressed_queue/.$job_id.tar.gz.partial.$$"
        rm -f "$tmp_compact"
        "$LOCAL_ENV/bin/python" "$HOME/.local/share/bxcpu_top7500_25k_v1_20260722/compact_run_evidence.py" \
            --project-root "$LOCAL_PROJECT" --job-id "$job_id" --output "$tmp_compact" >>"$log" 2>&1
        mv -f "$tmp_compact" "$PUBLISH_ROOT/compressed_queue/$job_id.tar.gz"
        rm -rf "$LOCAL_PROJECT/runs/$job_id"
    fi
    publish_status_last "$job_id"
    return "$rc"
}

failures=0; skipped=0; pids=()
drain_batch() {
    local pid rc
    for pid in "${pids[@]}"; do
        if wait "$pid"; then rc=0; else rc=$?; fi
        if [[ "$rc" == 100 ]]; then skipped=$((skipped+1)); elif [[ "$rc" != 0 ]]; then failures=$((failures+1)); fi
    done
    pids=()
}
for job_id in "${JOB_IDS[@]}"; do
    run_one "$job_id" & pids+=("$!")
    [[ ${#pids[@]} -lt "$NODE_CONCURRENCY" ]] || drain_batch
done
[[ ${#pids[@]} -eq 0 ]] || drain_batch

marker="$PUBLISH_ROOT/markers/top7500_25k_shard_${SHARD_INDEX}.done"
printf 'array_job=%s shard=%s assigned=%s skipped=%s failures=%s completed_at=%s\n' \
    "${SLURM_ARRAY_JOB_ID:-manual}" "$SHARD_INDEX" "${#JOB_IDS[@]}" "$skipped" "$failures" "$(date -u +%FT%TZ)" > "$marker"
exit "$failures"
