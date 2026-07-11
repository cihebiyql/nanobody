#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path

def parse_range(r):
    a,b=r.split('-',1); return list(range(int(a),int(b)+1))

def main():
    root=Path(__file__).resolve().parents[1]
    cand=[]
    with (root/'manifests/selected_candidates_manifest.tsv').open(newline='') as f:
        for r in csv.DictReader(f, delimiter='\t'): cand.append(r)
    ranges={}
    with (root/'inputs/candidate_cdr_ranges.tsv').open(newline='') as f:
        for r in csv.DictReader(f, delimiter='\t'): ranges[r['candidate_id']]=r
    hotspots=[x.strip() for x in (root/'inputs/hotspot_residues_8x6b.txt').read_text().splitlines() if x.strip()]
    for r in cand:
        cid=r['candidate_id']; cr=ranges[cid]
        cdr_res=parse_range(cr['cdr1_range'])+parse_range(cr['cdr2_range'])+parse_range(cr['cdr3_range'])
        d=root/'haddock3'/cid/'data'; d.mkdir(parents=True, exist_ok=True)
        (d/f'cdr_residues_{cid}_seq_numbering.txt').write_text('\n'.join(map(str,cdr_res))+'\n')
        (d/'hotspot_residues_8x6b.txt').write_text('\n'.join(hotspots)+'\n')
        lines=[]
        for res in cdr_res:
            lines.append(f'assign (resi {res} and segid A)')
            lines.append('(')
            for i,h in enumerate(hotspots):
                sep='        or' if i else '      '
                lines.append(f'{sep}\n       (resi {h} and segid B)' if i else f'       (resi {h} and segid B)')
            lines.append(') 2.0 2.0 0.0\n')
        (d/f'{cid}_cdr_to_pvrig_hotspot_ambig.tbl').write_text('\n'.join(lines)+'\n')
        cfg=f'''# {cid} VHH to PVRIG 8X6B hotspot/CDR-guided HADDOCK3 docking\nrun_dir = "run_{cid}_pvrig_hotspot"\nmode = "local"\nncores = 8\n\nmolecules = [\n    "data/{cid}_vhh_chainA.pdb",\n    "data/pvrig_8x6b_chainB.pdb",\n]\n\n[topoaa]\n\n[rigidbody]\nambig_fname = "data/{cid}_cdr_to_pvrig_hotspot_ambig.tbl"\ntolerance = 5\nsampling = 40\n\n[seletop]\nselect = 10\n\n[flexref]\ntolerance = 10\nambig_fname = "data/{cid}_cdr_to_pvrig_hotspot_ambig.tbl"\n\n[emref]\nambig_fname = "data/{cid}_cdr_to_pvrig_hotspot_ambig.tbl"\n\n[clustfcc]\nmin_population = 1\n\n[seletopclusts]\ntop_models = 4\n'''
        (root/'haddock3'/cid/f'{cid}_pvrig_hotspot.cfg').write_text(cfg)
    print(json.dumps({'candidates':[r['candidate_id'] for r in cand], 'hotspots':len(hotspots)}, indent=2))
if __name__ == '__main__': main()
