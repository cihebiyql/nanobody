#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
AA3={
 'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E','GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F','PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V','SEC':'U','PYL':'O'
}
def extract(path: Path, chain: str):
    residues=[]; seen=set()
    for line in path.read_text(errors='replace').splitlines():
        if not line.startswith(('ATOM  ','HETATM')) or len(line)<27: continue
        if line[21] != chain: continue
        if line[12:16].strip() != 'CA': continue
        key=(line[21],line[22:26],line[26],line[17:20].strip())
        if key in seen: continue
        seen.add(key); residues.append(AA3.get(key[3],'X'))
    return ''.join(residues)
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pdb', required=True, type=Path)
    p.add_argument('--chain', required=True)
    p.add_argument('--expected-seq', required=True)
    p.add_argument('--out-json', type=Path)
    args=p.parse_args()
    observed=extract(args.pdb,args.chain)
    report={'pdb':str(args.pdb),'chain':args.chain,'observed_len':len(observed),'expected_len':len(args.expected_seq),'observed_sha256':hashlib.sha256(observed.encode()).hexdigest(),'expected_sha256':hashlib.sha256(args.expected_seq.encode()).hexdigest(),'exact_match':observed==args.expected_seq,'observed_seq':observed,'expected_seq':args.expected_seq}
    text=json.dumps(report,indent=2)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True,exist_ok=True); args.out_json.write_text(text+'\n')
    print(text)
    if not report['exact_match']:
        raise SystemExit(2)
if __name__=='__main__': main()
