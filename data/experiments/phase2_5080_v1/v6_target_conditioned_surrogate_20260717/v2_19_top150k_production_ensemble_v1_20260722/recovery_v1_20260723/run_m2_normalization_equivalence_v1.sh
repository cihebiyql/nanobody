#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/recovery_v1_20260723"
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
M2_SCRIPT="$ROOT/code/src/materialize_full10644_m2_features_v1.py"
OLD_ROOT=/data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/full10644_features
OLD_MANIFEST="$OLD_ROOT/canonical10644_structure_manifest_v1.tsv"
OLD_FEATURES="$OLD_ROOT/canonical10644_m2_126d_features_v1.tsv"
SEQ_MANIFEST=/data1/qlyu/projects/pvrig_v2_11_canonical10644_label_free_graph_v1_20260721/prepared_graph_v1/canonical10644_label_free_graph_input_manifest_v1.tsv
OUT=/data1/qlyu/projects/pvrig_top150k_recovery_validation_v1_20260723
NORMALIZED="$OUT/m2_ca_normalized_10644_v1"
FEATURES="$OUT/m2_ca_normalized_features_10644_v1"
RECEIPT="$OUT/M2_CA_NORMALIZATION_EQUIVALENCE_V1.json"

mkdir -p "$OUT"
[[ ! -e "$NORMALIZED" && ! -e "$FEATURES" && ! -e "$RECEIPT" ]]
"$PY" "$PKG/normalize_m2_ca_monomers_v1.py" --m2-manifest "$OLD_MANIFEST" --sequence-manifest "$SEQ_MANIFEST" \
  --output-dir "$NORMALIZED" --expected-rows 10644 --workers 32 > "$OUT/normalize_10644.log" 2>&1
NM="$NORMALIZED/normalized_m2_structure_manifest_v1.tsv"; NM_SHA="$(sha256sum "$NM"|awk '{print $1}')"
"$PY" "$M2_SCRIPT" --input-manifest "$NM" --expected-manifest-sha256 "$NM_SHA" --output-dir "$FEATURES" \
  --expected-rows 10644 --workers 32 > "$OUT/extract_10644.log" 2>&1
"$PY" - "$OLD_FEATURES" "$FEATURES/canonical10644_m2_126d_features_v1.tsv" "$RECEIPT" <<'PY'
import csv,hashlib,json,math,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
old,new,out=map(Path,sys.argv[1:])
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
with old.open(newline='') as f: a=list(csv.DictReader(f,delimiter='\t'))
with new.open(newline='') as f: b=list(csv.DictReader(f,delimiter='\t'))
assert len(a)==len(b)==10644 and [r['candidate_id'] for r in a]==[r['candidate_id'] for r in b]
meta={'schema_version','candidate_id','sequence_sha256','parent_framework_cluster','model_split','asset_lane','monomer_sha256','claim_boundary'}
features=[k for k in a[0] if k not in meta]; assert len(features)==126
max_abs=0.0
for ra,rb in zip(a,b):
 for field in features: max_abs=max(max_abs,abs(float(ra[field])-float(rb[field])))
assert max_abs <= 1e-8
payload={'schema_version':'pvrig_m2_ca_normalization_equivalence_v1','status':'PASS_M2_CA_NORMALIZATION_FULL10644_EQUIVALENCE','created_at_utc':datetime.now(timezone.utc).isoformat(),'rows':10644,'features':126,'max_abs_feature_difference':max_abs,'inputs':{'original_features_sha256':sha(old),'normalized_features_sha256':sha(new)},'truth_access':{'candidate_docking_pose_files_opened':0,'teacher_labels_opened':0}}
fd,tmp=tempfile.mkstemp(prefix='.'+out.name+'.',dir=out.parent)
with os.fdopen(fd,'w') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,out); print(json.dumps(payload,sort_keys=True))
PY
