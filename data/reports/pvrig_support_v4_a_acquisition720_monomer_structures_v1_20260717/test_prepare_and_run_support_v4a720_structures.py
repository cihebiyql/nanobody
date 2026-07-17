#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_and_run_support_v4a720_structures.py")
if not MODULE_PATH.is_file():
    MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/prepare_and_run_support_v4a720_structures.py"
SPEC = importlib.util.spec_from_file_location("support_v4a720_structures", MODULE_PATH)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class StructureRunnerTests(unittest.TestCase):
    def test_parse_bool_is_strict(self) -> None:
        self.assertTrue(M.parse_bool("True"))
        self.assertFalse(M.parse_bool("false"))
        with self.assertRaises(RuntimeError):
            M.parse_bool("PASS")

    def test_frozen_resource_policy_is_half_node(self) -> None:
        self.assertEqual(M.EXPECTED_GPUS, (0, 1, 2, 3))
        self.assertEqual(M.MAX_PARALLEL, 4)
        self.assertEqual(M.THREADS_PER_WORKER, 8)
        self.assertEqual(M.MAX_PARALLEL * M.THREADS_PER_WORKER, 32)

    def test_claim_boundary_excludes_docking_and_biology(self) -> None:
        for token in ("not_docking", "binding", "affinity", "experimental_blocking", "docking_gold"):
            self.assertIn(token, M.CLAIM_BOUNDARY)

    def test_normalize_matching_chain_and_geometry(self) -> None:
        sequence = "AG"
        lines = [
            "ATOM      1  CA  ALA H   7       0.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      2  CA  GLY H   8       3.800   0.000   0.000  1.00 20.00           C  ",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            source, destination = Path(tmp) / "raw.pdb", Path(tmp) / "norm.pdb"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual(M.normalize_matching_chain(source, destination, sequence), "H")
            self.assertEqual(M.pdb_chains(destination)["A"], [(('   1', ' '), 'ALA'), (('   2', ' '), 'GLY')])
            geometry = M.ca_geometry(destination)
            self.assertEqual(geometry["ca_count"], 2)
            self.assertTrue(geometry["likely_sane_backbone"])

    def test_existing_terminal_binds_sequence_and_artifact_hash(self) -> None:
        row = {"candidate_id": "C1", "sequence_sha256": "abc"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdb = root / "outputs/nbb2/C1/a.pdb"
            pdb.parent.mkdir(parents=True)
            pdb.write_text("END\n", encoding="utf-8")
            M.write_json(root / "status/candidates/C1.terminal.json", {
                "candidate_id": "C1", "sequence_sha256": "abc",
                "nbb2": {"status": "SUCCESS", "pdb": str(pdb), "pdb_sha256": M.sha256_file(pdb)},
                "igfold": {"status": "FAILED"},
            })
            self.assertIsNotNone(M.validate_existing_terminal(root, row))
            pdb.write_text("DRIFT\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                M.validate_existing_terminal(root, row)

    def test_summary_is_fail_closed_without_replacement(self) -> None:
        self.assertIn("no replacement", M.__doc__.lower())
        self.assertIn("all 720", M.__doc__.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
