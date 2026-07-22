#!/usr/bin/env bash
set -Eeuo pipefail
: "${RUNTIME_ROOT:?}"; : "${CAMPAIGN_ROOT:?}"; : "${EXPECTED_RECORDS:?}"; : "${SHARDS:?}"; : "${SELECTION:?}"
PREFILTER_READY=${PREFILTER_READY:-$CAMPAIGN_ROOT/../aggregated/READY.json}
SOURCE_FASTA=${SOURCE_FASTA:-}
SUBMIT_RETRY_SECONDS=${SUBMIT_RETRY_SECONDS:-60}
STATUS="$CAMPAIGN_ROOT/status"; mkdir -p "$STATUS" "$CAMPAIGN_ROOT/logs"
exec 9>"$STATUS/chain.lock"; flock -n 9 || exit 75
state(){ python3 - "$STATUS/CHAIN.json" "$1" "${2:-}" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'state':sys.argv[2],'message':sys.argv[3],'pid':os.getppid(),'updated_at':datetime.now(timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
}
trap 'rc=$?; state FAILED "return_code=$rc" || true; exit $rc' ERR
wait_job(){
 local id=$1 label=$2 states
 while squeue -h -j "$id"|grep -q .; do state "WAITING_$label" "job=$id"; sleep 30; done
 states=$(sacct -X -j "$id" -n -P -o State|sed '/^$/d'|sed 's/+.*$//'|sort -u)
 [[ "$states" == "COMPLETED" ]]
}
job_id(){
 [[ -f "$STATUS/JOB_IDS" ]] || return 0
 sed -n "s/^$1=//p" "$STATUS/JOB_IDS" | tail -1
}
submit_job(){
 local label=$1 output rc; shift
 while true; do
  set +e
  output=$("$@" 2>>"$CAMPAIGN_ROOT/logs/submit_retry.log")
  rc=$?
  set -e
  if [[ "$rc" -eq 0 && "$output" =~ ^[0-9]+([_;].*)?$ ]]; then
   printf '%s\n' "$output"
   return 0
  fi
  state "WAITING_SUBMIT_$label" "rc=$rc; scheduler submit limit or transient failure"
  sleep "$SUBMIT_RETRY_SECONDS"
 done
}
while [[ ! -s "$PREFILTER_READY" || ! -s "$SELECTION" ]]; do state WAITING_PREFILTER "$PREFILTER_READY"; sleep 30; done
if [[ -z "$SOURCE_FASTA" ]]; then
 SOURCE_FASTA=$("$RUNTIME_ROOT/env/bin/python" - "$PREFILTER_READY" "$CAMPAIGN_ROOT/../input" <<'PY'
import hashlib,json,sys
from pathlib import Path
ready=json.load(open(sys.argv[1])); expected=ready.get('fasta_sha256',''); root=Path(sys.argv[2])
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 return h.hexdigest()
matches=[p for p in sorted(root.glob('*.fasta*')) if p.is_file() and expected and sha(p)==expected]
if len(matches)!=1: raise SystemExit(f'expected exactly one source FASTA matching READY hash; found {len(matches)}')
print(matches[0])
PY
 )
fi
state VALIDATING_INPUT "records=$EXPECTED_RECORDS shards=$SHARDS"
"$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/validate_nbb2_campaign_input.py" \
 --ready "$PREFILTER_READY" --selection "$SELECTION" --source-fasta "$SOURCE_FASTA" \
 --shard-dir "$CAMPAIGN_ROOT/input" --expected "$EXPECTED_RECORDS" --shards "$SHARDS" \
 --output "$STATUS/INPUT_VALIDATION.json"
nbb=$(job_id NBB2)
if [[ -z "$nbb" ]]; then
 state SUBMITTING_NBB2 "records=$EXPECTED_RECORDS shards=$SHARDS"
 nbb=$(cd "$CAMPAIGN_ROOT" && submit_job NBB2 sbatch --parsable --array="0-$((SHARDS-1))%$SHARDS" \
  --output="$CAMPAIGN_ROOT/logs/nbb2-%A_%a.out" --error="$CAMPAIGN_ROOT/logs/nbb2-%A_%a.err" \
  --export=ALL,RUNTIME_ROOT="$RUNTIME_ROOT",CAMPAIGN_ROOT="$CAMPAIGN_ROOT",ENV_ROOT="$RUNTIME_ROOT/env" \
  "$RUNTIME_ROOT/scripts/run_bxcpu_nbb2_generic.slurm")
 echo "NBB2=$nbb" > "$STATUS/JOB_IDS"
fi
wait_job "$nbb" NBB2
if [[ ! -s "$CAMPAIGN_ROOT/aggregated_${nbb}/COMPLETE.json" ]]; then
 state AGGREGATING_NBB2 "job=$nbb"
 "$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_nbb2_generic.py" --campaign "$CAMPAIGN_ROOT" --full-job-id "$nbb" --shards "$SHARDS" --expected "$EXPECTED_RECORDS"
fi
tnp=$(job_id TNP)
if [[ -z "$tnp" ]]; then
 state SUBMITTING_TNP "nbb2=$nbb"
 tnp=$(cd "$CAMPAIGN_ROOT" && submit_job TNP sbatch --parsable --array="0-$((SHARDS-1))%$SHARDS" \
  --output="$CAMPAIGN_ROOT/logs/tnp-%A_%a.scheduler.out" --error="$CAMPAIGN_ROOT/logs/tnp-%A_%a.scheduler.err" \
  --export=ALL,RUNTIME_ROOT="$RUNTIME_ROOT",CAMPAIGN_ROOT="$CAMPAIGN_ROOT",NBB2_JOB_ID="$nbb",SELECTION="$SELECTION" \
  "$RUNTIME_ROOT/scripts/run_bxcpu_tnp_generic.slurm")
 echo "TNP=$tnp" >> "$STATUS/JOB_IDS"
fi
wait_job "$tnp" TNP
if [[ ! -s "$CAMPAIGN_ROOT/tnp_aggregated_${tnp}/READY.json" ]]; then
 state AGGREGATING_TNP "job=$tnp"
 "$RUNTIME_ROOT/env/bin/python" "$RUNTIME_ROOT/scripts/aggregate_bxcpu_tnp_generic.py" --input-dir "$CAMPAIGN_ROOT/tnp_results_$tnp" --selection "$SELECTION" --output-dir "$CAMPAIGN_ROOT/tnp_aggregated_$tnp" --expected "$EXPECTED_RECORDS" --shards "$SHARDS"
fi
state COMPLETE "NBB2=$nbb TNP=$tnp"; date -Is > "$STATUS/CHAIN_COMPLETE"
