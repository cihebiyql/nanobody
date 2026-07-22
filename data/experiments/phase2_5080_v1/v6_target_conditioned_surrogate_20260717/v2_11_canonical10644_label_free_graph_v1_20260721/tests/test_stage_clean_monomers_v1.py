from __future__ import annotations

import csv
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage_clean", ROOT / "src/stage_clean_monomers_v1.py")
module = importlib.util.module_from_spec(spec); sys.modules["stage_clean"] = module
assert spec and spec.loader; spec.loader.exec_module(module)


class Tests(unittest.TestCase):
    def test_stages_and_rechecks_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); rows = []
            for index in range(2):
                pdb = root / f"source_{index}.pdb"; pdb.write_text(f"ATOM {index}\n")
                rows.append({
                    "candidate_id": f"C{index}", "sequence_sha256": hashlib.sha256(f"S{index}".encode()).hexdigest(),
                    "monomer_path": str(pdb), "monomer_sha256": module.sha256_file(pdb), "monomer_chain": "A",
                })
            manifest = root / "source.tsv"
            with manifest.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            output = root / "out"
            receipt = module.stage(manifest, module.sha256_file(manifest), output, 2, 2)
            self.assertEqual(receipt["counts"]["candidates"], 2)
            self.assertTrue((output / "pdb_bundle/clean_monomers/C0.pdb").is_file())

    def test_source_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "source.tsv"; manifest.write_text("candidate_id\n")
            with self.assertRaisesRegex(ValueError, "source_manifest_sha256_mismatch"):
                module.stage(manifest, "0" * 64, Path(tmp) / "out", 1, 0)


if __name__ == "__main__":
    unittest.main()
