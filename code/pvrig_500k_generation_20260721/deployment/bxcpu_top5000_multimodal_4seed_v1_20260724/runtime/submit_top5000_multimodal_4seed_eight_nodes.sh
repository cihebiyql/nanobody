#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_TOP5000_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_top5000_multimodal_4seed_v1_20260724/runtime}"
# shellcheck source=bxcpu_runtime_common.sh
source "$DEPLOY_ROOT/bxcpu_runtime_common.sh"

PROJECT_NAME="${PVRIG_TOP5000_PROJECT_NAME:-pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724}"
PROJECT_DIR="${PVRIG_TOP5000_PROJECT_DIR:-$PROJECT_NAME}"
BUNDLE_ARCHIVE="${PVRIG_TOP5000_BUNDLE_ARCHIVE:-$HOME/${PROJECT_NAME}.tar.zst}"
MANIFEST_PATH="${PVRIG_TOP5000_MANIFEST_PATH:-$HOME/${PROJECT_NAME}.manifest.tsv}"
READY_PATH="${PVRIG_TOP5000_READY_PATH:-$HOME/${PROJECT_NAME}.READY.json}"
PUBLISH_ROOT="${PVRIG_TOP5000_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
MANIFEST_RELATIVE="${PVRIG_TOP5000_MANIFEST_RELATIVE:-manifests/docking_jobs.tsv}"
SHARD_DIR_RELATIVE="${PVRIG_TOP5000_SHARD_DIR_RELATIVE:-manifests/shards_exact_8}"
RECEIPT_RELATIVE="${PVRIG_TOP5000_RECEIPT_RELATIVE:-HANDOFF_RECEIPT.json}"
READY_RELATIVE="${PVRIG_TOP5000_READY_RELATIVE:-READY.json}"
READY_STATUS="${PVRIG_TOP5000_READY_STATUS:-READY_FOR_EXTERNAL_DOCKING_SUBMISSION}"
RECEIPT_STATUS="${PVRIG_TOP5000_RECEIPT_STATUS:-READY_FOR_EXTERNAL_DOCKING_SUBMISSION}"
PREFLIGHT_RECEIPT="${PVRIG_TOP5000_PREFLIGHT_RECEIPT_PATH:-$PUBLISH_ROOT/reports/PREFLIGHT_RECEIPT.json}"
AUDIT_OUTPUT="${PVRIG_TOP5000_AUDIT_OUTPUT:-$PUBLISH_ROOT/reports/TECHNICAL_COMPLETION.json}"
SUBMISSION_RECEIPT="${PVRIG_TOP5000_SUBMISSION_RECEIPT_PATH:-$PUBLISH_ROOT/markers/SUBMISSION_RECEIPT.txt}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_TOP5000_ARCHIVE_SHA256:?archive SHA256 is required}"
EXPECTED_MANIFEST_SHA256="${PVRIG_TOP5000_MANIFEST_SHA256:?manifest SHA256 is required}"
EXPECTED_READY_SHA256="${PVRIG_TOP5000_READY_SHA256:?READY SHA256 is required}"
EXPECTED_RECEIPT_SHA256="${PVRIG_TOP5000_RECEIPT_SHA256:?receipt SHA256 is required}"

PARTITION="${PVRIG_TOP5000_PARTITION:-amd_256q}"
NODE_MEMORY="${PVRIG_TOP5000_NODE_MEMORY:-230G}"
ARRAY_TIME="${PVRIG_TOP5000_ARRAY_TIME:-24:00:00}"
PREFLIGHT_TIME="${PVRIG_TOP5000_PREFLIGHT_TIME:-01:00:00}"
AUDIT_TIME="${PVRIG_TOP5000_AUDIT_TIME:-01:00:00}"
JOB_NAME="${PVRIG_TOP5000_JOB_NAME:-pvrig-top5000-mm40k}"

for name in \
    EXPECTED_ARCHIVE_SHA256 \
    EXPECTED_MANIFEST_SHA256 \
    EXPECTED_READY_SHA256 \
    EXPECTED_RECEIPT_SHA256; do
    pvrig_require_sha256 "$name"
