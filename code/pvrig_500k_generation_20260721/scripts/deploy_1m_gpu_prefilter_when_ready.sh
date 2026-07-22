#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${ROOT:-/mnt/d/work/抗体/code}
BASE="$ROOT/pvrig_500k_generation_20260721"
LOCAL="$BASE/run/pvrig_1m_gpu_raw_normalized_v1_20260722"
RUNTIME_REL=pvrig_bxcpu_model_runtime_v1_20260721
CAMPAIGN_REL="$RUNTIME_REL/pvrig1m_gpu_raw_prefilter_v1_20260722"
POLL_SECONDS=${POLL_SECONDS:-60}
mkdir -p "$LOCAL/status"
exec 9>"$LOCAL/status/deploy_prefilter.lock"; flock -n 9 || exit 75
while [[ ! -s "$LOCAL/status/NORMALIZE_COMPLETE" ]]; do sleep "$POLL_SECONDS"; done
records=$(python3 - "$LOCAL/NORMALIZE_RECEIPT.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); print(sum(x['route_fast_qc_pass'].values()))
PY
)
test "$records" -ge 300000
python3 "$BASE/scripts/validate_gpu_prefilter_input.py" \
  --candidates "$LOCAL/gpu_fast_qc_pass_exact_unique.tsv.gz" \
  --fasta "$LOCAL/gpu_fast_qc_pass_exact_unique.fasta.gz" \
  --receipt "$LOCAL/NORMALIZE_RECEIPT.json" \
  --output "$LOCAL/status/GPU_PREFILTER_INPUT_VALIDATION.json"
ssh bxcpu "mkdir -p '$CAMPAIGN_REL/input' '$CAMPAIGN_REL/risk/scripts' '$CAMPAIGN_REL/anarci/input' '$CAMPAIGN_REL/status' '$CAMPAIGN_REL/logs'"
rsync -a --partial --append-verify \
 "$LOCAL/gpu_fast_qc_pass_exact_unique.fasta.gz" \
 "$LOCAL/gpu_fast_qc_pass_exact_unique.tsv.gz" \
 "$LOCAL/NORMALIZE_RECEIPT.json" \
 "$LOCAL/status/GPU_PREFILTER_INPUT_VALIDATION.json" bxcpu:"$CAMPAIGN_REL/input/"
rsync -a --partial \
 "$BASE/scripts/run_bxcpu_sapiens_full.slurm" "$BASE/scripts/run_bxcpu_abnativ_full.slurm" \
 "$BASE/scripts/run_bxcpu_deepnano_corrected_full.slurm" "$BASE/scripts/run_bxcpu_binding_full.slurm" \
 "$BASE/scripts/run_bxcpu_sequence_risk_proxy.slurm" "$BASE/scripts/run_bxcpu_anarci_full.slurm" \
 "$BASE/scripts/run_bxcpu_generic_prefilter_finalize.slurm" "$BASE/scripts/monitor_bxcpu_generic_prefilter.sh" \
 "$BASE/scripts/build_bxcpu_prefilter_table.py" "$BASE/scripts/prepare_bxcpu_anarci_shards.py" \
 bxcpu:"$RUNTIME_REL/scripts/"
rsync -a --partial "$BASE/scripts/score_sequence_risk_proxy.py" bxcpu:"$CAMPAIGN_REL/risk/scripts/"
ssh bxcpu 'bash -s' <<EOF
set -euo pipefail
R="\$HOME/$RUNTIME_REL"; C="\$HOME/$CAMPAIGN_REL"; N=$records
"\$R/env/bin/python" "\$R/scripts/prepare_bxcpu_anarci_shards.py" --input "\$C/input/gpu_fast_qc_pass_exact_unique.fasta.gz" --output-dir "\$C/anarci/input" --shards 32 >"\$C/anarci/prepare.log"
python3 - "\$C" "\$N" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
c=Path(sys.argv[1]); expected=int(sys.argv[2]); f=c/'input/gpu_fast_qc_pass_exact_unique.fasta.gz'; t=c/'input/gpu_fast_qc_pass_exact_unique.tsv.gz'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as x:
  for b in iter(lambda:x.read(8<<20),b''): h.update(b)
 return h.hexdigest()
m=json.loads((c/'anarci/input/MANIFEST.json').read_text())
assert m['records']==expected and m['shards']==32
(c/'input/INPUT_READY.json').write_text(json.dumps({'status':'READY','records':expected,'fasta_sha256':sha(f),'candidate_sha256':sha(t),'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
nohup env RUNTIME_ROOT="\$R" CAMPAIGN_ROOT="\$C" EXPECTED_RECORDS="\$N" INPUT_FASTA="\$C/input/gpu_fast_qc_pass_exact_unique.fasta.gz" CANDIDATE_TSV="\$C/input/gpu_fast_qc_pass_exact_unique.tsv.gz" bash "\$R/scripts/monitor_bxcpu_generic_prefilter.sh" >"\$C/logs/watcher.stdout.log" 2>"\$C/logs/watcher.stderr.log" &
echo \$! >"\$C/status/watcher.pid"
EOF
printf '{"state":"DEPLOYED","records":%s,"updated_at":"%s"}\n' "$records" "$(date -Is)" >"$LOCAL/status/PREFILTER_DEPLOYMENT.json"
