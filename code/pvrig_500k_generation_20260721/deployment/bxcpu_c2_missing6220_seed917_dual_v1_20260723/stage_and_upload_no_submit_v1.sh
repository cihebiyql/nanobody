#!/usr/bin/env bash
set -euo pipefail

# This script only seals and uploads immutable inputs.  It never invokes the
# scheduler submission command; preflight and submit remain separate steps.
DEPLOY=$(cd "$(dirname "$0")" && pwd)
PROJECT=pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723
NODE1_ROOT=${PVRIG_C2_NODE1_ROOT:-/data1/qlyu/projects/pvrig_top7500_c2_gap_recovery_v1_20260723}
NODE1_HANDOFF=${PVRIG_C2_NODE1_HANDOFF:-$NODE1_ROOT/c2_only_missing6220_seed917_dual_handoff_v1}
NODE1_DEPLOY=${PVRIG_C2_NODE1_DEPLOY:-$NODE1_ROOT/$PROJECT}
NODE1_CODE=${PVRIG_C2_NODE1_DEPLOY_CODE:-$NODE1_ROOT/bxcpu_deployment_code_v1}
NODE1_ZSTD=${PVRIG_C2_NODE1_ZSTD:-$NODE1_ROOT/tools/zstd}
LOCAL_RUNTIME=${PVRIG_C2_LOCAL_STAGE_RUNTIME:-/mnt/d/work/抗体/node1/pvrig_c2_missing6220_bxcpu_stage_v1_20260723}
REMOTE_CODE_REL=.local/share/bxcpu_c2_missing6220_seed917_dual_v1_20260723
LOCAL_ZSTD=${PVRIG_C2_LOCAL_ZSTD_BXCPU:-/mnt/d/work/抗体/data/experiments/phase2_5080_v1/prepared/pvrig_top7500_c2_gap_recovery_v1_20260723/inputs/zstd_bxcpu}
LOCAL_ZSTD_SHA=08a60ba61031bb1f38070099e77df196b24293de7a2c6517e5f29b183b2299ef
NODE1_SSH=${PVRIG_C2_NODE1_SSH:-/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe}
BXCPU_SSH=${PVRIG_C2_BXCPU_SSH:-ssh}

mkdir -p "$LOCAL_RUNTIME"
[[ ! -e "$DEPLOY/INDEPENDENT_LAUNCH_APPROVAL.json" ]] || {
  echo source_package_must_not_contain_launch_approval >&2; exit 67;
}
[[ -f "$LOCAL_ZSTD" && ! -L "$LOCAL_ZSTD" ]] || { echo missing_local_bxcpu_zstd >&2; exit 65; }
[[ $(sha256sum "$LOCAL_ZSTD" | awk '{print $1}') == "$LOCAL_ZSTD_SHA" ]] || {
  echo local_bxcpu_zstd_hash_mismatch >&2; exit 65;
}

# Upload only the two deterministic Node1 sealing modules.
"$NODE1_SSH" node1 "mkdir -p '$NODE1_CODE'"
for file in deployment_contract_v1.py prepare_node1_bundle_v1.py; do
  "$NODE1_SSH" node1 "cat > '$NODE1_CODE/$file.tmp' && mv '$NODE1_CODE/$file.tmp' '$NODE1_CODE/$file'" < "$DEPLOY/$file"
done

created_at=$(date -u +%FT%TZ)
"$NODE1_SSH" node1 "set -euo pipefail
  test -f '$NODE1_HANDOFF/HANDOFF_RECEIPT.json'
  test -f '$NODE1_HANDOFF/SHA256SUMS'
  test -x '$NODE1_ZSTD'
  if test -e '$NODE1_DEPLOY'; then
    python3 - '$NODE1_DEPLOY/DEPLOYMENT_BUNDLE_RECEIPT.json' <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['status']=='SEALED_FOR_BXCPU_UPLOAD_NOT_SUBMITTED'
assert d['project']=='pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723'
assert d['candidates']==6220 and d['jobs']==12440 and d['shard_sizes']==[1555]*8
assert d['docking_started'] is False and d['overlap1280_reuse_authorized'] is False
PY
  else
    cd '$NODE1_CODE'
    python3 prepare_node1_bundle_v1.py --handoff-root '$NODE1_HANDOFF' \
      --output-root '$NODE1_DEPLOY' --created-at '$created_at'
  fi
  cd '$NODE1_DEPLOY'
  sha256sum -c DEPLOYMENT_SHA256SUMS >/dev/null
"

# Download the small authoritative inputs first.
"$NODE1_SSH" node1 "cat '$NODE1_DEPLOY/DEPLOYMENT_BUNDLE_RECEIPT.json'" > "$LOCAL_RUNTIME/DEPLOYMENT_BUNDLE_RECEIPT.json.tmp"
mv "$LOCAL_RUNTIME/DEPLOYMENT_BUNDLE_RECEIPT.json.tmp" "$LOCAL_RUNTIME/DEPLOYMENT_BUNDLE_RECEIPT.json"
"$NODE1_SSH" node1 "cat '$NODE1_DEPLOY/manifests/docking_jobs.tsv'" > "$LOCAL_RUNTIME/$PROJECT.manifest.tsv.tmp"
mv "$LOCAL_RUNTIME/$PROJECT.manifest.tsv.tmp" "$LOCAL_RUNTIME/$PROJECT.manifest.tsv"

