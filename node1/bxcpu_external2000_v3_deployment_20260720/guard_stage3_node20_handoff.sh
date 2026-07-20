#!/usr/bin/env bash
# Wait for the Stage2 aggregation receipt, then submit the frozen Node20 Stage3.
set -euo pipefail
umask 027

DEPLOY="$HOME/.local/share/bxcpu_external2000_v3_deployment_20260720"
STAGE2_ROOT="$HOME/pvrig_v29_bxcpu_stage2_10500_v1_20260720_bxcpu_results"
NAME=pvrig_v29_bxcpu_stage3_node20_v1_20260720
ROOT="${PVRIG_STAGE3_PUBLISH_ROOT:-$HOME/${NAME}_bxcpu_results}"
POLL_SECONDS="${PVRIG_STAGE3_GUARD_POLL_SECONDS:-60}"
STAGE2_SUBMISSION="$STAGE2_ROOT/markers/stage2_10500_submission.receipt"
SUBMISSION="$ROOT/markers/stage3_node20_submission.receipt"
LOG="$ROOT/markers/stage3_node20_handoff_guard.log"
DONE="$ROOT/markers/stage3_node20_handoff_guard.done"

mkdir -p "$ROOT/markers"
exec 9>"$ROOT/markers/stage3_node20_handoff_guard.lock"
flock -n 9 || exit 0
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

while [[ ! -s "$STAGE2_SUBMISSION" ]]; do
    log "waiting for Stage2 submission receipt"
    sleep "$POLL_SECONDS"
done
stage2_aggregate=$(awk -F= '$1=="aggregate_job_id"{print $2}' "$STAGE2_SUBMISSION")
[[ "$stage2_aggregate" =~ ^[0-9]+$ ]] || { log "invalid Stage2 aggregate job ID"; exit 65; }
while squeue -h -j "$stage2_aggregate" 2>/dev/null | grep -q .; do
    log "waiting for Stage2 aggregate job $stage2_aggregate"
    sleep "$POLL_SECONDS"
done

if [[ -s "$SUBMISSION" ]]; then
    log "Stage3 submission receipt already exists"
elif squeue -h -u "$USER" -n pvrig-v29-s3-node20 | grep -q .; then
    log "Stage3 array is already active"
else
    log "submitting frozen Node20 Stage3"
    "$DEPLOY/submit_stage3_node20_eight_nodes.sh" >>"$LOG" 2>&1
fi
[[ -s "$SUBMISSION" ]] || { log "ERROR: Stage3 submission receipt is absent"; exit 1; }
printf 'completed_at=%s stage2_aggregate_job=%s\n' \
    "$(date -u +%FT%TZ)" "$stage2_aggregate" >"$DONE"
log "Stage3 handoff verified"
