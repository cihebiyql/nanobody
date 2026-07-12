#!/usr/bin/env bash
set -euo pipefail

MAX_LOAD1=${GEOMETRY4_MAX_LOAD1:-64}
POLL_SECONDS=${GEOMETRY4_POLL_SECONDS:-60}
MAX_WAIT_SECONDS=${GEOMETRY4_MAX_WAIT_SECONDS:-86400}
REMOTE_ROOT=${GEOMETRY4_REMOTE_ROOT:-/data/qlyu/projects/pvrig_v2_5_pose_batch}
HADDOCK_BIN=${GEOMETRY4_HADDOCK_BIN:-/data/qlyu/anaconda3/envs/haddock3/bin/haddock3}
LOADAVG_FILE=${GEOMETRY4_LOADAVG_FILE:-/proc/loadavg}
STATE_DIR="$REMOTE_ROOT/geometry4_waiter"
EVENT_LOG="$STATE_DIR/events.tsv"
STATUS_FILE="$STATE_DIR/status.env"
OWNER_FILE="$STATE_DIR/execution_owner.env"
CANDIDATES=(zym_test_359954 zym_test_3633872 zym_test_8787)

python3 - "$MAX_LOAD1" "$POLL_SECONDS" "$MAX_WAIT_SECONDS" <<'PY'
import math
import re
import sys

try:
    threshold = float(sys.argv[1])
except ValueError as exc:
    raise SystemExit("GEOMETRY4_MAX_LOAD1 must be numeric") from exc
if not math.isfinite(threshold) or threshold <= 0 or threshold > 64:
    raise SystemExit("GEOMETRY4_MAX_LOAD1 must be in (0, 64]")
if not re.fullmatch(r"[1-9][0-9]*", sys.argv[2]) or not re.fullmatch(r"[1-9][0-9]*", sys.argv[3]):
    raise SystemExit("GEOMETRY4_POLL_SECONDS and GEOMETRY4_MAX_WAIT_SECONDS must be positive base-10 integers")
poll_seconds = int(sys.argv[2])
max_wait_seconds = int(sys.argv[3])
if poll_seconds < 10:
    raise SystemExit("GEOMETRY4_POLL_SECONDS must be >= 10")
if max_wait_seconds < poll_seconds:
    raise SystemExit("GEOMETRY4_MAX_WAIT_SECONDS must be >= GEOMETRY4_POLL_SECONDS")
PY
test -r "$LOADAVG_FILE" || { echo "missing loadavg source: $LOADAVG_FILE" >&2; exit 5; }

mkdir -p "$STATE_DIR"
exec 8>"$STATE_DIR/ownership.lock"
if ! flock -n 8; then
  printf 'WAITER_OWNERSHIP_HANDOFF_BUSY\n' >&2
  exit 33
fi
exec 9>"$STATE_DIR/runner.lock"
if ! flock -n 9; then
  printf 'WAITER_ALREADY_RUNNING\n' >&2
  exit 30
fi
if [[ -s "$OWNER_FILE" ]] && grep -qx 'owner=local' "$OWNER_FILE"; then
  echo "REFUSE_LOCAL_EXECUTION_OWNER $OWNER_FILE" >&2
  exit 32
fi
flock -u 8
exec 8>&-

touch "$EVENT_LOG"
start_epoch=$(date +%s)
all_done=0
interrupted_signal=

current_load1() {
  awk '{print $1}' "$LOADAVG_FILE"
}

emit() {
  local event=$1 candidate=${2:--} detail=${3:--}
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date -Is)" "$event" "$candidate" "$(current_load1)" "$detail" | tee -a "$EVENT_LOG"
}

write_status() {
  local state=$1 candidate=${2:--} detail=${3:--}
  local tmp="$STATUS_FILE.tmp.$$"
  {
    printf 'updated_at=%s\n' "$(date -Is)"
    printf 'state=%s\n' "$state"
    printf 'candidate=%s\n' "$candidate"
    printf 'load1=%s\n' "$(current_load1)"
    printf 'threshold=%s\n' "$MAX_LOAD1"
    printf 'detail=%s\n' "$detail"
    printf 'pid=%s\n' "$$"
  } > "$tmp"
  mv "$tmp" "$STATUS_FILE"
}

