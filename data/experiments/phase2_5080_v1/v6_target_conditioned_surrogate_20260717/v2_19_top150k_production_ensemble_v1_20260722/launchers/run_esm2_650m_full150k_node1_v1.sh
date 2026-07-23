#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
INPUT="$ROOT/stage0_label_free_priors_v1/STAGE0_LABEL_FREE_PRIORS.tsv"
OUTPUT="$ROOT/esm2_650m_pooled_full150k_v1"
SCRIPT="$ROOT/code/src/cache_v6_esm_embeddings.py"
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
EXPECTED_SCRIPT=69d1de369e175bdf1645256f31552cf78247dbb5e793d7f6f010f1f975fb518b

mkdir -p "$ROOT/status" "$ROOT/logs"
[[ "$(sha256sum "$SCRIPT" | awk '{print $1}')" == "$EXPECTED_SCRIPT" ]]
[[ -f "$INPUT" && -f "$MODEL/config.json" ]]
[[ ! -e "$OUTPUT" ]]

cat > "$ROOT/status/ESM2_650M_LAUNCH_RECEIPT.json" <<JSON
{"status":"RUNNING_ESM2_650M_FULL150K","gpu":7,"rows":150000,"started_at":"$(date -u +%FT%TZ)"}
JSON

CUDA_VISIBLE_DEVICES=7 "$PYTHON" "$SCRIPT" \
  --input "$INPUT" \
  --model-path "$MODEL" \
  --output-dir "$OUTPUT" \
  --device cuda:0 \
  --dtype bfloat16 \
  --batch-size 64 \
  --shard-size 5000 > "$ROOT/logs/esm2_650m_full150k_v1.log" 2>&1

python3 - "$OUTPUT/embedding_cache_receipt.json" "$ROOT/status/ESM2_650M_TERMINAL.json" <<'PY'
import json,sys
source,target=sys.argv[1:]
payload=json.load(open(source))
assert payload["status"]=="PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE"
assert payload["rows"]==150000
payload["terminal_status"]="PASS_ESM2_650M_FULL150K_COMPLETE"
open(target,"w").write(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
