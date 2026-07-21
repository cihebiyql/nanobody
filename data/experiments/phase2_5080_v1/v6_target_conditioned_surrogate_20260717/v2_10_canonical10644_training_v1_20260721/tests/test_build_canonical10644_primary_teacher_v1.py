from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MOD = import_module("v210_builder", ROOT / "src/build_canonical10644_primary_teacher_v1.py")
VERIFY = import_module("v210_independent_verify", ROOT / "tests/verify_v2_10_canonical_release.py")


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str] | tuple[str, ...] | None = None) -> None:
    names = list(fields or rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sequence_fields(candidate: str, parent: str, index: int, cdr3: str) -> dict[str, str]:
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    cdr1 = "ACD" + alphabet[index % 20] + alphabet[(index // 20) % 20]
    cdr2 = "FGH" + alphabet[(index + 4) % 20]
    sequence = "QVQLVESGGGLVQSGGSLRLSCAAS" + cdr1 + "WYRQAPGKERELVA" + cdr2 + "RFTISRDFSRSTMYLQMNSLKPEDTAIYYCAA" + cdr3 + "WGQGTQVTVSS"
    return {
        "candidate_id": candidate,
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        "sequence": sequence,
        "parent_framework_cluster": parent,
        "cdr1": cdr1,
        "cdr2": cdr2,
        "cdr3": cdr3,
    }


def legacy_row(candidate: str, parent: str, index: int, cdr3: str) -> dict[str, str]:
    row = sequence_fields(candidate, parent, index, cdr3)
    row.update({
        "sample_weight": "1",
        "R_8X6B": "0.55",
        "R_9E6Y": "0.50",
        "R_dual_min": "0.50",
        "teacher_source": "LEGACY",
        "teacher_reliability": "MULTI_SEED",
    })
    return row


def canonical_row(
    candidate: str,
    parent: str,
    index: int,
    cdr3: str,
    parent_split: str,
    canonical_split: str,
    status: str = MOD.WEAK_LABEL,
    seed_count: str = "1",
) -> dict[str, str]:
    row = sequence_fields(candidate, parent, index, cdr3)
    open_label = status == MOD.WEAK_LABEL and canonical_split in MOD.OPEN_SPLITS
    row.update({
        "training_label_status": status,
        "parent_only_model_split": parent_split,
        "canonical_model_split": canonical_split,
        "R8_primary_seed917": "0.54" if open_label else "SECRET",
        "R9_primary_seed917": "0.49" if open_label else "SECRET",
        "R_dual_min": "0.49" if open_label else "SECRET",
        "successful_dual_seed_count": seed_count,
    })
    if status == MOD.TECHNICAL_NA:
        row["R8_primary_seed917"] = row["R9_primary_seed917"] = row["R_dual_min"] = ""
    return row


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.legacy = root / "legacy_D0.tsv"
        self.legacy_manifest = root / "legacy_D0_manifest.json"
        self.canonical = root / "canonical_release.tsv"
        self.release_receipt = root / "RELEASE_RECEIPT.json"
        self.output = root / "prepared"
        self.legacy_rows = [
            legacy_row("LT1", "P_LT", 1, "AAAAAAAAAA"),
            legacy_row("LD_QUAR", "P_LD", 2, "AAAAAAAACC"),  # 8/10 with LT1
            legacy_row("LD_KEEP", "P_LD", 3, "RRRRRRRRRR"),
        ]
        self.canonical_rows = [
            canonical_row("CT1", "P_CT", 21, "CCCCCCCCCC", "train", "train", seed_count="3"),
            canonical_row("CD1", "P_CD", 22, "YYYYYYYYYY", "development", "development", seed_count="2"),
            canonical_row("CF1", "P_CF", 23, "NNNNNNNNNN", "frozen_test", "frozen_test"),
            canonical_row("CQ1", "P_CD", 24, "SSSSSSSSSS", "development", "quarantine_cdr3_overlap"),
            canonical_row("CN1", "P_CT", 25, "TTTTTTTTTT", "train", "train", MOD.TECHNICAL_NA),
        ]
        self.write_inputs()

    def write_inputs(self) -> None:
        write_tsv(self.legacy, self.legacy_rows, MOD.OUTPUT_COLUMNS)
        train, dev, frozen = ["P_LT"], ["P_LD"], ["P_CF"]
        self.legacy_manifest.write_text(json.dumps({
            "schema_version": MOD.SPLIT_SCHEMA,
            "data_version": "D0",
            "open_only": True,
            "frozen_test_access_count": 0,
            "sealed_truth_access_count": 0,
            "training_tsv_sha256": MOD.sha256_file(self.legacy),
            "train_parents": train,
            "score_parents": dev,
            "frozen_test_parents": frozen,
            "train_parent_set_sha256": MOD.stable_set_hash(train),
            "score_parent_set_sha256": MOD.stable_set_hash(dev),
            "frozen_test_parent_set_sha256": MOD.stable_set_hash(frozen),
            "expected_total_rows": 3,
            "expected_train_rows": 1,
            "expected_score_rows": 2,
        }))
        write_tsv(self.canonical, self.canonical_rows)
        self.release_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v29_canonical_training_release_v1",
            "status": "PASS_CANONICAL_RELEASE",
            "protocol_core_sha256": "a" * 64,
            "target_contract": {
                "uniform_training_target": "R_dual_min=min(R8_primary_seed917,R9_primary_seed917)"
            },
        }))

    def run(self):
        return MOD.materialize(
            legacy_d0_tsv=self.legacy,
            legacy_d0_sha256=MOD.sha256_file(self.legacy),
            legacy_d0_manifest=self.legacy_manifest,
            legacy_d0_manifest_sha256=MOD.sha256_file(self.legacy_manifest),
            canonical_tsv=self.canonical,
            canonical_tsv_sha256=MOD.sha256_file(self.canonical),
            canonical_release_receipt=self.release_receipt,
            canonical_release_receipt_sha256=MOD.sha256_file(self.release_receipt),
            output_dir=self.output,
            split_id="fixture_v210",
            expected_raw_union=5,
            expected_train=2,
            expected_development=2,
            expected_final=4,
            expected_new_quarantine=1,
        )


