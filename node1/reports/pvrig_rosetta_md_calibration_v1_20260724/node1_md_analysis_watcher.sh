#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724}"
STATUS="$ROOT/status/MD_PRODUCTION_STATUS.json"
LOG="$ROOT/logs/md_analysis_watcher.log"
mkdir -p "$ROOT"/{status,logs,locks,reports}
exec 9>"$ROOT/locks/md_analysis_watcher.lock"
if ! flock -n 9; then
  echo "another MD analysis watcher owns the lock" >&2
  exit 75
fi
echo "watcher_start=$(date -Is) pid=$$" >> "$LOG"
while true; do
  state="$(python3 - "$STATUS" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1])).get("state","MISSING"))
except Exception: print("MISSING")
PY
)"
  echo "time=$(date -Is) md_state=$state" >> "$LOG"
  case "$state" in
    COMPLETE) break ;;
    PARTIAL)
      printf '{"state":"BLOCKED","reason":"MD_PRODUCTION_PARTIAL"}\n' \
        > "$ROOT/status/MD_ANALYSIS_STATUS.json"
      exit 1
      ;;
  esac
  sleep 60
done
python3 "$ROOT/scripts/analyze_md_stage_a.py" "$ROOT" \
  >"$ROOT/logs/md_analysis.stdout.log" 2>"$ROOT/logs/md_analysis.stderr.log"
cp "$ROOT/reports/MD_STAGE_A_CALIBRATION_RECEIPT.json" "$ROOT/status/MD_ANALYSIS_STATUS.json"
echo "watcher_complete=$(date -Is)" >> "$LOG"
