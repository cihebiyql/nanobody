#!/usr/bin/env python3
"""Freeze the final exact-unique 1M library after GPU-route sequence prefiltering."""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math,os
from collections import Counter,defaultdict,deque
from pathlib import Path

COMMON=['candidate_id','sequence','sequence_sha256','sequence_length','route_id','generation_seed','target_patch_assignment','design_mode','parent_id','parent_cluster','cdr1_after','cdr2_after','cdr3_after','designed_regions','generator','generator_version','generation_batch','max_positive_cdr_identity','max_positive_cdr_identity_detail']
SOURCE=['source_candidate_id','source_run_id','source_arm_id','source_backbone_group_id','source_pose_id','source_mpnn_index','source_row_kind']
def op(path,mode): return gzip.open(path,mode,newline='') if path.suffix=='.gz' else open(path,mode,newline='')
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(8<<20),b''):h.update(b)
 return h.hexdigest()
def number(value,default):
 try:
  x=float(value); return x if math.isfinite(x) else default
 except (TypeError,ValueError): return default
def quality(row):
 tier={'LOW':0,'MODERATE':1,'HIGH':2}.get(row.get('risk_tier',''),3)
 ab_status=0 if row.get('abnativ_status')=='PASS' else 1
 return (tier,number(row.get('developability_risk_proxy_partial'),1e9),number(row.get('expression_purity_risk_proxy_partial'),1e9),ab_status,-number(row.get('AbNatiV VHH Score'),-1),-number(row.get('mean_self_probability'),-1),number(row.get('binding_model_raw_disagreement'),1e9),-0.5*(number(row.get('deepnano_binding_prior'),0)+number(row.get('nanobind_binding_prior'),0)),row['candidate_id'])
def load_prefilter(path):
 output_keep=['candidate_id','anarci_qc_status','anarci_qc_reasons','risk_tier','developability_risk_proxy_partial','expression_purity_risk_proxy_partial','abnativ_status','AbNatiV VHH Score','mean_self_probability','binding_model_raw_disagreement','deepnano_binding_prior','nanobind_binding_prior']
 gate_keep=['numbered_sequence_matches_input_slice','anarci_fr1','anarci_fr4','imgt_cys23','imgt_cys104']
 keep=output_keep+gate_keep
 out={}
 with op(path,'rt') as f:
  for row in csv.DictReader(f,delimiter='\t'):
   cid=row['candidate_id']
   if cid in out: raise ValueError(f'duplicate prefilter ID: {cid}')
   out[cid]={k:row.get(k,'') for k in keep}
 return out,output_keep
def structure_gate(row):
 return (row.get('anarci_qc_status')=='PASS' and row.get('numbered_sequence_matches_input_slice')=='True' and len(row.get('anarci_fr1',''))>=19 and len(row.get('anarci_fr4',''))>=4 and row.get('imgt_cys23')=='C' and row.get('imgt_cys104')=='C' and row.get('sequence','').count('C')==2)
def ordered_rf(rows):
 by_backbone=defaultdict(list)
 for row in rows: by_backbone[row['source_backbone_group_id']].append(row)
 for values in by_backbone.values(): values.sort(key=quality)
 order=[]; depth=0
 while True:
  gained=0
  for key in sorted(by_backbone):
   if depth<len(by_backbone[key]): order.append(by_backbone[key][depth]); gained+=1
  if not gained: break
  depth+=1
 return order
def balanced_select(rows,route,target):
 group_key='source_arm_id' if route=='rfantibody' else 'source_pose_id'; groups=defaultdict(list)
 for row in rows:
  if not row[group_key]: raise ValueError(f'{route} missing {group_key}: {row["candidate_id"]}')
  groups[row[group_key]].append(row)
 ordered={k:(ordered_rf(v) if route=='rfantibody' else sorted(v,key=quality)) for k,v in groups.items()}
 queues={k:deque(v) for k,v in ordered.items()}; selected=[]
 while len(selected)<target:
  gained=0
  for key in sorted(queues):
   if queues[key]: selected.append(queues[key].popleft()); gained+=1
   if len(selected)==target: break
  if not gained: break
 if len(selected)!=target: raise ValueError(f'{route}: selected {len(selected)} != {target}')
 return selected
