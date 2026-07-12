#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("collect_pvrig_formal_rfantibody_candidates.py")
SPEC = importlib.util.spec_from_file_location("collect_pvrig_formal_rfantibody_candidates", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, residue: str, chain: str, number: int) -> str:
    return f"ATOM  {serial:5d}  CA  {residue:>3s} {chain}{number:4d}    {0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00\n"


class CollectRFantibodyCandidatesTest(unittest.TestCase):
    def test_pdb_chain_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.pdb"
            path.write_text(
                atom_line(1, "GLN", "H", 1)
                + atom_line(2, "VAL", "H", 2)
                + atom_line(3, "ALA", "T", 3),
                encoding="utf-8",
            )
            self.assertEqual(MOD.pdb_chain_sequence(path, "H"), "QV")
            self.assertEqual(MOD.pdb_chain_sequence(path, "T"), "A")

    def test_extract_candidate_cdrs_anchors_variable_cdr3_to_fr4(self) -> None:
        parent = {
            "cdr1_start_1based": 3, "cdr1_end_1based": 4, "cdr1": "CD",
            "cdr2_start_1based": 7, "cdr2_end_1based": 8, "cdr2": "GH",
            "cdr3_start_1based": 11, "cdr3_end_1based": 12, "cdr3": "KL",
            "fr4_tail": "WXYZ",
        }
        result = MOD.extract_candidate_cdrs("ABCDEFGHIJMNOPWXYZ", parent)
        self.assertEqual(result["cdr1"], "CD")
        self.assertEqual(result["cdr2"], "GH")
        self.assertEqual(result["cdr3"], "MNOP")
        self.assertEqual(result["cdr3_length"], 4)


if __name__ == "__main__":
    unittest.main()
