#!/home/qlyu/anaconda3/bin/python
import csv,subprocess,sys
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
root=Path(sys.argv[1]);fx='/data/qlyu/software/foldx/foldx_20261231';base=root/'fixed_pose_ddg'
pairs=list(csv.DictReader((root/'fixed_pose_pair_manifest.tsv').open(),delimiter='\t'))
tasks=[(r,i,k) for r in pairs for i in range(5) for k in ('wt','mut')]
def run(t):
 r,i,k=t;d=base/r['pair_id'];p=d/(f'WT_wt_1_{i}.pdb' if k=='wt' else f'wt_1_{i}.pdb');name=p.stem
 of=d/f'Interaction_{name}_AC.fxout'
 if not of.exists():
  with (d/f'analyse_{name}.stdout').open('w') as so,(d/f'analyse_{name}.stderr').open('w') as se:
   q=subprocess.run([fx,'--command=AnalyseComplex',f'--pdb={p.name}','--analyseComplexChains=A,B',f'--output-dir={d}'],cwd=d,stdout=so,stderr=se)
  if q.returncode or not of.exists():raise RuntimeError(f'{p}:rc={q.returncode}')
 return r['pair_id'],i,k,of
with ThreadPoolExecutor(max_workers=12) as ex:
 fs=[ex.submit(run,t) for t in tasks]
 for f in as_completed(fs):f.result()
def energy(p):
 lines=[x for x in p.read_text().splitlines() if x.strip()];i=next(i for i,x in enumerate(lines) if x.startswith('Pdb\tGroup1\tGroup2'))
 h=lines[i].split('\t');v=lines[i+1].split('\t');return float(dict(zip(h,v))['Interaction Energy'])
out=[]
for r in pairs:
 for i in range(5):
  wt=energy(base/r['pair_id']/f'Interaction_WT_wt_1_{i}_AC.fxout');mu=energy(base/r['pair_id']/f'Interaction_wt_1_{i}_AC.fxout')
  out.append({**r,'replicate':i,'foldx_wt_interaction':wt,'foldx_mut_interaction':mu,'foldx_binding_ddg':mu-wt})
with (root/'fixed_pose_foldx_binding_ddg.tsv').open('w',newline='') as f:
 w=csv.DictWriter(f,list(out[0]),delimiter='\t');w.writeheader();w.writerows(out)
print('rows',len(out))
