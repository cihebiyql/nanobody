#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?usage: $0 OUTPUT_DIR}"
PYTHON_BIN="/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
PREP="/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared"
V213="/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722"
PHASE0="/data1/qlyu/projects/pvrig_v2_20_phase0_train_contact_teacher_v1_20260723/release/train_contact_teacher_v1_2"
MODEL="/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c"
MODEL_SHA="a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"

[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2; exit 2; }
mkdir -p "$OUT"

"$PYTHON_BIN" - "$ROOT" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
prereg_path=root/'PREREGISTRATION_PHASE1_CORE_V1_2.json'
prereg=json.loads(prereg_path.read_text())
assert prereg['status']=='FROZEN_PRETRAINING_PHASE1_CORE_PROTOCOL'
for relative,expected in prereg['implementation_hashes_before_initial_state_materialization'].items():
    observed=hashlib.sha256((root/relative).read_bytes()).hexdigest()
    assert observed==expected,(relative,observed,expected)
PY

"$PYTHON_BIN" "$ROOT/src/replay_v213_b0_oof_v1.py" \
  --preregistration "$ROOT/PREREGISTRATION_PHASE1_CORE_V1_2.json" \
  --fold-prediction "0=$V213/training/phase_a_seed43/L1/fold_0/inner_oof_fold_predictions.tsv" \
  --fold-prediction "1=$V213/training/phase_a_seed43/L1/fold_1/inner_oof_fold_predictions.tsv" \
  --fold-prediction "2=$V213/training/phase_a_seed43/L1/fold_2/inner_oof_fold_predictions.tsv" \
  --fold-prediction "3=$V213/training/phase_a_seed43/L1/fold_3/inner_oof_fold_predictions.tsv" \
  --fold-prediction "4=$V213/training/phase_a_seed43/L1/fold_4/inner_oof_fold_predictions.tsv" \
  --train-teacher "$PREP/train9849_teacher.tsv" \
  --frozen-aggregate "$V213/training/phase_a_seed43/L1/OOF_AGGREGATE/TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --frozen-metrics "$V213/training/phase_a_seed43/L1/OOF_AGGREGATE/OOF_METRICS.json" \
  --frozen-receipt "$V213/training/phase_a_seed43/L1/OOF_AGGREGATE/OOF_RECEIPT.json" \
  --output-json "$OUT/B0_REPLAY.json" \
  > "$OUT/B0_REPLAY.log" 2>&1

"$PYTHON_BIN" "$ROOT/src/materialize_v220_production_initial_state_v1.py" \
  --runner "$ROOT/src/run_v220_contact_shared_fold_v1.py" \
  --paired-helper "$ROOT/src/materialize_v220_paired_initial_state_v1.py" \
  --preregistration "$ROOT/PREREGISTRATION_PHASE1_CORE_V1_2.json" \
  --terminal "$OUT/INITIAL_STATE_TERMINAL.json" \
  --scalar-contract "$PREP/fold_0_contract.json" \
  --teacher-release "$PHASE0" \
  --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
  --initial-state "$OUT/V220_PHASE1_SEED43_HEAD_STATE.bin" \
  --output-dir "$OUT/UNUSED_NO_TRAINING" \
  --arm C0 \
  --fold-id 0 \
  --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
  --device cuda:0 \
  --model-path "$MODEL" \
  --model-identity-file "$MODEL/model.safetensors" \
  --expected-model-sha256 "$MODEL_SHA" \
  > "$OUT/INITIAL_STATE_MATERIALIZATION.log" 2>&1

INITIAL_STATE_SHA="$(sha256sum "$OUT/V220_PHASE1_SEED43_HEAD_STATE.bin" | awk '{print $1}')"
INITIAL_RECEIPT_SHA="$(sha256sum "$OUT/V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json" | awk '{print $1}')"

"$PYTHON_BIN" "$ROOT/src/validate_v220_cross_process_initial_state_v1.py" \
  --runner "$ROOT/src/run_v220_contact_shared_fold_v1.py" \
  --paired-helper "$ROOT/src/materialize_v220_paired_initial_state_v1.py" \
  --preregistration "$ROOT/PREREGISTRATION_PHASE1_CORE_V1_2.json" \
  --terminal "$OUT/CROSS_PROCESS_INITIAL_STATE_TERMINAL.json" \
  --scalar-contract "$PREP/fold_0_contract.json" \
  --teacher-release "$PHASE0" \
  --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
  --initial-state "$OUT/V220_PHASE1_SEED43_HEAD_STATE.bin" \
  --initial-state-receipt "$OUT/V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json" \
  --expected-initial-state-sha256 "$INITIAL_STATE_SHA" \
  --expected-initial-state-receipt-sha256 "$INITIAL_RECEIPT_SHA" \
  --output-dir "$OUT/UNUSED_CROSS_PROCESS_NO_TRAINING" \
  --arm C0 \
  --fold-id 0 \
  --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
  --device cuda:0 \
  --seed 43 \
  --model-path "$MODEL" \
  --model-identity-file "$MODEL/model.safetensors" \
  --expected-model-sha256 "$MODEL_SHA" \
  > "$OUT/CROSS_PROCESS_INITIAL_STATE_VALIDATION.log" 2>&1

"$PYTHON_BIN" - "$OUT" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
b0=json.loads((root/'B0_REPLAY.json').read_text())
initial=json.loads((root/'INITIAL_STATE_TERMINAL.json').read_text())
cross=json.loads((root/'CROSS_PROCESS_INITIAL_STATE_TERMINAL.json').read_text())
assert b0['status']=='PASS_V213_B0_OOF_BYTE_EXACT_REPLAY'
assert initial['status']=='PASS_V220_PHASE1_INITIAL_HEAD_STATE_MATERIALIZED_NO_TRAINING'
assert initial['training_started'] is False
assert cross['status']=='PASS_V220_CROSS_PROCESS_INITIAL_STATE_AND_BACKBONE_BINDING'
assert cross['optimizer_created'] is False and cross['optimizer_steps']==0
assert cross['backward_called'] is False
assert cross['training_started'] is False
files=[
 'B0_REPLAY.json','B0_REPLAY.log','INITIAL_STATE_TERMINAL.json',
 'INITIAL_STATE_MATERIALIZATION.log','V220_PHASE1_SEED43_HEAD_STATE.bin',
 'V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json',
 'CROSS_PROCESS_INITIAL_STATE_TERMINAL.json',
 'CROSS_PROCESS_INITIAL_STATE_VALIDATION.log',
]
(root/'SHA256SUMS').write_text(''.join(f'{sha(root/name)}  {name}\n' for name in sorted(files)))
terminal={
 'schema_version':'pvrig_v220_phase1_pretraining_terminal_v1_2',
 'status':'PASS_B0_REPLAY_AND_INITIAL_STATE_MATERIALIZATION_NO_TRAINING',
 'B0_replay_sha256':sha(root/'B0_REPLAY.json'),
 'initial_state_terminal_sha256':sha(root/'INITIAL_STATE_TERMINAL.json'),
 'initial_state_sha256':sha(root/'V220_PHASE1_SEED43_HEAD_STATE.bin'),
 'initial_state_receipt_sha256':sha(root/'V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json'),
 'cross_process_initial_state_terminal_sha256':sha(root/'CROSS_PROCESS_INITIAL_STATE_TERMINAL.json'),
 'sha256sums_sha256':sha(root/'SHA256SUMS'),
 'cross_process_load_verified':True,
 'training_started':False,
}
(root/'PRETRAINING_TERMINAL.json').write_text(json.dumps(terminal,indent=2,sort_keys=True)+'\n')
PY
