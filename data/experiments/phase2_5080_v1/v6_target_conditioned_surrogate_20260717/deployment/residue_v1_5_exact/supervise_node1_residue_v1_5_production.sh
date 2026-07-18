#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=residue_v1_5_common.sh
source "$SCRIPT_DIR/residue_v1_5_common.sh"

if [[ "${1:-}" == --print-plan ]]; then
  cat <<'JSON'
{
  "bootstrap": {"repetitions": 1000, "seed": 20260718},
  "collector_after_fold_terminals": 5,
  "fail_closed": true,
  "gpu_assignment": {"1": [0, 4], "2": [1], "3": [2], "4": [3]},
  "gpu_zero": "FORBIDDEN",
  "lanes": ["F1_contact_low_frozen", "F4_contact_high_frozen", "F3_contact_low_rank_frozen", "L1_contact_low_lora"],
  "resume": true
}
JSON
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'usage: supervise_node1_residue_v1_5_production.sh [--print-plan]' >&2; exit 64; }

for gpu in 1 2 3 4; do assert_physical_gpu "$gpu"; done
verify_exact_code
verify_production_inputs
require_regular "$DEPLOY_ROOT/DEPLOYMENT_RECEIPT.json" deployment_receipt
require_regular "$REMOTE_ROOT/status/residue_v1_5_smoke93/terminal.json" smoke_terminal
"$PY" - "$DEPLOY_ROOT/DEPLOYMENT_RECEIPT.json" "$REMOTE_ROOT/status/residue_v1_5_smoke93/terminal.json" <<'PY'
import json,pathlib,sys
deploy=json.loads(pathlib.Path(sys.argv[1]).read_text()); smoke=json.loads(pathlib.Path(sys.argv[2]).read_text())
assert deploy['status']=='PASS_RESIDUE_V1_5_EXACT_DEPLOYMENT_NOT_LAUNCHED'
assert deploy['immutable_code_v1_5_touched'] is False and deploy['remote_jobs_launched'] is False
assert deploy['remote_test_count']==41 and deploy['remote_test_result']=='PASS'
assert deploy['remote_py_compile_result']=='PASS'
assert smoke['status']=='PASS_RESIDUE_V1_5_SMOKE93_TERMINAL'
PY
free_gb=$(free_data1_gb)
(( free_gb >= 180 )) || { echo "production_disk_preflight_below_180GB:$free_gb" >&2; exit 72; }

RUNTIME=$REMOTE_ROOT/runtime/residue_v1_5_production
STATUS_ROOT=$REMOTE_ROOT/status/residue_v1_5_production
GLOBAL_TERMINAL=$STATUS_ROOT/terminal.json
LOCK=$STATUS_ROOT/supervisor.lock
mkdir -p "$RUNTIME" "$STATUS_ROOT"
mkdir "$LOCK" 2>/dev/null || { echo "production_supervisor_already_active:$LOCK" >&2; exit 73; }
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
write_terminal "$STATUS_ROOT/status.json" RUNNING_RESIDUE_V1_5_PRODUCTION "pid=$$;lane_count=4;physical_gpus=1,2,3,4"

validate_fold_terminal() {
  local out=$1 expected_fold=$2
  "$PY" - "$out" "$expected_fold" "$FREEZE_SHA" <<'PY'
import hashlib,json,pathlib,sys
out=pathlib.Path(sys.argv[1]); fold=int(sys.argv[2]); freeze_sha=sys.argv[3]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
for name in ('RESULT.json','OUTER_EVALUATION_SEAL.json','contract.json','outer_test_predictions.tsv'):
    path=out/name; assert path.is_file() and not path.is_symlink(),name
result=json.loads((out/'RESULT.json').read_text()); seal=json.loads((out/'OUTER_EVALUATION_SEAL.json').read_text()); contract=json.loads((out/'contract.json').read_text())
assert result['schema_version']=='pvrig_v6_nested_residue_surrogate_v1_5_result'
assert result['status']=='PASS_OUTER_FOLD_COMPLETE' and result['outer_fold']==fold and result['outer_evaluation_count']==1
assert seal['schema_version']=='pvrig_v6_nested_residue_surrogate_v1_5_outer_evaluation_seal'
assert seal['status']=='SEALED_COMPLETE_ONE_EVALUATION' and seal['outer_fold']==fold and seal['result_sha256']==sha(out/'RESULT.json')
assert result['binding_hash']==seal['binding_hash']==contract['binding_hash']
assert contract['binding']['external_hashes']['implementation_freeze_sha256']==freeze_sha
assert result['artifacts']['outer_test_predictions.tsv']==sha(out/'outer_test_predictions.tsv')
PY
}

