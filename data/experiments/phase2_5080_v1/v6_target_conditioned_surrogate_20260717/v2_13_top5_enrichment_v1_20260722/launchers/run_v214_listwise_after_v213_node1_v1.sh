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
OUT=$ROOT/training/v214_listwise_seed43
LOGS=$OUT/logs

mkdir -p "$STATUS"
(cd "$ROOT" && sha256sum -c SHA256SUMS_V2_14_IMPLEMENTATION_V1)
"$PY" - "$ROOT/V2_14_IMPLEMENTATION_FREEZE_V1.json" "$ROOT" <<'PY'
import hashlib,json,pathlib,sys
freeze=json.loads(pathlib.Path(sys.argv[1]).read_text());root=pathlib.Path(sys.argv[2])
assert freeze['status']=='FROZEN_BEFORE_V2_13_PHASE_A_OOF_UNSEAL'
assert freeze['input_access']=={'open_development_rows':0,'frozen_test_rows':0,'v2_13_phase_a_oof_metrics_accessed_before_freeze':False}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,expected in freeze['files'].items():assert sha(root/name)==expected,(name,sha(root/name),expected)
assert freeze['tests']=={'count':7,'status':'OK','log_sha256':freeze['files']['TEST_RESULTS_V2_14_LISTWISE_FULL_V1.log']}
PY

printf '{"status":"WAITING_V2_13_CHAIN_TERMINAL","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/V2_14_LIVE_STATUS.json"
while [[ ! -f "$STATUS/HARD_NEGATIVE_C1_TERMINAL.json" ]];do
  if [[ -f "$STATUS/HARD_NEGATIVE_C1_SUPERVISOR.pid" ]];then pid=$(cat "$STATUS/HARD_NEGATIVE_C1_SUPERVISOR.pid");if ! kill -0 "$pid" 2>/dev/null;then printf '{"status":"FAIL_V2_13_CHAIN_DIED"}\n' > "$STATUS/V2_14_TERMINAL.json";exit 5;fi;fi
  sleep 60
done

[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2;exit 6; }
mkdir -p "$LOGS"
free_data1_gib=$(df -BG /data1|awk 'NR==2{gsub(/G/,"",$4);print $4}');[[ "$free_data1_gib" -ge 100 ]] || { echo "data1_free_space_gate:${free_data1_gib}GiB" >&2;exit 7; }

wait_gpu_gate(){
 local gpu="$1" attempt=0
 while true;do
  local free sum=0 util sample
  free=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits|awk -F', ' -v gpu="$gpu" '$1==gpu{print $2}')
  for sample in 1 2 3;do util=$(nvidia-smi --query-gpu=index,utilization.gpu --format=csv,noheader,nounits|awk -F', ' -v gpu="$gpu" '$1==gpu{print $2}');sum=$((sum+util));sleep 3;done
  if [[ -n "$free" && "$free" -ge 16000 && $((sum/3)) -le 50 ]];then return 0;fi
  attempt=$((attempt+1));printf '{"status":"WAITING_GPU_GATE","gpu":%s,"free_mib":%s,"mean_util":%s,"attempt":%s}\n' "$gpu" "${free:-0}" "$((sum/3))" "$attempt" > "$STATUS/V2_14_GPU${gpu}_WAITING.json";sleep 60
 done
}

validate_fold(){
 local variant="$1" fold="$2" path="$3"
 "$PY" - "$path/RESULT.json" "$variant" "$fold" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text());variant=sys.argv[2];fold=int(sys.argv[3])
assert x['status']=='PASS_V2_14_LISTWISE_TOP5_FOLD' and x['variant']==variant and x['fold_id']==fold and x['seed']==43
assert x['split']['whole_parent_overlap']==0 and x['exact_min_inference'] is True
assert x['open_development_access_count']==0 and x['frozen_test_access_count']==0
assert x['training']['batch_size']==32 and x['training']['gradient_accumulation']==1
PY
}

run_lane(){
 local variant="$1" gpu="$2" lane=$OUT/$variant
 mkdir -p "$lane"
 for fold in 0 1 2 3 4;do
  wait_gpu_gate "$gpu";fold_out=$lane/fold_${fold};log=$LOGS/${variant}_fold_${fold}.log
  CUDA_VISIBLE_DEVICES="$gpu" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  "$PY" "$ROOT/src/run_v214_listwise_fold_v1.py" \
   --contract "$SOURCE/prepared/fold_${fold}_contract.json" --listwise-contract "$ROOT/V2_14_LISTWISE_TOP5_CONTRACT_V1.json" \
   --variant "$variant" --graph-cache-dir "$GRAPH" --model-path "$MODEL" --model-identity-file "$IDENTITY" --expected-model-sha256 "$IDENTITY_SHA" \
   --output-dir "$fold_out" --device cuda:0 --seed 43 > "$log" 2>&1
  validate_fold "$variant" "$fold" "$fold_out"
 done
 "$PY" "$ROOT/src/collect_v214_listwise_oof_v1.py" --teacher "$SOURCE/prepared/train9849_teacher.tsv" --assignment "$SOURCE/prepared/candidate_fold_assignment.tsv" --contracts-dir "$SOURCE/prepared" --run-root "$lane" --output-dir "$lane/OOF_AGGREGATE" --variant "$variant" > "$LOGS/${variant}_collector.log" 2>&1
}

printf '{"status":"RUNNING_V2_14_LISTWISE_OOF","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/V2_14_LIVE_STATUS.json"
PIDS=();cleanup(){ for pid in "${PIDS[@]:-}";do kill "$pid" 2>/dev/null||true;done;};trap cleanup INT TERM HUP
for binding in N1:3 N2:4 N3:5;do variant=${binding%%:*};gpu=${binding##*:};run_lane "$variant" "$gpu" & PIDS+=($!);done
printf '%s\n' "${PIDS[@]}" > "$STATUS/V2_14_WORKER_PIDS.txt"
failed=0;for pid in "${PIDS[@]}";do if ! wait "$pid";then failed=1;fi;done
if [[ "$failed" -ne 0 ]];then printf '{"status":"FAIL_V2_14_ONE_OR_MORE_LANES"}\n' > "$STATUS/V2_14_TERMINAL.json";exit 8;fi

set +e
"$PY" "$ROOT/src/select_v214_variant_v1.py" --contract "$ROOT/V2_14_PROMOTION_CONTRACT_V1.json" --baseline-oof "$ROOT/inputs/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv" --phase-a-root "$OUT" --output "$OUT/V2_14_SELECTION.json" > "$LOGS/selection.log" 2>&1
selection_rc=$?;set -e
[[ "$selection_rc" -eq 0 || "$selection_rc" -eq 2 ]] || exit "$selection_rc"
cp "$OUT/V2_14_SELECTION.json" "$STATUS/V2_14_TERMINAL.json"
