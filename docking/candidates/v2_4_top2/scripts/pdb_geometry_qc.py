#!/usr/bin/env python3
"""Lightweight PDB geometry sanity checks for protein chains."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pdb', required=True)
    p.add_argument('--chain', action='append', help='Chain ID to report; repeatable. Defaults to all chains.')
    p.add_argument('--out-json')
    return p.parse_args()


def parse_coord(line):
    try:
        return float(line[30:38]), float(line[38:46]), float(line[46:54])
    except Exception:
        # Fallback for overflowed nonstandard PDB whitespace columns.
        parts = line.split()
        if len(parts) >= 9:
            return float(parts[6]), float(parts[7]), float(parts[8])
        raise


def dist(a, b):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))


def main():
    args = parse_args()
    path = Path(args.pdb)
    chains = set(args.chain or [])
    residues = {}
    bad_coord_lines = 0
    for line in path.read_text(errors='replace').splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')) or len(line) < 54:
            continue
        chain = line[21]
        if chains and chain not in chains:
            continue
        atom = line[12:16].strip()
        key = (chain, line[22:26].strip(), line[26].strip(), line[17:20].strip())
        try:
            xyz = parse_coord(line)
        except Exception:
            bad_coord_lines += 1
            continue
        residues.setdefault(chain, []).append((key, atom, xyz))
    report = {'pdb': str(path), 'bad_coord_lines': bad_coord_lines, 'chains': {}}
    for chain, atoms in sorted(residues.items()):
        ca = [(key, xyz) for key, atom, xyz in atoms if atom == 'CA']
        dists = [dist(ca[i][1], ca[i+1][1]) for i in range(len(ca)-1)]
        all_xyz = [xyz for _key, _atom, xyz in atoms]
        bbox = None
        if all_xyz:
            bbox = {
                'min': [min(x[i] for x in all_xyz) for i in range(3)],
                'max': [max(x[i] for x in all_xyz) for i in range(3)],
            }
        report['chains'][chain] = {
            'atom_count': len(atoms),
            'ca_count': len(ca),
            'adjacent_ca_distance_min': min(dists) if dists else None,
            'adjacent_ca_distance_median': sorted(dists)[len(dists)//2] if dists else None,
            'adjacent_ca_distance_max': max(dists) if dists else None,
            'adjacent_ca_distance_gt_6A': sum(1 for d in dists if d > 6.0),
            'bbox': bbox,
            'likely_sane_backbone': bool(dists) and sum(1 for d in dists if 2.5 <= d <= 4.5) >= 0.8 * len(dists),
        }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out_json:
        Path(args.out_json).write_text(text + '\n')
    print(text)

if __name__ == '__main__':
    main()
