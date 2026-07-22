#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}"
LOCAL="${LOCAL:-$BASE/run/pvrig_1m_old_cpu_remainder344295_quota_pause_v1_20260722}"
REMOTE="${REMOTE:-/data/qlyu/projects/pvrig_1m_old_cpu_remainder344295_quota_snapshot_v1_20260722}"
BX_SOURCE="${BX_SOURCE:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721/pvrig1m_old_cpu_remainder344295_v1/nbb2/results_11939813}"
POLL="${POLL:-20}"
SSH="/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe"

mkdir -p "$LOCAL/node1_receipts" "$LOCAL/bxcpu_purge_receipts" "$LOCAL/logs"
"$SSH" node1 "mkdir -p '$REMOTE/archives' '$REMOTE/receipts'"

for index in {0..7}; do
  node=$(printf 'node_%03d' "$index")
  archive="$LOCAL/archives/${node}_raw_snapshot.tar.gz"
  local_receipt="$LOCAL/archive_receipts/${node}.json"
  node1_receipt="$LOCAL/node1_receipts/${node}.json"
  purge_receipt="$LOCAL/bxcpu_purge_receipts/${node}.json"
  while [[ ! -s "$archive" || ! -s "$local_receipt" ]]; do sleep "$POLL"; done
  expected=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sha256"])' "$local_receipt")
  if [[ -s "$node1_receipt" ]] && grep -q "$expected" "$node1_receipt"; then continue; fi
  rsync -a --partial --append-verify -e "$SSH" "$archive" "node1:$REMOTE/archives/$(basename "$archive")"
  observed=$("$SSH" node1 "sha256sum '$REMOTE/archives/$(basename "$archive")'" | awk '{print $1}')
  [[ "$observed" == "$expected" ]]
  archive_pdb=$(tar -tzf "$archive" | awk '/\.pdb$/{n++} END{print n+0}')
  archive_manifests=$(tar -tzf "$archive" | awk '/manifest\.tsv\.partial$/{n++} END{print n+0}')
  remote_pdb=$(ssh -o BatchMode=yes -o ConnectTimeout=15 bxcpu "find '$BX_SOURCE/$node/raw' -type f -name '*.pdb' | wc -l")
  [[ "$archive_pdb" -eq "$remote_pdb" ]]
  [[ "$archive_manifests" -gt 0 ]]
  python3 - "$node1_receipt" "$node" "$expected" "$REMOTE/archives/$(basename "$archive")" <<'PY'
import json,sys,time
from pathlib import Path
p,node,digest,remote=Path(sys.argv[1]),sys.argv[2],sys.argv[3],sys.argv[4]
p.write_text(json.dumps({'status':'NODE1_HASH_VERIFIED','node':node,'sha256':digest,'remote':remote,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
  rsync -a -e "$SSH" "$node1_receipt" "node1:$REMOTE/receipts/${node}.json"
  if [[ ! -s "$purge_receipt" ]]; then
    if ssh -o BatchMode=yes -o ConnectTimeout=15 bxcpu "squeue -j 11939813 -h | grep -q ."; then
      echo "refusing purge while job 11939813 is active" >&2
      exit 1
    fi
    ssh -o BatchMode=yes -o ConnectTimeout=15 bxcpu \
      "python3 - '$BX_SOURCE' '$node' '$archive_pdb'" >"$purge_receipt" <<'PY'
import json,shutil,sys,time
from pathlib import Path
root=Path(sys.argv[1]).resolve(); node=sys.argv[2]; expected=int(sys.argv[3])
if not node.startswith('node_') or len(node)!=8: raise SystemExit('invalid node')
target=(root/node/'raw').resolve()
if target.parent != (root/node).resolve() or target.name!='raw': raise SystemExit('unsafe target')
observed=sum(1 for _ in target.rglob('*.pdb'))
if observed!=expected: raise SystemExit(f'pdb mismatch {observed}!={expected}')
shutil.rmtree(target)
print(json.dumps({'status':'BXCPU_NODE_RAW_PURGED_AFTER_LOCAL_AND_NODE1_HASH_VERIFICATION','node':node,'pdb_files':observed,'target':str(target),'created_epoch':time.time()},sort_keys=True))
PY
    rsync -a -e "$SSH" "$purge_receipt" "node1:$REMOTE/receipts/${node}_bxcpu_purge.json"
  fi
done

python3 - "$LOCAL" "$REMOTE" <<'PY'
import json,sys,time
from pathlib import Path
local,remote=Path(sys.argv[1]),sys.argv[2]
rows=[json.loads(p.read_text()) for p in sorted((local/'node1_receipts').glob('node_*.json'))]
if len(rows)!=8: raise SystemExit(f'expected 8 node1 receipts, found {len(rows)}')
purges=[json.loads(p.read_text()) for p in sorted((local/'bxcpu_purge_receipts').glob('node_*.json'))]
if len(purges)!=8: raise SystemExit(f'expected 8 purge receipts, found {len(purges)}')
(local/'NODE1_SNAPSHOT_COMPLETE.json').write_text(json.dumps({'status':'NODE1_8_NODE_SNAPSHOT_HASH_VERIFIED_AND_BXCPU_RAW_PURGED','remote':remote,'archives':rows,'purges':purges,'created_epoch':time.time(),'bxcpu_remote_delete_authorized':True},indent=2,sort_keys=True)+'\n')
PY
rsync -a -e "$SSH" "$LOCAL/NODE1_SNAPSHOT_COMPLETE.json" "node1:$REMOTE/NODE1_SNAPSHOT_COMPLETE.json"
