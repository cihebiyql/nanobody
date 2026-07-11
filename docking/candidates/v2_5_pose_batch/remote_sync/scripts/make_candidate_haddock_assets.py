#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path


def parse_range(value: str) -> list[int]:
    start, end = value.split('-', 1)
    return list(range(int(start), int(end) + 1))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = root / 'manifests/selected_candidates_manifest.tsv'
    ranges_path = root / 'inputs/candidate_cdr_ranges.tsv'
    hotspots_path = root / 'inputs/hotspot_residues_8x6b.txt'

    with manifest.open(newline='') as f:
        candidates = list(csv.DictReader(f, delimiter='\t'))
    with ranges_path.open(newline='') as f:
        ranges = {row['candidate_id']: row for row in csv.DictReader(f, delimiter='\t')}
    hotspots = [line.strip() for line in hotspots_path.read_text().splitlines() if line.strip()]

    for row in candidates:
        cid = row['candidate_id']
        cdr_row = ranges[cid]
        cdr_residues = parse_range(cdr_row['cdr1_range']) + parse_range(cdr_row['cdr2_range']) + parse_range(cdr_row['cdr3_range'])
        data_dir = root / 'haddock3' / cid / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / f'cdr_residues_{cid}_seq_numbering.txt').write_text('\n'.join(map(str, cdr_residues)) + '\n')
        (data_dir / 'hotspot_residues_8x6b.txt').write_text('\n'.join(hotspots) + '\n')

        tbl_lines: list[str] = []
        for residue in cdr_residues:
            tbl_lines.append(f'assign (resi {residue} and segid A)')
            tbl_lines.append('(')
            for index, hotspot in enumerate(hotspots):
                prefix = '       ' if index == 0 else '        or\n       '
                tbl_lines.append(f'{prefix}(resi {hotspot} and segid B)')
            tbl_lines.append(') 2.0 2.0 0.0\n')
        (data_dir / f'{cid}_cdr_to_pvrig_hotspot_ambig.tbl').write_text('\n'.join(tbl_lines) + '\n')

        cfg = f'''# {cid} VHH to PVRIG 8X6B hotspot/CDR-guided HADDOCK3 docking\n# V2.5 package boundary: computational pose/QC proxy only; not binding/blocker proof.\nrun_dir = "run_{cid}_pvrig_hotspot"\nmode = "local"\nncores = 8\n\nmolecules = [\n    "data/{cid}_vhh_chainA.pdb",\n    "data/pvrig_8x6b_chainB.pdb",\n]\n\n[topoaa]\n\n[rigidbody]\nambig_fname = "data/{cid}_cdr_to_pvrig_hotspot_ambig.tbl"\ntolerance = 5\nsampling = 40\n\n[seletop]\nselect = 10\n\n[flexref]\ntolerance = 10\nambig_fname = "data/{cid}_cdr_to_pvrig_hotspot_ambig.tbl"\n\n[emref]\nambig_fname = "data/{cid}_cdr_to_pvrig_hotspot_ambig.tbl"\n\n[clustfcc]\nmin_population = 1\n\n[seletopclusts]\ntop_models = 4\n'''
        (root / 'haddock3' / cid / f'{cid}_pvrig_hotspot.cfg').write_text(cfg)

    print(json.dumps({'candidates': [row['candidate_id'] for row in candidates], 'hotspots': len(hotspots)}, indent=2))


if __name__ == '__main__':
    main()
