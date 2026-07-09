#!/usr/bin/env python3
"""Build PVRIG numbering reconciliation artifacts for Phase I-b.

Maps local PDB residue numbers to UniProt/PVRIG canonical numbering using PDB
DBREF offsets, then annotates current interface membership and soft patent hints.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURES = ROOT / 'data' / 'structures'
AA3_TO_1 = {
    'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C',
    'GLN': 'Q', 'GLU': 'E', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
    'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F', 'PRO': 'P',
    'SER': 'S', 'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V',
}
SPECS = {
    '8X6B': {'chain': 'B', 'dbref_start': 1, 'dbref_uniprot_start': 39, 'dbref_end': 116, 'dbref_uniprot_end': 154},
    '9E6Y': {'chain': 'A', 'dbref_start': 1, 'dbref_uniprot_start': 41, 'dbref_end': 132, 'dbref_uniprot_end': 172},
}
SOFT_HINTS = {67: 'S67', 95: 'R95', 97: 'I97'}
EXPECTED_HINT_AA = {67: 'S', 95: 'R', 97: 'I'}


def load_interface_by_pdb_residue() -> dict[tuple[str, int, str], dict[str, str]]:
    out = {}
    for pdb_id in SPECS:
        path = STRUCTURES / f'PVRIG_interface_residues_{pdb_id}.csv'
        with path.open(newline='') as handle:
            for row in csv.DictReader(handle):
                out[(pdb_id, int(row['pvrig_resseq']), row['pvrig_icode'])] = row
    return out


def load_consensus_by_ref() -> dict[tuple[str, int, str], dict[str, str]]:
    out = {}
    with (STRUCTURES / 'PVRIG_consensus_interface_residues.csv').open(newline='') as handle:
        for row in csv.DictReader(handle):
            refs = row['aligned_residue_refs'].split(';')
            for ref in refs:
                if ref.endswith(':gap'):
                    continue
                pdb_id, label = ref.split(':', 1)
                # label format: residue number + optional insertion code + one-letter aa.
                aa = label[-1]
                residue_label = label[:-1]
                if residue_label[-1:].isalpha():
                    resseq = int(residue_label[:-1])
                    icode = residue_label[-1]
                else:
                    resseq = int(residue_label)
                    icode = ''
                out[(pdb_id, resseq, icode)] = row
    return out


def iter_ca_residues(pdb_id: str):
    spec = SPECS[pdb_id]
    chain = spec['chain']
    path = STRUCTURES / f'{pdb_id}.pdb'
    seen = set()
    with path.open() as handle:
        for line in handle:
            if not line.startswith('ATOM'):
                continue
            if line[21].strip() != chain or line[12:16].strip() != 'CA':
                continue
            resname = line[17:20].strip()
            resseq = int(line[22:26])
            icode = line[26].strip()
            key = (resseq, icode)
            if key in seen:
                continue
            seen.add(key)
            yield resseq, icode, resname, AA3_TO_1.get(resname, 'X')


def uniprot_position(pdb_id: str, resseq: int) -> int | None:
    spec = SPECS[pdb_id]
    if not (spec['dbref_start'] <= resseq <= spec['dbref_end']):
        return None
    return resseq - spec['dbref_start'] + spec['dbref_uniprot_start']


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output-dir',
        default=str(STRUCTURES),
        help='Directory for reconciliation outputs. Inputs are read from data/structures.',
    )
    args = parser.parse_args()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    interface = load_interface_by_pdb_residue()
    consensus = load_consensus_by_ref()
    rows = []
    by_uniprot: dict[int, list[dict[str, str]]] = {}
    for pdb_id in SPECS:
        for resseq, icode, resname, aa in iter_ca_residues(pdb_id):
            uni = uniprot_position(pdb_id, resseq)
            iface = interface.get((pdb_id, resseq, icode))
            cons = consensus.get((pdb_id, resseq, icode))
            note = ''
            if pdb_id == '8X6B' and resseq == 89:
                note = 'SEQADV: engineered Cys127-to-Ser mutation in 8X6B construct'
            row = {
                'pdb_id': pdb_id,
                'pvrig_chain': SPECS[pdb_id]['chain'],
                'pdb_resseq': resseq,
                'pdb_icode': icode,
                'pdb_resname': resname,
                'pdb_aa': aa,
                'uniprot_accession': 'Q6DKI7',
                'uniprot_position': uni if uni is not None else '',
                'uniprot_label_assumption': 'PDB_DBREF_mapping',
                'alignment_col': cons['alignment_col'] if cons else '',
                'is_4p5a_interface': 'yes' if iface else 'no',
                'interface_support_count': cons['support_count'] if cons else '',
                'interface_priority_class': cons['priority_class'] if cons else '',
                'soft_hint_label': SOFT_HINTS.get(uni, '') if uni is not None else '',
                'note': note,
            }
            rows.append(row)
            if uni is not None:
                by_uniprot.setdefault(uni, []).append(row)
    fields = list(rows[0].keys())
    with (outdir / 'PVRIG_numbering_reconciliation.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    hint_rows = []
    for uni, hint in SOFT_HINTS.items():
        mapped = by_uniprot.get(uni, [])
        for row in mapped:
            expected = EXPECTED_HINT_AA[uni]
            status = 'mapped_residue_matches_hint_aa' if row['pdb_aa'] == expected else 'mapped_residue_aa_mismatch'
            if row['is_4p5a_interface'] == 'yes' and row['interface_support_count'] == '2':
                interface_status = 'consensus_4p5a_interface'
            elif row['is_4p5a_interface'] == 'yes':
                interface_status = 'single_structure_4p5a_interface'
            else:
                interface_status = 'not_4p5a_interface_in_this_structure'
            hint_rows.append({
                'hint': hint,
                'assumed_hint_numbering': 'UniProt_Q6DKI7_position',
                'uniprot_position': uni,
                'expected_hint_aa': expected,
                'pdb_id': row['pdb_id'],
                'pvrig_chain': row['pvrig_chain'],
                'pdb_resseq': row['pdb_resseq'],
                'pdb_icode': row['pdb_icode'],
                'pdb_aa': row['pdb_aa'],
                'mapping_status': status,
                'interface_status': interface_status,
                'alignment_col': row['alignment_col'],
                'interpretation': 'soft_hint_only_not_hard_constraint',
            })
    fields = ['hint', 'assumed_hint_numbering', 'uniprot_position', 'expected_hint_aa', 'pdb_id', 'pvrig_chain', 'pdb_resseq', 'pdb_icode', 'pdb_aa', 'mapping_status', 'interface_status', 'alignment_col', 'interpretation']
    with (outdir / 'PVRIG_soft_hint_structure_mapping.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(hint_rows)
    print(f'wrote {outdir / "PVRIG_numbering_reconciliation.csv"}')
    print(f'wrote {outdir / "PVRIG_soft_hint_structure_mapping.csv"}')


if __name__ == '__main__':
    main()