on_exit() {
  local rc=$?
  trap - EXIT
  if [[ -n "$interrupted_signal" ]]; then
    write_status INTERRUPTED - "signal=$interrupted_signal exit_code=$rc"
    emit RUNNER_INTERRUPTED - "signal=$interrupted_signal exit_code=$rc"
  elif [[ $all_done -eq 1 && $rc -eq 0 ]]; then
    write_status COMPLETE - all_candidates_complete
    emit RUNNER_COMPLETE - all_candidates_complete
  elif [[ $rc -eq 31 ]]; then
    write_status TIMED_OUT - max_wait_exceeded
    emit RUNNER_EXIT - "exit_code=$rc max_wait_exceeded"
  else
    write_status FAILED - "exit_code=$rc"
    emit RUNNER_EXIT - "exit_code=$rc"
  fi
}
handle_signal() {
  local signal_name=$1 exit_code=$2
  interrupted_signal=$signal_name
  trap - HUP INT TERM
  exit "$exit_code"
}
trap on_exit EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

wait_for_gate() {
  local candidate=$1
  while true; do
    local load1 now elapsed
    now=$(date +%s)
    elapsed=$((now - start_epoch))
    if (( elapsed >= MAX_WAIT_SECONDS )); then
      write_status TIMED_OUT "$candidate" "elapsed_seconds=$elapsed"
      emit LOAD_GATE_TIMEOUT "$candidate" "threshold=$MAX_LOAD1 elapsed_seconds=$elapsed"
      return 31
    fi

    load1=$(current_load1)
    if python3 - "$load1" "$MAX_LOAD1" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)
PY
    then
      write_status GATE_ACCEPTED "$candidate" "load1=$load1"
      emit LOAD_GATE_OK "$candidate" "threshold=$MAX_LOAD1"
      return 0
    fi
    write_status WAITING_FOR_LOAD "$candidate" "elapsed_seconds=$elapsed"
    emit LOAD_GATE_WAIT "$candidate" "threshold=$MAX_LOAD1 elapsed_seconds=$elapsed"
    sleep "$POLL_SECONDS"
  done
}

run_complete() {
  local run_dir=$1
  [[ -s "$run_dir/traceback/consensus.tsv" ]] &&
    find "$run_dir/6_seletopclusts" -maxdepth 1 \
      \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) \
      -type f -size +0c -print -quit 2>/dev/null | grep -q .
}

test -x "$HADDOCK_BIN" || { emit REFUSE_MISSING_HADDOCK_BIN - "$HADDOCK_BIN"; exit 21; }
emit RUNNER_START - "threshold=$MAX_LOAD1 poll_seconds=$POLL_SECONDS max_wait_seconds=$MAX_WAIT_SECONDS"

for cid in "${CANDIDATES[@]}"; do
  candidate_dir="$REMOTE_ROOT/haddock3/$cid"
  cfg="${cid}_pvrig_hotspot.cfg"
  run_dir="$candidate_dir/run_${cid}_pvrig_hotspot"
  lock_path="$candidate_dir/.geometry4_haddock.lock"

  exec {candidate_lock_fd}>"$lock_path"
  if ! flock -n "$candidate_lock_fd"; then
    emit REFUSE_CANDIDATE_LOCK_BUSY "$cid" "$lock_path"
    exit 27
  fi

  if run_complete "$run_dir"; then
    emit HADDOCK_ALREADY_COMPLETE "$cid" "$run_dir"
    exec {candidate_lock_fd}>&-
    continue
  fi
  if [[ -e "$run_dir" ]]; then
    emit REFUSE_INCOMPLETE_EXISTING_RUN "$cid" "$run_dir"
    exit 25
  fi
  test -s "$candidate_dir/$cfg" || { emit REFUSE_MISSING_CFG "$cid" "$candidate_dir/$cfg"; exit 22; }
  test -s "$candidate_dir/data/${cid}_vhh_chainA.pdb" || { emit REFUSE_MISSING_VHH "$cid" -; exit 23; }
  test -s "$candidate_dir/data/pvrig_8x6b_chainB.pdb" || { emit REFUSE_MISSING_PVRIG "$cid" -; exit 24; }

  wait_for_gate "$cid"
  if [[ -e "$run_dir" ]]; then
    emit REFUSE_RUN_DIR_APPEARED_AFTER_GATE "$cid" "$run_dir"
    exit 25
  fi

  mkdir -p "$candidate_dir/logs"
  candidate_log="$candidate_dir/logs/${cid}_haddock3_geometry4_$(date +%Y%m%d_%H%M%S).log"
  write_status RUNNING "$cid" "$candidate_log"
  emit HADDOCK_START "$cid" "$candidate_log"
  (
    cd "$candidate_dir"
    "$HADDOCK_BIN" "$cfg"
  ) > "$candidate_log" 2>&1

  if ! run_complete "$run_dir"; then
    emit REFUSE_INCOMPLETE_AFTER_RUN "$cid" "$run_dir"
    exit 26
  fi
  emit HADDOCK_COMPLETE "$cid" "$run_dir"
  exec {candidate_lock_fd}>&-
done

all_done=1
