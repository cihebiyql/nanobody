#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
STAGING="$ROOT/nbb2_staging_full150k_v1"
M2_SCRIPT="$ROOT/code/src/materialize_full10644_m2_features_v1.py"
INFER_SCRIPT="$ROOT/code/src/run_v2_11_production_multimodal_inference_v1.py"
M2_OUT="$ROOT/m2_126d_full150k_v1"
ESM_CACHE="$ROOT/esm2_650m_pooled_full150k_v1"
COMPACT="$ROOT/stage0_label_free_priors_v1/STAGE0_LABEL_FREE_PRIORS.tsv"
COMPACT_SHA=15277b5f56d6274989479874dee4ff9639405f63fac5c18dd33b974eeea460bb
ARTIFACT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/MODEL_ARTIFACT.pkl
ARTIFACT_SHA=02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d
PRED_OUT="$ROOT/s0_m2_predictions_full150k_v1"
STATUS="$ROOT/status"
LOGS="$ROOT/logs"
RECOVERY="$ROOT/recovery_v1_20260723"

mkdir -p "$STATUS" "$LOGS" "$RECOVERY"
[[ ! -e "$M2_OUT" && ! -e "$PRED_OUT" ]]
"$PY" - <<'PY'
import json
from pathlib import Path
p=Path('/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/status/NBB2_STAGING_TERMINAL.json')
x=json.loads(p.read_text())
assert x['status']=='PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING'
assert x['counts']['candidates']==150000
PY

MANIFEST="$STAGING/top150k_m2_structure_manifest_v1.tsv"
MANIFEST_SHA="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["outputs"]["top150k_m2_structure_manifest_v1.tsv"])' "$STAGING/top150k_nbb2_staging_receipt_v1.json")"
[[ "$(sha256sum "$MANIFEST" | awk '{print $1}')" == "$MANIFEST_SHA" ]]
[[ "$(sha256sum "$COMPACT" | awk '{print $1}')" == "$COMPACT_SHA" ]]
[[ "$(sha256sum "$ARTIFACT" | awk '{print $1}')" == "$ARTIFACT_SHA" ]]

"$PY" "$M2_SCRIPT" \
  --input-manifest "$MANIFEST" \
  --expected-manifest-sha256 "$MANIFEST_SHA" \
  --output-dir "$M2_OUT" \
  --expected-rows 150000 \
  --workers 32 > "$LOGS/m2_126d_full150k_recovery_v1.log" 2>&1

M2_TSV="$M2_OUT/canonical10644_m2_126d_features_v1.tsv"
M2_SHA="$(sha256sum "$M2_TSV" | awk '{print $1}')"
"$PY" "$INFER_SCRIPT" \
  --compact-manifest "$COMPACT" \
  --expected-compact-manifest-sha256 "$COMPACT_SHA" \
  --esm2-pooled-cache "$ESM_CACHE" \
  --m2-features "$M2_TSV" \
  --expected-m2-features-sha256 "$M2_SHA" \
  --model-artifact "$ARTIFACT" \
  --expected-model-artifact-sha256 "$ARTIFACT_SHA" \
  --expected-rows 150000 \
  --output-dir "$PRED_OUT" > "$LOGS/s0_m2_predictions_full150k_recovery_v1.log" 2>&1

"$PY" - "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" "$PRED_OUT/RUN_RECEIPT.json" "$STATUS/M2_S0M2_TERMINAL.json" "$RECOVERY/M2_S0M2_RECOVERY_RECEIPT.json" <<'PY'
import hashlib,json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
m2,pred,terminal,recovery=map(Path,sys.argv[1:])
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
payload={"status":"PASS_M2_AND_S0M2_FULL150K_COMPLETE","m2":json.loads(m2.read_text()),"predictions":json.loads(pred.read_text())}
audit={"schema_version":"pvrig_top150k_m2_s0m2_recovery_v1","status":"PASS_TOP150K_M2_S0M2_RECOVERY","created_at_utc":datetime.now(timezone.utc).isoformat(),"reason":"original launcher used system python3 without numpy; recovery uses frozen pvrig-v6-tc Python and unchanged model/data artifacts","rows":150000,"inputs":{"staging_terminal_sha256":sha(Path('/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/status/NBB2_STAGING_TERMINAL.json'))},"outputs":{"m2_receipt_sha256":sha(m2),"prediction_receipt_sha256":sha(pred)},"truth_access":{"candidate_docking_pose_files_opened":0,"teacher_labels_opened":0}}
for path,obj in ((Path(terminal),payload),(Path(recovery),audit)):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    with os.fdopen(fd,'w') as f: json.dump(obj,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
PY
