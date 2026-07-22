#!/usr/bin/env bash
set -Eeuo pipefail
: "${RUNTIME_ROOT:?}"; : "${CAMPAIGN_ROOT:?}"; : "${EXPECTED_RECORDS:?}"
: "${INPUT_FASTA:?}"; : "${CANDIDATE_TSV:?}"
SUBMIT_RETRY_SECONDS=${SUBMIT_RETRY_SECONDS:-60}
SMALL_CAMPAIGN_MODE=${SMALL_CAMPAIGN_MODE:-0}
STATUS="$CAMPAIGN_ROOT/status"; mkdir -p "$STATUS" "$CAMPAIGN_ROOT/logs"
exec 9>"$STATUS/chain.lock"; flock -n 9 || exit 75
state(){ python3 - "$STATUS/CHAIN.json" "$1" "${2:-}" <<'PY'
import json,os,sys,time
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'state':sys.argv[2],'message':sys.argv[3],'pid':os.getppid(),'updated_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
}
job_id(){ [[ -f "$STATUS/JOB_IDS" ]] || return 0; sed -n "s/^$1=//p" "$STATUS/JOB_IDS"|tail -1; }
save_job(){ local key=$1 value=$2; echo "$key=$value" >>"$STATUS/JOB_IDS"; }
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
wait_completed(){
 local id=$1 label=$2 states
 while [[ -n "$(squeue -h -j "$id" 2>/dev/null || true)" ]]; do state "WAITING_$label" "job=$id"; sleep 30; done
 states=$(sacct -X -j "$id" -n -P -o State|sed '/^$/d'|sed 's/+.*$//'|sort -u)
 [[ "$states" == "COMPLETED" ]] || { state FAILED "$label job=$id states=$states"; return 1; }
}
while [[ ! -s "$CAMPAIGN_ROOT/input/INPUT_READY.json" ]]; do state WAITING_INPUT "$CAMPAIGN_ROOT/input/INPUT_READY.json"; sleep 30; done
cd "$RUNTIME_ROOT"
sapiens_resources=(); abnativ_resources=(); deepnano_resources=(); binding_resources=(); risk_resources=(); anarci_resources=()
if [[ "$SMALL_CAMPAIGN_MODE" == 1 ]]; then
 sapiens_resources=(--nodes=1 --ntasks-per-node=4 --cpus-per-task=16)
 abnativ_resources=(--nodes=1 --ntasks-per-node=4 --cpus-per-task=16)
 deepnano_resources=(--nodes=1 --ntasks-per-node=4 --cpus-per-task=16)
 binding_resources=(--nodes=1 --ntasks-per-node=4 --cpus-per-task=16)
 risk_resources=(--nodes=1 --ntasks-per-node=64 --cpus-per-task=1)
 anarci_resources=(--array=0-7%1)
fi
sapiens=$(job_id SAPIENS)
if [[ -z "$sapiens" ]]; then sapiens=$(submit_job SAPIENS sbatch --parsable "${sapiens_resources[@]}" --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",INPUT="$INPUT_FASTA",EXPECTED_RECORDS="$EXPECTED_RECORDS" "$RUNTIME_ROOT/scripts/run_bxcpu_sapiens_full.slurm"); save_job SAPIENS "$sapiens"; fi
wait_completed "$sapiens" SAPIENS
abnativ=$(job_id ABNATIV)
if [[ -z "$abnativ" ]]; then abnativ=$(submit_job ABNATIV sbatch --parsable "${abnativ_resources[@]}" --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",INPUT="$INPUT_FASTA",EXPECTED_RECORDS="$EXPECTED_RECORDS" "$RUNTIME_ROOT/scripts/run_bxcpu_abnativ_full.slurm"); save_job ABNATIV "$abnativ"; fi
wait_completed "$abnativ" ABNATIV
deepnano=$(job_id DEEPNANO)
if [[ -z "$deepnano" ]]; then deepnano=$(submit_job DEEPNANO sbatch --parsable "${deepnano_resources[@]}" --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",INPUT="$INPUT_FASTA",EXPECTED_RECORDS="$EXPECTED_RECORDS" "$RUNTIME_ROOT/scripts/run_bxcpu_deepnano_corrected_full.slurm"); save_job DEEPNANO "$deepnano"; fi
wait_completed "$deepnano" DEEPNANO
binding=$(job_id BINDING)
if [[ -z "$binding" ]]; then binding=$(submit_job BINDING sbatch --parsable "${binding_resources[@]}" --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",MODEL_ROOT="$RUNTIME_ROOT/models",INPUT="$INPUT_FASTA",EXPECTED_RECORDS="$EXPECTED_RECORDS" "$RUNTIME_ROOT/scripts/run_bxcpu_binding_full.slurm"); save_job BINDING "$binding"; fi
wait_completed "$binding" BINDING
risk=$(job_id RISK)
if [[ -z "$risk" ]]; then risk=$(cd "$CAMPAIGN_ROOT/risk" && submit_job RISK sbatch --parsable "${risk_resources[@]}" --export=ALL,ROOT="$CAMPAIGN_ROOT/risk",INPUT="$INPUT_FASTA" "$RUNTIME_ROOT/scripts/run_bxcpu_sequence_risk_proxy.slurm"); save_job RISK "$risk"; fi
wait_completed "$risk" RISK
anarci=$(job_id ANARCI)
if [[ -z "$anarci" ]]; then anarci=$(cd "$CAMPAIGN_ROOT/anarci" && submit_job ANARCI sbatch --parsable "${anarci_resources[@]}" --export=ALL,ROOT="$RUNTIME_ROOT",ENV_ROOT="$RUNTIME_ROOT/env",CAMPAIGN="$CAMPAIGN_ROOT/anarci" "$RUNTIME_ROOT/scripts/run_bxcpu_anarci_full.slurm"); save_job ANARCI "$anarci"; fi
wait_completed "$anarci" ANARCI
final=$(job_id FINALIZE)
if [[ -z "$final" ]]; then final=$(submit_job FINALIZE sbatch --parsable --output="$CAMPAIGN_ROOT/logs/finalize-%j.out" --error="$CAMPAIGN_ROOT/logs/finalize-%j.err" --export=ALL,RUNTIME_ROOT="$RUNTIME_ROOT",CAMPAIGN_ROOT="$CAMPAIGN_ROOT",EXPECTED_RECORDS="$EXPECTED_RECORDS",SAPIENS_JOB_ID="$sapiens",ABNATIV_JOB_ID="$abnativ",DEEPNANO_JOB_ID="$deepnano",BINDING_JOB_ID="$binding",ANARCI_JOB_ID="$anarci",CANDIDATE_TSV="$CANDIDATE_TSV" "$RUNTIME_ROOT/scripts/run_bxcpu_generic_prefilter_finalize.slurm"); save_job FINALIZE "$final"; fi
wait_completed "$final" FINALIZE
test -s "$CAMPAIGN_ROOT/aggregated/READY.json"
state COMPLETE "records=$EXPECTED_RECORDS"
date -Is >"$STATUS/CHAIN_COMPLETE"