run_fold() {
  local lane=$1 fold=$2 gpu=$3 out status_dir free_gb rc
  assert_physical_gpu "$gpu"
  configure_lane "$lane"
  out=$RUNTIME/$lane/fold$fold
  status_dir=$STATUS_ROOT/$lane/fold$fold
  mkdir -p "$status_dir" "$(dirname "$out")"
  if [[ -f "$out/RESULT.json" ]]; then
    validate_fold_terminal "$out" "$fold"
    write_terminal "$status_dir/terminal.json" PASS_RESIDUE_V1_5_FOLD_TERMINAL "lane=$lane;fold=$fold;physical_gpu=$gpu;resumed_existing_terminal=true"
    return 0
  fi
  if [[ -f "$out/OUTER_EVALUATION_SEAL.json" ]]; then
    if grep -q 'SEALED_STARTED_NOT_REPEATABLE' "$out/OUTER_EVALUATION_SEAL.json"; then
      write_terminal "$status_dir/terminal.json" FAIL_RESIDUE_V1_5_OUTER_SEAL_INCOMPLETE "lane=$lane;fold=$fold;SEALED_STARTED_NOT_REPEATABLE"
      return 74
    fi
    write_terminal "$status_dir/terminal.json" FAIL_RESIDUE_V1_5_OUTER_SEAL_INVALID "lane=$lane;fold=$fold"
    return 74
  fi
  free_gb=$(free_data1_gb)
  if (( free_gb < 180 )); then
    write_terminal "$status_dir/terminal.json" SAFE_STOP_DISK_BELOW_CHECKPOINT_GUARD "lane=$lane;fold=$fold;free_gb=$free_gb"
    return 75
  fi
  cmd=("$PY" "$TRAINER"
    --training-tsv "$TRAIN" --contact-tsv-gz "$CONTACT" --contact-receipt "$CONTACT_RECEIPT" --contact-validation "$CONTACT_VALIDATION"
    --expected-training-sha256 "$TRAIN_SHA" --expected-contact-sha256 "$CONTACT_SHA"
    --output-dir "$out" --outer-fold "$fold" --resume
    --implementation-freeze "$FREEZE" --governance-amendment "$GOVERNANCE"
    --backbone-kind hf --model-path "$MODEL" --model-identity-file "$MODEL_IDENTITY" --expected-model-sha256 "$MODEL_SHA"
    --ridge-alpha 10.0 --precision bf16 --gradient-accumulation 2 --fusion-dim 64 --dropout 0.25 --residual-scale 0.02
    --dual-weight 1.0 --receptor-weight 0.35 --residual-weight 0.05 --huber-delta 0.02
    --max-epochs 8 --batch-size 8 --per-parent-batch 2 --head-learning-rate 0.0001 --weight-decay 0.02
    --warmup-steps 10 --gradient-clip 1.0 --safe-stop-free-gb 150 --checkpoint-min-free-gb 180 --seed 43 --device cuda:0
    "${LANE_ARGS[@]}")
  export CUDA_VISIBLE_DEVICES="$gpu"
  export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
  export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
  write_terminal "$status_dir/status.json" RUNNING_RESIDUE_V1_5_FOLD "lane=$lane;fold=$fold;physical_gpu=$gpu;pid=$BASHPID"
  set +e
  "${cmd[@]}" >"$status_dir/stdout.json.tmp" 2>"$status_dir/stderr.log"
  rc=$?
  set -e
  if (( rc != 0 )); then
    if grep -qE 'SAFE_STOP|safe_stop|checkpoint_guard' "$status_dir/stderr.log"; then
      write_terminal "$status_dir/terminal.json" SAFE_STOP_RESUMABLE_TRAINER "lane=$lane;fold=$fold;return_code=$rc"
      return 75
    fi
    write_terminal "$status_dir/terminal.json" FAIL_RESIDUE_V1_5_FOLD_TRAINER "lane=$lane;fold=$fold;return_code=$rc"
    return "$rc"
  fi
  mv "$status_dir/stdout.json.tmp" "$status_dir/stdout.json"
  validate_fold_terminal "$out" "$fold"
  write_terminal "$status_dir/terminal.json" PASS_RESIDUE_V1_5_FOLD_TERMINAL "lane=$lane;fold=$fold;physical_gpu=$gpu;result_sha256=$(sha256_file "$out/RESULT.json")"
}

run_gpu1_worker() {
  local lane=$1
  run_fold "$lane" 0 1 && run_fold "$lane" 4 1
}

validate_five_fold_terminals() {
  local lane=$1 fold terminal out
  for fold in 0 1 2 3 4; do
    terminal=$STATUS_ROOT/$lane/fold$fold/terminal.json
    require_regular "$terminal" "fold_${fold}_wrapper_terminal"
    grep -q 'PASS_RESIDUE_V1_5_FOLD_TERMINAL' "$terminal" || return 81
    out=$RUNTIME/$lane/fold$fold
    validate_fold_terminal "$out" "$fold"
  done
}