# Stream a fresh deterministic content bundle. Archive metadata is sealed by
# its final byte hash; no previous old-panel archive is accepted.
"$NODE1_SSH" node1 "set -euo pipefail; cd '$(dirname "$NODE1_DEPLOY")'; tar -cf - '$PROJECT' | '$NODE1_ZSTD' -T0 -3 -c" \
  > "$LOCAL_RUNTIME/$PROJECT.tar.zst.tmp"
mv "$LOCAL_RUNTIME/$PROJECT.tar.zst.tmp" "$LOCAL_RUNTIME/$PROJECT.tar.zst"

python3 "$DEPLOY/write_frozen_input_anchors_v1.py" \
  --archive "$LOCAL_RUNTIME/$PROJECT.tar.zst" \
  --manifest "$LOCAL_RUNTIME/$PROJECT.manifest.tsv" \
  --bundle-receipt "$LOCAL_RUNTIME/DEPLOYMENT_BUNDLE_RECEIPT.json" \
  --output "$LOCAL_RUNTIME/FROZEN_INPUT_ANCHORS.json" \
  --created-at "$created_at" > "$LOCAL_RUNTIME/FROZEN_INPUT_ANCHORS.stdout.json"

# Upload archive, manifest and deployment code. No launch command is called.
rsync -a --partial --timeout=1800 -e "$BXCPU_SSH" \
  "$LOCAL_RUNTIME/$PROJECT.tar.zst" "bxcpu:$PROJECT.tar.zst"
rsync -a --partial --timeout=600 -e "$BXCPU_SSH" \
  "$LOCAL_RUNTIME/$PROJECT.manifest.tsv" "bxcpu:$PROJECT.manifest.tsv"
tar -C "$DEPLOY" -cf - . | "$BXCPU_SSH" bxcpu "set -euo pipefail; mkdir -p '$REMOTE_CODE_REL'; test ! -e '$REMOTE_CODE_REL/INDEPENDENT_LAUNCH_APPROVAL.json'; tar -xf - -C '$REMOTE_CODE_REL'"
rsync -a -e "$BXCPU_SSH" "$LOCAL_ZSTD" "bxcpu:$REMOTE_CODE_REL/zstd_bxcpu"
rsync -a -e "$BXCPU_SSH" "$LOCAL_RUNTIME/FROZEN_INPUT_ANCHORS.json" \
  "bxcpu:$REMOTE_CODE_REL/FROZEN_INPUT_ANCHORS.json"

"$BXCPU_SSH" bxcpu "set -euo pipefail
  chmod 750 '$REMOTE_CODE_REL/zstd_bxcpu'
  test \"\$(sha256sum '$REMOTE_CODE_REL/zstd_bxcpu' | cut -d' ' -f1)\" = '$LOCAL_ZSTD_SHA'
  python3 - '$REMOTE_CODE_REL/FROZEN_INPUT_ANCHORS.json' \"\$HOME/$PROJECT.tar.zst\" \"\$HOME/$PROJECT.manifest.tsv\" <<'PY'
import hashlib,json,pathlib,sys
d=json.load(open(sys.argv[1])); archive=pathlib.Path(sys.argv[2]); manifest=pathlib.Path(sys.argv[3])
def h(p):
 x=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): x.update(b)
 return x.hexdigest()
assert d['status']=='SEALED_NODE1_HANDOFF_PASS_READY_FOR_BXCPU_PREFLIGHT'
assert d['project']=='pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723'
assert d['required_candidates']==6220 and d['required_jobs']==12440
assert h(archive)==d['archive_sha256'] and archive.stat().st_size==d['archive_bytes']
assert h(manifest)==d['job_manifest_sha256']
assert d['docking_started'] is False and d['overlap1280_reuse_authorized'] is False
PY
"

python3 - "$LOCAL_RUNTIME/STAGING_UPLOAD_RECEIPT.json" "$LOCAL_RUNTIME/FROZEN_INPUT_ANCHORS.json" <<'PY'
import datetime,hashlib,json,pathlib,sys
out=pathlib.Path(sys.argv[1]); anchor=pathlib.Path(sys.argv[2]); d=json.load(anchor.open())
payload={
 "schema_version":"pvrig.c2_missing6220.bxcpu_staging_upload.v1",
 "status":"UPLOADED_HASH_VERIFIED_NOT_SUBMITTED",
 "created_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "frozen_input_anchors_sha256":hashlib.sha256(anchor.read_bytes()).hexdigest(),
 "archive_sha256":d["archive_sha256"],"job_manifest_sha256":d["job_manifest_sha256"],
 "docking_started":False,"overlap1280_reuse_authorized":False,
 "claim_boundary":"Immutable input upload only; no scheduler job was submitted."
}
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
print(json.dumps(payload,sort_keys=True))
PY
