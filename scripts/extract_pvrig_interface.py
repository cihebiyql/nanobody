#!/usr/bin/env python3
"""Extract PVRIG-ligand interface residues from local PDB files.

The two reference structures use different PVRIG residue numbering schemes. This
script therefore writes per-structure residue contacts and builds the consensus
on sequence-alignment columns, not raw PDB residue numbers.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

AA3_TO_1 = {
    'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C',
    'GLN': 'Q', 'GLU': 'E', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
    'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F', 'PRO': 'P',
    'SER': 'S', 'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V',
    'SEC': 'U', 'PYL': 'O',
}
CHARGED = {'ARG', 'LYS', 'ASP', 'GLU', 'HIS'}


def parse_atoms(path: Path, chain_id: str):
    atoms = []
    residues = {}
    with path.open() as handle:
        for line in handle:
            if not line.startswith('ATOM'):
                continue
            if len(line) < 54 or line[21].strip() != chain_id:
                continue
            altloc = line[16].strip()
            if altloc not in ('', 'A'):
                continue
            atom_name = line[12:16].strip()
            element = line[76:78].strip() or atom_name[0]
            if element.upper() == 'H':
                continue
            resname = line[17:20].strip()
            resseq = int(line[22:26])
            icode = line[26].strip()
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            key = (chain_id, resseq, icode, resname)
            residues[key] = resname
            atoms.append((key, atom_name, x, y, z))
    if not atoms:
        raise SystemExit(f'No ATOM records found for chain {chain_id} in {path}')
    return atoms, residues


def chain_sequence(path: Path, chain_id: str):
    seq = []
    keys = []
    seen = set()
    with path.open() as handle:
        for line in handle:
            if not line.startswith('ATOM'):
                continue
            if len(line) < 54 or line[21].strip() != chain_id:
                continue
            if line[12:16].strip() != 'CA':
                continue
            resname = line[17:20].strip()
            resseq = int(line[22:26])
            icode = line[26].strip()
            key = (chain_id, resseq, icode, resname)
            if key in seen:
                continue
            seen.add(key)
            seq.append(AA3_TO_1.get(resname, 'X'))
            keys.append(key)
    if not seq:
        raise SystemExit(f'No CA sequence found for chain {chain_id} in {path}')
    return ''.join(seq), keys


def needleman_wunsch(seq_a: str, seq_b: str):
    match, mismatch, gap = 2, -1, -2
    n, m = len(seq_a), len(seq_b)
    score = [[0] * (m + 1) for _ in range(n + 1)]
    trace = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + gap
        trace[i][0] = 'U'
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + gap
        trace[0][j] = 'L'
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = score[i - 1][j - 1] + (match if seq_a[i - 1] == seq_b[j - 1] else mismatch)
            up = score[i - 1][j] + gap
            left = score[i][j - 1] + gap
            best = max(diag, up, left)
            score[i][j] = best
            trace[i][j] = 'D' if best == diag else ('U' if best == up else 'L')
    i, j = n, m
    pairs = []
    while i > 0 or j > 0:
        t = trace[i][j]
        if t == 'D':
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif t == 'U':
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return list(reversed(pairs))


def sqdist(a, b):
    return (a[2] - b[2]) ** 2 + (a[3] - b[3]) ** 2 + (a[4] - b[4]) ** 2


def extract_contacts(pdb_path: Path, receptor_chain: str, ligand_chain: str, cutoff: float):
    receptor_atoms, _ = parse_atoms(pdb_path, receptor_chain)
    ligand_atoms, _ = parse_atoms(pdb_path, ligand_chain)
    cutoff2 = cutoff * cutoff
    receptor_best = {}
    pair_best = {}
    for ra in receptor_atoms:
        rkey = ra[0]
        for la in ligand_atoms:
            d2 = sqdist(ra, la)
            if d2 <= cutoff2:
                lkey = la[0]
                d = math.sqrt(d2)
                prev = receptor_best.get(rkey)
                if prev is None or d < prev[0]:
                    receptor_best[rkey] = (d, lkey, ra[1], la[1])
                pkey = (rkey, lkey)
                prev = pair_best.get(pkey)
                if prev is None or d < prev[0]:
                    pair_best[pkey] = (d, ra[1], la[1])
    return receptor_best, pair_best


def build_alignment_maps(specs):
    # Use the first structure as the reference numbering surface.
    ref = specs[0]
    ref_seq, ref_keys = chain_sequence(ref['path'], ref['pvrig_chain'])
    maps = {ref['pdb_id']: {key: idx + 1 for idx, key in enumerate(ref_keys)}}
    ref_key_by_col = {idx + 1: key for idx, key in enumerate(ref_keys)}
    raw_by_pdb_col = {ref['pdb_id']: ref_key_by_col.copy()}

    for spec in specs[1:]:
        seq, keys = chain_sequence(spec['path'], spec['pvrig_chain'])
        pairs = needleman_wunsch(ref_seq, seq)
        key_to_col = {}
        col_to_key = {}
        next_insert_col = len(ref_seq) + 1
        for ref_i, query_i in pairs:
            if query_i is None:
                continue
            key = keys[query_i]
            if ref_i is not None:
                col = ref_i + 1
            else:
                # Rare insertion versus reference; keep it distinct and after ref columns.
                col = next_insert_col
                next_insert_col += 1
            key_to_col[key] = col
            col_to_key[col] = key
        maps[spec['pdb_id']] = key_to_col
        raw_by_pdb_col[spec['pdb_id']] = col_to_key
    return maps, raw_by_pdb_col


def write_csv(rows, output: Path, fieldnames):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cutoff', type=float, default=4.5)
    parser.add_argument('--output-dir', default='data/structures')
    parser.add_argument('spec', nargs='+', help='Format PDBID:path:pvrig_chain:ligand_chain')
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    specs = []
    for spec in args.spec:
        pdb_id, path_s, pvrig_chain, ligand_chain = spec.split(':', 3)
        specs.append({'pdb_id': pdb_id, 'path': Path(path_s), 'pvrig_chain': pvrig_chain, 'ligand_chain': ligand_chain})

    alignment_maps, raw_by_pdb_col = build_alignment_maps(specs)
    contacts_by_col = {}
    summary_rows = []

    interface_fields = [
        'pdb_id', 'pvrig_chain', 'ligand_chain', 'alignment_col', 'pvrig_resseq', 'pvrig_icode',
        'pvrig_resname', 'pvrig_aa', 'nearest_ligand_resseq', 'nearest_ligand_icode',
        'nearest_ligand_resname', 'min_heavy_atom_distance_a', 'pvrig_atom', 'ligand_atom', 'annotation'
    ]
    pair_fields = [
        'pdb_id', 'pvrig_chain', 'ligand_chain', 'alignment_col', 'pvrig_resseq', 'pvrig_icode',
        'pvrig_resname', 'ligand_resseq', 'ligand_icode', 'ligand_resname',
        'min_heavy_atom_distance_a', 'pvrig_atom', 'ligand_atom'
    ]

    for spec in specs:
        pdb_id = spec['pdb_id']
        receptor_best, pair_best = extract_contacts(spec['path'], spec['pvrig_chain'], spec['ligand_chain'], args.cutoff)
        rows = []
        for rkey, (dist, lkey, ratom, latom) in sorted(receptor_best.items(), key=lambda item: (alignment_maps[pdb_id].get(item[0], 10_000), item[0][1])):
            _, resseq, icode, resname = rkey
            _, lresseq, licode, lresname = lkey
            col = alignment_maps[pdb_id].get(rkey)
            ann = []
            if resname in CHARGED:
                ann.append('charged_residue')
            row = {
                'pdb_id': pdb_id,
                'pvrig_chain': spec['pvrig_chain'],
                'ligand_chain': spec['ligand_chain'],
                'alignment_col': col,
                'pvrig_resseq': resseq,
                'pvrig_icode': icode,
                'pvrig_resname': resname,
                'pvrig_aa': AA3_TO_1.get(resname, 'X'),
                'nearest_ligand_resseq': lresseq,
                'nearest_ligand_icode': licode,
                'nearest_ligand_resname': lresname,
                'min_heavy_atom_distance_a': f'{dist:.3f}',
                'pvrig_atom': ratom,
                'ligand_atom': latom,
                'annotation': ';'.join(ann),
            }
            rows.append(row)
            contacts_by_col.setdefault(col, []).append(row)
        write_csv(rows, outdir / f'PVRIG_interface_residues_{pdb_id}.csv', interface_fields)

        pair_rows = []
        for (rkey, lkey), (dist, ratom, latom) in sorted(pair_best.items(), key=lambda item: (alignment_maps[pdb_id].get(item[0][0], 10_000), item[0][1][1])):
            _, resseq, icode, resname = rkey
            _, lresseq, licode, lresname = lkey
            pair_rows.append({
                'pdb_id': pdb_id,
                'pvrig_chain': spec['pvrig_chain'],
                'ligand_chain': spec['ligand_chain'],
                'alignment_col': alignment_maps[pdb_id].get(rkey),
                'pvrig_resseq': resseq,
                'pvrig_icode': icode,
                'pvrig_resname': resname,
                'ligand_resseq': lresseq,
                'ligand_icode': licode,
                'ligand_resname': lresname,
                'min_heavy_atom_distance_a': f'{dist:.3f}',
                'pvrig_atom': ratom,
                'ligand_atom': latom,
            })
        write_csv(pair_rows, outdir / f'PVRIG_ligand_contact_pairs_{pdb_id}.csv', pair_fields)
        summary_rows.append((pdb_id, len(rows), len(pair_rows)))

    consensus = []
    for col in sorted(contacts_by_col):
        rows = contacts_by_col[col]
        pdb_ids = sorted({r['pdb_id'] for r in rows})
        best = min(float(r['min_heavy_atom_distance_a']) for r in rows)
        ref_parts = []
        aa_set = []
        charged = False
        for spec in specs:
            key = raw_by_pdb_col.get(spec['pdb_id'], {}).get(col)
            if key:
                _, resseq, icode, resname = key
                aa = AA3_TO_1.get(resname, 'X')
                aa_set.append(aa)
                ref_parts.append(f"{spec['pdb_id']}:{resseq}{icode or ''}{aa}")
                if resname in CHARGED:
                    charged = True
            else:
                ref_parts.append(f"{spec['pdb_id']}:gap")
        priority_class = 'highest' if len(pdb_ids) >= 2 else 'high'
        flags = ['consensus_interface' if len(pdb_ids) >= 2 else 'single_structure_interface']
        if charged:
            flags.append('charged_residue')
        consensus.append({
            'alignment_col': col,
            'aligned_residue_refs': ';'.join(ref_parts),
            'aligned_aas': ''.join(sorted(set(aa_set))),
            'supporting_structures': ';'.join(pdb_ids),
            'support_count': len(pdb_ids),
            'best_min_heavy_atom_distance_a': f'{best:.3f}',
            'priority_class': priority_class,
            'annotation': ';'.join(flags),
        })

    consensus_fields = ['alignment_col', 'aligned_residue_refs', 'aligned_aas', 'supporting_structures', 'support_count', 'best_min_heavy_atom_distance_a', 'priority_class', 'annotation']
    write_csv(consensus, outdir / 'PVRIG_consensus_interface_residues.csv', consensus_fields)

    consensus_cols = {r['alignment_col'] for r in consensus if r['support_count'] >= 2}
    all_cols = {r['alignment_col'] for r in consensus}
    pml_lines = [
        '# Generated by scripts/extract_pvrig_interface.py',
        '# Executable PyMOL helper. It uses raw PDB residue numbers per structure; consensus is derived from alignment columns.',
    ]
    for spec in specs:
        pdb_id = spec['pdb_id']
        obj = f'pdb{pdb_id.lower()}'
        pml_lines.append(f'load data/structures/{pdb_id}.pdb, {obj}')
        pml_lines.append(f'hide everything, {obj}')
        pml_lines.append(f'show cartoon, {obj} and chain {spec["pvrig_chain"]}')
        pml_lines.append(f'show surface, {obj} and chain {spec["pvrig_chain"]}')
        pml_lines.append(f'color gray80, {obj} and chain {spec["pvrig_chain"]}')
        for label, cols, color in [
            ('all', all_cols, 'yellow'),
            ('consensus', consensus_cols, 'orange'),
            ('single_structure', all_cols - consensus_cols, 'tv_yellow'),
        ]:
            resis = []
            for col in sorted(cols):
                key = raw_by_pdb_col.get(pdb_id, {}).get(col)
                if not key:
                    continue
                _, resseq, icode, _ = key
                resis.append(f'{resseq}{icode or ""}')
            if resis:
                sel = '+'.join(resis)
                pml_lines.append(f'select pvrig_{pdb_id}_{label}, {obj} and chain {spec["pvrig_chain"]} and resi {sel}')
                pml_lines.append(f'color {color}, pvrig_{pdb_id}_{label}')
                pml_lines.append(f'show sticks, pvrig_{pdb_id}_{label}')
        pml_lines.append('')
    pml_lines.extend([
        'set transparency, 0.35',
        'zoom pvrig_8X6B_consensus or pvrig_9E6Y_consensus',
        '# Soft hints S67/R95/I97 are intentionally not selected here; see PVRIG_soft_hint_structure_mapping.csv after numbering reconciliation.',
    ])
    (outdir / 'PVRIG_epitope_priority_map.pml').write_text('\n'.join(pml_lines) + '\n')
    write_csv([
        {'hint': 'S67', 'status': 'soft_epitope_hint_not_hard_selected', 'note': 'Map separately with scripts/reconcile_pvrig_numbering.py; never use as a Phase I hard constraint.'},
        {'hint': 'R95', 'status': 'soft_epitope_hint_not_hard_selected', 'note': 'Map separately with scripts/reconcile_pvrig_numbering.py; never use as a Phase I hard constraint.'},
        {'hint': 'I97', 'status': 'soft_epitope_hint_not_hard_selected', 'note': 'Map separately with scripts/reconcile_pvrig_numbering.py; never use as a Phase I hard constraint.'},
    ], outdir / 'PVRIG_soft_epitope_hints.csv', ['hint', 'status', 'note'])

    print('Extraction complete')
    for pdb_id, nres, npairs in summary_rows:
        print(f'{pdb_id}: {nres} PVRIG interface residues, {npairs} residue-residue contact pairs')
    both = sum(1 for r in consensus if r['support_count'] >= 2)
    print(f'Alignment-consensus interface columns: {len(consensus)} total, {both} supported by both structures')


if __name__ == '__main__':
    main()
