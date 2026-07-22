#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
PKG=$ROOT/v2_15_raw_multimodal_top5_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
OUT=$ROOT/training/v215_raw_multimodal_seed43_l1
RAW=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/prepared/canonical10644_multimodal_v1/canonical10644_multimodal_open_v1.tsv
ASSIGN=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared/candidate_fold_assignment.tsv
LEGACY=$ROOT/inputs/TRAIN_INNER_OOF_PREDICTIONS.tsv
L1=$ROOT/training/phase_a_seed43/L1/OOF_AGGREGATE/TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv

(cd "$PKG" && sha256sum -c SHA256SUMS_IMPLEMENTATION_V1)
"$PY" - "$PKG/IMPLEMENTATION_FREEZE_V1.json" "$PKG" <<'PY'
import hashlib,json,pathlib,sys
freeze=json.loads(pathlib.Path(sys.argv[1]).read_text());root=pathlib.Path(sys.argv[2])
assert freeze['status']=='FROZEN_AFTER_LOCAL_TESTS_BEFORE_NODE1_OOF_EXECUTION'
assert freeze['tests']=={'count':2,'status':'OK','log_sha256':freeze['files']['TEST_RESULTS_V1.log']}
assert freeze['input_access']=={'open_development_rows':0,'frozen_test_rows':0}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,expected in freeze['files'].items():assert sha(root/name)==expected,(name,sha(root/name),expected)
PY

test ! -e "$OUT"
printf '{"status":"RUNNING_V2_15_RAW_MULTIMODAL_OOF","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$ROOT/status/V2_15_LIVE_STATUS.json"
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8 \
"$PY" "$PKG/src/run_v215_raw_multimodal_top5_oof_v1.py" \
  --contract "$PKG/CONTRACT_V1.json" \
  --raw-multimodal "$RAW" \
  --assignment "$ASSIGN" \
  --legacy-oof "$LEGACY" \
  --l1-oof "$L1" \
  --output-dir "$OUT" > "$ROOT/status/V2_15_PRODUCTION.log" 2>&1
cp "$OUT/RUN_RECEIPT.json" "$ROOT/status/V2_15_TERMINAL.json"
