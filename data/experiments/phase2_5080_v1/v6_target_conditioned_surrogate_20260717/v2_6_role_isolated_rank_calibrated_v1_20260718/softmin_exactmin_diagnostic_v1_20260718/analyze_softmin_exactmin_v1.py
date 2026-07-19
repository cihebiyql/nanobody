#!/usr/bin/env python3
import argparse,csv,hashlib,itertools,json,math,statistics
from collections import Counter

def sha256(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def q(x,p):
 s=sorted(x);return s[int(p*(len(s)-1))]

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output',required=True);ap.add_argument('--tau',type=float,default=.02);ap.add_argument('--delta-noise',type=float,default=.019614956149);a=ap.parse_args()
 rows=[]
 with open(a.input,newline='') as f:
  for r in csv.DictReader(f,delimiter='\t'):
   r8=float(r['R_8X6B']);r9=float(r['R_9E6Y']);dual=min(r8,r9)
   z1=-r8/a.tau;z2=-r9/a.tau;m=max(z1,z2)
   soft=-a.tau*(m+math.log(math.exp(z1-m)+math.exp(z2-m)))+a.tau*math.log(2.0)
   rows.append({'parent':r['parent_framework_cluster'],'source':r['teacher_source'],'reliability':r['teacher_reliability'],'dual':dual,'soft':soft,'bias':soft-dual,'gap':abs(r8-r9)})
 thresholds=[0.0,.001,.002,.005,.01,.015,a.delta_noise]
 pair=[]
 for thr in thresholds:
  n=flips=ties=0
  for _,grp in itertools.groupby(sorted(rows,key=lambda x:x['parent']),lambda x:x['parent']):
   g=list(grp)
   for x,y in itertools.combinations(g,2):
    de=x['dual']-y['dual']
    if de==0 or abs(de)<thr:continue
    ds=x['soft']-y['soft'];n+=1
    if ds==0:ties+=1
    elif de*ds<0:flips+=1
  pair.append({'minimum_abs_exact_pair_delta':thr,'eligible_pair_count':n,'sign_flip_count':flips,'tie_count':ties,'sign_flip_fraction':flips/n if n else None})
 b=[x['bias'] for x in rows];g=[x['gap'] for x in rows]
 out={'schema_version':'pvrig_v2_6_softmin_exactmin_diagnostic_v1','claim_boundary':'Open teacher-label mathematical diagnostic only; no outer model metrics and no V4-F/test32 access.','input':{'path':a.input,'sha256':sha256(a.input),'rows':len(rows),'parents':len(set(x['parent'] for x in rows)),'sources':dict(Counter(x['source'] for x in rows)),'reliability':dict(Counter(x['reliability'] for x in rows))},'parameters':{'tau':a.tau,'delta_noise':a.delta_noise,'theoretical_max_bias':a.tau*math.log(2.0)},'row_bias':{'mean':statistics.mean(b),'median':statistics.median(b),'p95':q(b,.95),'max':max(b)},'receptor_gap':{'mean':statistics.mean(g),'median':statistics.median(g),'p95':q(g,.95),'max':max(g)},'within_parent_pair_direction':pair,'decision':'USE_EXACT_MIN_FOR_RANK_LOSS_KEEP_SOFTMIN_ONLY_AS_SCALAR_AUXILIARY_DIAGNOSTIC','v4_f_test32_access_count':0}
 with open(a.output,'w') as f:json.dump(out,f,indent=2,sort_keys=True);f.write('\n')
 print(json.dumps(out,sort_keys=True))
if __name__=='__main__':main()
