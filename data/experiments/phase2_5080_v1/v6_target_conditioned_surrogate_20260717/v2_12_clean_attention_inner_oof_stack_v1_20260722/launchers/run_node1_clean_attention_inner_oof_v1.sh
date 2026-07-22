#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY=$MODEL/model.safetensors
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
GRAPH=$ROOT/prepared/train9849_graph_view_v1/graph_cache
OUT=$ROOT/training/oof_seed43_v1
STATUS=$ROOT/status
LOGS=$OUT/logs
GPUS=(3 6 5 4 3)
PIDS=()

mkdir -p "$STATUS"
[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2; exit 4; }
mkdir -p "$LOGS"

(cd "$ROOT" && sha256sum -c SHA256SUMS)
sha256sum -c <<EOF
$IDENTITY_SHA  $IDENTITY
26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/model/residue_model_v2_5_ortho.py
af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/trainer/train_v2_5_ortho_heads.py
b1823387b70375517b65848d873ff0e875396125ca5882ea384fabfcbd8880a9  /data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_receipt_v2.json
59461f9d48e5995acd902ba8524caad5c779a3c8b54a5deee121f9c3be6adfbc  /data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt
EOF

"$PY" - "$GRAPH" <<'PY'
import json,pathlib,sys
g=pathlib.Path(sys.argv[1]); x=json.loads((g.parent/'GRAPH_VIEW_TERMINAL.json').read_text())
assert x['status']=='PASS_TRAIN9849_LABEL_FREE_GRAPH_VIEW'
assert x['inode_audit']['same_inode'] is True
assert x['input_access']=={'open_development_labels':0,'frozen_test_labels':0}
PY

gpu_gate() {
  local gpu="$1"
  local free
  free=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | awk -F', ' -v gpu="$gpu" '$1==gpu{print $2}')
  [[ -n "$free" && "$free" -ge 18000 ]] || { echo "gpu_memory_gate:$gpu:$free" >&2; return 1; }
}

cleanup() {
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup INT TERM HUP

launch_fold() {
  local fold="$1" gpu="${GPUS[$1]}"
  gpu_gate "$gpu"
  local fold_out="$OUT/fold_${fold}" log="$LOGS/fold_${fold}.log"
  CUDA_VISIBLE_DEVICES="$gpu" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    "$PY" "$ROOT/src/run_clean_attention_inner_oof_fold_v1.py" \
      --contract "$ROOT/prepared/fold_${fold}_contract.json" \
      --graph-cache-dir "$GRAPH" \
      --model-path "$MODEL" \
      --model-identity-file "$IDENTITY" \
      --expected-model-sha256 "$IDENTITY_SHA" \
      --output-dir "$fold_out" --device cuda:0 --seed 43 \
      >"$log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  printf '%s\t%s\t%s\t%s\t%s\n' "$fold" "$gpu" 43 "$pid" "$fold_out" >> "$STATUS/FOLD_GPU_PID_MAP.tsv"
}

validate_fold() {
  local fold="$1"
  "$PY" - "$OUT/fold_${fold}/RESULT.json" "$fold" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); fold=int(sys.argv[2]); x=json.loads(p.read_text())
assert x['status']=='PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_FOLD_TRAINING'
assert x['fold_id']==fold and x['seed']==43
assert x['open_development_access_count']==0 and x['frozen_test_access_count']==0
assert x['split']['whole_parent_overlap']==0
PY
}

printf 'fold_id\tgpu\tseed\tpid\toutput\n' > "$STATUS/FOLD_GPU_PID_MAP.tsv"
for fold in 0 1 2 3; do launch_fold "$fold"; done
printf '%s\n' "${PIDS[@]}" > "$STATUS/WAVE1_PIDS.txt"
wave_failed=0
for pid in "${PIDS[@]}"; do if ! wait "$pid"; then wave_failed=1; fi; done
if [[ "$wave_failed" -ne 0 ]]; then
  printf '{"status":"FAIL_V2_12_OOF_WAVE1"}\n' > "$STATUS/TERMINAL.json"
  exit 5
fi
for fold in 0 1 2 3; do validate_fold "$fold"; done

PIDS=()
launch_fold 4
printf '%s\n' "${PIDS[@]}" > "$STATUS/WAVE2_PIDS.txt"
if ! wait "${PIDS[0]}"; then
  printf '{"status":"FAIL_V2_12_OOF_WAVE2"}\n' > "$STATUS/TERMINAL.json"
  exit 6
fi
validate_fold 4

"$PY" "$ROOT/src/collect_clean_attention_inner_oof_v1.py" \
  --teacher "$ROOT/prepared/train9849_teacher.tsv" \
  --assignment "$ROOT/prepared/candidate_fold_assignment.tsv" \
  --contracts-dir "$ROOT/prepared" \
  --run-root "$OUT" \
  --output-dir "$OUT/OOF_AGGREGATE" \
  > "$LOGS/collector.log" 2>&1

"$PY" - "$ROOT" > "$STATUS/TERMINAL.json" <<'PY'
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); out=r/'training/oof_seed43_v1'; sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths=[out/f'fold_{fold}/RESULT.json' for fold in range(5)]
paths += [out/'OOF_AGGREGATE/OOF_RECEIPT.json',out/'OOF_AGGREGATE/OOF_METRICS.json',out/'OOF_AGGREGATE/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv']
print(json.dumps({'schema_version':'pvrig_v2_12_node1_clean_attention_inner_oof_terminal_v1','status':'PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_AND_AGGREGATE','outputs':{str(p):sha(p) for p in paths},'open_development_access_count':0,'frozen_test_access_count':0},indent=2,sort_keys=True))
PY

