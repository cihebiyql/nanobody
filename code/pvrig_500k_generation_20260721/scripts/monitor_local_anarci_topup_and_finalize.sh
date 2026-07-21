#!/usr/bin/env bash
set -euo pipefail

campaign_dir=$(realpath "${1:?usage: $0 CAMPAIGN_DIR}")
anarci_session=pvrig-500k-pilot-anarci-topup-20260721
while tmux has-session -t "$anarci_session" 2>/dev/null; do
  sleep 15
done

csv="$campaign_dir/qc/local_cpu_routes_supplemental_anarci_v1_H.csv"
if [[ ! -s "$csv" ]]; then
  python3 - "$campaign_dir" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
(root/'status/LOCAL_CPU_ANARCI_TERMINAL.json').write_text(json.dumps({
  'status':'FAILED',
  'reason':'supplemental ANARCI ended without H-chain CSV',
  'log':'logs/local_cpu_routes_supplemental_anarci_v1.log'
},indent=2,sort_keys=True)+'\n')
PY
  exit 1
fi

cd /mnt/d/work/抗体/code
exec python3 pvrig_500k_generation_20260721/scripts/finalize_local_anarci.py \
  --campaign-dir "$campaign_dir" \
  --supplemental-candidates "$campaign_dir/qc/local_cpu_routes_supplemental_pre_anarci.tsv" \
  --supplemental-anarci "$csv"