done
pvrig_check_sha256 "$BUNDLE_ARCHIVE" "$EXPECTED_ARCHIVE_SHA256" archive
pvrig_check_sha256 "$MANIFEST_PATH" "$EXPECTED_MANIFEST_SHA256" manifest
pvrig_check_sha256 "$READY_PATH" "$EXPECTED_READY_SHA256" READY

for value in \
    "$DEPLOY_ROOT" "$PROJECT_NAME" "$PROJECT_DIR" "$BUNDLE_ARCHIVE" \
    "$MANIFEST_PATH" "$READY_PATH" "$PUBLISH_ROOT" "$MANIFEST_RELATIVE" \
    "$SHARD_DIR_RELATIVE" "$RECEIPT_RELATIVE" "$READY_RELATIVE" \
    "$READY_STATUS" "$RECEIPT_STATUS" \
    "$PREFLIGHT_RECEIPT" "$AUDIT_OUTPUT"; do
    [[ "$value" != *','* && "$value" != *$'\n'* ]] ||
        pvrig_die "Slurm export values may not contain commas or newlines"
done

mkdir -p \
    "$PUBLISH_ROOT/status/jobs" \
    "$PUBLISH_ROOT/results" \
    "$PUBLISH_ROOT/worker_logs" \
    "$PUBLISH_ROOT/compressed_queue" \
    "$PUBLISH_ROOT/markers" \
    "$PUBLISH_ROOT/reports"

if [[ -s "$SUBMISSION_RECEIPT" ]]; then
    grep -Fx "archive_sha256=$EXPECTED_ARCHIVE_SHA256" "$SUBMISSION_RECEIPT" >/dev/null
    grep -Fx "manifest_sha256=$EXPECTED_MANIFEST_SHA256" "$SUBMISSION_RECEIPT" >/dev/null
    grep -Fx "ready_sha256=$EXPECTED_READY_SHA256" "$SUBMISSION_RECEIPT" >/dev/null
    cat "$SUBMISSION_RECEIPT"
    exit 0
fi

LOCK_DIR="$PUBLISH_ROOT/markers/.submit.lock"
mkdir "$LOCK_DIR" 2>/dev/null || pvrig_die "another submit process owns $LOCK_DIR"
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
[[ $(squeue -h -u "$USER" -n "$JOB_NAME,$JOB_NAME-preflight" | wc -l) -eq 0 ]] ||
    pvrig_die "active campaign jobs already exist"

COMMON_EXPORT="ALL"
append_export() {
    local name=$1 value=$2
    COMMON_EXPORT+=",$name=$value"
}
append_export PVRIG_TOP5000_DEPLOY_ROOT "$DEPLOY_ROOT"
append_export PVRIG_TOP5000_PROJECT_NAME "$PROJECT_NAME"
append_export PVRIG_TOP5000_PROJECT_DIR "$PROJECT_DIR"
append_export PVRIG_TOP5000_BUNDLE_ARCHIVE "$BUNDLE_ARCHIVE"
append_export PVRIG_TOP5000_MANIFEST_PATH "$MANIFEST_PATH"
append_export PVRIG_TOP5000_READY_PATH "$READY_PATH"
append_export PVRIG_TOP5000_PUBLISH_ROOT "$PUBLISH_ROOT"
append_export PVRIG_TOP5000_MANIFEST_RELATIVE "$MANIFEST_RELATIVE"
append_export PVRIG_TOP5000_SHARD_DIR_RELATIVE "$SHARD_DIR_RELATIVE"
append_export PVRIG_TOP5000_RECEIPT_RELATIVE "$RECEIPT_RELATIVE"
append_export PVRIG_TOP5000_READY_RELATIVE "$READY_RELATIVE"
append_export PVRIG_TOP5000_READY_STATUS "$READY_STATUS"
append_export PVRIG_TOP5000_RECEIPT_STATUS "$RECEIPT_STATUS"
append_export PVRIG_TOP5000_PREFLIGHT_RECEIPT_PATH "$PREFLIGHT_RECEIPT"
append_export PVRIG_TOP5000_AUDIT_OUTPUT "$AUDIT_OUTPUT"
append_export PVRIG_TOP5000_ARCHIVE_SHA256 "$EXPECTED_ARCHIVE_SHA256"
append_export PVRIG_TOP5000_MANIFEST_SHA256 "$EXPECTED_MANIFEST_SHA256"
append_export PVRIG_TOP5000_READY_SHA256 "$EXPECTED_READY_SHA256"
append_export PVRIG_TOP5000_RECEIPT_SHA256 "$EXPECTED_RECEIPT_SHA256"

