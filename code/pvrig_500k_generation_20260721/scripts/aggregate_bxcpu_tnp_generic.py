#!/usr/bin/env python3
"""Aggregate generic TNP shards with exact selection-ID validation."""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8<<20),b''):h.update(b)
 return h.hexdigest()
def ids(path):
 op=gzip.open if path.suffix=='.gz' else open
 with op(path,'rt',newline='') as f:return {r['candidate_id'] for r in csv.DictReader(f,delimiter='\t')}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--input-dir',type=Path,required=True); p.add_argument('--selection',type=Path,required=True)
 p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--expected',type=int,required=True); p.add_argument('--shards',type=int,required=True); a=p.parse_args()
 a.output_dir.mkdir(parents=True,exist_ok=True); shards=sorted(a.input_dir.glob('node_*.tnp.tsv'))
 if len(shards)!=a.shards: raise SystemExit(f'expected {a.shards} shards, found {len(shards)}')
 output=a.output_dir/'tnp_all.tsv.gz'; seen=set(); counts={}; fields=None
 with gzip.open(output,'wt',newline='') as out:
  writer=None
  for shard in shards:
   if not shard.with_name(shard.name.replace('.tnp.tsv','.READY')).exists(): raise SystemExit(f'missing READY: {shard}')
   checksum_path=shard.with_name(shard.name+'.sha256')
   if not checksum_path.is_file(): raise SystemExit(f'missing checksum: {shard}')
   parts=checksum_path.read_text().strip().split()
   if len(parts)<2 or parts[0]!=sha(shard): raise SystemExit(f'checksum mismatch: {shard}')
   with shard.open(newline='') as src:
    reader=csv.DictReader(src,delimiter='\t')
    if fields is None: fields=list(reader.fieldnames or []); writer=csv.DictWriter(out,fieldnames=fields,delimiter='\t'); writer.writeheader()
    elif list(reader.fieldnames or [])!=fields: raise SystemExit(f'schema mismatch: {shard}')
    for row in reader:
     cid=row['candidate_id']
     if cid in seen: raise SystemExit(f'duplicate: {cid}')
     seen.add(cid); counts[row['status']]=counts.get(row['status'],0)+1; writer.writerow(row)
 expected_ids=ids(a.selection)
 if len(expected_ids)!=a.expected or seen!=expected_ids: raise SystemExit(f'ID mismatch expected={len(expected_ids)} seen={len(seen)}')
 digest=sha(output); receipt={'status':'PASS' if counts.get('PASS',0)==a.expected else 'COMPLETE_WITH_TECHNICAL_NA',
  'records':len(seen),'status_counts':counts,'technical_na_is_not_negative':True,'shards':len(shards),
  'output':str(output.resolve()),'sha256':digest,'id_set_exact_match':True,
  'scientific_boundary':'TNP structure developability proxy; not measured expression or purity'}
 (a.output_dir/'READY.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n'); (a.output_dir/'SHA256SUMS').write_text(f'{digest}  {output.name}\n'); print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__': main()
