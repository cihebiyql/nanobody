#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


from experiments.phase2_5080_v1.src import (
    process_phase2_v3_p2_v1_3_native_top8 as processor,
)
from experiments.phase2_5080_v1.src import (
    validate_phase2_v3_p2_v1_3_native_processor_release as validator,
)
from experiments.phase2_5080_v1.src.test_process_phase2_v3_p2_v1_3_native_top8 import (
    NativeFixture,
)


class NativeProcessorQualificationTests(unittest.TestCase):
    def _build_pair(self, root: Path):
        fixture = NativeFixture(root)
        first_root = root / "processor_primary"
        second_root = root / "processor_rebuild"
        first = processor.build_package(fixture.config(first_root))
        second = processor.build_package(fixture.config(second_root))
        self.assertEqual(first["status"], processor.PROCESSOR_PENDING_STATUS)
        self.assertEqual(first, second)
        return fixture, first_root, second_root

    def _config(
        self,
        fixture: NativeFixture,
        first_root: Path,
        second_root: Path,
        outdir: Path,
    ) -> validator.QualificationConfig:
        return validator.QualificationConfig(
            primary_audit=first_root / "current" / processor.AUDIT_NAME,
            rebuild_audit=second_root / "current" / processor.AUDIT_NAME,
            selector_csv=fixture.selector_csv,
            selector_audit=fixture.selector_audit,
            preregistration=fixture.preregistration,
            execution_release=fixture.execution_release_manifest,
            positive_manifest=fixture.positive_manifest,
            mutant_manifest=fixture.mutant_manifest,
            case_manifest=fixture.case_manifest,
            run_manifest=fixture.run_manifest,
            protocol_manifest=fixture.protocol_manifest,
            references=fixture.references,
            processor_path=Path(processor.__file__).resolve(),
            processor_test=processor.DEFAULT_PROCESSOR_TEST,
            outdir=outdir,
            contract=validator.QualificationContract(
                case_count=1,
                run_count=2,
                metric_rows=2 * fixture.poses_per_run,
            ),
        )

    def test_two_independent_pending_releases_qualify_and_publish_immutably(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, first_root, second_root = self._build_pair(root)
            outdir = root / "qualification"
            payload = validator.qualify(
                self._config(fixture, first_root, second_root, outdir)
            )
            self.assertEqual(payload["status"], validator.STATUS)
            self.assertTrue(payload["calibration_input_eligible"])
            self.assertFalse(payload["formal_eligible"])
            self.assertFalse(payload["training_label_release_eligible"])
            self.assertFalse(payload["docking_gold_release_eligible"])
            self.assertEqual(
                payload["determinism"]["independent_publication_count"], 2
            )
            current = outdir / "current"
            self.assertTrue(current.is_symlink())
            observed = json.loads(
                (current / validator.QUALIFICATION_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(observed, payload)
            self.assertEqual(
                set(payload["qualified_input"]),
                {
                    "processor_audit_sha256",
                    "continuous_metrics_sha256",
                    "continuous_metrics_row_hash_chain",
                    "selector_csv_sha256",
                    "selector_audit_sha256",
                    "selector_publication_release_id",
                    "preregistration_sha256",
                    "execution_release_sha256",
                    "positive_manifest_sha256",
                    "mutant_manifest_sha256",
                    "case_manifest_sha256",
                    "run_manifest_sha256",
                    "protocol_manifest_sha256",
                    "reference_sha256",
                    "processor_sha256",
                    "processor_test_sha256",
                    "validator_sha256",
                    "validator_test_sha256",
                },
            )

    def test_same_release_self_signed_and_tampered_rebuild_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, first_root, second_root = self._build_pair(root)
            config = self._config(
                fixture, first_root, second_root, root / "qualification"
            )
            same = validator.QualificationConfig(
                **{**config.__dict__, "rebuild_audit": config.primary_audit}
            )
            with self.assertRaises(validator.QualificationError):
                validator.qualify(same)

            # A builder-local, self-signed release file cannot alter pending status.
            processor.write_json(
                first_root / "self_signed_release.json",
                {"status": validator.STATUS, "calibration_input_eligible": True},
            )
            primary_audit = json.loads(
                config.primary_audit.read_text(encoding="utf-8")
            )
            self.assertEqual(primary_audit["status"], processor.PROCESSOR_PENDING_STATUS)
            self.assertFalse(primary_audit["primary_native_metric_eligible"])

            rebuild_metrics = second_root / "current" / processor.CONTINUOUS_METRICS_NAME
            rebuild_metrics.write_text(
                rebuild_metrics.read_text(encoding="utf-8") + "tamper\n",
                encoding="utf-8",
            )
            with self.assertRaises(validator.QualificationError):
                validator.qualify(config)


if __name__ == "__main__":
    unittest.main()
