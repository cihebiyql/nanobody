#!/home/qlyu/anaconda3/bin/python
import csv,json,shutil,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
root=Path(sys.argv[1] if len(sys.argv)>1 else '/data1/qlyu/model_smoke/pvrig_positive11_structure_affinity_benchmark_20260719')
foldx=Path('/data/qlyu/software/foldx/foldx_20261231')
rows=list(csv.DictReader((root/'fixed_pose_pair_manifest.tsv').open(),delimiter='\t'))
out=root/'fixed_pose_ddg';out.mkdir(exist_ok=True)
smoke=root/'fixed_pose_ddg_smoke_20H5'
if (smoke/'Dif_wt.fxout').exists():
    shutil.copytree(smoke,out/'20_to_20H5',dirs_exist_ok=True)

def run(r):
    pid=r['pair_id'];wd=out/pid;wd.mkdir(exist_ok=True)
    if (wd/'Dif_wt.fxout').exists() and len(list(wd.glob('wt_1_*.pdb')))>=5:
        return pid,'SKIP_COMPLETE'
    stem=f"{r['parent_candidate_id']}__pose01__cluster_1_model_1"
    src=root/'foldx'/stem/f'{stem}_Repair.pdb'
    if not src.exists():raise FileNotFoundError(src)
    shutil.copy2(src,wd/'wt.pdb')
    (wd/'individual_list.txt').write_text(r['foldx_mutations']+'\n')
    cmd=[str(foldx),'--command=BuildModel','--pdb=wt.pdb','--mutant-file=individual_list.txt','--numberOfRuns=5',f'--output-dir={wd}']
    t=time.time()
    with (wd/'run.stdout').open('w') as so,(wd/'run.stderr').open('w') as se:
        p=subprocess.run(cmd,cwd=wd,stdout=so,stderr=se)
    (wd/'elapsed_seconds.txt').write_text(f'{time.time()-t:.3f}\n')
    if p.returncode or not (wd/'Dif_wt.fxout').exists() or len(list(wd.glob('wt_1_*.pdb')))<5:
        raise RuntimeError(f'{pid} foldx failed rc={p.returncode}')
    return pid,'SUCCESS'

status=[]
with ThreadPoolExecutor(max_workers=5) as ex:
    fs={ex.submit(run,r):r['pair_id'] for r in rows}
    for f in as_completed(fs):
        try: status.append(f.result())
        except Exception as e: status.append((fs[f],f'FAILED:{e}'))
with (root/'fixed_pose_ddg_status.tsv').open('w') as f:
    f.write('pair_id\tstatus\n');
    for a,b in sorted(status):f.write(f'{a}\t{b}\n')
receipt={'pair_count':len(rows),'complete_count':sum((out/r['pair_id']/'Dif_wt.fxout').exists() for r in rows),'status_lines':status,'status':'PASS' if all((out/r['pair_id']/'Dif_wt.fxout').exists() for r in rows) else 'FAIL','boundary':'FoldX fixed-parent-pose multi-mutation ddG; not experimental affinity'}
(root/'FIXED_POSE_DDG_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
if receipt['status']!='PASS':sys.exit(1)
