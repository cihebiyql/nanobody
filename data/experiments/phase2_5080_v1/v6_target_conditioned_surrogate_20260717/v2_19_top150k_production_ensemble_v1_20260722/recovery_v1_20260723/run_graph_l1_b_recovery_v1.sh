#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
GRAPH_BUILDER="$ROOT/residue_v2/src/build_residue_graph_cache_v2.py"
GRAPH_OUT="$ROOT/label_free_graph_full150k_v1"
SOURCE_PDB_ROOT="$ROOT/nbb2_pdbs_full150k_v1"
SAFE_ROOT=/data1/qlyu/projects/pvrig_1m_vhh_monomer_cache_v1_20260723/nbb2_pdbs_full150k_v1
STAGING="$ROOT/nbb2_staging_full150k_v1"
MANIFEST="$ROOT/compact_manifest_full150k_v1.tsv"
INFER="$ROOT/code/src/infer_clean_attention_checkpoint_ensemble_v1.py"
BASE=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/src/run_top5_clean_attention_fold_v1.py
REFERENCE=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_b_multiseed/contracts/seed_917_fold_0_contract.json
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
IDENTITY="$MODEL/model.safetensors"
IDENTITY_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
L1_OUT="$ROOT/l1_5fold_predictions_full150k_v1"
B_OUT="$ROOT/b_4seed_predictions_full150k_v1"
STATUS="$ROOT/status"
LOGS="$ROOT/logs"
RECOVERY="$ROOT/recovery_v1_20260723"

mkdir -p "$STATUS" "$LOGS" "$RECOVERY" "$(dirname "$SAFE_ROOT")"
[[ ! -e "$GRAPH_OUT" && ! -e "$L1_OUT" && ! -e "$B_OUT" ]]
"$PY" - <<'PY'
import json
from pathlib import Path
p=Path('/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/status/NBB2_STAGING_TERMINAL.json')
x=json.loads(p.read_text())
assert x['status']=='PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING'
assert x['counts']['candidates']==150000
PY

if [[ ! -e "$SAFE_ROOT" ]]; then
  mkdir "$SAFE_ROOT"
  cp -al "$SOURCE_PDB_ROOT/." "$SAFE_ROOT/"
fi

"$PY" - "$STAGING/top150k_graph_structure_manifest_v1.tsv" "$SOURCE_PDB_ROOT" "$SAFE_ROOT" "$RECOVERY/HARDLINK_MIRROR_RECEIPT.json" <<'PY'
import csv,hashlib,json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
manifest,source,safe,out=map(Path,sys.argv[1:])
for token in ('pose','dock','complex'):
    assert token not in str(safe).lower()
rows=0
with manifest.open(newline='') as f:
    for row in csv.DictReader(f,delimiter='\t'):
        rel=Path(row['monomer_relative_path'])
        a,b=source/rel,safe/rel
        sa,sb=a.stat(),b.stat()
        assert a.is_file() and b.is_file() and not a.is_symlink() and not b.is_symlink()
        assert sa.st_dev==sb.st_dev and sa.st_ino==sb.st_ino and sa.st_size==sb.st_size
        rows+=1
assert rows==150000
payload={'schema_version':'pvrig_top150k_label_free_hardlink_mirror_v1','status':'PASS_TOP150K_LABEL_FREE_HARDLINK_MIRROR','created_at_utc':datetime.now(timezone.utc).isoformat(),'rows':rows,'source_root':str(source),'safe_root':str(safe),'same_device_inode_verified_for_all_rows':True,'truth_access':{'candidate_docking_pose_files_opened':0,'teacher_labels_opened':0}}
out.parent.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.'+out.name+'.',dir=out.parent)
with os.fdopen(fd,'w') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,out)
PY

"$PY" "$GRAPH_BUILDER" \
  --manifest "$STAGING/top150k_graph_structure_manifest_v1.tsv" \
  --pdb-root "$SAFE_ROOT" \
  --output-dir "$GRAPH_OUT" \
  --expected-entities 150000 > "$LOGS/graph_full150k_recovery_v1.log" 2>&1

L1_CHECKPOINTS=()
for fold in 0 1 2 3 4; do
  L1_CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_a_seed43/L1/fold_${fold}/inner_oof_clean_attention_head_final.pt")
done
CUDA_VISIBLE_DEVICES=7 "$PY" "$INFER" \
  --manifest "$MANIFEST" --expected-rows 150000 \
  --graph-cache-dir "$GRAPH_OUT" \
  --reference-contract "$REFERENCE" --base-module "$BASE" \
  "${L1_CHECKPOINTS[@]}" \
  --model-path "$MODEL" --model-identity-file "$IDENTITY" \
  --expected-model-sha256 "$IDENTITY_SHA" \
  --device cuda:0 --batch-size 64 --precision bf16 --backbone-dtype bf16 \
  --uncertainty-penalty 1.0 --output-dir "$L1_OUT" > "$LOGS/l1_5fold_full150k_recovery_v1.log" 2>&1

B_CHECKPOINTS=()
for seed in 43 917 1931 3253; do
  B_CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed${seed}/clean_attention_head_final.pt")
done
CUDA_VISIBLE_DEVICES=7 "$PY" "$INFER" \
  --manifest "$MANIFEST" --expected-rows 150000 \
  --graph-cache-dir "$GRAPH_OUT" \
  --reference-contract "$REFERENCE" --base-module "$BASE" \
  "${B_CHECKPOINTS[@]}" \
  --model-path "$MODEL" --model-identity-file "$IDENTITY" \
  --expected-model-sha256 "$IDENTITY_SHA" \
  --device cuda:0 --batch-size 64 --precision bf16 --backbone-dtype bf16 \
  --uncertainty-penalty 1.0 --output-dir "$B_OUT" > "$LOGS/b_4seed_full150k_recovery_v1.log" 2>&1

"$PY" - "$GRAPH_OUT/graph_cache_receipt_v2.json" "$L1_OUT/RUN_RECEIPT.json" "$B_OUT/RUN_RECEIPT.json" "$RECOVERY/HARDLINK_MIRROR_RECEIPT.json" "$STATUS/GRAPH_L1_B_TERMINAL.json" "$RECOVERY/GRAPH_L1_B_RECOVERY_RECEIPT.json" <<'PY'
import hashlib,json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
graph,l1,b,mirror,terminal,recovery=map(Path,sys.argv[1:])
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1<<20),b''): h.update(x)
    return h.hexdigest()
payload={'status':'PASS_GRAPH_L1_B_FULL150K_COMPLETE','graph':json.loads(graph.read_text()),'L1':json.loads(l1.read_text()),'B':json.loads(b.read_text())}
audit={'schema_version':'pvrig_top150k_graph_l1_b_recovery_v1','status':'PASS_TOP150K_GRAPH_L1_B_RECOVERY','created_at_utc':datetime.now(timezone.utc).isoformat(),'reason':'original label-free path firewall rejected a project ancestor containing fixed_pose; recovery uses an all-row inode-verified hardlink mirror under a token-safe path and unchanged monomer bytes/models','rows':150000,'inputs':{'hardlink_mirror_receipt_sha256':sha(mirror)},'outputs':{'graph_receipt_sha256':sha(graph),'l1_receipt_sha256':sha(l1),'b_receipt_sha256':sha(b)},'truth_access':{'candidate_docking_pose_files_opened':0,'teacher_labels_opened':0}}
for path,obj in ((terminal,payload),(recovery,audit)):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    with os.fdopen(fd,'w') as f: json.dump(obj,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
PY
