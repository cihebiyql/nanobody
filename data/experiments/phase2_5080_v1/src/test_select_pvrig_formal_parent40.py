#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("select_pvrig_formal_parent40.py")
SPEC = importlib.util.spec_from_file_location("select_pvrig_formal_parent40", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class SelectFormalParent40Test(unittest.TestCase):
    def test_infer_contiguous_cdr3_repairs_imgt_insertion_order(self) -> None:
        sequence = "QVQLQESGGGLVQAGGSLRLSCVASGGTFSGYAMAWFRQRPGKVREFVATISRSAASTDYADSVKGRFTISRDNAKNTVYLQMNSLKPEDTAVYYCAAKLGVTSFYRSTYSYWGQGIQVTVSS"
        result = MOD.infer_cdr3(sequence)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[2], "AAKLGVTSFYRSTYSY")
        self.assertEqual(sequence[result[0] : result[1]], result[2])

    def test_current_parent40_selection_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = MOD.run(MOD.DEFAULT_SOURCE, MOD.DEFAULT_POSITIVE_ROOT, Path(tmp))
            self.assertEqual(audit["status"], "PASS_PARENT40_FROZEN")
            self.assertEqual(audit["selected_rows"], 40)
            self.assertEqual(audit["unique_parent_clusters"], 40)
            self.assertEqual(audit["exact_known_positive_sequence_overlaps"], [])
            with (Path(tmp) / "parent40_manifest.tsv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(Counter(row["formal_split"] for row in rows), Counter(train=28, dev=6, test=6))
            self.assertEqual(Counter(row["cdr3_length_bin"] for row in rows), Counter({name: 10 for name, _, _ in MOD.LENGTH_BINS}))
            for row in rows:
                sequence = row["sequence"]
                for cdr in ("cdr1", "cdr2", "cdr3"):
                    start = int(row[f"{cdr}_start_1based"]) - 1
                    end = int(row[f"{cdr}_end_1based"])
                    self.assertEqual(sequence[start:end], row[cdr])


if __name__ == "__main__":
    unittest.main()
