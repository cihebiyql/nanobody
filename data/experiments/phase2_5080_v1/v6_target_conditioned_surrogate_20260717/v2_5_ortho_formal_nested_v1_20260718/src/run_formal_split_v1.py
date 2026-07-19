#!/usr/bin/env python3
"""Frozen formal split adapter for V2.5 ORTHO nested training."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,os,random,sys
from pathlib import Path
from typing import Any,Sequence
import numpy as np
import torch

SCHEMA="pvrig_v2_5_ortho_formal_split_runner_v1"
HP={
 "H0":{"fixed_epochs":8,"learning_rate":1e-4,"weight_decay":.02,"huber_beta":.03},
 "H1":{"fixed_epochs":16,"learning_rate":2e-4,"weight_decay":.02,"huber_beta":.03},
 "H2":{"fixed_epochs":16,"learning_rate":1e-4,"weight_decay":.03,"huber_beta":.04},
}
LANES=("B_CLEAN_TARGET_ATTENTION","E_DECOUPLED_CONTACT_DETACHED","E_DECOUPLED_CONTACT_SHARED")
SEEDS=(43,97,193)

class ContractError(RuntimeError): pass
def req(x,m):
 if not x: raise ContractError(m)
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def atomic_json(p:Path,x:Any):
 p.parent.mkdir(parents=True,exist_ok=True); q=p.with_name('.'+p.name+f'.{os.getpid()}.tmp'); q.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n'); os.replace(q,p)
def load_module(path:Path):
 req(path.is_file() and not path.is_symlink(),f'base_runner_missing:{path}')
 spec=importlib.util.spec_from_file_location('v25_real1507_frozen',path); req(spec and spec.loader,'base_import_spec')
 m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); return m

def choose_h(args)->str:
 if args.hparam_id:
  req(args.selection_json is None,'hparam_and_selection_mutually_exclusive'); return args.hparam_id
 req(args.selection_json and args.selection_json.is_file(),'selection_missing')
 s=json.loads(args.selection_json.read_text()); req(s.get('status')=='PASS_INNER_HPARAM_SELECTED','selection_status')
 req(s.get('lane')==args.lane_variant and int(s.get('outer_fold'))==args.outer_fold,'selection_scope')
 return str(s['selected_hparam_id'])

def materialize_split(source:Path,out:Path,hid:str)->Path:
 s=json.loads(source.read_text()); req(s.get('open_only') is True and s.get('v4_f_test32_access_count')==0,'split_not_open')
 s['fixed_epochs']=HP[hid]['fixed_epochs']; s['formal_hparam_id']=hid; s['formal_source_split_sha256']=sha(source); s['v4_f_test32_access_count']=0
 target=out/f"{source.stem}.{hid}.json"; payload=json.dumps(s,indent=2,sort_keys=True)+'\n'
 if target.exists(): req(target.read_text()==payload,'materialized_split_collision')
 else: target.parent.mkdir(parents=True,exist_ok=True); target.write_text(payload)
 return target

def row_counts(tsv:Path,split:dict)->tuple[int,int,int,int]:
 rows=list(csv.DictReader(tsv.open(),delimiter='\t')); req(rows,'empty_training')
 parents=[r['parent_framework_cluster'] for r in rows]; obs=set(parents); tr=set(split['train_parents']); sc=set(split['score_parents'])
 req(obs==tr|sc and tr.isdisjoint(sc),'parent_exact_closure')
 return len(rows),len(obs),sum(p in tr for p in parents),sum(p in sc for p in parents)

def parser():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--job-id',required=True); p.add_argument('--phase',choices=('inner','outer'),required=True)
 p.add_argument('--outer-fold',type=int,required=True); p.add_argument('--inner-fold',type=int)
 p.add_argument('--lane-variant',choices=LANES,required=True); p.add_argument('--hparam-id',choices=tuple(HP)); p.add_argument('--selection-json',type=Path)
 p.add_argument('--seed',type=int,required=True); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--materialized-split-dir',type=Path,required=True)
 p.add_argument('--base-runner',type=Path,required=True); p.add_argument('--source-split-manifest',type=Path,required=True)
 for n in ('v2-4-adapter-path','v2-3-bundle-root','training-tsv','contact-tsv-gz','pair-contact-tsv-gz','graph-cache-dir','target-graph-pt','contact-formula-json','model-path','model-identity-file'):
  p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--expected-v2-4-adapter-sha256',required=True); p.add_argument('--expected-model-sha256',required=True); p.add_argument('--device',default='cuda')
 return p

def main(argv:Sequence[str]|None=None)->int:
 a=parser().parse_args(argv); req(0<=a.outer_fold<5,'outer_fold')
 if a.phase=='inner': req(a.inner_fold is not None and 0<=a.inner_fold<5 and a.seed==43 and a.hparam_id,'inner_contract')
 else: req(a.inner_fold is None and a.seed in SEEDS and a.selection_json,'outer_contract')
 req(not a.output_dir.exists(),'output_dir_exists'); hid=choose_h(a); req(hid in HP,'hparam')
 source=json.loads(a.source_split_manifest.read_text()); variant=materialize_split(a.source_split_manifest,a.materialized_split_dir,hid)
 counts=row_counts(a.training_tsv,source); base=load_module(a.base_runner)
 cfg=dict(base.FROZEN_TRAINING); cfg.update(HP[hid]); cfg['seed']=a.seed; base.FROZEN_TRAINING.clear(); base.FROZEN_TRAINING.update(cfg)
 random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
 ns=argparse.Namespace(mode='train',lane_variant=a.lane_variant,output_dir=a.output_dir,
  v2_4_adapter_path=getattr(a,'v2_4_adapter_path'),expected_v2_4_adapter_sha256=a.expected_v2_4_adapter_sha256,
  v2_3_bundle_root=getattr(a,'v2_3_bundle_root'),training_tsv=a.training_tsv,contact_tsv_gz=a.contact_tsv_gz,
  pair_contact_tsv_gz=a.pair_contact_tsv_gz,graph_cache_dir=a.graph_cache_dir,target_graph_pt=a.target_graph_pt,
  contact_formula_json=a.contact_formula_json,split_manifest=variant,model_path=a.model_path,model_identity_file=a.model_identity_file,
  expected_model_sha256=a.expected_model_sha256,device=a.device,expected_rows=counts[0],expected_parents=counts[1],expected_train_rows=counts[2],expected_score_rows=counts[3])
 context=base.load_real_context(ns); receipt=base.run_training(ns,context)
 receipt['schema_version']=SCHEMA; receipt['status']='PASS_FORMAL_INNER_TRAINING' if a.phase=='inner' else 'PASS_FORMAL_OUTER_REFIT'
 receipt['job_id']=a.job_id; receipt['phase']=a.phase; receipt['outer_fold']=a.outer_fold; receipt['inner_fold']=a.inner_fold
 receipt['formal_hparam_id']=hid; receipt['formal_hyperparameters']=HP[hid]; receipt['formal_seed']=a.seed
 receipt['source_split_manifest']={'path':str(a.source_split_manifest),'sha256':sha(a.source_split_manifest)}
 receipt['materialized_split_manifest']={'path':str(variant),'sha256':sha(variant)}
 receipt['exact_min_contract']=True; receipt['neural_input_firewall']={'M2_126D_ID_pose_inputs':0}; receipt['v4_f_test32_access_count']=0
 atomic_json(a.output_dir/'TRAINING_RECEIPT.json',receipt); atomic_json(a.output_dir/'RESULT.json',receipt)
 print(json.dumps({'status':receipt['status'],'job_id':a.job_id,'hparam_id':hid,'seed':a.seed},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
