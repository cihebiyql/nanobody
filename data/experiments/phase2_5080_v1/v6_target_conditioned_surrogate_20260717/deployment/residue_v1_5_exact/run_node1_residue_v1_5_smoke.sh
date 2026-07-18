#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=residue_v1_5_common.sh
source "$SCRIPT_DIR/residue_v1_5_common.sh"

if [[ "${1:-}" == --print-plan ]]; then
  cat <<'JSON'
{
  "claim_boundary": "mechanical smoke only; not model selection or biological evidence",
  "lanes": ["F1_contact_low_frozen", "F4_contact_high_frozen", "F3_contact_low_rank_frozen", "L1_contact_low_lora"],
  "max_epochs": 1,
  "physical_gpu": 1,
  "resume_replay": true
}
JSON
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'usage: run_node1_residue_v1_5_smoke.sh [--print-plan]' >&2; exit 64; }

assert_physical_gpu 1
verify_exact_code
verify_smoke_inputs
free_gb=$(free_data1_gb)
(( free_gb >= 180 )) || { echo "smoke_disk_preflight_below_180GB:$free_gb" >&2; exit 72; }

RUNTIME=$REMOTE_ROOT/runtime/residue_v1_5_smoke93
STATUS_ROOT=$REMOTE_ROOT/status/residue_v1_5_smoke93
GLOBAL_TERMINAL=$STATUS_ROOT/terminal.json
LOCK=$STATUS_ROOT/supervisor.lock
CHECKPOINT_AUDITOR=$SCRIPT_DIR/validate_residue_v1_5_smoke_checkpoint.py
mkdir -p "$RUNTIME" "$STATUS_ROOT"
mkdir "$LOCK" 2>/dev/null || { echo "smoke_supervisor_already_active:$LOCK" >&2; exit 73; }
require_regular "$CHECKPOINT_AUDITOR" checkpoint_auditor
ACTIVE_MONITOR_PID=
cleanup_smoke() {
  if [[ -n "${ACTIVE_MONITOR_PID:-}" ]]; then
    kill "$ACTIVE_MONITOR_PID" 2>/dev/null || true
    wait "$ACTIVE_MONITOR_PID" 2>/dev/null || true
  fi
  rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup_smoke EXIT
write_terminal "$STATUS_ROOT/status.json" RUNNING_RESIDUE_V1_5_SMOKE93 "pid=$$;physical_gpu=1"

validate_smoke_terminal() {
  local out=$1 expected_fold=$2 mode=$3 status_dir=$4
  "$PY" - "$out" "$expected_fold" <<'PY'
import hashlib,json,pathlib,sys
out=pathlib.Path(sys.argv[1]); fold=int(sys.argv[2]); sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
result=json.loads((out/'RESULT.json').read_text()); seal=json.loads((out/'OUTER_EVALUATION_SEAL.json').read_text()); contract=json.loads((out/'contract.json').read_text())
assert result['schema_version']=='pvrig_v6_nested_residue_surrogate_v1_5_result'
assert result['status']=='PASS_OUTER_FOLD_COMPLETE' and result['outer_fold']==fold and result['outer_evaluation_count']==1
assert seal['status']=='SEALED_COMPLETE_ONE_EVALUATION' and seal['result_sha256']==sha(out/'RESULT.json')
assert result['binding_hash']==seal['binding_hash']==contract['binding_hash']
PY
  "$PY" "$CHECKPOINT_AUDITOR" \
    --output-dir "$out" --mode "$mode" \
    --gpu-memory-csv "$status_dir/gpu_memory_mib.csv" \
    --audit-json "$status_dir/checkpoint_audit.json" \
    >"$status_dir/checkpoint_audit.stdout.json.tmp"
  mv "$status_dir/checkpoint_audit.stdout.json.tmp" "$status_dir/checkpoint_audit.stdout.json"
}

monitor_gpu_memory() {
  local path=$1 physical_gpu=$2 value timestamp
  printf 'timestamp_utc,memory_used_mib\n' >"$path.tmp"
  mv "$path.tmp" "$path"
  while true; do
    value=$(nvidia-smi --id="$physical_gpu" --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d '[:space:]') || return 1
    [[ "$value" =~ ^[0-9]+$ ]] || return 1
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    printf '%s,%s\n' "$timestamp" "$value" >>"$path"
    sleep 2
  done
}

stop_gpu_monitor() {
  local require_alive=${1:-false} was_alive=false
  if [[ -n "${ACTIVE_MONITOR_PID:-}" ]]; then
    if kill -0 "$ACTIVE_MONITOR_PID" 2>/dev/null; then was_alive=true; fi
    kill "$ACTIVE_MONITOR_PID" 2>/dev/null || true
    wait "$ACTIVE_MONITOR_PID" 2>/dev/null || true
    ACTIVE_MONITOR_PID=
  fi
  if [[ "$require_alive" == true && "$was_alive" != true ]]; then
    return 1
  fi
}

checkpoint_detail() {
  "$PY" - "$1" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['status']=='PASS_ADAPTER_ONLY_CHECKPOINT_AUDIT'
print(f"checkpoint_count={x['checkpoint_count']};checkpoint_total_bytes={x['checkpoint_total_bytes']};peak_gpu_memory_mib={x['peak_gpu_memory_mib']}")
PY
}

for lane in "${LANES[@]}"; do
  configure_lane "$lane"
  out=$RUNTIME/$lane/fold0
  lane_status=$STATUS_ROOT/$lane
  if [[ "$lane" == L1_contact_low_lora ]]; then checkpoint_mode=lora; else checkpoint_mode=frozen; fi
  mkdir -p "$lane_status"
  if [[ -f "$out/RESULT.json" ]]; then
    if ! validate_smoke_terminal "$out" 0 "$checkpoint_mode" "$lane_status"; then
      write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_CHECKPOINT_AUDIT "lane=$lane;resumed_existing_terminal=true"
      write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;checkpoint_audit_failed"
      exit 77
    fi
    detail=$(checkpoint_detail "$lane_status/checkpoint_audit.json")
    write_terminal "$lane_status/terminal.json" PASS_RESIDUE_V1_5_SMOKE_LANE_TERMINAL "lane=$lane;resumed_existing_terminal=true;$detail"
    continue
  fi
  if [[ -f "$out/OUTER_EVALUATION_SEAL.json" ]]; then
    write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_OUTER_SEAL_INCOMPLETE "lane=$lane"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;outer_seal_incomplete"
    exit 74
  fi
  free_gb=$(free_data1_gb)
  if (( free_gb < 180 )); then
    write_terminal "$lane_status/terminal.json" SAFE_STOP_DISK_BELOW_CHECKPOINT_GUARD "lane=$lane;free_gb=$free_gb"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;disk_safe_stop"
    exit 75
  fi
  cmd=("$PY" "$TRAINER"
    --training-tsv "$SMOKE_TRAIN" --contact-tsv-gz "$SMOKE_CONTACT" --contact-receipt "$SMOKE_CONTACT_RECEIPT"
    --output-dir "$out" --outer-fold 0 --smoke-mode --resume
    --implementation-freeze "$FREEZE" --governance-amendment "$GOVERNANCE"
    --backbone-kind hf --model-path "$MODEL" --model-identity-file "$MODEL_IDENTITY" --expected-model-sha256 "$MODEL_SHA"
    --ridge-alpha 10.0 --precision bf16 --gradient-accumulation 2 --fusion-dim 64 --dropout 0.25 --residual-scale 0.02
    --dual-weight 1.0 --receptor-weight 0.35 --residual-weight 0.05 --huber-delta 0.02
    --max-epochs 1 --batch-size 8 --per-parent-batch 2 --head-learning-rate 0.0001 --weight-decay 0.02
    --warmup-steps 0 --gradient-clip 1.0 --safe-stop-free-gb 150 --checkpoint-min-free-gb 180 --seed 43 --device cuda:0
    "${LANE_ARGS[@]}")
  export CUDA_VISIBLE_DEVICES=1
  export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
  export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
  write_terminal "$lane_status/status.json" RUNNING_RESIDUE_V1_5_SMOKE_LANE "lane=$lane;physical_gpu=1"
  monitor_gpu_memory "$lane_status/gpu_memory_mib.csv" 1 &
  ACTIVE_MONITOR_PID=$!
  set +e
  "${cmd[@]}" >"$lane_status/stdout.first.json.tmp" 2>"$lane_status/stderr.first.log"
  rc=$?
  set -e
  if (( rc != 0 )); then
    stop_gpu_monitor false
    write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_LANE "lane=$lane;return_code=$rc"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;return_code=$rc"
    exit "$rc"
  fi
  mv "$lane_status/stdout.first.json.tmp" "$lane_status/stdout.first.json"
  before=$(sha256_file "$out/RESULT.json")
  set +e
  "${cmd[@]}" >"$lane_status/stdout.resume.json.tmp" 2>"$lane_status/stderr.resume.log"
  rc=$?
  set -e
  if ! stop_gpu_monitor true; then
    write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_GPU_MONITOR "lane=$lane;monitor_not_alive_at_terminal"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;gpu_monitor_failed"
    exit 78
  fi
  if (( rc != 0 )); then
    write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_RESUME_REPLAY "lane=$lane;return_code=$rc"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;resume_return_code=$rc"
    exit "$rc"
  fi
  mv "$lane_status/stdout.resume.json.tmp" "$lane_status/stdout.resume.json"
  after=$(sha256_file "$out/RESULT.json")
  [[ "$before" == "$after" ]] || {
    write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_RESUME_MUTATED_RESULT "lane=$lane"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;resume_mutated_result"
    exit 76
  }
  if ! validate_smoke_terminal "$out" 0 "$checkpoint_mode" "$lane_status"; then
    write_terminal "$lane_status/terminal.json" FAIL_RESIDUE_V1_5_SMOKE_CHECKPOINT_AUDIT "lane=$lane"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_SMOKE "lane=$lane;checkpoint_audit_failed"
    exit 77
  fi
  detail=$(checkpoint_detail "$lane_status/checkpoint_audit.json")
  write_terminal "$lane_status/terminal.json" PASS_RESIDUE_V1_5_SMOKE_LANE_TERMINAL "lane=$lane;result_sha256=$after;resume_result_unchanged=true;$detail"
done

write_terminal "$GLOBAL_TERMINAL" PASS_RESIDUE_V1_5_SMOKE93_TERMINAL "lanes=4;physical_gpu=1;remote_jobs=mechanical_smoke_only"
echo PASS_RESIDUE_V1_5_SMOKE93_TERMINAL
