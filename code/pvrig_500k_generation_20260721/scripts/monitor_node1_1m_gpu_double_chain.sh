#!/usr/bin/env bash
set -Eeuo pipefail

CURRENT_RF=${CURRENT_RF:-/data1/qlyu/projects/pvrig_500k_rfantibody75k_v1_20260721}
CURRENT_MPNN=${CURRENT_MPNN:-/data1/qlyu/projects/pvrig_500k_fixed_pose_mpnn75k_v2_20260721}
RF2=${RF2:-/data1/qlyu/projects/pvrig_1m_rfantibody150k_v1_20260722}
MPNN2=${MPNN2:-/data1/qlyu/projects/pvrig_1m_fixed_pose_mpnn150k_v1_20260722}
STATUS_ROOT=${STATUS_ROOT:-/data1/qlyu/projects/pvrig_1m_gpu_double_prepare_v1_20260722}
MIN_FREE_GB=${MIN_FREE_GB:-100}
POLL_SECONDS=${POLL_SECONDS:-60}
DISK_PATH=${DISK_PATH:-/data1}
mkdir -p "$STATUS_ROOT"
exec 9>"$STATUS_ROOT/chain.lock"
flock -n 9 || { echo "1M GPU expansion watcher already running" >&2; exit 75; }

state_of() {
  python3 - "$1/status/controller.json" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1])).get("state", "UNKNOWN"))
except Exception: print("UNKNOWN")
PY
}

controller_pid() {
  local root=$1 pid_file="$1/status/controller.pid"
  if [[ -s "$pid_file" ]]; then
    tr -dc '0-9' <"$pid_file"
    return 0
  fi
  python3 - "$root/status/controller.json" <<'PY'
import json,sys
try:
    pid=int(json.load(open(sys.argv[1])).get("pid", 0))
    print(pid if pid > 0 else "")
except Exception:
    print("")
PY
}

controller_alive() {
  local pid
  pid=$(controller_pid "$1")
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

write_state() {
  python3 - "$STATUS_ROOT/CHAIN_STATUS.json" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "state":sys.argv[2], "message":sys.argv[3], "pid":os.getppid(),
    "updated_at":datetime.now(timezone.utc).isoformat(),
},indent=2,sort_keys=True)+"\n")
PY
}

wait_for_terminal() {
  local root=$1 label=$2 state dead_polls=0
  while true; do
    state=$(state_of "$root")
    write_state "WAITING_${label}" "state=$state root=$root"
    case "$state" in
      COMPLETE|HOLD) printf '%s\n' "$state"; return 0 ;;
      FAILED|BLOCKED) printf '%s\n' "$state"; return 5 ;;
      *)
        if controller_alive "$root"; then
          dead_polls=0
        else
          dead_polls=$((dead_polls + 1))
          if (( dead_polls >= 3 )); then
            printf 'DEAD_CONTROLLER(state=%s,root=%s)\n' "$state" "$root"
            return 6
          fi
        fi
        sleep "$POLL_SECONDS"
        ;;
    esac
  done
}

start_rf2_if_needed() {
  local state
  state=$(state_of "$RF2")
  case "$state" in
    COMPLETE|HOLD) return 0 ;;
    FAILED|BLOCKED) return 6 ;;
  esac
  if controller_alive "$RF2"; then
    write_state RESUMING_RF2 "state=$state pid=$(controller_pid "$RF2")"
    return 0
  fi
  write_state STARTING_RF2 "current MPNN terminal=$current_terminal"
  RUN_ROOT="$RF2" nohup bash "$RF2/scripts/run_rfantibody_75k_controller.sh" \
    >"$RF2/logs/controller.log" 2>&1 &
  echo $! > "$RF2/status/controller.pid"
}

start_mpnn2_if_needed() {
  local state
  state=$(state_of "$MPNN2")
  case "$state" in
    COMPLETE|HOLD) return 0 ;;
    FAILED|BLOCKED) return 7 ;;
  esac
  if controller_alive "$MPNN2"; then
    write_state RESUMING_MPNN2 "state=$state pid=$(controller_pid "$MPNN2")"
    return 0
  fi
  write_state STARTING_MPNN2 "RF2 terminal=$rf2_terminal"
  RUN_ROOT="$MPNN2" RF_RUN_ROOT="$RF2" nohup bash "$MPNN2/scripts/run_fixed_pose_mpnn_controller.sh" \
    >"$MPNN2/logs/controller.log" 2>&1 &
  echo $! > "$MPNN2/status/controller.pid"
}

wait_for_disk() {
  local label=$1 free_kb free_gb
  while true; do
    free_kb=$(df -Pk "$DISK_PATH" | awk 'NR==2 {print $4}')
    free_gb=$((free_kb / 1024 / 1024))
    if (( free_gb >= MIN_FREE_GB )); then return 0; fi
    write_state WAITING_DISK "$label requires ${MIN_FREE_GB}GiB free; observed ${free_gb}GiB"
    sleep 300
  done
}

current_terminal=$(wait_for_terminal "$CURRENT_MPNN" CURRENT_MPNN) || {
  write_state BLOCKED "current fixed-pose campaign terminal failure: $current_terminal"
  exit 5
}

wait_for_disk RF2
start_rf2_if_needed || {
  write_state BLOCKED "cannot start or resume doubled RFantibody campaign"
  exit 6
}

rf2_terminal=$(wait_for_terminal "$RF2" RF2) || {
  write_state BLOCKED "doubled RFantibody campaign terminal failure: $rf2_terminal"
  exit 6
}

wait_for_disk MPNN2
start_mpnn2_if_needed || {
  write_state BLOCKED "cannot start or resume doubled fixed-pose campaign"
  exit 7
}

mpnn2_terminal=$(wait_for_terminal "$MPNN2" MPNN2) || {
  write_state BLOCKED "doubled fixed-pose campaign terminal failure: $mpnn2_terminal"
  exit 7
}

write_state COMPLETE "current MPNN=$current_terminal RF2=$rf2_terminal MPNN2=$mpnn2_terminal"
date -Is > "$STATUS_ROOT/CHAIN_COMPLETE"
