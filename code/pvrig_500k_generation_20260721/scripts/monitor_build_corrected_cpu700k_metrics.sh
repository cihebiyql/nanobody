#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/mnt/d/work/抗体/code}
BASE="$ROOT/pvrig_500k_generation_20260721"
CORRECTED="$BASE/run/pvrig_1m_cpu700k_corrected_v1_20260722"
REPLACEMENT_POINTER="$CORRECTED/REPLACEMENT_CAMPAIGN.json"
PRE50="$BASE/run/pvrig_prestructure50k_tnp_bxcpu_v1_20260722"
TOP="$BASE/run/pvrig_1m_cpu_topup305705_nbb2_tnp_v1_20260722"
OLD="$BASE/run/pvrig_1m_old_cpu_remainder344295_nbb2_tnp_v1_20260722"
OUT="$BASE/run/pvrig_1m_cpu700k_corrected_metrics_v1_20260722"
POLL_SECONDS=${POLL_SECONDS:-60}
mkdir -p "$OUT/status"
exec 9>"$OUT/status/build.lock"
flock -n 9 || exit 75

while [[ ! -s "$REPLACEMENT_POINTER" ]]; do
  printf '{"state":"WAITING_REPLACEMENT_BINDING","updated_at":"%s"}\n' \
    "$(date -Is)" >"$OUT/status/STATUS.json"
  sleep "$POLL_SECONDS"
done
mapfile -t replacement_binding < <(python3 - "$REPLACEMENT_POINTER" "$BASE/run" <<'PY'
import json,sys
from pathlib import Path
pointer=Path(sys.argv[1]); run_root=Path(sys.argv[2]).resolve(); x=json.loads(pointer.read_text())
required={'status','local_root','node1_root','remote_campaign','records','selection_sha256'}
if required-set(x): raise SystemExit(f'replacement pointer missing fields: {sorted(required-set(x))}')
if x['status']!='BOUND' or int(x['records'])<3031 or len(x['selection_sha256'])!=64:
 raise SystemExit(f'invalid replacement pointer: {x}')
tag=f"{int(x['records'])}_{x['selection_sha256'][:16]}"
expected=(run_root/f'pvrig_1m_cpu700k_replacement_{tag}_nbb2_tnp_v1_20260722').resolve()
observed=Path(x['local_root']).resolve()
if observed!=expected: raise SystemExit(f'replacement local root mismatch observed={observed} expected={expected}')
binding=observed/'CAMPAIGN_BINDING.json'
if not binding.is_file() or json.loads(binding.read_text())!=x:
 raise SystemExit('replacement local binding is absent or differs from pointer')
print(observed); print(int(x['records'])); print(x['selection_sha256'])
PY
)
REPLACEMENT=${replacement_binding[0]}
REPLACEMENT_RECORDS=${replacement_binding[1]}
REPLACEMENT_SELECTION_SHA=${replacement_binding[2]}

required=(
  "$CORRECTED/READY.json"
  "$CORRECTED/replacement_selected3031_prefilter.tsv.gz"
  "$PRE50/recovery/prestructure50000_nbb2_final_manifest.tsv.gz"
  "$PRE50/tnp_aggregate/tnp_prestructure50000.tsv.gz"
  "$TOP/aggregate/nbb2/nbb2_manifest.tsv.gz"
  "$TOP/aggregate/tnp/tnp_all.tsv.gz"
  "$OLD/aggregate/nbb2/nbb2_manifest.tsv.gz"
  "$OLD/aggregate/tnp/tnp_all.tsv.gz"
  "$REPLACEMENT/SYNC_COMPLETE.json"
  "$REPLACEMENT/aggregate/nbb2/COMPLETE.json"
  "$REPLACEMENT/aggregate/nbb2/nbb2_manifest.tsv.gz"
  "$REPLACEMENT/aggregate/tnp/READY.json"
  "$REPLACEMENT/aggregate/tnp/tnp_all.tsv.gz"
)
while true; do
  missing=0
  for path in "${required[@]}"; do [[ -s "$path" ]] || missing=$((missing + 1)); done
  printf '{"state":"WAITING_INPUTS","missing":%s,"updated_at":"%s"}\n' \
    "$missing" "$(date -Is)" >"$OUT/status/STATUS.json"
  [[ "$missing" -eq 0 ]] && break
  sleep "$POLL_SECONDS"
