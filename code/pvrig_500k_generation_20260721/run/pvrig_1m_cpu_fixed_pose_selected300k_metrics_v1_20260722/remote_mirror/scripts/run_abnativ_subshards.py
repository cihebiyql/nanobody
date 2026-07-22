#!/usr/bin/env python3
"""Run independent single-core AbNatiV subshards to saturate CPU nodes."""

import argparse
import csv
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from Bio import SeqIO


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('fasta',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--workers',type=int,required=True)
    parser.add_argument('--python',required=True)
    parser.add_argument('--scorer',required=True)
    args=parser.parse_args()

    records=list(SeqIO.parse(args.fasta,'fasta'))
    if not records: raise SystemExit('empty FASTA')
    workers=min(args.workers,len(records))
    root=args.output.parent/'subshards'; root.mkdir(parents=True,exist_ok=True)
    jobs=[]
    for index in range(workers):
        shard_records=records[index::workers]
        fasta=root/f'shard_{index:02d}.fasta'; output=root/f'shard_{index:02d}.csv'
        SeqIO.write(shard_records,fasta,'fasta')
        jobs.append((fasta,output))

    env=os.environ.copy()
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        env[name]='1'

    def run(job):
        fasta,output=job
        log=output.with_suffix('.log')
        with log.open('w') as handle:
            subprocess.run([args.python,args.scorer,str(fasta),'-o',str(output),
                            '--ncpu','1','--batch-size','128'],check=True,
                           stdout=handle,stderr=subprocess.STDOUT,env=env)
        return output

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outputs=list(pool.map(run,jobs))

    fieldnames=None; count=0
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',newline='') as target:
        writer=None
        for output in outputs:
            with output.open(newline='') as source:
                reader=csv.DictReader(source)
                if fieldnames is None:
                    fieldnames=reader.fieldnames
                    writer=csv.DictWriter(target,fieldnames=fieldnames)
                    writer.writeheader()
                elif reader.fieldnames != fieldnames:
                    raise ValueError(f'column mismatch in {output}')
                for row in reader:
                    writer.writerow(row); count+=1
    if count != len(records):
        raise ValueError(f'merged rows {count} != input records {len(records)}')


if __name__=='__main__':
    main()
