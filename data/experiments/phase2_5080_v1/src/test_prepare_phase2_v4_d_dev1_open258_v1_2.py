#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SUBJECT = HERE / "prepare_phase2_v4_d_dev1_open258_v1_2.py"

spec = importlib.util.spec_from_file_location("dev1_v12_subject", SUBJECT)
if spec is None or spec.loader is None:
    raise RuntimeError("unable_to_load_subject")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class Helper:
    SUCCESS_STATES = {"SUCCESS"}
    EXPECTED_PROTOCOL_CORE_SHA256 = "protocol"

    @staticmethod
    def as_float(value, *, field):
        output = float(value)
        if output != output:
            raise ValueError(field)
        return output

    @staticmethod
    def nested_metric(payload, *path):
        value = payload
        for key in path:
            value = value[key]
        return value


class FakeV11:
    @staticmethod
    def partition_open_jobs_for_recovery(selected_jobs):
        return [dict(selected_jobs[0])], dict(selected_jobs[1])

    @staticmethod
    def read_frozen_terminal_failure(_path, failure):
        return (
            {
                "job_id": failure["job_id"],
                "job_hash": failure["job_hash"],
                "state": "FAILED_MAX_ATTEMPTS",
                "selected_model_count": "0",
                "pose_score_model_count": "0",
                "pose_backed_2x2": "false",
            },
            {"aggregate_terminal_rows_parsed": 1, "aggregate_metric_fields_parsed": 0},
        )


def jobs_and_split(count: int = 2):
    jobs = []
    split = []
    for index in range(count):
        candidate = f"candidate_{index}"
        jobs.append(
            {
                "job_id": f"job_{index}",
                "entity_id": candidate,
                "entity_type": "candidate",
                "conformation": "8x6b" if index % 2 == 0 else "9e6y",
                "seed": str(100 + index),
            }
        )
        split.append(
            {
                "candidate_id": candidate,
                "parent_id": f"parent_{index}",
                "target_patch_id": "A_CENTER",
                "design_mode": "H3",
                "model_split": "OPEN_TRAIN" if index == 0 else "OPEN_DEVELOPMENT",
            }
        )
    return jobs, split


def poses_for_jobs(jobs, pair_count: int = 5, rmsd_overrides=None):
    rmsd_overrides = rmsd_overrides or {}
    rows = []
    for job_index, job in enumerate(jobs):
        for model_index in range(pair_count):
            for reference in m.CONFORMATIONS:
                rmsd = rmsd_overrides.get((job_index, model_index, reference), 0.25)
                rows.append(
                    {
                        "job_id": job["job_id"],
                        "model": f"model_{model_index}.pdb.gz",
                        "scoring_reference": reference,
                        "overlay_rmsd_a": str(rmsd),
                        "haddock_score": str(-100.0 + model_index),
                    }
                )
    return rows


def identity_hash_for(jobs, overrides):
    identities = []
    for (job_index, model_index, reference), rmsd in overrides.items():
        if reference == jobs[job_index]["conformation"] and rmsd > 1.0:
            identities.append(
                {
                    "job_id": jobs[job_index]["job_id"],
                    "model": f"model_{model_index}.pdb.gz",
                    "conformation": reference,
                    "seed": int(jobs[job_index]["seed"]),
                    "t_ca_rmsd_a": float(rmsd),
                }
            )
    return m.canonical_invalid_identity(identities)[1]


