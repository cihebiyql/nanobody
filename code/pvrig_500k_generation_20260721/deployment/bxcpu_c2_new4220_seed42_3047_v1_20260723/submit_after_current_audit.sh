#!/usr/bin/env bash
set -euo pipefail
umask 027

CAMPAIGN=pvrig_c2_new4220_seed42_3047_v1_20260723
PACKAGE_NAME=c2_new4220_dualreceptor_seed42_3047_handoff_v1
DEPLOY_ROOT="${PVRIG_C2_EXTRA_DEPLOY_ROOT:-$HOME/.local/share/$CAMPAIGN}"
ARCHIVE="$HOME/${PACKAGE_NAME}_20260723.tar.gz"
PUBLISH_ROOT="$HOME/${CAMPAIGN}_bxcpu_results"
ARCHIVE_SHA256=b5afb17360a03c539e02dae064e87f8b70de597179823a891f1f8a0a79ac4061
MANIFEST_SHA256=60290622ab842f7c888912c828a2a48068a208ba370b666a32b121a8c7266aa5
PREDECESSOR_AUDIT=11943297
RECEIPT="$PUBLISH_ROOT/markers/SUBMISSION_RECEIPT.txt"
PREFLIGHT_ID_FILE="$PUBLISH_ROOT/markers/PREFLIGHT_JOB_ID"
ARRAY_ID_FILE="$PUBLISH_ROOT/markers/ARRAY_JOB_ID"
AUDIT_ID_FILE="$PUBLISH_ROOT/markers/AUDIT_JOB_ID"

mkdir -p "$PUBLISH_ROOT/markers" "$PUBLISH_ROOT/reports" "$PUBLISH_ROOT/status/jobs" \
    "$PUBLISH_ROOT/results" "$PUBLISH_ROOT/worker_logs" "$PUBLISH_ROOT/compressed_queue"
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$ARCHIVE_SHA256" ]]
if [[ -s "$RECEIPT" ]]; then
    cat "$RECEIPT"
    exit 0
fi

COMMON_EXPORT="ALL,PVRIG_C2_EXTRA_DEPLOY_ROOT=$DEPLOY_ROOT,PVRIG_C2_EXTRA_ARCHIVE=$ARCHIVE,PVRIG_C2_EXTRA_PUBLISH_ROOT=$PUBLISH_ROOT,PVRIG_C2_EXTRA_ARCHIVE_SHA256=$ARCHIVE_SHA256,PVRIG_C2_EXTRA_MANIFEST_SHA256=$MANIFEST_SHA256"

state_of() {
    sacct -n -X -j "$1" --format=State | awk 'NF{print $1;exit}' | cut -d+ -f1
}

predecessor_state=$(state_of "$PREDECESSOR_AUDIT")
case "$predecessor_state" in
    COMPLETED) ;;
    PENDING|RUNNING|CONFIGURING|COMPLETING|"")
        echo "WAITING_PREDECESSOR_AUDIT job_id=$PREDECESSOR_AUDIT state=${predecessor_state:-UNKNOWN}"
        exit 0
        ;;
    *)
        echo "PREDECESSOR_AUDIT_FAILED job_id=$PREDECESSOR_AUDIT state=$predecessor_state" >&2
        exit 67
        ;;
esac

if [[ ! -s "$PREFLIGHT_ID_FILE" ]]; then
    preflight=$(sbatch --parsable --partition=amd_256q \
        --job-name=pvrig-c2-s42-3047-preflight \
        --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=16G --time=00:30:00 \
        --output="$PUBLISH_ROOT/slurm-%x-%j.out" --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
        --export="$COMMON_EXPORT" "$DEPLOY_ROOT/preflight_seed42_3047.sh")
    preflight=${preflight%%;*}
    printf '%s\n' "$preflight" > "$PREFLIGHT_ID_FILE.tmp"
    mv "$PREFLIGHT_ID_FILE.tmp" "$PREFLIGHT_ID_FILE"
    echo "PREFLIGHT_SUBMITTED job_id=$preflight"
    exit 0
fi
preflight=$(cat "$PREFLIGHT_ID_FILE")
preflight_state=$(state_of "$preflight")
case "$preflight_state" in
    COMPLETED) ;;
    RUNNING)
        if [[ "${PVRIG_SUBMIT_FROM_PREFLIGHT:-0}" == 1 && "${SLURM_JOB_ID:-}" == "$preflight" ]]; then
            :
        else
            echo "WAITING_PREFLIGHT job_id=$preflight state=$preflight_state"
            exit 0
        fi
        ;;
    PENDING|CONFIGURING|COMPLETING|"")
        echo "WAITING_PREFLIGHT job_id=$preflight state=${preflight_state:-UNKNOWN}"
        exit 0
        ;;
    *)
        echo "PREFLIGHT_FAILED job_id=$preflight state=$preflight_state" >&2
        exit 68
        ;;
esac

if [[ ! -s "$ARRAY_ID_FILE" ]]; then
    array=$(sbatch --parsable --partition=amd_256q \
        --job-name=pvrig-c2-s42-3047-16880 \
        --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G --exclusive --time=24:00:00 \
        --array=1-8%8 --output="$PUBLISH_ROOT/slurm-%x-%A_%a.out" \
        --error="$PUBLISH_ROOT/slurm-%x-%A_%a.err" \
        --export="$COMMON_EXPORT,PVRIG_C2_EXTRA_NODE_CONCURRENCY=16" \
        "$DEPLOY_ROOT/bxcpu_c2_new4220_seed42_3047_worker.sh")
    array=${array%%;*}
    printf '%s\n' "$array" > "$ARRAY_ID_FILE.tmp"
    mv "$ARRAY_ID_FILE.tmp" "$ARRAY_ID_FILE"
    echo "ARRAY_SUBMITTED job_id=$array"
    exit 0
fi
array=$(cat "$ARRAY_ID_FILE")

audit_dep=afterany
for shard in {1..8}; do audit_dep+=:${array}_${shard}; done
if [[ ! -s "$AUDIT_ID_FILE" ]]; then
    audit=$(sbatch --parsable --dependency="$audit_dep" \
        --partition=amd_256q --job-name=pvrig-c2-s42-3047-audit \
        --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=4G --time=01:00:00 \
        --output="$PUBLISH_ROOT/slurm-%x-%j.out" --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
        --export="$COMMON_EXPORT" "$DEPLOY_ROOT/run_terminal_audit_seed42_3047.sh")
    audit=${audit%%;*}
    printf '%s\n' "$audit" > "$AUDIT_ID_FILE.tmp"
    mv "$AUDIT_ID_FILE.tmp" "$AUDIT_ID_FILE"
else
    audit=$(cat "$AUDIT_ID_FILE")
fi
printf 'status=SUBMITTED_DEPENDENT_ON_CURRENT_TERMINAL_AUDIT\npredecessor_audit_job_id=%s\npreflight_job_id=%s\narray_job_id=%s\naudit_job_id=%s\nexpected_candidates=4220\nexpected_jobs=16880\nseeds=42,3047\narchive_sha256=%s\nmanifest_sha256=%s\nresult_root=%s\nsubmitted_at=%s\n' \
    "$PREDECESSOR_AUDIT" "$preflight" "$array" "$audit" "$ARCHIVE_SHA256" \
    "$MANIFEST_SHA256" "$PUBLISH_ROOT" "$(date -u +%FT%TZ)" | tee "$RECEIPT"
