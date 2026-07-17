#!/usr/bin/env python3
"""Functional regression coverage for the V4-D surrogate watcher V3.

All fixtures are noncanonical and contain only synthetic OPEN_TRAIN /
OPEN_DEVELOPMENT geometry labels.  The prospective split remains manifest-only.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

try:  # package-mode unittest discovery
    from .test_monitor_phase2_v4_d_surrogate_training_v2 import (
        Fixture as V2Fixture,
        sha,
        write_json,
    )
except ImportError:  # direct execution from this source directory
    from test_monitor_phase2_v4_d_surrogate_training_v2 import (
        Fixture as V2Fixture,
        sha,
        write_json,
    )


SRC = Path(__file__).resolve().parent
SCRIPT = SRC / "monitor_phase2_v4_d_surrogate_training_v3.sh"
HELPER = SRC / "phase2_v4_d_surrogate_watcher_helper_v3.py"
EXPECTED_BUILDER_SHA256 = (
    "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"
)
EXPECTED_JOB_MANIFEST_SHA256 = (
    "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
)


class Fixture(V2Fixture):
    """V2 stage stubs plus the stronger V3 teacher/evaluator closure."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.evaluator = self.delivery / "EVALUATOR_STABLE.json"
        self._write_v3_teacher_release()

    @property
    def status_path(self) -> Path:
        return self.exp / "status/pvrig_v4_d_surrogate_training_v3/status.json"

    @property
    def completion_receipt(self) -> Path:
        return (
            self.exp
            / "status/pvrig_v4_d_surrogate_training_v3/surrogate_v3_completion_receipt.json"
        )

    def _write_v3_teacher_release(self) -> None:
        raw_closure = "c" * 64
        job_results_sha256 = "d" * 64
        pose_scores_sha256 = "e" * 64
        write_json(
            self.evaluator,
            {
                "status": "PASS",
                "unlockable": True,
                "evidence_mode": "production_pose_backed",
                "job_count": 2022,
                "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
                "job_results_sha256": job_results_sha256,
                "pose_scores_sha256": pose_scores_sha256,
                "gates": {
                    "job_closure": {"status": "PASS"},
                    "pose_closure": {"passed": True},
                    "sealed_test": True,
                },
            },
        )
        write_json(
            self.teacher_audit,
            {
                "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
                "release": "open_train_and_open_development_only",
                "row_count": 3,
                "sealed_data_boundary": {
                    "model_split": "PROSPECTIVE_COMPUTATIONAL_TEST",
                    "raw_job_results_opened": 0,
                    "sealed_metrics_used_for_teacher_or_ranking": False,
                },
                "inputs": {
                    "split_manifest_sha256": sha(self.split),
                    "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
                    "job_results_sha256_for_evaluator_binding_only": job_results_sha256,
                    "pose_scores_sha256_for_evaluator_binding_only": pose_scores_sha256,
                    "raw_aggregate_closure": {
                        "status": "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
                        "job_count": 18,
                        "closure_sha256": raw_closure,
                    },
                },
            },
        )
        write_json(
            self.release_receipt,
            {
                "schema_version": "pvrig_v4_d_open_teacher_postprocess_receipt_v2",
                "status": "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
                "row_count": 3,
                "teacher_sha256": sha(self.teacher),
                "teacher_audit_sha256": sha(self.teacher_audit),
                "evaluator_sha256": sha(self.evaluator),
                "sealed_test_raw_job_results_opened": 0,
                "sealed_metrics_used_for_teacher_or_ranking": False,
                "raw_aggregate_closure_sha256": raw_closure,
                "full_aggregate_streamed_only_for_open_row_closure": True,
                "builder_sha256": EXPECTED_BUILDER_SHA256,
                "job_manifest_sha256": EXPECTED_JOB_MANIFEST_SHA256,
                "job_results_sha256": job_results_sha256,
                "pose_scores_sha256": pose_scores_sha256,
            },
        )

    def environment(self, contact: bool = True) -> dict[str, str]:
        environment = super().env(contact)
        environment.update(
            {
                "WATCHER_HELPER": str(HELPER),
                "V4D_OPEN_EVALUATOR": str(self.evaluator),
                "PYTHONOPTIMIZE": "0",
            }
        )
        for variable in (
            "V4D_V3_TRUST_ANCHOR",
            "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA",
            "BASH_ENV",
            "PYTHONPATH",
        ):
            environment.pop(variable, None)
        return environment

    def run_v3(self, contact: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT)],
            env=self.environment(contact),
            text=True,
            capture_output=True,
        )

    def status(self) -> dict[str, object]:
        return json.loads(self.status_path.read_text(encoding="utf-8"))


