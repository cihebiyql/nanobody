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

mkdir -p "$STATUS"
[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2; exit 4; }

(cd "$ROOT" && sha256sum -c SHA256SUMS_PHASE_B_IMPLEMENTATION_V1_1)
"$PY" - "$ROOT/PHASE_B_IMPLEMENTATION_FREEZE_V1_1.json" "$ROOT" <<'PY'
import hashlib,json,pathlib,sys
freeze=json.loads(pathlib.Path(sys.argv[1]).read_text()); root=pathlib.Path(sys.argv[2])
assert freeze['status']=='FROZEN_AFTER_LOCAL_AND_REMOTE_PATH_TESTS_BEFORE_PHASE_A_OOF_UNSEAL'
assert freeze['input_access']=={'open_development_rows':0,'frozen_test_rows':0,'phase_a_oof_metrics_accessed_before_freeze':False}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,expected in freeze['files'].items(): assert sha(root/name)==expected,(name,sha(root/name),expected)
assert freeze['tests']['status']=='OK' and freeze['tests']['count']==17
PY

mkdir -p "$LOGS"
printf '{"status":"WAITING_PHASE_A_TERMINAL","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_LIVE_STATUS.json"
while [[ ! -f "$STATUS/TERMINAL.json" ]]; do
  if [[ -f "$STATUS/SUPERVISOR.pid" ]]; then
    phase_a_pid=$(cat "$STATUS/SUPERVISOR.pid")
    if ! kill -0 "$phase_a_pid" 2>/dev/null; then
      printf '{"status":"FAIL_PHASE_A_DIED_WITHOUT_TERMINAL","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_TERMINAL.json"
      exit 5
    fi
  fi
  sleep 60
done

"$PY" - "$STATUS/TERMINAL.json" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['status']=='PASS_V2_13_TOP5_PHASE_A_COMPLETE'
assert x['open_development_access_count']==0 and x['frozen_test_access_count']==0
PY

set +e
"$PY" "$ROOT/src/select_phase_a_variant_v1.py" \
  --contract "$ROOT/PHASE_B_PROMOTION_CONTRACT_V1.json" \
  --baseline-oof "$ROOT/inputs/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --phase-a-root "$PHASE_A" \
  --output "$SELECTION" > "$LOGS/phase_a_selection.log" 2>&1
selection_rc=$?
set -e
if [[ "$selection_rc" -eq 2 ]]; then
  "$PY" - "$SELECTION" > "$STATUS/PHASE_B_TERMINAL.json" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['status']=='FAIL_NO_PHASE_A_VARIANT_ELIGIBLE' and x['selected_variant'] is None
assert x['input_access']=={'open_development_rows':0,'frozen_test_rows':0}
print(json.dumps({'status':x['status'],'phase_b_training_started':False,'input_access':x['input_access']},indent=2,sort_keys=True))
PY
  exit 0
fi
[[ "$selection_rc" -eq 0 ]] || { echo "selector_rc:$selection_rc" >&2; exit "$selection_rc"; }

variant=$("$PY" - "$SELECTION" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert x['status']=='PASS_PHASE_A_VARIANT_PROMOTED' and x['selected_variant'] in {'L1','L2','L3'}
assert x['input_access']=={'open_development_rows':0,'frozen_test_rows':0}
print(x['selected_variant'])
PY
)

"$PY" "$ROOT/src/materialize_phase_b_seed_contracts_v1.py" \
  --promotion-contract "$ROOT/PHASE_B_PROMOTION_CONTRACT_V1.json" \
  --selection "$SELECTION" \
  --source-contracts "$SOURCE/prepared" \
  --output-dir "$CONTRACTS" > "$LOGS/materialize_contracts.log" 2>&1

sha256sum -c <<EOF
$IDENTITY_SHA  $IDENTITY
26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/model/residue_model_v2_5_ortho.py
af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/trainer/train_v2_5_ortho_heads.py
EOF

free_data1_gib=$(df -BG /data1 | awk 'NR==2{gsub(/G/,"",$4); print $4}')
[[ "$free_data1_gib" -ge 100 ]] || { echo "data1_free_space_gate:${free_data1_gib}GiB" >&2; exit 6; }

wait_gpu_gate() {
  local gpu="$1" attempt=0
  while true; do
    local free sum=0 util sample
    free=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | awk -F', ' -v gpu="$gpu" '$1==gpu{print $2}')
    for sample in 1 2 3; do
      util=$(nvidia-smi --query-gpu=index,utilization.gpu --format=csv,noheader,nounits | awk -F', ' -v gpu="$gpu" '$1==gpu{print $2}')
      sum=$((sum + util)); sleep 3
    done
    if [[ -n "$free" && "$free" -ge 18000 && $((sum / 3)) -le 50 ]]; then return 0; fi
    attempt=$((attempt + 1))
    printf '{"status":"WAITING_GPU_GATE","gpu":%s,"free_mib":%s,"mean_util":%s,"attempt":%s}\n' "$gpu" "${free:-0}" "$((sum/3))" "$attempt" > "$STATUS/PHASE_B_GPU${gpu}_WAITING.json"
    sleep 60
  done
}

