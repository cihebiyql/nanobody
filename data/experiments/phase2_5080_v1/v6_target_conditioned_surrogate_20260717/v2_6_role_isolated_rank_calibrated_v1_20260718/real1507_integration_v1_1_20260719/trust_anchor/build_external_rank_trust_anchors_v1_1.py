#!/usr/bin/env python3
"""Materialize immutable pre-runtime split/label trust anchors for V2.6 V1.1."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, json, sys
from collections import defaultdict
from pathlib import Path

SCHEMA="pvrig_v2_6_external_rank_split_label_trust_anchor_v1"
TEACHER_SHA="47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
MANIFEST_SHA="b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073"
RANK_SHA="b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec"
class BuildError(RuntimeError): pass
def require(x,m):
    if not x: raise BuildError(m)
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def atomic_json(path,payload):
    tmp=path.with_name('.'+path.name+'.tmp')
    tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    tmp.replace(path)
def load_core(path):
    require(path.is_file() and not path.is_symlink(),'rank_core_not_regular')
    require(sha(path)==RANK_SHA,'rank_core_sha_mismatch')
    spec=importlib.util.spec_from_file_location('pvrig_v26_rank_anchor_core',path)
    require(spec and spec.loader,'rank_core_import_spec')
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod)
    return mod
def read(path,expected):
    require(path.is_file() and not path.is_symlink(),f'input_not_regular:{path}')
    require(sha(path)==expected,f'input_sha_mismatch:{path.name}')
    with path.open(newline='',encoding='utf-8') as f: return list(csv.DictReader(f,delimiter='\t'))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--teacher',type=Path,required=True); ap.add_argument('--inner-manifest',type=Path,required=True); ap.add_argument('--rank-core',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True)
    a=ap.parse_args(); core=load_core(a.rank_core); teachers=read(a.teacher,TEACHER_SHA); manifest=read(a.inner_manifest,MANIFEST_SHA)
    require(len(teachers)==1507,'teacher_count'); require(len(manifest)==30140,'manifest_count')
    labels={}
    for r in teachers:
        label=core.CandidateLabel(candidate_id=r['candidate_id'],parent_cluster_id=r['parent_framework_cluster'],true_r8=float(r['R_8X6B']),true_r9=float(r['R_9E6Y']),teacher_source=r['teacher_source'],development_reliability_tier=r['development_reliability_tier'],docking_evidence_tier=r['docking_evidence_tier'],teacher_reliability=r['teacher_reliability'],ranking_release=r['ranking_release'])
        label.validate(); require(label.candidate_id not in labels,'teacher_duplicate'); labels[label.candidate_id]=label
    groups=defaultdict(list); seen=set()
    for r in manifest:
        key=(int(r['outer_fold']),int(r['inner_fold'])); require(key in {(o,i) for o in range(5) for i in range(5)},'fold_invalid')
        k=key+(r['candidate_id'],); require(k not in seen,'manifest_duplicate'); seen.add(k)
        require(r['candidate_id'] in labels,'manifest_unknown_candidate')
        if r['candidate_role']=='train': groups[key].append(labels[r['candidate_id']])
        else: require(r['candidate_role']=='score','manifest_role')
    require(set(groups)=={(o,i) for o in range(5) for i in range(5)},'partition_grid')
    require(not a.output_dir.exists(),'output_dir_exists'); a.output_dir.mkdir(parents=True)
    files={}; anchors=[]
    for o,i in sorted(groups):
        values=groups[(o,i)]
        payload={'schema_version':SCHEMA,'status':'FROZEN_EXTERNAL_PRETRAINING_TRUST_ANCHOR','created_before_runtime':True,'outer_fold':o,'inner_fold':i,'training_split_sha256':core.compute_training_split_sha256(values,o,i),'label_sha256':core.compute_label_sha256(values),'source_teacher_sha256':TEACHER_SHA,'source_inner_manifest_sha256':MANIFEST_SHA,'rank_core_sha256':RANK_SHA,'scalar_train_label_count':len(values),'rank_eligible_label_count':sum(v.rank_eligible for v in values),'v4_f_test32_access_count':0}
        name=f'outer_{o}_inner_{i}.rank_trust_anchor.json'; path=a.output_dir/name; atomic_json(path,payload); files[name]=sha(path); anchors.append(payload)
    receipt={'schema_version':'pvrig_v2_6_external_rank_trust_anchor_set_receipt_v1','status':'PASS_25_EXTERNAL_PRETRAINING_TRUST_ANCHORS_FROZEN','partition_count':25,'source_teacher_sha256':TEACHER_SHA,'source_inner_manifest_sha256':MANIFEST_SHA,'rank_core_sha256':RANK_SHA,'files':files,'total_scalar_train_labels_across_partitions':sum(x['scalar_train_label_count'] for x in anchors),'v4_f_test32_access_count':0}
    atomic_json(a.output_dir/'TRUST_ANCHOR_SET_RECEIPT.json',receipt)
if __name__=='__main__': main()
