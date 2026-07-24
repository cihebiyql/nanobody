#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_TOP5000_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_top5000_multimodal_4seed_v1_20260724/runtime}"
# shellcheck source=bxcpu_runtime_common.sh
source "$DEPLOY_ROOT/bxcpu_runtime_common.sh"

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
PROJECT_NAME="${PVRIG_TOP5000_PROJECT_NAME:-pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724}"
PROJECT_DIR="${PVRIG_TOP5000_PROJECT_DIR:-$PROJECT_NAME}"
BUNDLE_ARCHIVE="${PVRIG_TOP5000_BUNDLE_ARCHIVE:-$HOME/${PROJECT_NAME}.tar.zst}"
EXTERNAL_MANIFEST="${PVRIG_TOP5000_MANIFEST_PATH:-$HOME/${PROJECT_NAME}.manifest.tsv}"
READY_PATH="${PVRIG_TOP5000_READY_PATH:-$HOME/${PROJECT_NAME}.READY.json}"
PUBLISH_ROOT="${PVRIG_TOP5000_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
MANIFEST_RELATIVE="${PVRIG_TOP5000_MANIFEST_RELATIVE:-manifests/docking_jobs.tsv}"
SHARD_DIR_RELATIVE="${PVRIG_TOP5000_SHARD_DIR_RELATIVE:-manifests/shards_exact_8}"
RECEIPT_RELATIVE="${PVRIG_TOP5000_RECEIPT_RELATIVE:-HANDOFF_RECEIPT.json}"
READY_RELATIVE="${PVRIG_TOP5000_READY_RELATIVE:-READY.json}"
READY_STATUS="${PVRIG_TOP5000_READY_STATUS:-READY_FOR_EXTERNAL_DOCKING_SUBMISSION}"
RECEIPT_STATUS="${PVRIG_TOP5000_RECEIPT_STATUS:-READY_FOR_EXTERNAL_DOCKING_SUBMISSION}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_TOP5000_ARCHIVE_SHA256:?archive SHA256 is required}"
EXPECTED_MANIFEST_SHA256="${PVRIG_TOP5000_MANIFEST_SHA256:?manifest SHA256 is required}"
EXPECTED_READY_SHA256="${PVRIG_TOP5000_READY_SHA256:?READY SHA256 is required}"
EXPECTED_RECEIPT_SHA256="${PVRIG_TOP5000_RECEIPT_SHA256:?receipt SHA256 is required}"

SHARD_INDEX="${SLURM_ARRAY_TASK_ID:-1}"
SHARD_COUNT=8
JOBS_PER_SHARD=5000
JOB_CPUS=4
NODE_CONCURRENCY="${PVRIG_TOP5000_NODE_CONCURRENCY:-16}"

[[ "$SHARD_INDEX" =~ ^[1-8]$ ]] || pvrig_die "shard index must be 1..8"
[[ "$NODE_CONCURRENCY" == 16 ]] ||
    pvrig_die "worker requires exactly 16 concurrent jobs"
[[ "$((NODE_CONCURRENCY * JOB_CPUS))" == 64 ]] ||
    pvrig_die "worker concurrency must consume 64 CPUs as 16x4"
[[ "${SLURM_CPUS_ON_NODE:-64}" == 64 ]] || pvrig_die "expected 64 allocated CPUs"
for name in \
    EXPECTED_ARCHIVE_SHA256 \
    EXPECTED_MANIFEST_SHA256 \
    EXPECTED_READY_SHA256 \
    EXPECTED_RECEIPT_SHA256; do
    pvrig_require_sha256 "$name"
