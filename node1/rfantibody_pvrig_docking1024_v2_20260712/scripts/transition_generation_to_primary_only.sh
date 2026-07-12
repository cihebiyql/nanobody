#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
PRIMARY_ARM_TABLE=${PRIMARY_ARM_TABLE:-$RUN_ROOT/config/generation_arms_primary.tsv}
POLL_SECONDS=${POLL_SECONDS:-2}
MAX_LOAD1=${MAX_LOAD1:-400}
GPU_MEMORY_GATE_MB=${GPU_MEMORY_GATE_MB:-12000}
STATUS_ROOT="$RUN_ROOT/status/primary_only_transition"
LOG="$RUN_ROOT/logs/primary_only_transition.log"

mkdir -p "$STATUS_ROOT" "$RUN_ROOT/logs"
exec 9>"$RUN_ROOT/status/primary_only_transition.lock"
if ! flock -n 9; then
  echo "Primary-only transition is already running"
  exit 0
fi

[[ -s "$PRIMARY_ARM_TABLE" ]] || { echo "Missing primary arm table: $PRIMARY_ARM_TABLE" >&2; exit 2; }
[[ $(awk 'NR > 1 { count++ } END { print count+0 }' "$PRIMARY_ARM_TABLE") -eq 36 ]] || {
  echo "Primary arm table must contain exactly 36 arms" >&2
  exit 2
}

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

kill_tree() {
  local root_pid=$1
  python3 - "$root_pid" "$RUN_ROOT" <<'PY'
import os
import signal
import subprocess
import sys
import time

root = int(sys.argv[1])
run_root = sys.argv[2]
rows = subprocess.check_output(["ps", "-eo", "pid=,ppid=,args="], text=True).splitlines()
children = {}
commands = {}
for raw in rows:
    parts = raw.strip().split(None, 2)
    if len(parts) < 2:
        continue
    pid, ppid = map(int, parts[:2])
    commands[pid] = parts[2] if len(parts) == 3 else ""
    children.setdefault(ppid, []).append(pid)

if root not in commands or run_root not in commands[root] or "launch_generation_multi_gpu.sh" not in commands[root]:
    raise SystemExit(f"refusing to stop unexpected lane pid={root} command={commands.get(root)!r}")

ordered = []
def walk(pid):
    for child in children.get(pid, []):
        walk(child)
    ordered.append(pid)
walk(root)

for pid in ordered:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(1)
for pid in ordered:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        continue
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
PY
}

monitor_lane() {
  local gpu=$1 first_arm=$2 controller_pid=$3
  while [[ ! -s "$RUN_ROOT/generation/arms/$first_arm/complete.json" ]]; do
    if ! kill -0 "$controller_pid" 2>/dev/null; then
      log "controller exited before first arm completed gpu=$gpu arm=$first_arm"
      return 1
    fi
    sleep "$POLL_SECONDS"
  done

  local lane_pid
  lane_pid=$(cat "$RUN_ROOT/status/generation/gpu_${gpu}.pid")
  log "first arm complete; stopping old lane gpu=$gpu arm=$first_arm lane_pid=$lane_pid"
  if kill -0 "$lane_pid" 2>/dev/null; then
    kill_tree "$lane_pid"
  fi
  date -Is > "$STATUS_ROOT/gpu_${gpu}.stopped"
}

controller_pid=$(cat "$RUN_ROOT/status/generation_controller.pid")
kill -0 "$controller_pid" 2>/dev/null || { echo "Generation controller is not running" >&2; exit 3; }
log "waiting for the six in-flight first arms before dropping unused diagnostic arms controller_pid=$controller_pid"

declare -a watchers=()
for lane in \
  "1:P1_orig_S" \
  "2:P1_orig_L" \
  "3:P1_qrg_S" \
  "4:P1_qrg_L" \
  "5:P1_ekg_S" \
  "7:P1_ekg_L"; do
  gpu=${lane%%:*}
  arm=${lane#*:}
  monitor_lane "$gpu" "$arm" "$controller_pid" &
  watchers+=("$!")
done

rc=0
for watcher in "${watchers[@]}"; do
  wait "$watcher" || rc=1
done
[[ $rc -eq 0 ]] || { log "lane transition failed"; exit 4; }

for _ in $(seq 1 60); do
  kill -0 "$controller_pid" 2>/dev/null || break
  sleep 1
done
if kill -0 "$controller_pid" 2>/dev/null; then
  log "old controller still alive after all lanes stopped; terminating pid=$controller_pid"
  kill -TERM "$controller_pid"
  for _ in $(seq 1 20); do
    kill -0 "$controller_pid" 2>/dev/null || break
    sleep 1
  done
  kill -0 "$controller_pid" 2>/dev/null && { log "old controller did not exit"; exit 5; }
fi

python3 - "$RUN_ROOT" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
first = {"P1_orig_S", "P1_orig_L", "P1_qrg_S", "P1_qrg_L", "P1_ekg_S", "P1_ekg_L"}
partial = []
for arm in (root / "generation" / "arms").glob("*"):
    if arm.name in first:
        continue
    pdb = len(list((arm / "backbones").glob("design_*.pdb")))
    trb = len(list((arm / "backbones").glob("design_*.trb")))
    if pdb or trb:
        partial.append((arm.name, pdb, trb))
if partial:
    raise SystemExit(f"refusing primary-only restart because a next arm already has RF outputs: {partial}")
PY

if ps -eo args | grep "$RUN_ROOT" | grep -E 'launch_generation_multi_gpu|run_generation_arm|rfdiffusion_inference.py|proteinmpnn_interface_design.py' | grep -v grep >/dev/null; then
  log "refusing restart because generation workers remain"
  exit 5
fi

rm -f "$RUN_ROOT/status/generation"/gpu_*.pid "$RUN_ROOT/status/generation"/gpu_*.complete
log "starting primary-only generation controller with 36 cohort-producing arms"
nohup env MAX_LOAD1="$MAX_LOAD1" GPU_MEMORY_GATE_MB="$GPU_MEMORY_GATE_MB" \
  GENERATION_ARM_TABLE="$PRIMARY_ARM_TABLE" \
  bash "$RUN_ROOT/scripts/run_generation_controller.sh" \
  >"$RUN_ROOT/logs/generation_pipeline_controller.log" 2>&1 < /dev/null &
new_pid=$!
echo "$new_pid" > "$RUN_ROOT/status/generation_controller.pid"
sleep 5
kill -0 "$new_pid" 2>/dev/null || { log "primary-only controller failed to stay alive pid=$new_pid"; exit 6; }
date -Is > "$RUN_ROOT/status/primary_only_transition.complete"
log "primary-only generation controller started pid=$new_pid"