done

python3 - "$CORRECTED/READY.json" "$REPLACEMENT_RECORDS" "$REPLACEMENT_SELECTION_SHA" \
  "$CORRECTED/replacement_selected3031_prefilter.tsv.gz" <<'PY'
import hashlib,json,sys
from pathlib import Path
ready_path,records,digest,selection=sys.argv[1:]; ready=json.load(open(ready_path)); records=int(records)
if ready.get('status')!='READY_FOR_REPLACEMENT_NBB2_TNP' or int(ready.get('replacement_records',-1))!=records:
 raise SystemExit(f'corrected replacement receipt mismatch: {ready}')
h=hashlib.sha256()
with Path(selection).open('rb') as f:
 for block in iter(lambda:f.read(8<<20),b''): h.update(block)
if h.hexdigest()!=digest: raise SystemExit('replacement selection hash differs from campaign binding')
PY
python3 - "$REPLACEMENT/aggregate/nbb2/COMPLETE.json" \
  "$REPLACEMENT/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  "$REPLACEMENT/aggregate/tnp/READY.json" "$REPLACEMENT/aggregate/tnp/tnp_all.tsv.gz" \
  "$REPLACEMENT_RECORDS" <<'PY'
import hashlib,json,sys
from pathlib import Path
nbb_ready,nbb_file,tnp_ready,tnp_file,expected=sys.argv[1:]; expected=int(expected)
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 return h.hexdigest()
nbb=json.load(open(nbb_ready)); tnp=json.load(open(tnp_ready))
if nbb.get('status')!='PASS' or int(nbb.get('records',-1))!=expected or nbb.get('status_counts')!={'SUCCESS':expected}:
 raise SystemExit(f'replacement NBB2 is not strict SUCCESS closure: {nbb}')
if nbb.get('manifest_sha256')!=sha(nbb_file): raise SystemExit('replacement NBB2 manifest hash mismatch')
if tnp.get('status')!='PASS' or int(tnp.get('records',-1))!=expected or tnp.get('status_counts')!={'PASS':expected}:
 raise SystemExit(f'replacement TNP is not strict PASS closure: {tnp}')
if tnp.get('sha256')!=sha(tnp_file): raise SystemExit('replacement TNP table hash mismatch')
PY

printf '{"state":"BUILDING","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
python3 "$BASE/scripts/build_corrected_cpu700k_metrics.py" \
  --candidates "$CORRECTED/cpu700k_corrected.tsv.gz" \
  --prefilter "$BASE/run/pvrig_bxcpu_model_predictions_v1_20260721/pvrig_prefilter_all_v2.tsv.gz" \
  --prefilter "$BASE/run/pvrig_1m_cpu_topup305705_prefilter_v1_20260722/pvrig_prefilter_cpu_topup305705_v1.tsv.gz" \
  --prefilter "$CORRECTED/replacement_selected3031_prefilter.tsv.gz" \
  --nbb2 "$PRE50/recovery/prestructure50000_nbb2_final_manifest.tsv.gz" \
  --nbb2 "$TOP/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  --nbb2 "$OLD/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  --nbb2 "$REPLACEMENT/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  --tnp "$PRE50/tnp_aggregate/tnp_prestructure50000.tsv.gz" \
  --tnp "$TOP/aggregate/tnp/tnp_all.tsv.gz" \
  --tnp "$OLD/aggregate/tnp/tnp_all.tsv.gz" \
  --tnp "$REPLACEMENT/aggregate/tnp/tnp_all.tsv.gz" \
  --output-dir "$OUT" --expected 700000 \
  >"$OUT/build.stdout.log" 2>"$OUT/build.stderr.log"
(cd "$OUT" && sha256sum -c SHA256SUMS)
printf '{"state":"COMPLETE","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
