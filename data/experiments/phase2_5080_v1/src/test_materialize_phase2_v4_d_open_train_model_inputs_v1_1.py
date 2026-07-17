import csv
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("materialize_phase2_v4_d_open_train_model_inputs_v1_1.py")
SPEC = importlib.util.spec_from_file_location("materializer", MODULE_PATH)
materializer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(materializer)


SOURCE_FIELDS = [
    "candidate_id", "sequence", "sequence_sha256", "model_split",
    "parent_framework_cluster", "design_mode", "target_patch_id", "R_dual_min",
]


class MaterializerTests(unittest.TestCase):
    def make_source(self, path: Path, bad_target: bool = False) -> None:
        sequence = "QVQLVESGGGLVQAGGSLRLSCAASG"
        sequence_sha = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(226):
                seq = sequence + "A" * index
                writer.writerow({
                    "candidate_id": f"train_{index:03d}", "sequence": seq,
                    "sequence_sha256": hashlib.sha256(seq.encode("ascii")).hexdigest(),
                    "model_split": "OPEN_TRAIN", "parent_framework_cluster": f"C{index % 20:04d}",
                    "design_mode": "H3", "target_patch_id": "A_CENTER",
                    "R_dual_min": "nan" if bad_target and index == 0 else "0.5",
                })
            for index in range(32):
                writer.writerow({
                    "candidate_id": f"dev_{index:03d}", "sequence": "SEALED_DEV_NOT_EMITTED",
                    "sequence_sha256": sequence_sha, "model_split": "OPEN_DEVELOPMENT",
                    "parent_framework_cluster": "SEALED", "design_mode": "SEALED",
                    "target_patch_id": "SEALED", "R_dual_min": "POISON_NOT_CONVERTED",
                })

    def test_materializes_closed_train_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, labels, sequences, receipt = (root / name for name in ("source.tsv", "labels.tsv", "sequences.csv", "receipt.json"))
            self.make_source(source)
            result = materializer.materialize(source, labels, sequences, receipt, enforce_hash=False)
            self.assertEqual(result["rows"], 226)
            self.assertEqual(result["V4_F_test32_sequences_accessed"], 0)
            with labels.open(newline="") as handle:
                label_rows = list(csv.DictReader(handle, delimiter="\t"))
            with sequences.open(newline="") as handle:
                sequence_rows = list(csv.DictReader(handle))
            self.assertEqual(len(label_rows), len(sequence_rows), 226)
            self.assertNotIn("SEALED_DEV_NOT_EMITTED", sequences.read_text())

    def test_fails_on_nonfinite_train_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, labels, sequences, receipt = (root / name for name in ("source.tsv", "labels.tsv", "sequences.csv", "receipt.json"))
            self.make_source(source, bad_target=True)
            with self.assertRaisesRegex(materializer.MaterializationError, "nonfinite_open_train_target"):
                materializer.materialize(source, labels, sequences, receipt, enforce_hash=False)

    def test_fails_closed_on_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, labels, sequences, receipt = (root / name for name in ("source.tsv", "labels.tsv", "sequences.csv", "receipt.json"))
            self.make_source(source)
            labels.write_text("exists")
            with self.assertRaisesRegex(materializer.MaterializationError, "output_exists"):
                materializer.materialize(source, labels, sequences, receipt, enforce_hash=False)


if __name__ == "__main__":
    unittest.main()
