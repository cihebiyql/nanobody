#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FOLD_ID="${1:?usage: CUDA_VISIBLE_DEVICES=N $0 FOLD_ID OUTPUT_ROOT}"
OUTPUT_ROOT="${2:?usage: CUDA_VISIBLE_DEVICES=N $0 FOLD_ID OUTPUT_ROOT}"

[[ "$FOLD_ID" =~ ^[0-4]$ ]] || { echo "invalid_fold_id:$FOLD_ID" >&2; exit 2; }
[[ "${CUDA_VISIBLE_DEVICES:-}" =~ ^[0-7]$ ]] || {
  echo "CUDA_VISIBLE_DEVICES_must_bind_exactly_one_physical_GPU_0_to_7" >&2
  exit 2
}

PYTHON_BIN="/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
PREP="/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared"
V213="/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722"
PHASE0="/data1/qlyu/projects/pvrig_v2_20_phase0_train_contact_teacher_v1_20260723/release/train_contact_teacher_v1_2"
MODEL="/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c"
PREFLIGHT="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_2_20260723/pretraining_v1_2"
UPSTREAM_ROOT="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_2_20260723/layout_v1/v6_target_conditioned_surrogate_20260717/v2_20_contact_shared_top5_challenger_v1_2_20260723"
UPSTREAM_RUNNER="$UPSTREAM_ROOT/src/run_v220_contact_shared_fold_v1.py"
INITIAL_STATE="$PREFLIGHT/V220_PHASE1_SEED43_HEAD_STATE.bin"
INITIAL_RECEIPT="$PREFLIGHT/V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json"

EXPECTED_PREREG_SHA="16e2b808da07b81d2744f50d4ef3658f0245c79641b19130c5b0f3cd82d4b652"
EXPECTED_IMPLEMENTATION_FREEZE_SHA="9468b6124b1bcd858b484e0a4ddfa4fe9ac595682d7697bee96be3d2f2f65819"
EXPECTED_SHARED_MODULE_SHA="2bf29d87ee82bea984dff4d01495b787b9feb4adcd11b22e4bd6d504cdf5d84e"
EXPECTED_MATERIALIZER_SHA="bb3ac28c26e164fd7a1c1415ea911f8de2d886c0446dfaec99911ed0074fb3e1"
EXPECTED_ARM_RUNNER_SHA="8c1457c049704462bf3eba3e853561010c894a9f19b9bf1e4f8fa2f60e1e30f1"
EXPECTED_UPSTREAM_RUNNER_SHA="da7a9e28dc818fc20fdaedf35b14da46e4db407c618bd5ce41e1db0ca8b22116"
EXPECTED_PRETRAINING_TERMINAL_SHA="8e568bf30bc3c942a716b8748030e80475fc2f57401fb61a1103cdb13f6fb7a9"
EXPECTED_CROSS_PROCESS_TERMINAL_SHA="de1fe107afa0609bd9795bf1ebcba81778b12b9f1acd7ea86471b4506be7824a"
EXPECTED_INITIAL_STATE_SHA="3139cf661a7358ea89e508ac0d27f0810fc239e6f662e976e250f7029b45e807"
EXPECTED_INITIAL_RECEIPT_SHA="a3bd507edc70fbed2b62e64db82671a1e81849df3d203df1fc3256f705f9aa5f"
EXPECTED_V213_RUNNER_SHA="76f63369838995c10be0e7969ba36ae09fe9d0ed5d619ddbc233118d4d2a32a9"
EXPECTED_MODEL_SHA="a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"

sha256sum -c <<SUMS
$EXPECTED_PREREG_SHA  $ROOT/PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3.json
$EXPECTED_IMPLEMENTATION_FREEZE_SHA  $ROOT/IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3.json
$EXPECTED_SHARED_MODULE_SHA  $ROOT/src/v220_shared_calibration_artifact_v1.py
$EXPECTED_MATERIALIZER_SHA  $ROOT/src/materialize_v220_shared_fold_calibration_v1_3.py
$EXPECTED_ARM_RUNNER_SHA  $ROOT/src/run_v220_contact_shared_fold_v1_3.py
$EXPECTED_UPSTREAM_RUNNER_SHA  $UPSTREAM_RUNNER
$EXPECTED_PRETRAINING_TERMINAL_SHA  $PREFLIGHT/PRETRAINING_TERMINAL.json
$EXPECTED_CROSS_PROCESS_TERMINAL_SHA  $PREFLIGHT/CROSS_PROCESS_INITIAL_STATE_TERMINAL.json
$EXPECTED_INITIAL_STATE_SHA  $INITIAL_STATE
$EXPECTED_INITIAL_RECEIPT_SHA  $INITIAL_RECEIPT
$EXPECTED_V213_RUNNER_SHA  $V213/src/run_top5_clean_attention_fold_v1.py
$EXPECTED_MODEL_SHA  $MODEL/model.safetensors
SUMS

