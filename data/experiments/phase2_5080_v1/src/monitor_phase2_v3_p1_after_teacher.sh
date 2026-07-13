#!/usr/bin/env bash
# Wait for the frozen Teacher500 audit and then run formal V3-P exactly once.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
AUDIT=${AUDIT:-$ROOT/audits/pvrig_formal_teacher500_audit.json}
PIPELINE=${PIPELINE:-$ROOT/src/run_phase2_v3_p1_formal_pipeline.sh}
POLL_SECONDS=${POLL_SECONDS:-120}
LOG=${LOG:-$ROOT/logs/phase2_v3_p1_after_teacher_monitor.log}
PID_FILE=${PID_FILE:-$ROOT/logs/phase2_v3_p1_after_teacher_monitor.pid}
LOCK=${LOCK:-/tmp/phase2_v3_p1_after_teacher_monitor.lock}

mkdir -p "$(dirname "$LOG")"
exec 9>"$LOCK"
flock -n 9 || { echo "Another formal V3-P watcher owns $LOCK" >&2; exit 4; }
exec >>"$LOG" 2>&1
echo $$ >"$PID_FILE"
cleanup() {
  local child
  for child in $(jobs -pr); do kill -TERM "$child" 2>/dev/null || true; done
  [[ ! -f "$PID_FILE" || $(cat "$PID_FILE") != $$ ]] || rm -f "$PID_FILE"
}
trap cleanup EXIT
trap 'exit 143' TERM INT
sleep_interruptibly() { sleep "$1" & wait "$!"; }

echo "V3P_WATCHER_START $(date -Is) audit=$AUDIT"
while true; do
  if [[ -f "$AUDIT" ]] && python - "$AUDIT" <<'PY'
import json
import sys

raise SystemExit(0 if json.load(open(sys.argv[1])).get("status") == "PASS_FORMAL_TEACHER500_READY" else 1)
PY
  then
    break
  fi
  echo "V3P_WAIT_TEACHER $(date -Is)"
  sleep_interruptibly "$POLL_SECONDS"
done

echo "V3P_FORMAL_PIPELINE_START $(date -Is)"
bash "$PIPELINE"
echo "V3P_FORMAL_PIPELINE_COMPLETE $(date -Is)"
