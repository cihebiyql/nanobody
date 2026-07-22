#!/usr/bin/env bash
set -Eeuo pipefail
BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_cpu_fixed_pose_selected300k_metrics_v1_20260722}
RUNTIME=${RUNTIME:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721}
REMOTE=${REMOTE:-$RUNTIME/pvrig1m_cpu_fixed_pose_selected300k_metrics_v1_20260722}
NODE1=${NODE1:-/data/qlyu/projects/pvrig_1m_cpu_fixed_pose_selected300k_metrics_v1_20260722}
SSH1=/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe
LOCK_DIR=${LOCK_DIR:-$BASE/run/.locks}
mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_DIR/pvrig_fixed_pose300k_metrics_sync.lock"
if ! flock -n 9; then
  echo "another fixed-pose 300k metrics sync controller is active" >&2
  exit 0
fi
while [[ ! -s "$LOCAL/READY_FOR_DEPLOY.json" ]]; do sleep 30; done
"$SSH1" node1 "mkdir -p '$NODE1'"
while true; do
  mkdir -p "$LOCAL/remote_mirror"
  rsync -a --partial --exclude='env' --exclude='models' --exclude='tools' --exclude='vhh_eval_tools' -e ssh \
    "bxcpu:$REMOTE/" "$LOCAL/remote_mirror/"
  rsync -a --partial --append-verify -e "$SSH1" "$LOCAL/remote_mirror/" "node1:$NODE1/"
  if [[ ! -s "$LOCAL/JOB_CHAIN.json" ]]; then
    sleep 120
    continue
  fi
  final=$(python3 - "$LOCAL/JOB_CHAIN.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['jobs']['abnativ'])
PY
)
  state=$(ssh bxcpu "sacct -j '$final' --format=State -n -X 2>/dev/null" | awk 'NF{print $1;exit}' || true)
  case "$state" in
    COMPLETED)
      python3 - "$LOCAL/remote_mirror/status" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
names=(
    'RISK_COMPLETE.json',
    'ANARCI_COMPLETE.json',
    'BINDING_COMPLETE.json',
    'SAPIENS_FULL_COMPLETE.json',
    'ABNATIV_FULL_COMPLETE.json',
)
for name in names:
    path=root/name
    if not path.is_file(): raise SystemExit(f'missing required metrics status: {path}')
    payload=json.load(open(path))
    if payload.get('status')!='PASS': raise SystemExit(f'non-PASS metrics status: {path}: {payload.get("status")}')
    if int(payload.get('records',-1))!=300000: raise SystemExit(f'wrong record count: {path}: {payload.get("records")}')
PY
      python3 - "$LOCAL/remote_mirror" "$LOCAL/METRICS_SYNC_COMPLETE.json" "$final" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
r,out,job=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
files=[p for p in r.rglob('*') if p.is_file()]
out.write_text(json.dumps({'status':'FINAL_JOB_COMPLETED_AND_REMOTE_MIRROR_SYNCED','final_job_id':job,'files':len(files),
 'bytes':sum(p.stat().st_size for p in files),'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
      rsync -a -e "$SSH1" "$LOCAL/METRICS_SYNC_COMPLETE.json" "node1:$NODE1/METRICS_SYNC_COMPLETE.json"; break ;;
    FAILED*|CANCELLED*|TIMEOUT*|OUT_OF_MEMORY*) echo "metrics chain terminal failure: $state" >&2; exit 8 ;;
  esac
  sleep 120
done
