from __future__ import annotations

import importlib.util
import csv
import tempfile
import unittest
from pathlib import Path


PATH=Path(__file__).with_name("import_node23_tail_monomers_v1.py")
SPEC=importlib.util.spec_from_file_location("importer",PATH); MODULE=importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None; SPEC.loader.exec_module(MODULE)


class ImporterTests(unittest.TestCase):
    def test_pdb_sequence_reads_chain_a_ca_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"x.pdb"
            path.write_text(
                "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
                "ATOM      2  CA  CYS A   2       3.800   0.000   0.000  1.00  0.00           C\n"
                "ATOM      3  CA  GLY B   1       0.000   0.000   0.000  1.00  0.00           C\n"
            )
            self.assertEqual(MODULE.pdb_sequence(path),"AC")

    def test_manifest_count_is_configurable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"manifest.tsv"
            with path.open("w",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=["candidate_id","sequence_sha256"],delimiter="\t")
                writer.writeheader(); writer.writerow({"candidate_id":"A","sequence_sha256":"x"})
            self.assertEqual(set(MODULE.read_manifest(path,1)),{"A"})
            with self.assertRaisesRegex(RuntimeError,"manifest_count_or_id_closure"):
                MODULE.read_manifest(path,2)


if __name__=="__main__": unittest.main()