run_collector() {
  local lane=$1 output status_dir report rc
  output=$RUNTIME/$lane/oof
  status_dir=$STATUS_ROOT/$lane/collector
  report=$output/OOF_PROMOTION_REPORT.json
  mkdir -p "$status_dir"
  validate_five_fold_terminals "$lane"
  if [[ -f "$report" ]]; then
    "$PY" - "$report" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['schema_version']=='pvrig_v6_residue_v1_5_oof_collector'
assert x['status'] in {'PROMOTE_RESIDUE_V1_5_OVER_M2','DO_NOT_PROMOTE_RESIDUE_V1_5'}
assert x['bootstrap']['repetitions']==1000 and x['bootstrap']['seed']==20260718
assert x['collector_matrix']['bootstrap_repetitions']==1000 and x['collector_matrix']['bootstrap_seed']==20260718
assert x['candidate_count']==1507 and len(x['outer_runs'])==5
PY
    write_terminal "$status_dir/terminal.json" PASS_RESIDUE_V1_5_COLLECTOR_TERMINAL "lane=$lane;resumed_existing_terminal=true"
    return 0
  fi
  [[ ! -e "$output" && ! -L "$output" ]] || {
    write_terminal "$status_dir/terminal.json" FAIL_RESIDUE_V1_5_COLLECTOR_PARTIAL_OUTPUT "lane=$lane;output=$output"
    return 82
  }
  write_terminal "$status_dir/status.json" RUNNING_RESIDUE_V1_5_COLLECTOR "lane=$lane;fold_terminals=5"
  set +e
  "$PY" "$COLLECTOR" --training-tsv "$TRAIN" \
    --outer-run-dir "$RUNTIME/$lane/fold0" --outer-run-dir "$RUNTIME/$lane/fold1" \
    --outer-run-dir "$RUNTIME/$lane/fold2" --outer-run-dir "$RUNTIME/$lane/fold3" \
    --outer-run-dir "$RUNTIME/$lane/fold4" --output-dir "$output" \
    --implementation-freeze "$FREEZE" --governance-amendment "$GOVERNANCE" \
    --bootstrap-replicates 1000 --bootstrap-seed 20260718 \
    >"$status_dir/stdout.json.tmp" 2>"$status_dir/stderr.log"
  rc=$?
  set -e
  if (( rc != 0 )); then
    write_terminal "$status_dir/terminal.json" FAIL_RESIDUE_V1_5_COLLECTOR "lane=$lane;return_code=$rc"
    return "$rc"
  fi
  mv "$status_dir/stdout.json.tmp" "$status_dir/stdout.json"
  run_collector "$lane"
}

for lane in "${LANES[@]}"; do
  write_terminal "$STATUS_ROOT/$lane/status.json" RUNNING_RESIDUE_V1_5_LANE "lane=$lane"
  set +e
  run_gpu1_worker "$lane" & pid1=$!
  run_fold "$lane" 1 2 & pid2=$!
  run_fold "$lane" 2 3 & pid3=$!
  run_fold "$lane" 3 4 & pid4=$!
  rc1=0; rc2=0; rc3=0; rc4=0
  wait "$pid1" || rc1=$?
  wait "$pid2" || rc2=$?
  wait "$pid3" || rc3=$?
  wait "$pid4" || rc4=$?
  set -e
  if (( rc1 != 0 || rc2 != 0 || rc3 != 0 || rc4 != 0 )); then
    write_terminal "$STATUS_ROOT/$lane/terminal.json" FAIL_RESIDUE_V1_5_LANE "lane=$lane;gpu1_rc=$rc1;gpu2_rc=$rc2;gpu3_rc=$rc3;gpu4_rc=$rc4"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_PRODUCTION "lane=$lane;fold_worker_failure"
    exit 83
  fi
  if ! run_collector "$lane"; then
    write_terminal "$STATUS_ROOT/$lane/terminal.json" FAIL_RESIDUE_V1_5_LANE "lane=$lane;collector_failure"
    write_terminal "$GLOBAL_TERMINAL" FAIL_RESIDUE_V1_5_PRODUCTION "lane=$lane;collector_failure"
    exit 84
  fi
  write_terminal "$STATUS_ROOT/$lane/terminal.json" PASS_RESIDUE_V1_5_LANE_TERMINAL "lane=$lane;five_folds=true;collector=true"
done

write_terminal "$GLOBAL_TERMINAL" PASS_RESIDUE_V1_5_PRODUCTION_TERMINAL "lanes=4;fold_runs=20;collectors=4;gpu0_forbidden=true"
echo PASS_RESIDUE_V1_5_PRODUCTION_TERMINAL
