#!/usr/bin/env bash
set -Eeuo pipefail
BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
SELECT=${SELECT:-$BASE/run/pvrig_1m_fixed_pose_top150k_structure_input_v1_20260722}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
RUNTIME=${RUNTIME:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721}
REMOTE=${REMOTE:-$RUNTIME/pvrig1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
NODE1=${NODE1:-/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_nbb2_batched_v1_20260722}
SSH1=/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe
LOCK_DIR=${LOCK_DIR:-$BASE/run/.locks}
mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_DIR/pvrig_fixed_pose150k_nbb2_batched.lock"
if ! flock -n 9; then
 echo "another fixed-pose 150k NBB2 batched controller is active" >&2
 exit 0
fi
while [[ ! -s "$SELECT/READY.json" ]]; do sleep 60; done
if [[ ! -s "$LOCAL/READY.json" ]]; then
 python3 "$BASE/scripts/prepare_batched_nbb2_150k.py" --input "$SELECT/fixed_pose_top150k_for_structure.fasta.gz" --output-dir "$LOCAL"
fi
ssh bxcpu "mkdir -p '$REMOTE'"
# Only deploy immutable wave inputs.  Local receipts and downloaded archives
# are intentionally excluded so a resumed controller cannot feed results back
# into the bxcpu staging tree.
rsync -a --partial --append-verify -e ssh \
 --include='/READY.json' --include='/wave_*/' --include='/wave_*/input/***' --exclude='*' \
 "$LOCAL/" "bxcpu:$REMOTE/"
"$SSH1" node1 "mkdir -p '$NODE1'"
mkdir -p "$LOCAL/receipts"

submit_wave() {
 local remote_wave=$1 output rc
 while true; do
  set +e
  output=$(ssh bxcpu "sbatch --parsable --array=0-7%8 --export=ALL,RUNTIME_ROOT='$RUNTIME',CAMPAIGN_ROOT='$remote_wave' '$RUNTIME/scripts/run_bxcpu_nbb2_generic.slurm'" 2>>"$LOCAL/submit_retry.log")
  rc=$?
  set -e
  if [[ "$rc" -eq 0 && "$output" =~ ^[0-9]+([_;].*)?$ ]]; then
   printf '%s\n' "${output%%[_;]*}"
   return 0
  fi
  printf '%s waiting to submit %s rc=%s\n' "$(date -Is)" "$remote_wave" "$rc" >>"$LOCAL/submit_retry.log"
  sleep 60
 done
}

for wi in 0 1 2 3; do
 wave=$(printf 'wave_%02d' "$wi"); remote_wave="$REMOTE/$wave"; local_wave="$LOCAL/$wave"
 job_file="$local_wave/JOB_ID"
 if [[ -s "$job_file" ]]; then job=$(cat "$job_file"); else
  job=$(submit_wave "$remote_wave")
  printf '%s\n' "$job" >"$job_file"
 fi
 for idx in {0..7}; do
  node=$(printf 'node_%03d' "$idx"); archive="$node.tar.gz"; remote_arch="$remote_wave/archives_$job"
  receipt="$LOCAL/receipts/${wave}_${node}.json"
  if [[ -s "$receipt" ]]; then
   expected=$(python3 - "$receipt" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['sha256'])
PY
)
   node1hash=$("$SSH1" node1 "sha256sum '$NODE1/$wave/archives_$job/$archive'" | awk '{print $1}')
   [[ "$expected" == "$node1hash" ]]
   if [[ -f "$local_wave/archives_$job/$archive" ]]; then
    observed=$(sha256sum "$local_wave/archives_$job/$archive" | awk '{print $1}')
    [[ "$expected" == "$observed" ]]
   else
    purge_receipt="$LOCAL/receipts/${wave}_${node}.LOCAL_ARCHIVE_PURGED.json"
    [[ -s "$purge_receipt" ]]
    python3 - "$purge_receipt" "$expected" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
if x.get('status')!='PURGED_AFTER_NODE1_WAVE_REVALIDATION' or x.get('sha256')!=sys.argv[2]:
    raise SystemExit('local archive purge receipt mismatch')
PY
   fi
   continue
  fi
  while ! ssh bxcpu "test -s '$remote_arch/$node.READY.json'"; do
   state=$(ssh bxcpu "sacct -j '$job' --format=State -n -X 2>/dev/null" | awk 'NF{print $1;exit}' || true)
   case "$state" in FAILED*|CANCELLED*|TIMEOUT*|OUT_OF_MEMORY*) echo "NBB2 wave failed $wave $state" >&2; exit 8;; esac
   sleep 30
  done
  mkdir -p "$local_wave/archives_$job"
  rsync -a --partial --append-verify -e ssh \
    --include="$archive" --include="$node.sha256" --include="$node.READY.json" --exclude='*' \
    "bxcpu:$remote_arch/" "$local_wave/archives_$job/"
  expected=$(awk '{print $1}' "$local_wave/archives_$job/$node.sha256"); observed=$(sha256sum "$local_wave/archives_$job/$archive"|awk '{print $1}'); [[ "$expected" == "$observed" ]]
  tar -tzf "$local_wave/archives_$job/$archive" >/dev/null
  "$SSH1" node1 "mkdir -p '$NODE1/$wave/archives_$job'"
  rsync -a --partial --append-verify -e "$SSH1" "$local_wave/archives_$job/$archive" "$local_wave/archives_$job/$node.sha256" "$local_wave/archives_$job/$node.READY.json" "node1:$NODE1/$wave/archives_$job/"
  node1hash=$("$SSH1" node1 "sha256sum '$NODE1/$wave/archives_$job/$archive'"|awk '{print $1}'); [[ "$node1hash" == "$expected" ]]
  python3 - "$receipt" "$wave" "$node" "$job" "$expected" <<'PY'
