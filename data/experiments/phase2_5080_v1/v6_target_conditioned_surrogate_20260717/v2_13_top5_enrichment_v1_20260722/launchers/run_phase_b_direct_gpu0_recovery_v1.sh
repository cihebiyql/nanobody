#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
SOURCE=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY=$MODEL/model.safetensors
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
GRAPH=$SOURCE/prepared/train9849_graph_view_v1/graph_cache
STATUS=$ROOT/status
PHASE_A=$ROOT/training/phase_a_seed43
OUT=$ROOT/training/phase_b_multiseed
CONTRACTS=$OUT/contracts
LOGS=$OUT/logs
SELECTION=$OUT/PHASE_A_SELECTION.json
VARIANT=L1
GPU=0

on_error() {
  local rc=$?
  printf '{"status":"FAIL_PHASE_B_DIRECT_GPU0_RECOVERY","return_code":%s,"timestamp":"%s"}\n' \
    "$rc" "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_TERMINAL.json"
  exit "$rc"
}
trap on_error ERR

mkdir -p "$STATUS" "$LOGS"
[[ -d "$CONTRACTS" && -f "$SELECTION" ]]

existing=0
if [[ -d "$OUT/$VARIANT" ]]; then
  existing=$(find "$OUT/$VARIANT" -type f -name RESULT.json | wc -l)
fi
[[ "$existing" -eq 0 ]] || { echo "existing_fold_results:$existing" >&2; exit 10; }

sha256sum -c <<EOF
$IDENTITY_SHA  $IDENTITY
26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/model/residue_model_v2_5_ortho.py
af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/trainer/train_v2_5_ortho_heads.py
EOF

"$PY" - "$SELECTION" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['status']=='PASS_PHASE_A_VARIANT_PROMOTED' and x['selected_variant']=='L1'
assert x['input_access']=={'open_development_rows':0,'frozen_test_rows':0}
PY

validate_fold() {
  local seed=$1 fold=$2 path=$3
  "$PY" - "$path/RESULT.json" "$seed" "$fold" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['status']=='PASS_V2_13_TOP5_CLEAN_ATTENTION_FOLD_TRAINING'
assert x['variant']=='L1' and x['seed']==int(sys.argv[2]) and x['fold_id']==int(sys.argv[3])
assert x['open_development_access_count']==0 and x['frozen_test_access_count']==0
assert x['split']['whole_parent_overlap']==0 and x['exact_min_inference'] is True
PY
}

run_cell() {
  local seed=$1 fold=$2
  local cell=$OUT/$VARIANT/seed_${seed}/fold_${fold}
  local log=$LOGS/DIRECT_GPU0_${VARIANT}_seed${seed}_fold${fold}.log
  [[ ! -e "$cell" ]] || { echo "cell_exists:$cell" >&2; exit 11; }
  printf '{"status":"RUNNING_DIRECT_GPU0_CELL","seed":%s,"fold":%s,"gpu":0,"timestamp":"%s"}\n' \
    "$seed" "$fold" "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_DIRECT_CURRENT_CELL.json"
  CUDA_VISIBLE_DEVICES=$GPU OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
    "$PY" "$ROOT/src/run_top5_clean_attention_fold_v1.py" \
      --contract "$CONTRACTS/seed_${seed}_fold_${fold}_contract.json" \
      --top5-contract "$ROOT/TOP5_EXPERIMENT_CONTRACT_V1.json" \
      --variant "$VARIANT" --graph-cache-dir "$GRAPH" \
      --model-path "$MODEL" --model-identity-file "$IDENTITY" \
      --expected-model-sha256 "$IDENTITY_SHA" \
      --output-dir "$cell" --device cuda:0 --seed "$seed" > "$log" 2>&1
  validate_fold "$seed" "$fold" "$cell"
}

printf '{"status":"RUNNING_PHASE_B_DIRECT_GPU0_RECOVERY","selected_variant":"L1","timestamp":"%s"}\n' \
  "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_LIVE_STATUS.json"

for job in 917:0 1931:0 917:1 1931:1 917:2 1931:2 917:3 1931:3 917:4 1931:4; do
  seed=${job%%:*}; fold=${job##*:}
  run_cell "$seed" "$fold"
done

for seed in 917 1931; do
  "$PY" "$ROOT/src/collect_top5_oof_seed_v1.py" \
    --teacher "$SOURCE/prepared/train9849_teacher.tsv" \
    --assignment "$SOURCE/prepared/candidate_fold_assignment.tsv" \
    --contracts-dir "$CONTRACTS" \
    --run-root "$OUT/$VARIANT/seed_${seed}" \
    --output-dir "$OUT/$VARIANT/seed_${seed}/OOF_AGGREGATE" \
    --variant "$VARIANT" --seed "$seed" > "$LOGS/DIRECT_${VARIANT}_seed${seed}_collector.log" 2>&1
done

"$PY" "$ROOT/src/aggregate_phase_b_3seed_v1.py" \
  --promotion-contract "$ROOT/PHASE_B_PROMOTION_CONTRACT_V1.json" \
  --selection "$SELECTION" \
  --seed43-oof "$PHASE_A/$VARIANT/OOF_AGGREGATE/TOP5_${VARIANT}_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --seed917-oof "$OUT/$VARIANT/seed_917/OOF_AGGREGATE/TOP5_${VARIANT}_SEED917_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --seed1931-oof "$OUT/$VARIANT/seed_1931/OOF_AGGREGATE/TOP5_${VARIANT}_SEED1931_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --output-dir "$OUT/$VARIANT/THREE_SEED_AGGREGATE" > "$LOGS/DIRECT_${VARIANT}_3seed_aggregate.log" 2>&1

cp "$OUT/$VARIANT/THREE_SEED_AGGREGATE/PHASE_B_RECEIPT.json" "$STATUS/PHASE_B_TERMINAL.json"
