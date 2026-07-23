#!/usr/bin/env bash
set -euo pipefail

FINALIZATION_STATE="__V220_FINALIZATION_STATE__"
PACKAGE_ROOT="__V220_PACKAGE_ROOT__"
IMPLEMENTATION_FREEZE="__V220_IMPLEMENTATION_FREEZE__"
EXPECTED_IMPLEMENTATION_FREEZE_SHA="__V220_IMPLEMENTATION_FREEZE_SHA__"
PREREGISTRATION="__V220_PREREGISTRATION__"
EXPECTED_PREREGISTRATION_SHA="__V220_PREREGISTRATION_SHA__"
PREFLIGHT_RECEIPT="__V220_PREFLIGHT_RECEIPT__"
EXPECTED_PREFLIGHT_RECEIPT_SHA="__V220_PREFLIGHT_RECEIPT_SHA__"
APPROVAL_RECEIPT="__V220_APPROVAL_RECEIPT__"
EXPECTED_APPROVAL_RECEIPT_SHA="__V220_APPROVAL_RECEIPT_SHA__"
EXPECTED_HELPER_SHA="__V220_HELPER_SHA__"
EXPECTED_MATERIALIZER_SHA="__V220_MATERIALIZER_SHA__"
EXPECTED_ARM_RUNNER_SHA="__V220_ARM_RUNNER_SHA__"

[[ "$FINALIZATION_STATE" == "FINALIZED_V220_V1_3_4" ]] || {
  echo "training_template_not_finalized" >&2
  exit 86
}
for VALUE in "$PACKAGE_ROOT" "$EXPECTED_IMPLEMENTATION_FREEZE_SHA" "$EXPECTED_PREREGISTRATION_SHA" \
  "$EXPECTED_PREFLIGHT_RECEIPT_SHA" "$EXPECTED_APPROVAL_RECEIPT_SHA" "$EXPECTED_HELPER_SHA" \
  "$EXPECTED_MATERIALIZER_SHA" "$EXPECTED_ARM_RUNNER_SHA"; do
  [[ "$VALUE" != __*__ ]] || { echo "unresolved_training_template_placeholder" >&2; exit 86; }
done

