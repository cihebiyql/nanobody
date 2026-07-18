#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CODE=$ROOT/code_v1_1/m4/train_m4_sklearn_fusion.py
INPUT=$ROOT/inputs_v1_1/full1507/v6_supervised1507.tsv
TABLE_RECEIPT=$ROOT/inputs_v1_1/full1507/v6_training_table_receipt.json
EMBED=$ROOT/runtime/full1507_esm2_650m_embeddings_v1
OUT=$ROOT/runtime/m4_sklearn_650m_nested_oof_v1_1
STATUS=$ROOT/status/m4_sklearn_650m_v1_1
mkdir -p "$OUT" "$STATUS"
sha256sum -c <<'HASHES'
d24e9b9c04cd3039dd004dcf15e224b45569373487a66a9ddf6b47b6aece9d76  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/m4/train_m4_sklearn_fusion.py
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_supervised1507.tsv
46fae18a63e10920c05ccf1dc873de2b588ec436a0320d909405164f9d14c529  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_1/full1507/v6_training_table_receipt.json
95371648f6ee177fe286c731f6891782708e4a4f86bffb13f6fa8f41abe68760  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/runtime/full1507_esm2_650m_embeddings_v1/embedding_cache_receipt.json
HASHES
free_gb=$(df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}'); if (( free_gb < 180 )); then exit 72; fi
printf '{"status":"RUNNING","pid":%s,"cpu_threads":8,"started_at":"%s"}\n' "$$" "$(date -Is)" > "$STATUS/status.json"
export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8
set +e
"$PY" "$CODE" --input "$INPUT" --table-receipt "$TABLE_RECEIPT" --embeddings "$EMBED" --output-dir "$OUT" --expected-outer-folds 5 --inner-folds 5 --subinner-folds 4 --m2-alpha 10 --pca-dimensions 8,16,32 --head-families ridge,extra_trees,hist_gradient_boosting --ridge-alphas 1,10,100 --extra-trees-estimators 300 --extra-trees-max-features 0.5,1.0 --extra-trees-min-samples-leaf 2,5 --hist-learning-rates 0.03,0.08 --hist-max-leaf-nodes 7,15 --hist-min-samples-leaf 10 --hist-l2 1,10 --hist-max-iter 250 --bootstrap-repetitions 1000 --seed 43 > "$STATUS/stdout.json.tmp" 2> "$STATUS/stderr.log"
rc=$?
set -e
if (( rc != 0 )); then printf '{"status":"FAIL_M4_SKLEARN_650M","return_code":%s,"finished_at":"%s"}\n' "$rc" "$(date -Is)" > "$STATUS/terminal.json"; exit "$rc"; fi
mv "$STATUS/stdout.json.tmp" "$STATUS/stdout.json"
python3 - "$OUT" "$STATUS" <<'PY'
import json,sys,pathlib,hashlib,datetime
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);s=out/'summary.json';x=json.loads(s.read_text());assert x['status']=='PASS_V6_M4_OOF_COMPLETE' and x['rows']==1507
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(status/'terminal.json').write_text(json.dumps({'status':'PASS_M4_SKLEARN_650M_TERMINAL','M2':x['M2'],'M4':x['M4'],'comparison':x['comparison'],'bootstrap':x['parent_bootstrap_delta'],'summary_sha256':sha(s),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
