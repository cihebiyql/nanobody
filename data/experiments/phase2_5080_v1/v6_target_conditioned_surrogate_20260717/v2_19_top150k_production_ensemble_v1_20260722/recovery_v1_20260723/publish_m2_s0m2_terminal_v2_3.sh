#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/recovery_v1_20260723"
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
M2_OUT="$ROOT/m2_126d_full150k_v1"
PRED_OUT="$ROOT/s0_m2_predictions_full150k_v1"
RECOVERY="$ROOT/recovery_v1_20260723"
STATUS="$ROOT/status"
VALIDATION="$RECOVERY/M2_S0M2_RECOVERY_VALIDATION_V2_3.json"
TERMINAL="$STATUS/M2_S0M2_TERMINAL.json"

[[ ! -e "$TERMINAL" ]]
"$PY" "$PKG/test_validate_m2_s0m2_recovery_v2_3.py"
"$PY" "$PKG/validate_m2_s0m2_recovery_v2_3.py" \
  --m2-tsv "$M2_OUT/canonical10644_m2_126d_features_v1.tsv" \
  --prediction-tsv "$PRED_OUT/PRODUCTION_PREDICTIONS_RANK_READY.tsv" \
  --m2-receipt "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" \
  --prediction-receipt "$PRED_OUT/RUN_RECEIPT.json" \
  --staging-terminal "$STATUS/NBB2_STAGING_TERMINAL.json" \
  --environment-preflight "$RECOVERY/M2_S0M2_ENVIRONMENT_PREFLIGHT_V2.json" \
  --expected-rows 150000 --receipt "$VALIDATION"

"$PY" - "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" "$PRED_OUT/RUN_RECEIPT.json" "$VALIDATION" "$TERMINAL" <<'PY'
import json,os,sys,tempfile
from pathlib import Path
m2,pred,validation,target=map(Path,sys.argv[1:])
v=json.loads(validation.read_text())
assert v['status']=='PASS_TOP150K_M2_S0M2_RECOVERY_VALIDATION'
payload={
 'status':'PASS_M2_AND_S0M2_FULL150K_COMPLETE',
 'm2':json.loads(m2.read_text()),
 'predictions':json.loads(pred.read_text()),
 'recovery_validation':v,
 'normalization':json.loads(Path('/data1/qlyu/projects/pvrig_1m_vhh_m2_ca_cache_v1_20260723/NORMALIZATION_RECEIPT.json').read_text()),
 'equivalence':json.loads(Path('/data1/qlyu/projects/pvrig_top150k_recovery_validation_v1_20260723/M2_CA_NORMALIZATION_EQUIVALENCE_V1.json').read_text()),
}
target.parent.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
with os.fdopen(fd,'w') as f:
 json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,target)
PY
