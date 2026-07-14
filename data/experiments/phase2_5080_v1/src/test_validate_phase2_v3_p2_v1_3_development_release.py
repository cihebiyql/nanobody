#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from experiments.phase2_5080_v1.src import (
    calibrate_phase2_v3_p2_v1_3_dual_native as calibration,
)
from experiments.phase2_5080_v1.src import (
    validate_phase2_v3_p2_v1_3_development_release as validator,
)
from experiments.phase2_5080_v1.src.test_calibrate_phase2_v3_p2_v1_3_dual_native import (
    V13SyntheticFixture,
)


class V13DevelopmentReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        inputs = cls.root / "inputs"
        inputs.mkdir()
        cls.fixture = V13SyntheticFixture(inputs)
        cls.primary_root = cls.root / "calibration_primary"
        cls.rebuild_root = cls.root / "calibration_rebuild"
        calibration.build_calibration(cls._calibration_config(cls.primary_root))
        calibration.build_calibration(cls._calibration_config(cls.rebuild_root))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def _calibration_config(cls, outdir: Path) -> calibration.CalibrationConfig:
        fixture = cls.fixture
        return calibration.CalibrationConfig(
            metrics_csv=fixture.metrics_csv,
            processor_audit=fixture.processor_audit,
            processor_qualification=fixture.processor_qualification,
            selector_csv=fixture.selector_csv,
            selector_audit=fixture.selector_audit,
            execution_release=fixture.execution_release,
            case_manifest=fixture.case_manifest,
            run_manifest=fixture.run_manifest,
            protocol_manifest=fixture.protocol_manifest,
            references=fixture.references,
            preregistration=fixture.preregistration,
            positive_manifest=fixture.positive_manifest,
            mutant_manifest=fixture.mutant_manifest,
            outdir=outdir,
            report=outdir / "current" / calibration.REPORT_NAME,
            bootstrap_seed=calibration.BOOTSTRAP_SEED,
            bootstrap_replicates=calibration.BOOTSTRAP_REPLICATES,
        )

    def _config(
        self,
        outdir: Path,
        primary_root: Path | None = None,
        rebuild_root: Path | None = None,
    ) -> validator.ReleaseConfig:
        fixture = self.fixture
        primary_root = primary_root or self.primary_root
        rebuild_root = rebuild_root or self.rebuild_root
        return validator.ReleaseConfig(
            primary_release_input=(
                primary_root / "current" / calibration.RELEASE_INPUT_NAME
            ),
            rebuild_release_input=(
                rebuild_root / "current" / calibration.RELEASE_INPUT_NAME
            ),
            preregistration=fixture.preregistration,
            anchor_readiness=validator.DEFAULT_ANCHOR_READINESS,
            execution_release=fixture.execution_release,
            case_manifest=fixture.case_manifest,
            run_manifest=fixture.run_manifest,
            protocol_manifest=fixture.protocol_manifest,
            selector_csv=fixture.selector_csv,
            selector_audit=fixture.selector_audit,
            metrics_csv=fixture.metrics_csv,
            processor_audit=fixture.processor_audit,
            processor_qualification=fixture.processor_qualification,
            positive_manifest=fixture.positive_manifest,
            mutant_manifest=fixture.mutant_manifest,
            calibrator=Path(calibration.__file__).resolve(),
            calibrator_test=calibration.DEFAULT_CALIBRATOR_TEST,
            outdir=outdir,
        )

    def _clone_root(self, source: Path, name: str) -> Path:
        target = self.root / name
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target, symlinks=True)
        return target

    def _convert_publication_to_consistent_bootstrap_failure(
        self, root: Path
    ) -> None:
        release = (root / "current").resolve()
        dual_name = "pvrig_v1_3_bootstrap_dual_anchor_evaluations.csv"
        dual_path = release / dual_name
        with dual_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        hash_field = "bootstrap_dual_row_sha256"
        for row in rows:
            row["native_class_8X6B"] = "E"
            row["native_class_9E6Y"] = "E"
            row["dual_tier"] = "G5"
            row["assigned_tier_support_fraction"] = "0"
            row["assigned_tier_supporting_pose_count"] = "0"
            row["class_ordinal_gap"] = "0"
            row["both_native_non_E"] = "false"
            row[hash_field] = validator.sha256_json(
                {key: value for key, value in row.items() if key != hash_field}
            )
        with dual_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        rules_path = release / calibration.RULES_NAME
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        rules["development_method_passed"] = False
        rules["computed_gate_outcome"] = "COMPUTED_GATES_NOT_SATISFIED"
        calibration.write_json(rules_path, rules)

        audit_path = release / calibration.AUDIT_NAME
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        dual_binding = {
            "sha256": validator.sha256_file(dual_path),
            "rows": len(rows),
            "row_hash_chain": validator.row_hash_chain(rows, hash_field),
        }
        audit["output_sha256"][dual_name] = dual_binding
        audit["output_sha256"][calibration.RULES_NAME] = {
            "sha256": validator.sha256_file(rules_path)
        }
        audit["development_method_passed"] = False
        audit["computed_gate_outcome"] = "COMPUTED_GATES_NOT_SATISFIED"
        audit["acceptance_summary"]["development_method_passed"] = False
        audit["acceptance_summary"]["computed_gate_outcome"] = (
            "COMPUTED_GATES_NOT_SATISFIED"
        )
        audit["acceptance_summary"]["gates"]["bootstrap"]["passed"] = False
        audit["acceptance_summary"]["gates"]["receptor_consistency"][
            "passed"
        ] = False
        audit["bootstrap"]["summary"]["passed"] = False
        audit["bootstrap"]["summary"][
            "family_G1_G3_retention_gate_passed"
        ] = False
        audit["bootstrap"]["summary"][
            "family_both_native_non_E_gate_passed"
        ] = False
        calibration.write_json(audit_path, audit)

        input_path = release / calibration.RELEASE_INPUT_NAME
        release_input = json.loads(input_path.read_text(encoding="utf-8"))
        release_input["computed_gate_outcome"] = "COMPUTED_GATES_NOT_SATISFIED"
        release_input["output_sha256"] = copy.deepcopy(audit["output_sha256"])
        release_input["calibration_audit"]["sha256"] = validator.sha256_file(
            audit_path
        )
        calibration.write_json(input_path, release_input)

    def test_full_B2000_pair_is_revalidated_and_only_validator_emits_pass(self) -> None:
        outdir = self.root / "development_pass"
        payload = validator.validate_and_publish(self._config(outdir))
        self.assertEqual(payload["status"], validator.PASS_STATUS)
        self.assertTrue(payload["development_method_passed"])
        self.assertTrue(payload["development_smoke_eligible"])
        self.assertFalse(payload["formal_eligible"])
        self.assertFalse(payload["docking_gold_release_eligible"])
        self.assertFalse(payload["training_label_release_eligible"])
        self.assertFalse(payload["p2_training_ready"])
        self.assertEqual(
            payload["anchor_readiness"]["new_eligible_independent_family_count"],
            0,
        )
        self.assertTrue(payload["gate_revalidation"]["all_gates_passed"])
        self.assertEqual(
            payload["determinism"]["bootstrap_threshold_rows"], 20000
        )
        self.assertEqual(
            payload["determinism"]["bootstrap_receptor_anchor_rows"], 44000
        )
        self.assertEqual(
            payload["determinism"]["bootstrap_dual_anchor_rows"], 22000
        )
        current = outdir / "current"
        self.assertTrue(current.is_symlink())
        observed = json.loads(
            (current / validator.RELEASE_NAME).read_text(encoding="utf-8")
        )
        self.assertEqual(observed, payload)
        for source_root in (self.primary_root, self.rebuild_root):
            source_bytes = b"".join(
                path.read_bytes()
                for path in (source_root / "current").resolve().iterdir()
                if path.is_file()
            )
            self.assertNotIn(validator.PASS_STATUS.encode("ascii"), source_bytes)

    def test_self_sign_and_same_publication_cannot_unlock_smoke(self) -> None:
        primary = self._clone_root(self.primary_root, "self_sign_primary")
        release = (primary / "current").resolve()
        (release / "self_signed_release.json").write_text(
            json.dumps(
                {
                    "status": validator.PASS_STATUS,
                    "development_smoke_eligible": True,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(validator.ReleaseError, "inventory mismatch"):
            validator.validate_and_publish(
                self._config(self.root / "never_self_sign", primary, self.rebuild_root)
            )

        same = self._config(
            self.root / "never_same",
            self.primary_root,
            self.primary_root,
        )
        with self.assertRaisesRegex(validator.ReleaseError, "distinct roots"):
            validator.validate_and_publish(same)

    def test_row_tamper_and_independent_byte_drift_fail_closed(self) -> None:
        tampered = self._clone_root(self.rebuild_root, "row_tamper_rebuild")
        pose_path = (
            (tampered / "current").resolve()
            / "pvrig_v1_3_native_pose_scores.csv"
        )
        text = pose_path.read_text(encoding="utf-8")
        pose_path.write_text(text.replace("8X6B", "9E6Y", 1), encoding="utf-8")
        with self.assertRaises(validator.ReleaseError):
            validator.validate_and_publish(
                self._config(self.root / "never_tamper", self.primary_root, tampered)
            )

        drifted = self._clone_root(self.rebuild_root, "byte_drift_rebuild")
        release = (drifted / "current").resolve()
        report_path = release / calibration.REPORT_NAME
        report_path.write_text(
            report_path.read_text(encoding="utf-8") + "\nsynthetic independent drift\n",
            encoding="utf-8",
        )
        audit_path = release / calibration.AUDIT_NAME
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["report"]["sha256"] = validator.sha256_file(report_path)
        calibration.write_json(audit_path, audit)
        input_path = release / calibration.RELEASE_INPUT_NAME
        release_input = json.loads(input_path.read_text(encoding="utf-8"))
        release_input["calibration_audit"]["sha256"] = validator.sha256_file(
            audit_path
        )
        calibration.write_json(input_path, release_input)
        with self.assertRaisesRegex(
            validator.ReleaseError, "inventories differ|output bytes differ"
        ):
            validator.validate_and_publish(
                self._config(self.root / "never_drift", self.primary_root, drifted)
            )

    def test_claimed_gate_tamper_is_not_a_legitimate_failure_release(self) -> None:
        first = self._clone_root(self.primary_root, "gate_tamper_primary")
        second = self._clone_root(self.rebuild_root, "gate_tamper_rebuild")
        for root in (first, second):
            release = (root / "current").resolve()
            audit_path = release / calibration.AUDIT_NAME
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["acceptance_summary"]["gates"]["LOFO"]["passed"] = False
            audit["acceptance_summary"]["development_method_passed"] = False
            audit["acceptance_summary"]["computed_gate_outcome"] = (
                "COMPUTED_GATES_NOT_SATISFIED"
            )
            audit["development_method_passed"] = False
            audit["computed_gate_outcome"] = "COMPUTED_GATES_NOT_SATISFIED"
            calibration.write_json(audit_path, audit)
            input_path = release / calibration.RELEASE_INPUT_NAME
            release_input = json.loads(input_path.read_text(encoding="utf-8"))
            release_input["computed_gate_outcome"] = (
                "COMPUTED_GATES_NOT_SATISFIED"
            )
            release_input["calibration_audit"]["sha256"] = validator.sha256_file(
                audit_path
            )
            calibration.write_json(input_path, release_input)
        with self.assertRaisesRegex(validator.ReleaseError, "claimed/recomputed gate"):
            validator.validate_and_publish(
                self._config(self.root / "never_gate_tamper", first, second)
            )

    def test_preregistered_gate_failure_decision_and_pointer_rollback(self) -> None:
        gates = dict.fromkeys(validator.REQUIRED_GATES, True)
        gates["bootstrap"] = False
        status, smoke = validator.decision_from_gates(gates)
        self.assertEqual(status, validator.FAIL_STATUS)
        self.assertFalse(smoke)

        outdir = self.root / "rollback"
        validator.validate_and_publish(self._config(outdir))
        previous = (outdir / "current").resolve()
        previous_bytes = (
            previous / validator.RELEASE_NAME
        ).read_bytes()

        def fail_pointer(_release: Path, _current: Path) -> None:
            raise RuntimeError("injected atomic-pointer failure")

        with self.assertRaisesRegex(RuntimeError, "injected atomic-pointer failure"):
            validator.validate_and_publish(
                self._config(outdir), pointer_promoter=fail_pointer
            )
        self.assertTrue((outdir / "current").is_symlink())
        self.assertEqual((outdir / "current").resolve(), previous)
        self.assertEqual(
            (previous / validator.RELEASE_NAME).read_bytes(), previous_bytes
        )

    def test_consistent_computed_gate_failure_publishes_fail_without_smoke(self) -> None:
        first = self._clone_root(self.primary_root, "computed_fail_primary")
        second = self._clone_root(self.rebuild_root, "computed_fail_rebuild")
        self._convert_publication_to_consistent_bootstrap_failure(first)
        self._convert_publication_to_consistent_bootstrap_failure(second)
        payload = validator.validate_and_publish(
            self._config(self.root / "development_fail", first, second)
        )
        self.assertEqual(payload["status"], validator.FAIL_STATUS)
        self.assertFalse(payload["development_method_passed"])
        self.assertFalse(payload["development_smoke_eligible"])
        self.assertFalse(payload["formal_eligible"])
        self.assertFalse(payload["docking_gold_release_eligible"])
        self.assertFalse(payload["training_label_release_eligible"])
        self.assertFalse(payload["p2_training_ready"])
        self.assertFalse(
            payload["gate_revalidation"]["gates"]["bootstrap"]["passed"]
        )


if __name__ == "__main__":
    unittest.main()
