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
TRAIN_ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/full10644_features
ARTIFACT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/MODEL_ARTIFACT.pkl
NORMALIZATION=/data1/qlyu/projects/pvrig_1m_vhh_m2_ca_cache_v1_20260723/NORMALIZATION_RECEIPT.json
EQUIVALENCE=/data1/qlyu/projects/pvrig_top150k_recovery_validation_v1_20260723/M2_CA_NORMALIZATION_EQUIVALENCE_V1.json
FREEZE="$PKG/IMPLEMENTATION_FREEZE_V2_3_1.json"
VALIDATION="$RECOVERY/M2_S0M2_RECOVERY_VALIDATION_V2_3_1.json"
TERMINAL="$STATUS/M2_S0M2_TERMINAL.json"
OLD_TERMINAL_SHA=436906f47411a7840b5f5db4580886de57b1c7a9246d4b07fbfc168f5d4ea8a1

[[ -n "${EXPECTED_FREEZE_SHA256:-}" ]]
[[ "$(sha256sum "$FREEZE" | awk '{print $1}')" == "$EXPECTED_FREEZE_SHA256" ]]
[[ ! -e "$VALIDATION" ]]
[[ ! -e "$STATUS/GRAPH_L1_B_TERMINAL.json" ]]
[[ ! -e "$STATUS/FOUR_MODEL_PRELIMINARY_TERMINAL.json" ]]
[[ "$(sha256sum "$TERMINAL" | awk '{print $1}')" == "$OLD_TERMINAL_SHA" ]]

"$PY" - "$FREEZE" "$PKG" <<'PY'
import hashlib,json,sys
from pathlib import Path
freeze=Path(sys.argv[1]); root=Path(sys.argv[2]); data=json.loads(freeze.read_text())
for name,expected in data['files'].items():
    observed=hashlib.sha256((root/name).read_bytes()).hexdigest()
    assert observed==expected,(name,observed,expected)
assert data['status']=='FROZEN_BEFORE_V2_3_1_TERMINAL_SUPERSESSION'
PY

cat <<'EOF' | sha256sum -c -
15c3131b17308766c1108b282b26ab28b4fb5234872c31feadbed0d1bdd06745  /data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/m2_126d_full150k_v1/canonical10644_m2_126d_features_v1.tsv
9ed66c7b64512a02ecd3fbf51935bcb5d9a358d286036ed298d4675f6b9a1b1c  /data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/m2_126d_full150k_v1/canonical10644_m2_126d_features_v1.receipt.json
913e78646cc8c65d939cf28fc793d3ebe24bdd0fc6fb1cc900c315b873da28f8  /data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/s0_m2_predictions_full150k_v1/PRODUCTION_PREDICTIONS_RANK_READY.tsv
d713e14a62954f74db2203fb6c276dfc051ae6c3557389d4ff6c598d776cebd0  /data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/s0_m2_predictions_full150k_v1/RUN_RECEIPT.json
e4a50fce1802993305b8f044d9551b59300c07b3c7c02593e2d1d9ede5cdc9ca  /data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/full10644_features/canonical10644_m2_126d_features_v1.tsv
6b338342ebed3b9c8341d6bd268ec7ad8510133b67c41b3cfcb3ca5f2452c5cd  /data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/full10644_features/canonical10644_m2_126d_features_v1.receipt.json
02f71b30e70a3afe326d1a6f9b8fffb5c05fb1249a9c75ac8887b3ffadf5395d  /data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/MODEL_ARTIFACT.pkl
23da75a74756984e23a40bdf5a6a184773734d341935fd2f9cc6e9b92ad8ba8b  /data1/qlyu/projects/pvrig_1m_vhh_m2_ca_cache_v1_20260723/NORMALIZATION_RECEIPT.json
85b1cfb80ba2088edf9f0258b738dff240240b2b93eaaaeccb411ead6bd7d111  /data1/qlyu/projects/pvrig_top150k_recovery_validation_v1_20260723/M2_CA_NORMALIZATION_EQUIVALENCE_V1.json
EOF

"$PY" "$PKG/test_validate_m2_s0m2_recovery_v2_3_1.py"
"$PY" "$PKG/validate_m2_s0m2_recovery_v2_3_1.py" \
  --m2-tsv "$M2_OUT/canonical10644_m2_126d_features_v1.tsv" \
  --prediction-tsv "$PRED_OUT/PRODUCTION_PREDICTIONS_RANK_READY.tsv" \
  --m2-receipt "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" \
  --prediction-receipt "$PRED_OUT/RUN_RECEIPT.json" \
  --staging-terminal "$STATUS/NBB2_STAGING_TERMINAL.json" \
  --environment-preflight "$RECOVERY/M2_S0M2_ENVIRONMENT_PREFLIGHT_V2.json" \
  --training-m2-tsv "$TRAIN_ROOT/canonical10644_m2_126d_features_v1.tsv" \
  --training-m2-receipt "$TRAIN_ROOT/canonical10644_m2_126d_features_v1.receipt.json" \
  --model-artifact "$ARTIFACT" --normalization-receipt "$NORMALIZATION" \
  --equivalence-receipt "$EQUIVALENCE" --expected-rows 150000 --receipt "$VALIDATION"

"$PY" - "$TERMINAL" "$RECOVERY/M2_S0M2_TERMINAL_V2_3_SUPERSEDED_PRECONSUMPTION.json" \
  "$M2_OUT/canonical10644_m2_126d_features_v1.receipt.json" "$PRED_OUT/RUN_RECEIPT.json" \
  "$VALIDATION" "$NORMALIZATION" "$EQUIVALENCE" <<'PY'
import hashlib,json,os,shutil,sys,tempfile
from pathlib import Path
terminal,snapshot,m2,pred,validation,normalization,equivalence=map(Path,sys.argv[1:])
old_sha=hashlib.sha256(terminal.read_bytes()).hexdigest()
assert old_sha=='436906f47411a7840b5f5db4580886de57b1c7a9246d4b07fbfc168f5d4ea8a1'
shutil.copyfile(terminal,snapshot)
v=json.loads(validation.read_text()); assert v['status']=='PASS_TOP150K_M2_S0M2_RECOVERY_VALIDATION'
payload={
 'status':'PASS_M2_AND_S0M2_FULL150K_COMPLETE',
 'terminal_schema_version':'pvrig_top150k_m2_s0m2_terminal_v2_3_1',
 'supersedes_terminal_sha256':old_sha,
 'm2':json.loads(m2.read_text()), 'predictions':json.loads(pred.read_text()),
 'recovery_validation':v, 'normalization':json.loads(normalization.read_text()),
 'equivalence':json.loads(equivalence.read_text()),
}
fd,tmp=tempfile.mkstemp(prefix='.'+terminal.name+'.',dir=terminal.parent)
with os.fdopen(fd,'w') as f:
 json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,terminal)
PY
