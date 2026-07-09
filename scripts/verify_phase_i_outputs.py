#!/usr/bin/env python3
"""Leader verification for Phase I exploration artifacts."""
from __future__ import annotations

import csv
from collections import Counter
import filecmp
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(msg: str) -> None:
    print(f'FAIL: {msg}')
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f'PASS: {msg}')


def require(path: str) -> Path:
    p = ROOT / path
    if not p.exists():
        fail(f'missing {path}')
    ok(f'exists {path}')
    return p


def read_csv(path: str):
    p = require(path)
    with p.open(newline='') as handle:
        return list(csv.DictReader(handle))


def count_fasta(path: str) -> int:
    p = require(path)
    count = sum(1 for line in p.read_text().splitlines() if line.startswith('>'))
    return count


def verify_structure() -> None:
    rows_8 = read_csv('data/structures/PVRIG_interface_residues_8X6B.csv')
    rows_9 = read_csv('data/structures/PVRIG_interface_residues_9E6Y.csv')
    pairs_8 = read_csv('data/structures/PVRIG_ligand_contact_pairs_8X6B.csv')
    pairs_9 = read_csv('data/structures/PVRIG_ligand_contact_pairs_9E6Y.csv')
    consensus = read_csv('data/structures/PVRIG_consensus_interface_residues.csv')
    hints = read_csv('data/structures/PVRIG_soft_epitope_hints.csv')
    if len(rows_8) != 22:
        fail(f'8X6B interface row count {len(rows_8)} != 22')
    if len(rows_9) != 22:
        fail(f'9E6Y interface row count {len(rows_9)} != 22')
    if len(pairs_8) != 57:
        fail(f'8X6B contact pair row count {len(pairs_8)} != 57')
    if len(pairs_9) != 56:
        fail(f'9E6Y contact pair row count {len(pairs_9)} != 56')
    if len(consensus) != 23:
        fail(f'consensus row count {len(consensus)} != 23')
    both = sum(1 for r in consensus if r['support_count'] == '2')
    one = sum(1 for r in consensus if r['support_count'] == '1')
    if both != 21 or one != 2:
        fail(f'consensus support counts both={both} one={one}, expected 21/2')
    if [r['hint'] for r in hints] != ['S67', 'R95', 'I97']:
        fail('soft hint rows are not S67/R95/I97')
    pml = require('data/structures/PVRIG_epitope_priority_map.pml').read_text()
    for token in ['select pvrig_8X6B_consensus', 'select pvrig_9E6Y_consensus', 'pdb8x6b and chain B', 'pdb9e6y and chain A']:
        if token not in pml:
            fail(f'PML missing token {token}')
    ok('structure artifacts have expected row counts and PML selections')


