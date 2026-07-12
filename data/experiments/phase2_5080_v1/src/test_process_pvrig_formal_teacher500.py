#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("process_pvrig_formal_teacher500.py")
SPEC = importlib.util.spec_from_file_location("process_pvrig_formal_teacher500", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class ProcessPVRIGFormalTeacher500Test(unittest.TestCase):
    def test_normalize_row_maps_formal_cdr_fields(self) -> None:
        row = {
            "candidate_id": "c1",
            "vhh_sequence": "QVQL",
            "cdr1_after": "A",
            "cdr2_after": "B",
            "cdr3_after": "C",
            "parent_id": "p1",
        }
        normalized = MOD.normalize_row(row)
        self.assertEqual(normalized["sequence"], "QVQL")
        self.assertEqual(normalized["cdr1"], "A")
        self.assertEqual(normalized["cdr3"], "C")
        self.assertEqual(normalized["parent_id"], "p1")

    def test_normalize_row_rejects_missing_sequence(self) -> None:
        with self.assertRaises(ValueError):
            MOD.normalize_row({"candidate_id": "c1"})


if __name__ == "__main__":
    unittest.main()
