import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("project_phase2_v4_d_open_train_primary_v1.py")
SPEC = importlib.util.spec_from_file_location("projector", MODULE_PATH)
projector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(projector)


FIELDS = [
    "candidate_id", "sequence_sha256", "model_split", "parent_framework_cluster",
    "design_mode", "target_patch_id", "R_dual_min",
]


class ProjectionTests(unittest.TestCase):
    def make_source(self, path: Path) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(226):
                writer.writerow({
                    "candidate_id": f"train_{index:03d}", "sequence_sha256": f"{index:064x}",
                    "model_split": "OPEN_TRAIN", "parent_framework_cluster": f"C{index % 20:04d}",
                    "design_mode": "H3", "target_patch_id": "A_CENTER", "R_dual_min": "0.5",
                })
            for index in range(32):
                writer.writerow({
                    "candidate_id": f"dev_{index:03d}", "sequence_sha256": f"{index + 1000:064x}",
                    "model_split": "OPEN_DEVELOPMENT", "parent_framework_cluster": "SEALED",
                    "design_mode": "SEALED", "target_patch_id": "SEALED",
                    "R_dual_min": "POISON_NOT_PARSED_AS_FLOAT",
                })

    def test_projects_only_train_without_parsing_dev_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, receipt = root / "source.tsv", root / "output.tsv", root / "receipt.json"
            self.make_source(source)
            result = projector.project(source, output, receipt, enforce_hash=False)
            self.assertEqual(result["output_rows"], 226)
            self.assertEqual(result["open_development_target_values_converted"], 0)
            with output.open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 226)
            self.assertEqual({row["model_split"] for row in rows}, {"OPEN_TRAIN"})

    def test_fails_closed_on_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, receipt = root / "source.tsv", root / "output.tsv", root / "receipt.json"
            self.make_source(source)
            output.write_text("existing")
            with self.assertRaisesRegex(projector.ProjectionError, "output_exists"):
                projector.project(source, output, receipt, enforce_hash=False)

    def test_fails_on_nonfinite_train_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, receipt = root / "source.tsv", root / "output.tsv", root / "receipt.json"
            self.make_source(source)
            text = source.read_text().replace("\t0.5\n", "\tnan\n", 1)
            source.write_text(text)
            with self.assertRaisesRegex(projector.ProjectionError, "nonfinite_open_train_target"):
                projector.project(source, output, receipt, enforce_hash=False)


if __name__ == "__main__":
    unittest.main()
