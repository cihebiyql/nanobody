#!/usr/bin/env python3
"""Replace batch-composition-dependent DeepNano values with length-bucketed values."""

import argparse,csv,gzip,hashlib,json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser(); p.add_argument('corrected_root',type=Path)
    p.add_argument('old_binding',type=Path); p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--expected-records',type=int,default=394295); a=p.parse_args()
    with gzip.open(a.old_binding,'rt',newline='') as handle:
        old={row['candidate_id']:row for row in csv.DictReader(handle,delimiter='\t')}
    if len(old)!=a.expected_records: raise ValueError(f'old count {len(old)}')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    seen=set(); corrected_values=[]; old_values=[]
    fields=['candidate_id','antigen_id','deepnano_binding_prior','nanobind_binding_prior',
            'nanobind_binary_prediction','deepnano_source_task','nanobind_source_task',
            'deepnano_inference_semantics']
    with gzip.open(a.output,'wt',newline='') as target:
        writer=csv.DictWriter(target,fieldnames=fields,delimiter='\t'); writer.writeheader()
        for task in sorted(x for x in a.corrected_root.glob('task_*') if x.is_dir()):
            receipt=task/'COMPLETE.json'
            if not receipt.exists() or json.loads(receipt.read_text()).get('status')!='PASS':
                raise ValueError(f'incomplete {task}')
            for row in csv.DictReader((task/'output/deepnano_binding.csv').open(newline='')):
                candidate=row['Nanobody ID']; prior=old[candidate]
                if candidate in seen: raise ValueError(f'duplicate {candidate}')
                seen.add(candidate); new=float(row['Prediction']); previous=float(prior['deepnano_binding_prior'])
                corrected_values.append(new); old_values.append(previous)
                writer.writerow({'candidate_id':candidate,'antigen_id':row['Antigen ID'],
                    'deepnano_binding_prior':repr(new),'nanobind_binding_prior':prior['nanobind_binding_prior'],
                    'nanobind_binary_prediction':prior['nanobind_binary_prediction'],
                    'deepnano_source_task':task.name,'nanobind_source_task':prior['source_task'],
                    'deepnano_inference_semantics':'exact-length buckets; batch-composition invariant'})
    if len(seen)!=a.expected_records or seen!=old.keys(): raise ValueError('final ID/count mismatch')
    new=np.asarray(corrected_values); previous=np.asarray(old_values); drift=np.abs(new-previous)
    stats=lambda x:{'min':float(x.min()),'median':float(np.median(x)),'max':float(x.max()),'mean':float(x.mean())}
    summary={'status':'PASS','records':len(seen),'deepnano_binding_prior_corrected':stats(new),
             'old_vs_corrected_abs_diff':stats(drift),'pearson_old_vs_corrected':float(np.corrcoef(previous,new)[0,1]),
             'output':str(a.output),'output_sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),
             'scientific_boundary':'weak binding priors; not Kd, IC50, or blocking evidence'}
    sp=a.output.with_suffix(a.output.suffix+'.summary.json'); sp.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,sort_keys=True))


if __name__=='__main__': main()
