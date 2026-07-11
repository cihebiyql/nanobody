#!/usr/bin/env python3
"""Align a pose PDB to a reference PDB by CA atoms from selected chains."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mobile-pdb', required=True, help='Pose/mobile PDB to transform.')
    p.add_argument('--reference-pdb', required=True, help='Reference PDB to align onto.')
    p.add_argument('--mobile-chain', required=True, help='Chain in mobile PDB used for alignment.')
    p.add_argument('--reference-chain', required=True, help='Chain in reference PDB used for alignment.')
    p.add_argument('--out-pdb', required=True, help='Aligned output PDB path.')
    p.add_argument('--atom-name', default='CA', help='Atom name used for fit, default CA.')
    p.add_argument('--pair-map-csv', help='Optional CSV with paired PDB residue refs for sequence-aware fitting.')
    p.add_argument('--mobile-ref-column', help='Column in --pair-map-csv for mobile residue refs, e.g. pdb_8x6b_ref.')
    p.add_argument('--reference-ref-column', help='Column in --pair-map-csv for reference residue refs, e.g. pdb_9e6y_ref.')
    return p.parse_args()


def iter_atoms(path: Path):
    for line in path.read_text(errors='replace').splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')) or len(line) < 54:
            continue
        try:
            yield {
                'line': line,
                'chain': line[21],
                'atom': line[12:16].strip(),
                'resseq': line[22:26].strip(),
                'icode': line[26].strip(),
                'resname': line[17:20].strip(),
                'xyz': np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])], dtype=float),
            }
        except ValueError:
            continue


def chain_fit_points(path: Path, chain: str, atom_name: str) -> np.ndarray:
    pts = [a['xyz'] for a in iter_atoms(path) if a['chain'] == chain and a['atom'] == atom_name]
    if not pts:
        raise SystemExit(f'No {atom_name} atoms found for chain {chain} in {path}')
    return np.vstack(pts)


def parse_pdb_residue_ref(value: str):
    """Parse refs such as B:33S into (chain, resseq, aa)."""
    value = (value or '').strip()
    match = re.fullmatch(r'([^:]):(-?\d+)([A-Za-z]{1,3})?', value)
    if not match:
        return None
    chain, resseq, aa = match.groups()
    return chain, resseq, (aa or '').upper()


def atom_lookup(path: Path, atom_name: str):
    lookup = {}
    for atom in iter_atoms(path):
        if atom['atom'] != atom_name:
            continue
        lookup[(atom['chain'], atom['resseq'])] = atom
    return lookup


def mapped_fit_points(
    mobile_pdb: Path,
    reference_pdb: Path,
    pair_map_csv: Path,
    mobile_column: str,
    reference_column: str,
    atom_name: str,
):
    mobile_atoms = atom_lookup(mobile_pdb, atom_name)
    reference_atoms = atom_lookup(reference_pdb, atom_name)
    mobile_pts = []
    reference_pts = []
    skipped = 0
    with pair_map_csv.open(encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            mobile_ref = parse_pdb_residue_ref(row.get(mobile_column, ''))
            reference_ref = parse_pdb_residue_ref(row.get(reference_column, ''))
            if not mobile_ref or not reference_ref:
                skipped += 1
                continue
            mobile_atom = mobile_atoms.get((mobile_ref[0], mobile_ref[1]))
            reference_atom = reference_atoms.get((reference_ref[0], reference_ref[1]))
            if mobile_atom is None or reference_atom is None:
                skipped += 1
                continue
            mobile_pts.append(mobile_atom['xyz'])
            reference_pts.append(reference_atom['xyz'])
    if len(mobile_pts) < 3:
        raise SystemExit(
            f'Need at least 3 mapped {atom_name} atom pairs, got {len(mobile_pts)} '
            f'from {pair_map_csv}'
        )
    return np.vstack(mobile_pts), np.vstack(reference_pts), skipped


def kabsch_transform(mobile: np.ndarray, reference: np.ndarray):
    n = min(len(mobile), len(reference))
    if n < 3:
        raise SystemExit(f'Need at least 3 paired atoms, got {n}')
    if len(mobile) != len(reference):
        print(f'WARNING: atom count differs mobile={len(mobile)} reference={len(reference)}; using first {n} atoms')
    p = mobile[:n]
    q = reference[:n]
    p_centroid = p.mean(axis=0)
    q_centroid = q.mean(axis=0)
    pc = p - p_centroid
    qc = q - q_centroid
    h = pc.T @ qc
    u, _s, vt = np.linalg.svd(h)
    r = u @ vt
    if np.linalg.det(r) < 0:
        vt[-1, :] *= -1
        r = u @ vt
    aligned = pc @ r + q_centroid
    rmsd = float(np.sqrt(np.mean(np.sum((aligned - q) ** 2, axis=1))))
    return r, p_centroid, q_centroid, rmsd, n


def transform_xyz(xyz: np.ndarray, r: np.ndarray, mobile_centroid: np.ndarray, ref_centroid: np.ndarray) -> np.ndarray:
    return (xyz - mobile_centroid) @ r + ref_centroid


def rewrite_pdb(mobile_pdb: Path, out_pdb: Path, r: np.ndarray, mobile_centroid: np.ndarray, ref_centroid: np.ndarray) -> None:
    out_lines = []
    for line in mobile_pdb.read_text(errors='replace').splitlines():
        if line.startswith(('ATOM  ', 'HETATM')) and len(line) >= 54:
            try:
                xyz = np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])], dtype=float)
                x, y, z = transform_xyz(xyz, r, mobile_centroid, ref_centroid)
                line = f'{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}'
            except ValueError:
                pass
        out_lines.append(line)
    out_pdb.parent.mkdir(parents=True, exist_ok=True)
    out_pdb.write_text('\n'.join(out_lines) + '\n')


def main() -> None:
    args = parse_args()
    mobile_pdb = Path(args.mobile_pdb)
    reference_pdb = Path(args.reference_pdb)
    if args.pair_map_csv:
        if not args.mobile_ref_column or not args.reference_ref_column:
            raise SystemExit('--pair-map-csv requires --mobile-ref-column and --reference-ref-column')
        mobile_pts, ref_pts, skipped = mapped_fit_points(
            mobile_pdb,
            reference_pdb,
            Path(args.pair_map_csv),
            args.mobile_ref_column,
            args.reference_ref_column,
            args.atom_name,
        )
        print(
            f'using mapped residue pairs from {args.pair_map_csv}: '
            f'pairs={len(mobile_pts)} skipped={skipped}'
        )
    else:
        mobile_pts = chain_fit_points(mobile_pdb, args.mobile_chain, args.atom_name)
        ref_pts = chain_fit_points(reference_pdb, args.reference_chain, args.atom_name)
    r, mc, rc, rmsd, n = kabsch_transform(mobile_pts, ref_pts)
    rewrite_pdb(mobile_pdb, Path(args.out_pdb), r, mc, rc)
    print(f'aligned {mobile_pdb} -> {args.out_pdb}')
    print(f'fit_atoms={n} atom={args.atom_name} mobile_chain={args.mobile_chain} reference_chain={args.reference_chain} rmsd={rmsd:.3f} A')


if __name__ == '__main__':
    main()
