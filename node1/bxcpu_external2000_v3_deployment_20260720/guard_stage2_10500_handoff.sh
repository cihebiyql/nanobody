#!/usr/bin/env bash
# Login-node guard for the one-time handoff from the active 3,814-job batch to
# the frozen 10,500-job Stage2 array. It consumes no compute allocation.
set -euo pipefail
umask 027

DEPLOY="$HOME/.local/share/bxcpu_external2000_v3_deployment_20260720"
NAME=pvrig_v29_bxcpu_stage2_10500_v1_20260720
ROOT="${PVRIG_STAGE2_PUBLISH_ROOT:-$HOME/${NAME}_bxcpu_results}"
SOURCE_AGGREGATE_JOB_ID="${PVRIG_STAGE2_SOURCE_AGGREGATE_JOB_ID:-11936122}"
POLL_SECONDS="${PVRIG_STAGE2_GUARD_POLL_SECONDS:-60}"
LOG="$ROOT/markers/stage2_handoff_guard.log"
DONE="$ROOT/markers/stage2_handoff_guard.done"
SUBMISSION="$ROOT/markers/stage2_10500_submission.receipt"

mkdir -p "$ROOT/markers"
exec 9>"$ROOT/markers/stage2_handoff_guard.lock"
if ! flock -n 9; then
    printf '%s another guard owns the handoff lock\n' "$(date -u +%FT%TZ)" >>"$LOG"
    exit 0
fi

log() {
    printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"
}

submit_missing_aggregate() {
    local array_id=$1 dep agg
    dep=afterany
    for shard in {1..8}; do dep+=":${array_id}_${shard}"; done
    agg=$(sbatch --parsable --dependency="$dep" \
        --partition=amd_256q --job-name=pvrig-v29-s2-agg \
        --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=4G --exclusive \
        --time=02:00:00 --output="$ROOT/slurm-%x-%j.out" \
        --error="$ROOT/slurm-%x-%j.err" \
        "$DEPLOY/aggregate_stage2_10500_after_shards.sh")
    agg=${agg%%;*}
    printf 'array_job_id=%s\naggregate_job_id=%s\nrecovered_by_guard=true\nsubmitted_at=%s\n' \
        "$array_id" "$agg" "$(date -u +%FT%TZ)" | tee "$SUBMISSION"
    log "recovered missing aggregate job array=$array_id aggregate=$agg"
}

while squeue -h -j "$SOURCE_AGGREGATE_JOB_ID" 2>/dev/null | grep -q .; do
    log "waiting for source aggregate job $SOURCE_AGGREGATE_JOB_ID"
    sleep "$POLL_SECONDS"
done

if [[ -s "$SUBMISSION" ]]; then
    log "Stage2 submission receipt already exists"
elif array_id=$(squeue -h -u "$USER" -n pvrig-v29-s2-10500 -o '%A' | head -n 1) && [[ -n "$array_id" ]]; then
    if squeue -h -u "$USER" -n pvrig-v29-s2-agg | grep -q .; then
        log "Stage2 array and aggregate are already active"
    else
        submit_missing_aggregate "$array_id"
    fi
else
    log "source aggregate ended without an active Stage2 array; submitting now"
    "$DEPLOY/submit_stage2_10500_eight_nodes.sh" >>"$LOG" 2>&1
fi

[[ -s "$SUBMISSION" ]] || {
    log "ERROR: Stage2 submission receipt is still absent"
    exit 1
}
printf 'completed_at=%s source_aggregate_job=%s\n' \
    "$(date -u +%FT%TZ)" "$SOURCE_AGGREGATE_JOB_ID" >"$DONE"
log "handoff verified"
