#!/usr/bin/env python3
"""Split a 150k FASTA into four quota-safe 8-node NBB2 waves."""

import argparse,gzip,hashlib,json
from pathlib import Path


def records(path):
 name=None; seq=[]
 with gzip.open(path,'rt') as h:
  for raw in h:
   line=raw.strip()
   if line.startswith('>'):
    if name: yield name,''.join(seq)
    name=line[1:].split()[0];seq=[]
   elif line: seq.append(line)
 if name: yield name,''.join(seq)


def main():
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
 if a.output_dir.exists(): raise FileExistsError(a.output_dir)
 rows=list(records(a.input));
 if len(rows)!=150000 or len({x[0] for x in rows})!=len(rows) or len({x[1] for x in rows})!=len(rows): raise ValueError('150k closure failure')
 sizes=(40000,40000,40000,30000); cursor=0; waves=[]
 for wi,size in enumerate(sizes):
  wave=rows[cursor:cursor+size];cursor+=size; root=a.output_dir/f'wave_{wi:02d}'/'input';root.mkdir(parents=True)
  hs=[(root/f'task_{i:03d}.fasta').open('w') for i in range(8)]; counts=[0]*8
  try:
   for i,(name,seq) in enumerate(wave): shard=i%8;hs[shard].write(f'>{name}\n{seq}\n');counts[shard]+=1
  finally:
   for h in hs:h.close()
  waves.append({'wave':wi,'records':size,'shard_counts':counts,'input_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.fasta')}})
 rec={'status':'READY_FOR_SEQUENTIAL_NBB2_WAVES','records':len(rows),'waves':waves,'max_concurrent_raw_records':40000,
  'scientific_boundary':'monomer structure prediction inputs; not binding, affinity, docking, purity, expression, or blocking'}
 a.output_dir.mkdir(parents=True,exist_ok=True);(a.output_dir/'READY.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n');print(json.dumps(rec,sort_keys=True))

if __name__=='__main__':main()
