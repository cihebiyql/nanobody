#!/usr/bin/env bash
set -Eeuo pipefail

BASE=/data1/qlyu/pvrig_migration_20260716
SCRIPT="$BASE/resume_ssd_deepqc.py"
PREFLIGHT_LOG="$BASE/deepqc_recovery_v1/preflight_launcher.log"
RUN_LOG="$BASE/deepqc_recovery_v1/recovery_launcher.log"

mkdir -p "$BASE/deepqc_recovery_v1"
test -x "$SCRIPT"

# Do not start a waiter: launch only when every real precondition already PASSes.
set +e
/usr/bin/python3 "$SCRIPT" --preflight >"$PREFLIGHT_LOG" 2>&1
preflight_rc=$?
set -e
if [[ $preflight_rc -ne 0 ]]; then
  printf 'NOT_LAUNCHED preflight_rc=%s at %s\n' "$preflight_rc" "$(date -Is)" >&2
  exit "$preflight_rc"
fi

exec 9>"$BASE/deepqc_recovery_v1/launcher.lock"
flock -n 9 || { echo "another recovery launcher holds the lock" >&2; exit 75; }
nohup /usr/bin/python3 "$SCRIPT" --run >"$RUN_LOG" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" >"$BASE/deepqc_recovery_v1/recovery.pid.tmp"
mv "$BASE/deepqc_recovery_v1/recovery.pid.tmp" "$BASE/deepqc_recovery_v1/recovery.pid"
printf 'LAUNCHED pid=%s at %s\n' "$pid" "$(date -Is)"
