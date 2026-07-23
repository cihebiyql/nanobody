#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/recovery_v1_20260723"
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
[[ ! -d /proc/743054 ]]
[[ ! -e "$STATUS/M2_S0M2_TERMINAL.json" && ! -e "$M2_OUT" && ! -e "$PRED_OUT" ]]

MANIFEST="$STAGING/top150k_m2_structure_manifest_v1.tsv"
ENV_RECEIPT="$RECOVERY/M2_S0M2_ENVIRONMENT_PREFLIGHT_V2.json"
"$PY" - "$MANIFEST" "$M2_SCRIPT" "$INFER_SCRIPT" "$COMPACT" "$ARTIFACT" "$ESM_CACHE/embedding_cache_receipt.json" "$STATUS/NBB2_STAGING_TERMINAL.json" "$ENV_RECEIPT" <<'PY'
import hashlib,json,os,platform,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
import numpy,scipy,sklearn,torch
paths=list(map(Path,sys.argv[1:-1])); out=Path(sys.argv[-1])
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
for p in paths:
 assert p.is_file() and not p.is_symlink(),p
stage=json.loads(paths[-1].read_text()); assert stage['status']=='PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING' and stage['counts']['candidates']==150000
esm=json.loads(paths[-2].read_text()); assert esm['status']=='PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE' and esm['rows']==150000 and len(esm['shards'])==30
for shard in esm['shards']:
 p=Path(shard['path']); assert sha(p)==shard['sha256']
payload={'schema_version':'pvrig_top150k_m2_s0m2_environment_preflight_v2','status':'PASS_TOP150K_M2_S0M2_ENVIRONMENT_PREFLIGHT','created_at_utc':datetime.now(timezone.utc).isoformat(),'runtime':{'executable':os.path.realpath(sys.executable),'python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__,'torch':torch.__version__,'cuda_available':torch.cuda.is_available()},'inputs':{str(p):sha(p) for p in paths},'esm_shards':{Path(x['path']).name:x['sha256'] for x in esm['shards']},'truth_access':{'candidate_docking_pose_files_opened':0,'teacher_labels_opened':0}}
assert sys.executable=='/data1/qlyu/software/envs/pvrig-v6-tc/bin/python'
assert payload['runtime']['executable']=='/data1/qlyu/anaconda3/envs/boltz/bin/python3.11'
out.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix='.'+out.name+'.',dir=out.parent)
with os.fdopen(fd,'w') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,out)
PY

MANIFEST_SHA="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["outputs"]["top150k_m2_structure_manifest_v1.tsv"])' "$STAGING/top150k_nbb2_staging_receipt_v1.json")"
[[ "$(sha256sum "$MANIFEST" | awk '{print $1}')" == "$MANIFEST_SHA" ]]
[[ "$(sha256sum "$COMPACT" | awk '{print $1}')" == "$COMPACT_SHA" ]]
[[ "$(sha256sum "$ARTIFACT" | awk '{print $1}')" == "$ARTIFACT_SHA" ]]

"$PY" "$M2_SCRIPT" --input-manifest "$MANIFEST" --expected-manifest-sha256 "$MANIFEST_SHA" \
  --output-dir "$M2_OUT" --expected-rows 150000 --workers 32 > "$LOGS/m2_126d_full150k_recovery_v2.log" 2>&1
M2_TSV="$M2_OUT/canonical10644_m2_126d_features_v1.tsv"
M2_SHA="$(sha256sum "$M2_TSV" | awk '{print $1}')"
"$PY" "$INFER_SCRIPT" --compact-manifest "$COMPACT" --expected-compact-manifest-sha256 "$COMPACT_SHA" \
  --esm2-pooled-cache "$ESM_CACHE" --m2-features "$M2_TSV" --expected-m2-features-sha256 "$M2_SHA" \
  --model-artifact "$ARTIFACT" --expected-model-artifact-sha256 "$ARTIFACT_SHA" --expected-rows 150000 \
  --output-dir "$PRED_OUT" > "$LOGS/s0_m2_predictions_full150k_recovery_v2.log" 2>&1

"$PY" "$PKG/validate_m2_s0m2_recovery_v2.py" \
  --m2-tsv "$M2_TSV" --prediction-tsv "$PRED_OUT/PRODUCTION_PREDICTIONS_RANK_READY.tsv" \
  --m2-receipt "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" --prediction-receipt "$PRED_OUT/RUN_RECEIPT.json" \
  --staging-terminal "$STATUS/NBB2_STAGING_TERMINAL.json" --environment-preflight "$ENV_RECEIPT" \
  --expected-rows 150000 --receipt "$RECOVERY/M2_S0M2_RECOVERY_VALIDATION_V2.json" > "$LOGS/m2_s0m2_recovery_validation_v2.log" 2>&1

"$PY" - "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" "$PRED_OUT/RUN_RECEIPT.json" "$RECOVERY/M2_S0M2_RECOVERY_VALIDATION_V2.json" "$STATUS/M2_S0M2_TERMINAL.json" <<'PY'
import json,os,sys,tempfile
from pathlib import Path
m2,pred,validation,target=map(Path,sys.argv[1:]); assert json.loads(validation.read_text())['status']=='PASS_TOP150K_M2_S0M2_RECOVERY_VALIDATION'
payload={'status':'PASS_M2_AND_S0M2_FULL150K_COMPLETE','m2':json.loads(m2.read_text()),'predictions':json.loads(pred.read_text()),'recovery_validation':json.loads(validation.read_text())}
fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
with os.fdopen(fd,'w') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,target)
PY
