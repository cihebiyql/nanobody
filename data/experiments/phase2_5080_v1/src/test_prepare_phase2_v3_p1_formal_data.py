import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_phase2_v3_p1_formal_data.py")
SPEC = importlib.util.spec_from_file_location("formal_data", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class FormalDataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        rows = []
        manifest = []
        contacts = []
        for index, split in enumerate(("train", "train", "dev", "test")):
            candidate_id = f"c{index}"
            sequence = "A" * (10 + index)
            sha = hashlib.sha256(sequence.encode()).hexdigest()
            row = {
                "candidate_id": candidate_id, "sequence": sequence, "sequence_sha256": sha,
                "formal_split": split, "parent_framework_cluster": f"pc{index}",
                "generic_binding_prior": "0.5", "provisional_stable_geometry_tier": f"G{index + 1}",
                "teacher_completeness": "COMPLETE",
            }
            row.update({field: "1" for field in MOD.LABEL_FIELDS if field != "provisional_stable_geometry_tier"})
            row.update({"pose_count": "4", "valid_baseline_pair_count": "4",
                        "valid_contact_pose_count": "4", "failed_contact_pose_count": "0"})
            rows.append(row)
            manifest.append({"candidate_id": candidate_id, "vhh_sequence": sequence, "sequence_sha256": sha,
                             "formal_split": split, "parent_framework_cluster": f"pc{index}"})
            contacts.append({"candidate_id": candidate_id, "sequence": sequence, "sequence_sha256": sha,
                             "pair_frequencies": []})
        write_csv(self.root / "candidates.csv", rows)
        write_csv(self.root / "manifest.csv", manifest)
        (self.root / "contacts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in contacts))
        output_hashes = {
            str(path.resolve()): MOD.sha256_file(path)
            for path in (self.root / "candidates.csv", self.root / "contacts.jsonl", self.root / "manifest.csv")
        }
        (self.root / "upstream.json").write_text(json.dumps({
            "status": "PASS_FORMAL_TEACHER500_READY", "output_sha256": output_hashes,
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_seals_test_labels_and_preserves_parent_isolation(self):
        audit = MOD.prepare(
            self.root / "candidates.csv", self.root / "contacts.jsonl", self.root / "manifest.csv",
            self.root / "out", self.root / "audit.json", self.root / "upstream.json", expected_candidates=4,
            expected_splits={"train": 2, "dev": 1, "test": 1},
        )
        self.assertEqual(audit["status"], "PASS_PHASE2_V3_P1_FORMAL_DATA_SEALED")
        with (self.root / "out/pvrig_teacher_formal_blinded_v1.csv").open(newline="") as handle:
            blinded = list(csv.DictReader(handle))
        self.assertEqual(len(blinded), 1)
        self.assertNotIn("teacher_relevance_mean", blinded[0])
        with (self.root / "out/pvrig_teacher_formal_labels_sealed_v1.csv").open(newline="") as handle:
            labels = list(csv.DictReader(handle))
        self.assertEqual(labels[0]["sealed_status"], "SEALED_FORMAL_TEST_LABEL")
        self.assertEqual(labels[0]["sequence_sha256"], blinded[0]["sequence_sha256"])

    def test_rejects_parent_cluster_leakage(self):
        rows = MOD.read_csv(self.root / "manifest.csv")
        rows[-1]["parent_framework_cluster"] = rows[0]["parent_framework_cluster"]
        write_csv(self.root / "manifest.csv", rows)
        upstream = json.loads((self.root / "upstream.json").read_text())
        upstream["output_sha256"][str((self.root / "manifest.csv").resolve())] = MOD.sha256_file(
            self.root / "manifest.csv"
        )
        (self.root / "upstream.json").write_text(json.dumps(upstream))
        with self.assertRaisesRegex(ValueError, "Parent-cluster"):
            MOD.prepare(
                self.root / "candidates.csv", self.root / "contacts.jsonl", self.root / "manifest.csv",
                self.root / "out", self.root / "audit.json", self.root / "upstream.json", expected_candidates=4,
                expected_splits={"train": 2, "dev": 1, "test": 1},
            )

    def test_rejects_nonpass_upstream_audit(self):
        upstream = json.loads((self.root / "upstream.json").read_text())
        upstream["status"] = "FAIL_INCOMPLETE"
        (self.root / "upstream.json").write_text(json.dumps(upstream))
        with self.assertRaisesRegex(ValueError, "upstream audit is not PASS"):
            MOD.prepare(
                self.root / "candidates.csv", self.root / "contacts.jsonl", self.root / "manifest.csv",
                self.root / "out", self.root / "audit.json", self.root / "upstream.json", expected_candidates=4,
                expected_splits={"train": 2, "dev": 1, "test": 1},
            )

    def test_rejects_contact_sequence_hash_mismatch(self):
        contacts = MOD.read_jsonl(self.root / "contacts.jsonl")
        contacts[0]["sequence_sha256"] = "0" * 64
        (self.root / "contacts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in contacts))
        upstream = json.loads((self.root / "upstream.json").read_text())
        upstream["output_sha256"][str((self.root / "contacts.jsonl").resolve())] = MOD.sha256_file(
            self.root / "contacts.jsonl"
        )
        (self.root / "upstream.json").write_text(json.dumps(upstream))
        with self.assertRaisesRegex(ValueError, "Contact sequence/hash mismatch"):
            MOD.prepare(
                self.root / "candidates.csv", self.root / "contacts.jsonl", self.root / "manifest.csv",
                self.root / "out", self.root / "audit.json", self.root / "upstream.json", expected_candidates=4,
                expected_splits={"train": 2, "dev": 1, "test": 1},
            )


if __name__ == "__main__":
    unittest.main()