def main():
 p=argparse.ArgumentParser(); p.add_argument('--cpu',type=Path,action='append',required=True); p.add_argument('--gpu-candidates',type=Path,required=True); p.add_argument('--gpu-prefilter',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True)
 p.add_argument('--rf-target',type=int,default=150000); p.add_argument('--mpnn-target',type=int,default=150000); p.add_argument('--expected-total',type=int,default=1000000); a=p.parse_args()
 a.output_dir.mkdir(parents=True,exist_ok=True); pre,metric_fields=load_prefilter(a.gpu_prefilter); gpu=[]; seen_gpu=set()
 with op(a.gpu_candidates,'rt') as f:
  for row in csv.DictReader(f,delimiter='\t'):
   cid=row['candidate_id']
   if cid in seen_gpu: raise ValueError(f'duplicate GPU candidate ID: {cid}')
   seen_gpu.add(cid)
   if cid not in pre: raise ValueError(f'GPU candidate missing prefilter: {cid}')
   row.update(pre[cid])
   if row.get('fast_qc_status')=='PASS' and structure_gate(row): gpu.append(row)
 if set(pre)!=seen_gpu: raise ValueError(f'prefilter ID set mismatch extra={len(set(pre)-seen_gpu)}')
 by_route=defaultdict(list)
 for row in gpu: by_route[row['route_id']].append(row)
 rf=balanced_select(by_route['rfantibody'],'rfantibody',a.rf_target)
 selected_seq={r['sequence'] for r in rf}; mp_pool=[r for r in by_route['fixed_pose_mpnn'] if r['sequence'] not in selected_seq]
 mp=balanced_select(mp_pool,'fixed_pose_mpnn',a.mpnn_target); selected=rf+mp
 gpu_ids={r['candidate_id'] for r in selected}; gpu_seq={r['sequence'] for r in selected}
 gpu_target=a.rf_target+a.mpnn_target
 if len(gpu_ids)!=gpu_target or len(gpu_seq)!=gpu_target: raise ValueError('GPU selection is not exact unique')
 gpu_out=a.output_dir/'gpu_selected300k.tsv.gz'; gpu_pref=a.output_dir/'gpu_selected300k_prefilter.tsv.gz'; gpu_fa=a.output_dir/'gpu_selected300k.fasta.gz'
 with gzip.open(gpu_out,'wt',newline='') as h,gzip.open(gpu_pref,'wt',newline='') as ph,gzip.open(gpu_fa,'wt') as fa:
  fields=COMMON+SOURCE; w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n',extrasaction='ignore');w.writeheader()
  pfields=fields+metric_fields[1:]; pw=csv.DictWriter(ph,fieldnames=pfields,delimiter='\t',lineterminator='\n',extrasaction='ignore');pw.writeheader()
  for row in selected: w.writerow(row);pw.writerow(row);fa.write(f">{row['candidate_id']}\n{row['sequence']}\n")
 final=a.output_dir/'pvrig_1m_candidates.tsv.gz'; final_fa=a.output_dir/'pvrig_1m_candidates.fasta.gz'; ids=set(); seqs=set(); route_counts=Counter(); total=0
 with gzip.open(final,'wt',newline='') as out,gzip.open(final_fa,'wt') as fa:
  fields=COMMON+SOURCE; w=csv.DictWriter(out,fieldnames=fields,delimiter='\t',lineterminator='\n',extrasaction='ignore');w.writeheader()
  for path in a.cpu:
   with op(path,'rt') as src:
    for row in csv.DictReader(src,delimiter='\t'):
     cid=row['candidate_id']; seq=row['sequence'].strip().upper()
     if cid in ids or seq in seqs: raise ValueError(f'CPU duplicate: {cid}')
     ids.add(cid);seqs.add(seq);route_counts[row['route_id']]+=1;total+=1;w.writerow(row);fa.write(f'>{cid}\n{seq}\n')
  for row in selected:
   cid=row['candidate_id'];seq=row['sequence']
   if cid in ids or seq in seqs: raise ValueError(f'GPU/CPU duplicate: {cid}')
   ids.add(cid);seqs.add(seq);route_counts[row['route_id']]+=1;total+=1;w.writerow(row);fa.write(f'>{cid}\n{seq}\n')
 if total!=a.expected_total or len(ids)!=total or len(seqs)!=total: raise ValueError(f'final count/uniqueness mismatch {total}')
 if (a.expected_total,a.rf_target,a.mpnn_target)==(1000000,150000,150000):
  expected={'conservative_cdr_redesign':400000,'natural_cdr_donor':200000,'profile_diversified_exploration_control':100000,'rfantibody':150000,'fixed_pose_mpnn':150000}
  if dict(route_counts)!=expected: raise ValueError(f'route quotas mismatch: {dict(route_counts)}')
 outputs=[gpu_out,gpu_pref,gpu_fa,final,final_fa]; receipt={'status':'PASS','records':total,'candidate_id_exact_unique':True,'sequence_exact_unique':True,'route_counts':dict(sorted(route_counts.items())),'gpu_hard_qc_pool':dict(sorted((k,len(v)) for k,v in by_route.items())),'outputs':{x.name:sha(x) for x in outputs},'scientific_boundary':'sequence generation and computational prefilter; not measured binding, affinity, purity, expression, docking, or blocking evidence'}
 (a.output_dir/'FREEZE_RECEIPT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');(a.output_dir/'SHA256SUMS').write_text(''.join(f'{receipt["outputs"][x.name]}  {x.name}\n' for x in outputs));print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__':main()
