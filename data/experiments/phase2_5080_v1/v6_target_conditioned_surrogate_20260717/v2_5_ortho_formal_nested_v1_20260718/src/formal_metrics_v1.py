#!/usr/bin/env python3
"""Inner-only selection and final open-outer evaluation for V2.5 nested training."""
from __future__ import annotations
import argparse,csv,hashlib,json,math,os
from collections import defaultdict
from pathlib import Path
from typing import Any,Sequence
import numpy as np
LANES=("B_CLEAN_TARGET_ATTENTION","E_DECOUPLED_CONTACT_DETACHED","E_DECOUPLED_CONTACT_SHARED")
HP=("H0","H1","H2"); SEEDS=(43,97,193)
class E(RuntimeError): pass
def req(x,m):
 if not x: raise E(m)
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def loadj(p): return json.loads(Path(p).read_text())
def atomic_json(p,x):
 p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); q=p.with_name('.'+p.name+f'.{os.getpid()}.tmp'); q.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n'); os.replace(q,p)
def rows(p):
 with Path(p).open() as handle: return list(csv.DictReader(handle,delimiter='\t'))
def ranks(x):
 x=np.asarray(x,float); order=np.argsort(x,kind='mergesort'); r=np.empty(len(x),float); i=0
 while i<len(x):
  j=i+1
  while j<len(x) and x[order[j]]==x[order[i]]: j+=1
  r[order[i:j]]=(i+j-1)/2+1; i=j
 return r
def spearman(a,b):
 ra,rp=ranks(a),ranks(b); req(len(ra)>1,'metric_small_n'); sa,sb=ra.std(),rp.std(); return 0.0 if sa==0 or sb==0 else float(np.corrcoef(ra,rp)[0,1])
def metrics(recs):
 out={}
 for name,t,p in [('R8','R_8X6B','pred_R8'),('R9','R_9E6Y','pred_R9'),('Rdual','R_dual_min','pred_Rdual')]:
  y=np.array([float(r[t]) for r in recs]); z=np.array([float(r[p]) for r in recs]); d=z-y
  out[name]={'spearman':spearman(y,z),'mae':float(np.abs(d).mean()),'rmse':float(np.sqrt(np.mean(d*d)))}
 return out
def truth_map(tsv):
 d={}
 for r in rows(tsv):
  cid=r['candidate_id']; req(cid not in d,'truth_duplicate'); d[cid]={'R_8X6B':float(r['R_8X6B']),'R_9E6Y':float(r['R_9E6Y']),'R_dual_min':float(r['R_dual_min']),'parent':r['parent_framework_cluster']}
 return d
def prediction_rows(directory):
 d=Path(directory); result=loadj(d/'RESULT.json'); req(str(result.get('status','')).startswith('PASS_FORMAL_'),'training_status')
 p=d/'score_predictions_no_metrics.tsv'; req(sha(p)==result['artifacts']['predictions_no_metrics']['sha256'],'prediction_hash')
 return result,rows(p)
def select(args):
 req(not args.output_dir.exists(),'output_exists'); grouped=defaultdict(list)
 for d in args.input_dir:
  r,p=prediction_rows(d); req(r['phase']=='inner' and r['lane']['variant']==args.lane and r['outer_fold']==args.outer_fold,'inner_scope')
  req(r['formal_seed']==43 and r['inner_fold'] in range(5),'inner_seed_fold'); grouped[r['formal_hparam_id']].append((r,p))
 req(set(grouped)==set(HP) and all(len(v)==5 for v in grouped.values()),'inner_grid_closure')
 summaries={}
 for hid,jobs in grouped.items():
  merged=[]; seen=set()
  for result,preds in jobs:
   tm=truth_map(result['input_receipt']['files']['training_tsv']['path'])
   for p in preds:
    cid=p['candidate_id']; req(cid in tm and cid not in seen,'inner_candidate_closure'); seen.add(cid); t=tm[cid]
    pr8=float(p['neural_R8']); pr9=float(p['neural_R9']); pd=min(pr8,pr9); req(abs(pd-float(p['neural_Rdual']))<=1e-7,'inner_exact_min')
    merged.append({**t,'candidate_id':cid,'pred_R8':pr8,'pred_R9':pr9,'pred_Rdual':pd})
  summaries[hid]={'rows':len(merged),'metrics':metrics(merged)}
 key=lambda h:(-summaries[h]['metrics']['Rdual']['spearman'],summaries[h]['metrics']['Rdual']['mae'],summaries[h]['metrics']['Rdual']['rmse'],h)
 chosen=min(HP,key=key); payload={'schema_version':'pvrig_v2_5_inner_hparam_selection_v1','status':'PASS_INNER_HPARAM_SELECTED','job_id':args.job_id,'lane':args.lane,'outer_fold':args.outer_fold,'selected_hparam_id':chosen,'selection_order':['Rdual_spearman_desc','Rdual_mae_asc','Rdual_rmse_asc','hparam_id_asc'],'summaries':summaries,'prediction_metrics_scope':'inner_only','v4_f_test32_access_count':0}
 args.output_dir.mkdir(parents=True); atomic_json(args.output_dir/'RESULT.json',payload); atomic_json(args.output_dir/'SELECTION.json',payload)
