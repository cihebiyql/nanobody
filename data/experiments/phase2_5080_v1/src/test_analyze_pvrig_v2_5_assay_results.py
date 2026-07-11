from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_pvrig_v2_5_assay_results import AssayContractError, analyze
from build_pvrig_v2_5_assay_execution_package import DEFAULT_PANEL, DEFAULT_TARGET_FASTA, build_package
from freeze_pvrig_v2_5_assay_preregistration import freeze


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PvrigV25AssayResultTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> Path:
        package = root / "package"
        build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, package)
        return package

    def set_lab_parameters(self, package: Path) -> None:
        path = package / "assay_preregistration.json"
        data = json.loads(path.read_text())
        data["lab_parameters_to_freeze_before_first_measurement"] = {
            "minimum_expression_yield_mg_per_l": 0.1,
            "minimum_purity_fraction": 0.8,
            "minimum_sec_monomer_fraction": 0.8,
            "maximum_aggregation_fraction": 0.2,
            "binding_max_analyte_concentration_nM": 1000,
            "binding_response_detection_rule": "scientist-reviewed concentration dependence",
            "binding_fit_qc_rule": "reviewed fit",
            "competition_max_analyte_concentration_nM": 1000,
            "competition_effect_rule": "scientist-reviewed competition curve",
            "functional_max_analyte_concentration_nM": 1000,
            "minimum_functional_viability_fraction": 0.8,
            "functional_effect_rule": "scientist-reviewed reporter curve",
            "functional_viability_rule": "scientist-reviewed viability",
        }
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def freeze_lab_parameters(self, package: Path) -> None:
        self.set_lab_parameters(package)
        freeze(package)

    def raw_evidence(self, package: Path, name: str) -> tuple[str, str]:
        path = package / name
        path.write_text(f"raw evidence for {name}\n")
        return name, sha256_file(path)

    def fill_qc(self, package: Path, sample_id: str, call: str) -> None:
        frame = pd.read_csv(package / "expression_qc_results.csv", keep_default_na=False)
        mask = frame["assay_sample_id"] == sample_id
        raw_path, raw_hash = self.raw_evidence(package, f"raw_qc_{sample_id}.txt")
        frame.loc[mask, "expression_yield_mg_per_l"] = 1.0
        frame.loc[mask, "purity_fraction"] = 0.95
        frame.loc[mask, "sec_monomer_fraction"] = 0.95
        frame.loc[mask, "aggregation_fraction"] = 0.05
        frame.loc[mask, "identity_call"] = "PASS" if call == "PASS" else "FAIL"
        frame.loc[mask, "sequence_sha256_observed"] = frame.loc[mask, "sequence_sha256_expected"].iloc[0]
        frame.loc[mask, "scientist_qc_call"] = call
        frame.loc[mask, "exclusion_reason"] = "expression_failed" if call == "FAIL" else ""
        frame.loc[mask, "raw_data_path"] = raw_path
        frame.loc[mask, "raw_data_sha256"] = raw_hash
        frame.to_csv(package / "expression_qc_results.csv", index=False)

    def fill_stage(self, package: Path, filename: str, sample_id: str, call_column: str, call: str) -> None:
        frame = pd.read_csv(package / filename, keep_default_na=False)
        mask = frame["assay_sample_id"] == sample_id
        frame.loc[mask, "assay_method"] = "BLI" if filename == "binding_results.csv" else "reviewed_assay"
        frame.loc[mask, "analyte_max_concentration_nM"] = 1000
        frame.loc[mask, "fit_qc_call"] = "PASS"
        frame.loc[mask, call_column] = call
        for index in frame.index[mask]:
            run_id = frame.loc[index, "run_id"]
            raw_path, raw_hash = self.raw_evidence(package, f"raw_{filename}_{sample_id}_{run_id}.txt")
            frame.loc[index, "raw_data_path"] = raw_path
            frame.loc[index, "raw_data_sha256"] = raw_hash
        if filename == "binding_results.csv":
            frame.loc[mask, "concentration_dependent_binding_call"] = "PRESENT" if call == "BINDER" else "ABSENT"
            if call == "BINDER":
                frame.loc[mask, "kd_value_M"] = 1e-8
        elif filename == "competition_results.csv" and call == "BLOCKER":
            frame.loc[mask, "verified_binder_eligibility"] = "YES"
            frame.loc[mask, "ic50_value_nM"] = 20
        elif filename == "competition_results.csv":
            frame.loc[mask, "verified_binder_eligibility"] = "YES"
        elif filename == "functional_results.csv" and call == "POSITIVE":
            frame.loc[mask, "verified_blocker_eligibility"] = "YES"
            frame.loc[mask, "viability_fraction"] = 0.95
            frame.loc[mask, "ec50_value_nM"] = 30
        elif filename == "functional_results.csv":
            frame.loc[mask, "verified_blocker_eligibility"] = "YES"
            frame.loc[mask, "viability_fraction"] = 0.95
        frame.to_csv(package / filename, index=False)

    def test_blank_package_is_ready_but_has_no_experimental_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            summary = analyze(package)
            self.assertEqual(summary["measurement_status"], "READY_FOR_LAB_PREREGISTRATION")
            self.assertFalse(summary["preregistration_complete"])
            self.assertEqual(summary["truth_status_counts"], {"PENDING_EXPRESSION_QC": 24})
            self.assertEqual(summary["e6_candidate_row_count"], 0)

    def test_expression_failure_never_becomes_nonbinder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "FAIL")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "NONBINDER")
            summary = analyze(package)
            status = pd.read_csv(package / "candidate_assay_status.csv")
            observed = status.loc[status["assay_sample_id"] == sample_id].iloc[0]
            self.assertEqual(observed["truth_status"], "EXCLUDED_EXPRESSION_OR_QC_FAILURE")
            evidence = pd.read_csv(package / "e6_label_candidates_review.csv")
            self.assertFalse((evidence.get("assay_sample_id", pd.Series(dtype=str)) == sample_id).any())
            self.assertEqual(summary["e6_candidate_row_count"], 0)

    def test_binding_does_not_imply_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
            analyze(package)
            status = pd.read_csv(package / "candidate_assay_status.csv")
            observed = status.loc[status["assay_sample_id"] == sample_id].iloc[0]
            self.assertEqual(observed["binding_status"], "VERIFIED_BINDER")
            self.assertEqual(observed["blocking_status"], "PENDING_COMPETITION")
            self.assertEqual(observed["truth_status"], "VERIFIED_BINDER_COMPETITION_PENDING")
            evidence = pd.read_csv(package / "e6_label_candidates_review.csv")
            sample_evidence = evidence[evidence["assay_sample_id"] == sample_id]
            self.assertEqual(set(sample_evidence["label_axis"]), {"binding"})

    def test_complete_positive_chain_produces_three_review_only_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
            self.fill_stage(package, "competition_results.csv", sample_id, "scientist_blocking_call", "BLOCKER")
            self.fill_stage(package, "functional_results.csv", sample_id, "scientist_functional_call", "POSITIVE")
            analyze(package)
            status = pd.read_csv(package / "candidate_assay_status.csv")
            observed = status.loc[status["assay_sample_id"] == sample_id].iloc[0]
            self.assertEqual(observed["truth_status"], "FUNCTIONAL_BLOCKER_VALIDATED")
            evidence = pd.read_csv(package / "e6_label_candidates_review.csv")
            sample_evidence = evidence[evidence["assay_sample_id"] == sample_id]
            self.assertEqual(set(sample_evidence["label_axis"]), {"binding", "blocking", "functional"})
            self.assertEqual(set(sample_evidence["allowed_use"]), {"PROSPECTIVE_E6_REVIEW_ONLY"})
            self.assertEqual(set(sample_evidence["ordinary_train_allowed"].astype(str)), {"False"})

    def test_completed_call_without_raw_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            frame = pd.read_csv(package / "expression_qc_results.csv", keep_default_na=False)
            frame.loc[0, "scientist_qc_call"] = "FAIL"
            frame.to_csv(package / "expression_qc_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "lacks raw_data_path"):
                analyze(package)

    def test_completed_calls_require_actual_freeze_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.set_lab_parameters(package)
            prereg = package / "assay_preregistration.json"
            manifest_path = package / "package_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            digest = sha256_file(prereg)
            manifest["artifacts"][prereg.name] = digest
            manifest["frozen_artifacts"][prereg.name] = digest
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            with self.assertRaisesRegex(AssayContractError, "freeze command"):
                analyze(package)

    def test_completed_functional_call_requires_positive_max_concentration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
            self.fill_stage(package, "competition_results.csv", sample_id, "scientist_blocking_call", "BLOCKER")
            self.fill_stage(package, "functional_results.csv", sample_id, "scientist_functional_call", "POSITIVE")
            functional = pd.read_csv(package / "functional_results.csv", keep_default_na=False)
            functional.loc[functional["assay_sample_id"] == sample_id, "analyte_max_concentration_nM"] = ""
            functional.to_csv(package / "functional_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "analyte_max_concentration_nM must be numeric"):
                analyze(package)

    def test_completed_functional_call_requires_viability_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
            self.fill_stage(package, "competition_results.csv", sample_id, "scientist_blocking_call", "BLOCKER")
            self.fill_stage(package, "functional_results.csv", sample_id, "scientist_functional_call", "POSITIVE")
            functional = pd.read_csv(package / "functional_results.csv", keep_default_na=False)
            functional.loc[functional["assay_sample_id"] == sample_id, "viability_fraction"] = ""
            functional.to_csv(package / "functional_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "viability_fraction must be numeric"):
                analyze(package)

    def test_functional_inconclusive_requires_complete_measurement_payload(self) -> None:
        cases = (
            ("analyte_max_concentration_nM", "", "analyte_max_concentration_nM must be numeric"),
            ("viability_fraction", "", "viability_fraction must be numeric"),
            ("viability_fraction", "0.5", "failed the preregistered viability gate"),
        )
        for column, value, expected_error in cases:
            with self.subTest(column=column, value=value), tempfile.TemporaryDirectory() as tmp:
                package = self.build_fixture(Path(tmp))
                self.freeze_lab_parameters(package)
                sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
                self.fill_qc(package, sample_id, "PASS")
                self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
                self.fill_stage(package, "competition_results.csv", sample_id, "scientist_blocking_call", "BLOCKER")
                self.fill_stage(
                    package,
                    "functional_results.csv",
                    sample_id,
                    "scientist_functional_call",
                    "INCONCLUSIVE",
                )
                functional = pd.read_csv(package / "functional_results.csv", keep_default_na=False)
                functional.loc[functional["assay_sample_id"] == sample_id, column] = value
                functional.to_csv(package / "functional_results.csv", index=False)
                with self.assertRaisesRegex(AssayContractError, expected_error):
                    analyze(package)

    def test_functional_inconclusive_requires_distinct_raw_data_per_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
            self.fill_stage(package, "competition_results.csv", sample_id, "scientist_blocking_call", "BLOCKER")
            self.fill_stage(
                package,
                "functional_results.csv",
                sample_id,
                "scientist_functional_call",
                "INCONCLUSIVE",
            )
            functional = pd.read_csv(package / "functional_results.csv", keep_default_na=False)
            mask = functional["assay_sample_id"] == sample_id
            first = functional.loc[mask].iloc[0]
            functional.loc[mask, "raw_data_path"] = first["raw_data_path"]
            functional.loc[mask, "raw_data_sha256"] = first["raw_data_sha256"]
            functional.to_csv(package / "functional_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "distinct raw-data files"):
                analyze(package)

    def test_mixed_binding_calls_are_inconclusive_without_e6_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "PASS")
            self.fill_stage(package, "binding_results.csv", sample_id, "scientist_binding_call", "BINDER")
            binding = pd.read_csv(package / "binding_results.csv", keep_default_na=False)
            indices = binding.index[binding["assay_sample_id"] == sample_id]
            binding.loc[indices[-1], "scientist_binding_call"] = "NONBINDER"
            binding.loc[indices[-1], "concentration_dependent_binding_call"] = "ABSENT"
            binding.loc[indices[-1], "kd_value_M"] = ""
            binding.to_csv(package / "binding_results.csv", index=False)
            analyze(package)
            status = pd.read_csv(package / "candidate_assay_status.csv")
            observed = status.loc[status["assay_sample_id"] == sample_id].iloc[0]
            self.assertEqual(observed["truth_status"], "BINDING_INCONCLUSIVE_REMEASURE")
            evidence = pd.read_csv(package / "e6_label_candidates_review.csv")
            self.assertFalse((evidence.get("assay_sample_id", pd.Series(dtype=str)) == sample_id).any())

    def test_raw_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = self.build_fixture(Path(tmp))
            self.freeze_lab_parameters(package)
            sample_id = pd.read_csv(package / "blinding_key.csv").iloc[0]["assay_sample_id"]
            self.fill_qc(package, sample_id, "FAIL")
            qc = pd.read_csv(package / "expression_qc_results.csv", keep_default_na=False)
            qc.loc[qc["assay_sample_id"] == sample_id, "raw_data_sha256"] = "0" * 64
            qc.to_csv(package / "expression_qc_results.csv", index=False)
            with self.assertRaisesRegex(AssayContractError, "hash-mismatched"):
                analyze(package)


if __name__ == "__main__":
    unittest.main()
