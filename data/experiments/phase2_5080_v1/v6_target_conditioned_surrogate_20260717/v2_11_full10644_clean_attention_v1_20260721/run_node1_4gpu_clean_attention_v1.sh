#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CONTRACT=$ROOT/DEPLOYMENT_CONTRACT_V1.json
GRAPH=/data1/qlyu/projects/pvrig_v2_11_canonical10644_label_free_graph_v1_20260721/prepared_graph_v1/graph_cache
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY=$MODEL/model.safetensors
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
OUT=$ROOT/training/4seed_v1
STATUS=$ROOT/status
LOGS=$OUT/logs
SEEDS=(43 917 1931 3253)
GPUS=(3 4 5 6)

mkdir -p "$STATUS"
[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2; exit 4; }
mkdir -p "$LOGS"

sha256sum -c <<EOF
239a8141c464bbc5e817322082b1dfb509aac2b917417e43d302883af70b5177  $ROOT/src/run_full10644_clean_attention_v1.py
10d42d104d4d7b36e5f3e65e0ecfab7eb5ad9a8bfee3b21392ad0e0aaa315493  $ROOT/src/evaluate_multiseed_clean_attention_v1.py
26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/model/residue_model_v2_5_ortho.py
af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0  /data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/trainer/train_v2_5_ortho_heads.py
b1823387b70375517b65848d873ff0e875396125ca5882ea384fabfcbd8880a9  /data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_receipt_v2.json
59461f9d48e5995acd902ba8524caad5c779a3c8b54a5deee121f9c3be6adfbc  /data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt
6605323342c2e64cc75157d7d6cbb484b72a8ef70e0d5d3f5aaf7817a707e696  $GRAPH/graph_cache_v2.npz
b82e159fb028072e1d780885867276e7bb01552af53be0470ceec3e461b8c0d1  $GRAPH/graph_cache_receipt_v2.json
$IDENTITY_SHA  $IDENTITY
EOF

launch_seed() {
  local slot="$1" seed="${SEEDS[$1]}" gpu="${GPUS[$1]}"
  local seed_out="$OUT/D1_seed${seed}" log="$LOGS/D1_seed${seed}.log"
  CUDA_VISIBLE_DEVICES="$gpu" OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    "$PY" "$ROOT/src/run_full10644_clean_attention_v1.py" \
      --contract "$CONTRACT" \
      --graph-cache-dir "$GRAPH" \
      --model-path "$MODEL" \
      --model-identity-file "$IDENTITY" \
      --expected-model-sha256 "$IDENTITY_SHA" \
      --output-dir "$seed_out" \
      --device cuda:0 \
      --seed "$seed" \
      >"$log" 2>&1 &
  PIDS[$slot]=$!
  printf '%s\t%s\t%s\t%s\n' "$gpu" "$seed" "${PIDS[$slot]}" "$seed_out" >> "$STATUS/GPU_SEED_PID_MAP.tsv"
}

PIDS=()
printf 'gpu\tseed\tpid\toutput\n' > "$STATUS/GPU_SEED_PID_MAP.tsv"
launch_seed 0
sleep 60
kill -0 "${PIDS[0]}" 2>/dev/null || {
  printf '{"status":"FAIL_FIRST_SEED_PREFLIGHT"}\n' > "$STATUS/TERMINAL.json"
  tail -n 100 "$LOGS/D1_seed43.log" >&2
  exit 5
}
for slot in 1 2 3; do launch_seed "$slot"; done
printf '%s\n' "${PIDS[@]}" > "$STATUS/SEED_PIDS.txt"

failed=0
for pid in "${PIDS[@]}"; do
  if ! wait "$pid"; then failed=1; fi
done
if [[ "$failed" -ne 0 ]]; then
  printf '{"status":"FAIL_ONE_OR_MORE_CLEAN_ATTENTION_SEEDS"}\n' > "$STATUS/TERMINAL.json"
  exit 6
fi

"$PY" "$ROOT/src/evaluate_multiseed_clean_attention_v1.py" \
  --contract "$CONTRACT" \
  --run-root "$OUT" \
  --output-dir "$OUT/EARLY_ENRICHMENT"

"$PY" - "$OUT" > "$STATUS/TERMINAL.json" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
paths = [root / f"D1_seed{s}/RESULT.json" for s in (43, 917, 1931, 3253)]
paths += [root / "EARLY_ENRICHMENT/EARLY_ENRICHMENT.json"]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps({
    "schema_version": "pvrig_v2_11_node1_4gpu_clean_attention_terminal_v1",
    "status": "PASS_4SEED_CLEAN_ATTENTION_AND_ENRICHMENT",
    "outputs": {str(p): sha(p) for p in paths},
}, indent=2, sort_keys=True))
PY