class Dev1V12Tests(unittest.TestCase):
    def raw_payload(self, state="SUCCESS"):
        scores = []
        for reference in m.CONFORMATIONS:
            scores.append(
                {
                    "reference_id": reference,
                    "hotspot_overlap": {"full": {"count": 1}, "anchor": {"count": 1}, "holdout": {"count": 1}},
                    "vhh_pvrl2_occlusion": {"residue_pair_count": 1, "by_vhh_region_pair_count": {"cdr3": 1}, "cdr3_fraction": 0.1},
                    "clashes_2p5a": {
                        "vhh_pvrig": {"residue_pair_count": 0},
                        "vhh_pvrl2": {"residue_pair_count": 0},
                        "atom_pair_count": 0,
                        "residue_pair_count": 0,
                    },
                    "overlay": {"t_ca_rmsd_a": 0.1},
                }
            )
        return {
            "job_id": "open_job",
            "job_hash": "open_hash",
            "protocol_core_sha256": "protocol",
            "entity_type": "candidate",
            "entity_id": "open_candidate",
            "dock_conformation": "8x6b",
            "seed": "1",
            "state": state,
            "selected_model_count": 1,
            "pose_scores": [
                {"pose": "/tmp/model_1.pdb.gz", "haddock_io": {"score": -1, "unw_energies.air": 0}, "scores": scores}
            ],
        }

    def filter_with_contract(self, jobs, split, poses, invalid_count, affected_jobs, affected_candidates, by_conf, min_affected, identity_sha):
        pair_count = len(poses) // 2
        with ExitStack() as stack:
            values = {
                "EXPECTED_OPEN_ROWS": len(split),
                "EXPECTED_RAW_OPEN_JOBS": len(jobs),
                "EXPECTED_COMPLETE_PAIR_COUNT": pair_count,
                "EXPECTED_FILTERED_COMPLETE_PAIR_COUNT": pair_count - invalid_count,
                "EXPECTED_INVALID_PAIR_COUNT": invalid_count,
                "EXPECTED_AFFECTED_JOB_COUNT": affected_jobs,
                "EXPECTED_AFFECTED_CANDIDATE_COUNT": affected_candidates,
                "EXPECTED_INVALID_BY_CONFORMATION": by_conf,
                "EXPECTED_MIN_AFFECTED_RETAINED_PAIRS": min_affected,
                "EXPECTED_INVALID_IDENTITY_SHA256": identity_sha,
            }
            for name, value in values.items():
                stack.enter_context(mock.patch.object(m, name, value))
            return m.filter_invalid_native_overlay_pairs(Helper, poses, jobs, split)

    def test_frozen_canonicalization_reproduces_941d_hash(self):
        diagnostic = json.loads((ROOT / "audits/phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2.json").read_text())
        rows, digest = m.canonical_invalid_identity(diagnostic["invalid_native_overlay_rows"])
        self.assertEqual(len(rows), 99)
        self.assertEqual(digest, "941d5010190c6576ee0961681227d5b9b1ce9a719cc63ae5c25a45b0f8de9c1f")

    def test_real_governance_contract_is_self_consistent(self):
        load = lambda name: json.loads((ROOT / "audits" / name).read_text())
        rows = m.validate_frozen_governance(
            load("phase2_v4_d_dev1_open258_v1_2_pose_validity_recovery_preregistration.json"),
            load("phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2.json"),
            load("phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2_run_receipt.json"),
            load("phase2_v4_d_dev1_open258_v1_2_invalid_pair_canonicalization_clarification.json"),
            load("phase2_v4_d_dev1_open258_v1_1_remote_runtime_failure_receipt.json"),
        )
        self.assertEqual(len(rows), 99)

    def test_pair_filter_drops_both_references_before_downstream(self):
        jobs, split = jobs_and_split()
        overrides = {(0, 0, "8x6b"): 1.5}
        poses = poses_for_jobs(jobs, rmsd_overrides=overrides)
        filtered, audit = self.filter_with_contract(
            jobs, split, poses, 1, 1, 1, {"8x6b": 1}, 4, identity_hash_for(jobs, overrides)
        )
        pair = [row for row in filtered if row["job_id"] == "job_0" and row["model"] == "model_0.pdb.gz"]
        self.assertEqual(pair, [])
        self.assertEqual(len(filtered), 18)
        self.assertEqual(audit["complete_pair_count_after_filter"], 9)

    def test_exact_two_conformation_three_seed_grid_is_pre_raw_gate(self):
        jobs = [
            {
                "job_id": f"j_{conformation}_{seed}",
                "entity_type": "candidate",
                "entity_id": "candidate",
                "conformation": conformation,
                "seed": str(seed),
            }
            for conformation in m.CONFORMATIONS
            for seed in (917, 1931, 3253)
        ]
        with mock.patch.object(m, "EXPECTED_OPEN_JOBS", 6):
            m.validate_exact_open_job_grid(jobs, {"candidate"})
            broken = [dict(row) for row in jobs]
            broken[-1]["seed"] = "917"
            with self.assertRaisesRegex(m.Dev1V12BuildError, "duplicate_candidate_conformation_seed"):
                m.validate_exact_open_job_grid(broken, {"candidate"})

    def test_threshold_equality_is_retained(self):
        jobs, split = jobs_and_split()
        overrides = {(0, 0, "8x6b"): 1.0, (1, 1, "9e6y"): 1.01}
        poses = poses_for_jobs(jobs, rmsd_overrides=overrides)
        filtered, _audit = self.filter_with_contract(
            jobs, split, poses, 1, 1, 1, {"9e6y": 1}, 4, identity_hash_for(jobs, overrides)
        )
        retained = [row for row in filtered if row["job_id"] == "job_0" and row["model"] == "model_0.pdb.gz"]
        self.assertEqual({row["scoring_reference"] for row in retained}, set(m.CONFORMATIONS))

    def test_nonfinite_rmsd_and_wrong_native_conformation_fail_closed(self):
        jobs, split = jobs_and_split()
        poses = poses_for_jobs(jobs, rmsd_overrides={(0, 0, "8x6b"): float("nan")})
        real_helper = m.load_bound_module(
            HERE / "prepare_phase2_v4_d_open_teacher.py", "nonfinite_helper", m.EXPECTED_V1_HELPER_SHA256
        )
        with mock.patch.object(m, "EXPECTED_OPEN_ROWS", 2), mock.patch.object(m, "EXPECTED_COMPLETE_PAIR_COUNT", 10):
            with self.assertRaisesRegex(Exception, "non_finite_float:overlay_rmsd_a"):
                m.filter_invalid_native_overlay_pairs(real_helper, poses, jobs, split)
        wrong = [dict(job) for job in jobs]
        wrong[0]["conformation"] = "wrong_reference"
        with mock.patch.object(m, "EXPECTED_OPEN_ROWS", 2), mock.patch.object(m, "EXPECTED_COMPLETE_PAIR_COUNT", 10):
            with self.assertRaisesRegex(m.Dev1V12BuildError, "job_conformation_invalid"):
                m.filter_invalid_native_overlay_pairs(Helper, poses_for_jobs(wrong), wrong, split)

    def test_incomplete_or_duplicate_reference_pair_is_rejected(self):
        jobs, split = jobs_and_split()
        poses = poses_for_jobs(jobs)
        incomplete = poses[:-1]
        with mock.patch.object(m, "EXPECTED_OPEN_ROWS", 2), mock.patch.object(m, "EXPECTED_COMPLETE_PAIR_COUNT", 10):
            with self.assertRaisesRegex(m.Dev1V12BuildError, "pair_not_exact_two_reference"):
                m.filter_invalid_native_overlay_pairs(Helper, incomplete, jobs, split)
        duplicate = poses + [dict(poses[0])]
        with mock.patch.object(m, "EXPECTED_OPEN_ROWS", 2):
            with self.assertRaisesRegex(m.Dev1V12BuildError, "duplicate_pair_reference"):
                m.filter_invalid_native_overlay_pairs(Helper, duplicate, jobs, split)

    def test_invalid_identity_hash_and_count_drift_fail_closed(self):
        jobs, split = jobs_and_split()
        overrides = {(0, 0, "8x6b"): 1.5}
        poses = poses_for_jobs(jobs, rmsd_overrides=overrides)
        with self.assertRaisesRegex(m.Dev1V12BuildError, "invalid_pair_count_not_99"):
            self.filter_with_contract(jobs, split, poses, 2, 1, 1, {"8x6b": 1}, 4, identity_hash_for(jobs, overrides))
        with self.assertRaisesRegex(m.Dev1V12BuildError, "raw_invalid_identity_sha256_mismatch"):
            self.filter_with_contract(jobs, split, poses, 1, 1, 1, {"8x6b": 1}, 4, "0" * 64)

    def test_less_than_four_retained_pairs_fails(self):
        jobs, split = jobs_and_split(1)
        overrides = {(0, 0, "8x6b"): 1.5}
        poses = poses_for_jobs(jobs, pair_count=4, rmsd_overrides=overrides)
        with self.assertRaisesRegex(m.Dev1V12BuildError, "success_job_retained_pairs_below_4"):
            self.filter_with_contract(jobs, split, poses, 1, 1, 1, {"8x6b": 1}, 3, identity_hash_for(jobs, overrides))

    def test_missing_success_job_cannot_be_hidden_by_extra_pairs(self):
        jobs, split = jobs_and_split()
        poses = poses_for_jobs(jobs[:1], pair_count=10, rmsd_overrides={(0, 0, "8x6b"): 1.5})
        digest = identity_hash_for(jobs[:1], {(0, 0, "8x6b"): 1.5})
        with ExitStack() as stack:
            for name, value in {
                "EXPECTED_OPEN_ROWS": 2,
                "EXPECTED_RAW_OPEN_JOBS": 2,
                "EXPECTED_COMPLETE_PAIR_COUNT": 10,
                "EXPECTED_FILTERED_COMPLETE_PAIR_COUNT": 9,
                "EXPECTED_INVALID_PAIR_COUNT": 1,
                "EXPECTED_AFFECTED_JOB_COUNT": 1,
                "EXPECTED_AFFECTED_CANDIDATE_COUNT": 1,
                "EXPECTED_INVALID_BY_CONFORMATION": {"8x6b": 1},
                "EXPECTED_INVALID_IDENTITY_SHA256": digest,
            }.items():
                stack.enter_context(mock.patch.object(m, name, value))
            with self.assertRaisesRegex(m.Dev1V12BuildError, "pose_pair_success_job_closure_failed"):
                m.filter_invalid_native_overlay_pairs(Helper, poses, jobs, split)

    def test_secure_collector_rejects_second_fallback_and_never_addresses_sealed_dir(self):
        jobs = [
            {"job_id": "open_job", "job_hash": "open_hash", "entity_type": "candidate", "entity_id": "open_candidate", "conformation": "8x6b", "seed": "1"},
            {"job_id": "failed_job", "job_hash": "failed_hash"},
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "open_job").mkdir()
            (root / "sealed_job").mkdir()
            (root / "sealed_job" / "job_result.json").write_text("SEALED MUST NOT OPEN")
            result = root / "open_job" / "job_result.json"
            payload = self.raw_payload()
            raw = json.dumps(payload).encode()
            result.write_bytes(raw)
            bindings = [{"job_id": "open_job", "sha256": hashlib.sha256(raw).hexdigest()}]
            chain = hashlib.sha256(json.dumps(bindings, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
            real_open = m.os.open

            def guarded_open(path, *args, **kwargs):
                if str(path) == "sealed_job":
                    raise AssertionError("sealed path addressed")
                return real_open(path, *args, **kwargs)

            with mock.patch.object(m, "EXPECTED_RAW_OPEN_JOBS", 1), mock.patch.object(m, "EXPECTED_OPEN_JOBS", 2), mock.patch.object(m, "EXPECTED_RAW_RESULT_SHA256_CHAIN", chain), mock.patch.object(m.os, "open", side_effect=guarded_open):
                poses, results, _bindings, evidence = m.collect_recovery_results_secure(
                    Helper, FakeV11, root, jobs, root / "unused_job_results.tsv"
                )
            self.assertEqual(len(poses), 2)
            self.assertEqual(len(results), 2)
            self.assertEqual(evidence["raw_result_sha256_chain"], chain)

            payload["state"] = "FAILED"
            result.write_text(json.dumps(payload))
            with mock.patch.object(m, "EXPECTED_RAW_OPEN_JOBS", 1), mock.patch.object(m, "EXPECTED_OPEN_JOBS", 2):
                with self.assertRaisesRegex(m.Dev1V12BuildError, "second_nonsuccess_open_job_forbidden"):
                    m.collect_recovery_results_secure(Helper, FakeV11, root, jobs, root / "unused")

    def test_raw_result_chain_drift_fails_closed(self):
        jobs = [
            {"job_id": "open_job", "job_hash": "open_hash", "entity_type": "candidate", "entity_id": "open_candidate", "conformation": "8x6b", "seed": "1"},
            {"job_id": "failed_job", "job_hash": "failed_hash"},
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "open_job").mkdir()
            (root / "open_job" / "job_result.json").write_text(json.dumps(self.raw_payload()))
            with mock.patch.object(m, "EXPECTED_RAW_OPEN_JOBS", 1), mock.patch.object(m, "EXPECTED_OPEN_JOBS", 2), mock.patch.object(m, "EXPECTED_RAW_RESULT_SHA256_CHAIN", "0" * 64):
                with self.assertRaisesRegex(m.Dev1V12BuildError, "raw_result_sha256_chain_mismatch"):
                    m.collect_recovery_results_secure(Helper, FakeV11, root, jobs, root / "unused")

    def test_secure_collector_rejects_raw_result_symlink_and_non_directory(self):
        jobs = [
            {"job_id": "open_job", "job_hash": "open_hash", "entity_type": "candidate", "entity_id": "open_candidate", "conformation": "8x6b", "seed": "1"},
            {"job_id": "failed_job", "job_hash": "failed_hash"},
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.json"
            target.write_text(json.dumps(self.raw_payload()))
            (root / "open_job").mkdir()
            (root / "open_job" / "job_result.json").symlink_to(target)
            with mock.patch.object(m, "EXPECTED_RAW_OPEN_JOBS", 1):
                with self.assertRaisesRegex(m.Dev1V12BuildError, "raw_job_result_unavailable"):
                    m.collect_recovery_results_secure(Helper, FakeV11, root, jobs, root / "unused")
            (root / "open_job" / "job_result.json").unlink()
            (root / "open_job").rmdir()
            (root / "open_job").write_text("not a directory")
            with mock.patch.object(m, "EXPECTED_RAW_OPEN_JOBS", 1):
                with self.assertRaisesRegex(m.Dev1V12BuildError, "raw_job_directory_unavailable"):
                    m.collect_recovery_results_secure(Helper, FakeV11, root, jobs, root / "unused")

    def test_pair_drop_precedes_unchanged_helper_rank_weighting(self):
        helper = m.load_bound_module(HERE / "prepare_phase2_v4_d_open_teacher.py", "test_helper", m.EXPECTED_V1_HELPER_SHA256)
        jobs, split = jobs_and_split(1)
        overrides = {(0, 0, "8x6b"): 1.5}
        poses = poses_for_jobs(jobs, pair_count=5, rmsd_overrides=overrides)
        for row in poses:
            row.update({
                "air_energy": "0", "hotspot_overlap": "12", "anchor_overlap": "5",
                "holdout_overlap": "7", "total_occlusion": "200", "cdr3_occlusion": "30",
                "cdr3_fraction": "0.12", "vhh_pvrig_clash_residue_pairs": "0",
                "vhh_pvrl2_clash_residue_pairs": "0",
            })
        filtered, _audit = self.filter_with_contract(
            jobs, split, poses, 1, 1, 1, {"8x6b": 1}, 4, identity_hash_for(jobs, overrides)
        )
        summary = helper.job_summary("job_0", "8x6b", filtered)
        direct = helper.job_summary(
            "job_0", "8x6b", [row for row in poses if row["model"] != "model_0.pdb.gz"]
        )
        self.assertEqual(summary, direct)
        self.assertEqual(summary["complete_model_count"], 4)

    def test_production_shaped_filter_counts_and_descriptive_replay_are_deterministic(self):
        candidate_ids = [m.FROZEN_FAILED_JOB_ID.split("_8x6b_s3253_")[0].removeprefix("CANDIDATE_")]
        candidate_ids.extend(f"production_candidate_{index:03d}" for index in range(1, 258))
        split = [
            {
                "candidate_id": candidate_id,
                "parent_id": f"parent_{index % 20}",
                "target_patch_id": ("A_CENTER", "B_LOWER", "C_CROSS")[index % 3],
                "design_mode": ("H3", "H1H3")[index % 2],
                "model_split": "OPEN_TRAIN" if index < 226 else "OPEN_DEVELOPMENT",
            }
            for index, candidate_id in enumerate(candidate_ids)
        ]
        jobs = []
        for candidate_index, candidate_id in enumerate(candidate_ids):
            for conformation in m.CONFORMATIONS:
                for seed in (917, 1931, 3253):
                    if candidate_index == 0 and conformation == "8x6b" and seed == 3253:
                        job_id = m.FROZEN_FAILED_JOB_ID
                    else:
                        job_id = f"prod_{candidate_index}_{conformation}_{seed}"
                    jobs.append(
                        {
                            "job_id": job_id,
                            "entity_id": candidate_id,
                            "entity_type": "candidate",
                            "conformation": conformation,
                            "seed": str(seed),
                        }
                    )
        success_jobs = [job for job in jobs if job["job_id"] != m.FROZEN_FAILED_JOB_ID]
        invalid_jobs = []
        for candidate_index in range(1, 84):
            invalid_jobs.append(f"prod_{candidate_index}_8x6b_917")
        invalid_jobs.extend(f"prod_{candidate_index}_8x6b_1931" for candidate_index in range(1, 6))
        invalid_jobs.extend(f"prod_{candidate_index}_9e6y_917" for candidate_index in range(1, 11))
        self.assertEqual(len(invalid_jobs), 98)
        invalid_set = set(invalid_jobs)
        poses = []
        identities = []
        pair_total = 0
        retained_affected = []
        for job_index, job in enumerate(success_jobs):
            pair_count = 10 if job_index < 567 else 9
            pair_total += pair_count
            invalid_models = 2 if job["job_id"] == invalid_jobs[0] else (1 if job["job_id"] in invalid_set else 0)
            if invalid_models:
                retained_affected.append(pair_count - invalid_models)
            for model_index in range(pair_count):
                model = f"model_{model_index}.pdb.gz"
                for reference in m.CONFORMATIONS:
                    rmsd = 1.25 if model_index < invalid_models and reference == job["conformation"] else 0.25
                    poses.append(
                        {
                            "job_id": job["job_id"],
                            "model": model,
                            "scoring_reference": reference,
                            "overlay_rmsd_a": str(rmsd),
                            "haddock_score": str(-100 + model_index),
                        }
                    )
                if model_index < invalid_models:
                    identities.append(
                        {
                            "job_id": job["job_id"],
                            "model": model,
                            "conformation": job["conformation"],
                            "seed": int(job["seed"]),
                            "t_ca_rmsd_a": 1.25,
                        }
                    )
        self.assertEqual(pair_total, 14490)
        digest = m.canonical_invalid_identity(identities)[1]
        with mock.patch.object(m, "EXPECTED_INVALID_IDENTITY_SHA256", digest), mock.patch.object(
            m, "EXPECTED_MIN_AFFECTED_RETAINED_PAIRS", min(retained_affected)
        ):
            filtered1, audit1 = m.filter_invalid_native_overlay_pairs(Helper, poses, jobs, split)
            filtered2, audit2 = m.filter_invalid_native_overlay_pairs(Helper, poses, jobs, split)
        self.assertEqual(len(filtered1) // 2, 14391)
        self.assertEqual(audit1["invalid_complete_pair_count"], 99)
        self.assertEqual(audit1["affected_job_count"], 98)
        self.assertEqual(audit1["affected_candidate_count"], 83)
        self.assertEqual(audit1["invalid_by_conformation"], {"8x6b": 89, "9e6y": 10})
        self.assertEqual(filtered1, filtered2)
        self.assertEqual(audit1, audit2)

        teacher_rows = [
            {
                **row,
                "R_dual_min": 0.1 + index / 10000.0,
                "R_8X6B": 0.2 + index / 10000.0,
                "R_9E6Y": 0.15 + index / 10000.0,
                "teacher_uncertainty": 0.01 + index / 100000.0,
            }
            for index, row in enumerate(split)
        ]
        report1 = m.build_descriptive_sensitivity_report(teacher_rows, audit1)
        report2 = m.build_descriptive_sensitivity_report(teacher_rows, audit1)
        self.assertEqual(report1, report2)
        json.dumps(report1, allow_nan=False, sort_keys=True)

    def test_all_numeric_teacher_targets_are_explicitly_finite_gated(self):
        row = {
            "candidate_id": "candidate",
            "R_8X6B": 0.1,
            "R_9E6Y": 0.2,
            "R_dual_min": 0.1,
            "teacher_uncertainty": 0.01,
            "hotspot_overlap_median_8X6B": 2.0,
            "generic_binding_prior": 0.5,
            "generic_binding_model_uncertainty": "",
        }
        m.validate_all_numeric_teacher_targets_finite([row])
        bad = dict(row)
        bad["R_9E6Y"] = float("inf")
        with self.assertRaisesRegex(m.Dev1V12BuildError, "teacher_numeric_target_nonfinite"):
            m.validate_all_numeric_teacher_targets_finite([bad])

    def test_release_failure_never_publishes_partial_final(self):
        rows = [{"candidate_id": "x", "model_split": "OPEN_TRAIN", "R_dual_min": 0.1}]
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "release_v1_2"
            with mock.patch.object(m.tarfile, "open", side_effect=RuntimeError("synthetic")):
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    m.create_release_artifacts(
                        output, rows, source_inputs={}, pose_filter_audit={}, descriptive_sensitivity={}, builder_sha256="a" * 64
                    )
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_preexisting_output_directory_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "release_v1_2"
            output.mkdir()
            sentinel = output / "sentinel"
            sentinel.write_text("keep")
            with self.assertRaisesRegex(m.Dev1V12BuildError, "output_directory_exists"):
                m.create_release_artifacts(
                    output,
                    [{"candidate_id": "x"}],
                    source_inputs={},
                    pose_filter_audit={},
                    descriptive_sensitivity={},
                    builder_sha256="a" * 64,
                )
            self.assertEqual(sentinel.read_text(), "keep")

    def test_release_does_not_expose_invalid_counts_as_teacher_features(self):
        rows = [{"candidate_id": "x", "model_split": "OPEN_TRAIN", "R_dual_min": 0.1}]
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "release_v1_2"
            m.create_release_artifacts(
                output,
                rows,
                source_inputs={},
                pose_filter_audit={"invalid_complete_pair_count": 99},
                descriptive_sensitivity={},
                builder_sha256="a" * 64,
            )
            header = (output / "outputs" / m.OUTPUT_BASENAME).read_text().splitlines()[0]
            self.assertNotIn("invalid_pair", header)
            audit = json.loads((output / "outputs" / m.AUDIT_BASENAME).read_text())
            self.assertEqual(audit["pose_validity_filter"]["invalid_complete_pair_count"], 99)

    def test_release_rejects_invalid_count_training_feature(self):
        rows = [{"candidate_id": "x", "invalid_pair_count": 1}]
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "release_v1_2"
            with self.assertRaisesRegex(m.Dev1V12BuildError, "exposed_as_teacher_feature"):
                m.create_release_artifacts(
                    output, rows, source_inputs={}, pose_filter_audit={}, descriptive_sensitivity={}, builder_sha256="a" * 64
                )
            self.assertFalse(output.exists())

    def test_symlink_and_snapshot_identity_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / "real"
            real.write_bytes(b"abc")
            link = root / "link"
            link.symlink_to(real)
            digest = hashlib.sha256(b"abc").hexdigest()
            with self.assertRaises(m.Dev1V12BuildError):
                m.read_bound_bytes(link, "link", digest)
            original_fstat = m.os.fstat
            calls = {"n": 0}

            def drifting(fd):
                value = original_fstat(fd)
                calls["n"] += 1
                if calls["n"] == 2:
                    values = list(value)
                    values[9] += 1
                    return os.stat_result(values)
                return value

            with mock.patch.object(m.os, "fstat", side_effect=drifting):
                with self.assertRaisesRegex(m.Dev1V12BuildError, "changed_during_read"):
                    m.read_bound_bytes(real, "real", digest)

    def test_v1_and_v1_1_immutable_hashes_remain_exact(self):
        expected = {
            HERE / "prepare_phase2_v4_d_dev1_open258.py": m.EXPECTED_V1_BUILDER_SHA256,
            HERE / "prepare_phase2_v4_d_dev1_open258_v1_1.py": m.EXPECTED_V1_1_BUILDER_SHA256,
            HERE / "prepare_phase2_v4_d_open_teacher.py": m.EXPECTED_V1_HELPER_SHA256,
            ROOT / "audits/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json": m.EXPECTED_V1_FAILURE_RECEIPT_SHA256,
            ROOT / "audits/phase2_v4_d_dev1_open258_v1_1_remote_runtime_failure_receipt.json": m.EXPECTED_V1_1_FAILURE_RECEIPT_SHA256,
        }
        for path, digest in expected.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path.name)
        v1 = json.loads((ROOT / "audits/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json").read_text())
        self.assertEqual(v1["status"], "FAILED_CLOSED_MISSING_RAW_RESULT_FOR_FROZEN_FAILED_MAX_ATTEMPTS_JOB")
        self.assertFalse(v1["teacher_artifacts_created"])
        self.assertTrue(v1["release_absent"])
        v11 = json.loads((ROOT / "audits/phase2_v4_d_dev1_open258_v1_1_remote_runtime_failure_receipt.json").read_text())
        self.assertEqual(v11["status"], "FAILED_CLOSED_NATIVE_OVERLAY_RMSD_ABOVE_1A")
        self.assertFalse(v11["artifact_closure"]["teacher_artifacts_created"])
        self.assertTrue(v11["artifact_closure"]["release_v1_1_absent"])

    def test_source_has_no_assert_remote_execution_or_formal_claim(self):
        source = SUBJECT.read_text()
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(tree)))
        self.assertNotIn("ssh.exe", source)
        self.assertNotIn("subprocess", source)
        self.assertIn("formal_v4_f_unlock_eligible\": False", source)
        self.assertIn("raw_result_sha256_chain_mismatch", source)
        self.assertNotIn("--root-cause", source)
        self.assertNotIn("root_cause_sha256", source)
        self.assertIn('"builder_reads_root_cause_path_or_hash": False', source)
        main_source = source[source.index("def main(") :]
        self.assertLess(
            main_source.index('read_bound_bytes(\n        args.generic_prior'),
            main_source.index("collect_recovery_results_secure("),
        )
        self.assertLess(
            main_source.index("validate_exact_open_job_grid(jobs, allowed)"),
            main_source.index("collect_recovery_results_secure("),
        )

    def test_node23_launcher_is_v1_2_only_and_requires_future_authorization(self):
        launcher = (HERE / "run_phase2_v4_d_dev1_open258_v1_2_node23.sh").read_text()
        self.assertIn("/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_2_20260717", launcher)
        self.assertIn("FROZEN_FOR_DEV1_V1_2_REMOTE_EXECUTION", launcher)
        self.assertIn('f.get("remote_execution_authorized") is not True', launcher)
        self.assertIn('f.get("independent_implementation_review_status") != "PASS"', launcher)
        self.assertIn('f.get("test32_label_rows_emitted") != 0', launcher)
        self.assertIn('f.get("source_evaluator_status") != "FAIL"', launcher)
        self.assertIn("872bee4bf27b894244f14b31f43b03f877a1cff89a084f6272c0cbccd026ba9b", launcher)
        for option in (
            "--diagnostic", "--diagnostic-receipt", "--canonical-clarification",
            "--v1-1-failure-receipt", "--v1-1-builder", "--output-dir",
        ):
            self.assertIn(option, launcher)
        self.assertNotIn("ssh.exe", launcher)


if __name__ == "__main__":
    unittest.main()
