#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724}"
mkdir -p "$ROOT"/{status,logs,locks}
exec 9>"$ROOT/locks/md_expansion_chain.lock"
if ! flock -n 9; then
  echo "another expansion chain owns the lock" >&2
  exit 75
fi
printf '%s\n' "$$" > "$ROOT/status/MD_EXPANSION_CHAIN.pid.tmp.$$"
mv "$ROOT/status/MD_EXPANSION_CHAIN.pid.tmp.$$" "$ROOT/status/MD_EXPANSION_CHAIN.pid"
CURRENT_STAGE="INITIALIZING"
write_failure_status() {
  local rc="$1"
  python3 - "$ROOT/status/MD_EXPANSION_ANALYSIS_STATUS.json.tmp.$$" "$CURRENT_STAGE" "$rc" <<'PY'
import json
import sys
from datetime import datetime, timezone

json.dump(
    {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "FAILED",
        "failed_stage": sys.argv[2],
        "return_code": int(sys.argv[3]),
    },
    open(sys.argv[1], "w"),
    indent=2,
)
PY
  mv "$ROOT/status/MD_EXPANSION_ANALYSIS_STATUS.json.tmp.$$" \
    "$ROOT/status/MD_EXPANSION_ANALYSIS_STATUS.json"
}
on_exit() {
  local rc="$?"
  if [[ "$rc" -ne 0 ]]; then
    write_failure_status "$rc"
  fi
}
trap on_exit EXIT

CURRENT_STAGE="TOPOLOGY"
"$ROOT/scripts/node1_md_expansion_topology.sh" \
  >"$ROOT/logs/md_expansion_topology.stdout.log" \
  2>"$ROOT/logs/md_expansion_topology.stderr.log"
python3 - "$ROOT/status/MD_EXPANSION_TOPOLOGY_STATUS.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
if x.get("state")!="COMPLETE": raise SystemExit(f"topology stage did not complete: {x}")
PY

CURRENT_STAGE="PRODUCTION"
env \
  PVRIG_CALIBRATION_ROOT="$ROOT" \
  PVRIG_MD_MANIFEST="$ROOT/manifests/MD_EXPANSION_PRODUCTION.tsv" \
  PVRIG_MD_SOURCE_BASE="$ROOT/md/expansion/jobs" \
  PVRIG_MD_PRODUCTION_BASE="$ROOT/md/expansion/production" \
  PVRIG_MD_STATUS_FILE="$ROOT/status/MD_EXPANSION_PRODUCTION_STATUS.json" \
  PVRIG_MD_LOCK_FILE="$ROOT/locks/md_expansion_production.lock" \
  PVRIG_MD_CONTROLLER_PID_FILE="$ROOT/status/MD_EXPANSION_CONTROLLER.pid" \
  "$ROOT/scripts/node1_gromacs_md_controller.sh" \
  >"$ROOT/logs/md_expansion_production.stdout.log" \
  2>"$ROOT/logs/md_expansion_production.stderr.log"

CURRENT_STAGE="ANALYSIS"
python3 "$ROOT/scripts/analyze_md_expansion.py" "$ROOT" \
  >"$ROOT/logs/md_expansion_analysis.stdout.log" \
  2>"$ROOT/logs/md_expansion_analysis.stderr.log"
cp "$ROOT/reports/MD_EXPANSION_CALIBRATION_RECEIPT.json" \
  "$ROOT/status/MD_EXPANSION_ANALYSIS_STATUS.json.tmp"
mv "$ROOT/status/MD_EXPANSION_ANALYSIS_STATUS.json.tmp" \
  "$ROOT/status/MD_EXPANSION_ANALYSIS_STATUS.json"
CURRENT_STAGE="COMPLETE"