preflight=$(
    sbatch --parsable \
        --partition="$PARTITION" \
        --job-name="$JOB_NAME-preflight" \
        --nodes=1 \
        --ntasks=1 \
        --cpus-per-task=4 \
        --mem=16G \
        --time="$PREFLIGHT_TIME" \
        --output="$PUBLISH_ROOT/slurm-%x-%j.out" \
        --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
        --export="$COMMON_EXPORT" \
        "$DEPLOY_ROOT/preflight_top5000_multimodal_4seed.sh"
)
preflight=${preflight%%;*}

array=$(
    sbatch --parsable \
        --dependency="afterok:$preflight" \
        --partition="$PARTITION" \
        --job-name="$JOB_NAME" \
        --nodes=1 \
        --ntasks=1 \
        --cpus-per-task=64 \
        --mem="$NODE_MEMORY" \
        --exclusive \
        --time="$ARRAY_TIME" \
        --array=1-8%8 \
        --output="$PUBLISH_ROOT/slurm-%x-%A_%a.out" \
        --error="$PUBLISH_ROOT/slurm-%x-%A_%a.err" \
        --export="$COMMON_EXPORT,PVRIG_TOP5000_NODE_CONCURRENCY=16" \
        "$DEPLOY_ROOT/bxcpu_top5000_multimodal_4seed_worker.sh"
)
array=${array%%;*}

audit_dependency=afterany
for shard in {1..8}; do
    audit_dependency+=:${array}_${shard}
done
audit=$(
    sbatch --parsable \
        --dependency="$audit_dependency" \
        --partition="$PARTITION" \
        --job-name="$JOB_NAME-audit" \
        --nodes=1 \
        --ntasks=1 \
        --cpus-per-task=1 \
        --mem=4G \
        --time="$AUDIT_TIME" \
        --output="$PUBLISH_ROOT/slurm-%x-%j.out" \
        --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
        --export="$COMMON_EXPORT" \
        "$DEPLOY_ROOT/audit_top5000_multimodal_4seed.sh"
)
audit=${audit%%;*}

printf 'status=SUBMITTED\npreflight_job_id=%s\narray_job_id=%s\naudit_job_id=%s\nexpected_candidates=5000\nexpected_jobs=40000\nexpected_shards=8\nexpected_jobs_per_shard=5000\nnodes=8\ncpus_per_node=64\nconcurrent_jobs_per_node=16\ncpus_per_job=4\narchive_sha256=%s\nmanifest_sha256=%s\nready_sha256=%s\nreceipt_sha256=%s\nresult_root=%s\npreflight_receipt=%s\naudit_output=%s\nsubmitted_at=%s\n' \
    "$preflight" \
    "$array" \
    "$audit" \
    "$EXPECTED_ARCHIVE_SHA256" \
    "$EXPECTED_MANIFEST_SHA256" \
    "$EXPECTED_READY_SHA256" \
    "$EXPECTED_RECEIPT_SHA256" \
    "$PUBLISH_ROOT" \
    "$PREFLIGHT_RECEIPT" \
    "$AUDIT_OUTPUT" \
    "$(date -u +%FT%TZ)" | pvrig_atomic_write_stdin "$SUBMISSION_RECEIPT"
cat "$SUBMISSION_RECEIPT"
