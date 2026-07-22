#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/mnt/d/work/抗体/code}
BASE="$ROOT/pvrig_500k_generation_20260721"
RUNTIME_REL=${RUNTIME_REL:-pvrig_bxcpu_model_runtime_v1_20260721}
PREF_REL=${PREF_REL:-$RUNTIME_REL/pvrig1m_cpu700k_replacement_reserve12124_prefilter_v1_20260722}
STRUCT_PREFIX=${STRUCT_PREFIX:-pvrig1m_cpu700k_replacement_dynamic}
PREF_LOCAL="$BASE/run/pvrig_1m_cpu700k_replacement_prefilter_v1_20260722"
CORRECTED="$BASE/run/pvrig_1m_cpu700k_corrected_v1_20260722"
DYNAMIC_INVALID="$BASE/run/pvrig_1m_cpu700k_dynamic_invalid_v1_20260722"
SYNC_BASE="$BASE/run"
PRE50="$BASE/run/pvrig_prestructure50k_tnp_bxcpu_v1_20260722"
TOP="$BASE/run/pvrig_1m_cpu_topup305705_nbb2_tnp_v1_20260722"
OLD="$BASE/run/pvrig_1m_old_cpu_remainder344295_nbb2_tnp_v1_20260722"
NODE1_BASE=${NODE1_BASE:-/data/qlyu/projects}
POLL_SECONDS=${POLL_SECONDS:-60}
mkdir -p "$PREF_LOCAL/status" "$CORRECTED" "$DYNAMIC_INVALID"
exec 9>"$PREF_LOCAL/status/replacement_pipeline.lock"
flock -n 9 || exit 75

remote_home=$(ssh bxcpu 'printf %s "$HOME"')
pref="$remote_home/$PREF_REL"
while ! ssh bxcpu "test -s '$pref/aggregated/READY.json'"; do
  printf '{"state":"WAITING_PREFILTER","updated_at":"%s"}\n' "$(date -Is)" >"$PREF_LOCAL/status/STATUS.json"
  sleep "$POLL_SECONDS"
done
rsync -a --partial --append-verify "bxcpu:$pref/aggregated/" "$PREF_LOCAL/aggregated/"
(cd "$PREF_LOCAL/aggregated" && sha256sum -c SHA256SUMS)
python3 - "$PREF_LOCAL/aggregated/READY.json" 12124 <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); expected=int(sys.argv[2])
if x.get('status') != 'READY' or int(x.get('records',-1)) != expected:
    raise SystemExit(f'replacement reserve prefilter is not strict READY/{expected}: {x}')
PY

initial_metrics=(
  "$PRE50/recovery/COMPLETE.json"
  "$PRE50/recovery/prestructure50000_nbb2_final_manifest.tsv.gz"
  "$PRE50/tnp_aggregate/READY.json"
  "$PRE50/tnp_aggregate/tnp_prestructure50000.tsv.gz"
  "$TOP/SYNC_COMPLETE.json"
  "$TOP/aggregate/nbb2/COMPLETE.json"
  "$TOP/aggregate/nbb2/nbb2_manifest.tsv.gz"
  "$TOP/aggregate/tnp/READY.json"
  "$TOP/aggregate/tnp/tnp_all.tsv.gz"
  "$OLD/SYNC_COMPLETE.json"
  "$OLD/aggregate/nbb2/COMPLETE.json"
  "$OLD/aggregate/nbb2/nbb2_manifest.tsv.gz"
  "$OLD/aggregate/tnp/READY.json"
  "$OLD/aggregate/tnp/tnp_all.tsv.gz"
)
while true; do
  missing=0
  for path in "${initial_metrics[@]}"; do [[ -s "$path" ]] || missing=$((missing + 1)); done
  printf '{"state":"WAITING_INITIAL_CPU_TECHNICAL_CENSUS","missing":%s,"updated_at":"%s"}\n' \
    "$missing" "$(date -Is)" >"$PREF_LOCAL/status/STATUS.json"
  [[ "$missing" -eq 0 ]] && break
  sleep "$POLL_SECONDS"
done
python3 - \
  "$PRE50/recovery/COMPLETE.json" "$PRE50/recovery/prestructure50000_nbb2_final_manifest.tsv.gz" \
  "$PRE50/tnp_aggregate/READY.json" "$PRE50/tnp_aggregate/tnp_prestructure50000.tsv.gz" 50000 \
  "$TOP/aggregate/nbb2/COMPLETE.json" "$TOP/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  "$TOP/aggregate/tnp/READY.json" "$TOP/aggregate/tnp/tnp_all.tsv.gz" 305705 \
  "$OLD/aggregate/nbb2/COMPLETE.json" "$OLD/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  "$OLD/aggregate/tnp/READY.json" "$OLD/aggregate/tnp/tnp_all.tsv.gz" 344295 <<'PY'
