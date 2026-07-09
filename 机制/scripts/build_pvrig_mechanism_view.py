#!/usr/bin/env python3
"""Build PyMOL visualizations and key contact tables for PVRIG-PVRL2 mechanism review."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCT = ROOT / 'data' / 'structures'
VIS = ROOT / 'visualization'
FIG = ROOT / 'reports' / 'figures'
REPORTS = ROOT / 'reports'


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def resi_from_ref(ref: str) -> str:
    # B:57R or B:57R:status -> 57
    if not ref:
        return ''
    label = ref.split(':')[1]
    # strip trailing amino acid and optional status
    return label[:-1] if label[-1].isalpha() else label


def chain_from_ref(ref: str) -> str:
    return ref.split(':')[0] if ref else ''


def main() -> None:
    VIS.mkdir(exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    hotspots = read_csv(STRUCT / 'PVRIG_hotspot_set_v1.csv')
    pair_rows = {
        '8X6B': read_csv(STRUCT / 'PVRIG_ligand_contact_pairs_8X6B.csv'),
        '9E6Y': read_csv(STRUCT / 'PVRIG_ligand_contact_pairs_9E6Y.csv'),
    }
    numbering = read_csv(STRUCT / 'PVRIG_numbering_reconciliation.csv')
    numbering_by = {(r['pdb_id'], r['pdb_resseq']): r for r in numbering}

    write_key_contact_table(hotspots, pair_rows, numbering_by)
    write_pml(hotspots, pair_rows)
    write_notes()
    write_html_viewer(hotspots)


def write_key_contact_table(hotspots, pair_rows, numbering_by) -> None:
    pair_by_pdb_res = defaultdict(list)
    for pdb_id, rows in pair_rows.items():
        for r in rows:
            pair_by_pdb_res[(pdb_id, r['pvrig_resseq'])].append(r)

    out_rows = []
    for h in hotspots:
        for pdb_id, ref_field in [('8X6B', 'pdb_8x6b_ref'), ('9E6Y', 'pdb_9e6y_ref')]:
            ref = h[ref_field]
            if not ref:
                continue
            resseq = resi_from_ref(ref)
            if not resseq:
                continue
            pairs = pair_by_pdb_res.get((pdb_id, resseq), [])
            nearest = sorted(pairs, key=lambda r: float(r['min_heavy_atom_distance_a']))[:5]
            number = numbering_by.get((pdb_id, resseq), {})
            out_rows.append({
                'hotspot_id': h['hotspot_id'],
                'hotspot_class': h['hotspot_class'],
                'priority_weight': h['priority_weight'],
                'pdb_id': pdb_id,
                'pvrig_chain': chain_from_ref(ref),
                'pvrig_pdb_residue': resseq,
                'pvrig_uniprot_position': h['uniprot_position'],
                'pvrig_aa': h['uniprot_aa'],
                'alignment_col': h['alignment_col'],
                'contact_pair_count_at_4p5a': len(pairs),
                'nearest_ligand_contacts': ';'.join(
                    f"{r['ligand_resname']}{r['ligand_resseq']}:{r['min_heavy_atom_distance_a']}A:{r['pvrig_atom']}-{r['ligand_atom']}"
                    for r in nearest
                ),
                'mechanism_readout': mechanism_readout(h),
                'design_use': h['design_use'],
                'notes': h['notes'],
            })
    fields = ['hotspot_id', 'hotspot_class', 'priority_weight', 'pdb_id', 'pvrig_chain', 'pvrig_pdb_residue', 'pvrig_uniprot_position', 'pvrig_aa', 'alignment_col', 'contact_pair_count_at_4p5a', 'nearest_ligand_contacts', 'mechanism_readout', 'design_use', 'notes']
    with (STRUCT / 'PVRIG_key_contact_residues_v1.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)


def mechanism_readout(h: dict[str, str]) -> str:
    if h['hotspot_class'] == 'core_hotspot':
        return 'two_structure_supported_blocking_interface_seed'
    if h['hotspot_class'] == 'secondary_hotspot':
        return 'single_structure_interface_edge_or_dynamic_contact'
    if h['hotspot_id'] == 'soft_hint_R95':
        return 'patent_hint_overlaps_consensus_interface_high_priority_soft_hint'
    if h['hotspot_id'] == 'soft_hint_I97':
        return 'patent_hint_with_partial_single_structure_interface_support'
    if h['hotspot_id'] == 'soft_hint_S67':
        return 'patent_hint_outside_current_distance_interface_not_for_phase_i_scoring'
    return ''


def write_pml(hotspots, pair_rows) -> None:
    core_8, core_9, sec_8, sec_9 = [], [], [], []
    labels = []
    for h in hotspots:
        if h['hotspot_class'] in {'core_hotspot', 'secondary_hotspot'}:
            for pdb_id, field, target in [('8X6B', 'pdb_8x6b_ref', core_8 if h['hotspot_class']=='core_hotspot' else sec_8), ('9E6Y', 'pdb_9e6y_ref', core_9 if h['hotspot_class']=='core_hotspot' else sec_9)]:
                if h[field]:
                    # For secondary hotspots, only color the structure that actually supports the contact.
                    if h['hotspot_class'] == 'secondary_hotspot' and pdb_id not in h['supporting_structures'].split(';'):
                        continue
                    target.append(resi_from_ref(h[field]))
        if h['hotspot_id'].startswith('soft_hint_'):
            for pdb_id, field, obj in [('8X6B', 'pdb_8x6b_ref', 'pdb8x6b'), ('9E6Y', 'pdb_9e6y_ref', 'pdb9e6y')]:
                if h[field]:
                    labels.append((obj, chain_from_ref(h[field]), resi_from_ref(h[field]), h['hotspot_id'].replace('soft_hint_', ''), h['hotspot_class']))

    lines = [
        'reinitialize',
        f'load {STRUCT / "8X6B.pdb"}, pdb8x6b',
        f'load {STRUCT / "9E6Y.pdb"}, pdb9e6y',
        'hide everything',
        'bg_color white',
        'set ray_opaque_background, off',
        'set antialias, 2',
        'set cartoon_fancy_helices, 1',
        'set dash_width, 2.0',
        'set label_size, 16',
        'set label_color, black',
        '# Align both complexes by PVRIG chains to compare interface conservation',
        'align pdb9e6y and chain A, pdb8x6b and chain B',
        '# Base coloring: PVRIG receptor cyan/teal, PVRL2 ligand gray',
        'show cartoon, pdb8x6b and (chain A+B)',
        'show cartoon, pdb9e6y and (chain A+D)',
        'color teal, pdb8x6b and chain B',
        'color marine, pdb9e6y and chain A',
        'color gray70, pdb8x6b and chain A',
        'color gray50, pdb9e6y and chain D',
        'set cartoon_transparency, 0.20, pdb9e6y',
        '# Interface surfaces',
        'show surface, pdb8x6b and chain B',
        'set transparency, 0.55, pdb8x6b and chain B',
        'show surface, pdb9e6y and chain A',
        'set transparency, 0.70, pdb9e6y and chain A',
    ]
    add_selection(lines, 'core_8x6b', 'pdb8x6b', 'B', core_8, 'orange')
    add_selection(lines, 'core_9e6y', 'pdb9e6y', 'A', core_9, 'orange')
    add_selection(lines, 'secondary_8x6b', 'pdb8x6b', 'B', sec_8, 'yellow')
    add_selection(lines, 'secondary_9e6y', 'pdb9e6y', 'A', sec_9, 'yellow')

    lines.extend([
        '# Soft hints: R95 magenta, I97 pink, S67 blue-gray; these are not hard constraints',
        'select soft_R95, (pdb8x6b and chain B and resi 57) or (pdb9e6y and chain A and resi 55)',
        'select soft_I97, (pdb8x6b and chain B and resi 59) or (pdb9e6y and chain A and resi 57)',
        'select soft_S67, (pdb8x6b and chain B and resi 29) or (pdb9e6y and chain A and resi 27)',
        'color magenta, soft_R95',
        'color hotpink, soft_I97',
        'color slate, soft_S67',
        'show sticks, soft_R95 or soft_I97 or soft_S67',
    ])
    for obj, chain, resi, label, cls in labels:
        lines.append(f'label ({obj} and chain {chain} and resi {resi} and name CA), "{label} ({obj}:{chain}{resi})"')

    # Add the closest ten contact distances per structure to show binding mode without clutter.
    lines.append('# Closest heavy-atom contacts at the PVRIG-PVRL2 interface')
    for pdb_id, obj, rchain, lchain in [('8X6B', 'pdb8x6b', 'B', 'A'), ('9E6Y', 'pdb9e6y', 'A', 'D')]:
        top = sorted(pair_rows[pdb_id], key=lambda r: float(r['min_heavy_atom_distance_a']))[:10]
        for i, r in enumerate(top, 1):
            dname = f'd_{pdb_id.lower()}_{i:02d}'
            lines.append(
                f'distance {dname}, ({obj} and chain {rchain} and resi {r["pvrig_resseq"]} and name {r["pvrig_atom"]}), '
                f'({obj} and chain {lchain} and resi {r["ligand_resseq"]} and name {r["ligand_atom"]})'
            )
            lines.append(f'color red, {dname}')

    lines.extend([
        'hide labels, d_*',
        '# Views/scenes',
        'orient (core_8x6b or secondary_8x6b or soft_R95 or soft_I97)',
        'zoom (core_8x6b or secondary_8x6b or soft_R95 or soft_I97), 8',
        'scene interface_overlay, store',
        'disable pdb9e6y',
        'zoom (pdb8x6b and (chain A+B)), 5',
        'scene complex_8x6b, store',
        'enable pdb9e6y',
        'disable pdb8x6b',
        'zoom (pdb9e6y and (chain A+D)), 5',
        'scene complex_9e6y, store',
        'enable pdb8x6b',
        'scene interface_overlay, recall',
        f'png {FIG / "pvrig_pvrl2_interface_overlay.png"}, 1800, 1400, ray=1',
        'disable pdb9e6y',
        f'png {FIG / "pvrig_pvrl2_8x6b_interface.png"}, 1800, 1400, ray=1',
        'enable pdb9e6y',
        'disable pdb8x6b',
        f'png {FIG / "pvrig_pvrl2_9e6y_interface.png"}, 1800, 1400, ray=1',
        'enable pdb8x6b',
        f'save {VIS / "pvrig_pvrl2_mechanism_view.pse"}',
        'set_name pdb8x6b, 8X6B_PVRIG_PVRL2',
        'set_name pdb9e6y, 9E6Y_PVRIG_PVRL2',
    ])
    (VIS / 'pvrig_pvrl2_mechanism_view.pml').write_text('\n'.join(lines) + '\n')


def add_selection(lines: list[str], name: str, obj: str, chain: str, residues: list[str], color: str) -> None:
    if not residues:
        return
    resis = '+'.join(sorted(set(residues), key=lambda x: int(''.join(ch for ch in x if ch.isdigit()))))
    lines.extend([
        f'select {name}, {obj} and chain {chain} and resi {resis}',
        f'color {color}, {name}',
        f'show sticks, {name}',
        f'show spheres, {name} and name CA',
        f'set sphere_scale, 0.35, {name} and name CA',
    ])


def write_notes() -> None:
    text = '''# PVRIG-PVRL2 Binding Mechanism Visual Notes

## What to Open

- PyMOL script: `visualization/pvrig_pvrl2_mechanism_view.pml`
- PyMOL session: `visualization/pvrig_pvrl2_mechanism_view.pse`
- Key residue table: `data/structures/PVRIG_key_contact_residues_v1.csv`
- Hotspot set: `data/structures/PVRIG_hotspot_set_v1.csv`
- PNG snapshots: `reports/figures/pvrig_pvrl2_interface_overlay.png`, `reports/figures/pvrig_pvrl2_8x6b_interface.png`, `reports/figures/pvrig_pvrl2_9e6y_interface.png`

## Color Legend

- PVRIG receptor: cyan/blue cartoon and surface.
- PVRL2/Nectin-2 ligand: gray cartoon.
- Core hotspots: orange sticks/spheres; these are 21 PVRIG interface positions supported by both 8X6B and 9E6Y.
- Secondary hotspots: yellow sticks/spheres; these are 2 edge contacts supported by one structure under the current 4.5 A cutoff.
- R95: magenta; strongest patent soft hint because it overlaps the consensus distance interface.
- I97: hot pink; weaker soft hint, supported as a current contact only in 8X6B.
- S67: slate; mapped but outside the current PVRIG-PVRL2 distance interface.
- Red dashed lines: ten closest heavy-atom PVRIG-PVRL2 contacts per structure.

## Mechanistic Interpretation

The interface is a broad Ig-like domain surface, not a deep pocket. The current strongest blocking seed is the two-structure consensus interface: a surface patch that includes charged residues such as H92/R95/R98/K135/E141 in UniProt numbering. R95 is especially important for review because it is both a patent-derived soft hint and a consensus interface residue. I97 sits next to this region but has weaker structural support. S67 maps away from the current distance interface and should not drive Phase I scoring.

Use this view to reason about where a VHH CDR3 or redesigned CDR surface would need to occupy space to sterically compete with PVRL2. Do not interpret this view as a docking pose, affinity model, or antibody paratope.
'''
    (REPORTS / 'pvrig_pvrl2_binding_mechanism_visual_notes.md').write_text(text)


def write_html_viewer(hotspots) -> None:
    # Lightweight offline-friendly HTML that loads local PDB text into py3Dmol from CDNs when opened in a browser.
    pdb8 = (STRUCT / '8X6B.pdb').read_text().replace('`', '')
    pdb9 = (STRUCT / '9E6Y.pdb').read_text().replace('`', '')
    html = f'''<!doctype html>
<html><head><meta charset="utf-8"><title>PVRIG-PVRL2 mechanism viewer</title>
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<style>body{{font-family:sans-serif;margin:0}} #viewer{{width:100vw;height:92vh}} .note{{padding:8px 12px}}</style></head>
<body><div class="note"><b>PVRIG-PVRL2 mechanism viewer</b>: cyan/marine=PVRIG, gray=PVRL2. Use PyMOL session for full labels/hotspot selections.</div><div id="viewer"></div>
<script>
let viewer = $3Dmol.createViewer('viewer', {{backgroundColor:'white'}});
viewer.addModel(`{pdb8}`, 'pdb');
viewer.addModel(`{pdb9}`, 'pdb');
viewer.setStyle({{}}, {{cartoon:{{color:'lightgray'}}}});
viewer.setStyle({{model:0, chain:'B'}}, {{cartoon:{{color:'teal'}}, stick:{{radius:0.12}}}});
viewer.setStyle({{model:0, chain:'A'}}, {{cartoon:{{color:'lightgray'}}}});
viewer.setStyle({{model:1, chain:'A'}}, {{cartoon:{{color:'marine'}}, stick:{{radius:0.12}}}});
viewer.setStyle({{model:1, chain:'D'}}, {{cartoon:{{color:'gray'}}}});
viewer.setStyle({{model:0, chain:'B', resi:[57]}}, {{stick:{{color:'magenta', radius:0.35}}, sphere:{{color:'magenta', radius:0.7}}}});
viewer.setStyle({{model:1, chain:'A', resi:[55]}}, {{stick:{{color:'magenta', radius:0.35}}, sphere:{{color:'magenta', radius:0.7}}}});
viewer.setStyle({{model:0, chain:'B', resi:[59]}}, {{stick:{{color:'hotpink', radius:0.30}}, sphere:{{color:'hotpink', radius:0.6}}}});
viewer.setStyle({{model:1, chain:'A', resi:[57]}}, {{stick:{{color:'hotpink', radius:0.30}}, sphere:{{color:'hotpink', radius:0.6}}}});
viewer.setStyle({{model:0, chain:'B', resi:[29]}}, {{stick:{{color:'slateblue', radius:0.25}}, sphere:{{color:'slateblue', radius:0.5}}}});
viewer.setStyle({{model:1, chain:'A', resi:[27]}}, {{stick:{{color:'slateblue', radius:0.25}}, sphere:{{color:'slateblue', radius:0.5}}}});
viewer.zoomTo(); viewer.render();
</script></body></html>'''
    (VIS / 'pvrig_pvrl2_mechanism_view.html').write_text(html)


if __name__ == '__main__':
    main()