def ensemble(args):
 req(not args.output_dir.exists(),'output_exists'); seed_preds={}; truth=None; lane=None; outer=None; h=None
 for d in args.input_dir:
  r,ps=prediction_rows(d); req(r['phase']=='outer' and r['formal_seed'] in SEEDS,'outer_scope'); seed_preds[r['formal_seed']]={x['candidate_id']:x for x in ps}
  tm=truth_map(r['input_receipt']['files']['training_tsv']['path']); truth=tm if truth is None else truth; req(set(truth)==set(tm),'outer_truth_closure')
  lane=lane or r['lane']['variant']; outer=r['outer_fold'] if outer is None else outer; h=h or r['formal_hparam_id']; req(lane==r['lane']['variant'] and outer==r['outer_fold'] and h==r['formal_hparam_id'],'outer_ensemble_scope')
 req(set(seed_preds)==set(SEEDS),'outer_seed_closure'); ids=set(next(iter(seed_preds.values()))); req(all(set(v)==ids for v in seed_preds.values()),'outer_candidate_closure')
 out=[]
 for cid in sorted(ids):
  r8=float(np.mean([float(seed_preds[s][cid]['neural_R8']) for s in SEEDS])); r9=float(np.mean([float(seed_preds[s][cid]['neural_R9']) for s in SEEDS])); dual=min(r8,r9); t=truth[cid]
  out.append({**t,'candidate_id':cid,'pred_R8':r8,'pred_R9':r9,'pred_Rdual':dual})
 req(all(abs(x['pred_Rdual']-min(x['pred_R8'],x['pred_R9']))<=1e-12 for x in out),'ensemble_exact_min')
 args.output_dir.mkdir(parents=True); pred=args.output_dir/'outer_ensemble_predictions.tsv'
 with pred.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(out[0]),delimiter='\t',lineterminator='\n'); w.writeheader(); w.writerows(out)
 payload={'schema_version':'pvrig_v2_5_outer_ensemble_eval_v1','status':'PASS_OPEN_OUTER_ENSEMBLE_EVALUATION','job_id':args.job_id,'lane':lane,'outer_fold':outer,'selected_hparam_id':h,'seeds':list(SEEDS),'rows':len(out),'metrics':metrics(out),'predictions':{'path':str(pred),'sha256':sha(pred)},'exact_min_violations':0,'prediction_metrics_scope':'open_outer_final_only','v4_f_test32_access_count':0}
 atomic_json(args.output_dir/'RESULT.json',payload)
def collect(args):
 req(not args.output_dir.exists(),'output_exists'); by=defaultdict(list); folds=defaultdict(set)
 for d in args.input_dir:
  r=loadj(Path(d)/'RESULT.json'); req(r.get('status')=='PASS_OPEN_OUTER_ENSEMBLE_EVALUATION','outer_eval_status'); p=Path(r['predictions']['path']); req(sha(p)==r['predictions']['sha256'],'outer_pred_hash'); by[r['lane']]+=rows(p); folds[r['lane']].add(int(r['outer_fold']))
 req(set(by)==set(LANES) and all(v==set(range(5)) for v in folds.values()),'outer_lane_fold_closure')
 summary={}
 args.output_dir.mkdir(parents=True)
 for lane,recs in by.items():
  req(len(recs)==1507 and len({r['candidate_id'] for r in recs})==1507,'outer_1507_closure'); req(len({r['parent'] for r in recs})==31,'outer_parent_closure'); summary[lane]={'rows':1507,'parents':31,'metrics':metrics(recs)}
 payload={'schema_version':'pvrig_v2_5_formal_nested_open_outer_summary_v1','status':'PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED','job_id':args.job_id,'lanes':summary,'rows_per_lane':1507,'parents_per_lane':31,'exact_min_contract':True,'v4_f_test32_access_count':0,'claim_boundary':'computational dual-receptor docking geometry surrogate only'}
 atomic_json(args.output_dir/'RESULT.json',payload); atomic_json(args.output_dir/'FORMAL_OPEN_OUTER_SUMMARY.json',payload)
def parser():
 p=argparse.ArgumentParser(); sp=p.add_subparsers(dest='cmd',required=True)
 q=sp.add_parser('select'); q.add_argument('--job-id',required=True); q.add_argument('--lane',choices=LANES,required=True); q.add_argument('--outer-fold',type=int,required=True); q.add_argument('--input-dir',type=Path,action='append',required=True); q.add_argument('--output-dir',type=Path,required=True); q.set_defaults(fn=select)
 q=sp.add_parser('ensemble'); q.add_argument('--job-id',required=True); q.add_argument('--input-dir',type=Path,action='append',required=True); q.add_argument('--output-dir',type=Path,required=True); q.set_defaults(fn=ensemble)
 q=sp.add_parser('collect'); q.add_argument('--job-id',required=True); q.add_argument('--input-dir',type=Path,action='append',required=True); q.add_argument('--output-dir',type=Path,required=True); q.set_defaults(fn=collect)
 return p
def main(argv:Sequence[str]|None=None): a=parser().parse_args(argv); a.fn(a); print(json.dumps({'status':'PASS','command':a.cmd,'job_id':a.job_id},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
