#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${1:?usage: CUDA_VISIBLE_DEVICES=N $0 RUNTIME_ROOT IMPLEMENTATION_FREEZE EXPECTED_FREEZE_SHA256}"
IMPLEMENTATION_FREEZE="${2:?missing implementation freeze}"
EXPECTED_FREEZE_SHA256="${3:?missing implementation freeze sha256}"

[[ "${CUDA_VISIBLE_DEVICES:-}" =~ ^[0-7]$ ]] || {
  echo "CUDA_VISIBLE_DEVICES_must_bind_exactly_one_physical_GPU_0_to_7" >&2
  exit 2
}
[[ "$EXPECTED_FREEZE_SHA256" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid_freeze_sha256" >&2; exit 2; }
[[ ! -e "$RUNTIME_ROOT" ]] || { echo "runtime_root_exists:$RUNTIME_ROOT" >&2; exit 2; }

PYTHON_BIN="/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
PREP="/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared"
V213="/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722"
PHASE0="/data1/qlyu/projects/pvrig_v2_20_phase0_train_contact_teacher_v1_20260723/release/train_contact_teacher_v1_2"
MODEL="/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c"
PREFLIGHT="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_2_20260723/pretraining_v1_2"
UPSTREAM_ROOT="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_2_20260723/layout_v1/v6_target_conditioned_surrogate_20260717/v2_20_contact_shared_top5_challenger_v1_2_20260723"
UPSTREAM_RUNNER="$UPSTREAM_ROOT/src/run_v220_contact_shared_fold_v1.py"
LEGACY_TEST_LAUNCHER="$ROOT/launchers/run_legacy_102_tests_python311_v1_3_4.sh"
INITIAL_STATE="$PREFLIGHT/V220_PHASE1_SEED43_HEAD_STATE.bin"
INITIAL_RECEIPT="$PREFLIGHT/V220_PHASE1_SEED43_HEAD_STATE.bin.receipt.json"
PREREG="$ROOT/PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3_4.json"
HELPER="$ROOT/launchers/run_shared_fold_materialization_once_v1_3_1.sh"
MATERIALIZER="$ROOT/src/materialize_v220_shared_fold_calibration_v1_3_1.py"
LOAD_ONLY="$ROOT/src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py"
NEW_TEST_LAUNCHER="$ROOT/launchers/run_tests_v1_3_4.sh"
RECEIPT_BUILDER="$ROOT/src/build_v220_v1_3_4_preflight_receipt.py"

EXPECTED_UPSTREAM_RUNNER_SHA="da7a9e28dc818fc20fdaedf35b14da46e4db407c618bd5ce41e1db0ca8b22116"
EXPECTED_CALIBRATOR_SHA="b0b5e6719324fa8376bc33512c9e76805ef768ae1917081f8d2f83a6c9f858e8"
EXPECTED_PAIRED_INITIAL_STATE_SHA="9be8bd8572b297a2b075965775e04c2f066b2ca534738f6f3a8535fd97e988ec"
EXPECTED_CONTACT_TEACHER_STORE_SHA="cb6a20cfe752f237f6afb865bb1c2440b4f3b219634b7d8ca59800f2ec5f0953"
EXPECTED_LEGACY_TEST_LAUNCHER_SHA="e7659f2c81e4b1ef8d736d50b4a87943a0fb5b491a42003a2ff46ca8bc26fbf1"
EXPECTED_INITIAL_STATE_SHA="3139cf661a7358ea89e508ac0d27f0810fc239e6f662e976e250f7029b45e807"
EXPECTED_INITIAL_RECEIPT_SHA="a3bd507edc70fbed2b62e64db82671a1e81849df3d203df1fc3256f705f9aa5f"
EXPECTED_V213_RUNNER_SHA="76f63369838995c10be0e7969ba36ae09fe9d0ed5d619ddbc233118d4d2a32a9"
EXPECTED_MODEL_SHA="a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"

sha256sum -c <<SUMS
$EXPECTED_FREEZE_SHA256  $IMPLEMENTATION_FREEZE
$EXPECTED_UPSTREAM_RUNNER_SHA  $UPSTREAM_RUNNER
$EXPECTED_CALIBRATOR_SHA  $UPSTREAM_ROOT/src/calibrate_v220_contact_weight_v1.py
$EXPECTED_PAIRED_INITIAL_STATE_SHA  $UPSTREAM_ROOT/src/materialize_v220_paired_initial_state_v1.py
$EXPECTED_CONTACT_TEACHER_STORE_SHA  $UPSTREAM_ROOT/src/v220_contact_teacher_store_v1.py
$EXPECTED_LEGACY_TEST_LAUNCHER_SHA  $LEGACY_TEST_LAUNCHER
$EXPECTED_INITIAL_STATE_SHA  $INITIAL_STATE
$EXPECTED_INITIAL_RECEIPT_SHA  $INITIAL_RECEIPT
$EXPECTED_V213_RUNNER_SHA  $V213/src/run_top5_clean_attention_fold_v1.py
$EXPECTED_MODEL_SHA  $MODEL/model.safetensors
SUMS

"$PYTHON_BIN" - "$ROOT" "$IMPLEMENTATION_FREEZE" "$EXPECTED_FREEZE_SHA256" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(); freeze_path=Path(sys.argv[2]).resolve(); expected_freeze_sha=sys.argv[3]
raw=freeze_path.read_bytes(); assert hashlib.sha256(raw).hexdigest()==expected_freeze_sha
freeze=json.loads(raw)
assert freeze['status']=='FROZEN_V1_3_4_IMPLEMENTATION_PENDING_INDEPENDENT_REVIEW_AND_NODE1_PREFLIGHT'
assert freeze['training_started'] is False and freeze['training_authorized'] is False
expected_allowlist=set(freeze['package_file_allowlist']); assert expected_allowlist and len(expected_allowlist)==len(freeze['package_file_allowlist'])
observed=set()
for path in root.rglob('*'):
    relative=path.relative_to(root)
    assert not path.is_symlink(),relative
    if path.is_file():
        observed.add(relative.as_posix())
assert observed==expected_allowlist,(sorted(observed-expected_allowlist),sorted(expected_allowlist-observed))
freeze_rel=freeze_path.relative_to(root).as_posix(); sidecar_rel=freeze_rel+'.sha256'
implementation=set(freeze['implementation_hashes'])
assert expected_allowlist-implementation=={freeze_rel,sidecar_rel} and implementation<=expected_allowlist
assert (root/sidecar_rel).read_bytes()==f'{expected_freeze_sha}  {freeze_path.name}\n'.encode()
for rel,digest in freeze['implementation_hashes'].items():
    path=root/rel
    assert path.is_file() and not path.is_symlink(), rel
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest, rel
assert freeze['external_bindings']['upstream_v1_2_runner_sha256']=='da7a9e28dc818fc20fdaedf35b14da46e4db407c618bd5ce41e1db0ca8b22116'
assert freeze['preflight_contract']['folds']==5
assert freeze['preflight_contract']['training_code_path_allowed'] is False
PY

mkdir "$RUNTIME_ROOT"
mkdir "$RUNTIME_ROOT/logs" "$RUNTIME_ROOT/load_only"
TRAINING_SENTINEL="$RUNTIME_ROOT/training_output_forbidden"
[[ ! -e "$TRAINING_SENTINEL" ]] || exit 70
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"

PYTHON_BIN="$PYTHON_BIN" "$LEGACY_TEST_LAUNCHER" "$UPSTREAM_ROOT" > "$RUNTIME_ROOT/logs/LEGACY_102_TESTS.log" 2>&1
PYTHON_BIN="$PYTHON_BIN" "$NEW_TEST_LAUNCHER" > "$RUNTIME_ROOT/logs/V1_3_4_TESTS.log" 2>&1

HELPER_SHA="$(sha256sum "$HELPER" | awk '{print $1}')"
for FOLD_ID in 0 1 2 3 4; do
  SHARED_DIR="$RUNTIME_ROOT/shared_calibration/fold_${FOLD_ID}"
  SHARED_ARTIFACT="$SHARED_DIR/CONTACT_WEIGHT_CALIBRATION.json"
  FORBIDDEN_OUTPUT="$TRAINING_SENTINEL/fold_${FOLD_ID}"
  "$HELPER" "$SHARED_DIR" -- \
    "$PYTHON_BIN" "$MATERIALIZER" \
      --upstream-v1-2-runner "$UPSTREAM_RUNNER" \
      --expected-upstream-v1-2-runner-sha256 "$EXPECTED_UPSTREAM_RUNNER_SHA" \
      --expected-calibrator-sha256 "$EXPECTED_CALIBRATOR_SHA" \
      --expected-paired-initial-state-sha256 "$EXPECTED_PAIRED_INITIAL_STATE_SHA" \
      --expected-contact-teacher-store-sha256 "$EXPECTED_CONTACT_TEACHER_STORE_SHA" \
      --shared-lock-dir "$SHARED_DIR" \
      --exact-once-helper "$HELPER" \
      --expected-exact-once-helper-sha256 "$HELPER_SHA" \
      --shared-calibration-artifact "$SHARED_ARTIFACT" \
      --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" \
      --teacher-release "$PHASE0" \
      --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
      --initial-state "$INITIAL_STATE" \
      --initial-state-receipt "$INITIAL_RECEIPT" \
      --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" \
      --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
      --output-dir "$FORBIDDEN_OUTPUT" --arm C1 --fold-id "$FOLD_ID" \
      --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
      --device cuda:0 --seed 43 --epochs 8 --batch-size 8 --eval-batch-size 16 \
      --gradient-accumulation 4 --precision bf16 --learning-rate 0.0001 \
      --weight-decay 0.02 --gradient-clip 1.0 --graph-hidden-dim 128 --dropout 0.25 \
      --receptor-weight 1.0 --dual-weight 0.5 --huber-beta 0.03 --softmin-tau 0.02 \
      --top-weight-strength 3.0 --top-weight-center 0.85 --top-weight-scale 0.05 \
      --backbone-kind hf --backbone-dtype bf16 --model-path "$MODEL" \
      --model-identity-file "$MODEL/model.safetensors" --expected-model-sha256 "$EXPECTED_MODEL_SHA"
  SHARED_SHA="$(sha256sum "$SHARED_ARTIFACT" | awk '{print $1}')"
  "$PYTHON_BIN" "$LOAD_ONLY" \
      --upstream-v1-2-runner "$UPSTREAM_RUNNER" \
      --expected-upstream-v1-2-runner-sha256 "$EXPECTED_UPSTREAM_RUNNER_SHA" \
      --expected-calibrator-sha256 "$EXPECTED_CALIBRATOR_SHA" \
      --expected-paired-initial-state-sha256 "$EXPECTED_PAIRED_INITIAL_STATE_SHA" \
      --expected-contact-teacher-store-sha256 "$EXPECTED_CONTACT_TEACHER_STORE_SHA" \
      --exact-once-helper "$HELPER" \
      --expected-exact-once-helper-sha256 "$HELPER_SHA" \
      --shared-calibration-artifact "$SHARED_ARTIFACT" \
      --expected-shared-calibration-sha256 "$SHARED_SHA" \
      --output-receipt "$RUNTIME_ROOT/load_only/fold_${FOLD_ID}.json" \
      --scalar-contract "$PREP/fold_${FOLD_ID}_contract.json" \
      --teacher-release "$PHASE0" --graph-cache-dir "$PREP/train9849_graph_view_v1/graph_cache" \
      --initial-state "$INITIAL_STATE" --initial-state-receipt "$INITIAL_RECEIPT" \
      --expected-initial-state-sha256 "$EXPECTED_INITIAL_STATE_SHA" \
      --expected-initial-state-receipt-sha256 "$EXPECTED_INITIAL_RECEIPT_SHA" \
      --output-dir "$FORBIDDEN_OUTPUT" --arm C1 --fold-id "$FOLD_ID" \
      --v213-runner "$V213/src/run_top5_clean_attention_fold_v1.py" \
      --device cuda:0 --seed 43 --epochs 8 --batch-size 8 --eval-batch-size 16 \
      --gradient-accumulation 4 --precision bf16 --learning-rate 0.0001 \
      --weight-decay 0.02 --gradient-clip 1.0 --graph-hidden-dim 128 --dropout 0.25 \
      --receptor-weight 1.0 --dual-weight 0.5 --huber-beta 0.03 --softmin-tau 0.02 \
      --top-weight-strength 3.0 --top-weight-center 0.85 --top-weight-scale 0.05 \
      --backbone-kind hf --backbone-dtype bf16 --model-path "$MODEL" \
      --model-identity-file "$MODEL/model.safetensors" --expected-model-sha256 "$EXPECTED_MODEL_SHA" \
      > "$RUNTIME_ROOT/logs/load_only_fold_${FOLD_ID}.log" 2>&1
  [[ ! -e "$FORBIDDEN_OUTPUT" ]] || { echo "training_output_created:$FORBIDDEN_OUTPUT" >&2; exit 71; }
done

EXPECTED_NEW_TESTS="$("$PYTHON_BIN" - "$IMPLEMENTATION_FREEZE" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['tests']['new_tests'])
PY
)"
"$PYTHON_BIN" "$RECEIPT_BUILDER" \
  --runtime-root "$RUNTIME_ROOT" \
  --training-sentinel "$TRAINING_SENTINEL" \
  --implementation-freeze "$IMPLEMENTATION_FREEZE" \
  --expected-implementation-freeze-sha256 "$EXPECTED_FREEZE_SHA256" \
  --preregistration "$PREREG" \
  --legacy-test-log "$RUNTIME_ROOT/logs/LEGACY_102_TESTS.log" \
  --v1-3-3-test-log "$RUNTIME_ROOT/logs/V1_3_4_TESTS.log" \
  --expected-new-tests "$EXPECTED_NEW_TESTS" \
  --output-receipt "$RUNTIME_ROOT/NODE1_V1_3_4_PREFLIGHT_RECEIPT.json"
