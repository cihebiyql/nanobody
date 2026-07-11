#!/usr/bin/env python3
"""Quantify which VHH regions sterically occlude reference PVRL2 in an aligned pose.

The pose must already be aligned to a PVRIG:PVRL2 reference frame and contain
VHH + PVRIG chains. The reference PVRL2 chain provides the ligand position.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pose-pdb', required=True)
    p.add_argument('--reference-pdb', required=True)
    p.add_argument('--vhh-chain', required=True)
    p.add_argument('--ref-pvrl2-chain', required=True)
    p.add_argument('--cdr1', default='26-35')
    p.add_argument('--cdr2', default='53-59')
    p.add_argument('--cdr3', default='98-116')
    p.add_argument('--contact-cutoff', type=float, default=4.5)
    p.add_argument('--clash-cutoff', type=float, default=2.5)
    p.add_argument('--out-json')
    p.add_argument('--out-csv')
    return p.parse_args()


def parse_range(spec: str) -> set[int]:
    vals: set[int] = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            vals.update(range(int(a), int(b) + 1))
        else:
            vals.add(int(part))
    return vals


def parse_resseq(s: str) -> int | None:
    try:
        return int(s.strip())
    except ValueError:
        return None


def atom_element(line: str) -> str:
    elem = line[76:78].strip() if len(line) >= 78 else ''
    if elem:
        return elem.upper()
    return ''.join(ch for ch in line[12:16].strip() if ch.isalpha())[:1].upper()


def iter_atoms(path: Path, chain: str | None = None):
    for line in path.read_text(errors='replace').splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')) or len(line) < 54:
            continue
        if chain is not None and line[21] != chain:
            continue
        elem = atom_element(line)
        if elem == 'H':
            continue
        try:
            x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
        except ValueError:
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                x, y, z = float(parts[6]), float(parts[7]), float(parts[8])
            except ValueError:
                continue
        resseq = parse_resseq(line[22:26])
        yield {
            'chain': line[21],
            'atom': line[12:16].strip(),
            'resname': line[17:20].strip(),
            'resseq': resseq,
            'icode': line[26].strip(),
            'xyz': (x, y, z),
            'resid': f"{line[21]}:{line[22:26].strip()}{line[26].strip()}{line[17:20].strip()}",
        }


def dist2(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3))


def region_name(resseq: int | None, cdr1: set[int], cdr2: set[int], cdr3: set[int]) -> str:
    if resseq in cdr3:
        return 'CDR3'
    if resseq in cdr1:
        return 'CDR1'
    if resseq in cdr2:
        return 'CDR2'
    return 'framework'


def summarize_contacts(vhh_atoms, pvrl2_atoms, cutoff: float, clash_cutoff: float, cdr1, cdr2, cdr3):
    cutoff2 = cutoff * cutoff
    clash2 = clash_cutoff * clash_cutoff
    regions = ['CDR3', 'CDR1', 'CDR2', 'framework']
    stats = {
        r: {
            'occluding_atom_contact_count': 0,
            'occluding_residue_pair_count': 0,
            'clash_atom_contact_count': 0,
            'clash_residue_pair_count': 0,
            'vhh_residues': set(),
            'pvrl2_residues': set(),
            'occluding_residue_pairs': set(),
            'clash_residue_pairs': set(),
            'min_distance_a': None,
        }
        for r in regions
    }
    all_occ_pairs = 0
    all_clash_pairs = 0
    all_occ_residue_pairs = set()
    all_clash_residue_pairs = set()
    for va in vhh_atoms:
        r = region_name(va['resseq'], cdr1, cdr2, cdr3)
        for pa in pvrl2_atoms:
            d2 = dist2(va['xyz'], pa['xyz'])
            if d2 <= cutoff2:
                d = math.sqrt(d2)
                all_occ_pairs += 1
                stats[r]['occluding_atom_contact_count'] += 1
                stats[r]['vhh_residues'].add(va['resid'])
                stats[r]['pvrl2_residues'].add(pa['resid'])
                residue_pair = (va['resid'], pa['resid'])
                stats[r]['occluding_residue_pairs'].add(residue_pair)
                all_occ_residue_pairs.add(residue_pair)
                cur = stats[r]['min_distance_a']
                if cur is None or d < cur:
                    stats[r]['min_distance_a'] = d
                if d2 <= clash2:
                    all_clash_pairs += 1
                    stats[r]['clash_atom_contact_count'] += 1
                    stats[r]['clash_residue_pairs'].add(residue_pair)
                    all_clash_residue_pairs.add(residue_pair)
    for r in regions:
        stats[r]['occluding_residue_pair_count'] = len(stats[r]['occluding_residue_pairs'])
        stats[r]['clash_residue_pair_count'] = len(stats[r]['clash_residue_pairs'])
        stats[r]['vhh_residue_count'] = len(stats[r]['vhh_residues'])
        stats[r]['pvrl2_residue_count'] = len(stats[r]['pvrl2_residues'])
        stats[r]['occluding_residue_pairs'] = [f'{a}--{b}' for a, b in sorted(stats[r]['occluding_residue_pairs'])]
        stats[r]['clash_residue_pairs'] = [f'{a}--{b}' for a, b in sorted(stats[r]['clash_residue_pairs'])]
        stats[r]['vhh_residues'] = sorted(stats[r]['vhh_residues'])
        stats[r]['pvrl2_residues'] = sorted(stats[r]['pvrl2_residues'])
        stats[r]['occlusion_fraction_of_total'] = (
            stats[r]['occluding_atom_contact_count'] / all_occ_pairs if all_occ_pairs else 0.0
        )
        stats[r]['occluding_residue_pair_fraction_of_total'] = (
            stats[r]['occluding_residue_pair_count'] / len(all_occ_residue_pairs) if all_occ_residue_pairs else 0.0
        )
        stats[r]['clash_fraction_of_total'] = (
            stats[r]['clash_atom_contact_count'] / all_clash_pairs if all_clash_pairs else 0.0
        )
        stats[r]['clash_residue_pair_fraction_of_total'] = (
            stats[r]['clash_residue_pair_count'] / len(all_clash_residue_pairs) if all_clash_residue_pairs else 0.0
        )
    return stats, all_occ_pairs, all_clash_pairs, len(all_occ_residue_pairs), len(all_clash_residue_pairs)


def main():
    args = parse_args()
    cdr1, cdr2, cdr3 = parse_range(args.cdr1), parse_range(args.cdr2), parse_range(args.cdr3)
    pose = Path(args.pose_pdb)
    ref = Path(args.reference_pdb)
    vhh_atoms = list(iter_atoms(pose, args.vhh_chain))
    pvrl2_atoms = list(iter_atoms(ref, args.ref_pvrl2_chain))
    if not vhh_atoms:
        raise SystemExit(f'No VHH atoms found for chain {args.vhh_chain} in {pose}')
    if not pvrl2_atoms:
        raise SystemExit(f'No reference PVRL2 atoms found for chain {args.ref_pvrl2_chain} in {ref}')
    stats, total_occ, total_clash, total_occ_residue_pairs, total_clash_residue_pairs = summarize_contacts(
        vhh_atoms, pvrl2_atoms, args.contact_cutoff, args.clash_cutoff, cdr1, cdr2, cdr3
    )
    report = {
        'pose_pdb': str(pose),
        'reference_pdb': str(ref),
        'vhh_chain': args.vhh_chain,
        'ref_pvrl2_chain': args.ref_pvrl2_chain,
        'contact_cutoff_a': args.contact_cutoff,
        'clash_cutoff_a': args.clash_cutoff,
        'cdr_ranges': {'CDR1': args.cdr1, 'CDR2': args.cdr2, 'CDR3': args.cdr3},
        'total_occluding_atom_contact_count': total_occ,
        'total_clash_atom_contact_count': total_clash,
        'total_occluding_residue_pair_count': total_occ_residue_pairs,
        'total_clash_residue_pair_count': total_clash_residue_pairs,
        'regions': stats,
    }
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    if args.out_csv:
        fields = [
            'pose_pdb','region','occluding_atom_contact_count','occlusion_fraction_of_total',
            'occluding_residue_pair_count','occluding_residue_pair_fraction_of_total',
            'clash_atom_contact_count','clash_fraction_of_total',
            'clash_residue_pair_count','clash_residue_pair_fraction_of_total',
            'vhh_residue_count','pvrl2_residue_count',
            'min_distance_a','vhh_residues','pvrl2_residues'
        ]
        with Path(args.out_csv).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for region, s in stats.items():
                w.writerow({
                    'pose_pdb': str(pose),
                    'region': region,
                    'occluding_atom_contact_count': s['occluding_atom_contact_count'],
                    'occlusion_fraction_of_total': s['occlusion_fraction_of_total'],
                    'occluding_residue_pair_count': s['occluding_residue_pair_count'],
                    'occluding_residue_pair_fraction_of_total': s['occluding_residue_pair_fraction_of_total'],
                    'clash_atom_contact_count': s['clash_atom_contact_count'],
                    'clash_fraction_of_total': s['clash_fraction_of_total'],
                    'clash_residue_pair_count': s['clash_residue_pair_count'],
                    'clash_residue_pair_fraction_of_total': s['clash_residue_pair_fraction_of_total'],
                    'vhh_residue_count': s['vhh_residue_count'],
                    'pvrl2_residue_count': s['pvrl2_residue_count'],
                    'min_distance_a': s['min_distance_a'],
                    'vhh_residues': ';'.join(s['vhh_residues']),
                    'pvrl2_residues': ';'.join(s['pvrl2_residues']),
                })
    print(json.dumps({
        'pose_pdb': str(pose),
        'total_occluding_atom_contact_count': total_occ,
        'total_clash_atom_contact_count': total_clash,
        'total_occluding_residue_pair_count': total_occ_residue_pairs,
        'total_clash_residue_pair_count': total_clash_residue_pairs,
        'region_summary': {
            r: {
                'occluding_atom_contact_count': s['occluding_atom_contact_count'],
                'occlusion_fraction_of_total': round(s['occlusion_fraction_of_total'], 4),
                'occluding_residue_pair_count': s['occluding_residue_pair_count'],
                'occluding_residue_pair_fraction_of_total': round(s['occluding_residue_pair_fraction_of_total'], 4),
                'clash_atom_contact_count': s['clash_atom_contact_count'],
                'clash_residue_pair_count': s['clash_residue_pair_count'],
                'vhh_residue_count': s['vhh_residue_count'],
                'pvrl2_residue_count': s['pvrl2_residue_count'],
            } for r, s in stats.items()
        }
    }, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
