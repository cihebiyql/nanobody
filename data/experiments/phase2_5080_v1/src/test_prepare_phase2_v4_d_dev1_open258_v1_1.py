#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


MODULE_PATH = Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258_v1_1.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v4_d_dev1_open258_v1_1", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable_to_load_dev1_v1_1_builder")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def write_aggregate(path: Path, rows: list[dict[str, str]]) -> None:
    fields = (
        "job_id", "entity_id", "entity_type", "control_class", "expected_behavior",
        "conformation", "seed", "state", "attempts", "selected_model_count",
        "pose_score_model_count", "pose_backed_2x2", "representative_model",
        "haddock_score", "air_energy", "native_class", "cross_class",
        "representative_pair_label", "model_pair_consensus_fraction",
        "model_native_cross_support_agreement_fraction", "model_strict_a_fraction",
        "native_hotspot_overlap", "cross_hotspot_overlap", "native_holdout_overlap",
        "cross_holdout_overlap", "native_total_occlusion", "cross_total_occlusion",
        "native_cdr3_occlusion", "cross_cdr3_occlusion", "native_cdr3_fraction",
        "cross_cdr3_fraction", "anomaly_flag", "anomaly_reason", "job_hash",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture_layout(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    header_length = raw.index(b"\n") + 1
    target = (MOD.FROZEN_FAILED_JOB_ID + "\t").encode("utf-8")
    offset = raw.index(target, header_length)
    end = raw.index(b"\n", offset) + 1
    row = raw[offset:end]
    return {
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "file_size": len(raw),
        "header_length": header_length,
        "header_sha256": hashlib.sha256(raw[:header_length]).hexdigest(),
        "row_offset": offset,
        "row_length": len(row),
        "row_sha256": hashlib.sha256(row).hexdigest(),
    }


def valid_failure_row() -> dict[str, str]:
    row = {field: "" for field in (
        "control_class", "representative_model", "haddock_score", "air_energy",
        "native_class", "cross_class", "representative_pair_label",
        *MOD.FORCED_EMPTY_METRIC_FIELDS, "anomaly_reason",
    )}
    row.update({
        "job_id": MOD.FROZEN_FAILED_JOB_ID,
        "entity_id": MOD.FROZEN_FAILED_CANDIDATE_ID,
        "entity_type": "candidate",
        "expected_behavior": "CANDIDATE_UNKNOWN",
        "conformation": "8x6b",
        "seed": "3253",
        "job_hash": MOD.FROZEN_FAILED_JOB_HASH,
        "state": MOD.FROZEN_FAILED_JOB_STATE,
        "attempts": "2",
        "selected_model_count": "0",
        "pose_score_model_count": "0",
        "pose_backed_2x2": "false",
        "model_pair_consensus_fraction": "",
        "model_native_cross_support_agreement_fraction": "0.0",
        "model_strict_a_fraction": "0.0",
        "anomaly_flag": "false",
    })
    row["model_pair_consensus_fraction"] = "0.0"
    return row


def frozen_job() -> dict[str, str]:
    return {
        "job_id": MOD.FROZEN_FAILED_JOB_ID,
        "job_hash": MOD.FROZEN_FAILED_JOB_HASH,
        "entity_type": "candidate",
        "entity_id": MOD.FROZEN_FAILED_CANDIDATE_ID,
        "conformation": "8x6b",
        "seed": "3253",
    }


class Dev1V11FallbackTest(unittest.TestCase):
    def test_exact_frozen_failure_is_the_only_admitted_aggregate_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_results.tsv"
            write_aggregate(
                path,
                [
                    {
                        **valid_failure_row(),
                        "job_id": "unselected-success",
                        "job_hash": "1" * 64,
                        "state": "SUCCESS",
                        "selected_model_count": "8",
                        "pose_score_model_count": "8",
                        "pose_backed_2x2": "true",
                    },
                    valid_failure_row(),
                ],
            )
            row, audit = MOD.read_frozen_terminal_failure(
                path, frozen_job(), layout=fixture_layout(path)
            )
            self.assertEqual(row["job_id"], MOD.FROZEN_FAILED_JOB_ID)
            self.assertEqual(row["state"], MOD.FROZEN_FAILED_JOB_STATE)
            self.assertEqual(audit["aggregate_terminal_rows_parsed"], 1)
            self.assertEqual(audit["aggregate_metric_fields_parsed"], 0)
            self.assertEqual(set(row), set(MOD.FALLBACK_TERMINAL_FIELDS))

    def test_duplicate_fallback_row_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_results.tsv"
            write_aggregate(path, [valid_failure_row()])
            layout = fixture_layout(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(path.read_text(encoding="utf-8").splitlines()[1] + "\n")
            with self.assertRaisesRegex(MOD.Dev1V11BuildError, "size_mismatch"):
                MOD.read_frozen_terminal_failure(path, frozen_job(), layout=layout)

    def test_success_or_other_failure_state_cannot_be_fallback(self) -> None:
        for state in ("SUCCESS", "FAILED", "PENDING"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "job_results.tsv"
                row = valid_failure_row()
                row["state"] = state
                write_aggregate(path, [row])
                with self.assertRaisesRegex(MOD.Dev1V11BuildError, "fallback_state_mismatch"):
                    MOD.read_frozen_terminal_failure(path, frozen_job(), layout=fixture_layout(path))

    def test_metric_or_pose_bearing_fallback_is_rejected(self) -> None:
        mutations = {
            "selected_model_count": "1",
            "pose_score_model_count": "1",
            "pose_backed_2x2": "true",
        }
        for field, value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "job_results.tsv"
                row = valid_failure_row()
                row[field] = value
                write_aggregate(path, [row])
                with self.assertRaisesRegex(MOD.Dev1V11BuildError, f"fallback_{field}_mismatch"):
                    MOD.read_frozen_terminal_failure(path, frozen_job(), layout=fixture_layout(path))

    def test_wrong_hash_candidate_or_sealed_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_results.tsv"
            write_aggregate(path, [valid_failure_row()])
            wrong_hash = frozen_job()
            wrong_hash["job_hash"] = "0" * 64
            with self.assertRaisesRegex(MOD.Dev1V11BuildError, "frozen_failed_manifest_identity_mismatch"):
                MOD.read_frozen_terminal_failure(path, wrong_hash, layout=fixture_layout(path))
            sealed = frozen_job()
            sealed["entity_id"] = "SEALED-CANDIDATE"
            with self.assertRaisesRegex(MOD.Dev1V11BuildError, "frozen_failed_manifest_identity_mismatch"):
                MOD.read_frozen_terminal_failure(path, sealed, layout=fixture_layout(path))

    def test_raw_path_policy_requires_1547_raw_and_exact_fallback_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = []
            for index in range(MOD.EXPECTED_RAW_OPEN_JOBS):
                job_id = f"job-{index:04d}"
                jobs.append({"job_id": job_id})
                result = root / job_id
                result.mkdir()
                (result / "job_result.json").write_text("{}")
            jobs.append(frozen_job())
            raw_jobs, failure = MOD.partition_open_jobs_for_recovery(jobs)
            MOD.validate_recovery_result_paths(root, raw_jobs, failure)
            self.assertEqual(len(raw_jobs), MOD.EXPECTED_RAW_OPEN_JOBS)
            self.assertEqual(failure["job_id"], MOD.FROZEN_FAILED_JOB_ID)

            os.unlink(root / "job-0000" / "job_result.json")
            with self.assertRaisesRegex(MOD.Dev1V11BuildError, "raw_job_result_missing"):
                MOD.validate_recovery_result_paths(root, raw_jobs, failure)

    def test_second_missing_raw_job_is_never_converted_to_fallback(self) -> None:
        jobs = [{"job_id": f"job-{index:04d}"} for index in range(MOD.EXPECTED_OPEN_JOBS)]
        with self.assertRaisesRegex(MOD.Dev1V11BuildError, "frozen_failed_job_count_not_one"):
            MOD.partition_open_jobs_for_recovery(jobs)

    def test_collect_closes_1547_raw_plus_one_terminal_failure(self) -> None:
        raw_jobs = [
            {"job_id": f"job-{index:04d}", "job_hash": f"{index:064x}"}
            for index in range(MOD.EXPECTED_RAW_OPEN_JOBS)
        ]
        selected = [*raw_jobs, frozen_job()]
        raw_results = [
            {"job_id": row["job_id"], "job_hash": row["job_hash"], "state": "SUCCESS"}
            for row in raw_jobs
        ]
        helper = SimpleNamespace(
            SUCCESS_STATES={"SUCCESS"},
            raw_pose_rows_for_jobs=lambda _root, jobs: (
                [],
                raw_results,
                [{"job_id": row["job_id"], "sha256": "a" * 64} for row in jobs],
                "b" * 64,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            aggregate = Path(directory) / "job_results.tsv"
            write_aggregate(aggregate, [valid_failure_row()])
            with mock.patch.object(MOD, "validate_recovery_result_paths"):
                poses, results, bindings, evidence = MOD.collect_recovery_results(
                    helper, Path(directory), selected, aggregate,
                    layout=fixture_layout(aggregate),
                )
        self.assertEqual(poses, [])
        self.assertEqual(len(results), MOD.EXPECTED_OPEN_JOBS)
        self.assertEqual(len(bindings), MOD.EXPECTED_RAW_OPEN_JOBS)
        self.assertEqual(sum(row["state"] == MOD.FROZEN_FAILED_JOB_STATE for row in results), 1)
        self.assertEqual(evidence["aggregate_terminal_failure_count"], 1)
        self.assertEqual(evidence["aggregate_metric_fields_parsed"], 0)

    def test_every_frozen_layout_binding_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_results.tsv"
            write_aggregate(path, [valid_failure_row()])
            baseline = fixture_layout(path)
            mutations = {
                "file_size": int(baseline["file_size"]) + 1,
                "file_sha256": "0" * 64,
                "header_length": int(baseline["header_length"]) - 1,
                "header_sha256": "0" * 64,
                "row_offset": int(baseline["row_offset"]) + 1,
                "row_length": int(baseline["row_length"]) - 1,
                "row_sha256": "0" * 64,
            }
            for field, value in mutations.items():
                with self.subTest(field=field):
                    layout = dict(baseline)
                    layout[field] = value
                    with self.assertRaises(MOD.Dev1V11BuildError):
                        MOD.read_frozen_terminal_failure(path, frozen_job(), layout=layout)

    def test_same_tick_in_place_mutation_cannot_mix_hash_and_row_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_results.tsv"
            write_aggregate(path, [valid_failure_row()])
            layout = fixture_layout(path)
            original_raw = path.read_bytes()
            mutated_raw = original_raw.replace(b"FAILED_MAX_ATTEMPTS", b"FAILEX_MAX_ATTEMPTS")
            self.assertEqual(len(mutated_raw), len(original_raw))
            baseline_stat = os.stat(path)
            real_read = os.read
            mutated = False

            def read_then_mutate(fd: int, count: int) -> bytes:
                nonlocal mutated
                block = real_read(fd, count)
                if block and not mutated:
                    path.write_bytes(mutated_raw)
                    mutated = True
                return block

            # Simulate a filesystem whose timestamp/ctime granularity cannot expose
            # the same-tick in-place mutation. The immutable bytes already returned
            # by the single read pass must remain the only hash/header/row source.
            with mock.patch.object(MOD.os, "read", side_effect=read_then_mutate), \
                 mock.patch.object(MOD.os, "fstat", return_value=baseline_stat):
                terminal, audit = MOD.read_frozen_terminal_failure(
                    path, frozen_job(), layout=layout
                )
            self.assertTrue(mutated)
            self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), layout["file_sha256"])
            self.assertEqual(terminal["state"], MOD.FROZEN_FAILED_JOB_STATE)
            self.assertEqual(audit["aggregate_terminal_rows_parsed"], 1)

    def test_unexpected_raw_result_for_fallback_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_jobs = []
            for index in range(MOD.EXPECTED_RAW_OPEN_JOBS):
                job_id = f"job-{index:04d}"
                raw_jobs.append({"job_id": job_id})
                result = root / job_id
                result.mkdir()
                (result / "job_result.json").write_text("{}")
            fallback = root / MOD.FROZEN_FAILED_JOB_ID
            fallback.mkdir()
            (fallback / "job_result.json").write_text("{}")
            with self.assertRaisesRegex(MOD.Dev1V11BuildError, "frozen_failure_raw_job_result_unexpected"):
                MOD.validate_recovery_result_paths(root, raw_jobs, frozen_job())

    def test_immutable_v1_failure_receipt_is_runtime_hash_bound(self) -> None:
        receipt = MODULE_PATH.parents[1] / "audits/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json"
        payload = MOD.validate_v1_failure_receipt(receipt)
        self.assertFalse(payload["teacher_artifacts_created"])
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "receipt.json"
            changed = json.loads(receipt.read_text(encoding="utf-8"))
            changed["teacher_artifacts_created"] = True
            altered.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(MOD.Dev1V11BuildError, "sha256_mismatch"):
                MOD.validate_v1_failure_receipt(altered)

    def test_terminal_fallback_is_formula_equivalent_to_any_skipped_nonsuccess(self) -> None:
        helper_path = MODULE_PATH.with_name("prepare_phase2_v4_d_open_teacher.py")
        spec = importlib.util.spec_from_file_location("dev1_v11_formula_equivalence_helper", helper_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        split = {field: f"value-{field}" for field in helper.CANDIDATE_FIELDS}
        split.update({"candidate_id": MOD.FROZEN_FAILED_CANDIDATE_ID, "model_split": "OPEN_TRAIN"})
        jobs = []
        results = []
        for conf in helper.CONFORMATIONS:
            for seed in (1, 2, 3):
                job_id = MOD.FROZEN_FAILED_JOB_ID if (conf, seed) == ("8x6b", 3) else f"job-{conf}-{seed}"
                job_hash = hashlib.sha256(job_id.encode()).hexdigest()
                jobs.append({"job_id": job_id, "job_hash": job_hash, "entity_type": "candidate", "entity_id": MOD.FROZEN_FAILED_CANDIDATE_ID, "conformation": conf})
                results.append({"job_id": job_id, "job_hash": job_hash, "state": MOD.FROZEN_FAILED_JOB_STATE if job_id == MOD.FROZEN_FAILED_JOB_ID else "SUCCESS", "pose_backed_2x2": "false" if job_id == MOD.FROZEN_FAILED_JOB_ID else "true"})

        def summary(job_id: str, conf: str, _poses: object) -> dict[str, object]:
            base = {
                "job_id": job_id, "dock_conformation": conf, "job_utility": 0.4,
                "native_cross_support_agreement": 0.5, "model_pair_consensus_fraction": 0.5,
                "model_strict_a_fraction": 0.0, "model_count_reliability": 1.0,
                "agreement_reliability": 0.75,
            }
            for field in ("hotspot_overlap", "anchor_overlap", "holdout_overlap", "total_occlusion", "cdr3_occlusion", "cdr3_fraction", "vhh_pvrig_clash_residue_pairs", "vhh_pvrl2_clash_residue_pairs", "overlay_rmsd_a"):
                base[field] = 1.0
            return base

        with mock.patch.object(helper, "job_summary", side_effect=summary):
            failed = helper.build_teacher_rows([split], jobs, results, [])
            pending_results = [dict(row, state="PENDING") if row["job_id"] == MOD.FROZEN_FAILED_JOB_ID else row for row in results]
            pending = helper.build_teacher_rows([split], jobs, pending_results, [])
        self.assertEqual(failed, pending)
        self.assertEqual(failed[0]["successful_seed_count_8X6B"], 2)
        self.assertEqual(failed[0]["successful_seed_count_9E6Y"], 3)

    def test_recovery_prereg_binds_exact_failure_and_preserves_test32(self) -> None:
        prereg = MODULE_PATH.parents[1] / "audits/phase2_v4_d_dev1_open258_v1_1_recovery_preregistration.json"
        payload = json.loads(prereg.read_text(encoding="utf-8"))
        fallback = payload["single_terminal_failure_fallback"]
        self.assertEqual(fallback["job_id"], MOD.FROZEN_FAILED_JOB_ID)
        self.assertEqual(fallback["job_hash"], MOD.FROZEN_FAILED_JOB_HASH)
        self.assertEqual(fallback["state"], MOD.FROZEN_FAILED_JOB_STATE)
        self.assertEqual(fallback["count"], 1)
        self.assertEqual(payload["sealed_data_boundary"]["test32_metric_values_read"], 0)
        self.assertFalse(payload["formal_v4_f_unlock_eligible"])

    def test_frozen_projection_evidence_matches_production_layout_and_zero_pose_rows(self) -> None:
        evidence_path = MODULE_PATH.parents[1] / "audits/phase2_v4_d_dev1_open258_v1_1_terminal_fallback_projection_evidence.json"
        self.assertEqual(MOD.sha256_file(evidence_path), MOD.EXPECTED_FALLBACK_EVIDENCE_SHA256)
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        source = payload["source_job_results"]
        for field in ("file_size", "header_length", "header_sha256", "row_offset", "row_length", "row_sha256"):
            source_field = {"file_size": "size", "row_offset": "row_offset", "row_length": "row_length"}.get(field, field)
            self.assertEqual(MOD.PRODUCTION_LAYOUT[field], source[source_field])
        self.assertEqual(payload["terminal_projection"], {
            **MOD.EXPECTED_TERMINAL_IDENTITY,
        })
        self.assertEqual(payload["ignored_non_supervision_fields_present"], MOD.SUPPORT_FIELDS_IGNORED)
        self.assertEqual(payload["source_pose_scores"]["exact_job_id_row_count"], 0)
        self.assertEqual(payload["aggregate_metric_fields_parsed"], 0)

    def test_versioned_output_names_and_claim_boundary(self) -> None:
        self.assertIn("v1_1", MOD.OUTPUT_BASENAME)
        self.assertIn("v1_1", MOD.ARCHIVE_BASENAME)
        self.assertNotEqual(MOD.ARCHIVE_BASENAME, "v4d_dev1_open258_delivery_v1.tar.gz")
        self.assertIn("development-only", MOD.CLAIM_BOUNDARY)
        self.assertIn("not", MOD.CLAIM_BOUNDARY)

    def test_source_has_no_python_assert_or_formal_output_path(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*assert\s")
        self.assertNotIn("predictions/pvrig_v4_f_surrogate_predictions_v1", source)
        self.assertNotIn("status/pvrig_v4_d_surrogate_training_v3", source)


if __name__ == "__main__":
    unittest.main()