def verify_numbering() -> None:
    numbering = read_csv('data/structures/PVRIG_numbering_reconciliation.csv')
    mapping = read_csv('data/structures/PVRIG_soft_hint_structure_mapping.csv')
    hotspots = read_csv('data/structures/PVRIG_hotspot_set_v1.csv')
    if len(numbering) != 211:
        fail(f'numbering reconciliation row count {len(numbering)} != 211')
    counts = Counter(r['pdb_id'] for r in numbering)
    if counts != {'8X6B': 103, '9E6Y': 108}:
        fail(f'numbering reconciliation PDB counts {dict(counts)} != expected 8X6B=103, 9E6Y=108')
    if any(r['uniprot_accession'] != 'Q6DKI7' or not r['uniprot_position'] for r in numbering):
        fail('numbering reconciliation should map all rows to UniProt Q6DKI7 positions')
    soft_rows = [r for r in numbering if r['soft_hint_label']]
    if len(soft_rows) != 6:
        fail(f'numbering reconciliation soft-hint row count {len(soft_rows)} != 6')

    if len(mapping) != 6:
        fail(f'soft hint structure mapping row count {len(mapping)} != 6')
    if {r['hint'] for r in mapping} != {'S67', 'R95', 'I97'}:
        fail('soft hint structure mapping should cover S67/R95/I97')
    if any(r['mapping_status'] != 'mapped_residue_matches_hint_aa' for r in mapping):
        fail('all soft hints should map to the expected amino acid under the UniProt Q6DKI7 assumption')
    if any(r['interpretation'] != 'soft_hint_only_not_hard_constraint' for r in mapping):
        fail('soft hint mapping must remain marked as soft-only')
    expected = {
        ('S67', '8X6B'): ('29', 'S', 'not_4p5a_interface_in_this_structure', ''),
        ('S67', '9E6Y'): ('27', 'S', 'not_4p5a_interface_in_this_structure', ''),
        ('R95', '8X6B'): ('57', 'R', 'consensus_4p5a_interface', '50'),
        ('R95', '9E6Y'): ('55', 'R', 'consensus_4p5a_interface', '50'),
        ('I97', '8X6B'): ('59', 'I', 'single_structure_4p5a_interface', '52'),
        ('I97', '9E6Y'): ('57', 'I', 'not_4p5a_interface_in_this_structure', '52'),
    }
    by_hint_pdb = {(r['hint'], r['pdb_id']): r for r in mapping}
    if set(by_hint_pdb) != set(expected):
        fail(f'soft hint mapping keys {sorted(by_hint_pdb)} do not match expected')
    for key, (pdb_resseq, aa, interface_status, alignment_col) in expected.items():
        row = by_hint_pdb[key]
        if (row['pdb_resseq'], row['pdb_aa'], row['interface_status'], row['alignment_col']) != (pdb_resseq, aa, interface_status, alignment_col):
            fail(f'soft hint mapping mismatch for {key}: {row}')
    if len(hotspots) != 26:
        fail(f'hotspot set row count {len(hotspots)} != 26')
    hotspot_counts = Counter(r['hotspot_class'] for r in hotspots)
    if hotspot_counts['core_hotspot'] != 21 or hotspot_counts['secondary_hotspot'] != 2:
        fail(f'hotspot core/secondary counts mismatch: {dict(hotspot_counts)}')
    for hint, expected_class in {
        'soft_hint_R95': 'soft_hint_high',
        'soft_hint_I97': 'soft_hint_low',
        'soft_hint_S67': 'soft_hint_excluded_from_phase_i_scoring',
    }.items():
        row = next((r for r in hotspots if r['hotspot_id'] == hint), None)
        if row is None or row['hotspot_class'] != expected_class or row['design_use'] != 'soft_hint_only_not_hard_constraint':
            fail(f'hotspot soft hint row mismatch for {hint}: {row}')
    ok('numbering reconciliation and S67/R95/I97 soft-hint mapping have expected statuses')


def verify_regeneration() -> None:
    with tempfile.TemporaryDirectory(prefix='pvrig_phase_i_verify_') as tmp_s:
        tmp = Path(tmp_s)
        cmd = [
            sys.executable,
            str(ROOT / 'scripts' / 'extract_pvrig_interface.py'),
            '--output-dir',
            str(tmp),
            f"8X6B:{ROOT / 'data/structures/8X6B.pdb'}:B:A",
            f"9E6Y:{ROOT / 'data/structures/9E6Y.pdb'}:A:D",
        ]
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for name in [
            'PVRIG_interface_residues_8X6B.csv',
            'PVRIG_interface_residues_9E6Y.csv',
            'PVRIG_ligand_contact_pairs_8X6B.csv',
            'PVRIG_ligand_contact_pairs_9E6Y.csv',
            'PVRIG_consensus_interface_residues.csv',
            'PVRIG_soft_epitope_hints.csv',
            'PVRIG_epitope_priority_map.pml',
        ]:
            if not filecmp.cmp(ROOT / 'data/structures' / name, tmp / name, shallow=False):
                fail(f'regenerated artifact differs: {name}')
        cmd = [
            sys.executable,
            str(ROOT / 'scripts' / 'reconcile_pvrig_numbering.py'),
            '--output-dir',
            str(tmp),
        ]
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for name in [
            'PVRIG_numbering_reconciliation.csv',
            'PVRIG_soft_hint_structure_mapping.csv',
        ]:
            if not filecmp.cmp(ROOT / 'data/structures' / name, tmp / name, shallow=False):
                fail(f'regenerated numbering artifact differs: {name}')
    ok('structure extraction regenerates byte-identical artifacts')


