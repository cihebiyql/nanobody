#!/usr/bin/env python3
"""Build an exact-ID 1M sequence/prefilter/NBB2/TNP release via SQLite."""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sqlite3,tempfile
from collections import Counter
from pathlib import Path

def op(path,mode): return gzip.open(path,mode,newline='') if path.suffix=='.gz' else open(path,mode,newline='')
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(8<<20),b''):h.update(b)
 return h.hexdigest()
def create(conn,name,fields,unique_sequence=False):
 cols=','.join(f'"{x}" TEXT' for x in fields)
 extra=', UNIQUE("sequence")' if unique_sequence else ''
 conn.execute(f'CREATE TABLE {name} ({cols}, PRIMARY KEY("candidate_id"){extra})')
def load(conn,name,paths,required,unique_sequence=False):
 fields=None; count=0
 for path in paths:
  with op(path,'rt') as f:
   reader=csv.DictReader(f,delimiter='\t'); current=list(reader.fieldnames or [])
   if not required<=set(current): raise ValueError(f'{path}: missing {sorted(required-set(current))}')
   if fields is None: fields=current; create(conn,name,fields,unique_sequence)
   elif current!=fields: raise ValueError(f'{path}: schema mismatch')
   marks=','.join('?' for _ in fields); sql=f'INSERT INTO {name} VALUES ({marks})'
   batch=[]
   for row in reader:
    batch.append(tuple(row.get(x,'') for x in fields)); count+=1
    if len(batch)>=5000: conn.executemany(sql,batch);batch=[]
   if batch: conn.executemany(sql,batch)
 conn.commit(); return fields,count
def main():
 p=argparse.ArgumentParser(); p.add_argument('--candidates',type=Path,required=True);p.add_argument('--prefilter',type=Path,action='append',required=True);p.add_argument('--nbb2',type=Path,action='append',required=True);p.add_argument('--tnp',type=Path,action='append',required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--expected',type=int,default=1000000);p.add_argument('--allow-technical-na',action='store_true');a=p.parse_args()
 a.output_dir.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile(prefix='pvrig1m_',suffix='.sqlite',dir=a.output_dir,delete=True) as tmp:
  conn=sqlite3.connect(tmp.name);conn.execute('PRAGMA journal_mode=OFF');conn.execute('PRAGMA synchronous=OFF');conn.execute('PRAGMA temp_store=FILE')
  cf,cn=load(conn,'candidate',[a.candidates],{'candidate_id','sequence','route_id'},True)
  pf,pn=load(conn,'prefilter',a.prefilter,{'candidate_id','anarci_qc_status'})
  nf,nn=load(conn,'nbb2',a.nbb2,{'candidate_id','status','failure_reason'})
  tf,tn=load(conn,'tnp',a.tnp,{'candidate_id','status','failure_reason'})
  counts={'candidate':cn,'prefilter':pn,'nbb2':nn,'tnp':tn}
  if any(v!=a.expected for v in counts.values()): raise ValueError(f'count mismatch: {counts}')
  for name in ('prefilter','nbb2','tnp'):
   missing=conn.execute(f'SELECT COUNT(*) FROM candidate c LEFT JOIN {name} x USING(candidate_id) WHERE x.candidate_id IS NULL').fetchone()[0]
   extra=conn.execute(f'SELECT COUNT(*) FROM {name} x LEFT JOIN candidate c USING(candidate_id) WHERE c.candidate_id IS NULL').fetchone()[0]
   if missing or extra: raise ValueError(f'{name} ID mismatch missing={missing} extra={extra}')
  pcols=[x for x in pf if x!='candidate_id'];ncols=[x for x in nf if x!='candidate_id'];tcols=[x for x in tf if x!='candidate_id']
  out_fields=cf+[f'prefilter_{x}' for x in pcols]+[f'nbb2_{x}' for x in ncols]+[f'tnp_{x}' for x in tcols]
  select=','.join([f'c."{x}"' for x in cf]+[f'p."{x}"' for x in pcols]+[f'n."{x}"' for x in ncols]+[f't."{x}"' for x in tcols])
  out=a.output_dir/'pvrig_1m_multimetric.tsv.gz'; status_counts={'nbb2':Counter(),'tnp':Counter(),'anarci':Counter()}
  with gzip.open(out,'wt',newline='') as h:
   w=csv.writer(h,delimiter='\t',lineterminator='\n');w.writerow(out_fields)
   cur=conn.execute(f'SELECT {select} FROM candidate c JOIN prefilter p USING(candidate_id) JOIN nbb2 n USING(candidate_id) JOIN tnp t USING(candidate_id) ORDER BY c.candidate_id')
   for row in cur:
    d=dict(zip(out_fields,row)); status_counts['nbb2'][d.get('nbb2_status','')]+=1;status_counts['tnp'][d.get('tnp_status','')]+=1;status_counts['anarci'][d.get('prefilter_anarci_qc_status','')]+=1;w.writerow(row)
  all_success=(status_counts['nbb2'].get('SUCCESS',0)==a.expected and status_counts['tnp'].get('PASS',0)==a.expected and status_counts['anarci'].get('PASS',0)==a.expected)
  if not all_success and not a.allow_technical_na: raise ValueError(f'technical failures remain: {status_counts}')
  digest=sha(out); receipt={'status':'PASS' if all_success else 'NONRELEASABLE_WITH_TECHNICAL_NA','records':a.expected,'id_set_exact_match':True,'candidate_sequence_exact_unique':True,'source_counts':counts,'status_counts':{k:dict(sorted(v.items())) for k,v in status_counts.items()},'technical_na_is_not_negative':True,'output':str(out.resolve()),'sha256':digest,'schema_fields':out_fields,'schema_sha256':hashlib.sha256('\t'.join(out_fields).encode()).hexdigest(),'scientific_boundaries':{'prefilter':'weak priors and developability proxies; not Kd, IC50, measured purity/expression, docking, or blocking evidence','nbb2':'VHH monomer prediction; not binding or docking evidence','tnp':'structure developability proxy; not measured expression or purity'}}
  (a.output_dir/'READY.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');(a.output_dir/'SHA256SUMS').write_text(f'{digest}  {out.name}\n');print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__':main()
