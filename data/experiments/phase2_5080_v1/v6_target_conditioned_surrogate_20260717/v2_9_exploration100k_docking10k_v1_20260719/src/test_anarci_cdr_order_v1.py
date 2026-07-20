from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd


PATH = Path(__file__).with_name("run_anarci_imgt_batch_v1.py")
SPEC = importlib.util.spec_from_file_location("anarci_batch", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class AnarciCdrOrderTests(unittest.TestCase):
    def test_insertion_columns_keep_anarci_sequence_order(self) -> None:
        row = pd.Series(
            ["R", "A", "G", "S", "W", "C", "P"],
            index=["105", "111", "111A", "111B", "112", "112A", "117"],
        )
        self.assertEqual(MODULE.cdr_from_row(row, 105, 117), "RAGSWCP")


if __name__ == "__main__":
    unittest.main()
