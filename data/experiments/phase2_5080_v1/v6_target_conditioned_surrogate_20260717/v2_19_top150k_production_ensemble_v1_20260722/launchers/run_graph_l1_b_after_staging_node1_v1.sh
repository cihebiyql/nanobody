#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
GRAPH_BUILDER="$ROOT/residue_v2/src/build_residue_graph_cache_v2.py"
GRAPH_OUT="$ROOT/label_free_graph_full150k_v1"
PDB_ROOT="$ROOT/nbb2_pdbs_full150k_v1"
STAGING="$ROOT/nbb2_staging_full150k_v1"
MANIFEST="$ROOT/compact_manifest_full150k_v1.tsv"
INFER="$ROOT/code/src/infer_clean_attention_checkpoint_ensemble_v1.py"
BASE=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/src/run_top5_clean_attention_fold_v1.py
REFERENCE=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_b_multiseed/contracts/seed_917_fold_0_contract.json
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY="$MODEL/model.safetensors"
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
L1_OUT="$ROOT/l1_5fold_predictions_full150k_v1"
B_OUT="$ROOT/b_4seed_predictions_full150k_v1"

mkdir -p "$ROOT/status" "$ROOT/logs"
cat > "$ROOT/status/GRAPH_L1_B_WATCHER_LAUNCH_RECEIPT.json" <<JSON
{"status":"WAITING_FOR_NBB2_STAGING","gpu":7,"started_at":"$(date -u +%FT%TZ)"}
JSON

for _ in $(seq 1 17280); do
  [[ -f "$ROOT/status/NBB2_STAGING_TERMINAL.json" ]] && break
  sleep 10
done
[[ -f "$ROOT/status/NBB2_STAGING_TERMINAL.json" ]]

"$PYTHON" "$GRAPH_BUILDER" \
  --manifest "$STAGING/top150k_graph_structure_manifest_v1.tsv" \
  --pdb-root "$PDB_ROOT" \
  --output-dir "$GRAPH_OUT" \
  --expected-entities 150000 > "$ROOT/logs/graph_full150k_v1.log" 2>&1

L1_CHECKPOINTS=()
for fold in 0 1 2 3 4; do
  L1_CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_a_seed43/L1/fold_${fold}/inner_oof_clean_attention_head_final.pt")
done
CUDA_VISIBLE_DEVICES=7 "$PYTHON" "$INFER" \
  --manifest "$MANIFEST" --expected-rows 150000 \
  --graph-cache-dir "$GRAPH_OUT" \
  --reference-contract "$REFERENCE" --base-module "$BASE" \
  "${L1_CHECKPOINTS[@]}" \
  --model-path "$MODEL" --model-identity-file "$IDENTITY" \
  --expected-model-sha256 "$IDENTITY_SHA" \
  --device cuda:0 --batch-size 64 --precision bf16 --backbone-dtype bf16 \
  --uncertainty-penalty 1.0 --output-dir "$L1_OUT" > "$ROOT/logs/l1_5fold_full150k_v1.log" 2>&1

B_CHECKPOINTS=()
for seed in 43 917 1931 3253; do
  B_CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed${seed}/clean_attention_head_final.pt")
done
CUDA_VISIBLE_DEVICES=7 "$PYTHON" "$INFER" \
  --manifest "$MANIFEST" --expected-rows 150000 \
  --graph-cache-dir "$GRAPH_OUT" \
  --reference-contract "$REFERENCE" --base-module "$BASE" \
  "${B_CHECKPOINTS[@]}" \
  --model-path "$MODEL" --model-identity-file "$IDENTITY" \
  --expected-model-sha256 "$IDENTITY_SHA" \
  --device cuda:0 --batch-size 64 --precision bf16 --backbone-dtype bf16 \
  --uncertainty-penalty 1.0 --output-dir "$B_OUT" > "$ROOT/logs/b_4seed_full150k_v1.log" 2>&1

python3 - "$GRAPH_OUT/graph_cache_receipt_v2.json" "$L1_OUT/RUN_RECEIPT.json" "$B_OUT/RUN_RECEIPT.json" "$ROOT/status/GRAPH_L1_B_TERMINAL.json" <<'PY'
import json,sys
graph,l1,b,target=sys.argv[1:]
payload={"status":"PASS_GRAPH_L1_B_FULL150K_COMPLETE","graph":json.load(open(graph)),"L1":json.load(open(l1)),"B":json.load(open(b))}
open(target,"w").write(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
