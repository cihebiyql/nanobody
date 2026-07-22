#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${ROOT:-/mnt/d/work/抗体/code}
BASE="$ROOT/pvrig_500k_generation_20260721"
SYNC="$BASE/run/pvrig_1m_gpu_generation_outputs_v1_20260722"
OUT="$BASE/run/pvrig_1m_gpu_raw_normalized_v1_20260722"
POLL_SECONDS=${POLL_SECONDS:-60}
mkdir -p "$OUT/status"
exec 9>"$OUT/status/normalize.lock"; flock -n 9 || exit 75
while [[ ! -s "$SYNC/SYNC_COMPLETE.json" ]]; do
 printf '{"state":"WAITING_NODE1_GPU_SYNC","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
 sleep "$POLL_SECONDS"
done
printf '{"state":"NORMALIZING","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
python3 "$BASE/scripts/normalize_1m_gpu_raw_pool.py" \
 --cpu "$BASE/run/pvrig_500k_cpu_control_combined394k_v1_20260721/combined_exact_unique_fast_qc_pass.tsv.gz" \
 --cpu "$BASE/run/pvrig_1m_cpu_topup305705_v1_20260722_frozen/route_quota_exact_unique.tsv.gz" \
 --rf-raw "$SYNC/rf150/data/candidates_raw.tsv" \
 --mpnn-pool "$SYNC/mpnn150/data/fixed_pose_candidates_exact_unique_fastqc_pass.tsv.gz" \
 --positive-cdr "$BASE/run/pvrig_1m_cpu_topup430k_v1_20260722_package/inputs/known_positive_CDR_table.csv" \
 --positive-fasta "$BASE/run/pvrig_1m_cpu_topup430k_v1_20260722_package/inputs/known_positive_antibodies.fasta" \
 --output-dir "$OUT" >"$OUT/normalize.stdout.log" 2>"$OUT/normalize.stderr.log"
python3 - "$OUT/NORMALIZE_RECEIPT.json" "$OUT/status/STATUS.json" <<'PY'
import json,sys,time
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text())
Path(sys.argv[2]).write_text(json.dumps({'state':r['status'],'route_fast_qc_pass':r['route_fast_qc_pass'],'updated_epoch':time.time()},indent=2,sort_keys=True)+'\n')
if r['status']!='READY_FOR_ANARCI': raise SystemExit(4)
PY
date -Is >"$OUT/status/NORMALIZE_COMPLETE"
