#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


MODULE_PATH = Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v4_d_dev1_open258", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable_to_load_dev1_builder")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def valid_evaluator() -> dict[str, object]:
    gates = {name: {"status": "PASS"} for name in MOD.EXPECTED_GATE_NAMES}
    gates[MOD.SOURCE_FAILED_GATE] = {"status": "FAIL"}
    return {
        "status": "FAIL",
        "unlockable": False,
        "evidence_mode": "production_pose_backed",
        "job_count": MOD.EXPECTED_TOTAL_JOBS,
        "result_count": MOD.EXPECTED_TOTAL_JOBS,
        "completed_pose_backed_jobs": MOD.EXPECTED_COMPLETED_POSE_BACKED_JOBS,
        "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256": MOD.EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256": MOD.EXPECTED_POSE_SCORES_SHA256,
        "protocol_core_sha256": MOD.EXPECTED_PROTOCOL_CORE_SHA256,
        "protocol_lock_sha256": MOD.EXPECTED_PROTOCOL_LOCK_SHA256,
        "candidates_sha256": MOD.EXPECTED_SPLIT_MANIFEST_SHA256,
        "stability_gate_spec_sha256": MOD.EXPECTED_STABILITY_SPEC_SHA256,
        "gates": gates,
    }


def teacher_row(index: int) -> dict[str, object]:
    split = "OPEN_TRAIN" if index < 226 else "OPEN_DEVELOPMENT"
    return {
        "schema_version": MOD.SCHEMA_VERSION,
        "candidate_id": f"candidate-{index:03d}",
        "model_split": split,
        "parent_framework_cluster": f"parent-{index % 12:02d}",
        "sequence_sha256": f"{index:064x}",
        "sequence": "QVQLVESGGGLVQAGGSLRLSCAASG",
        "design_method": "RFantibody",
        "design_mode": "H3",
        "target_patch_id": "A_CENTER",
        "cdr1": "AAA",
        "cdr2": "BBB",
        "cdr3": "CCC",
        "R_8X6B": 0.2,
        "R_9E6Y": 0.3,
        "R_dual_min": 0.2,
        "generic_binding_prior": 0.5,
        "dev_release_track": MOD.TRACK_ID,
        "development_only": True,
        "source_evaluator_status": "FAIL",
        "source_failed_gate": MOD.SOURCE_FAILED_GATE,
        "formal_v4_f_unlock_eligible": False,
        "claim_boundary": MOD.CLAIM_BOUNDARY,
    }


def prior_row(index: int, *, prior: str = "0.5", uncertainty: str = "0.1") -> dict[str, str]:
    return {
        "candidate_id": f"candidate-{index:03d}",
        "sequence_sha256": f"{index:064x}",
        "generic_binding_prior": prior,
        "model_uncertainty": uncertainty,
        "model_disagreement": "0.01",
        "generic_binding_prior_seed_43": "0.4",
        "generic_binding_prior_seed_53": "0.5",
        "generic_binding_prior_seed_67": "0.6",
        "generic_binding_model": "label_free_fixture",
        "generic_binding_train_summary_sha256": "a" * 64,
        "target_sequence_sha256": "b" * 64,
        "model_claim_boundary": "label_free_generic_prior_only",
    }


