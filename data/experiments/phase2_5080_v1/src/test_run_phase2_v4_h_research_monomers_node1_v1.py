#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_phase2_v4_h_research_monomers_node1_v1.py")
SPEC = importlib.util.spec_from_file_location("monomer_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def atom(serial: int, residue: str, number: int, x: float) -> str:
    return (
        f"ATOM  {serial:5d}  CA  {residue:>3s} H{number:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C"
    )


class MonomerRunnerTests(unittest.TestCase):
    def test_normalize_and_validate_exact_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdb"
            destination = root / "normalized.pdb"
            source.write_text(
                "\n".join([atom(1, "GLN", 10, 0.0), atom(2, "VAL", 11, 3.8)]) + "\n"
            )
            geometry = MODULE.normalize_and_validate(source, destination, "QV")
            self.assertEqual(geometry["source_chain"], "H")
            self.assertEqual(MODULE.pdb_chain_sequences(destination), {"A": "QV"})

    def test_normalize_rejects_sequence_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdb"
            source.write_text(
                "\n".join([atom(1, "GLN", 1, 0.0), atom(2, "VAL", 2, 3.8)]) + "\n"
            )
            with self.assertRaisesRegex(RuntimeError, "exact_sequence_chain_count"):
                MODULE.normalize_and_validate(source, root / "out.pdb", "QA")

    def test_hash_is_stable(self) -> None:
        self.assertEqual(
            MODULE.sha256_text("QVQL"),
            "40284552a0c1e0630e2634b159453e2ccfb5f5e88997b360a30f64523b3bc125",
        )


if __name__ == "__main__":
    unittest.main()