FOLD_ID="${1:?usage: EXPECTED_FINAL_AUTH_SHA256=... CUDA_VISIBLE_DEVICES=N $0 FOLD_ID OUTPUT_ROOT}"
OUTPUT_ROOT="${2:?missing output root}"
EXPECTED_FINAL_AUTH_SHA256="${EXPECTED_FINAL_AUTH_SHA256:?must bind final authorization sha256}"
[[ "$FOLD_ID" =~ ^[0-4]$ ]] || { echo "invalid_fold_id:$FOLD_ID" >&2; exit 2; }
[[ "${CUDA_VISIBLE_DEVICES:-}" =~ ^[0-7]$ ]] || { echo "single_physical_gpu_required" >&2; exit 2; }
[[ "$EXPECTED_FINAL_AUTH_SHA256" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid_final_auth_sha256" >&2; exit 2; }

FINAL_AUTH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/FINAL_TRAINING_AUTHORIZATION_V1_3_4.json"
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HELPER="$PACKAGE_ROOT/launchers/run_shared_fold_materialization_once_v1_3_1.sh"
MATERIALIZER="$PACKAGE_ROOT/src/materialize_v220_shared_fold_calibration_v1_3_1.py"
ARM_RUNNER="$PACKAGE_ROOT/src/run_v220_contact_shared_fold_v1_3_1.py"
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
EXPECTED_UPSTREAM_RUNNER_SHA="da7a9e28dc818fc20fdaedf35b14da46e4db407c618bd5ce41e1db0ca8b22116"
EXPECTED_CALIBRATOR_SHA="b0b5e6719324fa8376bc33512c9e76805ef768ae1917081f8d2f83a6c9f858e8"
EXPECTED_PAIRED_INITIAL_STATE_SHA="9be8bd8572b297a2b075965775e04c2f066b2ca534738f6f3a8535fd97e988ec"
EXPECTED_CONTACT_TEACHER_STORE_SHA="cb6a20cfe752f237f6afb865bb1c2440b4f3b219634b7d8ca59800f2ec5f0953"
EXPECTED_INITIAL_STATE_SHA="3139cf661a7358ea89e508ac0d27f0810fc239e6f662e976e250f7029b45e807"
EXPECTED_INITIAL_RECEIPT_SHA="a3bd507edc70fbed2b62e64db82671a1e81849df3d203df1fc3256f705f9aa5f"
EXPECTED_V213_RUNNER_SHA="76f63369838995c10be0e7969ba36ae09fe9d0ed5d619ddbc233118d4d2a32a9"
EXPECTED_MODEL_SHA="a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"

# This complete authorization/hash gate runs before output-root creation,
# shared-lock creation, model construction, optimizer construction or training.
sha256sum -c <<SUMS
$EXPECTED_FINAL_AUTH_SHA256  $FINAL_AUTH
$EXPECTED_IMPLEMENTATION_FREEZE_SHA  $IMPLEMENTATION_FREEZE
$EXPECTED_PREREGISTRATION_SHA  $PREREGISTRATION
$EXPECTED_PREFLIGHT_RECEIPT_SHA  $PREFLIGHT_RECEIPT
$EXPECTED_APPROVAL_RECEIPT_SHA  $APPROVAL_RECEIPT
$EXPECTED_HELPER_SHA  $HELPER
$EXPECTED_MATERIALIZER_SHA  $MATERIALIZER
$EXPECTED_ARM_RUNNER_SHA  $ARM_RUNNER
$EXPECTED_UPSTREAM_RUNNER_SHA  $UPSTREAM_RUNNER
$EXPECTED_CALIBRATOR_SHA  $UPSTREAM_ROOT/src/calibrate_v220_contact_weight_v1.py
$EXPECTED_PAIRED_INITIAL_STATE_SHA  $UPSTREAM_ROOT/src/materialize_v220_paired_initial_state_v1.py
$EXPECTED_CONTACT_TEACHER_STORE_SHA  $UPSTREAM_ROOT/src/v220_contact_teacher_store_v1.py
$EXPECTED_INITIAL_STATE_SHA  $INITIAL_STATE
$EXPECTED_INITIAL_RECEIPT_SHA  $INITIAL_RECEIPT
$EXPECTED_V213_RUNNER_SHA  $V213/src/run_top5_clean_attention_fold_v1.py
$EXPECTED_MODEL_SHA  $MODEL/model.safetensors
SUMS

"$PYTHON_BIN" - "$SELF" "$FINAL_AUTH" "$EXPECTED_FINAL_AUTH_SHA256" \
  "$IMPLEMENTATION_FREEZE" "$EXPECTED_IMPLEMENTATION_FREEZE_SHA" \
  "$PREREGISTRATION" "$EXPECTED_PREREGISTRATION_SHA" \
  "$PREFLIGHT_RECEIPT" "$EXPECTED_PREFLIGHT_RECEIPT_SHA" \
  "$APPROVAL_RECEIPT" "$EXPECTED_APPROVAL_RECEIPT_SHA" <<'PY'
import hashlib,json,sys
sha=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()
self_path,auth_path,auth_sha,freeze_path,freeze_sha,prereg_path,prereg_sha,preflight_path,preflight_sha,approval_path,approval_sha=sys.argv[1:]
assert sha(auth_path)==auth_sha and sha(freeze_path)==freeze_sha and sha(prereg_path)==prereg_sha
assert sha(preflight_path)==preflight_sha and sha(approval_path)==approval_sha
auth=json.load(open(auth_path)); prereg=json.load(open(prereg_path)); preflight=json.load(open(preflight_path)); approval=json.load(open(approval_path))
assert prereg['authorization']['training_authorized'] is False
assert preflight['status']=='PASS_NODE1_V220_V1_3_4_FIVE_FOLD_SHARED_CALIBRATION_LOAD_ONLY_NO_TRAINING'
assert preflight['implementation_freeze']['sha256']==freeze_sha
assert preflight['preregistration']['sha256']==prereg_sha
for key in ('optimizer_created','backward_called','training_started','run_fold_core_called','training_output_created'):
    assert preflight[key] is False
assert preflight['optimizer_steps']==0 and preflight['fold_count']==5 and preflight['calibrator_invocations_total']==5
assert approval['status']=='APPROVE_V220_V1_3_4_TECHNICAL_RECOVERY_TRAINING'
assert approval['approved'] is True
assert approval['implementation_freeze_sha256']==freeze_sha
assert approval['preregistration_sha256']==prereg_sha
assert approval['preflight_receipt_sha256']==preflight_sha
assert auth['status']=='FINAL_AUTHORIZED_V220_V1_3_4_TEN_FRESH_ARMS'
assert auth['training_authorized'] is True and auth['training_started'] is False
assert auth['implementation_freeze_sha256']==freeze_sha and auth['preregistration_sha256']==prereg_sha
assert auth['preflight_receipt_sha256']==preflight_sha and auth['approval_receipt_sha256']==approval_sha
assert auth['training_launcher_sha256']==sha(self_path)
assert auth['all_ten_arms_fresh_required'] is True and auth['old_training_outputs_allowed'] is False
PY

TERMINAL="$OUTPUT_ROOT/fold_${FOLD_ID}_PAIR_TERMINAL.json"
SHARED_DIR="$OUTPUT_ROOT/shared_calibration/fold_${FOLD_ID}"
SHARED_ARTIFACT="$SHARED_DIR/CONTACT_WEIGHT_CALIBRATION.json"
[[ ! -e "$TERMINAL" && ! -e "$SHARED_DIR" ]] || { echo "fold_or_lock_exists" >&2; exit 72; }
for ARM in C0 C1; do
  [[ ! -e "$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" ]] || { echo "arm_output_exists:$ARM:$FOLD_ID" >&2; exit 72; }
done
mkdir -p "$OUTPUT_ROOT/logs"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"

"$HELPER" "$SHARED_DIR" -- \
  "$PYTHON_BIN" "$MATERIALIZER" \
    --upstream-v1-2-runner "$UPSTREAM_RUNNER" \
    --expected-upstream-v1-2-runner-sha256 "$EXPECTED_UPSTREAM_RUNNER_SHA" \
    --expected-calibrator-sha256 "$EXPECTED_CALIBRATOR_SHA" \
    --expected-paired-initial-state-sha256 "$EXPECTED_PAIRED_INITIAL_STATE_SHA" \
    --expected-contact-teacher-store-sha256 "$EXPECTED_CONTACT_TEACHER_STORE_SHA" \
    --shared-lock-dir "$SHARED_DIR" \
    --exact-once-helper "$HELPER" \
    --expected-exact-once-helper-sha256 "$EXPECTED_HELPER_SHA" \
    --shared-calibration-artifact "$SHARED_ARTIFACT" \
    --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" \
    --teacher-release "$PHASE0" --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
    --initial-state "$INITIAL_STATE" --initial-state-receipt "$INITIAL_RECEIPT" \
    --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" \
    --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
    --output-dir "$OUTPUT_ROOT/C1/fold_${FOLD_ID}" --arm C1 --fold-id "$FOLD_ID" \
    --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
    --device cuda:0 --seed 43 --epochs 8 --batch-size 8 --eval-batch-size 16 \
    --gradient-accumulation 4 --precision bf16 --learning-rate 0.0001 \
    --weight-decay 0.02 --gradient-clip 1.0 --graph-hidden-dim 128 --dropout 0.25 \
    --receptor-weight 1.0 --dual-weight 0.5 --huber-beta 0.03 --softmin-tau 0.02 \
    --top-weight-strength 3.0 --top-weight-center 0.85 --top-weight-scale 0.05 \
    --backbone-kind hf --backbone-dtype bf16 --model-path "$MODEL" \
    --model-identity-file "$MODEL/model.safetensors" --expected-model-sha256 "$EXPECTED_MODEL_SHA"

SHARED_SHA="$(sha256sum "$SHARED_ARTIFACT" | awk '{print $1}')"
if (( FOLD_ID % 2 == 0 )); then ARMS=(C0 C1); else ARMS=(C1 C0); fi
for ARM in "${ARMS[@]}"; do
  "$PYTHON_BIN" "$ARM_RUNNER" \
    --upstream-v1-2-runner "$UPSTREAM_RUNNER" --expected-upstream-v1-2-runner-sha256 "$EXPECTED_UPSTREAM_RUNNER_SHA" \
    --expected-calibrator-sha256 "$EXPECTED_CALIBRATOR_SHA" \
    --expected-paired-initial-state-sha256 "$EXPECTED_PAIRED_INITIAL_STATE_SHA" \
    --expected-contact-teacher-store-sha256 "$EXPECTED_CONTACT_TEACHER_STORE_SHA" \
    --exact-once-helper "$HELPER" --expected-exact-once-helper-sha256 "$EXPECTED_HELPER_SHA" \
    --shared-calibration-artifact "$SHARED_ARTIFACT" --expected-shared-calibration-sha256 "$SHARED_SHA" \
    --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" --teacher-release "$PHASE0" \
    --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
    --initial-state "$INITIAL_STATE" --initial-state-receipt "$INITIAL_RECEIPT" \
    --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
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
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest(); results={}
for arm in ('C0','C1'):
    base=root/arm/f'fold_{fold}'; result_path=base/'RESULT.json'; result=json.load(open(result_path))
    replay_path=base/'V1_3_1_SHARED_CALIBRATION_REPLAY_RECEIPT.json'; replay=json.load(open(replay_path))
    assert result['status']==f'PASS_V220_{arm}_CONTACT_SHARED_FOLD'
    assert result['arm']==arm and int(result['fold_id'])==fold and int(result['seed'])==43
    assert result['outputs']['CONTACT_WEIGHT_CALIBRATION.json']==shared_sha
    assert replay['status']=='PASS_V220_V1_3_1_ARM_USED_SHARED_CALIBRATION_NO_RECALIBRATION'
    assert replay['shared_artifact_sha256']==shared_sha and replay['arm_side_true_calibrator_invocations']==0
    results[arm]={'result_path':str(result_path),'result_sha256':sha(result_path),'prediction_sha256':result['outputs']['fold_predictions.tsv'],'checkpoint_sha256':result['outputs']['fold_checkpoint.pt'],'calibration_sha256':result['outputs']['CONTACT_WEIGHT_CALIBRATION.json'],'replay_receipt_path':str(replay_path),'replay_receipt_sha256':sha(replay_path)}
assert results['C0']['calibration_sha256']==results['C1']['calibration_sha256']==shared_sha
payload={'schema_version':'pvrig_v220_phase1_core_fold_pair_terminal_v1_3_4','status':'PASS_V220_V1_3_4_C0_C1_FOLD_PAIR','fold_id':fold,'seed':43,'physical_gpu_at_launch':gpu,'shared_calibration_sha256':shared_sha,'results':results}
target=root/f'fold_{fold}_PAIR_TERMINAL.json'; fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
try:
    with os.fdopen(fd,'w') as h: json.dump(payload,h,indent=2,sort_keys=True); h.write('\n'); h.flush(); os.fsync(h.fileno())
    os.replace(tmp,target)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
print(json.dumps({'status':payload['status'],'fold_id':fold},sort_keys=True))
PY
