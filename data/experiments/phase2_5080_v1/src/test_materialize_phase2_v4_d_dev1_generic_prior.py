#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("materialize_phase2_v4_d_dev1_generic_prior.py")
SPEC = importlib.util.spec_from_file_location("materialize_phase2_v4_d_dev1_generic_prior", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable_to_load_generic_prior_materializer")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_inputs(root: Path, *, forbidden_column: bool = False, mismatch_sequence: bool = False) -> tuple[Path, Path]:
    split = root / "split.tsv"
    source = root / "source.csv"
    split_fields = ["candidate_id", "sequence_sha256", "sequence", "model_split"]
    split_rows = []
    for index in range(290):
        sequence = "QVQLVESGGGLVQAGGSLRLSCAASG" + chr(65 + index % 20)
        role = "OPEN_TRAIN" if index < 226 else "OPEN_DEVELOPMENT" if index < 258 else "PROSPECTIVE_COMPUTATIONAL_TEST"
        split_rows.append({
            "candidate_id": f"candidate-{index:03d}",
            "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            "sequence": sequence,
            "model_split": role,
        })
    with split.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=split_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(split_rows)
    source_fields = ["vhh_sequence", *MOD.OUTPUT_FIELDS]
    if forbidden_column:
        source_fields.append("R_dual_min")
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields, lineterminator="\n")
        writer.writeheader()
        for index, split_row in enumerate(split_rows):
            row = {
                "candidate_id": split_row["candidate_id"],
                "sequence_sha256": ("f" * 64 if mismatch_sequence and index == 0 else split_row["sequence_sha256"]),
                "vhh_sequence": split_row["sequence"],
                "generic_binding_prior": "0.7",
                "model_uncertainty": "0.1",
                "model_disagreement": "0.02",
                "generic_binding_prior_seed_43": "0.6",
                "generic_binding_prior_seed_53": "0.7",
                "generic_binding_prior_seed_67": "0.8",
                "generic_binding_model": "label_free_fixture",
                "generic_binding_train_summary_sha256": "a" * 64,
                "target_sequence_sha256": "b" * 64,
                "model_claim_boundary": "not_binding_or_blocking_truth",
            }
            if forbidden_column:
                row["R_dual_min"] = "0.9"
            writer.writerow(row)
    return split, source


class GenericPriorMaterializerTest(unittest.TestCase):
    def test_materializes_exact_label_free_290_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            split, source = make_inputs(root)
            output = root / "output"
            result = MOD.materialize(
                split,
                source,
                output,
                expected_split_sha256=digest(split),
                expected_source_sha256=digest(source),
                expected_source_rows=290,
            )
            self.assertEqual(result["row_count"], 290)
            self.assertEqual(result["test32_metric_values_read"], 0)
            self.assertFalse(result["formal_v4_f_unlock_eligible"])
            with (output / MOD.OUTPUT_BASENAME).open(newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames or ()), MOD.OUTPUT_FIELDS)
            self.assertEqual(len(rows), 290)
            self.assertNotIn("model_split", reader.fieldnames or ())
            audit = json.loads((output / MOD.AUDIT_BASENAME).read_text())
            self.assertEqual(audit["source"]["forbidden_docking_geometry_or_label_columns"], [])
            self.assertEqual(audit["sealed_data_boundary"]["test32_metric_values_read"], 0)
            self.assertTrue(audit["numeric_validation"]["all_numeric_values_finite"])
            self.assertEqual(
                audit["numeric_validation"]["ranges"]["generic_binding_prior"],
                {"min": 0.7, "max": 0.7},
            )

    def test_rejects_any_docking_or_geometry_column_in_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            split, source = make_inputs(root, forbidden_column=True)
            with self.assertRaisesRegex(MOD.GenericPriorError, "forbidden_label_column"):
                MOD.materialize(
                    split,
                    source,
                    root / "output",
                    expected_split_sha256=digest(split),
                    expected_source_sha256=digest(source),
                    expected_source_rows=290,
                )

    def test_rejects_sequence_sha_drift_and_leaves_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            split, source = make_inputs(root, mismatch_sequence=True)
            output = root / "output"
            with self.assertRaisesRegex(MOD.GenericPriorError, "sequence_sha_mismatch"):
                MOD.materialize(
                    split,
                    source,
                    output,
                    expected_split_sha256=digest(split),
                    expected_source_sha256=digest(source),
                    expected_source_rows=290,
                )
            self.assertFalse(output.exists())

    def test_source_contains_no_python_assert(self) -> None:
        self.assertNotRegex(MODULE_PATH.read_text(), r"(?m)^\s*assert\s")


if __name__ == "__main__":
    unittest.main()