import json,sys,time
from pathlib import Path
p=Path(sys.argv[1]);p.write_text(json.dumps({'status':'LOCAL_AND_NODE1_ARCHIVE_HASH_VERIFIED','wave':sys.argv[2],'node':sys.argv[3],'job_id':sys.argv[4],'sha256':sys.argv[5],'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
 done
 python3 - "$LOCAL/$wave/COMPLETE.json" "$LOCAL/receipts" "$wave" "$job" <<'PY'
import json,sys,time
from pathlib import Path
out,receipts,wave,job=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4]
rows=[json.load(open(p)) for p in sorted(receipts.glob(f'{wave}_node_*.json'))]
if len(rows)!=8: raise SystemExit(f'expected 8 durable receipts for {wave}, found {len(rows)}')
out.write_text(json.dumps({'status':'WAVE_8_NODES_LOCAL_AND_NODE1_HASH_VERIFIED','wave':wave,'job_id':job,
 'archives':rows,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
 "$SSH1" node1 "mkdir -p '$NODE1/$wave'"; rsync -a -e "$SSH1" "$LOCAL/$wave/COMPLETE.json" "node1:$NODE1/$wave/COMPLETE.json"
 for idx in {0..7}; do
  node=$(printf 'node_%03d' "$idx"); archive="$node.tar.gz"
  expected=$(python3 - "$LOCAL/receipts/${wave}_${node}.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['sha256'])
PY
)
  node1hash=$("$SSH1" node1 "sha256sum '$NODE1/$wave/archives_$job/$archive'" | awk '{print $1}')
  [[ "$expected" == "$node1hash" ]]
 done
 date -Is >"$LOCAL/$wave/NODE1_WAVE_REVERIFIED"
 rsync -a -e "$SSH1" "$LOCAL/$wave/NODE1_WAVE_REVERIFIED" "node1:$NODE1/$wave/NODE1_WAVE_REVERIFIED"
 # Purge the bxcpu staging copy only after the complete eight-node wave manifest
 # and every archive hash have been verified on both local storage and Node1.
 ssh bxcpu "python3 - '$remote_wave/results_$job' '$remote_arch' <<'PY'
import shutil,sys
from pathlib import Path
results,archives=(Path(x).resolve() for x in sys.argv[1:])
if results.parent != archives.parent or not results.name.startswith('results_') or not archives.name.startswith('archives_'):
    raise SystemExit('unsafe wave purge target')
if results.is_dir(): shutil.rmtree(results)
if archives.is_dir(): shutil.rmtree(archives)
PY"
 for idx in {0..7}; do
  node=$(printf 'node_%03d' "$idx"); archive="$node.tar.gz"
  local_archive="$local_wave/archives_$job/$archive"
  purge_receipt="$LOCAL/receipts/${wave}_${node}.LOCAL_ARCHIVE_PURGED.json"
  if [[ -f "$local_archive" ]]; then
   expected=$(python3 - "$LOCAL/receipts/${wave}_${node}.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['sha256'])
PY
)
   bytes=$(stat -c '%s' "$local_archive")
   python3 - "$purge_receipt" "$wave" "$node" "$job" "$expected" "$bytes" "$NODE1/$wave/archives_$job/$archive" <<'PY'
import json,sys,time
from pathlib import Path
out,wave,node,job,digest,size,durable=sys.argv[1:]
Path(out).write_text(json.dumps({'status':'PURGED_AFTER_NODE1_WAVE_REVALIDATION','wave':wave,'node':node,
 'job_id':job,'sha256':digest,'bytes':int(size),'durable_node1_path':durable,
 'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
   rm -f "$local_archive"
  fi
 done
 python3 - "$LOCAL/$wave/PURGE_COMPLETE.json" "$wave" "$job" <<'PY'
import json,sys,time
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'status':'BXCPU_WAVE_PURGED_AFTER_8_NODE_DURABLE_ACK','wave':sys.argv[2],
 'job_id':sys.argv[3],'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
 rsync -a -e "$SSH1" "$LOCAL/$wave/PURGE_COMPLETE.json" "node1:$NODE1/$wave/PURGE_COMPLETE.json"
done
python3 - "$LOCAL/READY.json" "$LOCAL/NBB2_ALL_WAVES_COMPLETE.json" <<'PY'
import json,sys,time
from pathlib import Path
d=json.load(open(sys.argv[1]));Path(sys.argv[2]).write_text(json.dumps({'status':'NBB2_150K_ALL_WAVES_ARCHIVED_LOCAL_NODE1_HASH_VERIFIED_AND_BXCPU_PURGED','records':d['records'],'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
rsync -a -e "$SSH1" "$LOCAL/NBB2_ALL_WAVES_COMPLETE.json" "node1:$NODE1/NBB2_ALL_WAVES_COMPLETE.json"