def verify_positives() -> None:
    if count_fasta('positives/known_positive_antibodies.fasta') != 3:
        fail('positive FASTA should contain exactly 3 entries')
    meta = read_csv('positives/positive_antibody_metadata.csv')
    cdr = read_csv('positives/known_positive_CDR_table.csv')
    mech = read_csv('positives/mechanism_reference_table.csv')
    if {r['record_id'] for r in meta} != {'tab5_vh', 'tab5_vl', 'hr151_vhh'}:
        fail('positive metadata record ids mismatch')
    if any(r['numbering_status'] != 'anarci_success' for r in meta):
        fail('positive metadata should be anarci_success')
    if any(r['cdr_source'] != 'ab_data_validator_anarci_imgt' for r in meta):
        fail('positive metadata should record ab_data_validator_anarci_imgt CDR source')
    if len(cdr) != 3 or any(r['numbering_status'] != 'anarci_success' for r in cdr):
        fail('CDR table should contain 3 anarci_success rows')
    expected_cdr3 = {'tab5_vh': 'AKGSGNIYYFSGMDV', 'tab5_vl': 'QQYYSYPLT', 'hr151_vhh': 'AAGDSPDGRCGLPPQGLNY'}
    for row in cdr:
        if not (row['cdr1'] and row['cdr2'] and row['cdr3']):
            fail(f"CDR table has empty CDR for {row['record_id']}")
        if row['cdr3'] != expected_cdr3[row['record_id']]:
            fail(f"Unexpected CDR3 for {row['record_id']}: {row['cdr3']}")
    sim = read_csv('positives/positive_CDR_similarity_exclusion_table.csv')
    if len(sim) != 9 or any(r['status'] != 'excluded_high_cdr_identity' for r in sim):
        fail('similarity exclusion table should contain 9 high-identity rows')
    if any(r['identity_pct'] != '100.0' or r['threshold_pct'] != '80.0' for r in sim):
        fail('similarity exclusion table should record 100.0 identity against 80.0 threshold')
    if len(mech) != 1 or mech[0]['record_id'] != 'com701' or mech[0]['sequence_status'] != 'not_in_sequence_positive_fasta':
        fail('COM701 mechanism reference row mismatch')
    fasta_text = require('positives/known_positive_antibodies.fasta').read_text()
    if 'COM701' in fasta_text.upper():
        fail('COM701 should not appear in positive FASTA')
    ok('positive/reference artifacts are separated and official-validator CDR/similarity evidence is populated')


def verify_scaffolds() -> None:
    source = read_csv('scaffolds/source_registry.csv')
    if len(source) < 5:
        fail('scaffold source registry should have at least five explored sources')
    source_by_name = {r['source']: r for r in source}
    if source_by_name.get('PLAbDab-nano', {}).get('status') != 'controlled_import_completed_local_screening_only':
        fail('PLAbDab-nano source should be controlled_import_completed_local_screening_only after Phase I-b import')
    if 'do_not_redistribute_raw_csv' not in source_by_name['PLAbDab-nano']['use_terms_status']:
        fail('PLAbDab-nano source should preserve raw-data redistribution caveat')

    raw_meta = read_csv('scaffolds/raw_vhh_scaffold_metadata.csv')
    quality = read_csv('scaffolds/vhh_scaffold_quality_table.csv')
    clusters = read_csv('scaffolds/vhh_scaffold_cluster_table.csv')
    top = read_csv('scaffolds/top_200_vhh_scaffolds_for_design.csv')
    require('scaffolds/README.md')
    if len(raw_meta) != 1965 or len(quality) != 1965:
        fail(f'expected 1965 imported/quality rows, got metadata={len(raw_meta)} quality={len(quality)}')
    if count_fasta('scaffolds/raw_vhh_scaffold_pool.fasta') != 1965:
        fail('raw scaffold FASTA should contain 1965 records')
    if sum(r['numbering_status'] == 'anarci_success' for r in quality) != 1965:
        fail('all imported scaffolds should have ANARCI success in this controlled batch')
    kept = [r for r in quality if r['keep_or_drop'] == 'keep']
    dropped = [r for r in quality if r['keep_or_drop'] == 'drop']
    if len(kept) != 1591 or len(dropped) != 374:
        fail(f'expected kept=1591 dropped=374, got kept={len(kept)} dropped={len(dropped)}')
    if count_fasta('scaffolds/clean_vhh_scaffold_library.fasta') != 1591:
        fail('clean scaffold FASTA should contain 1591 records')
    if len(clusters) != 1268:
        fail(f'expected 1268 cluster rows, got {len(clusters)}')
    if len(top) != 200 or count_fasta('scaffolds/top_200_vhh_scaffolds_for_design.fasta') != 200:
        fail('top 200 outputs should contain exactly 200 records')
    if any('do_not_redistribute_raw_csv' not in r['license_or_use_terms'] for r in quality):
        fail('quality rows should preserve PLAbDab-nano raw-data redistribution caveat')
    ok('controlled PLAbDab-nano scaffold import, gate, clustering, clean library, and top 200 outputs verified')