import hashlib,json,sys
from pathlib import Path
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 return h.hexdigest()
items=sys.argv[1:]
for offset in range(0,len(items),5):
 nbb_ready,nbb_file,tnp_ready,tnp_file,expected=items[offset:offset+5]; expected=int(expected)
 nbb=json.load(open(nbb_ready)); tnp=json.load(open(tnp_ready))
 if int(nbb.get('records',-1))!=expected or sum(map(int,nbb.get('status_counts',{}).values()))!=expected:
  raise SystemExit(f'NBB2 completion receipt mismatch: {nbb_ready}')
 if nbb.get('manifest_sha256')!=sha(nbb_file):
  raise SystemExit(f'NBB2 manifest hash mismatch: {nbb_file}')
 if int(tnp.get('records',-1))!=expected or sum(map(int,tnp.get('status_counts',{}).values()))!=expected:
  raise SystemExit(f'TNP completion receipt mismatch: {tnp_ready}')
 if tnp.get('sha256')!=sha(tnp_file):
  raise SystemExit(f'TNP table hash mismatch: {tnp_file}')
PY

python3 "$BASE/scripts/build_cpu700k_dynamic_invalid.py" \
  --candidates "$BASE/run/pvrig_500k_cpu_control_combined394k_v1_20260721/combined_exact_unique_fast_qc_pass.tsv.gz" \
  --candidates "$BASE/run/pvrig_1m_cpu_topup305705_v1_20260722_frozen/route_quota_exact_unique.tsv.gz" \
  --base-invalid "$BASE/run/pvrig_1m_cpu700k_nbb2_replacement_reserve_v1_20260722/cpu700k_nbb2_incompatible.tsv.gz" \
  --nbb2 "$PRE50/recovery/prestructure50000_nbb2_final_manifest.tsv.gz" \
  --nbb2 "$TOP/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  --nbb2 "$OLD/aggregate/nbb2/nbb2_manifest.tsv.gz" \
  --tnp "$PRE50/tnp_aggregate/tnp_prestructure50000.tsv.gz" \
  --tnp "$TOP/aggregate/tnp/tnp_all.tsv.gz" \
  --tnp "$OLD/aggregate/tnp/tnp_all.tsv.gz" \
  --output "$DYNAMIC_INVALID/cpu700k_dynamic_invalid.tsv.gz" \
  --receipt "$DYNAMIC_INVALID/READY.json" --expected 700000 \
  >"$DYNAMIC_INVALID/build.stdout.log" 2>"$DYNAMIC_INVALID/build.stderr.log"

python3 "$BASE/scripts/select_cpu700k_nbb2_replacements.py" \
  --cpu "$BASE/run/pvrig_500k_cpu_control_combined394k_v1_20260721/combined_exact_unique_fast_qc_pass.tsv.gz" \
  --cpu "$BASE/run/pvrig_1m_cpu_topup305705_v1_20260722_frozen/route_quota_exact_unique.tsv.gz" \
  --invalid "$DYNAMIC_INVALID/cpu700k_dynamic_invalid.tsv.gz" \
  --reserve-candidates "$BASE/run/pvrig_1m_cpu700k_nbb2_replacement_reserve_v1_20260722/cpu700k_nbb2_replacement_reserve.tsv.gz" \
  --reserve-prefilter "$PREF_LOCAL/aggregated/prefilter_all.tsv.gz" \
  --output-dir "$CORRECTED" --expected 700000 \
  >"$CORRECTED/select.stdout.log" 2>"$CORRECTED/select.stderr.log"
(cd "$CORRECTED" && sha256sum -c SHA256SUMS)
records=$(python3 - "$CORRECTED/READY.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); assert x['status']=='READY_FOR_REPLACEMENT_NBB2_TNP'; print(x['replacement_records'])
PY
)
test "$records" -ge 3031
selection_sha=$(sha256sum "$CORRECTED/replacement_selected3031_prefilter.tsv.gz" | awk '{print $1}')
selection_tag="${records}_${selection_sha:0:16}"
STRUCT_REL="$RUNTIME_REL/${STRUCT_PREFIX}_${selection_tag}_v1_20260722"
structure="$remote_home/$STRUCT_REL"
SYNC_LOCAL="$SYNC_BASE/pvrig_1m_cpu700k_replacement_${selection_tag}_nbb2_tnp_v1_20260722"
NODE1_ROOT="$NODE1_BASE/pvrig_1m_cpu700k_replacement_${selection_tag}_nbb2_tnp_v1_20260722"
mkdir -p "$SYNC_LOCAL"
python3 - "$CORRECTED/REPLACEMENT_CAMPAIGN.json" "$SYNC_LOCAL/CAMPAIGN_BINDING.json" \
  "$SYNC_LOCAL" "$NODE1_ROOT" \
  "$structure/nbb2" "$records" "$selection_sha" <<'PY'
import json,sys
from pathlib import Path
pointer,binding,local_root,node1_root,remote,records,digest=sys.argv[1:]
payload={'status':'BOUND','local_root':local_root,'node1_root':node1_root,
         'remote_campaign':remote,'records':int(records),'selection_sha256':digest}
