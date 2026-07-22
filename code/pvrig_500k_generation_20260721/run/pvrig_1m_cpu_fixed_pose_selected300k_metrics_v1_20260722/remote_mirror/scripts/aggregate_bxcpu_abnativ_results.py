#!/usr/bin/env python3
"""Merge AbNatiV task outputs while preserving explicit NA semantics."""

import argparse,csv,gzip,hashlib,json
from collections import Counter
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser(); p.add_argument('root',type=Path)
    p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--expected-records',type=int,default=394295); a=p.parse_args()
    tasks=sorted(x for x in a.root.glob('task_*') if x.is_dir())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    seen=set(); scores=[]; statuses=Counter(); reasons=Counter(); fields=None
    with gzip.open(a.output,'wt',newline='') as target:
        writer=None
        for task in tasks:
            receipt=task/'COMPLETE.json'
            if not receipt.exists() or json.loads(receipt.read_text()).get('status')!='PASS':
                raise ValueError(f'task is not complete: {task}')
            with (task/'output/abnativ.csv').open(newline='') as source:
                reader=csv.DictReader(source)
                if fields is None:
                    fields=reader.fieldnames; writer=csv.DictWriter(target,fieldnames=fields,delimiter='\t'); writer.writeheader()
                elif reader.fieldnames!=fields: raise ValueError(f'column mismatch: {task}')
                for row in reader:
                    seq_id=row['seq_id']
                    if seq_id in seen: raise ValueError(f'duplicate: {seq_id}')
                    seen.add(seq_id); statuses[row['abnativ_status']]+=1
                    if row['abnativ_status']=='PASS': scores.append(float(row['AbNatiV VHH Score']))
                    else: reasons[row['abnativ_failure_reason'].split(':',1)[0]]+=1
                    writer.writerow(row)
    if len(seen)!=a.expected_records: raise ValueError(f'{len(seen)} != {a.expected_records}')
    arr=np.asarray(scores,dtype=float)
    stats={"min":float(arr.min()),"q05":float(np.quantile(arr,.05)),
           "median":float(np.median(arr)),"q95":float(np.quantile(arr,.95)),
           "max":float(arr.max()),"mean":float(arr.mean())} if len(arr) else {}
    summary={'status':'PASS','records':len(seen),'tasks':len(tasks),
             'status_counts':dict(statuses),'na_reason_counts':dict(reasons),
             'abnativ_vhh_score_pass_only':stats,'output':str(a.output),
             'output_sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),
             'scientific_boundary':'VHH nativeness/developability proxy; not measured expression or purity'}
    sp=a.output.with_suffix(a.output.suffix+'.summary.json'); sp.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,sort_keys=True))


if __name__=='__main__': main()
