#!/usr/bin/env python3
"""Minimal AbNatiV scoring entry point that avoids unrelated humanisation imports."""

import argparse
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from anarci import anarci as run_anarci
from abnativ.model.scoring_functions import abnativ_scoring
import pandas as pd


def batch_aho_align(records, ncpu):
    """Run one multithreaded hmmscan for the whole shard, not one per sequence."""
    numbered, details, _ = run_anarci(
        [(record.id, str(record.seq)) for record in records],
        scheme='aho', output=False, ncpu=ncpu, allow=['H'])
    aligned=[]; failed={}
    for record, domains, domain_details in zip(records, numbered, details):
        if not domains or not domain_details or domain_details[0].get('chain_type') != 'H':
            failed[record.id]='ANARCI_NO_HEAVY_DOMAIN'; continue
        positions=domains[0][0]
        insertions=[f'{position}{insertion.strip()}' for (position,insertion),_ in positions if insertion.strip()]
        if insertions:
            failed[record.id]='AHO_INSERTION_UNSUPPORTED:'+','.join(insertions)
            continue
        sequence=['-']*149
        for (position, insertion), residue in positions:
            if 1 <= position <= 149:
                sequence[position-1]=residue
        aligned.append(SeqRecord(Seq(''.join(sequence)),id=record.id,description=''))
    return aligned,failed


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('fasta',type=Path)
    parser.add_argument('-o','--output',type=Path,required=True)
    parser.add_argument('--ncpu',type=int,default=1)
    parser.add_argument('--batch-size',type=int,default=128)
    args=parser.parse_args()
    records=list(SeqIO.parse(args.fasta,'fasta'))
    if not records:
        raise SystemExit('empty FASTA')
    aligned_records,failures=batch_aho_align(records,args.ncpu)
    if aligned_records:
        mean,_=abnativ_scoring(
            model_type='VHH',seq_records=aligned_records,batch_size=args.batch_size,
            mean_score_only=True,do_align=False,is_VHH=True,
            is_plotting_profiles=False,output_dir=str(args.output.parent),
            output_id=args.output.stem,verbose=False,run_parall_al=False)
    else:
        mean=pd.DataFrame(columns=['seq_id','input_seq','aligned_seq','AbNatiV VHH Score',
            'AbNatiV CDR1-VHH Score','AbNatiV CDR2-VHH Score','AbNatiV CDR3-VHH Score',
            'AbNatiV FR-VHH Score'])
    mean['abnativ_status']='PASS'; mean['abnativ_failure_reason']=''
    failed_rows=[]
    sequence_by_id={record.id:str(record.seq) for record in records}
    for seq_id,reason in failures.items():
        failed_rows.append({'seq_id':seq_id,'input_seq':sequence_by_id[seq_id],
            'aligned_seq':'','AbNatiV VHH Score':'','AbNatiV CDR1-VHH Score':'',
            'AbNatiV CDR2-VHH Score':'','AbNatiV CDR3-VHH Score':'',
            'AbNatiV FR-VHH Score':'','abnativ_status':'NA',
            'abnativ_failure_reason':reason})
    if failed_rows:
        mean=pd.concat([mean,pd.DataFrame(failed_rows)],ignore_index=True)
    order={record.id:index for index,record in enumerate(records)}
    mean['_order']=mean['seq_id'].map(order); mean=mean.sort_values('_order').drop(columns=['_order'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    mean.to_csv(args.output,index=False)


if __name__=='__main__':
    main()
