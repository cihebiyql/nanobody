#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
PUBLISH="$HOME/pvrig_c2_new4220_seed42_3047_v1_20260723_bxcpu_results"
LOG="$PUBLISH/markers/STAGED_SUBMISSION_WATCHER.log"
mkdir -p "$PUBLISH/markers"

while [[ ! -s "$PUBLISH/markers/SUBMISSION_RECEIPT.txt" ]]; do
    printf '[%s] ' "$(date -u +%FT%TZ)" >> "$LOG"
    if "$DEPLOY/submit_after_current_audit.sh" >> "$LOG" 2>&1; then
        :
    else
        printf '[%s] staged submission attempt returned nonzero\n' "$(date -u +%FT%TZ)" >> "$LOG"
    fi
    sleep 30
done
printf '[%s] staged submission complete\n' "$(date -u +%FT%TZ)" >> "$LOG"