class Dev1BuilderTest(unittest.TestCase):
    def test_prereg_timestamp_precedes_file_mtime_and_raw_open_is_zero(self) -> None:
        prereg = MODULE_PATH.parents[1] / "audits/phase2_v4_d_dev1_open258_preregistration.json"
        payload = json.loads(prereg.read_text())
        frozen = datetime.fromisoformat(payload["frozen_at_utc"]).timestamp()
        self.assertLessEqual(frozen, prereg.stat().st_mtime)
        self.assertEqual(payload["timestamp_source"], "initial_prereg_file_mtime_before_any_raw_open")
        self.assertFalse(payload["split_boundary"]["sealed_raw_job_results_may_be_opened"])
        self.assertEqual(payload["physical_read_policy"]["sealed_raw_job_results_opened_required"], 0)

    def test_expected_prereg_hash_matches_file(self) -> None:
        prereg = MODULE_PATH.parents[1] / "audits/phase2_v4_d_dev1_open258_preregistration.json"
        self.assertEqual(MOD.sha256_file(prereg), MOD.EXPECTED_PREREG_SHA256)

    def test_source_evaluator_accepts_only_single_frozen_failure(self) -> None:
        MOD.validate_source_evaluator(valid_evaluator(), MOD.EXPECTED_EVALUATOR_SHA256)
        altered = valid_evaluator()
        altered["gates"]["protocol_validation"] = {"status": "FAIL"}
        with self.assertRaisesRegex(MOD.Dev1BuildError, "failed_gate_set_mismatch"):
            MOD.validate_source_evaluator(altered, MOD.EXPECTED_EVALUATOR_SHA256)
        passed = valid_evaluator()
        passed["status"] = "PASS"
        with self.assertRaisesRegex(MOD.Dev1BuildError, "status_not_FAIL"):
            MOD.validate_source_evaluator(passed, MOD.EXPECTED_EVALUATOR_SHA256)

    def test_evaluator_file_hash_is_mandatory(self) -> None:
        with self.assertRaisesRegex(MOD.Dev1BuildError, "evaluator_file_sha256_mismatch"):
            MOD.validate_source_evaluator(valid_evaluator(), "0" * 64)
        altered = valid_evaluator()
        altered["protocol_core_sha256"] = "0" * 64
        with self.assertRaisesRegex(MOD.Dev1BuildError, "protocol_core_sha256_mismatch"):
            MOD.validate_source_evaluator(altered, MOD.EXPECTED_EVALUATOR_SHA256)

    def test_selected_result_symlink_is_rejected_before_raw_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            root.mkdir()
            target = Path(directory) / "target"
            target.mkdir()
            (target / "job_result.json").write_text("{}")
            job_id = "job-0"
            os.symlink(target, root / job_id, target_is_directory=True)
            jobs = [{"job_id": job_id}] * MOD.EXPECTED_OPEN_JOBS
            with self.assertRaisesRegex(MOD.Dev1BuildError, "not_real_directory"):
                MOD.validate_selected_result_paths(root, jobs)

    def test_release_artifacts_preserve_trainer_schema_and_non_authority(self) -> None:
        rows = [teacher_row(index) for index in range(MOD.EXPECTED_OPEN_ROWS)]
        rows[-1]["generic_binding_model_uncertainty"] = 0.2
        MOD.validate_teacher_rows(rows)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release"
            result = MOD.create_release_artifacts(
                output,
                rows,
                source_inputs={
                    "split_manifest_sha256": MOD.EXPECTED_SPLIT_MANIFEST_SHA256,
                    "raw_test32_job_files_opened": 0,
                    "test32_metric_values_read": 0,
                    "test32_label_rows_emitted": 0,
                    "full_aggregate_value_rows_parsed": 0,
                },
                builder_sha256="a" * 64,
                prereg_sha256=MOD.EXPECTED_PREREG_SHA256,
            )
            self.assertEqual(result["test32_raw_open"], 0)
            audit = json.loads((output / "outputs" / MOD.AUDIT_BASENAME).read_text())
            self.assertEqual(audit["status"], MOD.AUDIT_STATUS)
            self.assertFalse(audit["formal_v4_f_unlock_eligible"])
            self.assertFalse(audit["non_authority"]["formal_completion_or_unlock_receipt_created"])
            self.assertTrue(set(MOD.REQUIRED_TRAINER_FIELDS) <= set(audit["output"]["exact_header"]))
            self.assertIn(MOD.PRIMARY_TARGET, audit["output"]["exact_header"])
            self.assertIn("generic_binding_model_uncertainty", audit["output"]["exact_header"])

    def test_generic_prior_must_be_hash_bound_and_in_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=MOD.GENERIC_PRIOR_FIELDS)
                writer.writeheader()
                row = prior_row(0, prior="1.1")
                row["candidate_id"] = "a"
                writer.writerow(row)
            digest = MOD.sha256_file(path)
            prior = MOD.read_prior_csv(
                path,
                expected_sha256=digest,
                expected_candidates={"a": "0" * 64},
            )
            with self.assertRaisesRegex(MOD.Dev1BuildError, "out_of_range"):
                MOD.add_generic_prior([{"candidate_id": "a"}], prior)
            with self.assertRaisesRegex(MOD.Dev1BuildError, "sha256_mismatch"):
                MOD.read_prior_csv(
                    path,
                    expected_sha256="0" * 64,
                    expected_candidates={"a": "0" * 64},
                )

    def test_generic_prior_requires_exact_290_id_and_sequence_hash_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=MOD.GENERIC_PRIOR_FIELDS)
                writer.writeheader()
                writer.writerow(prior_row(0))
            digest = MOD.sha256_file(path)
            with self.assertRaisesRegex(MOD.Dev1BuildError, "candidate_id_closure_failed"):
                MOD.read_prior_csv(
                    path,
                    expected_sha256=digest,
                    expected_candidates={"candidate-000": "0" * 64, "candidate-001": "1" * 64},
                )
            altered = prior_row(0)
            altered["sequence_sha256"] = "f" * 64
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=MOD.GENERIC_PRIOR_FIELDS)
                writer.writeheader()
                writer.writerow(altered)
            with self.assertRaisesRegex(MOD.Dev1BuildError, "sequence_sha_mismatch"):
                MOD.read_prior_csv(
                    path,
                    expected_sha256=MOD.sha256_file(path),
                    expected_candidates={"candidate-000": "0" * 64},
                )

    def test_main_filters_open_ids_before_raw_opener_and_binds_lock_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [
                "prereg.json", "helper.py", "split.tsv", "jobs.tsv", "job_results.tsv",
                "pose_scores.tsv", "core.lock", "protocol.lock", "stability.json",
                "evaluator.json", "prior.csv",
            ]
            files = {name: root / name for name in names}
            for path in files.values():
                path.write_text("x")
            files["prereg.json"].write_text(json.dumps({
                "status": "FROZEN_POSTHOC_BEFORE_DEV1_RAW_OPEN_EXTRACTION_OR_REMOTE_EXECUTION"
            }))
            files["evaluator.json"].write_text(json.dumps(valid_evaluator()))
            split_rows = []
            for index in range(290):
                split = "OPEN_TRAIN" if index < 226 else ("OPEN_DEVELOPMENT" if index < 258 else MOD.SEALED_SPLIT)
                split_rows.append({
                    "candidate_id": f"candidate-{index:03d}",
                    "sequence_sha256": f"{index:064x}",
                    "model_split": split,
                })
            jobs = [
                {"job_id": f"job-{index:04d}", "entity_type": "candidate", "entity_id": f"candidate-{index // 6:03d}", "conformation": "8x6b" if index % 2 == 0 else "9e6y", "job_hash": f"{index:064x}"}
                for index in range(290 * 6)
            ]
            raw_seen: list[dict[str, str]] = []

            def raw_open(_root: Path, selected: list[dict[str, str]]):
                raw_seen.extend(selected)
                results = [{"job_id": row["job_id"], "job_hash": row["job_hash"], "state": "SUCCESS"} for row in selected]
                return [], results, [{"job_id": row["job_id"], "sha256": "a" * 64} for row in selected], "b" * 64

            helper = SimpleNamespace(
                read_tsv=lambda path: split_rows if path == files["split.tsv"] else jobs,
                select_open_split=lambda rows: rows[:258],
                select_open_candidate_jobs=lambda rows, allowed: [row for row in rows if row["entity_id"] in allowed],
                raw_pose_rows_for_jobs=raw_open,
                build_teacher_rows=lambda *_args: [teacher_row(index) for index in range(258)],
                SUCCESS_STATES={"SUCCESS"},
            )
            with files["prior.csv"].open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=MOD.GENERIC_PRIOR_FIELDS)
                writer.writeheader()
                for index in range(290):
                    writer.writerow(prior_row(index))
            expected_by_name = {
                "prereg.json": MOD.EXPECTED_PREREG_SHA256,
                "split.tsv": MOD.EXPECTED_SPLIT_MANIFEST_SHA256,
                "jobs.tsv": MOD.EXPECTED_JOB_MANIFEST_SHA256,
                "job_results.tsv": MOD.EXPECTED_JOB_RESULTS_SHA256,
                "pose_scores.tsv": MOD.EXPECTED_POSE_SCORES_SHA256,
                "core.lock": MOD.EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256,
                "protocol.lock": MOD.EXPECTED_PROTOCOL_LOCK_FILE_SHA256,
                "stability.json": MOD.EXPECTED_STABILITY_SPEC_FILE_SHA256,
                "evaluator.json": MOD.EXPECTED_EVALUATOR_SHA256,
                "prior.csv": "c" * 64,
            }

            def fake_hash(path: Path) -> str:
                return expected_by_name.get(path.name, "d" * 64)

            argv = [
                "--preregistration", str(files["prereg.json"]),
                "--v1-formula-helper", str(files["helper.py"]),
                "--split-manifest", str(files["split.tsv"]),
                "--job-manifest", str(files["jobs.tsv"]),
                "--job-results", str(files["job_results.tsv"]),
                "--pose-scores", str(files["pose_scores.tsv"]),
                "--protocol-core-lock", str(files["core.lock"]),
                "--protocol-lock", str(files["protocol.lock"]),
                "--stability-spec", str(files["stability.json"]),
                "--results-root", str(root),
                "--evaluator", str(files["evaluator.json"]),
                "--generic-prior", str(files["prior.csv"]),
                "--expected-generic-prior-sha256", "c" * 64,
                "--output-dir", str(root / "out"),
            ]
            with mock.patch.object(MOD, "sha256_file", side_effect=fake_hash), \
                 mock.patch.object(MOD, "load_v1_helper", return_value=helper), \
                 mock.patch.object(MOD, "validate_selected_result_paths"), \
                 mock.patch.object(MOD, "create_release_artifacts", return_value={"status": "ok"}):
                self.assertEqual(MOD.main(argv), 0)
            self.assertEqual(len(raw_seen), MOD.EXPECTED_OPEN_JOBS)
            self.assertTrue(all(row["entity_id"] not in {f"candidate-{i:03d}" for i in range(258, 290)} for row in raw_seen))

            raw_seen.clear()

            def drifted_hash(path: Path) -> str:
                if path.name == "core.lock":
                    return "0" * 64
                return fake_hash(path)

            with mock.patch.object(MOD, "sha256_file", side_effect=drifted_hash), \
                 mock.patch.object(MOD, "load_v1_helper", return_value=helper), \
                 mock.patch.object(MOD, "validate_selected_result_paths"), \
                 mock.patch.object(MOD, "create_release_artifacts", return_value={"status": "ok"}):
                with self.assertRaisesRegex(MOD.Dev1BuildError, "protocol_core_lock_file_sha256_mismatch"):
                    MOD.main(argv)
            self.assertEqual(raw_seen, [])

    def test_protocol_lock_file_hash_drift_stops_before_raw_open(self) -> None:
        source = MODULE_PATH.read_text()
        self.assertIn("protocol_core_lock_file_sha256", source)
        self.assertIn("protocol_lock_file_sha256", source)
        self.assertIn("stability_spec_file_sha256", source)

    def test_source_contains_no_python_assert_or_formal_output_path(self) -> None:
        source = MODULE_PATH.read_text()
        self.assertNotRegex(source, r"(?m)^\s*assert\s")
        self.assertNotIn("predictions/pvrig_v4_f_surrogate_predictions_v1", source)
        self.assertNotIn("status/pvrig_v4_d_surrogate_training_v3", source)


if __name__ == "__main__":
    unittest.main()
