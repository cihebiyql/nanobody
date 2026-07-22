#!/usr/bin/env python3
"""Normalize RFantibody/ProteinMPNN raw pools before the final 1M freeze."""
from __future__ import annotations

import argparse,csv,gzip,hashlib,importlib.util,json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('cpu_routes',HERE/'generate_local_cpu_routes.py')
GEN=importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(GEN)
AA=set('ACDEFGHIKLMNPQRSTVWY')
FIELDS=[
 'candidate_id','sequence','sequence_sha256','sequence_length','route_id','generation_seed',
 'target_patch_assignment','design_mode','parent_id','parent_cluster','cdr1_after','cdr2_after',
 'cdr3_after','designed_regions','generator','generator_version','generation_batch',
 'max_positive_cdr_identity','max_positive_cdr_identity_detail','fast_qc_status','fast_qc_reasons',
 'source_candidate_id','source_run_id','source_arm_id','source_backbone_group_id','source_pose_id',
 'source_mpnn_index','source_row_kind'
]

def op(path:Path,mode:str): return gzip.open(path,mode,newline='') if path.suffix=='.gz' else open(path,mode,newline='')
def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(8<<20),b''):h.update(b)
 return h.hexdigest()
def cpu_sequences(paths:list[Path])->set[str]:
 values=set()
 for path in paths:
  with op(path,'rt') as f:
   for row in csv.DictReader(f,delimiter='\t'):
    seq=row['sequence'].strip().upper()
    if seq in values: raise ValueError(f'duplicate CPU sequence across frozen inputs: {row["candidate_id"]}')
    values.add(seq)
 return values
def qc(sequence:str,cdrs:dict[str,str],positives:dict[str,dict[str,str]])->tuple[str,str,float,str]:
 reasons=[]
 if not 95<=len(sequence)<=160: reasons.append('length_outside_95_160')
 if set(sequence)-AA: reasons.append('invalid_amino_acid')
 if any(not x or sequence.count(x)!=1 for x in cdrs.values()): reasons.append('cdr_missing_or_nonunique')
 if sequence.count('C')%2: reasons.append('odd_total_cys')
 if GEN.has_n_glyco(''.join(cdrs.values())): reasons.append('cdr_n_glyco_motif')
 if sequence and sum(x in GEN.HYDROPHOBIC for x in sequence)/len(sequence)>0.52: reasons.append('high_hydrophobic_fraction')
 if sequence and max(Counter(sequence).values())/len(sequence)>0.28: reasons.append('severe_low_complexity')
 if GEN.longest_hydrophobic_run(''.join(cdrs.values()))>=5: reasons.append('cdr_hydrophobic_run_ge_5')
 ident,detail=GEN.max_positive_identity(cdrs,positives)
 if ident>=0.80: reasons.append('positive_any_cdr_identity_ge_80pct')
 return ('PASS' if not reasons else 'FAIL','|'.join(reasons),ident,detail)
def normalize_rf(row:dict[str,str],positives)->dict[str,str]:
 sequence=row['sequence'].strip().upper(); digest=hashlib.sha256(sequence.encode()).hexdigest()
 cdrs={x:row[x].strip().upper() for x in ('cdr1','cdr2','cdr3')}; status,reasons,ident,detail=qc(sequence,cdrs,positives)
 if row.get('valid_sequence','').lower() not in {'true','1'}: status='FAIL'; reasons='|'.join(filter(None,[reasons,'rfantibody_invalid_sequence']))
 if row.get('exact_known_positive_match','').lower() in {'true','1'}: status='FAIL'; reasons='|'.join(filter(None,[reasons,'exact_known_positive_match']))
 if row.get('scaffold_lane')!='primary_vhhified': status='FAIL'; reasons='|'.join(filter(None,[reasons,'non_primary_scaffold_lane']))
 return {'candidate_id':f'P1M__RFANTIBODY__{digest[:20].upper()}','sequence':sequence,'sequence_sha256':digest,'sequence_length':str(len(sequence)),
  'route_id':'rfantibody','generation_seed':f"{row.get('arm_id','')}:{row.get('backbone_index','')}:{row.get('mpnn_index','')}",
  'target_patch_assignment':row.get('patch_id',''),'design_mode':f"rfantibody_{row.get('h3_regime','')}",'parent_id':row.get('scaffold_id',''),
  'parent_cluster':row.get('scaffold_id',''),'cdr1_after':cdrs['cdr1'],'cdr2_after':cdrs['cdr2'],'cdr3_after':cdrs['cdr3'],
  'designed_regions':'cdr1,cdr2,cdr3','generator':'RFantibody','generator_version':'node1_20260722','generation_batch':row.get('source_run_id',''),
  'max_positive_cdr_identity':f'{ident:.6f}','max_positive_cdr_identity_detail':detail,'fast_qc_status':status,'fast_qc_reasons':reasons,
  'source_candidate_id':row.get('candidate_id',''),'source_run_id':row.get('source_run_id',''),'source_arm_id':row.get('arm_id',''),
  'source_backbone_group_id':row.get('backbone_group_id',''),'source_pose_id':'','source_mpnn_index':row.get('mpnn_index',''),'source_row_kind':'rfantibody_raw'}