def verify_docs_reports() -> None:
    for path in [
        'PROJECT_PROGRESS.md',
        'docs/PHASE_I_PLAN.md',
        'docs/PHASE_I_EXPLORATION.md',
        'docs/PHASE_I_B_PLAN.md',
        'reports/leader_verification.md',
        'reports/phase_i_b_numbering_reconciliation.md',
        'reports/plabdab_nano_access_review.md',
        'reports/plabdab_nano_license_decision.md',
        'reports/plabdab_nano_scaffold_gate_summary.md',
        'reports/external_source_evidence.md',
        'reports/team/worker-1_structure_interface_method_review.md',
        'reports/team/worker-1-structure.md',
        'reports/team/worker-2-positives-validator.md',
        'reports/team/worker-3-scaffolds.md',
    ]:
        require(path)
    progress = require('PROJECT_PROGRESS.md').read_text()
    for token in ['Positive FASTA entries: 3', 'Consensus map: 23 aligned interface columns', 'PVRIG numbering reconciliation: 211 mapped structure residues', 'S67/R95/I97 structure mappings: 6 rows', 'Clean scaffold records retained: 1591', 'Top scaffold records written: 200', 'Official `ab-data-validator` has been installed/run and versioned.']:
        if token not in progress:
            fail(f'progress doc missing token: {token}')
    evidence = require('reports/external_source_evidence.md').read_text()
    for token in ['bioshanghaiweek_2026_sicbc', 'Tab5', 'HR-151', 'ANARCI', '8X6B']:
        if token not in evidence:
            fail(f'external evidence missing token: {token}')
    access_review = require('reports/plabdab_nano_access_review.md').read_text()
    for token in ['vhh_sequences.csv.gz', '4457 rows', 'download_route_confirmed_not_imported', 'dataset-use-term']:
        if token not in access_review:
            fail(f'PLAbDab-nano access review missing token: {token}')
    license_decision = require('reports/plabdab_nano_license_decision.md').read_text()
    for token in ['local internal Phase I-b scaffold screening', 'not be redistributed', 'do_not_redistribute_raw_csv']:
        if token not in license_decision:
            fail(f'PLAbDab-nano license decision missing token: {token}')
    scaffold_summary = require('reports/plabdab_nano_scaffold_gate_summary.md').read_text()
    for token in ['Unique imported VHH/sdAb records: 1965', 'Clean scaffold records retained: 1591', 'Top scaffold records written: 200']:
        if token not in scaffold_summary:
            fail(f'PLAbDab-nano scaffold gate summary missing token: {token}')
    ok('docs and reports are present with expected anchors')


def main() -> None:
    verify_structure()
    verify_numbering()
    verify_regeneration()
    verify_positives()
    verify_scaffolds()
    verify_docs_reports()
    ok('Phase I exploration verification complete')


if __name__ == '__main__':
    main()
