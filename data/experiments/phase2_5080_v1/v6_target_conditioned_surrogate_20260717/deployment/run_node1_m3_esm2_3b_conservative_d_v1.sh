#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CODE=$ROOT/code_v1_1/src/train_v6_fusion_surrogate.py
INPUT=$ROOT/inputs_v1_1/full1507/v6_supervised1507.tsv
EMBED=$ROOT/runtime/full1507_esm2_3b_embeddings_v1
OUT=$ROOT/runtime/m3_esm2_3b_conservative_d_oof_v1
STATUS=$ROOT/status/m3_esm2_3b_conservative_d_v1
mkdir -p "$OUT" "$STATUS"
sha256sum -c <<'HASHES'
2d462b8b427a4784bddd2a4af6ba5fc4cc43c0160029bf810108471126ff8278  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/train_v6_fusion_surrogate.py
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_supervised1507.tsv
f808d677c6c34d4ddb804f4fcba97cf9d66c7900bbac60532e506d5f89bc9574  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/runtime/full1507_esm2_3b_embeddings_v1/embedding_cache_receipt.json
HASHES
printf '{"status":"RUNNING","pid":%s,"gpu_physical":2,"started_at":"%s"}\n' "$$" "$(date -Is)" > "$STATUS/status.json"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
export CUDA_VISIBLE_DEVICES=2
set +e
"$PY" "$CODE" --input "$INPUT" --embeddings "$EMBED" --output-dir "$OUT" --device cuda:0 --seed 43 --epochs 40 --patience 8 --batch-size 64 --per-parent-batch 8 --hidden 64 --dropout 0.30 --residual-scale 0.03 --lr 0.0001 --weight-decay 0.02 --huber-beta 0.02 --dual-weight 1.0 --receptor-weight 0.35 --nll-weight 0.0 --top-weight 0.0 --ranking-weight 0.0 --bootstrap-repetitions 1000 --resume > "$STATUS/stdout.json.tmp" 2> "$STATUS/stderr.log"
rc=$?
set -e
if (( rc != 0 )); then printf '{"status":"FAIL_M3_ESM2_3B_CAPACITY_LANE","return_code":%s}\n' "$rc" > "$STATUS/terminal.json"; exit "$rc"; fi
mv "$STATUS/stdout.json.tmp" "$STATUS/stdout.json"
python3 - "$OUT" "$STATUS" <<'PY'
import json,sys,pathlib,hashlib,datetime
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);s=out/'summary.json';x=json.loads(s.read_text());assert x['rows']==1507
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(status/'terminal.json').write_text(json.dumps({'status':'PASS_M3_ESM2_3B_CAPACITY_LANE_TERMINAL','promotion_status':x['promotion']['status'],'M2':x['M2'],'M3':x['V6'],'summary_sha256':sha(s),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