class CanonicalBuilderTests(unittest.TestCase):
    def test_materialization_and_independent_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            receipt = fixture.run()
            self.assertEqual(receipt["counts"]["pre_joint_graph_union_rows"], 5)
            self.assertEqual(receipt["counts"]["new_joint_cdr3_quarantine_rows"], 1)
            self.assertEqual(receipt["canonical_access_audit"]["numeric_parse_frozen_test"], 0)
            with (fixture.output / "joint_cdr3_quarantine.tsv").open() as handle:
                qrows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(qrows[0]["candidate_id"], "LD_QUAR")
            result = VERIFY.verify_release(
                teacher_tsv=fixture.output / "primary_D1_canonical10644_teacher.tsv",
                split_manifest=fixture.output / "primary_D1_canonical10644_split_manifest.json",
                quarantine_tsv=fixture.output / "joint_cdr3_quarantine.tsv",
                receipt_json=fixture.output / "MATERIALIZATION_RECEIPT.json",
                sha256sums=fixture.output / "SHA256SUMS",
                expected=VERIFY.ExpectedCounts(2, 2, 4, 1),
            )
            self.assertEqual(result["status"], "PASS_V2_10_CANONICAL_OPEN_TEACHER")

    def test_nonopen_secret_targets_are_never_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            rows, audit = MOD.load_canonical_open(fixture.canonical)
            self.assertEqual(len(rows), 2)
            self.assertEqual(audit["numeric_parse_by_split"], {"development": 1, "train": 1})
            self.assertEqual(audit["numeric_parse_frozen_test"], 0)
            self.assertEqual(audit["numeric_parse_quarantine"], 0)

    def test_technical_na_numeric_imputation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            fixture.canonical_rows[-1]["R8_primary_seed917"] = "0"
            fixture.write_inputs()
            with self.assertRaisesRegex(RuntimeError, "technical_na_numeric_imputation:CN1"):
                fixture.run()
            self.assertFalse(fixture.output.exists())

    def test_cross_source_sequence_overlap_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            for key in ("sequence", "sequence_sha256", "cdr1", "cdr2", "cdr3"):
                fixture.canonical_rows[0][key] = fixture.legacy_rows[0][key]
            fixture.write_inputs()
            with self.assertRaisesRegex(RuntimeError, "cross_source_sequence_overlap"):
                fixture.run()

    def test_release_receipt_target_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            payload = json.loads(fixture.release_receipt.read_text())
            payload["target_contract"]["uniform_training_target"] = "wrong"
            fixture.release_receipt.write_text(json.dumps(payload))
            with self.assertRaisesRegex(RuntimeError, "release_target_contract"):
                fixture.run()

    def test_expected_quarantine_count_is_not_silently_hardcoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            fixture.legacy_rows[1] = legacy_row("LD_QUAR", "P_LD", 2, "GGGGGGGGGG")
            fixture.write_inputs()
            with self.assertRaisesRegex(RuntimeError, "development_rows_mismatch:3"):
                fixture.run()


if __name__ == "__main__":
    unittest.main()
