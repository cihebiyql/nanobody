#!/usr/bin/env bash
set -Eeuo pipefail
: "${RUNTIME_ROOT:?}"; : "${CAMPAIGN_ROOT:?}"; : "${RECOVERY_JOB_ID:?}"
EXPECTED_RECORDS=${EXPECTED_RECORDS:-305705}
ORIGINAL_BINDING_JOB_ID=${ORIGINAL_BINDING_JOB_ID:-11939665}
DEEPNANO_JOB_ID=${DEEPNANO_JOB_ID:-11939664}
SAPIENS_JOB_ID=${SAPIENS_JOB_ID:-11939655}
ABNATIV_JOB_ID=${ABNATIV_JOB_ID:-11939656}
INPUT_FASTA=${INPUT_FASTA:-$CAMPAIGN_ROOT/input/route_quota_exact_unique.fasta.gz}
CANDIDATE_TSV=${CANDIDATE_TSV:-$CAMPAIGN_ROOT/input/route_quota_exact_unique.tsv.gz}
STATUS="$CAMPAIGN_ROOT/status"; AGG="$CAMPAIGN_ROOT/aggregated"
mkdir -p "$STATUS" "$AGG"
exec 9>"$STATUS/prefilter_recovery.lock"; flock -n 9 || exit 75

state(){ python3 - "$STATUS/PREFILTER_CHAIN.json" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'state':sys.argv[2],'message':sys.argv[3],'pid':os.getppid(),'updated_at':datetime.now(timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
}
wait_completed(){
 local id=$1 label=$2 states
 while squeue -h -j "$id"|grep -q .; do state "WAITING_$label" "job=$id"; sleep 20; done
 states=$(sacct -X -j "$id" -n -P -o State|sed '/^$/d'|sed 's/+.*$//'|sort -u)
 [[ "$states" == "COMPLETED" ]] || { state FAILED "$label job=$id states=$states"; return 1; }
}

wait_completed "$RECOVERY_JOB_ID" BINDING_RECOVERY
state VALIDATING_BINDING "original=$ORIGINAL_BINDING_JOB_ID recovery=$RECOVERY_JOB_ID"
"$RUNTIME_ROOT/env/bin/python" - "$RUNTIME_ROOT/results/full_$ORIGINAL_BINDING_JOB_ID" "$EXPECTED_RECORDS" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); expected=int(sys.argv[2]); total=0
for index in range(32):
 path=root/f'task_{index:03d}'/'COMPLETE.json'
 if not path.is_file(): raise SystemExit(f'missing {path}')
 payload=json.loads(path.read_text())
 if payload.get('status')!='PASS': raise SystemExit(f'failed {path}')
 total+=int(payload['counts']['prepared'])
if total!=expected: raise SystemExit(f'count mismatch {total} != {expected}')
(root/'COMPLETE.json').write_text(json.dumps({'status':'PASS','tasks':32,'records':total,'recovered_tasks':[29,30]},indent=2,sort_keys=True)+'\n')
PY

anarci_campaign="$CAMPAIGN_ROOT/anarci_campaign"; mkdir -p "$anarci_campaign"
[[ -e "$anarci_campaign/input" ]] || ln -s ../anarci_input "$anarci_campaign/input"
anarci=$(sed -n 's/^ANARCI_RECOVERY=//p' "$STATUS/PRIMARY_JOB_IDS" 2>/dev/null | tail -1)
if [[ -z "$anarci" || ! -s "$anarci_campaign/results_${anarci}/task_031/COMPLETE" ]]; then
 state SUBMITTING_ANARCI "32 shards via 8 nodes"
 anarci=$(cd "$RUNTIME_ROOT" && sbatch --parsable --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",CAMPAIGN="$anarci_campaign" "$RUNTIME_ROOT/scripts/run_bxcpu_anarci_full.slurm")
 echo "ANARCI_RECOVERY=$anarci" >> "$STATUS/PRIMARY_JOB_IDS"
 wait_completed "$anarci" ANARCI
fi

state AGGREGATING "records=$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_sapiens_results.py" "$RUNTIME_ROOT/results/sapiens_full_$SAPIENS_JOB_ID" -o "$AGG/sapiens_all.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_abnativ_results.py" "$RUNTIME_ROOT/results/abnativ_full_$ABNATIV_JOB_ID" -o "$AGG/abnativ_all.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_binding_results.py" "$RUNTIME_ROOT/results/full_$ORIGINAL_BINDING_JOB_ID" -o "$AGG/binding_priors_uncorrected.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/build_corrected_binding_priors_v2.py" "$RUNTIME_ROOT/results/deepnano_corrected_full_$DEEPNANO_JOB_ID" "$AGG/binding_priors_uncorrected.tsv.gz" -o "$AGG/binding_priors_all_v2.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_anarci_results.py" --input-dir "$anarci_campaign/input" --results-dir "$anarci_campaign/results_$anarci" --output "$AGG/anarci_imgt_qc_all.tsv.gz" --summary "$AGG/anarci_imgt_qc_all.tsv.gz.summary.json"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/build_bxcpu_prefilter_table.py" --candidates "$CANDIDATE_TSV" --risk "$CAMPAIGN_ROOT/risk/results/sequence_risk_proxy_all.tsv.gz" --binding "$AGG/binding_priors_all_v2.tsv.gz" --sapiens "$AGG/sapiens_all.tsv.gz" --abnativ "$AGG/abnativ_all.tsv.gz" --anarci "$AGG/anarci_imgt_qc_all.tsv.gz" --output "$AGG/pvrig_prefilter_cpu_topup305705_v1.tsv.gz" --summary "$AGG/pvrig_prefilter_cpu_topup305705_v1.tsv.gz.summary.json"

python3 - "$AGG" "$EXPECTED_RECORDS" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
root=Path(sys.argv[1]); expected=int(sys.argv[2]); files=sorted(p for p in root.iterdir() if p.is_file() and p.name not in {'SHA256SUMS','READY.json'})
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''): h.update(block)
 return h.hexdigest()
(root/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in files))
(root/'READY.json').write_text(json.dumps({'status':'READY','records':expected,'created_epoch':time.time(),'recovered_binding_tasks':[29,30],'scientific_boundary':'weak priors and developability proxies; not Kd, IC50, purity, expression, docking, or blocking evidence'},indent=2,sort_keys=True)+'\n')
PY
state COMPLETE "records=$EXPECTED_RECORDS"
date -Is > "$STATUS/PREFILTER_CHAIN_COMPLETE"
