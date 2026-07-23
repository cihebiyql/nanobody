#!/usr/bin/env bash
set -euo pipefail
umask 027

ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
PKG="$ROOT/code/recovery_v1_20260723"
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
GRAPH_BUILDER="$ROOT/residue_v2/src/build_residue_graph_cache_v2.py"
GRAPH_OUT="$ROOT/label_free_graph_full150k_v1"
SOURCE_PDB_ROOT="$ROOT/nbb2_pdbs_full150k_v1"
SAFE_ROOT=/data1/qlyu/projects/pvrig_1m_vhh_monomer_cache_v2_20260723/nbb2_pdbs_full150k_v1
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
STATUS="$ROOT/status"; LOGS="$ROOT/logs"; RECOVERY="$ROOT/recovery_v1_20260723"

mkdir -p "$STATUS" "$LOGS" "$RECOVERY" "$(dirname "$SAFE_ROOT")"
[[ ! -d /proc/750700 ]]
[[ ! -e "$STATUS/GRAPH_L1_B_TERMINAL.json" && ! -e "$GRAPH_OUT" && ! -e "$L1_OUT" && ! -e "$B_OUT" && ! -e "$SAFE_ROOT" ]]
FREE_KIB="$(df -Pk /data1 | awk 'NR==2{print $4}')"; (( FREE_KIB >= 100*1024*1024 ))

"$PY" "$PKG/materialize_hardlink_mirror_v2.py" --mode create \
  --manifest "$STAGING/top150k_graph_structure_manifest_v1.tsv" --source-root "$SOURCE_PDB_ROOT" \
  --mirror-root "$SAFE_ROOT" --expected-rows 150000 --receipt "$RECOVERY/HARDLINK_MIRROR_CREATE_V2.json" \
  > "$LOGS/hardlink_mirror_create_v2.log" 2>&1

"$PY" "$GRAPH_BUILDER" --manifest "$STAGING/top150k_graph_structure_manifest_v1.tsv" --pdb-root "$SAFE_ROOT" \
  --output-dir "$GRAPH_OUT" --expected-entities 150000 > "$LOGS/graph_full150k_recovery_v2.log" 2>&1

"$PY" "$PKG/materialize_hardlink_mirror_v2.py" --mode validate \
  --manifest "$STAGING/top150k_graph_structure_manifest_v1.tsv" --source-root "$SOURCE_PDB_ROOT" \
  --mirror-root "$SAFE_ROOT" --expected-rows 150000 --receipt "$RECOVERY/HARDLINK_MIRROR_POST_GRAPH_V2.json" \
  > "$LOGS/hardlink_mirror_post_graph_v2.log" 2>&1

"$PY" - "$GRAPH_OUT/graph_cache_receipt_v2.json" "$GRAPH_OUT/graph_manifest_v2.tsv" "$STAGING/top150k_graph_structure_manifest_v1.tsv" <<'PY'
import csv,hashlib,json,sys
from pathlib import Path
receipt,graph_manifest,input_manifest=map(Path,sys.argv[1:]); x=json.loads(receipt.read_text())
assert x['status']=='PASS_LABEL_FREE_MONOMER_GRAPH_CACHE' and x['counts']['entities']==150000
assert x['forbidden_model_features']==['teacher_source','candidate_docking_pose','absolute_coordinate_mlp_input']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
assert x['input_manifest_sha256']==sha(input_manifest)
assert x['outputs']['graph_manifest_v2.tsv']==sha(graph_manifest)
with graph_manifest.open() as f: assert sum(1 for _ in f)-1==150000
with input_manifest.open(newline='') as f:
 fields=next(csv.reader(f,delimiter='\t'))
 assert not any(any(t in field.lower() for t in ('teacher_source','docking_pose','geometry_label')) for field in fields)
PY

L1_CHECKPOINTS=(); for fold in 0 1 2 3 4; do L1_CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/training/phase_a_seed43/L1/fold_${fold}/inner_oof_clean_attention_head_final.pt"); done
CUDA_VISIBLE_DEVICES=7 "$PY" "$INFER" --manifest "$MANIFEST" --expected-rows 150000 --graph-cache-dir "$GRAPH_OUT" \
  --reference-contract "$REFERENCE" --base-module "$BASE" "${L1_CHECKPOINTS[@]}" --model-path "$MODEL" \
  --model-identity-file "$IDENTITY" --expected-model-sha256 "$IDENTITY_SHA" --device cuda:0 --batch-size 64 \
  --precision bf16 --backbone-dtype bf16 --uncertainty-penalty 1.0 --output-dir "$L1_OUT" > "$LOGS/l1_5fold_full150k_recovery_v2.log" 2>&1

B_CHECKPOINTS=(); for seed in 43 917 1931 3253; do B_CHECKPOINTS+=(--checkpoint "/data1/qlyu/projects/pvrig_v2_11_full10644_clean_attention_v1_20260722/training/4seed_v1/D1_seed${seed}/clean_attention_head_final.pt"); done
CUDA_VISIBLE_DEVICES=7 "$PY" "$INFER" --manifest "$MANIFEST" --expected-rows 150000 --graph-cache-dir "$GRAPH_OUT" \
  --reference-contract "$REFERENCE" --base-module "$BASE" "${B_CHECKPOINTS[@]}" --model-path "$MODEL" \
  --model-identity-file "$IDENTITY" --expected-model-sha256 "$IDENTITY_SHA" --device cuda:0 --batch-size 64 \
  --precision bf16 --backbone-dtype bf16 --uncertainty-penalty 1.0 --output-dir "$B_OUT" > "$LOGS/b_4seed_full150k_recovery_v2.log" 2>&1

"$PY" - "$GRAPH_OUT/graph_cache_receipt_v2.json" "$L1_OUT/RUN_RECEIPT.json" "$B_OUT/RUN_RECEIPT.json" "$RECOVERY/HARDLINK_MIRROR_CREATE_V2.json" "$RECOVERY/HARDLINK_MIRROR_POST_GRAPH_V2.json" "$STATUS/GRAPH_L1_B_TERMINAL.json" <<'PY'
import hashlib,json,os,sys,tempfile
from pathlib import Path
graph,l1,b,pre,post,target=map(Path,sys.argv[1:])
g,lr,br=map(lambda p:json.loads(p.read_text()),(graph,l1,b))
assert g['counts']['entities']==150000
for x in (lr,br): assert x['status']=='PASS_TRUTH_FREE_CLEAN_ATTENTION_CHECKPOINT_ENSEMBLE_INFERENCE' and x['counts']['rows']==150000 and x['input_firewall']['truth_fields_read']==0 and x['input_firewall']['docking_pose_files_opened']==0
payload={'status':'PASS_GRAPH_L1_B_FULL150K_COMPLETE','graph':g,'L1':lr,'B':br,'hardlink_mirror_pre':json.loads(pre.read_text()),'hardlink_mirror_post':json.loads(post.read_text())}
fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
with os.fdopen(fd,'w') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(tmp,target)
PY
