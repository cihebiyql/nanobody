from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "data" / "build_v6_training_dataset.py"
SPEC = importlib.util.spec_from_file_location("build_v6_training_dataset", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class V6TrainingDatasetTests(unittest.TestCase):
    def build(self, output_dir: Path) -> dict[str, object]:
        return builder.build_dataset(
            builder.DEFAULT_OPEN_TEACHER,
            builder.DEFAULT_STAGE1_RANKING,
            builder.DEFAULT_STAGE1_METADATA,
            output_dir,
        )

    def test_real_dataset_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            receipt = self.build(output_dir)
            supervised = read_tsv(output_dir / "v6_supervised1507.tsv")
            incomplete = read_tsv(output_dir / "v6_unsupervised_incomplete39.tsv")
            folds = read_tsv(output_dir / "v6_whole_parent_fold_assignments.tsv")

            self.assertEqual(receipt["status"], "COMPLETE_LEAKAGE_CLOSED_V6_DATASET")
            self.assertEqual(len(supervised), 1507)
            self.assertEqual(len(incomplete), 39)
            self.assertEqual(len(folds), 31)
            self.assertEqual(
                {row["campaign"] for row in supervised},
                {"V4_D_OPEN_TRAIN_MULTI_SEED", "V4_H_STAGE1_SEED917"},
            )
            self.assertEqual(
                sum(row["campaign"] == "V4_D_OPEN_TRAIN_MULTI_SEED" for row in supervised),
                226,
            )
            self.assertEqual(
                sum(row["campaign"] == "V4_H_STAGE1_SEED917" for row in supervised),
                1281,
            )
            self.assertEqual({row["reliability_weight"] for row in supervised}, {"1.00", "0.65"})
            self.assertEqual(
                {row["source_dataset"] for row in supervised},
                {
                    "pvrig_v4_d_open_continuous_teacher_v1",
                    "pvrig_v4_h_stage1_terminal_v1_20260717",
                },
            )
            self.assertTrue(all(row["R_8X6B"] and row["R_9E6Y"] and row["R_dual_min"] for row in supervised))
            self.assertEqual(
                {row["supervision_state"] for row in incomplete},
                {"TECHNICALLY_INCOMPLETE_UNSUPERVISED_ONLY"},
            )

    def test_incomplete_schema_has_no_target_or_negative_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            self.build(output_dir)
            incomplete_path = output_dir / "v6_unsupervised_incomplete39.tsv"
            with incomplete_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                self.assertNotIn("R_8X6B", reader.fieldnames or [])
                self.assertNotIn("R_9E6Y", reader.fieldnames or [])
                self.assertNotIn("R_dual_min", reader.fieldnames or [])
                self.assertNotIn("label", reader.fieldnames or [])
                rows = list(reader)
            self.assertTrue(all(row["technical_reasons"] for row in rows))

    def test_whole_parent_folds_and_open_development_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            receipt = self.build(output_dir)
            supervised = read_tsv(output_dir / "v6_supervised1507.tsv")
            fold_sets: dict[str, set[str]] = {}
            for row in supervised:
                fold_sets.setdefault(row["parent_framework_cluster"], set()).add(row["fold_id"])
            self.assertTrue(all(len(values) == 1 for values in fold_sets.values()))
            self.assertEqual(set(row["fold_id"] for row in supervised), {"0", "1", "2", "3", "4"})
            self.assertEqual(receipt["open_development_targets_emitted"], 0)
            self.assertEqual(
                receipt["open_development_overlap"],
                {
                    "candidate_id_overlap": 0,
                    "sequence_sha256_overlap": 0,
                    "parent_framework_cluster_overlap": 0,
                },
            )

    def test_build_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            dir_a, dir_b = Path(tmp_a), Path(tmp_b)
            self.build(dir_a)
            self.build(dir_b)
            for name in (
                "v6_supervised1507.tsv",
                "v6_unsupervised_incomplete39.tsv",
                "v6_whole_parent_fold_assignments.tsv",
            ):
                self.assertEqual((dir_a / name).read_bytes(), (dir_b / name).read_bytes())
            receipt_a = json.loads((dir_a / "V6_DATASET_RECEIPT.json").read_text())
            receipt_b = json.loads((dir_b / "V6_DATASET_RECEIPT.json").read_text())
            for receipt in (receipt_a, receipt_b):
                for output in receipt["outputs"].values():
                    output.pop("path")
            self.assertEqual(receipt_a, receipt_b)

    def test_overlap_and_geometry_contracts_fail_closed(self) -> None:
        supervised = [
            {
                "candidate_id": "candidate-a",
                "sequence_sha256": "sequence-a",
                "parent_framework_cluster": "parent-a",
            }
        ]
        development = [
            {
                "candidate_id": "candidate-b",
                "sequence_sha256": "sequence-b",
                "parent_framework_cluster": "parent-a",
            }
        ]
        with self.assertRaisesRegex(builder.DataContractError, "open_development_overlap"):
            builder.assert_no_overlap(supervised, development)
        with self.assertRaisesRegex(builder.DataContractError, "r_dual_min_mismatch"):
            builder.validate_geometry(
                {"R_8X6B": "0.5", "R_9E6Y": "0.4", "R_dual_min": "0.5"},
                "bad-row",
            )


if __name__ == "__main__":
    unittest.main()
