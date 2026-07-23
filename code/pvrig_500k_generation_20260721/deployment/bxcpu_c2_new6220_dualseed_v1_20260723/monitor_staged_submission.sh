#!/usr/bin/env bash
set -u

REMOTE_HOME=/publicfs04/fs04-al/home/als001821
REMOTE_DEPLOY="$REMOTE_HOME/.local/share/bxcpu_c2_new6220_dualseed_v1_20260723"
REMOTE_RECEIPT="$REMOTE_HOME/pvrig_c2_new6220_dualreceptor_2seed_v1_20260723_bxcpu_results/markers/SUBMISSION_RECEIPT.retry1.txt"
LOCAL_ROOT=$(cd "$(dirname "$0")" && pwd)
LOG="$LOCAL_ROOT/STAGED_SUBMISSION_WATCHER.retry1.log"
STATUS="$LOCAL_ROOT/STAGED_SUBMISSION_STATUS.retry1.txt"

while true; do
    now=$(date -Is)
    if ssh -o BatchMode=yes -o ConnectTimeout=20 bxcpu \
        "test -s '$REMOTE_RECEIPT' && cat '$REMOTE_RECEIPT'" > "$LOCAL_ROOT/SUBMISSION_RECEIPT.retry1.remote.tmp" 2>>"$LOG"; then
        mv "$LOCAL_ROOT/SUBMISSION_RECEIPT.retry1.remote.tmp" "$LOCAL_ROOT/SUBMISSION_RECEIPT.retry1.remote.txt"
        printf 'PASS_SUBMITTED %s\n' "$now" | tee "$STATUS" >>"$LOG"
        exit 0
    fi
    printf 'RETRYING %s\n' "$now" > "$STATUS"
    ssh -o BatchMode=yes -o ConnectTimeout=20 bxcpu \
        "'$REMOTE_DEPLOY/submit_after_top7500.sh'" >>"$LOG" 2>&1 || true
    sleep 30
done