for item in map(Path,(pointer,binding)):
 if item.exists():
  current=json.loads(item.read_text())
  if current!=payload: raise SystemExit(f'replacement campaign binding changed: {current}')
 else:
  tmp=item.with_suffix('.json.partial'); tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n'); tmp.replace(item)
PY
python3 - "$CORRECTED/replacement_selected3031.fasta.gz" \
  "$CORRECTED/replacement_selected3031_prefilter.tsv.gz" "$records" <<'PY'
import csv,gzip,hashlib,sys
fa,tsv,expected=sys.argv[1],sys.argv[2],int(sys.argv[3])
rows={}
with gzip.open(tsv,'rt',newline='') as f:
 r=csv.DictReader(f,delimiter='\t'); required={'candidate_id','sequence','sequence_sha256'}
 missing=required-set(r.fieldnames or [])
 if missing: raise SystemExit(f'replacement selection missing fields: {sorted(missing)}')
 for row in r:
  cid=row['candidate_id']; seq=row['sequence'].strip().upper()
  if cid in rows or seq in rows.values(): raise SystemExit(f'replacement duplicate: {cid}')
  if hashlib.sha256(seq.encode()).hexdigest()!=row['sequence_sha256']: raise SystemExit(f'replacement sequence hash mismatch: {cid}')
  rows[cid]=seq
records={}; current=''; chunks=[]
with gzip.open(fa,'rt') as f:
 for raw in f:
  line=raw.strip()
  if not line: continue
  if line.startswith('>'):
   if current:
    if current in records: raise SystemExit(f'replacement FASTA duplicate: {current}')
    records[current]=''.join(chunks).upper()
   current=line[1:].split()[0]; chunks=[]
  else: chunks.append(line)
 if current: records[current]=''.join(chunks).upper()
if len(rows)!=expected or records!=rows: raise SystemExit(f'replacement FASTA/TSV closure mismatch rows={len(rows)} fasta={len(records)} expected={expected}')
PY

ssh bxcpu "mkdir -p '$STRUCT_REL/input' '$STRUCT_REL/nbb2/input' '$STRUCT_REL/nbb2/status' '$STRUCT_REL/nbb2/logs'"
rsync -a --partial --append-verify \
  "$CORRECTED/replacement_selected3031.fasta.gz" \
  "$CORRECTED/replacement_selected3031_prefilter.tsv.gz" \
  "$CORRECTED/READY.json" \
  "bxcpu:$STRUCT_REL/input/"
ssh bxcpu 'bash -s' <<EOF
set -Eeuo pipefail
R="\$HOME/$RUNTIME_REL"
C="\$HOME/$STRUCT_REL"
"\$R/env/bin/python" "\$R/scripts/prepare_bxcpu_anarci_shards.py" \
  --input "\$C/input/replacement_selected3031.fasta.gz" \
  --output-dir "\$C/nbb2/input" --shards 8 >"\$C/nbb2/prepare.log"
python3 - "\$C" "$records" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
c=Path(sys.argv[1]); expected=int(sys.argv[2])
f=c/'input/replacement_selected3031.fasta.gz'
s=c/'input/replacement_selected3031_prefilter.tsv.gz'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as x:
  for block in iter(lambda:x.read(8<<20),b''): h.update(block)
 return h.hexdigest()
m=json.loads((c/'nbb2/input/MANIFEST.json').read_text())
assert m['records']==expected and m['shards']==8
(c/'input/SELECTION_READY.json').write_text(json.dumps({'status':'READY','records':expected,
 'fasta_sha256':sha(f),'selection_sha256':sha(s),'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
if [[ ! -s "\$C/nbb2/status/CHAIN_COMPLETE" ]]; then
 nohup env RUNTIME_ROOT="\$R" CAMPAIGN_ROOT="\$C/nbb2" EXPECTED_RECORDS="$records" SHARDS=8 \
   SELECTION="\$C/input/replacement_selected3031_prefilter.tsv.gz" \
   PREFILTER_READY="\$C/input/SELECTION_READY.json" \
   bash "\$R/scripts/monitor_bxcpu_nbb2_tnp_generic.sh" \
   >"\$C/nbb2/logs/watcher.stdout.log" 2>"\$C/nbb2/logs/watcher.stderr.log" &
 echo \$! >"\$C/nbb2/status/watcher.pid"
fi
EOF

printf '{"state":"STRUCTURE_CAMPAIGN_DEPLOYED","records":%s,"updated_at":"%s"}\n' \
  "$records" "$(date -Is)" >"$PREF_LOCAL/status/STATUS.json"

exec env \
  REMOTE_CAMPAIGN="$structure/nbb2" \
  LOCAL_ROOT="$SYNC_LOCAL" \
  NODE1_ROOT="$NODE1_ROOT" \
  POLL_SECONDS="$POLL_SECONDS" \
  PURGE_LOCAL_ARCHIVE_AFTER_NODE1_ACK=1 \
  PURGE_REMOTE_AFTER_NODE1_ACK=1 \
  bash "$BASE/scripts/sync_bxcpu_1m_cpu_topup_nbb2_tnp.sh"
