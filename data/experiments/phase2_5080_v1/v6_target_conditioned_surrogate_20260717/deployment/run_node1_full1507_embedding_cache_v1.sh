#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
INPUT=$ROOT/inputs_v1_1/full1507/v6_supervised1507.tsv
CODE=$ROOT/code_v1_1/src/cache_v6_esm_embeddings.py
OUT=$ROOT/runtime/full1507_esm2_650m_embeddings_v1
STATUS=$ROOT/status/full1507_embedding_lane_v1
mkdir -p "$OUT" "$STATUS"
sha256sum -c <<'HASHES'
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_supervised1507.tsv
69d1de369e175bdf1645256f31552cf78247dbb5e793d7f6f010f1f975fb518b  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/cache_v6_esm_embeddings.py
HASHES
free_gb=$(df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}')
if (( free_gb < 180 )); then
  printf '{"status":"FAIL_DISK_PREFLIGHT","free_gb":%s}\n' "$free_gb" > "$STATUS/terminal.json"
  exit 72
fi
if [[ ! -x "$PY" || ! -f "$MODEL/model.safetensors" ]]; then
  printf '{"status":"FAIL_RUNTIME_PREFLIGHT"}\n' > "$STATUS/terminal.json"
  exit 73
fi
printf '{"status":"RUNNING","pid":%s,"gpu_physical":1,"started_at":"%s"}\n' "$$" "$(date -Is)" > "$STATUS/status.json"
export CUDA_VISIBLE_DEVICES=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
set +e
"$PY" "$CODE" \
  --input "$INPUT" \
  --model-path "$MODEL" \
  --output-dir "$OUT" \
  --device cuda:0 --dtype bfloat16 --batch-size 8 --shard-size 128 \
  > "$STATUS/stdout.json.tmp" 2> "$STATUS/stderr.log"
rc=$?
set -e
if (( rc != 0 )); then
  python3 - "$STATUS" "$rc" <<'PY'
import json,sys,datetime,pathlib
root=pathlib.Path(sys.argv[1]); rc=int(sys.argv[2])
(root/'terminal.json').write_text(json.dumps({'status':'FAIL_FULL1507_EMBEDDING_CACHE','return_code':rc,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2)+'\n')
PY
  exit "$rc"
fi
mv "$STATUS/stdout.json.tmp" "$STATUS/stdout.json"
python3 - "$OUT" "$STATUS" <<'PY'
import json,sys,datetime,pathlib,hashlib
out=pathlib.Path(sys.argv[1]); status=pathlib.Path(sys.argv[2])
receipt=out/'embedding_cache_receipt.json'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
payload=json.loads(receipt.read_text())
assert payload['status']=='PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE' and payload['rows']==1507
terminal={'status':'PASS_FULL1507_EMBEDDING_CACHE','rows':1507,'receipt':str(receipt),'receipt_sha256':sha(receipt),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(status/'terminal.json').write_text(json.dumps(terminal,indent=2,sort_keys=True)+'\n')
PY
