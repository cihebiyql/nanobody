#!/usr/bin/env bash
set -Eeuo pipefail

: "${RUNTIME_ROOT:?RUNTIME_ROOT is required}"
: "${CAMPAIGN_ROOT:?CAMPAIGN_ROOT is required}"
: "${SAPIENS_JOB_ID:?SAPIENS_JOB_ID is required}"
: "${ABNATIV_JOB_ID:?ABNATIV_JOB_ID is required}"
EXPECTED_RECORDS=${EXPECTED_RECORDS:-305705}
INPUT_FASTA=${INPUT_FASTA:-$CAMPAIGN_ROOT/input/route_quota_exact_unique.fasta.gz}
CANDIDATE_TSV=${CANDIDATE_TSV:-$CAMPAIGN_ROOT/input/route_quota_exact_unique.tsv.gz}
STATUS="$CAMPAIGN_ROOT/status"
mkdir -p "$STATUS" "$CAMPAIGN_ROOT/aggregated" "$RUNTIME_ROOT/logs"
exec 9>"$STATUS/prefilter_chain.lock"
flock -n 9 || { echo "prefilter watcher already active" >&2; exit 75; }

write_state() {
  python3 - "$STATUS/PREFILTER_CHAIN.json" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"state":sys.argv[2],"message":sys.argv[3],
 "pid":os.getppid(),"updated_at":datetime.now(timezone.utc).isoformat()},indent=2,sort_keys=True)+"\n")
PY
}

wait_job() {
  local id=$1 label=$2 states
  while squeue -h -j "$id" | grep -q .; do
    write_state "WAITING_${label}" "job=$id"
    sleep 20
  done
  states=$(sacct -X -j "$id" -n -P -o State | sed '/^$/d' | sort -u)
  if [[ -z "$states" || "$states" == *FAILED* || "$states" == *CANCELLED* || "$states" == *TIMEOUT* || "$states" == *OUT_OF_MEMORY* ]]; then
    write_state FAILED "$label job=$id states=$states"
    return 1
  fi
  echo "$(date -Is) $label job=$id states=$states" >> "$STATUS/prefilter_chain.log"
}

wait_job "$SAPIENS_JOB_ID" SAPIENS
wait_job "$ABNATIV_JOB_ID" ABNATIV

cd "$RUNTIME_ROOT"
write_state SUBMITTING_REMAINING "DeepNano corrected, original binding/NanoBind, sequence risk"
deepnano=$(sbatch --parsable --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",INPUT="$INPUT_FASTA",EXPECTED_RECORDS="$EXPECTED_RECORDS" "$RUNTIME_ROOT/scripts/run_bxcpu_deepnano_corrected_full.slurm")
binding=$(sbatch --parsable --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",MODEL_ROOT="$RUNTIME_ROOT/models",INPUT="$INPUT_FASTA",EXPECTED_RECORDS="$EXPECTED_RECORDS" "$RUNTIME_ROOT/scripts/run_bxcpu_binding_full.slurm")
risk=$(cd "$CAMPAIGN_ROOT/risk" && sbatch --parsable --export=ALL,ROOT="$CAMPAIGN_ROOT/risk",INPUT="$INPUT_FASTA" "$CAMPAIGN_ROOT/risk/scripts/run_bxcpu_sequence_risk_proxy.slurm")
printf 'SAPIENS=%s\nABNATIV=%s\nDEEPNANO=%s\nBINDING=%s\nRISK=%s\n' \
  "$SAPIENS_JOB_ID" "$ABNATIV_JOB_ID" "$deepnano" "$binding" "$risk" > "$STATUS/PRIMARY_JOB_IDS"

wait_job "$deepnano" DEEPNANO
wait_job "$binding" BINDING
wait_job "$risk" RISK

# The 8-way ANARCI array consumes eight accounting submission slots, so submit
# it only after the monolithic jobs have left the queue.
anarci_campaign="$CAMPAIGN_ROOT/anarci_campaign"
mkdir -p "$anarci_campaign"
if [[ ! -e "$anarci_campaign/input" ]]; then
  ln -s ../anarci_input "$anarci_campaign/input"
fi
write_state SUBMITTING_ANARCI "32 shards via 8 array elements"
anarci=$(sbatch --parsable --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",CAMPAIGN="$anarci_campaign" "$RUNTIME_ROOT/scripts/run_bxcpu_anarci_full.slurm")
printf 'ANARCI=%s\n' "$anarci" >> "$STATUS/PRIMARY_JOB_IDS"
wait_job "$anarci" ANARCI

write_state AGGREGATING "strict ID/count aggregation"
agg="$CAMPAIGN_ROOT/aggregated"
mkdir -p "$agg"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_sapiens_results.py" \
  "$RUNTIME_ROOT/results/sapiens_full_$SAPIENS_JOB_ID" -o "$agg/sapiens_all.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_abnativ_results.py" \
  "$RUNTIME_ROOT/results/abnativ_full_$ABNATIV_JOB_ID" -o "$agg/abnativ_all.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_binding_results.py" \
  "$RUNTIME_ROOT/results/full_$binding" -o "$agg/binding_priors_uncorrected.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/build_corrected_binding_priors_v2.py" \
  "$RUNTIME_ROOT/results/deepnano_corrected_full_$deepnano" "$agg/binding_priors_uncorrected.tsv.gz" \
  -o "$agg/binding_priors_all_v2.tsv.gz" --expected-records "$EXPECTED_RECORDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_anarci_results.py" \
  --input-dir "$anarci_campaign/input" --results-dir "$anarci_campaign/results_$anarci" \
  --output "$agg/anarci_imgt_qc_all.tsv.gz" --summary "$agg/anarci_imgt_qc_all.tsv.gz.summary.json"

while [[ ! -s "$CANDIDATE_TSV" ]]; do
  write_state WAITING_CANDIDATE_TSV "path=$CANDIDATE_TSV"
  sleep 30
done
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/build_bxcpu_prefilter_table.py" \
  --candidates "$CANDIDATE_TSV" \
  --risk "$CAMPAIGN_ROOT/risk/results/sequence_risk_proxy_all.tsv.gz" \
  --binding "$agg/binding_priors_all_v2.tsv.gz" \
  --sapiens "$agg/sapiens_all.tsv.gz" --abnativ "$agg/abnativ_all.tsv.gz" \
  --anarci "$agg/anarci_imgt_qc_all.tsv.gz" \
  --output "$agg/pvrig_prefilter_cpu_topup305705_v1.tsv.gz" \
  --summary "$agg/pvrig_prefilter_cpu_topup305705_v1.tsv.gz.summary.json"

python3 - "$agg" "$EXPECTED_RECORDS" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
root=Path(sys.argv[1]); expected=int(sys.argv[2]); files=sorted(p for p in root.iterdir() if p.is_file())
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
(root/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in files))
(root/'READY.json').write_text(json.dumps({'status':'READY','records':expected,'created_epoch':time.time(),
 'scientific_boundary':'sequence/structure-independent priors and developability proxies; not Kd, IC50, purity, expression, docking, or blocking evidence'},indent=2,sort_keys=True)+'\n')
PY
write_state COMPLETE "records=$EXPECTED_RECORDS"
date -Is > "$STATUS/PREFILTER_CHAIN_COMPLETE"
