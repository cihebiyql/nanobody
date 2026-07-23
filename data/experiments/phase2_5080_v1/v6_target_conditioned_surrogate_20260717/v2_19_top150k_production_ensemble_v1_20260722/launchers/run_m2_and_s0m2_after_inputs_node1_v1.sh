#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
M2_SCRIPT="$ROOT/code/src/materialize_full10644_m2_features_v1.py"
INFER_SCRIPT="$ROOT/code/src/run_v2_11_production_multimodal_inference_v1.py"
STAGING="$ROOT/nbb2_staging_full150k_v1"
M2_OUT="$ROOT/m2_126d_full150k_v1"
ESM_CACHE="$ROOT/esm2_650m_pooled_full150k_v1"
COMPACT="$ROOT/stage0_label_free_priors_v1/STAGE0_LABEL_FREE_PRIORS.tsv"
COMPACT_SHA=15277b5f56d6274989479874dee4ff9639405f63fac5c18dd33b974eeea460bb
ARTIFACT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/MODEL_ARTIFACT.pkl
ARTIFACT_SHA=02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d
PRED_OUT="$ROOT/s0_m2_predictions_full150k_v1"

mkdir -p "$ROOT/status" "$ROOT/logs"
cat > "$ROOT/status/M2_S0M2_WATCHER_LAUNCH_RECEIPT.json" <<JSON
{"status":"WAITING_FOR_STAGING_AND_ESM2","started_at":"$(date -u +%FT%TZ)"}
JSON

for _ in $(seq 1 17280); do
  [[ -f "$ROOT/status/NBB2_STAGING_TERMINAL.json" && -f "$ROOT/status/ESM2_650M_TERMINAL.json" ]] && break
  sleep 10
done
[[ -f "$ROOT/status/NBB2_STAGING_TERMINAL.json" && -f "$ROOT/status/ESM2_650M_TERMINAL.json" ]]

MANIFEST="$STAGING/top150k_m2_structure_manifest_v1.tsv"
MANIFEST_SHA="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["outputs"]["top150k_m2_structure_manifest_v1.tsv"])' "$STAGING/top150k_nbb2_staging_receipt_v1.json")"
[[ "$(sha256sum "$MANIFEST" | awk '{print $1}')" == "$MANIFEST_SHA" ]]
[[ "$(sha256sum "$COMPACT" | awk '{print $1}')" == "$COMPACT_SHA" ]]
[[ "$(sha256sum "$ARTIFACT" | awk '{print $1}')" == "$ARTIFACT_SHA" ]]

python3 "$M2_SCRIPT" \
  --input-manifest "$MANIFEST" \
  --expected-manifest-sha256 "$MANIFEST_SHA" \
  --output-dir "$M2_OUT" \
  --expected-rows 150000 \
  --workers 32 > "$ROOT/logs/m2_126d_full150k_v1.log" 2>&1

M2_TSV="$M2_OUT/canonical10644_m2_126d_features_v1.tsv"
M2_SHA="$(sha256sum "$M2_TSV" | awk '{print $1}')"
"$PYTHON" "$INFER_SCRIPT" \
  --compact-manifest "$COMPACT" \
  --expected-compact-manifest-sha256 "$COMPACT_SHA" \
  --esm2-pooled-cache "$ESM_CACHE" \
  --m2-features "$M2_TSV" \
  --expected-m2-features-sha256 "$M2_SHA" \
  --model-artifact "$ARTIFACT" \
  --expected-model-artifact-sha256 "$ARTIFACT_SHA" \
  --expected-rows 150000 \
  --output-dir "$PRED_OUT" > "$ROOT/logs/s0_m2_predictions_full150k_v1.log" 2>&1

python3 - "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" "$PRED_OUT/RUN_RECEIPT.json" "$ROOT/status/M2_S0M2_TERMINAL.json" <<'PY'
import json,sys
m2,pred,target=sys.argv[1:]
payload={"status":"PASS_M2_AND_S0M2_FULL150K_COMPLETE","m2":json.load(open(m2)),"predictions":json.load(open(pred))}
open(target,"w").write(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