def normalize_mpnn(row:dict[str,str],positives)->dict[str,str]:
 sequence=row['sequence'].strip().upper(); digest=hashlib.sha256(sequence.encode()).hexdigest()
 cdrs={x:row[f'{x}_after'].strip().upper() for x in ('cdr1','cdr2','cdr3')}; status,reasons,ident,detail=qc(sequence,cdrs,positives)
 if row.get('fast_qc_status')!='PASS': status='FAIL'; reasons='|'.join(filter(None,[reasons,row.get('fast_qc_reasons',''),'mpnn_source_fast_qc_fail']))
 return {'candidate_id':f'P1M__FIXED_POSE_MPNN__{digest[:20].upper()}','sequence':sequence,'sequence_sha256':digest,'sequence_length':str(len(sequence)),
  'route_id':'fixed_pose_mpnn','generation_seed':f"{row.get('pose_id','')}:{row.get('mpnn_index','')}",'target_patch_assignment':row.get('target_patch','positive_pose_conditioned_mixed'),
  'design_mode':'fixed_positive_pose_cdr123','parent_id':row.get('source_candidate_id',''),'parent_cluster':row.get('source_candidate_id',''),
  'cdr1_after':cdrs['cdr1'],'cdr2_after':cdrs['cdr2'],'cdr3_after':cdrs['cdr3'],'designed_regions':'cdr1,cdr2,cdr3',
  'generator':'RFantibody_ProteinMPNN_fixed_pose','generator_version':row.get('generator_version','node1_20260722'),'generation_batch':row.get('generator_version',''),
  'max_positive_cdr_identity':f'{ident:.6f}','max_positive_cdr_identity_detail':detail,'fast_qc_status':status,'fast_qc_reasons':reasons,
  'source_candidate_id':row.get('candidate_id',''),'source_run_id':'','source_arm_id':'','source_backbone_group_id':'','source_pose_id':row.get('pose_id',''),
  'source_mpnn_index':row.get('mpnn_index',''),'source_row_kind':'fixed_pose_exact_unique_fastqc'}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--cpu',type=Path,action='append',required=True); p.add_argument('--rf-raw',type=Path,required=True); p.add_argument('--mpnn-pool',type=Path,required=True)
 p.add_argument('--positive-cdr',type=Path,required=True); p.add_argument('--positive-fasta',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args()
 a.output_dir.mkdir(parents=True,exist_ok=True); cpu=cpu_sequences(a.cpu); positives=GEN.load_positive_cdrs(a.positive_cdr,a.positive_fasta)
 all_path=a.output_dir/'gpu_raw_normalized_all.tsv.gz'; pass_path=a.output_dir/'gpu_fast_qc_pass_exact_unique.tsv.gz'; fasta_path=a.output_dir/'gpu_fast_qc_pass_exact_unique.fasta.gz'
 seen=set(cpu); counts=Counter(); route_pass=Counter()
 with gzip.open(all_path,'wt',newline='') as all_h,gzip.open(pass_path,'wt',newline='') as pass_h,gzip.open(fasta_path,'wt') as fasta:
  aw=csv.DictWriter(all_h,fieldnames=FIELDS,delimiter='\t',lineterminator='\n'); pw=csv.DictWriter(pass_h,fieldnames=FIELDS,delimiter='\t',lineterminator='\n'); aw.writeheader();pw.writeheader()
  for path,kind in ((a.rf_raw,'rf'),(a.mpnn_pool,'mpnn')):
   with op(path,'rt') as src:
    for source in csv.DictReader(src,delimiter='\t'):
     row=normalize_rf(source,positives) if kind=='rf' else normalize_mpnn(source,positives); counts[f'{kind}_raw']+=1
     seq=row['sequence']
     if seq in seen:
      row['fast_qc_status']='FAIL'; row['fast_qc_reasons']='|'.join(filter(None,[row['fast_qc_reasons'],'exact_duplicate_or_cpu_overlap']))
     else: seen.add(seq)
     aw.writerow(row)
     if row['fast_qc_status']=='PASS': pw.writerow(row); fasta.write(f">{row['candidate_id']}\n{seq}\n"); route_pass[row['route_id']]+=1
     else:
      for reason in row['fast_qc_reasons'].split('|'):
       if reason: counts[f'fail:{reason}']+=1
 receipt={'status':'READY_FOR_ANARCI' if route_pass['rfantibody']>=150000 and route_pass['fixed_pose_mpnn']>=150000 else 'HOLD_INSUFFICIENT_FAST_QC_PASS',
  'cpu_excluded_sequences':len(cpu),'source_counts':dict(sorted(counts.items())),'route_fast_qc_pass':dict(sorted(route_pass.items())),
  'outputs':{x.name:sha(x) for x in (all_path,pass_path,fasta_path)},'scientific_boundary':'generated sequence QC only; not binding, affinity, docking, or blocking evidence'}
 (a.output_dir/'NORMALIZE_RECEIPT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n'); print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__': main()
