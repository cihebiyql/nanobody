#!/usr/bin/env bash
set -Eeuo pipefail

REMOTE_ROOT=${REMOTE_ROOT:-\$HOME/pvrig_bxcpu_model_runtime_v1_20260721}
NBB2_JOB_ID=${NBB2_JOB_ID:-11939532}
NBB2_AGG_JOB_ID=${NBB2_AGG_JOB_ID:-11939533}
LOCAL_ROOT=${LOCAL_ROOT:?LOCAL_ROOT is required}
NODE1_TARGET=${NODE1_TARGET:-/data1/qlyu/projects/pvrig_prestructure50k_tnp_v1_20260722}
POLL_SECONDS=${POLL_SECONDS:-30}
NODE1_SSH=${NODE1_SSH:-/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/scripts/ssh_node1_windows_proxy.sh}
if [[ "$REMOTE_ROOT" == '\$HOME/'* ]]; then
  remote_home=$(ssh bxcpu 'printf %s "$HOME"')
  REMOTE_ROOT="$remote_home/${REMOTE_ROOT#\$HOME/}"
fi
mkdir -p "$LOCAL_ROOT"

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOCAL_ROOT/monitor.log"; }

while ! ssh bxcpu "test -s '$REMOTE_ROOT/prestructure50k_v1/aggregated_${NBB2_JOB_ID}/COMPLETE.json'"; do
  log "waiting for NBB2 aggregate job ${NBB2_AGG_JOB_ID}"
  sleep "$POLL_SECONDS"
done

log "initial NBB2 aggregate complete; preparing OpenMM refinement recovery"
recovery_submission=$(ssh bxcpu "bash -s" <<EOF
set -euo pipefail
ROOT=$REMOTE_ROOT
BASE="\$ROOT/prestructure50k_v1/recovery_${NBB2_JOB_ID}"
mkdir -p "\$BASE/input" "\$ROOT/status"
if [[ ! -s "\$BASE/input/PREPARED.json" ]]; then
  "\$ROOT/env/bin/python" "\$ROOT/scripts/prepare_bxcpu_nbb2_recovery.py" \
    --campaign "\$ROOT/prestructure50k_v1" \
    --initial-job-id "$NBB2_JOB_ID" \
    --output "\$BASE/input"
fi
receipt="\$ROOT/status/NBB2_RECOVERY_SUBMITTED.json"
if [[ -s "\$receipt" ]]; then
  "\$ROOT/env/bin/python" - "\$receipt" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); print(x['recovery_job_id'],x['finalize_job_id'])
PY
  exit 0
fi
recovery=\$(sbatch --parsable --partition=amd_256q --chdir="\$ROOT/logs" \
  --export=ALL,PVRIG_BXCPU_ROOT="\$ROOT",INITIAL_JOB_ID=$NBB2_JOB_ID \
  "\$ROOT/scripts/run_bxcpu_nbb2_refine_recovery.slurm")
finalize=\$(sbatch --parsable --partition=amd_256q --dependency=afterok:\$recovery \
  --chdir="\$ROOT/logs" \
  --export=ALL,PVRIG_BXCPU_ROOT="\$ROOT",INITIAL_JOB_ID=$NBB2_JOB_ID,RECOVERY_JOB_ID=\$recovery \
  "\$ROOT/scripts/run_bxcpu_nbb2_recovery_finalize.slurm")
