#!/usr/bin/env python3
"""Apply computational multi-objective screening before monomer prediction."""

from __future__ import annotations

import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd


def pct(series, high=True):
 s=pd.to_numeric(series,errors='coerce'); rank=s.rank(method='average',pct=True,ascending=True)
 return rank if high else 1-rank


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
 p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--target',type=int,default=150000); a=p.parse_args()
 if a.output_dir.exists(): raise FileExistsError(a.output_dir)
 a.output_dir.mkdir(parents=True); d=pd.read_csv(a.input,sep='\t',low_memory=False)
 if len(d)!=300000 or d.candidate_id.duplicated().any() or d.sequence.duplicated().any(): raise ValueError('300k ID/sequence closure failure')
 d['expression_rank']=pct(d.expression_purity_risk_proxy_partial)
 d['developability_rank']=pct(d.developability_risk_proxy_partial)
 d['abnativ_rank']=pct(d['AbNatiV VHH Score'])
 d['sapiens_rank']=pct(d.mean_self_probability)
 d['deepnano_rank']=pct(d.deepnano_binding_prior)
 d['nanobind_rank']=pct(d.nanobind_binding_prior)
 d['binding_disagreement_rank']=pct(d.binding_model_raw_disagreement)
 d['production_proxy_score']=0.30*d.expression_rank+0.25*d.developability_rank+0.25*d.abnativ_rank+0.20*d.sapiens_rank
 d['binding_consensus_weak_prior']=0.5*d.deepnano_rank+0.5*d.nanobind_rank
 d['prestructure_multimetric_score']=0.75*d.production_proxy_score+0.20*d.binding_consensus_weak_prior-0.05*d.binding_disagreement_rank
 d['prestructure_hard_gate']=(d.anarci_qc_status.eq('PASS') & d.descriptor_status.eq('PASS') & ~d.risk_tier.eq('HIGH') & d.abnativ_status.eq('PASS'))
 eligible=d[d.prestructure_hard_gate].sort_values(['prestructure_multimetric_score','production_proxy_score','binding_consensus_weak_prior','candidate_id'],ascending=[False,False,False,True])
 if len(eligible)<a.target: raise ValueError(f'eligible {len(eligible)} < target {a.target}')
 selected=eligible.head(a.target).copy(); full=a.output_dir/'fixed_pose300k_multimetric.tsv.gz'; out=a.output_dir/'fixed_pose_top150k_for_structure.tsv.gz'; fasta=a.output_dir/'fixed_pose_top150k_for_structure.fasta.gz'
 d.to_csv(full,sep='\t',index=False,compression={'method':'gzip','compresslevel':1}); selected.to_csv(out,sep='\t',index=False,compression={'method':'gzip','compresslevel':1})
 with __import__('gzip').open(fasta,'wt',compresslevel=1) as h:
  for row in selected.itertuples(): h.write(f'>{row.candidate_id}\n{row.sequence}\n')
 rec={'status':'READY_FOR_BATCHED_NBB2','input_records':len(d),'hard_gate_pass':int(d.prestructure_hard_gate.sum()),'selected_records':len(selected),
  'score_weights':{'production_proxy':0.75,'binding_consensus_weak_prior':0.20,'binding_disagreement_penalty':0.05},
  'production_subweights':{'expression_purity_risk_proxy':0.30,'developability_risk_proxy':0.25,'AbNatiV':0.25,'Sapiens':0.20},
  'outputs':{x.name:sha(x) for x in (full,out,fasta)},
  'scientific_boundary':'computational prestructure triage; purity/expression and affinity are proxies, not measurements'}
 (a.output_dir/'READY.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n'); print(json.dumps(rec,sort_keys=True))

if __name__=='__main__': main()
