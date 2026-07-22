#!/usr/bin/env bash
set -Eeuo pipefail
BASE=${BASE:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721}
FINAL=${FINAL:-$BASE/run/pvrig_1m_screening_pool_exact1m_v1_20260722}
LOCAL=${LOCAL:-$BASE/run/pvrig_1m_cpu_fixed_pose_selected300k_metrics_v1_20260722}
RUNTIME=${RUNTIME:-/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721}
REMOTE=${REMOTE:-$RUNTIME/pvrig1m_cpu_fixed_pose_selected300k_metrics_v1_20260722}
LOCK_DIR=${LOCK_DIR:-$BASE/run/.locks}
mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_DIR/pvrig_fixed_pose300k_metrics_deploy.lock"
if ! flock -n 9; then
  echo "another fixed-pose 300k metrics deploy controller is active" >&2
  exit 0
fi
while [[ ! -s "$FINAL/READY.json" ]]; do sleep 30; done
if [[ -s "$LOCAL/JOB_CHAIN.json" ]]; then cat "$LOCAL/JOB_CHAIN.json"; exit 0; fi
if [[ ! -s "$LOCAL/READY_FOR_DEPLOY.json" ]]; then
  test ! -e "$LOCAL.partial"
  mkdir -p "$LOCAL.partial/scripts" "$LOCAL.partial/logs" "$LOCAL.partial/status"
  python3 "$BASE/scripts/prepare_fixed_pose300k_metrics_input.py" \
    --input "$FINAL/fixed_pose_cpu_selected300k.tsv.gz" --output-dir "$LOCAL.partial/input"
  python3 "$BASE/scripts/prepare_bxcpu_anarci_shards.py" --input "$LOCAL.partial/input/fixed_pose_selected300k.fasta.gz" \
    --output-dir "$LOCAL.partial/anarci300k_v1/input" --shards 32
  for script in prepare_bxcpu_binding_shard.py predict_deepnano_length_bucketed.py \
    run_bxcpu_binding_corrected_worker.sh run_bxcpu_binding_corrected300k.slurm aggregate_bxcpu_binding_results.py \
    score_sequence_risk_proxy.py run_bxcpu_sequence_risk300k.slurm prepare_bxcpu_anarci_shards.py \
    run_bxcpu_anarci_full.slurm aggregate_bxcpu_anarci_results.py run_bxcpu_anarci_aggregate300k.slurm \
    run_bxcpu_sapiens_worker.sh run_bxcpu_sapiens_full.slurm aggregate_bxcpu_sapiens_results.py \
    run_bxcpu_abnativ_worker.sh run_bxcpu_abnativ_full.slurm aggregate_bxcpu_abnativ_results.py \
    run_abnativ_subshards.py abnativ_score_direct.py; do
    cp "$BASE/scripts/$script" "$LOCAL.partial/scripts/"
  done
  python3 - "$LOCAL.partial" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
r=Path(sys.argv[1]); files=[p for p in r.rglob('*') if p.is_file()]
with (r/'SHA256SUMS').open('w') as h:
 for p in sorted(files): h.write(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(r)}\n')
(r/'READY_FOR_DEPLOY.json').write_text(json.dumps({'status':'READY','records':300000,'files':len(files),
 'bytes':sum(p.stat().st_size for p in files),'created_epoch':time.time(),
 'scientific_boundary':'computational developability and weak binding priors; not measured purity, expression, Kd, IC50, or blocking'},indent=2,sort_keys=True)+'\n')
PY
  mv "$LOCAL.partial" "$LOCAL"
fi
ssh bxcpu "mkdir -p '$REMOTE'"
# Upload only the immutable deployment package.  The same local root also
# receives a continuously downloaded remote_mirror; sending LOCAL/ wholesale
# would feed that mirror back into bxcpu and duplicate growing result trees.
rsync -a --partial --append-verify -e ssh \
  --include='/input/***' \
  --include='/anarci300k_v1/' --include='/anarci300k_v1/input/***' \
  --include='/scripts/***' \
  --include='/SHA256SUMS' --include='/READY_FOR_DEPLOY.json' \
  --exclude='*' \
  "$LOCAL/" "bxcpu:$REMOTE/"
ssh bxcpu "set -e; cd '$REMOTE'; sha256sum -c SHA256SUMS >/dev/null; \
  for name in env models tools vhh_eval_tools; do test -e \"\$name\" || ln -s '$RUNTIME'/\"\$name\" \"\$name\"; done"

STATUS="$LOCAL/status"
IDS="$STATUS/JOB_IDS"
mkdir -p "$STATUS"

write_submission_state() {
  python3 - "$IDS" "$LOCAL/SUBMISSION_STATE.json" "$1" "$2" <<'PY'
import json,sys,time
from pathlib import Path
ids_path,out,state,message=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4]
jobs={}
if ids_path.is_file():
    for line in ids_path.read_text().splitlines():
        if '=' in line:
            key,value=line.split('=',1); jobs[key.lower()]=value
