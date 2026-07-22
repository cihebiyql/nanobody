#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}"
OUT="${OUT:-$BASE/run/pvrig_1m_old_cpu_remainder344295_quota_pause_v1_20260722}"
REMOTE_ROOT="${REMOTE_ROOT:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721/pvrig1m_old_cpu_remainder344295_v1/nbb2/results_11939813}"
PARALLEL="${PARALLEL:-2}"

mkdir -p "$OUT/archives" "$OUT/archive_receipts" "$OUT/logs"

preserve_node() {
  local node="$1"
  local archive="$OUT/archives/${node}_raw_snapshot.tar.gz"
  local partial="${archive}.partial"
  local receipt="$OUT/archive_receipts/${node}.json"
  if [[ -s "$archive" && -s "$receipt" ]]; then
    gzip -t "$archive"
    return 0
  fi
  rm -f "$partial"
  ssh -o BatchMode=yes -o ConnectTimeout=15 bxcpu \
    "tar -C '$REMOTE_ROOT' -cf - '$node/raw'" \
    | gzip -1 >"$partial"
  gzip -t "$partial"
  mv -f "$partial" "$archive"
  python3 - "$archive" "$receipt" "$node" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
archive,receipt,node=map(Path,sys.argv[1:])
h=hashlib.sha256()
with archive.open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
payload={
    'status':'LOCAL_ARCHIVE_VERIFIED',
    'node':node.name,
    'archive':str(archive.resolve()),
    'bytes':archive.stat().st_size,
    'sha256':h.hexdigest(),
    'created_epoch':time.time(),
    'source_semantics':'read-only snapshot after bxcpu quota pause; includes successful PDBs and partial manifests',
}
receipt.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
}
export -f preserve_node
export BASE OUT REMOTE_ROOT
printf 'node_%03d\n' {0..7} | xargs -n1 -P "$PARALLEL" bash -c 'preserve_node "$0"' 

python3 - "$OUT" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
out=Path(sys.argv[1]); receipts=[]
for p in sorted((out/'archive_receipts').glob('node_*.json')):
    receipts.append(json.loads(p.read_text()))
if len(receipts)!=8: raise SystemExit(f'expected 8 receipts, found {len(receipts)}')
payload={
    'status':'LOCAL_8_NODE_SNAPSHOT_COMPLETE',
    'archives':receipts,
    'total_bytes':sum(x['bytes'] for x in receipts),
    'created_epoch':time.time(),
    'remote_delete_authorized':False,
}
(out/'LOCAL_SNAPSHOT_COMPLETE.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
