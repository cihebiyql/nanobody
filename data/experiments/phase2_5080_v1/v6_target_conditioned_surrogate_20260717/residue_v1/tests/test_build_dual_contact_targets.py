import csv
import gzip
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "build_dual_contact_targets.py"
spec = importlib.util.spec_from_file_location("build_dual_contact_targets", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestDualContactTargetBuilder(unittest.TestCase):
    def write_fixture(self, root: pathlib.Path, missing_receptor: bool = False):
        training = root / "training.tsv"
        sequences = {"C1": "ACDE", "C2": "FGHI"}
        with training.open("w", newline="", encoding="utf-8") as handle:
            fields = ["candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, (candidate, sequence) in enumerate(sequences.items()):
                writer.writerow({
                    "candidate_id": candidate,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                    "sequence": sequence,
                    "parent_framework_cluster": f"P{index}",
                })
        pair = root / "pair.tsv.gz"
        fields = sorted(mod.PAIR_REQUIRED)
        with gzip.open(pair, "wt", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, (candidate, sequence) in enumerate(sequences.items()):
                for receptor in mod.RECEPTORS:
                    if missing_receptor and candidate == "C2" and receptor == "9e6y":
                        continue
                    for pvrig, frequency in ((92, 0.2), (95, 0.7)):
                        writer.writerow({
                            "teacher_state": "VALID_DUAL_1_SEED_CONTACT",
                            "candidate_id": candidate,
                            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                            "parent_framework_cluster": f"P{index}",
                            "receptor": receptor,
                            "vhh_sequence_index": 2,
                            "vhh_aa": sequence[1],
                            "pvrig_uniprot_position": pvrig,
                            "contact_frequency_pose_weighted": frequency if receptor == "8x6b" else frequency / 2,
                        })
        return training, pair

    def test_deterministic_max_aggregation_and_zero_fill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, pair = self.write_fixture(root)
            first = mod.build_targets(training, pair, root / "out1", expected_candidates=2)
            second = mod.build_targets(training, pair, root / "out2", expected_candidates=2)
            self.assertEqual(first["output"]["sha256"], second["output"]["sha256"])
            self.assertEqual(first["counts"]["target_rows"], 8)
            with gzip.open(root / "out1" / mod.OUTPUT_NAME, "rt", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            c1_second = next(row for row in rows if row["candidate_id"] == "C1" and row["vhh_sequence_index"] == "2")
            c1_first = next(row for row in rows if row["candidate_id"] == "C1" and row["vhh_sequence_index"] == "1")
            self.assertAlmostEqual(float(c1_second["contact_target_8x6b"]), 0.7)
            self.assertAlmostEqual(float(c1_second["contact_target_9e6y"]), 0.35)
            self.assertEqual(float(c1_first["contact_target_8x6b"]), 0.0)
            receipt = json.loads((root / "out1" / mod.RECEIPT_NAME).read_text())
            self.assertEqual(receipt["status"], "PASS_DUAL_CONTACT_TARGETS_MATERIALIZED")

    def test_missing_receptor_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, pair = self.write_fixture(root, missing_receptor=True)
            with self.assertRaisesRegex(mod.ContactTargetError, "candidate_missing_receptor"):
                mod.build_targets(training, pair, root / "out", expected_candidates=2)


if __name__ == "__main__":
    unittest.main()

