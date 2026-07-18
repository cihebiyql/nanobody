from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "src" / "build_dual_contact_targets_v2.py"
SPEC = importlib.util.spec_from_file_location("build_dual_contact_targets_v2", MODULE)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]], *, compressed: bool) -> None:
    handle = gzip.open(path, "wt", encoding="utf-8", newline="") if compressed else path.open(
        "w", encoding="utf-8", newline=""
    )
    with handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class DualSourceTargetBuilderTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        training = root / "training.tsv"
        training_rows = [
            {
                "candidate_id": "D1", "sequence": "ACD", "sequence_sha256": sequence_hash("ACD"),
                "parent_framework_cluster": "PD", "teacher_source": "V4D_OPEN_MULTI_SEED",
            },
            {
                "candidate_id": "H1", "sequence": "FGH", "sequence_sha256": sequence_hash("FGH"),
                "parent_framework_cluster": "PH", "teacher_source": "V4H_STAGE1_SEED917",
            },
        ]
        write_tsv(training, list(training_rows[0]), training_rows, compressed=False)

        v4d = root / "v4d_marginal.tsv.gz"
        v4d_rows: list[dict[str, object]] = []
        for receptor, scale in (("8x6b", 1.0), ("9e6y", 0.5)):
            for index, aa in enumerate("ACD", start=1):
                v4d_rows.append({
                    "candidate_id": "D1", "sequence_sha256": sequence_hash("ACD"),
                    "parent_framework_cluster": "PD", "receptor": receptor,
                    "vhh_sequence_index": index, "vhh_aa": aa,
                    "contact_marginal_mean": 0.2 * index * scale,
                    "contact_marginal_variance": 0.01 * index,
                    "contact_marginal_uncertainty_weight": 1.0 / (1.0 + 0.04 * index),
                    "observed_seed_count": 3, "expected_seed_count": 3,
                })
        write_tsv(v4d, list(v4d_rows[0]), v4d_rows, compressed=True)

        v4h = root / "v4h_pairs.tsv.gz"
        v4h_rows = []
        for receptor, scale in (("8x6b", 1.0), ("9e6y", 0.5)):
            for position, value in ((92, 0.2), (95, 0.7)):
                v4h_rows.append({
                    "teacher_state": "VALID_DUAL_1_SEED_CONTACT", "candidate_id": "H1",
                    "sequence_sha256": sequence_hash("FGH"), "parent_framework_cluster": "PH",
                    "receptor": receptor, "vhh_sequence_index": 2, "vhh_aa": "G",
                    "pvrig_uniprot_position": position,
                    "contact_frequency_pose_weighted": value * scale,
                })
        write_tsv(v4h, list(v4h_rows[0]), v4h_rows, compressed=True)
        return training, v4d, v4h

    def test_builds_exact_v4d_marginals_and_v4h_compatibility_marginals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            training, v4d, v4h = self.fixture(root)
            receipt = MOD.build_targets(
                training, v4d, v4h, root / "out",
                expected_source_counts={"V4D_OPEN_MULTI_SEED": 1, "V4H_STAGE1_SEED917": 1},
            )
            self.assertEqual(receipt["counts"]["target_candidates"], 2)
            self.assertEqual(receipt["counts"]["target_rows"], 6)
            with gzip.open(root / "out" / MOD.OUTPUT_NAME, "rt", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            d1 = next(row for row in rows if row["candidate_id"] == "D1" and row["vhh_sequence_index"] == "3")
            h1 = next(row for row in rows if row["candidate_id"] == "H1" and row["vhh_sequence_index"] == "2")
            h1_zero = next(row for row in rows if row["candidate_id"] == "H1" and row["vhh_sequence_index"] == "1")
            self.assertAlmostEqual(float(d1["contact_target_8x6b"]), 0.6)
            self.assertEqual(d1["aggregation_8x6b"], "pose_any_contact_then_seed_mean")
            self.assertAlmostEqual(float(h1["contact_target_8x6b"]), 0.7)
            self.assertEqual(h1["aggregation_8x6b"], "max_pair_frequency_compatibility")
            self.assertEqual(float(h1_zero["contact_target_8x6b"]), 0.0)
            self.assertEqual(float(h1["contact_uncertainty_weight_8x6b"]), 1.0)
            self.assertEqual(d1["observed_seed_count_8x6b"], "3")

    def test_source_or_receptor_omission_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            training, v4d, v4h = self.fixture(root)
            with gzip.open(v4d, "rt", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
                fields = list(rows[0])
            rows = [row for row in rows if row["receptor"] != "9e6y"]
            write_tsv(v4d, fields, rows, compressed=True)
            with self.assertRaisesRegex(MOD.ContactTargetError, "v4d_candidate_missing_receptor"):
                MOD.build_targets(
                    training, v4d, v4h, root / "out",
                    expected_source_counts={"V4D_OPEN_MULTI_SEED": 1, "V4H_STAGE1_SEED917": 1},
                )

    def test_source_indicator_is_audit_only_and_sealed_sources_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            training, v4d, v4h = self.fixture(root)
            with training.open("a", encoding="utf-8") as handle:
                handle.write(
                    "X\tAAA\t" + sequence_hash("AAA") + "\tPX\tPROSPECTIVE_COMPUTATIONAL_TEST\n"
                )
            with self.assertRaisesRegex(MOD.ContactTargetError, "training_source_forbidden"):
                MOD.build_targets(
                    training, v4d, v4h, root / "out",
                    expected_source_counts={"V4D_OPEN_MULTI_SEED": 1, "V4H_STAGE1_SEED917": 1},
                )

    def test_receipt_is_deterministic_and_bound_to_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            training, v4d, v4h = self.fixture(root)
            first = MOD.build_targets(
                training, v4d, v4h, root / "a",
                expected_source_counts={"V4D_OPEN_MULTI_SEED": 1, "V4H_STAGE1_SEED917": 1},
            )
            second = MOD.build_targets(
                training, v4d, v4h, root / "b",
                expected_source_counts={"V4D_OPEN_MULTI_SEED": 1, "V4H_STAGE1_SEED917": 1},
            )
            self.assertEqual(first["output"]["sha256"], second["output"]["sha256"])
            stored = json.loads((root / "a" / MOD.RECEIPT_NAME).read_text(encoding="utf-8"))
            self.assertEqual(stored["status"], "PASS_DUAL_SOURCE_CONTACT_TARGETS_V2")
            self.assertFalse(stored["teacher_source_is_model_feature"])


if __name__ == "__main__":
    unittest.main()
