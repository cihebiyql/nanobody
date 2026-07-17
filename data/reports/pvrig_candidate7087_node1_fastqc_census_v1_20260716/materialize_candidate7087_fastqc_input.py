#!/usr/bin/env python3
"""Materialize the frozen label-free 7,087-candidate Node1 Fast-QC census input."""
from __future__ import annotations
import csv,hashlib,json,sys
from collections import Counter
from pathlib import Path

BASE=Path(__file__).resolve().parents[2]
PHASE2=BASE/'experiments/phase2_5080_v1'
PREREG=PHASE2/'audits/phase2_candidate7087_node1_fastqc_census_v1_preregistration.json'
POOL=PHASE2/'prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv'
V4D=PHASE2/'data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv'
V4F=PHASE2/'data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv'
V4G=PHASE2/'data_splits/pvrig_v4_g/unseen96_acquisition_manifest.tsv'
RESERVE=PHASE2/'data_splits/pvrig_v4_g/untouched_reserve2_parents.tsv'
EXPECTED={
 PREREG:'0112cd909702d85f760ebef92b7bc1ab5db83705c5c8546e45cdfe21b08c175b',
 POOL:'dd97835cfa3e39229d3ebddfe37768c7a8346a6237e35d2dbe16dc3d16ab965b',
 V4D:'c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd',
 V4F:'3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334',
 V4G:'e814103ee90831e33b3f04a7e8a477e68695d61401d96732b7e95829b1bd306f',
 RESERVE:'98c11e8f72d97d60c9e772fa2bb256622f1ed6e1e9fddd9e136a8cd42959bb75',
}
ALLOWED=['candidate_id','vhh_sequence','sequence_sha256','parent_id','parent_framework_cluster','target_patch_id','design_mode','cdr1_after','cdr2_after','cdr3_after']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(path,delimiter=','):
 with path.open(newline='',encoding='utf-8-sig') as h:return list(csv.DictReader(h,delimiter=delimiter))
def ids(path):return {r['candidate_id'] for r in rows(path,'\t')}

def main():
 out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=False)
 for p,d in EXPECTED.items():
  if sha(p)!=d:raise RuntimeError(f'frozen_hash_mismatch:{p}')
 prereg=json.loads(PREREG.read_text())
 if prereg['status']!='FROZEN_BEFORE_GLOBAL_7087_NODE1_FAST_QC_RESULTS':raise RuntimeError('prereg_not_frozen')
 v4d,v4f,v4g=ids(V4D),ids(V4F),ids(V4G)
 reserve={r['parent_framework_cluster'] for r in rows(RESERVE,'\t')}
 source=rows(POOL)
 if len(source)!=7087:raise RuntimeError(f'row_count:{len(source)}')
 projected=[]; seen_ids=set(); seen_seq=set()
 for raw in source:
  row={k:raw[k] for k in ALLOWED}
  cid,seq=row['candidate_id'],row['vhh_sequence']
  if cid in seen_ids or seq in seen_seq:raise RuntimeError(f'duplicate_id_or_sequence:{cid}')
  if hashlib.sha256(seq.encode()).hexdigest()!=row['sequence_sha256']:raise RuntimeError(f'sequence_hash:{cid}')
  seen_ids.add(cid);seen_seq.add(seq)
  roles=[]
  if cid in v4d:roles.append('V4_D_MEMBER')
  if cid in v4f:roles.append('V4_F_SEALED_HOLDOUT_MEMBER')
  if cid in v4g:roles.append('V4_G_ACQUISITION_MEMBER')
  if row['parent_framework_cluster'] in reserve:roles.append('RESERVE2_PARENT')
  row['census_role']=';'.join(roles) if roles else 'GLOBAL_POOL_OTHER'
  projected.append(row)
 if len({r['parent_framework_cluster'] for r in projected})!=40:raise RuntimeError('parent_count_not_40')
 fasta=out/'candidate7087.fasta'
 fasta.write_text(''.join(f">{r['candidate_id']}\n{r['vhh_sequence']}\n" for r in projected))
 lineage=out/'candidate7087_lineage.tsv'
 fields=ALLOWED+['census_role']
 with lineage.open('w',newline='',encoding='utf-8') as h:
  w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(projected)
 counts=Counter(r['parent_framework_cluster'] for r in projected)
 audit={
  'schema_version':'candidate7087_node1_fastqc_census_input_audit_v1','status':'PASS_LABEL_FREE_7087_INPUT_CLOSED',
  'candidate_count':len(projected),'parent_count':len(counts),'parent_candidate_counts':dict(sorted(counts.items())),
  'source_pool_sha256':EXPECTED[POOL],'preregistration_sha256':EXPECTED[PREREG],
  'split_manifest_hashes':{p.name:EXPECTED[p] for p in [V4D,V4F,V4G,RESERVE]},
  'allowed_source_fields':ALLOWED,'disallowed_source_fields_exported':0,
  'label_path_access':{'docking':0,'v4_d_geometry':0,'v4_f_labels':0,'model_score':0,'experimental':0},
  'output_sha256':{'candidate7087.fasta':sha(fasta),'candidate7087_lineage.tsv':sha(lineage)},
  'claim_boundary':prereg['claim_boundary'],
 }
 (out/'INPUT_AUDIT.json').write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n')
 print(json.dumps(audit,indent=2,sort_keys=True))
if __name__=='__main__':main()
