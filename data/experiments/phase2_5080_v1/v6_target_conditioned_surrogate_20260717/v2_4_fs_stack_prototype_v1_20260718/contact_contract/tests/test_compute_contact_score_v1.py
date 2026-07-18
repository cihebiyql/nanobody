#!/usr/bin/env python3

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "compute_contact_score_v1.py"
FORMULA_PATH = ROOT / "contact_score_formula_v1.json"
SPEC = importlib.util.spec_from_file_location("compute_contact_score_v1", MODULE_PATH)
assert SPEC and SPEC.loader
contact = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contact
SPEC.loader.exec_module(contact)


class ContactFormulaTests(unittest.TestCase):
    def test_frozen_formula_receipt_is_valid(self):
        formula = contact.load_and_validate_formula(FORMULA_PATH)
        self.assertEqual(formula["weights"], {"hotspot_contact_mass": 0.5, "interface_specificity": 0.5})
        self.assertFalse(formula["outer_result_tuning"])

    def test_exact_equal_weight_scores(self):
        rows = [{
            "candidate_id": "C1",
            "hotspot_contact_mass_R8": "0.8",
            "interface_specificity_R8": "0.4",
            "hotspot_contact_mass_R9": "0.2",
            "interface_specificity_R9": "0.6",
        }]
        output = contact.compute_rows(rows, contact.INPUT_COLUMNS)
        self.assertAlmostEqual(float(output[0]["contact_score_R8"]), 0.6)
        self.assertAlmostEqual(float(output[0]["contact_score_R9"]), 0.4)

    def test_extra_input_column_is_rejected(self):
        with self.assertRaisesRegex(contact.ContactFormulaError, "exact_input_header_mismatch"):
            contact.compute_rows([], (*contact.INPUT_COLUMNS, "outer_result"))

    def test_out_of_range_component_is_rejected(self):
        rows = [{
            "candidate_id": "C1",
            "hotspot_contact_mass_R8": "1.1",
            "interface_specificity_R8": "0.4",
            "hotspot_contact_mass_R9": "0.2",
            "interface_specificity_R9": "0.6",
        }]
        with self.assertRaisesRegex(contact.ContactFormulaError, "input_outside_unit_interval"):
            contact.compute_rows(rows, contact.INPUT_COLUMNS)

    def test_formula_weight_change_is_rejected(self):
        formula = json.loads(FORMULA_PATH.read_text())
        formula["weights"] = {"hotspot_contact_mass": 0.7, "interface_specificity": 0.3}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "formula.json"
            path.write_text(json.dumps(formula))
            with self.assertRaisesRegex(contact.ContactFormulaError, "formula_weights_not_frozen"):
                contact.load_and_validate_formula(path)

    def test_cli_binds_formula_hash(self):
        rows = [{
            "candidate_id": "C1",
            "hotspot_contact_mass_R8": "0.8",
            "interface_specificity_R8": "0.4",
            "hotspot_contact_mass_R9": "0.2",
            "interface_specificity_R9": "0.6",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.tsv"
            with input_path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=contact.INPUT_COLUMNS, delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            receipt = contact.run(contact.argparse.Namespace(
                input_tsv=str(input_path), formula_json=str(FORMULA_PATH),
                output_tsv=str(root / "output.tsv"), receipt_json=str(root / "receipt.json")
            ))
            self.assertEqual(receipt["formula_receipt_sha256"], contact.sha256_file(FORMULA_PATH))


if __name__ == "__main__":
    unittest.main(verbosity=2)
