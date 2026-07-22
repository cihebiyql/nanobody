#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${ROOT:-/mnt/d/work/抗体/code}
BASE="$ROOT/pvrig_500k_generation_20260721"
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_cpu700k_nbb2_replacement_reserve_v1_20260722}
RUNTIME_REL=${RUNTIME_REL:-pvrig_bxcpu_model_runtime_v1_20260721}
CAMPAIGN_REL=${CAMPAIGN_REL:-$RUNTIME_REL/pvrig1m_cpu700k_replacement_reserve12124_prefilter_v1_20260722}
EXPECTED_RECORDS=${EXPECTED_RECORDS:-12124}
TSV="$LOCAL/cpu700k_nbb2_replacement_reserve.tsv.gz"
FASTA="$LOCAL/cpu700k_nbb2_replacement_reserve.fasta.gz"
READY="$LOCAL/READY.json"
VALIDATION="$LOCAL/INPUT_VALIDATION.json"

mkdir -p "$LOCAL/status"
exec 9>"$LOCAL/status/deploy.lock"
flock -n 9 || exit 75
test -s "$TSV" && test -s "$FASTA" && test -s "$READY"

python3 - "$TSV" "$FASTA" "$READY" "$VALIDATION" "$EXPECTED_RECORDS" <<'PY'
import csv,gzip,hashlib,json,sys
from collections import Counter
from pathlib import Path

tsv,fasta,ready,out=map(Path,sys.argv[1:5]); expected=int(sys.argv[5])
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 return h.hexdigest()
receipt=json.loads(ready.read_text())
with gzip.open(tsv,'rt',newline='') as h: rows=list(csv.DictReader(h,delimiter='\t'))
records=[]
with gzip.open(fasta,'rt') as h:
 name=None; seq=[]
 for line in h:
  line=line.strip()
  if not line: continue
  if line.startswith('>'):
   if name is not None: records.append((name,''.join(seq)))
   name=line[1:].split()[0]; seq=[]
  else: seq.append(line)
 if name is not None: records.append((name,''.join(seq)))
ids=[r['candidate_id'] for r in rows]; seqs=[r['sequence'] for r in rows]
assert len(rows)==expected==len(records)
assert len(ids)==len(set(ids)) and len(seqs)==len(set(seqs))
assert list(zip(ids,seqs))==records
assert all(r.get('fast_qc_status')=='PASS' for r in rows)
assert not any(r.get('parent_cluster')=='C0532' or r['sequence'].startswith('GGGS') for r in rows)
route_counts=dict(sorted(Counter(r['route_id'] for r in rows).items()))
assert route_counts==receipt['reserve_route_counts']
assert receipt['outputs'][tsv.name]==sha(tsv)
assert receipt['outputs'][fasta.name]==sha(fasta)
payload={'status':'PASS','records':len(rows),'candidate_id_exact_unique':True,
 'sequence_exact_unique':True,'fasta_tsv_exact_ordered_closure':True,
 'fast_qc_all_pass':True,'known_nbb2_incompatible_parent_absent':True,
 'route_counts':route_counts,'tsv_sha256':sha(tsv),'fasta_sha256':sha(fasta)}
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
print(json.dumps(payload,sort_keys=True))
PY

ssh bxcpu "mkdir -p '$CAMPAIGN_REL/input' '$CAMPAIGN_REL/risk/scripts' '$CAMPAIGN_REL/anarci/input' '$CAMPAIGN_REL/status' '$CAMPAIGN_REL/logs'"
rsync -a --partial --append-verify "$TSV" "$FASTA" "$READY" "$VALIDATION" \
  "bxcpu:$CAMPAIGN_REL/input/"
rsync -a --partial \
  "$BASE/scripts/run_bxcpu_sapiens_full.slurm" "$BASE/scripts/run_bxcpu_abnativ_full.slurm" \
  "$BASE/scripts/run_bxcpu_deepnano_corrected_full.slurm" "$BASE/scripts/run_bxcpu_binding_full.slurm" \
  "$BASE/scripts/run_bxcpu_sequence_risk_proxy.slurm" "$BASE/scripts/run_bxcpu_anarci_full.slurm" \
  "$BASE/scripts/run_bxcpu_generic_prefilter_finalize.slurm" "$BASE/scripts/monitor_bxcpu_generic_prefilter.sh" \
  "$BASE/scripts/build_bxcpu_prefilter_table.py" "$BASE/scripts/prepare_bxcpu_anarci_shards.py" \
  "bxcpu:$RUNTIME_REL/scripts/"
rsync -a --partial "$BASE/scripts/score_sequence_risk_proxy.py" \
  "bxcpu:$CAMPAIGN_REL/risk/scripts/"

ssh bxcpu 'bash -s' <<EOF
set -Eeuo pipefail
R="\$HOME/$RUNTIME_REL"
C="\$HOME/$CAMPAIGN_REL"
N=$EXPECTED_RECORDS
"\$R/env/bin/python" "\$R/scripts/prepare_bxcpu_anarci_shards.py" \
  --input "\$C/input/cpu700k_nbb2_replacement_reserve.fasta.gz" \
  --output-dir "\$C/anarci/input" --shards 32 >"\$C/anarci/prepare.log"
python3 - "\$C" "\$N" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
c=Path(sys.argv[1]); expected=int(sys.argv[2])
f=c/'input/cpu700k_nbb2_replacement_reserve.fasta.gz'
t=c/'input/cpu700k_nbb2_replacement_reserve.tsv.gz'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as x:
  for block in iter(lambda:x.read(8<<20),b''): h.update(block)
 return h.hexdigest()
m=json.loads((c/'anarci/input/MANIFEST.json').read_text())
assert m['records']==expected and m['shards']==32
(c/'input/INPUT_READY.json').write_text(json.dumps({'status':'READY','records':expected,
 'fasta_sha256':sha(f),'candidate_sha256':sha(t),'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
if [[ ! -s "\$C/status/CHAIN_COMPLETE" ]]; then
  nohup env RUNTIME_ROOT="\$R" CAMPAIGN_ROOT="\$C" EXPECTED_RECORDS="\$N" SMALL_CAMPAIGN_MODE=1 \
    INPUT_FASTA="\$C/input/cpu700k_nbb2_replacement_reserve.fasta.gz" \
    CANDIDATE_TSV="\$C/input/cpu700k_nbb2_replacement_reserve.tsv.gz" \
    bash "\$R/scripts/monitor_bxcpu_generic_prefilter.sh" \
    >"\$C/logs/watcher.stdout.log" 2>"\$C/logs/watcher.stderr.log" &
  echo \$! >"\$C/status/watcher.pid"
fi
EOF

python3 - "$LOCAL/status/PREFILTER_DEPLOYMENT.json" "$EXPECTED_RECORDS" "$CAMPAIGN_REL" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
out,n,campaign=sys.argv[1:]
Path(out).write_text(json.dumps({'state':'DEPLOYED','records':int(n),'remote_campaign':campaign,
 'updated_at':datetime.now(timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
