#!/usr/bin/env python3
"""Regression tests for PVRIG/PVRL2 interface extraction artifacts."""
from __future__ import annotations

import csv
import filecmp
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'extract_pvrig_interface.py'
STRUCTURES = ROOT / 'data' / 'structures'


class ExtractPvrigInterfaceRegressionTest(unittest.TestCase):
    def test_golden_outputs_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory(prefix='pvrig_interface_test_') as tmp_s:
            tmp = Path(tmp_s)
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    '--output-dir',
                    str(tmp),
                    f'8X6B:{STRUCTURES / "8X6B.pdb"}:B:A',
                    f'9E6Y:{STRUCTURES / "9E6Y.pdb"}:A:D',
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for name in [
                'PVRIG_interface_residues_8X6B.csv',
                'PVRIG_interface_residues_9E6Y.csv',
                'PVRIG_ligand_contact_pairs_8X6B.csv',
                'PVRIG_ligand_contact_pairs_9E6Y.csv',
                'PVRIG_consensus_interface_residues.csv',
                'PVRIG_soft_epitope_hints.csv',
                'PVRIG_epitope_priority_map.pml',
            ]:
                self.assertTrue(
                    filecmp.cmp(STRUCTURES / name, tmp / name, shallow=False),
                    f'{name} differs from golden output',
                )

    def test_expected_interface_counts(self) -> None:
        expected_counts = {
            'PVRIG_interface_residues_8X6B.csv': 22,
            'PVRIG_interface_residues_9E6Y.csv': 22,
            'PVRIG_ligand_contact_pairs_8X6B.csv': 57,
            'PVRIG_ligand_contact_pairs_9E6Y.csv': 56,
            'PVRIG_consensus_interface_residues.csv': 23,
        }
        for name, expected in expected_counts.items():
            with self.subTest(name=name):
                with (STRUCTURES / name).open(newline='') as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), expected)
        with (STRUCTURES / 'PVRIG_consensus_interface_residues.csv').open(newline='') as handle:
            consensus = list(csv.DictReader(handle))
        self.assertEqual(sum(row['support_count'] == '2' for row in consensus), 21)
        self.assertEqual(sum(row['support_count'] == '1' for row in consensus), 2)

    def test_soft_hints_are_not_hard_selected(self) -> None:
        with (STRUCTURES / 'PVRIG_soft_epitope_hints.csv').open(newline='') as handle:
            hints = list(csv.DictReader(handle))
        self.assertEqual([row['hint'] for row in hints], ['S67', 'R95', 'I97'])
        self.assertTrue(all('soft' in row['status'] for row in hints))
        pml = (STRUCTURES / 'PVRIG_epitope_priority_map.pml').read_text()
        self.assertIn('Soft hints S67/R95/I97 are intentionally not selected here', pml)
        self.assertIn('PVRIG_soft_hint_structure_mapping.csv', pml)


if __name__ == '__main__':
    unittest.main()
