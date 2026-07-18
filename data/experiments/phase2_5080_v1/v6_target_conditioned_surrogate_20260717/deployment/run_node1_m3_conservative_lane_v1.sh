#!/usr/bin/env bash
set -euo pipefail
if (( $# != 10 )); then echo 'usage: lane gpu seed hidden dropout residual_scale lr nll top ranking' >&2; exit 64; fi
lane=$1; gpu=$2; seed=$3; hidden=$4; dropout=$5; residual=$6; lr=$7; nll=$8; top=$9; ranking=${10:-}
# shellcheck disable=SC2015
[[ -n "$ranking" ]] || { echo missing_ranking >&2; exit 64; }
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CODE=$ROOT/code_v1_1/src/train_v6_fusion_surrogate.py
INPUT=$ROOT/inputs_v1_1/full1507/v6_supervised1507.tsv
EMBED=$ROOT/runtime/full1507_esm2_650m_embeddings_v1
OUT=$ROOT/runtime/m3_${lane}_oof_v1
STATUS=$ROOT/status/m3_${lane}_v1
mkdir -p "$OUT" "$STATUS"
sha256sum -c <<'HASHES'
2d462b8b427a4784bddd2a4af6ba5fc4cc43c0160029bf810108471126ff8278  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/train_v6_fusion_surrogate.py
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_supervised1507.tsv
95371648f6ee177fe286c731f6891782708e4a4f86bffb13f6fa8f41abe68760  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/runtime/full1507_esm2_650m_embeddings_v1/embedding_cache_receipt.json
HASHES
free_gb=$(df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}')
if (( free_gb < 180 )); then printf '{"status":"FAIL_DISK_PREFLIGHT","free_gb":%s}\n' "$free_gb" > "$STATUS/terminal.json"; exit 72; fi
printf '{"status":"RUNNING","pid":%s,"gpu_physical":%s,"started_at":"%s"}\n' "$$" "$gpu" "$(date -Is)" > "$STATUS/status.json"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
export CUDA_VISIBLE_DEVICES="$gpu"
set +e
"$PY" "$CODE" --input "$INPUT" --embeddings "$EMBED" --output-dir "$OUT" --device cuda:0 \
 --seed "$seed" --epochs 40 --patience 8 --batch-size 64 --per-parent-batch 8 --hidden "$hidden" \
 --dropout "$dropout" --residual-scale "$residual" --lr "$lr" --weight-decay 0.02 --huber-beta 0.02 \
 --dual-weight 1.0 --receptor-weight 0.35 --nll-weight "$nll" --top-weight "$top" --ranking-weight "$ranking" \
 --bootstrap-repetitions 1000 --resume > "$STATUS/stdout.json.tmp" 2> "$STATUS/stderr.log"
rc=$?
set -e
if (( rc != 0 )); then printf '{"status":"FAIL_M3_CONSERVATIVE_LANE","return_code":%s,"finished_at":"%s"}\n' "$rc" "$(date -Is)" > "$STATUS/terminal.json"; exit "$rc"; fi
mv "$STATUS/stdout.json.tmp" "$STATUS/stdout.json"
python3 - "$OUT" "$STATUS" "$lane" <<'PY'
import json,sys,datetime,pathlib,hashlib
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);lane=sys.argv[3];summary=out/'summary.json';x=json.loads(summary.read_text());assert x['status']=='PASS_V6_OOF_COMPLETE' and x['rows']==1507
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(status/'terminal.json').write_text(json.dumps({'status':'PASS_M3_CONSERVATIVE_LANE_TERMINAL','lane':lane,'promotion_status':x['promotion']['status'],'M2':x['M2'],'M3':x['V6'],'summary_sha256':sha(summary),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