"$PYTHON_BIN" - "$ROOT/PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3.json" \
  "$ROOT/IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3.json" <<'PY'
import json,sys
prereg=json.load(open(sys.argv[1])); freeze=json.load(open(sys.argv[2]))
assert prereg['status']=='FROZEN_V1_3_TECHNICAL_RECOVERY_PENDING_INDEPENDENT_REVIEW'
assert prereg['authorization']['training_authorized'] is False
assert prereg['non_interference']['all_ten_arms_must_rerun'] is True
assert prereg['non_interference']['v1_2_checkpoint_history_prediction_or_calibration_input'] is False
assert freeze['status']=='FROZEN_V1_3_IMPLEMENTATION_PENDING_INDEPENDENT_REVIEW_AND_NODE1_PREFLIGHT'
assert freeze['training_started'] is False
PY

mkdir -p "$OUTPUT_ROOT/logs" "$OUTPUT_ROOT/shared_calibration"
TERMINAL="$OUTPUT_ROOT/fold_${FOLD_ID}_PAIR_TERMINAL.json"
SHARED_DIR="$OUTPUT_ROOT/shared_calibration/fold_${FOLD_ID}"
SHARED_ARTIFACT="$SHARED_DIR/CONTACT_WEIGHT_CALIBRATION.json"
MATERIALIZATION_TERMINAL="$SHARED_DIR/MATERIALIZATION_TERMINAL.json"
[[ ! -e "$TERMINAL" ]] || { echo "terminal_exists:$TERMINAL" >&2; exit 2; }
[[ ! -e "$SHARED_DIR" ]] || { echo "shared_calibration_exists:$SHARED_DIR" >&2; exit 2; }
for ARM in C0 C1; do
  [[ ! -e "$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" ]] || {
    echo "fold_output_exists:$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" >&2
    exit 2
  }
done

export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"

"$PYTHON_BIN" "$ROOT/src/materialize_v220_shared_fold_calibration_v1_3.py" \
  --upstream-v1-2-runner "$UPSTREAM_RUNNER" \
  --expected-upstream-v1-2-runner-sha256 "$EXPECTED_UPSTREAM_RUNNER_SHA" \
  --shared-calibration-artifact "$SHARED_ARTIFACT" \
  --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" \
  --teacher-release "$PHASE0" \
  --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
  --initial-state "$INITIAL_STATE" \
  --initial-state-receipt "$INITIAL_RECEIPT" \
  --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" \
  --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
  --output-dir "$OUTPUT_ROOT/C1/fold_${FOLD_ID}" \
  --arm C1 --fold-id "$FOLD_ID" \
  --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
  --device cuda:0 --seed 43 --epochs 8 --batch-size 8 --eval-batch-size 16 \
  --gradient-accumulation 4 --precision bf16 --learning-rate 0.0001 \
  --weight-decay 0.02 --gradient-clip 1.0 --graph-hidden-dim 128 --dropout 0.25 \
  --receptor-weight 1.0 --dual-weight 0.5 --huber-beta 0.03 --softmin-tau 0.02 \
  --top-weight-strength 3.0 --top-weight-center 0.85 --top-weight-scale 0.05 \
  --backbone-kind hf --backbone-dtype bf16 --model-path "$MODEL" \
  --model-identity-file "$MODEL/model.safetensors" --expected-model-sha256 "$EXPECTED_MODEL_SHA" \
  > "$MATERIALIZATION_TERMINAL" 2> "$OUTPUT_ROOT/logs/shared_calibration_fold_${FOLD_ID}.log"

SHARED_SHA="$(sha256sum "$SHARED_ARTIFACT" | awk '{print $1}')"
"$PYTHON_BIN" - "$MATERIALIZATION_TERMINAL" "$SHARED_ARTIFACT" "$SHARED_SHA" "$FOLD_ID" <<'PY'
import hashlib,json,sys
terminal=json.load(open(sys.argv[1])); artifact=json.load(open(sys.argv[2])); digest=hashlib.sha256(open(sys.argv[2],'rb').read()).hexdigest()
assert terminal['status']=='PASS_V220_SHARED_FOLD_CALIBRATION_MATERIALIZED_NO_TRAINING'
assert int(terminal['fold_id'])==int(sys.argv[4]) and terminal['seed']==43
assert terminal['shared_calibration_sha256']==sys.argv[3]==digest
assert terminal['calibrator_invocations']==1
assert terminal['optimizer_created'] is False and terminal['optimizer_steps']==0
assert terminal['backward_called'] is False and terminal['training_started'] is False
assert artifact['shared_artifact_status']=='PASS_V220_SHARED_FOLD_CALIBRATION_MATERIALIZED_NO_TRAINING'
assert artifact['calibrator_invocations']==1 and artifact['optimizer_created'] is False
PY

