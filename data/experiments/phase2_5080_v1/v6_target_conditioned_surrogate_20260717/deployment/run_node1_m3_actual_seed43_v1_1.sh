#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CODE=$ROOT/code_v1_1/src/train_v6_fusion_surrogate.py
INPUT=$ROOT/inputs_v1_1/full1507/v6_supervised1507.tsv
EMBED=$ROOT/runtime/full1507_esm2_650m_embeddings_v1
OUT=$ROOT/runtime/m3_actual_seed43_oof_v1_1
STATUS=$ROOT/status/m3_actual_seed43_v1_1
mkdir -p "$OUT" "$STATUS"
sha256sum -c <<'HASHES'
2d462b8b427a4784bddd2a4af6ba5fc4cc43c0160029bf810108471126ff8278  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/train_v6_fusion_surrogate.py
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_supervised1507.tsv
95371648f6ee177fe286c731f6891782708e4a4f86bffb13f6fa8f41abe68760  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/runtime/full1507_esm2_650m_embeddings_v1/embedding_cache_receipt.json
HASHES
free_gb=$(df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}')
if (( free_gb < 180 )); then printf '{"status":"FAIL_DISK_PREFLIGHT","free_gb":%s}\n' "$free_gb" > "$STATUS/terminal.json"; exit 72; fi
printf '{"status":"RUNNING","pid":%s,"gpu_physical":1,"started_at":"%s"}\n' "$$" "$(date -Is)" > "$STATUS/status.json"
export CUDA_VISIBLE_DEVICES=1
set +e
"$PY" "$CODE" --input "$INPUT" --embeddings "$EMBED" --output-dir "$OUT" \
 --device cuda:0 --seed 43 --epochs 30 --patience 6 --batch-size 64 --per-parent-batch 8 \
 --hidden 256 --dropout 0.15 --residual-scale 0.12 --lr 0.0003 --weight-decay 0.01 \
 --huber-beta 0.02 --dual-weight 1.0 --receptor-weight 0.35 --nll-weight 0.10 \
 --top-weight 0.10 --ranking-weight 0.10 --bootstrap-repetitions 1000 --resume \
 > "$STATUS/stdout.json.tmp" 2> "$STATUS/stderr.log"
rc=$?
set -e
if (( rc != 0 )); then
 python3 - "$STATUS" "$rc" <<'PY'
import json,sys,datetime,pathlib
root=pathlib.Path(sys.argv[1]);rc=int(sys.argv[2]);(root/'terminal.json').write_text(json.dumps({'status':'FAIL_M3_ACTUAL_SEED43','return_code':rc,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2)+'\n')
PY
 exit "$rc"
fi
mv "$STATUS/stdout.json.tmp" "$STATUS/stdout.json"
python3 - "$OUT" "$STATUS" <<'PY'
import json,sys,datetime,pathlib,hashlib
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);receipt=out/'terminal_receipt.json';summary=out/'summary.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
r=json.loads(receipt.read_text());s=json.loads(summary.read_text());assert r['status']=='PASS_V6_TRAINING_TERMINAL' and s['rows']==1507
(status/'terminal.json').write_text(json.dumps({'status':'PASS_M3_ACTUAL_SEED43_TERMINAL','promotion_status':s['promotion']['status'],'summary':str(summary),'summary_sha256':sha(summary),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
