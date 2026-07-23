#!/usr/bin/env bash
set -u

DEPLOY=$(cd "$(dirname "$0")" && pwd)
RUNTIME="$DEPLOY/watchdog_runtime"
mkdir -p "$RUNTIME"
while true; do
    printf '[%s] watchdog cycle start\n' "$(date -u +%FT%TZ)" >> "$RUNTIME/watchdog.nohup.log"
    if python3 "$DEPLOY/monitor_all_docking_30m.py" >> "$RUNTIME/watchdog.nohup.log" 2>&1; then
        printf '[%s] watchdog cycle complete\n' "$(date -u +%FT%TZ)" >> "$RUNTIME/watchdog.nohup.log"
    else
        printf '[%s] watchdog cycle returned nonzero; next cycle will retry\n' "$(date -u +%FT%TZ)" >> "$RUNTIME/watchdog.nohup.log"
    fi
    sleep 1800
done