class SurrogateTrainingWatcherV3FunctionalTests(unittest.TestCase):
    maxDiff = None

    def assert_failed_before_training(self, fixture: Fixture) -> None:
        result = fixture.run_v3()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(fixture.status()["status"], "FAILED_INPUT_VALIDATION")
        self.assertFalse(fixture.order.exists(), "a trainer ran after invalid input")
        self.assertFalse(fixture.completion_receipt.exists())

    def test_missing_teacher_or_evaluator_waits_without_training(self) -> None:
        for missing in ("teacher", "evaluator"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                getattr(fixture, missing).unlink()
                result = fixture.run_v3()
                self.assertEqual(result.returncode, 4, result.stderr)
                status = fixture.status()
                self.assertEqual(status["status"], "WAITING_OPEN_TEACHER")
                self.assertIs(status["prospective_test_labels_read"], False)
                self.assertEqual(status["prospective_test_label_paths_accepted"], 0)
                self.assertFalse(fixture.order.exists())
                self.assertFalse(fixture.completion_receipt.exists())

    def test_complete_teacher_evaluator_closure_runs_all_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            result = fixture.run_v3()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                fixture.order.read_text(encoding="utf-8").splitlines(),
                ["base", "embedding", "contact"],
            )
            status = fixture.status()
            self.assertEqual(
                status["status"], "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED"
            )
            self.assertIs(status["prospective_test_labels_read"], False)
            self.assertEqual(status["prospective_test_label_paths_accepted"], 0)
            receipt = json.loads(fixture.completion_receipt.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["status"], "PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED"
            )
            self.assertEqual(
                set(receipt["stage_receipts"]),
                {"base_stage", "embedding_stage", "contact_stage"},
            )
            self.assertIs(receipt["prospective_test_labels_read"], False)
            self.assertEqual(receipt["prospective_test_label_paths_accepted"], 0)

    def test_frozen_input_hash_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.split.write_text(
                fixture.split.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            self.assert_failed_before_training(fixture)

    def test_teacher_audit_hash_tamper_fails_receipt_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            audit = json.loads(fixture.teacher_audit.read_text(encoding="utf-8"))
            audit["unbound_tamper"] = True
            write_json(fixture.teacher_audit, audit)
            self.assert_failed_before_training(fixture)

    def test_release_receipt_semantic_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            receipt = json.loads(fixture.release_receipt.read_text(encoding="utf-8"))
            receipt["full_aggregate_streamed_only_for_open_row_closure"] = False
            write_json(fixture.release_receipt, receipt)
            self.assert_failed_before_training(fixture)

    def test_evaluator_semantic_tamper_fails_even_with_updated_receipt_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            evaluator = json.loads(fixture.evaluator.read_text(encoding="utf-8"))
            evaluator["gates"]["pose_closure"] = {"status": "FAIL"}
            write_json(fixture.evaluator, evaluator)
            receipt = json.loads(fixture.release_receipt.read_text(encoding="utf-8"))
            receipt["evaluator_sha256"] = sha(fixture.evaluator)
            write_json(fixture.release_receipt, receipt)
            self.assert_failed_before_training(fixture)

    def test_recovery_runs_only_missing_contact_and_completion_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            first = fixture.run_v3(contact=False)
            self.assertEqual(first.returncode, 4, first.stderr)
            self.assertEqual(fixture.status()["status"], "WAITING_CONTACT_TRAINER")
            self.assertEqual(
                fixture.order.read_text(encoding="utf-8").splitlines(),
                ["base", "embedding"],
            )

            recovered = fixture.run_v3(contact=True)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(
                fixture.order.read_text(encoding="utf-8").splitlines(),
                ["base", "embedding", "contact"],
            )
            first_completion = json.loads(
                fixture.completion_receipt.read_text(encoding="utf-8")
            )

            repeated = fixture.run_v3(contact=True)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(
                fixture.order.read_text(encoding="utf-8").splitlines(),
                ["base", "embedding", "contact"],
            )
            repeated_completion = json.loads(
                fixture.completion_receipt.read_text(encoding="utf-8")
            )
            self.assertEqual(
                repeated_completion["stage_receipts"],
                first_completion["stage_receipts"],
            )


if __name__ == "__main__":
    unittest.main()
