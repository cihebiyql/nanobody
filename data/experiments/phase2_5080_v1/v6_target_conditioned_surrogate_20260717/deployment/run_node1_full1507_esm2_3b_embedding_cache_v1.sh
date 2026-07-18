#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t36_3B_UR50D/snapshots/476b639933c8baad5ad09a60ac1a87f987b656fc
INPUT=$ROOT/inputs_v1_1/full1507/v6_supervised1507.tsv
CODE=$ROOT/code_v1_1/src/cache_v6_esm_embeddings.py
OUT=$ROOT/runtime/full1507_esm2_3b_embeddings_v1
STATUS=$ROOT/status/full1507_esm2_3b_embedding_lane_v1
mkdir -p "$OUT" "$STATUS"
sha256sum -c <<'HASHES'
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_supervised1507.tsv
69d1de369e175bdf1645256f31552cf78247dbb5e793d7f6f010f1f975fb518b  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/cache_v6_esm_embeddings.py
HASHES
free_gb=$(df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}')
if (( free_gb < 180 )); then printf '{"status":"FAIL_DISK_PREFLIGHT","free_gb":%s}\n' "$free_gb" > "$STATUS/terminal.json"; exit 72; fi
printf '{"status":"RUNNING","pid":%s,"gpu_physical":2,"started_at":"%s"}\n' "$$" "$(date -Is)" > "$STATUS/status.json"
export CUDA_VISIBLE_DEVICES=2 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
set +e
"$PY" "$CODE" --input "$INPUT" --model-path "$MODEL" --output-dir "$OUT" --device cuda:0 --dtype bfloat16 --batch-size 2 --shard-size 64 > "$STATUS/stdout.json.tmp" 2> "$STATUS/stderr.log"
rc=$?
set -e
if (( rc != 0 )); then printf '{"status":"FAIL_FULL1507_ESM2_3B_EMBEDDING_CACHE","return_code":%s,"finished_at":"%s"}\n' "$rc" "$(date -Is)" > "$STATUS/terminal.json"; exit "$rc"; fi
mv "$STATUS/stdout.json.tmp" "$STATUS/stdout.json"
python3 - "$OUT" "$STATUS" <<'PY'
import json,sys,datetime,pathlib,hashlib
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);receipt=out/'embedding_cache_receipt.json';x=json.loads(receipt.read_text());assert x['status']=='PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE' and x['rows']==1507
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(status/'terminal.json').write_text(json.dumps({'status':'PASS_FULL1507_ESM2_3B_EMBEDDING_CACHE','rows':1507,'receipt_sha256':sha(receipt),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
