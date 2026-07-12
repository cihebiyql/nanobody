#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("prepare_pvrig_rfantibody_v1.py")
SPEC = importlib.util.spec_from_file_location("prepare_pvrig_rfantibody_v1", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PrepareCandidateV1Test(unittest.TestCase):
    def test_repair_row(self) -> None:
        sequence = "QVQLWGQGTLVTVS"
        source = {
            "candidate_id": "PVRIG_RFAb_v0_A_bb000_mpn00",
            "sequence": sequence,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "framework_id": "h-NbBCII10",
        }
        row = MOD.repair_row(source)
        self.assertEqual(row["candidate_id"], "PVRIG_RFAb_v1_A_bb000_mpn00")
        self.assertEqual(row["sequence"], sequence + "S")
        self.assertTrue(row["sequence"].endswith("TVSS"))

    def test_current_source_inventory(self) -> None:
        with MOD.DEFAULT_SOURCE.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 1000)
        self.assertTrue(all(row["sequence"].endswith("VTVS") for row in rows))
        self.assertTrue(all(not row["sequence"].endswith("VTVSS") for row in rows))

    def test_invalid_terminal_is_rejected(self) -> None:
        sequence = "QVQLWGQGTQVTVSS"
        with self.assertRaises(ValueError):
            MOD.repair_row(
                {
                    "candidate_id": "PVRIG_RFAb_v0_A_bb000_mpn00",
                    "sequence": sequence,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                }
            )


if __name__ == "__main__":
    unittest.main()
