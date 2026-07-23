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
INITIAL_STATE="$PREFLIGHT/V220_PHASE1_SEED43_HEAD_STATE.bin"
INITIAL_RECEIPT="$PREFLIGHT/V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json"

EXPECTED_PREREG_SHA="3a42b7a53d599413085255c67d4fab84014d25abeeb3c8bd28bbf5be7341c07c"
EXPECTED_PREFLIGHT_FREEZE_SHA="02bbd9011ed0ee38128b3cd704a9b4c1d737147c6dfca932b00d2ac60286d4a8"
EXPECTED_NODE1_PREFLIGHT_RECEIPT_SHA="ea6c218f3e0f14ffbdd1f2dcbf27190b1859b2d17da02ef6f89b8397b8c97455"
EXPECTED_PRETRAINING_TERMINAL_SHA="8e568bf30bc3c942a716b8748030e80475fc2f57401fb61a1103cdb13f6fb7a9"
EXPECTED_CROSS_PROCESS_TERMINAL_SHA="de1fe107afa0609bd9795bf1ebcba81778b12b9f1acd7ea86471b4506be7824a"
EXPECTED_INITIAL_STATE_SHA="3139cf661a7358ea89e508ac0d27f0810fc239e6f662e976e250f7029b45e807"
EXPECTED_INITIAL_RECEIPT_SHA="a3bd507edc70fbed2b62e64db82671a1e81849df3d203df1fc3256f705f9aa5f"
EXPECTED_RUNNER_SHA="da7a9e28dc818fc20fdaedf35b14da46e4db407c618bd5ce41e1db0ca8b22116"
EXPECTED_V213_RUNNER_SHA="76f63369838995c10be0e7969ba36ae09fe9d0ed5d619ddbc233118d4d2a32a9"
EXPECTED_MODEL_SHA="a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"

sha256sum -c <<SUMS
$EXPECTED_PREREG_SHA  $ROOT/PREREGISTRATION_PHASE1_CORE_V1_2.json
$EXPECTED_PREFLIGHT_FREEZE_SHA  $ROOT/IMPLEMENTATION_FREEZE_PHASE1_PREFLIGHT_V1_2.json
$EXPECTED_NODE1_PREFLIGHT_RECEIPT_SHA  $ROOT/audits/NODE1_PHASE1_PREFLIGHT_V1_2_RECEIPT.json
$EXPECTED_PRETRAINING_TERMINAL_SHA  $PREFLIGHT/PRETRAINING_TERMINAL.json
$EXPECTED_CROSS_PROCESS_TERMINAL_SHA  $PREFLIGHT/CROSS_PROCESS_INITIAL_STATE_TERMINAL.json
$EXPECTED_INITIAL_STATE_SHA  $INITIAL_STATE
$EXPECTED_INITIAL_RECEIPT_SHA  $INITIAL_RECEIPT
$EXPECTED_RUNNER_SHA  $ROOT/src/run_v220_contact_shared_fold_v1.py
$EXPECTED_V213_RUNNER_SHA  $V213/src/run_top5_clean_attention_fold_v1.py
$EXPECTED_MODEL_SHA  $MODEL/model.safetensors
SUMS

"$PYTHON_BIN" - "$PREFLIGHT/PRETRAINING_TERMINAL.json" "$PREFLIGHT/CROSS_PROCESS_INITIAL_STATE_TERMINAL.json" "$ROOT/audits/NODE1_PHASE1_PREFLIGHT_V1_2_RECEIPT.json" <<'PY'
import json,sys
pretraining=json.load(open(sys.argv[1]))
cross=json.load(open(sys.argv[2]))
receipt=json.load(open(sys.argv[3]))
assert pretraining['status']=='PASS_B0_REPLAY_AND_INITIAL_STATE_MATERIALIZATION_NO_TRAINING'
assert pretraining['training_started'] is False
assert cross['status']=='PASS_V220_CROSS_PROCESS_INITIAL_STATE_AND_BACKBONE_BINDING'
assert cross['optimizer_created'] is False and cross['optimizer_steps']==0
assert cross['backward_called'] is False and cross['training_started'] is False
assert receipt['status']=='PASS_NODE1_102_TESTS_B0_NEW_INITIAL_AND_CROSS_PROCESS_LOAD_NO_TRAINING'
assert receipt['initial_state_contract']['training_started'] is False
PY

