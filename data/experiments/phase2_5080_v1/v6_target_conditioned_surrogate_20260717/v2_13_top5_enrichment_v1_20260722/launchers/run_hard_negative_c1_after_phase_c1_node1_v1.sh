#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
SOURCE=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
STATUS=$ROOT/status
PHASE_B=$ROOT/training/phase_b_multiseed
OUT=$ROOT/training/hard_negative_c1_3seed

mkdir -p "$STATUS"
(cd "$ROOT" && sha256sum -c SHA256SUMS_HARD_NEGATIVE_AUTORUN_V1)
"$PY" - "$ROOT/HARD_NEGATIVE_AUTORUN_DEPLOYMENT_FREEZE_V1.json" "$ROOT" <<'PY'
import hashlib,json,pathlib,sys
freeze=json.loads(pathlib.Path(sys.argv[1]).read_text());root=pathlib.Path(sys.argv[2])
assert freeze['status']=='FROZEN_BEFORE_PHASE_A_OOF_UNSEAL'
assert freeze['input_access']=={'open_development_rows':0,'frozen_test_rows':0,'phase_a_oof_metrics_accessed_before_freeze':False}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,expected in freeze['files'].items():assert sha(root/name)==expected,(name,sha(root/name),expected)
PY

printf '{"status":"WAITING_PHASE_C1_TERMINAL","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/HARD_NEGATIVE_C1_LIVE_STATUS.json"
while [[ ! -f "$STATUS/PHASE_C1_TERMINAL.json" ]]; do
  if [[ -f "$STATUS/PHASE_C1_SUPERVISOR.pid" ]]; then
    pid=$(cat "$STATUS/PHASE_C1_SUPERVISOR.pid")
    if ! kill -0 "$pid" 2>/dev/null;then printf '{"status":"FAIL_PHASE_C1_DIED_WITHOUT_TERMINAL"}\n' > "$STATUS/HARD_NEGATIVE_C1_TERMINAL.json";exit 5;fi
  fi
  sleep 60
done

phase_c_status=$("$PY" - "$STATUS/PHASE_C1_TERMINAL.json" <<'PY'
import json,pathlib,sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text()).get('status',''))
PY
)
if [[ "$phase_c_status" != "PASS_NESTED_MULTIMODAL_TOP5_OOF" ]];then
  printf '{"status":"SKIP_HARD_NEGATIVE_C1_PHASE_C1_NOT_RUN","phase_c1_status":"%s"}\n' "$phase_c_status" > "$STATUS/HARD_NEGATIVE_C1_TERMINAL.json";exit 0
fi

variant=$("$PY" - "$STATUS/PHASE_B_TERMINAL.json" <<'PY'
import json,pathlib,sys
x=json.loads(pathlib.Path(sys.argv[1]).read_text());assert x['status']=='PASS_PHASE_B_PROMOTED_TO_PHASE_C' and x['selected_variant'] in {'L1','L2','L3'};print(x['selected_variant'])
PY
)
AGG=$PHASE_B/$variant/THREE_SEED_AGGREGATE
[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2;exit 6; }
printf '{"status":"RUNNING_HARD_NEGATIVE_C1","selected_variant":"%s","timestamp":"%s"}\n' "$variant" "$(date --iso-8601=seconds)" > "$STATUS/HARD_NEGATIVE_C1_LIVE_STATUS.json"
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8 \
"$PY" "$ROOT/src/run_hard_negative_top5_reranker_v1.py" \
 --contract "$ROOT/HARD_NEGATIVE_TOP5_CONTRACT_V1.json" \
 --legacy-oof "$ROOT/inputs/TRAIN_INNER_OOF_PREDICTIONS.tsv" \
 --b-oof "$AGG/TOP5_${variant}_3SEED_OOF_PREDICTIONS.tsv" \
 --clean-b-reference "$ROOT/inputs/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv" \
 --assignment "$SOURCE/prepared/candidate_fold_assignment.tsv" \
 --phase-b-receipt "$AGG/PHASE_B_RECEIPT.json" --b-mode phase_b_3seed --output-dir "$OUT" \
 > "$STATUS/HARD_NEGATIVE_C1_PRODUCTION.log" 2>&1
cp "$OUT/RUN_RECEIPT.json" "$STATUS/HARD_NEGATIVE_C1_TERMINAL.json"
