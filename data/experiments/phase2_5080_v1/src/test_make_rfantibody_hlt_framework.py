#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("make_rfantibody_hlt_framework.py")
SPEC = importlib.util.spec_from_file_location("make_rfantibody_hlt_framework", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def atom(serial: int, residue: int, chain: str = "A") -> str:
    return f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    {float(residue):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C"


class MakeHltFrameworkTest(unittest.TestCase):
    def test_build_hlt_renumbers_chain_and_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdb"
            output = root / "framework.pdb"
            source.write_text("\n".join(atom(index, index + 10) for index in range(1, 8)) + "\nEND\n")
            audit = MOD.build_hlt(
                source,
                output,
                "A",
                7,
                {"H1": (2, 2), "H2": (4, 4), "H3": (6, 7)},
            )
            text = output.read_text()
            self.assertEqual(audit["status"], "PASS_HLT_FRAMEWORK_READY")
            self.assertEqual(audit["cdr_label_count"], 4)
            self.assertIn(" ALA H   1", text)
            self.assertIn("REMARK PDBinfo-LABEL:    7 H3", text)
            self.assertNotIn("END", text)

    def test_overlapping_ranges_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdb"
            source.write_text("\n".join(atom(index, index) for index in range(1, 8)) + "\n")
            with self.assertRaises(ValueError):
                MOD.build_hlt(source, Path(tmp) / "out.pdb", "A", 7, {"H1": (2, 3), "H2": (3, 4), "H3": (6, 7)})


if __name__ == "__main__":
    unittest.main()
