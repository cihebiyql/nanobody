#!/usr/bin/env python3
"""Regression tests for PVRIG numbering reconciliation artifacts."""
from __future__ import annotations

import csv
import filecmp
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'reconcile_pvrig_numbering.py'
STRUCTURES = ROOT / 'data' / 'structures'


class PvrigNumberingReconciliationTest(unittest.TestCase):
    def test_golden_outputs_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory(prefix='pvrig_numbering_test_') as tmp_s:
            tmp = Path(tmp_s)
            subprocess.run(
                [sys.executable, str(SCRIPT), '--output-dir', str(tmp)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for name in [
                'PVRIG_numbering_reconciliation.csv',
                'PVRIG_soft_hint_structure_mapping.csv',
            ]:
                self.assertTrue(
                    filecmp.cmp(STRUCTURES / name, tmp / name, shallow=False),
                    f'{name} differs from golden output',
                )

    def test_soft_hint_mapping_statuses(self) -> None:
        with (STRUCTURES / 'PVRIG_soft_hint_structure_mapping.csv').open(newline='') as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['mapping_status'] == 'mapped_residue_matches_hint_aa' for row in rows))
        self.assertTrue(all(row['interpretation'] == 'soft_hint_only_not_hard_constraint' for row in rows))

        by_hint_pdb = {(row['hint'], row['pdb_id']): row for row in rows}
        expected = {
            ('S67', '8X6B'): ('29', 'S', 'not_4p5a_interface_in_this_structure', ''),
            ('S67', '9E6Y'): ('27', 'S', 'not_4p5a_interface_in_this_structure', ''),
            ('R95', '8X6B'): ('57', 'R', 'consensus_4p5a_interface', '50'),
            ('R95', '9E6Y'): ('55', 'R', 'consensus_4p5a_interface', '50'),
            ('I97', '8X6B'): ('59', 'I', 'single_structure_4p5a_interface', '52'),
            ('I97', '9E6Y'): ('57', 'I', 'not_4p5a_interface_in_this_structure', '52'),
        }
        self.assertEqual(set(by_hint_pdb), set(expected))
        for key, (pdb_resseq, aa, interface_status, alignment_col) in expected.items():
            with self.subTest(key=key):
                row = by_hint_pdb[key]
                self.assertEqual(row['pdb_resseq'], pdb_resseq)
                self.assertEqual(row['pdb_aa'], aa)
                self.assertEqual(row['interface_status'], interface_status)
                self.assertEqual(row['alignment_col'], alignment_col)

    def test_numbering_reconciliation_counts(self) -> None:
        with (STRUCTURES / 'PVRIG_numbering_reconciliation.csv').open(newline='') as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 211)
        self.assertEqual(sum(row['pdb_id'] == '8X6B' for row in rows), 103)
        self.assertEqual(sum(row['pdb_id'] == '9E6Y' for row in rows), 108)
        self.assertTrue(all(row['uniprot_accession'] == 'Q6DKI7' for row in rows))
        self.assertTrue(all(row['uniprot_position'] for row in rows))


if __name__ == '__main__':
    unittest.main()