done
pvrig_check_sha256 "$BUNDLE_ARCHIVE" "$EXPECTED_ARCHIVE_SHA256" archive
pvrig_check_sha256 "$EXTERNAL_MANIFEST" "$EXPECTED_MANIFEST_SHA256" manifest
pvrig_check_sha256 "$READY_PATH" "$EXPECTED_READY_SHA256" READY

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/${SLURM_ARRAY_JOB_ID:-manual}_${SHARD_INDEX}"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
LOCAL_PROJECT="$WORK_BASE/$PROJECT_DIR"
mkdir -p \
    "$WORK_BASE" \
    "$LOCAL_SCRATCH" \
    "$PUBLISH_ROOT/status/jobs" \
    "$PUBLISH_ROOT/results" \
    "$PUBLISH_ROOT/worker_logs" \
    "$PUBLISH_ROOT/compressed_queue" \
    "$PUBLISH_ROOT/markers" \
    "$PUBLISH_ROOT/reports"

if [[ "${PVRIG_TOP5000_KEEP_LOCAL_WORK:-0}" != 1 ]]; then
    trap 'rm -rf "$WORK_BASE"' EXIT
fi

pvrig_unpack_runtime "$CACHE_ROOT" "$WORK_BASE"
pvrig_validate_runtime
"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/runtime_contract.py" validate-ready \
    --ready "$READY_PATH" \
    --ready-sha256 "$EXPECTED_READY_SHA256" \
    --ready-status "$READY_STATUS" \
    --archive-sha256 "$EXPECTED_ARCHIVE_SHA256" \
    --manifest-sha256 "$EXPECTED_MANIFEST_SHA256" \
    --receipt-sha256 "$EXPECTED_RECEIPT_SHA256" >/dev/null
pvrig_extract_bundle "$BUNDLE_ARCHIVE" "$WORK_BASE"
[[ -d "$LOCAL_PROJECT" && ! -L "$LOCAL_PROJECT" ]] ||
    pvrig_die "bundle did not produce project directory: $PROJECT_DIR"
pvrig_check_sha256 \
    "$LOCAL_PROJECT/$READY_RELATIVE" "$EXPECTED_READY_SHA256" "internal READY"
"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/runtime_contract.py" validate-project \
    --project-root "$LOCAL_PROJECT" \
    --manifest-relative "$MANIFEST_RELATIVE" \
    --manifest-sha256 "$EXPECTED_MANIFEST_SHA256" \
    --receipt-relative "$RECEIPT_RELATIVE" \
    --receipt-sha256 "$EXPECTED_RECEIPT_SHA256" \
    --receipt-status "$RECEIPT_STATUS" \
    --shard-dir-relative "$SHARD_DIR_RELATIVE" >/dev/null

SHARD_ZERO=$((SHARD_INDEX - 1))
SHARD_MANIFEST=$(printf '%s/%s/shard_%02d.tsv' \
    "$LOCAL_PROJECT" "$SHARD_DIR_RELATIVE" "$SHARD_ZERO")
