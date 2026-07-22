#!/usr/bin/env python3
"""Convert selected fixed-pose records into the established prefilter schema."""

from __future__ import annotations

import argparse,csv,gzip,hashlib,json
from pathlib import Path


FIELDS=["route_id","generation_seed","target_patch_assignment","design_mode","parent_id","parent_cluster",
"generation_batch","candidate_id","sequence","sequence_sha256","cdr1_after","cdr2_after","cdr3_after",
"designed_regions","generator","generator_version","sequence_length","max_positive_cdr_identity",
"max_positive_cdr_identity_detail"]


def main():
 p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args()
 if a.output_dir.exists(): raise FileExistsError(a.output_dir)
 a.output_dir.mkdir(parents=True); tsv=a.output_dir/'fixed_pose_selected300k_candidates.tsv.gz'; fasta=a.output_dir/'fixed_pose_selected300k.fasta.gz'
 count=0; ids=set(); seqs=set()
 with gzip.open(a.input,'rt',newline='') as src,gzip.open(tsv,'wt',newline='',compresslevel=1) as dst,gzip.open(fasta,'wt',compresslevel=1) as fa:
  reader=csv.DictReader(src,delimiter='\t'); writer=csv.DictWriter(dst,fieldnames=FIELDS,delimiter='\t',lineterminator='\n'); writer.writeheader()
  for row in reader:
   cid=row['candidate_id']; seq=row['sequence']; digest=hashlib.sha256(seq.encode()).hexdigest()
   if cid in ids or seq in seqs or digest!=row['sequence_sha256']: raise ValueError('ID/sequence/hash closure failure')
   ids.add(cid); seqs.add(seq); count+=1
   writer.writerow({'route_id':'fixed_pose_proteinmpnn_cpu','generation_seed':row['generation_seed'],
    'target_patch_assignment':row['target_patch'],'design_mode':row['design_mode'],'parent_id':row['source_candidate_id'],
    'parent_cluster':'positive_pose_source_'+row['source_candidate_id'],'generation_batch':'pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722',
    'candidate_id':cid,'sequence':seq,'sequence_sha256':digest,'cdr1_after':row['cdr1'],'cdr2_after':row['cdr2'],
    'cdr3_after':row['cdr3'],'designed_regions':'cdr1,cdr2,cdr3','generator':row['design_method'],
    'generator_version':'cpu_sequence_only_v4_20260722','sequence_length':len(seq),
    'max_positive_cdr_identity':row['max_positive_cdr_identity'],
    'max_positive_cdr_identity_detail':row['max_positive_cdr_identity_detail']})
   fa.write(f'>{cid}\n{seq}\n')
 if count!=300000: raise ValueError(f'{count} != 300000')
 outputs=[tsv,fasta]; receipt={'status':'READY','records':count,'exact_unique_ids':len(ids),'exact_unique_sequences':len(seqs),
  'outputs':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in outputs},
  'scientific_boundary':'inputs for computational prefilter proxies; not measured purity, expression, affinity, or blocking'}
 (a.output_dir/'READY.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n'); print(json.dumps(receipt,sort_keys=True))

if __name__=='__main__': main()
