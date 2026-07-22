#!/usr/bin/env python3
"""Filter a TSV by an exact candidate-ID set and verify set closure."""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,os
from pathlib import Path

def opener(path:Path,mode:str): return gzip.open(path,mode,newline='') if path.suffix=='.gz' else open(path,mode,newline='')
def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 return h.hexdigest()
def id_set(path:Path)->set[str]:
 with opener(path,'rt') as f: values=[row['candidate_id'] for row in csv.DictReader(f,delimiter='\t')]
 if len(values)!=len(set(values)): raise ValueError(f'duplicate IDs: {path}')
 return set(values)
def main()->None:
 p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,required=True); p.add_argument('--ids',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True); p.add_argument('--expected',type=int,required=True); a=p.parse_args()
 wanted=id_set(a.ids)
 if len(wanted)!=a.expected: raise ValueError(f'ID count {len(wanted)} != {a.expected}')
 a.output.parent.mkdir(parents=True,exist_ok=True); partial=a.output.with_suffix(a.output.suffix+'.partial'); seen=set()
 with opener(a.source,'rt') as src, gzip.open(partial,'wt',newline='') as dst:
  reader=csv.DictReader(src,delimiter='\t'); fields=list(reader.fieldnames or [])
  required={'candidate_id','sequence','anarci_cdr1','anarci_cdr2','anarci_cdr3'}
  missing=required-set(fields)
  if missing: raise ValueError(f'missing required fields: {sorted(missing)}')
  writer=csv.DictWriter(dst,fieldnames=fields,delimiter='\t',lineterminator='\n'); writer.writeheader()
  for row in reader:
   cid=row['candidate_id']
   if cid in wanted:
    if cid in seen: raise ValueError(f'duplicate source ID: {cid}')
    seen.add(cid); writer.writerow(row)
 if seen!=wanted: raise ValueError(f'ID mismatch missing={len(wanted-seen)} extra={len(seen-wanted)}')
 os.replace(partial,a.output); digest=sha(a.output)
 receipt={'status':'PASS','records':len(seen),'id_set_exact_match':True,'source':str(a.source.resolve()),'ids':str(a.ids.resolve()),'output':str(a.output.resolve()),'sha256':digest}
 (a.output.parent/(a.output.name+'.receipt.json')).write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
 print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__': main()
