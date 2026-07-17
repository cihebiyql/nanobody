import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("materialize_phase2_v4_h_research1320_sequence_manifest_v1.py")
SPEC = importlib.util.spec_from_file_location("sequence_manifest", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


FIELDS = [
    "candidate_id", "sequence", "sequence_sha256", "sequence_length",
    "research_pool_state", "monomer_structure_eligible", "sequence_repaired",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SequenceManifestTests(unittest.TestCase):
    def source(self, path: Path, count: int = 3, *, bad_hash: bool = False) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(count):
                sequence = "QVQLVESGGGLVQAGGSLRLSCAASG" + "A" * index
                writer.writerow({
                    "candidate_id": f"C{index}", "sequence": sequence,
                    "sequence_sha256": "0" * 64 if bad_hash and index == 0 else hashlib.sha256(sequence.encode()).hexdigest(),
                    "sequence_length": len(sequence), "research_pool_state": "RESEARCH_READY",
                    "monomer_structure_eligible": "true", "sequence_repaired": "false",
                })

    def test_materializes_exact_label_free_sequence_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, receipt = root / "source.tsv", root / "output.csv", root / "receipt.json"
            self.source(source)
            result = module.materialize(source, output, receipt, expected_source_sha256=sha(source), expected_rows=3)
            self.assertEqual(result["row_count"], 3)
            self.assertEqual(result["V4_H_geometry_labels_accessed"], 0)
            with output.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({row["roles"] for row in rows}, {"vhh"})
            self.assertEqual(json.loads(receipt.read_text())["output_sha256"], sha(output))

    def test_fails_on_sequence_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            self.source(source, bad_hash=True)
            with self.assertRaisesRegex(module.MaterializationError, "sequence_sha256_mismatch"):
                module.materialize(source, root / "output.csv", root / "receipt.json", expected_source_sha256=sha(source), expected_rows=3)

    def test_fails_closed_on_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.tsv", root / "output.csv"
            self.source(source)
            output.write_text("existing")
            with self.assertRaisesRegex(module.MaterializationError, "output_exists"):
                module.materialize(source, output, root / "receipt.json", expected_source_sha256=sha(source), expected_rows=3)


if __name__ == "__main__":
    unittest.main()
