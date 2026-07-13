#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
PYTHON=${PYTHON:-/data/qlyu/anaconda3/envs/boltz/bin/python}
POLL_SECONDS=${POLL_SECONDS:-60}
LOCKDIR="$RUN_ROOT/status/haddock_sidecar_watchdog.lock"
PIDFILE="$RUN_ROOT/status/haddock_sidecar_watchdog.pid"
LOG="$RUN_ROOT/logs/haddock_sidecar_watchdog.log"

mkdir -p "$RUN_ROOT/status" "$RUN_ROOT/logs"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "HADDOCK_WATCHDOG_ALREADY_RUNNING lock=$LOCKDIR"
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
echo $$ >"$PIDFILE"

pid_alive() {
  local pidfile=$1 pid
  pid=$(cat "$pidfile" 2>/dev/null || true)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

launch_sidecar() {
  local name=$1 max_load=$2 parallel=$3 log=$4 pidfile=$5 pid
  printf '\nWATCHDOG_RESTART name=%s time=%s\n' "$name" "$(date -Is)" >>"$log"
  nohup "$PYTHON" "$RUN_ROOT/scripts/run_haddock_load_aware.py" \
    --run-root "$RUN_ROOT" --max-load1 "$max_load" --cores-per-job 4 \
    --max-parallel "$parallel" --poll-seconds 30 --retry-failed --max-attempts 3 \
    >>"$log" 2>&1 < /dev/null &
  pid=$!
  echo "$pid" >"$pidfile"
  echo "HADDOCK_WATCHDOG_RESTARTED name=$name pid=$pid time=$(date -Is)" >>"$LOG"
}

while true; do
  read -r total terminal live_running success failed < <(
    "$PYTHON" - "$RUN_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = root / "docking/manifests/docking_candidates.tsv"
total = max(0, sum(1 for _ in manifest.open(encoding="utf-8")) - 1)
terminal = live_running = success = failed = 0
for path in (root / "docking/state/haddock").glob("*.json"):
    try:
        state = json.load(path.open())
    except Exception:
        continue
    status = state.get("status")
    if status in {"success", "failed", "missing"}:
        terminal += 1
    if status == "success":
        success += 1
    if status == "failed":
        failed += 1
    if status == "running":
        try:
            os.kill(int(state.get("pid")), 0)
            live_running += 1
        except (TypeError, ValueError, ProcessLookupError):
            pass
        except PermissionError:
            live_running += 1
print(total, terminal, live_running, success, failed)
PY
  )
  if [[ "$terminal" -ge "$total" ]]; then
    echo "HADDOCK_WATCHDOG_COMPLETE total=$total success=$success failed=$failed time=$(date -Is)" >>"$LOG"
    exit 0
  fi

  sidecar1_alive=0
  sidecar2_alive=0
  pid_alive "$RUN_ROOT/status/haddock_sidecar.pid" && sidecar1_alive=1
  pid_alive "$RUN_ROOT/status/haddock_sidecar2.pid" && sidecar2_alive=1
  expected_live_capacity=$((2 + sidecar1_alive * 6 + sidecar2_alive * 2))

  if [[ "$sidecar1_alive" -eq 0 || "$sidecar2_alive" -eq 0 ]]; then
    if [[ "$live_running" -le "$expected_live_capacity" ]]; then
      if [[ "$sidecar1_alive" -eq 0 ]]; then
        launch_sidecar sidecar1 160 6 "$RUN_ROOT/logs/haddock_load_aware_sidecar.log" "$RUN_ROOT/status/haddock_sidecar.pid"
      fi
      if [[ "$sidecar2_alive" -eq 0 ]]; then
        launch_sidecar sidecar2 120 2 "$RUN_ROOT/logs/haddock_load_aware_sidecar2.log" "$RUN_ROOT/status/haddock_sidecar2.pid"
      fi
    else
      echo "HADDOCK_WATCHDOG_WAIT_ORPHANS live=$live_running expected=$expected_live_capacity time=$(date -Is)" >>"$LOG"
    fi
  fi
  sleep "$POLL_SECONDS"
done
