#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
GRAPH_CACHE_DIR="${GRAPH_CACHE_DIR:?set GRAPH_CACHE_DIR to the completed full10644 graph_cache directory}"
MODEL_PATH="${MODEL_PATH:?set MODEL_PATH to the local frozen ESM2-650M directory}"
MODEL_IDENTITY_FILE="${MODEL_IDENTITY_FILE:?set MODEL_IDENTITY_FILE}"
EXPECTED_MODEL_SHA256="${EXPECTED_MODEL_SHA256:?set EXPECTED_MODEL_SHA256 from the frozen model receipt}"
OUTPUT_ROOT="${OUTPUT_ROOT:?set OUTPUT_ROOT}"

[[ -f "$GRAPH_CACHE_DIR/graph_cache_receipt_v2.json" ]] || { echo "graph cache incomplete" >&2; exit 3; }
[[ -f "$(dirname "$GRAPH_CACHE_DIR")/MATERIALIZATION_RECEIPT.json" ]] || { echo "full10644 materialization receipt missing" >&2; exit 3; }
[[ ! -e "$OUTPUT_ROOT" ]] || { echo "OUTPUT_ROOT already exists: $OUTPUT_ROOT" >&2; exit 4; }
mkdir -p "$OUTPUT_ROOT/logs"

SEEDS=(43 917 1931 3253)
PIDS=()
for gpu in 0 1 2 3; do
  seed="${SEEDS[$gpu]}"
  out="$OUTPUT_ROOT/D1_seed${seed}"
  log="$OUTPUT_ROOT/logs/D1_seed${seed}.log"
  CUDA_VISIBLE_DEVICES="$gpu" OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    "$PYTHON_BIN" "$HERE/src/run_full10644_clean_attention_v1.py" \
      --contract "$HERE/CLEAN_ATTENTION_CONTRACT_V1.json" \
      --graph-cache-dir "$GRAPH_CACHE_DIR" \
      --model-path "$MODEL_PATH" \
      --model-identity-file "$MODEL_IDENTITY_FILE" \
      --expected-model-sha256 "$EXPECTED_MODEL_SHA256" \
      --output-dir "$out" \
      --device cuda:0 \
      --seed "$seed" \
      >"$log" 2>&1 &
  PIDS+=("$!")
  printf '%s\t%s\t%s\t%s\n' "$gpu" "$seed" "$!" "$out"
done

printf '%s\n' "${PIDS[@]}" > "$OUTPUT_ROOT/PIDS.txt"
failed=0
for pid in "${PIDS[@]}"; do
  if ! wait "$pid"; then
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  echo "one or more clean-attention seed jobs failed" >&2
  exit 5
fi
"$PYTHON_BIN" "$HERE/src/evaluate_multiseed_clean_attention_v1.py" \
  --contract "$HERE/CLEAN_ATTENTION_CONTRACT_V1.json" \
  --run-root "$OUTPUT_ROOT" \
  --output-dir "$OUTPUT_ROOT/EARLY_ENRICHMENT"
echo "all four D1 seed jobs and independent early-enrichment aggregation completed"
