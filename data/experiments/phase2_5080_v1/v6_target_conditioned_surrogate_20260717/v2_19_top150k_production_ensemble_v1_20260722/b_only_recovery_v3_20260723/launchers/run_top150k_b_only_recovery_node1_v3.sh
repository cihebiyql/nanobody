#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/b_only_recovery_v3_20260723"
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
MANIFEST="$ROOT/compact_manifest_full150k_v1.tsv"
GRAPH="$ROOT/label_free_graph_full150k_v1"
L1="$ROOT/l1_5fold_predictions_full150k_v1"
B="$ROOT/b_4seed_predictions_full150k_v1"
STATUS="$ROOT/status"
LOGS="$ROOT/logs"
RECOVERY="$ROOT/recovery_b_only_v3_20260723"
FAILED_B_LOG="$LOGS/b_4seed_full150k_recovery_v2.log"
INFER_BASE="$ROOT/code/src/infer_clean_attention_checkpoint_ensemble_v1.py"
INFER_PROFILED="$PKG/src/run_profiled_v211_b4_inference_v3.py"
VALIDATOR="$PKG/src/validate_top150k_b_only_recovery_v3.py"
BASE=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/src/run_top5_clean_attention_fold_v1.py
REFERENCE=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_b_multiseed/contracts/seed_917_fold_0_contract.json
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY="$MODEL/model.safetensors"
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0

mkdir -p "$RECOVERY" "$STATUS" "$LOGS"

# Bind every executable/config byte to the reviewed freeze and also bind the
# two pre-existing code dependencies which are intentionally not copied into
# this versioned recovery package.
"$PY" - "$PKG/IMPLEMENTATION_FREEZE_V3.json" "$PKG" "$INFER_BASE" "$BASE" <<'PY'
import hashlib,json,sys
from pathlib import Path
freeze_path,pkg,infer_base,base=map(Path,sys.argv[1:])
def sha(path):
    assert path.is_file() and not path.is_symlink(), f"regular_file_required:{path}"
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''): h.update(block)
    return h.hexdigest()
x=json.loads(freeze_path.read_text())
assert x['status']=='FROZEN_REVIEW_READY_NOT_REMOTE_EXECUTED'
for relative,digest in x['files'].items():
    path=pkg/relative
    assert sha(path)==digest, f"package_hash_mismatch:{relative}"
assert sha(infer_base)==x['external_dependencies']['generic_inference_module_sha256']
assert sha(base)==x['external_dependencies']['v213_base_module_sha256']
PY

# This recovery is B-only.  Existing graph and L1 bytes are inputs and must not
# be regenerated; old failed V2 evidence must remain present and unchanged.
[[ -f "$GRAPH/graph_cache_receipt_v2.json" ]]
[[ -f "$L1/RUN_RECEIPT.json" && -f "$L1/clean_attention_checkpoint_ensemble_predictions.tsv" ]]
[[ -f "$FAILED_B_LOG" ]]
grep -Fq 'checkpoint_schema_invalid:pvrig_v2_11_full10644_clean_attention_runner_v1' "$FAILED_B_LOG"
[[ ! -e "$B" ]]
[[ ! -e "$STATUS/GRAPH_L1_B_TERMINAL.json" ]]
[[ ! -e "$RECOVERY/EXISTING_GRAPH_L1_BINDINGS_V3.json" ]]
[[ ! -e "$RECOVERY/B4_PROFILE_VALIDATION_V3.json" ]]
[[ ! -e "$RECOVERY/GRAPH_L1_B_TERMINAL_RECOVERY_V3.json" ]]

"$PY" "$VALIDATOR" preflight \
  --manifest "$MANIFEST" --graph-receipt "$GRAPH/graph_cache_receipt_v2.json" \
  --l1-output "$L1/clean_attention_checkpoint_ensemble_predictions.tsv" --l1-receipt "$L1/RUN_RECEIPT.json" \
  --failed-b-log "$FAILED_B_LOG" --expected-rows 150000 \
  --preflight-receipt "$RECOVERY/EXISTING_GRAPH_L1_BINDINGS_V3.json" \
  > "$LOGS/b_only_recovery_v3_preflight.log" 2>&1

CHECKPOINTS=()
RESULTS=()
for seed in 43 917 1931 3253; do
  CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed${seed}/clean_attention_head_final.pt")
  RESULTS+=(--result-receipt "/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed${seed}/RESULT.json")
done

CUDA_VISIBLE_DEVICES=7 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  "$PY" "$INFER_PROFILED" \
  --base-inference-module "$INFER_BASE" "${RESULTS[@]}" \
  --profile-receipt "$RECOVERY/B4_PROFILE_VALIDATION_V3.json" \
  --manifest "$MANIFEST" --expected-rows 150000 --graph-cache-dir "$GRAPH" \
  --reference-contract "$REFERENCE" --base-module "$BASE" "${CHECKPOINTS[@]}" \
  --model-path "$MODEL" --model-identity-file "$IDENTITY" --expected-model-sha256 "$IDENTITY_SHA" \
  --device cuda:0 --batch-size 64 --precision bf16 --backbone-dtype bf16 \
  --uncertainty-penalty 1.0 --output-dir "$B" \
  > "$LOGS/b_4seed_full150k_recovery_v3.log" 2>&1

"$PY" "$VALIDATOR" publish \
  --manifest "$MANIFEST" --graph-receipt "$GRAPH/graph_cache_receipt_v2.json" \
  --l1-output "$L1/clean_attention_checkpoint_ensemble_predictions.tsv" --l1-receipt "$L1/RUN_RECEIPT.json" \
  --b-output "$B/clean_attention_checkpoint_ensemble_predictions.tsv" --b-receipt "$B/RUN_RECEIPT.json" \
  --profile-receipt "$RECOVERY/B4_PROFILE_VALIDATION_V3.json" \
  --failed-b-log "$FAILED_B_LOG" --expected-rows 150000 \
  --preflight-receipt "$RECOVERY/EXISTING_GRAPH_L1_BINDINGS_V3.json" \
  --versioned-terminal "$RECOVERY/GRAPH_L1_B_TERMINAL_RECOVERY_V3.json" \
  --canonical-terminal "$STATUS/GRAPH_L1_B_TERMINAL.json" \
  > "$LOGS/b_only_recovery_v3_publish.log" 2>&1
