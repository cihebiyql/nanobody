#!/home/qlyu/anaconda3/bin/python
import csv,json,shutil,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
root=Path(sys.argv[1]);foldx='/data/qlyu/software/foldx/foldx_20261231'
rows=[r for r in csv.DictReader((root/'graphinity_single_mutation_manifest.tsv').open(),delimiter='\t') if r['is_interface_le4A']=='1']
out=root/'graphinity_single_mut_foldx';out.mkdir(exist_ok=True)
def clean(src,dst):
 z=[];serial=1
 for line in src.read_text(errors='ignore').splitlines():
  if not line.startswith(('ATOM  ','HETATM')):continue
  atom=line[12:16].strip();alt=line[16:17] or ' ';res=line[17:20].strip();ch=line[21:22].strip() or 'A';rn=int(line[22:26]);ic=line[26:27] or ' ';x=float(line[30:38]);y=float(line[38:46]);zz=float(line[46:54]);oc=float(line[54:60] or 1);bf=float(line[60:66] or 0);el=(''.join(c for c in atom if c.isalpha())[:1] or 'C').upper()
  z.append(f"ATOM  {serial:5d} {atom:>4s}{alt:1s}{res:>3s} {ch:1s}{rn:4d}{ic:1s}   {x:8.3f}{y:8.3f}{zz:8.3f}{oc:6.2f}{bf:6.2f}          {el:>2s}  ");serial+=1
 z.append('END');dst.write_text('\n'.join(z)+'\n')
def run(r):
 tid=f"{r['pair_id']}__{r['mutation']}";wd=out/tid;wd.mkdir(exist_ok=True)
 stem=f"{r['parent_candidate_id']}__pose01__cluster_1_model_1";src=root/'foldx'/stem/f'{stem}_Repair.pdb'
 shutil.copy2(src,wd/'wt.pdb');(wd/'individual_list.txt').write_text(r['mutation']+';\n')
 if not (wd/'Dif_wt.fxout').exists() or len(list(wd.glob('wt_1_*.pdb')))<3:
  with (wd/'run.stdout').open('w') as so,(wd/'run.stderr').open('w') as se:
   p=subprocess.run([foldx,'--command=BuildModel','--pdb=wt.pdb','--mutant-file=individual_list.txt','--numberOfRuns=3',f'--output-dir={wd}'],cwd=wd,stdout=so,stderr=se)
  if p.returncode:raise RuntimeError(f'{tid}:rc={p.returncode}')
 for i in range(3):
  clean(wd/f'WT_wt_1_{i}.pdb',wd/f'graphinity_wt_rep{i}.pdb');clean(wd/f'wt_1_{i}.pdb',wd/f'graphinity_mut_rep{i}.pdb')
 return tid,'SUCCESS'
status=[]
with ThreadPoolExecutor(max_workers=9) as ex:
 fs={ex.submit(run,r):r for r in rows}
 for f in as_completed(fs):
  try:status.append(f.result())
  except Exception as e:status.append((f"{fs[f]['pair_id']}__{fs[f]['mutation']}",f'FAILED:{e}'))
receipt={'task_count':len(rows),'complete_count':len(list(out.glob('*/Dif_wt.fxout'))),'status':status,'overall':'PASS' if len(list(out.glob('*/Dif_wt.fxout')))==len(rows) else 'FAIL'}
(root/'GRAPHINITY_SINGLE_MUT_FOLDX_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if receipt['overall']!='PASS':sys.exit(1)
