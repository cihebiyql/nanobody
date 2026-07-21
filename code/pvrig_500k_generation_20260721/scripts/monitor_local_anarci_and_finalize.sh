#!/usr/bin/env bash
set -euo pipefail

campaign_dir=$(realpath "${1:?usage: $0 CAMPAIGN_DIR}")
anarci_session=pvrig-500k-pilot-anarci-20260721
while tmux has-session -t "$anarci_session" 2>/dev/null; do
  sleep 30
done

if [[ ! -s "$campaign_dir/qc/local_cpu_routes_anarci_v1_H.csv" ]]; then
  python - "$campaign_dir" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
(root/'status/LOCAL_CPU_ANARCI_TERMINAL.json').write_text(json.dumps({
  'status':'FAILED',
  'reason':'ANARCI process ended without H-chain CSV',
  'log':'logs/local_cpu_routes_anarci_v1.log'
},indent=2,sort_keys=True)+'\n')
PY
  exit 1
fi

cd /mnt/d/work/抗体/code
exec python pvrig_500k_generation_20260721/scripts/finalize_local_anarci.py \
  --campaign-dir "$campaign_dir"