mkdir -p "$OUTPUT_ROOT/C0" "$OUTPUT_ROOT/C1" "$OUTPUT_ROOT/logs"
TERMINAL="$OUTPUT_ROOT/fold_${FOLD_ID}_PAIR_TERMINAL.json"
[[ ! -e "$TERMINAL" ]] || { echo "terminal_exists:$TERMINAL" >&2; exit 2; }
for ARM in C0 C1; do
  [[ ! -e "$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" ]] || {
    echo "fold_output_exists:$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" >&2
    exit 2
  }
done

if (( FOLD_ID % 2 == 0 )); then
  ARMS=(C0 C1)
else
  ARMS=(C1 C0)
fi

export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"

for ARM in "${ARMS[@]}"; do
  "$PYTHON_BIN" "$ROOT/src/run_v220_contact_shared_fold_v1.py" \
    --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" \
    --teacher-release "$PHASE0" \
    --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
    --initial-state "$INITIAL_STATE" \
    --initial-state-receipt "$INITIAL_RECEIPT" \
    --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" \
    --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
    --output-dir "$OUTPUT_ROOT/$ARM/fold_${FOLD_ID}" \
    --arm "$ARM" \
    --fold-id "$FOLD_ID" \
    --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
    --device cuda:0 \
    --seed 43 \
    --epochs 8 \
    --batch-size 8 \
    --eval-batch-size 16 \
    --gradient-accumulation 4 \
    --precision bf16 \
    --learning-rate 0.0001 \
    --weight-decay 0.02 \
    --gradient-clip 1.0 \
    --graph-hidden-dim 128 \
    --dropout 0.25 \
    --receptor-weight 1.0 \
    --dual-weight 0.5 \
    --huber-beta 0.03 \
    --softmin-tau 0.02 \
    --top-weight-strength 3.0 \
    --top-weight-center 0.85 \
    --top-weight-scale 0.05 \
    --backbone-kind hf \
    --backbone-dtype bf16 \
    --model-path "$MODEL" \
    --model-identity-file "$MODEL/model.safetensors" \
    --expected-model-sha256 "$EXPECTED_MODEL_SHA" \
    > "$OUTPUT_ROOT/logs/${ARM}_fold_${FOLD_ID}.log" 2>&1
done

"$PYTHON_BIN" - "$OUTPUT_ROOT" "$FOLD_ID" "$CUDA_VISIBLE_DEVICES" <<'PY'
import hashlib,json,os,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]); fold=int(sys.argv[2]); physical_gpu=sys.argv[3]
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
results={}
for arm in ('C0','C1'):
    result_path=root/arm/f'fold_{fold}'/'RESULT.json'
    result=json.load(open(result_path))
    assert result['status']==f'PASS_V220_{arm}_CONTACT_SHARED_FOLD'
    assert result['arm']==arm and int(result['fold_id'])==fold and int(result['seed'])==43
    results[arm]={
        'result_path':str(result_path),
        'result_sha256':sha(result_path),
        'prediction_sha256':result['outputs']['fold_predictions.tsv'],
        'checkpoint_sha256':result['outputs']['fold_checkpoint.pt'],
        'calibration_sha256':result['outputs']['CONTACT_WEIGHT_CALIBRATION.json'],
    }
assert results['C0']['calibration_sha256']==results['C1']['calibration_sha256']
payload={
    'schema_version':'pvrig_v220_phase1_core_fold_pair_terminal_v1_2',
    'status':'PASS_V220_C0_C1_FOLD_PAIR',
    'fold_id':fold,
    'seed':43,
    'physical_gpu_at_launch':physical_gpu,
    'results':results,
}
target=root/f'fold_{fold}_PAIR_TERMINAL.json'
fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
try:
    with os.fdopen(fd,'w') as handle:
        json.dump(payload,handle,indent=2,sort_keys=True); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp,target)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
print(json.dumps({'status':payload['status'],'fold_id':fold},sort_keys=True))
PY