mapfile -t JOB_IDS < <(
    awk -F $'\t' 'NR>1{gsub(/\r$/, "", $1); print $1}' "$SHARD_MANIFEST"
)
[[ ${#JOB_IDS[@]} -eq "$JOBS_PER_SHARD" ]] ||
    pvrig_die "shard has ${#JOB_IDS[@]} jobs, expected $JOBS_PER_SHARD"

published_success() {
    local job_id=$1
    local status="$PUBLISH_ROOT/status/jobs/$job_id.json"
    local result="$PUBLISH_ROOT/results/$job_id/job_result.json"
    local compact="$PUBLISH_ROOT/compressed_queue/$job_id.tar.gz"
    [[ -f "$status" && -f "$result" ]] || return 1
    "$LOCAL_ENV/bin/python" - "$status" "$result" "$compact" <<'PY' >/dev/null 2>&1
import json, pathlib, sys
status=json.load(open(sys.argv[1]))
result=json.load(open(sys.argv[2]))
compact=pathlib.Path(sys.argv[3])
ok=status.get("status")=="SUCCESS" and result.get("state")=="SUCCESS"
ok=ok and (compact.is_file() or result.get("offloaded_to_node1") is True)
raise SystemExit(0 if ok else 1)
PY
}

publish_status_last() {
    local job_id=$1 source="$LOCAL_PROJECT/status/jobs/$job_id.json"
    local temporary="$PUBLISH_ROOT/status/jobs/.$job_id.json.partial.$$"
    [[ -f "$source" ]] || return 0
    cp -f "$source" "$temporary"
    mv -f "$temporary" "$PUBLISH_ROOT/status/jobs/$job_id.json"
}

run_one() {
    local job_id=$1
    local log="$PUBLISH_ROOT/worker_logs/$job_id.log"
    local scratch="$LOCAL_SCRATCH/$job_id"
    local rc=1 call attempts temporary_result temporary_compact
    mkdir -p "$scratch"
    if published_success "$job_id"; then
        return 100
    fi
    if [[ -f "$PUBLISH_ROOT/status/jobs/$job_id.json" ]]; then
        cp -f \
            "$PUBLISH_ROOT/status/jobs/$job_id.json" \
            "$LOCAL_PROJECT/status/jobs/$job_id.json"
    fi
    for call in 1 2; do
        if PVRIG_PROJECT_ROOT="$LOCAL_PROJECT" \
            PVRIG_LOCAL_SCRATCH_ROOT="$scratch" \
            PVRIG_JOB_CPUS="$JOB_CPUS" \
            "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" \
            "$job_id" --max-attempts 2 >>"$log" 2>&1; then
            rc=0
            break
        else
            rc=$?
        fi
        attempts=$(
            "$LOCAL_ENV/bin/python" - "$LOCAL_PROJECT/status/jobs/$job_id.json" <<'PY'
import json, sys
try:
    print(int(json.load(open(sys.argv[1])).get("attempts", 0)))
except Exception:
    print(0)
PY
        )
        ((attempts < 2)) || break
    done

    if [[ "$rc" == 0 ]]; then
        temporary_result="$PUBLISH_ROOT/results/.$job_id.partial.$$"
        rm -rf "$temporary_result"
        cp -a "$LOCAL_PROJECT/results/$job_id" "$temporary_result"
        rm -rf "$PUBLISH_ROOT/results/$job_id"
        mv "$temporary_result" "$PUBLISH_ROOT/results/$job_id"

        temporary_compact="$PUBLISH_ROOT/compressed_queue/.$job_id.tar.gz.partial.$$"
        rm -f "$temporary_compact"
        "$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/compact_run_evidence.py" \
            --project-root "$LOCAL_PROJECT" \
            --job-id "$job_id" \
            --output "$temporary_compact" >>"$log" 2>&1
        mv -f "$temporary_compact" "$PUBLISH_ROOT/compressed_queue/$job_id.tar.gz"
        rm -rf "$LOCAL_PROJECT/runs/$job_id" "$scratch"
    fi
    publish_status_last "$job_id"
    return "$rc"
}

failures=0
skipped=0
pids=()
drain_batch() {
    local pid rc
    for pid in "${pids[@]}"; do
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
}

for job_id in "${JOB_IDS[@]}"; do
    run_one "$job_id" &
    pids+=("$!")
    [[ ${#pids[@]} -lt "$NODE_CONCURRENCY" ]] || drain_batch
done
[[ ${#pids[@]} -eq 0 ]] || drain_batch

marker="$PUBLISH_ROOT/markers/top5000_multimodal_shard_${SHARD_INDEX}.done"
printf 'array_job=%s shard=%s assigned=%s skipped=%s failures=%s completed_at=%s\n' \
    "${SLURM_ARRAY_JOB_ID:-manual}" \
    "$SHARD_INDEX" \
    "${#JOB_IDS[@]}" \
    "$skipped" \
    "$failures" \
    "$(date -u +%FT%TZ)" | pvrig_atomic_write_stdin "$marker"
((failures == 0))
