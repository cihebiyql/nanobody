#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/mnt/d/work/抗体/code}
WRAP=${WRAP:-$ROOT/pvrig_500k_generation_20260721/scripts/ssh_node1_windows_proxy.sh}
REMOTE_CAMPAIGN=${REMOTE_CAMPAIGN:-\$HOME/pvrig_bxcpu_model_runtime_v1_20260721/pvrig1m_cpu_topup305705_v1/nbb2}
LOCAL_ROOT=${LOCAL_ROOT:-$ROOT/pvrig_500k_generation_20260721/run/pvrig_1m_cpu_topup305705_nbb2_tnp_v1_20260722}
# Durable NBB2 archives are intentionally stored on Node1's large /data
# filesystem.  /data1 is reserved for active RFantibody/ProteinMPNN GPU work.
NODE1_ROOT=${NODE1_ROOT:-/data/qlyu/projects/pvrig_1m_cpu_topup305705_nbb2_tnp_v1_20260722}
POLL_SECONDS=${POLL_SECONDS:-60}
PURGE_LOCAL_ARCHIVE_AFTER_NODE1_ACK=${PURGE_LOCAL_ARCHIVE_AFTER_NODE1_ACK:-1}
PURGE_REMOTE_AFTER_NODE1_ACK=${PURGE_REMOTE_AFTER_NODE1_ACK:-1}
REMOTE_PURGE_TOOL=${REMOTE_PURGE_TOOL:-}
REMOTE_PYTHON=${REMOTE_PYTHON:-}

mkdir -p "$LOCAL_ROOT/archives" "$LOCAL_ROOT/state" "$LOCAL_ROOT/aggregate"
exec >>"$LOCAL_ROOT/sync.log" 2>&1
echo "$(date -Is) sync watcher start"

case "$REMOTE_CAMPAIGN" in
  '$HOME/'*)
    remote_home=$(ssh bxcpu 'printf %s "$HOME"')
    REMOTE_CAMPAIGN="$remote_home/${REMOTE_CAMPAIGN#\$HOME/}"
    ;;
esac
if [[ -z "$REMOTE_PURGE_TOOL" ]]; then
  REMOTE_PURGE_TOOL="$(dirname "$(dirname "$REMOTE_CAMPAIGN")")/scripts/purge_bxcpu_nbb2_after_durable_sync.py"
fi
if [[ -z "$REMOTE_PYTHON" ]]; then
  REMOTE_PYTHON="$(dirname "$(dirname "$REMOTE_CAMPAIGN")")/env/bin/python"
fi

while true; do
  job_ids=$(ssh bxcpu "cat '$REMOTE_CAMPAIGN/status/JOB_IDS' 2>/dev/null" || true)
  nbb_job=$(sed -n 's/^NBB2=//p' <<<"$job_ids" | tail -1)
  [[ -n "$nbb_job" ]] && break
  sleep "$POLL_SECONDS"
done
printf '%s\n' "$nbb_job" >"$LOCAL_ROOT/NBB2_JOB_ID"
remote_archives="$REMOTE_CAMPAIGN/archives_${nbb_job}"

for node in $(seq 0 7); do
  id=$(printf '%03d' "$node")
  while [[ ! -s "$LOCAL_ROOT/state/node_${id}.LOCAL_ACK" ]]; do
    if ssh bxcpu "test -s '$remote_archives/node_${id}.READY.json'"; then
      rsync -a --partial --append-verify \
        "bxcpu:$remote_archives/node_${id}.READY.json" \
        "bxcpu:$remote_archives/node_${id}.sha256" \
        "bxcpu:$remote_archives/node_${id}.tar.gz" \
        "$LOCAL_ROOT/archives/"
      (cd "$LOCAL_ROOT/archives" && sha256sum -c "node_${id}.sha256")
      date -Is >"$LOCAL_ROOT/state/node_${id}.LOCAL_ACK"
    else
      sleep "$POLL_SECONDS"
    fi
  done

  if [[ ! -s "$LOCAL_ROOT/state/node_${id}.NODE1_ACK" ]]; then
    "$WRAP" node1 "mkdir -p '$NODE1_ROOT/archives'"
    rsync -a --partial --append-verify -e "$WRAP" \
      "$LOCAL_ROOT/archives/node_${id}.READY.json" \
      "$LOCAL_ROOT/archives/node_${id}.sha256" \
      "$LOCAL_ROOT/archives/node_${id}.tar.gz" \
      "node1:$NODE1_ROOT/archives/"
    "$WRAP" node1 "cd '$NODE1_ROOT/archives' && sha256sum -c 'node_${id}.sha256'"
    date -Is >"$LOCAL_ROOT/state/node_${id}.NODE1_ACK"
  fi

  # The local workstation is a transfer hop, not the durable raw-archive store.
  # Remove the large tarball only after Node1 has independently verified it;
  # retain READY/checksum files plus an auditable purge receipt locally.
  if [[ "$PURGE_LOCAL_ARCHIVE_AFTER_NODE1_ACK" == 1 \
        && -s "$LOCAL_ROOT/state/node_${id}.NODE1_ACK" \
        && -f "$LOCAL_ROOT/archives/node_${id}.tar.gz" ]]; then
    archive_sha=$(awk 'NR==1 {print $1}' "$LOCAL_ROOT/archives/node_${id}.sha256")
    archive_bytes=$(stat -c '%s' "$LOCAL_ROOT/archives/node_${id}.tar.gz")
    python3 - "$LOCAL_ROOT/state/node_${id}.LOCAL_ARCHIVE_PURGED.json" \
      "$id" "$archive_sha" "$archive_bytes" "$NODE1_ROOT/archives/node_${id}.tar.gz" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