"\$ROOT/env/bin/python" - "\$receipt" "\$recovery" "\$finalize" <<'PY'
import json,sys,time
p,r,f=sys.argv[1:]
open(p,'w').write(json.dumps({'status':'SUBMITTED','recovery_job_id':r,'finalize_job_id':f,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
echo "\$recovery \$finalize"
EOF
)
read -r RECOVERY_JOB_ID RECOVERY_FINALIZE_JOB_ID <<<"$(printf '%s\n' "$recovery_submission" | tail -1)"
printf '%s\n' "$RECOVERY_JOB_ID" > "$LOCAL_ROOT/RECOVERY_JOB_ID"
printf '%s\n' "$RECOVERY_FINALIZE_JOB_ID" > "$LOCAL_ROOT/RECOVERY_FINALIZE_JOB_ID"
log "NBB2 recovery submitted/observed: array=$RECOVERY_JOB_ID finalize=$RECOVERY_FINALIZE_JOB_ID"

recovery_final="$REMOTE_ROOT/prestructure50k_v1/recovery_${NBB2_JOB_ID}/final_${RECOVERY_JOB_ID}"
while ! ssh bxcpu "test -s '$recovery_final/COMPLETE.json'"; do
  summary=$(ssh bxcpu "squeue -j '$RECOVERY_JOB_ID,$RECOVERY_FINALIZE_JOB_ID' -h -o '%i %t %M %R' 2>/dev/null | tr '\n' ';'" || true)
  log "waiting for NBB2 recovery: ${summary:-not in squeue}"
  sleep "$POLL_SECONDS"
done
mkdir -p "$LOCAL_ROOT/recovery"
rsync -a --partial "bxcpu:$recovery_final/" "$LOCAL_ROOT/recovery/"
(cd "$LOCAL_ROOT/recovery" && sha256sum -c SHA256SUMS)
log "NBB2 recovery package downloaded and verified"

tnp_submission=$(ssh bxcpu "bash -s" <<EOF
set -euo pipefail
ROOT=$REMOTE_ROOT
receipt="\$ROOT/status/TNP_PRESTRUCTURE50K_SUBMITTED.json"
if [[ -s "\$receipt" ]]; then
  "\$ROOT/env/bin/python" - "\$receipt" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); print(x['tnp_job_id'],x['aggregate_job_id'])
PY
  exit 0
fi
tnp=\$(sbatch --parsable --partition=amd_256q --chdir="\$ROOT/logs" \
  --export=ALL,PVRIG_BXCPU_ROOT="\$ROOT",NBB2_JOB_ID=$NBB2_JOB_ID,RECOVERY_JOB_ID=$RECOVERY_JOB_ID \
  "\$ROOT/scripts/run_bxcpu_tnp_prestructure50k.slurm")
agg=\$(sbatch --parsable --partition=amd_256q --dependency=afterok:\$tnp \
  --chdir="\$ROOT/logs" \
  --export=ALL,PVRIG_BXCPU_ROOT="\$ROOT",TNP_JOB_ID=\$tnp \
  "\$ROOT/scripts/run_bxcpu_tnp_prestructure50k_aggregate.slurm")
"\$ROOT/env/bin/python" - "\$receipt" "\$tnp" "\$agg" <<'PY'
import json,sys,time
p,t,a=sys.argv[1:]
open(p,'w').write(json.dumps({'status':'SUBMITTED','tnp_job_id':t,'aggregate_job_id':a,'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
echo "\$tnp \$agg"
EOF
)
read -r TNP_JOB_ID TNP_AGG_JOB_ID <<<"$(printf '%s\n' "$tnp_submission" | tail -1)"
printf '%s\n' "$TNP_JOB_ID" > "$LOCAL_ROOT/TNP_JOB_ID"
printf '%s\n' "$TNP_AGG_JOB_ID" > "$LOCAL_ROOT/TNP_AGG_JOB_ID"
log "TNP submitted/observed: array=$TNP_JOB_ID aggregate=$TNP_AGG_JOB_ID"

while ! ssh bxcpu "test -s '$REMOTE_ROOT/status/TNP_PRESTRUCTURE50K_COMPLETE.json'"; do
  summary=$(ssh bxcpu "squeue -j '$TNP_JOB_ID,$TNP_AGG_JOB_ID' -h -o '%i %t %M %R' 2>/dev/null | tr '\n' ';'" || true)
  log "waiting for TNP completion: ${summary:-not in squeue}"
  sleep "$POLL_SECONDS"
done

remote_agg="$REMOTE_ROOT/prestructure50k_v1/tnp_aggregated_${TNP_JOB_ID}"
mkdir -p "$LOCAL_ROOT/tnp_aggregate"
rsync -a --partial "bxcpu:$remote_agg/" "$LOCAL_ROOT/tnp_aggregate/"
(cd "$LOCAL_ROOT/tnp_aggregate" && sha256sum -c SHA256SUMS)
date -Is > "$LOCAL_ROOT/LOCAL_TRANSFER_COMPLETE"
log "TNP aggregate downloaded and checksum verified"

while true; do
  if timeout 30 "$NODE1_SSH" node1 \
      "mkdir -p '$NODE1_TARGET'" >/dev/null 2>&1 && \
     rsync -a --partial -e "$NODE1_SSH" "$LOCAL_ROOT/recovery/" "node1:$NODE1_TARGET/recovery/" && \
     rsync -a --partial -e "$NODE1_SSH" "$LOCAL_ROOT/tnp_aggregate/" "node1:$NODE1_TARGET/tnp_aggregate/" && \
     "$NODE1_SSH" node1 "cd '$NODE1_TARGET/recovery' && sha256sum -c SHA256SUMS && cd '$NODE1_TARGET/tnp_aggregate' && sha256sum -c SHA256SUMS"; then
    date -Is > "$LOCAL_ROOT/NODE1_SYNC_COMPLETE"
    log "recovery and TNP aggregates synchronized to Node1"
    break
  fi
  log "Node1 unavailable; retrying recovery/TNP sync"
  sleep 300
done
