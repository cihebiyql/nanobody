#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_12_oof_early_enrichment_portfolio_v1_20260722
OOF_ROOT=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
TEACHER=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/prepared/primary_D1_canonical10644_teacher.tsv
LEGACY_OOF=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/TRAIN_INNER_OOF_PREDICTIONS.tsv
LEGACY_DEV=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/OPEN_DEVELOPMENT_PREDICTIONS.tsv
CLEAN_DEV=/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed43/development_predictions.tsv
CLEAN_OOF=$OOF_ROOT/training/oof_seed43_v1/OOF_AGGREGATE/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv
OUT=$ROOT/results/open_development_v1
STATUS=$ROOT/status

mkdir -p "$STATUS"
[[ ! -e "$OUT" ]] || { echo "output_exists:$OUT" >&2; exit 4; }
(cd "$ROOT" && sha256sum -c SHA256SUMS)
sha256sum -c <<'EOF'
46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3  /data1/qlyu/projects/pvrig_v29_canonical_merged_teacher_v1_20260721/prepared/primary_D1_canonical10644_teacher.tsv
e1a5553e67b0f2d60a4c690756f4f2cbe81de53a669dc41cf6fee883f4d8847b  /data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/TRAIN_INNER_OOF_PREDICTIONS.tsv
2e335f1f08ee4697e234a52d0fe17e818375ffe09f872a8eda8b34e5403c44f1  /data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/OPEN_DEVELOPMENT_PREDICTIONS.tsv
f38e39310c9a8b31c46651319b3947b540b03f4f2370aaeaae7c8a5801ba4d52  /data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed43/development_predictions.tsv
EOF

while [[ ! -f "$OOF_ROOT/status/TERMINAL.json" ]]; do
  printf '{"status":"WAITING_CLEAN_ATTENTION_OOF","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/LIVE_STATUS.json"
  sleep 60
done

"$PY" - "$OOF_ROOT/status/TERMINAL.json" <<'PY'
import json, pathlib, sys
payload=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert payload['status']=='PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_AND_AGGREGATE', payload
assert payload['open_development_access_count']==0
assert payload['frozen_test_access_count']==0
PY

CLEAN_OOF_SHA=$(sha256sum "$CLEAN_OOF" | cut -d' ' -f1)
mkdir -p "$ROOT/results"
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 \
  "$PY" "$ROOT/src/run_oof_early_enrichment_portfolio_v1.py" \
    --contract "$ROOT/PORTFOLIO_CONTRACT_V1.json" \
    --teacher "$TEACHER" \
    --teacher-sha256 46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3 \
    --legacy-oof "$LEGACY_OOF" \
    --legacy-oof-sha256 e1a5553e67b0f2d60a4c690756f4f2cbe81de53a669dc41cf6fee883f4d8847b \
    --clean-oof "$CLEAN_OOF" \
    --clean-oof-sha256 "$CLEAN_OOF_SHA" \
    --legacy-development "$LEGACY_DEV" \
    --legacy-development-sha256 2e335f1f08ee4697e234a52d0fe17e818375ffe09f872a8eda8b34e5403c44f1 \
    --clean-development "$CLEAN_DEV" \
    --clean-development-sha256 f38e39310c9a8b31c46651319b3947b540b03f4f2370aaeaae7c8a5801ba4d52 \
    --output-dir "$OUT" \
    > "$STATUS/PORTFOLIO.log" 2>&1

"$PY" - "$OUT" "$CLEAN_OOF_SHA" > "$STATUS/TERMINAL.json" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); clean_sha=sys.argv[2]
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
metrics=json.loads((root/'METRICS.json').read_text())
assert metrics['status']=='PASS_OPEN_DEVELOPMENT_PORTFOLIO_COMPLETE'
print(json.dumps({
  'schema_version':'pvrig_v2_12_portfolio_node1_terminal_v1',
  'status':'PASS_V2_12_OPEN_DEVELOPMENT_PORTFOLIO_COMPLETE',
  'clean_oof_sha256':clean_sha,
  'outputs':{name:sha(root/name) for name in ('METRICS.json','OPEN_DEVELOPMENT_PORTFOLIO_PREDICTIONS.tsv','MODEL_ARTIFACT.pkl','RUN_RECEIPT.json')},
  'development_used_for_fit_or_selection':False,
  'frozen_test_access_count':0,
},indent=2,sort_keys=True))
PY

