#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/mnt/d/work/抗体/code}
WRAP=${WRAP:-$ROOT/pvrig_500k_generation_20260721/scripts/ssh_node1_windows_proxy.sh}
LOCAL_ROOT=${LOCAL_ROOT:-$ROOT/pvrig_500k_generation_20260721/run/pvrig_1m_gpu_generation_outputs_v1_20260722}
POLL_SECONDS=${POLL_SECONDS:-60}
CHAIN=/data1/qlyu/projects/pvrig_1m_gpu_double_prepare_v1_20260722/CHAIN_COMPLETE

declare -A REMOTE=(
  [rf75]=/data1/qlyu/projects/pvrig_500k_rfantibody75k_v1_20260721
  [mpnn75]=/data1/qlyu/projects/pvrig_500k_fixed_pose_mpnn75k_v2_20260721
  [rf150]=/data1/qlyu/projects/pvrig_1m_rfantibody150k_v1_20260722
  [mpnn150]=/data1/qlyu/projects/pvrig_1m_fixed_pose_mpnn150k_v1_20260722
)

mkdir -p "$LOCAL_ROOT/status"
exec >>"$LOCAL_ROOT/sync.log" 2>&1
echo "$(date -Is) Node1 GPU output watcher start"
while ! "$WRAP" node1 "test -s '$CHAIN'"; do
  printf '{"state":"WAITING_GPU_CHAIN","updated_at":"%s"}\n' "$(date -Is)" >"$LOCAL_ROOT/status/STATUS.json"
  sleep "$POLL_SECONDS"
done

for label in rf75 mpnn75 rf150 mpnn150; do
  remote=${REMOTE[$label]}
  target="$LOCAL_ROOT/$label"
  mkdir -p "$target"
  "$WRAP" node1 "test -d '$remote/data' && test -s '$remote/status/controller.json'"
  rsync -a --partial --append-verify -e "$WRAP" \
    "node1:$remote/data/" "$target/data/"
  rsync -a --partial --append-verify -e "$WRAP" \
    "node1:$remote/status/controller.json" "$target/controller.json"
  if "$WRAP" node1 "test -s '$remote/PREPARED.json'"; then
    rsync -a --partial --append-verify -e "$WRAP" \
      "node1:$remote/PREPARED.json" "$target/PREPARED.json"
  fi
done

python3 - "$LOCAL_ROOT" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
root=Path(sys.argv[1]); lines=[]; states={}
for label in ('rf75','mpnn75','rf150','mpnn150'):
 payload=json.loads((root/label/'controller.json').read_text())
 states[label]=payload.get('state','UNKNOWN')
for path in sorted(p for p in root.rglob('*') if p.is_file() and p.name not in {'SHA256SUMS','SYNC_COMPLETE.json','sync.log','STATUS.json'}):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''):h.update(block)
 lines.append(f'{h.hexdigest()}  ./{path.relative_to(root).as_posix()}')
(root/'SHA256SUMS').write_text('\n'.join(lines)+'\n')
(root/'SYNC_COMPLETE.json').write_text(json.dumps({'status':'COMPLETE','controller_states':states,'created_epoch':time.time(),'claim_boundary':'generated sequences; not binding, affinity, docking, or blocking evidence'},indent=2,sort_keys=True)+'\n')
PY
printf '{"state":"COMPLETE","updated_at":"%s"}\n' "$(date -Is)" >"$LOCAL_ROOT/status/STATUS.json"
echo "$(date -Is) Node1 GPU output sync complete"
