#!/usr/bin/env python3
"""Build a reusable PVRIG hotspot constraint set for Phase I-b scaffold gating."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURES = ROOT / 'data' / 'structures'
OUT = STRUCTURES / 'PVRIG_hotspot_set_v1.csv'


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    consensus = read_csv(STRUCTURES / 'PVRIG_consensus_interface_residues.csv')
    numbering = read_csv(STRUCTURES / 'PVRIG_numbering_reconciliation.csv')
    hint_mapping = read_csv(STRUCTURES / 'PVRIG_soft_hint_structure_mapping.csv')

    by_col: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in numbering:
        if row['alignment_col']:
            by_col[row['alignment_col']].append(row)

    rows: list[dict[str, str]] = []
    for row in consensus:
        col = row['alignment_col']
        mapped = by_col.get(col, [])
        # Both structures represent the same UniProt position for ordinary aligned columns.
        uniprot_positions = sorted({r['uniprot_position'] for r in mapped if r['uniprot_position']}, key=int)
        uniprot_aas = ''.join(sorted({r['pdb_aa'] for r in mapped if r['pdb_aa']}))
        by_pdb = {r['pdb_id']: r for r in mapped}
        support = int(row['support_count'])
        cls = 'core_hotspot' if support >= 2 else 'secondary_hotspot'
        weight = '1.00' if cls == 'core_hotspot' else '0.70'
        rows.append({
            'hotspot_id': f'{cls}_{col}',
            'hotspot_class': cls,
            'priority_weight': weight,
            'alignment_col': col,
            'uniprot_accession': 'Q6DKI7',
            'uniprot_position': ';'.join(uniprot_positions),
            'uniprot_aa': uniprot_aas,
            'supporting_structures': row['supporting_structures'],
            'support_count': row['support_count'],
            'best_min_heavy_atom_distance_a': row['best_min_heavy_atom_distance_a'],
            'pdb_8x6b_ref': _pdb_ref(by_pdb.get('8X6B')),
            'pdb_9e6y_ref': _pdb_ref(by_pdb.get('9E6Y')),
            'evidence_source': '8X6B_9E6Y_distance_interface_4p5A',
            'design_use': 'blocking_interface_seed_not_antibody_contact_requirement',
            'notes': row['annotation'],
        })

    # Keep patent-derived hints separate from distance-interface hotspots.
    hint_priority = {'R95': ('soft_hint_high', '0.50'), 'I97': ('soft_hint_low', '0.20'), 'S67': ('soft_hint_excluded_from_phase_i_scoring', '0.00')}
    for hint in ['R95', 'I97', 'S67']:
        mapped = [r for r in hint_mapping if r['hint'] == hint]
        by_pdb = {r['pdb_id']: r for r in mapped}
        hint_class, weight = hint_priority[hint]
        rows.append({
            'hotspot_id': f'soft_hint_{hint}',
            'hotspot_class': hint_class,
            'priority_weight': weight,
            'alignment_col': ';'.join(sorted({r['alignment_col'] for r in mapped if r['alignment_col']})),
            'uniprot_accession': 'Q6DKI7',
            'uniprot_position': ';'.join(sorted({r['uniprot_position'] for r in mapped}, key=int)),
            'uniprot_aa': ''.join(sorted({r['pdb_aa'] for r in mapped if r['pdb_aa']})),
            'supporting_structures': ';'.join(sorted({r['pdb_id'] for r in mapped})),
            'support_count': str(len(mapped)),
            'best_min_heavy_atom_distance_a': '',
            'pdb_8x6b_ref': _hint_ref(by_pdb.get('8X6B')),
            'pdb_9e6y_ref': _hint_ref(by_pdb.get('9E6Y')),
            'evidence_source': 'patent_epitope_mapping_hint_mapped_to_Q6DKI7',
            'design_use': 'soft_hint_only_not_hard_constraint',
            'notes': ';'.join(sorted({r['interface_status'] for r in mapped})),
        })

    fields = [
        'hotspot_id', 'hotspot_class', 'priority_weight', 'alignment_col', 'uniprot_accession',
        'uniprot_position', 'uniprot_aa', 'supporting_structures', 'support_count',
        'best_min_heavy_atom_distance_a', 'pdb_8x6b_ref', 'pdb_9e6y_ref', 'evidence_source',
        'design_use', 'notes',
    ]
    with OUT.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f'wrote {OUT}')
    print(f'rows={len(rows)} core={sum(r["hotspot_class"] == "core_hotspot" for r in rows)} secondary={sum(r["hotspot_class"] == "secondary_hotspot" for r in rows)} soft={sum(r["hotspot_class"].startswith("soft_hint") for r in rows)}')


def _pdb_ref(row: dict[str, str] | None) -> str:
    if not row:
        return ''
    return f"{row['pvrig_chain']}:{row['pdb_resseq']}{row['pdb_icode']}{row['pdb_aa']}"


def _hint_ref(row: dict[str, str] | None) -> str:
    if not row:
        return ''
    return f"{row['pvrig_chain']}:{row['pdb_resseq']}{row['pdb_icode']}{row['pdb_aa']}:{row['interface_status']}"


if __name__ == '__main__':
    main()
