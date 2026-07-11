from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_pvrig_v2_5_assay_results import AssayContractError, analyze, sha256_file
from build_pvrig_v2_5_assay_execution_package import DEFAULT_PANEL, DEFAULT_TARGET_FASTA, build_package
from freeze_pvrig_v2_5_assay_preregistration import freeze


class FreezePvrigV25AssayPreregistrationTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> Path:
        package = root / "package"
        build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, package)
        return package

    def complete_parameters(self, package: Path) -> None:
        path = package / "assay_preregistration.json"
        data = json.loads(path.read_text())
        data["lab_parameters_to_freeze_before_first_measurement"] = {
            "minimum_expression_yield_mg_per_l": 0.1,
            "minimum_purity_fraction": 0.8,
            "minimum_sec_monomer_fraction": 0.8,
            "maximum_aggregation_fraction": 0.2,
            "binding_max_analyte_concentration_nM": 1000,
            "binding_response_detection_rule": "reviewed response rule",
            "binding_fit_qc_rule": "reviewed fit rule",
            "competition_max_analyte_concentration_nM": 1000,
            "competition_effect_rule": "reviewed inhibition rule",
            "functional_max_analyte_concentration_nM": 1000,
            "minimum_functional_viability_fraction": 0.8,
            "functional_effect_rule": "reviewed response rule",
            "functional_viability_rule": "reviewed viability rule",
        }
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def test_complete_parameters_freeze_before_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.complete_parameters(package)
            manifest = freeze(package)
            self.assertTrue(manifest["preregistration_frozen"])
            self.assertEqual(manifest["status"], "READY_FOR_MEASUREMENT")
            self.assertEqual(
                manifest["frozen_artifacts"]["assay_preregistration.json"],
                sha256_file(package / "assay_preregistration.json"),
            )
            summary = analyze(package)
            self.assertTrue(summary["preregistration_complete"])
            self.assertEqual(summary["measurement_status"], "READY_FOR_MEASUREMENT")

    def test_incomplete_parameters_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            with self.assertRaisesRegex(AssayContractError, "incomplete"):
                freeze(package)

    def test_measurement_call_prevents_late_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.complete_parameters(package)
            qc = pd.read_csv(package / "expression_qc_results.csv", keep_default_na=False)
            qc.loc[0, "scientist_qc_call"] = "FAIL"
            qc.to_csv(package / "expression_qc_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "after any result call"):
                freeze(package)

    def test_pending_call_with_measurement_payload_prevents_late_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.complete_parameters(package)
            qc = pd.read_csv(package / "expression_qc_results.csv", keep_default_na=False)
            qc.loc[0, "expression_yield_mg_per_l"] = 1.0
            qc.loc[0, "raw_data_path"] = "already_measured.csv"
            qc.to_csv(package / "expression_qc_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "template changed before"):
                freeze(package)

    def test_every_required_parameter_key_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self.build_fixture(root)
            self.complete_parameters(package)
            prereg_path = package / "assay_preregistration.json"
            prereg = json.loads(prereg_path.read_text())
            del prereg["lab_parameters_to_freeze_before_first_measurement"]["functional_viability_rule"]
            prereg_path.write_text(json.dumps(prereg, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(AssayContractError, "parameters are missing"):
                freeze(package)


if __name__ == "__main__":
    unittest.main()