validate_fold() {
  local seed="$1" fold="$2" path="$3"
  "$PY" - "$path/RESULT.json" "$variant" "$seed" "$fold" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text()); variant=sys.argv[2]; seed=int(sys.argv[3]); fold=int(sys.argv[4])
assert x['status']=='PASS_V2_13_TOP5_CLEAN_ATTENTION_FOLD_TRAINING'
assert x['variant']==variant and x['fold_id']==fold and x['seed']==seed
assert x['open_development_access_count']==0 and x['frozen_test_access_count']==0
assert x['split']['whole_parent_overlap']==0 and x['exact_min_inference'] is True
PY
}

run_cell() {
  local gpu="$1" seed="$2" fold="$3"
  wait_gpu_gate "$gpu"
  local cell="$OUT/$variant/seed_${seed}/fold_${fold}" log="$LOGS/${variant}_seed${seed}_fold${fold}.log"
  CUDA_VISIBLE_DEVICES="$gpu" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
    "$PY" "$ROOT/src/run_top5_clean_attention_fold_v1.py" \
      --contract "$CONTRACTS/seed_${seed}_fold_${fold}_contract.json" \
      --top5-contract "$ROOT/TOP5_EXPERIMENT_CONTRACT_V1.json" \
      --variant "$variant" --graph-cache-dir "$GRAPH" \
      --model-path "$MODEL" --model-identity-file "$IDENTITY" \
      --expected-model-sha256 "$IDENTITY_SHA" \
      --output-dir "$cell" --device cuda:0 --seed "$seed" > "$log" 2>&1
  validate_fold "$seed" "$fold" "$cell"
}

run_gpu_lane() {
  local gpu="$1"; shift
  local job seed fold
  for job in "$@"; do
    seed=${job%%:*}; fold=${job##*:}
    run_cell "$gpu" "$seed" "$fold"
  done
}

printf '{"status":"RUNNING_PHASE_B_3SEED","selected_variant":"%s","timestamp":"%s"}\n' "$variant" "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_LIVE_STATUS.json"
PIDS=()
cleanup() { for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup INT TERM HUP
run_gpu_lane 3 917:0 917:3 1931:1 1931:4 & PIDS+=($!)
run_gpu_lane 4 917:1 917:4 1931:2 & PIDS+=($!)
run_gpu_lane 5 917:2 1931:0 1931:3 & PIDS+=($!)
printf '%s\n' "${PIDS[@]}" > "$STATUS/PHASE_B_WORKER_PIDS.txt"
failed=0
for pid in "${PIDS[@]}"; do if ! wait "$pid"; then failed=1; fi; done
if [[ "$failed" -ne 0 ]]; then
  printf '{"status":"FAIL_PHASE_B_ONE_OR_MORE_CELLS","selected_variant":"%s"}\n' "$variant" > "$STATUS/PHASE_B_TERMINAL.json"
  exit 7
fi

for seed in 917 1931; do
  "$PY" "$ROOT/src/collect_top5_oof_seed_v1.py" \
    --teacher "$SOURCE/prepared/train9849_teacher.tsv" \
    --assignment "$SOURCE/prepared/candidate_fold_assignment.tsv" \
    --contracts-dir "$CONTRACTS" \
    --run-root "$OUT/$variant/seed_${seed}" \
    --output-dir "$OUT/$variant/seed_${seed}/OOF_AGGREGATE" \
    --variant "$variant" --seed "$seed" > "$LOGS/${variant}_seed${seed}_collector.log" 2>&1
done

"$PY" "$ROOT/src/aggregate_phase_b_3seed_v1.py" \
  --promotion-contract "$ROOT/PHASE_B_PROMOTION_CONTRACT_V1.json" \
  --selection "$SELECTION" \
  --seed43-oof "$PHASE_A/$variant/OOF_AGGREGATE/TOP5_${variant}_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --seed917-oof "$OUT/$variant/seed_917/OOF_AGGREGATE/TOP5_${variant}_SEED917_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --seed1931-oof "$OUT/$variant/seed_1931/OOF_AGGREGATE/TOP5_${variant}_SEED1931_TRAIN9849_OOF_PREDICTIONS.tsv" \
  --output-dir "$OUT/$variant/THREE_SEED_AGGREGATE" > "$LOGS/${variant}_3seed_aggregate.log" 2>&1

cp "$OUT/$variant/THREE_SEED_AGGREGATE/PHASE_B_RECEIPT.json" "$STATUS/PHASE_B_TERMINAL.json"
