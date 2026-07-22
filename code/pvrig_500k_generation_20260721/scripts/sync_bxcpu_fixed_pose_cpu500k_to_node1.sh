#!/usr/bin/env bash
set -Eeuo pipefail

: "${JOB_ID:?JOB_ID is required}"
BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_cpu_fixed_pose500k_raw_v3_20260722/bxcpu_results_${JOB_ID}}
BX_ROOT=${BX_ROOT:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721/pvrig1m_cpu_fixed_pose500k_raw_v3_20260722}
NODE1_ROOT=${NODE1_ROOT:-/data/qlyu/projects/pvrig_1m_cpu_fixed_pose500k_raw_v3_20260722/bxcpu_results_${JOB_ID}}
POLL=${POLL:-20}
NODE1_SSH=/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe

mkdir -p "$LOCAL/receipts"
"$NODE1_SSH" node1 "mkdir -p '$NODE1_ROOT'"
for index in {0..7}; do
  node=$(printf 'node_%02d' "$index")
  remote="$BX_ROOT/results_${JOB_ID}/$node"
  local_node="$LOCAL/$node"
  receipt="$LOCAL/receipts/$node.json"
  while ! ssh bxcpu "test -s '$remote/READY.json'"; do sleep "$POLL"; done
  mkdir -p "$local_node"
  rsync -a --partial --append-verify -e ssh "bxcpu:$remote/" "$local_node/"
  archive="$local_node/${node}_sequence_outputs.tar.gz"
  expected=$(awk '{print $1}' "$local_node/${node}_sequence_outputs.sha256")
  observed=$(sha256sum "$archive" | awk '{print $1}')
  [[ "$observed" == "$expected" ]]
  tar -tzf "$archive" >/dev/null
  rsync -a --partial --append-verify -e "$NODE1_SSH" "$local_node/" "node1:$NODE1_ROOT/$node/"
  node1_hash=$("$NODE1_SSH" node1 "sha256sum '$NODE1_ROOT/$node/$(basename "$archive")'" | awk '{print $1}')
  [[ "$node1_hash" == "$expected" ]]
  python3 - "$receipt" "$node" "$expected" "$archive" "$NODE1_ROOT/$node" <<'PY'
import json,sys,time
from pathlib import Path
out,node,digest,archive,node1=Path(sys.argv[1]),*sys.argv[2:]
out.write_text(json.dumps({'status':'LOCAL_AND_NODE1_HASH_VERIFIED','node':node,'sha256':digest,
 'local_archive':archive,'node1_dir':node1,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
  rsync -a -e "$NODE1_SSH" "$receipt" "node1:$NODE1_ROOT/$node/SYNC_RECEIPT.json"
  # The array job writes final archives only; purge this small publication after
  # both durable copies close. Compute-node scratch is managed by Slurm.
  ssh bxcpu "python3 - '$remote' '$BX_ROOT/results_${JOB_ID}' '$node' <<'PY'
import shutil,sys
from pathlib import Path
target,root,node=Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve(),sys.argv[3]
if target.parent != root or target.name != node or not node.startswith('node_'):
    raise SystemExit('unsafe purge target')
shutil.rmtree(target)
PY"
done
python3 - "$LOCAL" "$NODE1_ROOT" "$JOB_ID" <<'PY'
import json,sys,time
from pathlib import Path
root,node1,job=Path(sys.argv[1]),sys.argv[2],sys.argv[3]
rows=[json.loads(p.read_text()) for p in sorted((root/'receipts').glob('node_*.json'))]
if len(rows)!=8: raise SystemExit(f'expected 8 receipts, found {len(rows)}')
(root/'SYNC_COMPLETE.json').write_text(json.dumps({'status':'ALL_8_NODES_LOCAL_AND_NODE1_HASH_VERIFIED',
 'job_id':job,'node1_root':node1,'nodes':rows,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
rsync -a -e "$NODE1_SSH" "$LOCAL/SYNC_COMPLETE.json" "node1:$NODE1_ROOT/SYNC_COMPLETE.json"
