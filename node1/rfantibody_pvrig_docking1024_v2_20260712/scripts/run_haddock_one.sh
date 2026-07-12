#!/usr/bin/env bash
set -Eeuo pipefail

CID=${1:?Usage: run_haddock_one.sh CANDIDATE_ID}
RUN_ROOT=${RUN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
DOCKING_ROOT=${DOCKING_ROOT:-$RUN_ROOT/docking}
HADDOCK3=${HADDOCK3:-/data/qlyu/anaconda3/envs/haddock3/bin/haddock3}
BOLTZ_BIN=${BOLTZ_BIN:-/data/qlyu/anaconda3/envs/boltz/bin}
CFG=${CFG:-$DOCKING_ROOT/haddock/$CID/${CID}_pvrig_8x6b_full_interface.cfg}
LOCKDIR="$DOCKING_ROOT/locks/haddock/$CID.lock"
STATE="$DOCKING_ROOT/state/haddock/$CID.json"
LOG="$DOCKING_ROOT/logs/haddock/${CID}.log"
RUN_DIR="$DOCKING_ROOT/haddock/$CID/run_${CID}_pvrig_8x6b_full_interface"

mkdir -p "$DOCKING_ROOT"/{locks/haddock,state/haddock,logs/haddock,reports}
PREVIOUS_ATTEMPT=$(python3 - "$STATE" <<'PY'
import json
import sys
try:
    print(int(json.load(open(sys.argv[1])).get("attempt", 0)))
except Exception:
    print(0)
PY
)
ATTEMPT=$((PREVIOUS_ATTEMPT + 1))

write_state() {
  local status=$1 rc=${2:-0} message=${3:-}
  python3 - "$STATE" "$CID" "$status" "$rc" "$message" "$ATTEMPT" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    "candidate_id": sys.argv[2],
    "stage": "haddock",
    "status": sys.argv[3],
    "pid": os.getppid(),
    "return_code": int(sys.argv[4]),
    "message": sys.argv[5],
    "attempt": int(sys.argv[6]),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
tmp = path.with_name(f".{path.name}.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
tmp.replace(path)
PY
}

if find "$RUN_DIR" -type f \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) -print -quit 2>/dev/null | grep -q .; then
  write_state success 0 "existing HADDOCK cluster model found"
  echo "HADDOCK_SKIP_SUCCESS cid=$CID"
  exit 0
fi
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "HADDOCK_SKIP_LOCKED cid=$CID"
  exit 75
fi
trap 'rm -rf "$LOCKDIR"' EXIT
if [[ ! -s "$DOCKING_ROOT/haddock/$CID/data/${CID}_vhh_chainA.pdb" ]]; then
  write_state missing 2 "missing NBB2 monomer for HADDOCK"
  echo "HADDOCK_MISSING_MONOMER cid=$CID" >&2
  exit 2
fi
if [[ ! -s "$CFG" ]]; then
  write_state missing 2 "missing HADDOCK config"
  echo "HADDOCK_MISSING_CFG cid=$CID cfg=$CFG" >&2
  exit 2
fi
write_state running 0 ""
echo "HADDOCK_START cid=$CID time=$(date -Is)" | tee -a "$LOG"
set +e
(cd "$DOCKING_ROOT/haddock/$CID" && PATH="$BOLTZ_BIN:$PATH" "$HADDOCK3" "$(basename "$CFG")" >>"$LOG" 2>&1)
rc=$?
set -e
if [[ $rc -eq 0 ]] && find "$RUN_DIR" -type f \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) -print -quit 2>/dev/null | grep -q .; then
  write_state success 0 "selected HADDOCK cluster model verified"
else
  if [[ $rc -eq 0 ]]; then
    rc=4
    message="HADDOCK3 exited zero but no selected cluster model was produced"
  else
    message="HADDOCK3 exited non-zero"
  fi
  write_state failed "$rc" "$message"
fi
echo "HADDOCK_EXIT cid=$CID rc=$rc time=$(date -Is)" | tee -a "$LOG"
exit "$rc"