if (( FOLD_ID % 2 == 0 )); then ARMS=(C0 C1); else ARMS=(C1 C0); fi
for ARM in "${ARMS[@]}"; do
  "$PYTHON_BIN" "$ROOT/src/run_v220_contact_shared_fold_v1_3.py" \
    --upstream-v1-2-runner "$UPSTREAM_RUNNER" \
    --expected-upstream-v1-2-runner-sha256 "$EXPECTED_UPSTREAM_RUNNER_SHA" \
    --shared-calibration-artifact "$SHARED_ARTIFACT" \
    --expected-shared-calibration-sha256 "$SHARED_SHA" \
    --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" \
    --teacher-release "$PHASE0" --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
    --initial-state "$INITIAL_STATE" --initial-state-receipt "$INITIAL_RECEIPT" \
    --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" \
    --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
    --output-dir "$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" --arm "$ARM" --fold-id "$FOLD_ID" \
    --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
    --device cuda:0 --seed 43 --epochs 8 --batch-size 8 --eval-batch-size 16 \
    --gradient-accumulation 4 --precision bf16 --learning-rate 0.0001 \
    --weight-decay 0.02 --gradient-clip 1.0 --graph-hidden-dim 128 --dropout 0.25 \
    --receptor-weight 1.0 --dual-weight 0.5 --huber-beta 0.03 --softmin-tau 0.02 \
    --top-weight-strength 3.0 --top-weight-center 0.85 --top-weight-scale 0.05 \
    --backbone-kind hf --backbone-dtype bf16 --model-path "$MODEL" \
    --model-identity-file "$MODEL/model.safetensors" --expected-model-sha256 "$EXPECTED_MODEL_SHA" \
    > "$OUTPUT_ROOT/logs/${ARM}_fold_${FOLD_ID}.log" 2>&1
done

"$PYTHON_BIN" - "$OUTPUT_ROOT" "$FOLD_ID" "$CUDA_VISIBLE_DEVICES" "$SHARED_SHA" <<'PY'
import hashlib,json,os,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]); fold=int(sys.argv[2]); gpu=sys.argv[3]; shared_sha=sys.argv[4]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(); results={}
for arm in ('C0','C1'):
    base=root/arm/f'fold_{fold}'; result_path=base/'RESULT.json'; result=json.load(open(result_path))
    replay_path=base/'V1_3_SHARED_CALIBRATION_REPLAY_RECEIPT.json'; replay=json.load(open(replay_path))
    assert result['status']==f'PASS_V220_{arm}_CONTACT_SHARED_FOLD'
    assert result['arm']==arm and int(result['fold_id'])==fold and int(result['seed'])==43
    assert result['outputs']['CONTACT_WEIGHT_CALIBRATION.json']==shared_sha
    assert replay['status']=='PASS_V220_V1_3_ARM_USED_SHARED_CALIBRATION_NO_RECALIBRATION'
    assert replay['shared_artifact_sha256']==shared_sha and replay['arm_side_true_calibrator_invocations']==0
    results[arm]={'result_path':str(result_path),'result_sha256':sha(result_path),'prediction_sha256':result['outputs']['fold_predictions.tsv'],'checkpoint_sha256':result['outputs']['fold_checkpoint.pt'],'calibration_sha256':result['outputs']['CONTACT_WEIGHT_CALIBRATION.json'],'replay_receipt_path':str(replay_path),'replay_receipt_sha256':sha(replay_path)}
assert results['C0']['calibration_sha256']==results['C1']['calibration_sha256']==shared_sha
payload={'schema_version':'pvrig_v220_phase1_core_fold_pair_terminal_v1_3','status':'PASS_V220_V1_3_C0_C1_FOLD_PAIR','fold_id':fold,'seed':43,'physical_gpu_at_launch':gpu,'shared_calibration_sha256':shared_sha,'results':results}
target=root/f'fold_{fold}_PAIR_TERMINAL.json'; fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
try:
    with os.fdopen(fd,'w') as handle: json.dump(payload,handle,indent=2,sort_keys=True); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp,target)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
print(json.dumps({'status':payload['status'],'fold_id':fold},sort_keys=True))
PY
