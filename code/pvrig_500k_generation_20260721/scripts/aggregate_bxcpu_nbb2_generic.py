#!/usr/bin/env python3
"""Strictly aggregate a manifest-driven generic NanoBodyBuilder2 campaign."""

from __future__ import annotations
import argparse,csv,gzip,hashlib,json
from collections import Counter
from pathlib import Path

def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(8<<20),b''): h.update(b)
 return h.hexdigest()

def fasta_ids(root:Path)->set[str]:
 ids=set()
 for path in sorted(root.glob('task_*.fasta')):
  for line in path.open():
   if line.startswith('>'):
    cid=line[1:].split()[0]
    if cid in ids: raise ValueError(f'duplicate input ID: {cid}')
    ids.add(cid)
 return ids

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument('--campaign',type=Path,required=True)
 p.add_argument('--full-job-id',required=True); p.add_argument('--shards',type=int,required=True)
 p.add_argument('--expected',type=int,required=True); a=p.parse_args()
 expected_ids=fasta_ids(a.campaign/'input')
 if len(expected_ids)!=a.expected: raise ValueError(f'input count {len(expected_ids)} != {a.expected}')
 results=a.campaign/f'results_{a.full_job_id}'; archives=a.campaign/f'archives_{a.full_job_id}'
 out=a.campaign/f'aggregated_{a.full_job_id}'; out.mkdir(parents=True,exist_ok=True)
 manifests=sorted(results.glob('node_*/node_*.manifest.tsv')); ready=sorted(archives.glob('node_*.READY.json'))
 if len(manifests)!=a.shards or len(ready)!=a.shards: raise ValueError(f'incomplete shards manifests={len(manifests)} ready={len(ready)}')
 rows=[]; source={}
 for path in manifests:
  with path.open(newline='') as f:
   for row in csv.DictReader(f,delimiter='\t'): rows.append(row); source[row['candidate_id']]=path
 ids=[r['candidate_id'] for r in rows]
 if len(ids)!=len(set(ids)) or set(ids)!=expected_ids: raise ValueError('manifest ID set mismatch')
 combined=out/'nbb2_manifest.tsv.gz'
 with gzip.open(combined,'wt',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t'); w.writeheader(); w.writerows(rows)
 counts=Counter(r['status'] for r in rows); failures=Counter(r['failure_reason'] for r in rows if r['status']!='SUCCESS')
 verified=0
 for row in rows:
  if row['status']!='SUCCESS': continue
  path=source[row['candidate_id']].parent/'raw'/f"worker_{int(row['worker_id']):02d}"/row['pdb_relative_path']
  if not path.is_file() or path.stat().st_size!=int(row['pdb_bytes']) or sha(path)!=row['pdb_sha256']:
   raise ValueError(f'PDB integrity mismatch: {path}')
  if row['pdb_sequence_match']!='true' or int(row['atom_records'])<500: raise ValueError(f'PDB QC mismatch: {path}')
  verified+=1
 archive_checks=[]
 seen_ready=set()
 for ready_path in ready:
  payload=json.loads(ready_path.read_text())
  shard=ready_path.name.removeprefix('node_').removesuffix('.READY.json')
  expected_archive=f'node_{shard}.tar.gz'
  if payload.get('archive')!=expected_archive: raise ValueError(f'archive metadata mismatch: {ready_path}')
  manifest_path=results/f'node_{shard}'/f'node_{shard}.manifest.tsv'
  with manifest_path.open(newline='') as handle:
   shard_records=sum(1 for _ in csv.DictReader(handle,delimiter='\t'))
  if int(payload.get('records',-1))!=shard_records or int(payload.get('expected_records',-1))!=shard_records:
   raise ValueError(f'record metadata mismatch: {ready_path}')
  if shard in seen_ready: raise ValueError(f'duplicate READY shard: {shard}')
  seen_ready.add(shard)
  path=archives/payload['archive']; observed=sha(path)
  if observed!=payload['archive_sha256']: raise ValueError(f'archive hash mismatch: {path}')
  archive_checks.append({'archive':path.name,'sha256':observed,'bytes':path.stat().st_size})
 partial=list(results.rglob('*.partial'))
 payload={'status':'PASS' if verified==a.expected else 'COMPLETE_WITH_TECHNICAL_NA',
  'records':len(rows),'expected_records':a.expected,'status_counts':dict(sorted(counts.items())),
  'verified_success_pdbs':verified,'technical_failure_reasons':dict(sorted(failures.items())),
  'technical_na_is_not_negative':True,'shards':a.shards,'archive_checks':archive_checks,
  'partial_file_count':len(partial),'manifest':str(combined.resolve()),'manifest_sha256':sha(combined),
  'scientific_boundary':'VHH monomer prediction and technical QC; not binding, affinity, docking, or blocking evidence'}
 (out/'COMPLETE.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n'); print(json.dumps(payload,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