out.write_text(json.dumps({'status':state,'message':message,'jobs':jobs,
 'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
  rsync -a --partial --append-verify -e ssh "$LOCAL/SUBMISSION_STATE.json" "bxcpu:$REMOTE/SUBMISSION_STATE.json"
}

job_id() {
  local label=$1
  [[ -f "$IDS" ]] || return 0
  sed -n "s/^${label}=//p" "$IDS" | tail -1
}

submit_stage() {
  local label=$1 command=$2 output rc
  output=$(job_id "$label")
  if [[ -n "$output" ]]; then printf '%s\n' "$output"; return 0; fi
  while true; do
    set +e
    output=$(ssh bxcpu "$command" 2>>"$STATUS/submit_retry.log")
    rc=$?
    set -e
    if [[ "$rc" -eq 0 && "$output" =~ ^[0-9]+([_;].*)?$ ]]; then
      output=${output%%[_;]*}
      printf '%s=%s\n' "$label" "$output" >>"$IDS"
      write_submission_state "SUBMITTED_$label" "job=$output"
      printf '%s\n' "$output"
      return 0
    fi
    write_submission_state "WAITING_SUBMIT_$label" "rc=$rc; scheduler submit limit or transient failure"
    sleep 60
  done
}

wait_stage() {
  local label=$1 id=$2 states attempt
  while ssh bxcpu "squeue -h -j '$id' | grep -q ."; do
    write_submission_state "WAITING_$label" "job=$id"
    sleep 60
  done
  states=""
  for attempt in {1..12}; do
    states=$(ssh bxcpu "sacct -X -j '$id' -n -P -o State 2>/dev/null" | sed '/^$/d' | sed 's/+.*$//' | sort -u)
    [[ -n "$states" ]] && break
    sleep 5
  done
  if [[ "$states" != COMPLETED ]]; then
    write_submission_state "FAILED_$label" "job=$id states=$states"
    echo "metrics stage $label failed: job=$id states=$states" >&2
    return 8
  fi
  write_submission_state "COMPLETED_$label" "job=$id"
}

RISK=$(submit_stage RISK "cd '$REMOTE' && sbatch --parsable --export=ALL,ROOT='$REMOTE',INPUT='$REMOTE/input/fixed_pose_selected300k.fasta.gz',ENV_ROOT='$RUNTIME/env',EXPECTED_RECORDS=300000 scripts/run_bxcpu_sequence_risk300k.slurm")
wait_stage RISK "$RISK"
ANARCI=$(submit_stage ANARCI "cd '$REMOTE' && sbatch --parsable --export=ALL,ROOT='$REMOTE',ENV_ROOT='$RUNTIME/env',CAMPAIGN='$REMOTE/anarci300k_v1' scripts/run_bxcpu_anarci_full.slurm")
wait_stage ANARCI "$ANARCI"
ANARCI_AGG=$(submit_stage ANARCI_AGGREGATE "cd '$REMOTE' && sbatch --parsable --export=ALL,ROOT='$REMOTE',ENV_ROOT='$RUNTIME/env',CAMPAIGN='$REMOTE/anarci300k_v1',FULL_JOB_ID='$ANARCI' scripts/run_bxcpu_anarci_aggregate300k.slurm")
wait_stage ANARCI_AGGREGATE "$ANARCI_AGG"
BINDING=$(submit_stage BINDING "cd '$REMOTE' && sbatch --parsable --export=ALL,ROOT='$REMOTE',INPUT='$REMOTE/input/fixed_pose_selected300k.fasta.gz',ENV_ROOT='$RUNTIME/env',MODEL_ROOT='$RUNTIME/models',EXPECTED_RECORDS=300000 scripts/run_bxcpu_binding_corrected300k.slurm")
wait_stage BINDING "$BINDING"
SAPIENS=$(submit_stage SAPIENS "cd '$REMOTE' && sbatch --parsable --export=ALL,ROOT='$REMOTE',INPUT='$REMOTE/input/fixed_pose_selected300k.fasta.gz',ENV_ROOT='$RUNTIME/env',EXPECTED_RECORDS=300000 scripts/run_bxcpu_sapiens_full.slurm")
wait_stage SAPIENS "$SAPIENS"
ABNATIV=$(submit_stage ABNATIV "cd '$REMOTE' && sbatch --parsable --export=ALL,ROOT='$REMOTE',INPUT='$REMOTE/input/fixed_pose_selected300k.fasta.gz',ENV_ROOT='$RUNTIME/env',EXPECTED_RECORDS=300000 scripts/run_bxcpu_abnativ_full.slurm")
wait_stage ABNATIV "$ABNATIV"
python3 - "$LOCAL/JOB_CHAIN.json" "$REMOTE" "$RISK" "$ANARCI" "$ANARCI_AGG" "$BINDING" "$SAPIENS" "$ABNATIV" <<'PY'
import json,sys,time
from pathlib import Path
out=Path(sys.argv[1]); remote=sys.argv[2]; names=('risk','anarci','anarci_aggregate','binding','sapiens','abnativ')
out.write_text(json.dumps({'status':'COMPLETED_SEQUENTIAL_QUOTA_SAFE','remote':remote,'jobs':dict(zip(names,sys.argv[3:])),
 'records':300000,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
rsync -a -e ssh "$LOCAL/JOB_CHAIN.json" "bxcpu:$REMOTE/JOB_CHAIN.json"
cat "$LOCAL/JOB_CHAIN.json"