out, node, digest, size, durable_path = sys.argv[1:]
Path(out).write_text(json.dumps({
    "status": "PURGED_AFTER_NODE1_SHA256_ACK",
    "node": node,
    "archive_sha256": digest,
    "archive_bytes": int(size),
    "durable_node1_path": durable_path,
    "created_at": datetime.now(timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + "\n")
PY
    rm -f "$LOCAL_ROOT/archives/node_${id}.tar.gz"
  fi
done

# Revalidate the complete durable archive set as a unit.  This makes a stale
# local NODE1_ACK insufficient on its own and proves that every purged local
# tarball is still present and hash-correct on Node1.
for node in $(seq 0 7); do
  id=$(printf '%03d' "$node")
  "$WRAP" node1 "cd '$NODE1_ROOT/archives' && sha256sum -c 'node_${id}.sha256'"
done
date -Is >"$LOCAL_ROOT/NODE1_ARCHIVES_REVERIFIED"
date -Is >"$LOCAL_ROOT/ARCHIVES_TRANSFER_COMPLETE"

while ! ssh bxcpu "test -s '$REMOTE_CAMPAIGN/status/CHAIN_COMPLETE'"; do sleep "$POLL_SECONDS"; done
job_ids=$(ssh bxcpu "cat '$REMOTE_CAMPAIGN/status/JOB_IDS'")
tnp_job=$(sed -n 's/^TNP=//p' <<<"$job_ids" | tail -1)
printf '%s\n' "$tnp_job" >"$LOCAL_ROOT/TNP_JOB_ID"

rsync -a --partial --append-verify \
  "bxcpu:$REMOTE_CAMPAIGN/aggregated_${nbb_job}/" "$LOCAL_ROOT/aggregate/nbb2/"
rsync -a --partial --append-verify \
  "bxcpu:$REMOTE_CAMPAIGN/tnp_aggregated_${tnp_job}/" "$LOCAL_ROOT/aggregate/tnp/"
rsync -a --partial --append-verify \
  "bxcpu:$REMOTE_CAMPAIGN/status/" "$LOCAL_ROOT/status/"

python3 - "$LOCAL_ROOT" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); lines=[]
for path in sorted(p for p in root.rglob('*') if p.is_file() and p.name not in {'SHA256SUMS','SYNC_COMPLETE.json','sync.log'}):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 lines.append(f'{h.hexdigest()}  ./{path.relative_to(root).as_posix()}')
(root/'SHA256SUMS').write_text('\n'.join(lines)+'\n')
(root/'SYNC_COMPLETE.json').write_text(json.dumps({'status':'COMPLETE','technical_na_is_not_negative':True},indent=2)+'\n')
PY

"$WRAP" node1 "mkdir -p '$NODE1_ROOT'"
rsync -a --partial --append-verify --exclude sync.log -e "$WRAP" "$LOCAL_ROOT/" "node1:$NODE1_ROOT/"
"$WRAP" node1 "cd '$NODE1_ROOT' && sha256sum -c SHA256SUMS"
date -Is >"$LOCAL_ROOT/NODE1_SYNC_COMPLETE"

# bxcpu is a compute staging area, not the durable archive store.  Once the
# complete archive set and aggregates have independently passed Node1 SHA256
# verification, remove only the redundant bxcpu raw/archive directories.  The
# purge receipt retains every archive digest and makes this operation auditable
# and idempotent.  Inputs, aggregates, status, and the Node1 archives remain.
if [[ "$PURGE_REMOTE_AFTER_NODE1_ACK" == 1 ]]; then
  durable_ack_remote="$REMOTE_CAMPAIGN/status/NODE1_DURABLE_ACK.json"
  durable_ack_local="$LOCAL_ROOT/state/NODE1_DURABLE_ACK.json"
  remote_receipt="$REMOTE_CAMPAIGN/status/REMOTE_PURGE_RECEIPT.json"
  if ssh bxcpu "test -s '$remote_receipt'"; then
    rsync -a --partial --append-verify "bxcpu:$remote_receipt" "$LOCAL_ROOT/status/"
    python3 - "$LOCAL_ROOT/status/REMOTE_PURGE_RECEIPT.json" "$REMOTE_CAMPAIGN" \
      "$NODE1_ROOT" "$nbb_job" "$tnp_job" 8 <<'PY'
import json,sys
from pathlib import Path
receipt,campaign,node1_root,nbb2_job,tnp_job,shards=sys.argv[1:]
x=json.load(open(receipt)); expected={
 'status':'PURGED_AFTER_DURABLE_NODE1_ACK','campaign':str(Path(campaign).resolve()),
 'durable_node1_root':node1_root,'nbb2_job_id':nbb2_job,'tnp_job_id':tnp_job,
 'expected_shards':int(shards),
}
bad={k:(v,x.get(k)) for k,v in expected.items() if x.get(k)!=v}
if bad: raise SystemExit(f'existing remote purge receipt mismatch: {bad}')
PY
  else
    revalidation_sha=$(sha256sum "$LOCAL_ROOT/NODE1_ARCHIVES_REVERIFIED" | awk '{print $1}')
    node1_manifest_sha=$(sha256sum "$LOCAL_ROOT/SHA256SUMS" | awk '{print $1}')
    python3 - "$durable_ack_local" "$REMOTE_CAMPAIGN" "$NODE1_ROOT" "$nbb_job" "$tnp_job" \
      8 "$node1_manifest_sha" "$revalidation_sha" <<'PY'
import json,sys,time
from datetime import datetime,timezone
from pathlib import Path
out,campaign,node1_root,nbb2_job,tnp_job,shards,manifest_sha,revalidation_sha=sys.argv[1:]
Path(out).write_text(json.dumps({
    'status':'DURABLE_NODE1_REVALIDATED',
    'campaign':str(Path(campaign).resolve()),
    'durable_node1_root':node1_root,
    'nbb2_job_id':nbb2_job,
    'tnp_job_id':tnp_job,
    'expected_shards':int(shards),
    'node1_manifest_sha256':manifest_sha,
    'revalidation_marker_sha256':revalidation_sha,
    'created_at':datetime.now(timezone.utc).isoformat(),
    'created_at_epoch':time.time(),
},indent=2,sort_keys=True)+'\n')
PY
    rsync -a --partial --append-verify "$durable_ack_local" "bxcpu:$durable_ack_remote"
    ssh bxcpu "'$REMOTE_PYTHON' '$REMOTE_PURGE_TOOL' \
      --campaign '$REMOTE_CAMPAIGN' \
      --nbb2-job-id '$nbb_job' \
      --tnp-job-id '$tnp_job' \
      --expected-shards 8 \
      --durable-node1-root '$NODE1_ROOT' \
      --durable-ack '$durable_ack_remote' \
      --node1-manifest-sha256 '$node1_manifest_sha' \
      --revalidation-marker-sha256 '$revalidation_sha'"
    rsync -a --partial --append-verify "bxcpu:$remote_receipt" "$LOCAL_ROOT/status/"
  fi
  receipt_rel=./status/REMOTE_PURGE_RECEIPT.json
  receipt_sha=$(sha256sum "$LOCAL_ROOT/status/REMOTE_PURGE_RECEIPT.json" | awk '{print $1}')
  grep -vF "  $receipt_rel" "$LOCAL_ROOT/SHA256SUMS" >"$LOCAL_ROOT/SHA256SUMS.partial"
  printf '%s  %s\n' "$receipt_sha" "$receipt_rel" >>"$LOCAL_ROOT/SHA256SUMS.partial"
  mv "$LOCAL_ROOT/SHA256SUMS.partial" "$LOCAL_ROOT/SHA256SUMS"
  rsync -a --partial --append-verify -e "$WRAP" \
    "$LOCAL_ROOT/status/REMOTE_PURGE_RECEIPT.json" \
    "node1:$NODE1_ROOT/status/"
  rsync -a --partial --append-verify -e "$WRAP" \
    "$LOCAL_ROOT/SHA256SUMS" \
    "node1:$NODE1_ROOT/"
  "$WRAP" node1 "cd '$NODE1_ROOT' && sha256sum -c SHA256SUMS"
  date -Is >"$LOCAL_ROOT/REMOTE_PURGE_COMPLETE"
fi
echo "$(date -Is) sync watcher complete"
