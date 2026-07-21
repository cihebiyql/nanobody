#!/usr/bin/env bash
set -euo pipefail

campaign_dir=$(realpath "${1:?usage: $0 LOCAL_CAMPAIGN_DIR}")
remote_root=/data1/qlyu/projects/pvrig_500k_rfantibody_pilot_v1_20260721
local_root="$campaign_dir/node1_rfantibody_mirror"
mkdir -p "$local_root" "$campaign_dir/status" "$campaign_dir/logs"

while true; do
  state=$(ssh.exe -o BatchMode=yes node1 "python3 - '$remote_root/status/controller.json'" <<'PY'
import json,sys
try:
    print(json.load(open(sys.argv[1])).get('state','UNKNOWN'))
except Exception:
    print('UNKNOWN')
PY
  )
  printf '%s\t%s\n' "$(date -Is)" "$state" >> "$campaign_dir/logs/node1_rfantibody_monitor.log"
  case "$state" in
    COMPLETE|FAILED)
      break
      ;;
  esac
  sleep 120
done

mkdir -p "$local_root/config" "$local_root/data" "$local_root/status" "$local_root/logs"
scp.exe -q node1:"$remote_root/status/controller.json" "$local_root/status/controller.json"
scp.exe -q node1:"$remote_root/config/generation_arms_primary.tsv" "$local_root/config/generation_arms_primary.tsv"
scp.exe -q node1:"$remote_root/config/generation_execution_policy.json" "$local_root/config/generation_execution_policy.json"

if [[ "$state" == COMPLETE ]]; then
  for name in candidates.tsv candidates.tsv.sha256 candidates.fasta candidates.fasta.sha256 \
    candidates_raw.tsv candidates_raw.tsv.sha256 backbone_groups.tsv backbone_groups.tsv.sha256 \
    generation_freeze_summary.json generation_freeze_summary.json.sha256; do
    scp.exe -q node1:"$remote_root/data/$name" "$local_root/data/$name"
  done
  (
    cd "$local_root/data"
    sha256sum -c candidates.tsv.sha256
    sha256sum -c candidates.fasta.sha256
    sha256sum -c candidates_raw.tsv.sha256
    sha256sum -c backbone_groups.tsv.sha256
    sha256sum -c generation_freeze_summary.json.sha256
  ) > "$local_root/status/checksums.log"
else
  scp.exe -q node1:"$remote_root/logs/controller.log" "$local_root/logs/controller.log" || true
fi

python - "$campaign_dir" "$local_root" "$state" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
campaign=Path(sys.argv[1]); local=Path(sys.argv[2]); state=sys.argv[3]
files=sorted(path for path in local.rglob('*') if path.is_file())
payload={
  'status':state,
  'remote_root':'/data1/qlyu/projects/pvrig_500k_rfantibody_pilot_v1_20260721',
  'local_mirror':str(local.relative_to(campaign)),
  'synced_at':datetime.now(timezone.utc).isoformat(),
  'files':{str(path.relative_to(local)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
}
(campaign/'status/NODE1_RFANTIBODY_TERMINAL.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
