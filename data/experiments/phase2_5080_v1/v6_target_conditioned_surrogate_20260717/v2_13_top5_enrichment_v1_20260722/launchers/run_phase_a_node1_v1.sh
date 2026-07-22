#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
SOURCE=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY=$MODEL/model.safetensors
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
GRAPH=$SOURCE/prepared/train9849_graph_view_v1/graph_cache
OUT=$ROOT/training/phase_a_seed43
STATUS=$ROOT/status
LOGS=$OUT/logs

mkdir -p "$STATUS"
[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2; exit 4; }
mkdir -p "$LOGS"

(cd "$ROOT" && sha256sum -c SHA256SUMS_PHASE_A_V1_1)
"$PY" - "$ROOT/IMPLEMENTATION_FREEZE_V1_1.json" "$ROOT" <<'PY'
import hashlib,json,pathlib,sys
freeze=json.loads(pathlib.Path(sys.argv[1]).read_text()); root=pathlib.Path(sys.argv[2])
assert freeze['status']=='FROZEN_AFTER_LOCAL_AND_REMOTE_PATH_TESTS_BEFORE_PRODUCTION_LAUNCH'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name, expected in freeze['files'].items():
    assert sha(root/name)==expected, (name,sha(root/name),expected)
assert freeze['tests']=={'count':9,'log_sha256':freeze['files']['TEST_RESULTS_PHASE_A_V1_1.log'],'status':'OK'}
PY
sha256sum -c <<EOF
$IDENTITY_SHA  $IDENTITY
26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/model/residue_model_v2_5_ortho.py
af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/trainer/train_v2_5_ortho_heads.py
EOF

"$PY" - "$SOURCE/status/TERMINAL.json" "$GRAPH" <<'PY'
import json,pathlib,sys
terminal=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert terminal['status']=='PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_AND_AGGREGATE'
assert terminal['open_development_access_count']==0 and terminal['frozen_test_access_count']==0
graph=pathlib.Path(sys.argv[2])
receipt=json.loads((graph.parent/'GRAPH_VIEW_TERMINAL.json').read_text())
assert receipt['status']=='PASS_TRAIN9849_LABEL_FREE_GRAPH_VIEW'
assert receipt['input_access']=={'open_development_labels':0,'frozen_test_labels':0}
PY

free_data1_gib=$(df -BG /data1 | awk 'NR==2{gsub(/G/,"",$4); print $4}')
[[ "$free_data1_gib" -ge 120 ]] || { echo "data1_free_space_gate:${free_data1_gib}GiB" >&2; exit 5; }

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
    printf '{"status":"WAITING_GPU_GATE","gpu":%s,"free_mib":%s,"mean_util":%s,"attempt":%s}\n' "$gpu" "${free:-0}" "$((sum/3))" "$attempt" > "$STATUS/GPU${gpu}_WAITING.json"
    sleep 60
  done
}

validate_fold() {
  local variant="$1" fold="$2" path="$3"
  "$PY" - "$path/RESULT.json" "$variant" "$fold" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text()); variant=sys.argv[2]; fold=int(sys.argv[3])
assert x['status']=='PASS_V2_13_TOP5_CLEAN_ATTENTION_FOLD_TRAINING'
assert x['variant']==variant and x['fold_id']==fold and x['seed']==43
assert x['open_development_access_count']==0 and x['frozen_test_access_count']==0
assert x['split']['whole_parent_overlap']==0 and x['exact_min_inference'] is True
PY
}

run_lane() {
  local variant="$1" gpu="$2" lane_root="$OUT/$variant"
  mkdir -p "$lane_root"
  for fold in 0 1 2 3 4; do
    wait_gpu_gate "$gpu"
    local fold_out="$lane_root/fold_${fold}" log="$LOGS/${variant}_fold_${fold}.log"
    CUDA_VISIBLE_DEVICES="$gpu" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
      "$PY" "$ROOT/src/run_top5_clean_attention_fold_v1.py" \
        --contract "$SOURCE/prepared/fold_${fold}_contract.json" \
        --top5-contract "$ROOT/TOP5_EXPERIMENT_CONTRACT_V1.json" \
        --variant "$variant" \
        --graph-cache-dir "$GRAPH" \
        --model-path "$MODEL" \
        --model-identity-file "$IDENTITY" \
        --expected-model-sha256 "$IDENTITY_SHA" \
        --output-dir "$fold_out" --device cuda:0 --seed 43 \
        >"$log" 2>&1
    validate_fold "$variant" "$fold" "$fold_out"
  done
  "$PY" "$ROOT/src/collect_top5_clean_attention_oof_v1.py" \
    --teacher "$SOURCE/prepared/train9849_teacher.tsv" \
    --assignment "$SOURCE/prepared/candidate_fold_assignment.tsv" \
    --contracts-dir "$SOURCE/prepared" \
    --run-root "$lane_root" \
    --output-dir "$lane_root/OOF_AGGREGATE" \
    --variant "$variant" > "$LOGS/${variant}_collector.log" 2>&1
  "$PY" - "$lane_root/OOF_AGGREGATE/OOF_RECEIPT.json" "$variant" > "$STATUS/${variant}_TERMINAL.json" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text()); variant=sys.argv[2]
assert x['status']=='PASS_V2_13_TOP5_TRAIN9849_WHOLE_PARENT_OOF' and x['variant']==variant
print(json.dumps({'status':'PASS_V2_13_PHASE_A_LANE','variant':variant,'metrics':x['outputs']['OOF_METRICS.json']},sort_keys=True))
PY
}

PIDS=()
cleanup() { for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup INT TERM HUP

printf 'variant\tgpu\tpid\n' > "$STATUS/PHASE_A_PID_MAP.tsv"
for binding in L1:3 L2:4 L3:5; do
  variant=${binding%%:*}; gpu=${binding##*:}
  run_lane "$variant" "$gpu" & pid=$!; PIDS+=("$pid")
  printf '%s\t%s\t%s\n' "$variant" "$gpu" "$pid" >> "$STATUS/PHASE_A_PID_MAP.tsv"
done
printf '%s\n' "${PIDS[@]}" > "$STATUS/PHASE_A_PIDS.txt"

failed=0
for pid in "${PIDS[@]}"; do if ! wait "$pid"; then failed=1; fi; done
if [[ "$failed" -ne 0 ]]; then
  printf '{"status":"FAIL_V2_13_PHASE_A_ONE_OR_MORE_LANES"}\n' > "$STATUS/TERMINAL.json"
  exit 6
fi

"$PY" - "$ROOT" > "$STATUS/TERMINAL.json" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
outputs={}
for variant in ('L1','L2','L3'):
    p=root/'training/phase_a_seed43'/variant/'OOF_AGGREGATE/OOF_METRICS.json'
    outputs[variant]={'path':str(p),'sha256':sha(p),'metrics':json.loads(p.read_text())}
print(json.dumps({
  'schema_version':'pvrig_v2_13_phase_a_terminal_v1',
  'status':'PASS_V2_13_TOP5_PHASE_A_COMPLETE',
  'outputs':outputs,
  'open_development_access_count':0,
  'frozen_test_access_count':0,
},indent=2,sort_keys=True))
PY
