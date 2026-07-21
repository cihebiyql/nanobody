#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "verify_v2_10", HERE / "verify_v2_10_canonical_release.py"
)
VERIFY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = VERIFY
SPEC.loader.exec_module(VERIFY)


FIELDS = [
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster",
    "cdr1", "cdr2", "cdr3", "sample_weight", "R_8X6B", "R_9E6Y",
    "R_dual_min", "teacher_source", "teacher_reliability",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_hash(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.teacher = root / "primary_D1_canonical10644_teacher.tsv"
        self.split = root / "primary_D1_canonical10644_split_manifest.json"
        self.quarantine = root / "joint_cdr3_quarantine.tsv"
        self.receipt = root / "MATERIALIZATION_RECEIPT.json"
        self.sums = root / "SHA256SUMS"
        self.rows = [
            self.row("T1", "C01", "AAAAAAAA", "ACDEFGHIKLMNPQRSTVWYACDEFGHIK"),
            self.row("T2", "C01", "CCCCCCCC", "ACDEFGHIKLMNPQRSTVWYACDEFGHIL"),
            self.row("D1", "C02", "RRRRRRRR", "ACDEFGHIKLMNPQRSTVWYACDEFGHIM"),
            self.row("D2", "C02", "YYYYYYYY", "ACDEFGHIKLMNPQRSTVWYACDEFGHIN"),
        ]
        self.write_all()

    @staticmethod
    def row(candidate: str, parent: str, cdr3: str, sequence: str) -> dict[str, str]:
        # Put the compact test CDRs in the sequence without relying on biological numbering.
        sequence = sequence + cdr3
        return {
            "candidate_id": candidate,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "sequence": sequence,
            "parent_framework_cluster": parent,
            "cdr1": sequence[:4],
            "cdr2": sequence[4:8],
            "cdr3": cdr3,
            "sample_weight": "1",
            "R_8X6B": "0.6",
            "R_9E6Y": "0.5",
            "R_dual_min": "0.5",
            "teacher_source": "TEST",
            "teacher_reliability": "DUAL_1_SEED",
        }

    @staticmethod
    def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def write_all(self) -> None:
        self.write_tsv(self.teacher, self.rows, FIELDS)
        quarantine_sequence = "ACDEFGHIKLMNPQRSTVWYQ"
        self.write_tsv(self.quarantine, [{
            "candidate_id": "Q1",
            "sequence_sha256": hashlib.sha256(quarantine_sequence.encode()).hexdigest(),
            "split_exclusion_reason": "CROSS_SPLIT_CDR3",
        }], ["candidate_id", "sequence_sha256", "split_exclusion_reason"])
        manifest = {
            "schema_version": VERIFY.SPLIT_SCHEMA,
            "data_version": "D1",
            "open_only": True,
            "frozen_test_access_count": 0,
            "sealed_truth_access_count": 0,
            "training_tsv_sha256": sha(self.teacher),
            "train_parents": ["C01"],
            "score_parents": ["C02"],
            "frozen_test_parents": ["C03"],
            "train_parent_set_sha256": set_hash(["C01"]),
            "score_parent_set_sha256": set_hash(["C02"]),
            "frozen_test_parent_set_sha256": set_hash(["C03"]),
            "expected_total_rows": 4,
            "expected_train_rows": 2,
            "expected_score_rows": 2,
        }
        self.split.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        self.receipt.write_text(json.dumps({
            "status": "PASS_TEST_FIXTURE",
            "output_sha256": {
                self.teacher.name: sha(self.teacher),
                self.split.name: sha(self.split),
                self.quarantine.name: sha(self.quarantine),
            },
        }, sort_keys=True) + "\n")
        artifacts = [self.teacher, self.split, self.quarantine, self.receipt]
        self.sums.write_text("".join(f"{sha(path)}  {path.name}\n" for path in artifacts))

    def verify(self):
        return VERIFY.verify_release(
            teacher_tsv=self.teacher,
            split_manifest=self.split,
            quarantine_tsv=self.quarantine,
            receipt_json=self.receipt,
            sha256sums=self.sums,
            expected=VERIFY.ExpectedCounts(2, 2, 4, 1),
        )


class VerifierTests(unittest.TestCase):
    def fixture(self, directory: str) -> Fixture:
        return Fixture(Path(directory))

    def test_valid_release_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            result = fixture.verify()
            self.assertEqual(result["status"], "PASS_V2_10_CANONICAL_OPEN_TEACHER")
            self.assertEqual(result["counts"]["open_total"], 4)

    def test_exact_min_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture.rows[0]["R_dual_min"] = "0.59"
            fixture.write_all()
            with self.assertRaisesRegex(VERIFY.VerificationError, "truth_exact_min"):
                fixture.verify()

    def test_duplicate_sequence_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture.rows[1]["sequence"] = fixture.rows[0]["sequence"]
            fixture.rows[1]["sequence_sha256"] = fixture.rows[0]["sequence_sha256"]
            fixture.rows[1]["cdr1"] = fixture.rows[0]["cdr1"]
            fixture.rows[1]["cdr2"] = fixture.rows[0]["cdr2"]
            fixture.rows[1]["cdr3"] = fixture.rows[0]["cdr3"]
            fixture.write_all()
            with self.assertRaisesRegex(VERIFY.VerificationError, "duplicate_sequence"):
                fixture.verify()

    def test_frozen_parent_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture.rows[0]["parent_framework_cluster"] = "C03"
            fixture.write_all()
            with self.assertRaisesRegex(VERIFY.VerificationError, "frozen_parent_in_teacher"):
                fixture.verify()

    def test_cdr3_hamming80_cross_split_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture.rows[2]["cdr3"] = "AAAAAAAT"  # 7/8 identity with train AAAAAAAA
            fixture.rows[2]["sequence"] = fixture.rows[2]["sequence"][:-8] + "AAAAAAAT"
            fixture.rows[2]["sequence_sha256"] = hashlib.sha256(
                fixture.rows[2]["sequence"].encode()
            ).hexdigest()
            fixture.write_all()
            with self.assertRaisesRegex(VERIFY.VerificationError, "cdr3_hamming80_cross_split"):
                fixture.verify()

    def test_quarantine_reintroduced_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            qrows, _ = VERIFY.load_tsv(fixture.quarantine, "quarantine")
            qrows[0]["candidate_id"] = fixture.rows[0]["candidate_id"]
            fixture.write_tsv(
                fixture.quarantine,
                qrows,
                ["candidate_id", "sequence_sha256", "split_exclusion_reason"],
            )
            # Refresh only the expected receipt/SHA closure so the semantic gate is reached.
            fixture.receipt.write_text(json.dumps({
                "status": "PASS_TEST_FIXTURE",
                "hashes": [sha(fixture.teacher), sha(fixture.split), sha(fixture.quarantine)],
            }) + "\n")
            fixture.sums.write_text("".join(
                f"{sha(path)}  {path.name}\n"
                for path in (fixture.teacher, fixture.split, fixture.quarantine, fixture.receipt)
            ))
            with self.assertRaisesRegex(VERIFY.VerificationError, "quarantine_candidate_in_teacher"):
                fixture.verify()

    def test_sha_closure_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture.teacher.write_text(fixture.teacher.read_text() + "\n")
            with self.assertRaisesRegex(VERIFY.VerificationError, "split_teacher_hash_mismatch"):
                fixture.verify()

    def test_nonpositive_weight_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture.rows[0]["sample_weight"] = "0"
            fixture.write_all()
            with self.assertRaisesRegex(VERIFY.VerificationError, "nonpositive_sample_weight"):
                fixture.verify()


if __name__ == "__main__":
    unittest.main()
