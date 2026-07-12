#!/usr/bin/env bash
set -euo pipefail

MODE=plan
if [[ ${1:-} == "--execute" ]]; then
  MODE=execute
elif [[ $# -gt 0 && ${1:-} != "--plan" ]]; then
  echo "usage: $0 [--plan|--execute]" >&2
  exit 2
fi

SSH_BIN=${GEOMETRY4_SSH_BIN:-}
if [[ -z "$SSH_BIN" ]]; then
  if command -v ssh.exe >/dev/null 2>&1; then
    SSH_BIN=ssh.exe
  else
    SSH_BIN=ssh
  fi
fi

HOST=${GEOMETRY4_SSH_HOST:-node1}
MAX_LOAD1=${GEOMETRY4_MAX_LOAD1:-64}
REMOTE_ROOT=/data/qlyu/projects/pvrig_v2_5_pose_batch
HADDOCK_BIN=/data/qlyu/anaconda3/envs/haddock3/bin/haddock3
CANDIDATES=(zym_test_359954 zym_test_3633872 zym_test_8787)

python3 - "$MAX_LOAD1" <<'PY'
import math
import sys

value = float(sys.argv[1])
if not math.isfinite(value) or value <= 0 or value > 64:
    raise SystemExit("GEOMETRY4_MAX_LOAD1 must be in (0, 64]")
PY

for cid in "${CANDIDATES[@]}"; do
  "$SSH_BIN" "$HOST" bash -s -- "$MODE" "$MAX_LOAD1" "$REMOTE_ROOT" "$HADDOCK_BIN" "$cid" <<'REMOTE'
set -euo pipefail

mode=$1
max_load1=$2
root=$3
haddock_bin=$4
cid=$5
candidate_dir="$root/haddock3/$cid"
cfg="${cid}_pvrig_hotspot.cfg"
run_dir="run_${cid}_pvrig_hotspot"
log_dir="$candidate_dir/logs"
lock_file="$candidate_dir/.geometry4_haddock.lock"
state_dir="$root/geometry4_waiter"
owner_file="$state_dir/execution_owner.env"

mkdir -p "$state_dir"
exec 8>"$state_dir/ownership.lock"
if ! flock -n 8; then
  echo "REFUSE_OWNERSHIP_HANDOFF_BUSY $state_dir/ownership.lock"
  exit 29
fi
if [[ -s "$owner_file" ]] && grep -qx 'owner=local' "$owner_file"; then
  echo "REFUSE_LOCAL_EXECUTION_OWNER $owner_file"
  exit 32
fi

exec 9>"$lock_file"
if ! flock -n 9; then
  echo "REFUSE_CANDIDATE_LOCK_BUSY $cid $lock_file"
  exit 28
fi

load1=$(awk '{print $1}' /proc/loadavg)
python3 - "$load1" "$max_load1" <<'PY'
import sys
import math

load1 = float(sys.argv[1])
threshold = float(sys.argv[2])
if not math.isfinite(load1) or not math.isfinite(threshold) or load1 >= threshold:
    print(f"LOAD_GATE_REFUSE load1={load1} threshold={threshold}")
    raise SystemExit(20)
print(f"LOAD_GATE_OK load1={load1} threshold={threshold}")
PY

test -x "$haddock_bin" || { echo "REFUSE_MISSING_HADDOCK_BIN $haddock_bin"; exit 21; }
test -s "$candidate_dir/$cfg" || { echo "REFUSE_MISSING_CFG $candidate_dir/$cfg"; exit 22; }
test -s "$candidate_dir/data/${cid}_vhh_chainA.pdb" || { echo "REFUSE_MISSING_VHH $cid"; exit 23; }
test -s "$candidate_dir/data/pvrig_8x6b_chainB.pdb" || { echo "REFUSE_MISSING_PVRIG $cid"; exit 24; }

if [[ -s "$candidate_dir/$run_dir/traceback/consensus.tsv" ]] && \
   find "$candidate_dir/$run_dir/6_seletopclusts" -maxdepth 1 \
     \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) \
     -type f -size +0c -print -quit 2>/dev/null | grep -q .; then
  echo "HADDOCK_ALREADY_COMPLETE $cid"
  exit 0
fi

if [[ -e "$candidate_dir/$run_dir" ]]; then
  echo "REFUSE_INCOMPLETE_EXISTING_RUN $candidate_dir/$run_dir"
  exit 25
fi

if [[ "$mode" == plan ]]; then
  echo "HADDOCK_PLAN_READY $cid root=$candidate_dir threshold=$max_load1"
  exit 0
fi

mkdir -p "$log_dir"
log="$log_dir/${cid}_haddock3_geometry4_$(date +%Y%m%d_%H%M%S).log"
echo "HADDOCK_START $cid $(date -Is) log=$log"
(
  cd "$candidate_dir"
  "$haddock_bin" "$cfg"
) >"$log" 2>&1

test -s "$candidate_dir/$run_dir/traceback/consensus.tsv" || {
  echo "REFUSE_MISSING_TRACEBACK_AFTER_RUN $cid"
  exit 26
}
find "$candidate_dir/$run_dir/6_seletopclusts" -maxdepth 1 \
  \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) \
  -type f -size +0c -print -quit | grep -q . || {
    echo "REFUSE_MISSING_TOP_POSES_AFTER_RUN $cid"
    exit 27
  }
echo "HADDOCK_COMPLETE $cid $(date -Is)"
REMOTE
done
