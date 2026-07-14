#!/usr/bin/env python3
"""Regression tests for protocol validation and the next-generation hard gate."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import aggregate_results  # noqa: E402
import guard_next_generation  # noqa: E402
import validate_protocol  # noqa: E402
from common import read_tsv, sha256_file, write_tsv  # noqa: E402


PROTOCOL = ROOT / "config/protocol_spec.json"
FULL_JOBS = ROOT / "manifests/docking_jobs.tsv"


class StabilityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def reduced_valid_jobs(self) -> list[dict[str, str]]:
        rows = read_tsv(FULL_JOBS)
        controls = [row for row in rows if row["entity_type"] == "control"]
        candidate_id = next(row["entity_id"] for row in rows if row["entity_type"] == "candidate")
        candidate = [row for row in rows if row["entity_id"] == candidate_id]
        return controls + candidate

    def passing_results(self, jobs: list[dict[str, str]], positive_class: str = "A") -> list[dict[str, str]]:
        output = []
        for row in jobs:
            if row["control_class"] == "positive_control":
                geometry_class = positive_class
            else:
                geometry_class = "C"
            output.append(
                {
                    "job_id": row["job_id"],
                    "entity_id": row["entity_id"],
                    "entity_type": row["entity_type"],
                    "control_class": row["control_class"],
                    "expected_behavior": row["expected_behavior"],
                    "conformation": row["conformation"],
                    "seed": row["seed"],
                    "state": "SUCCESS",
                    "selected_model_count": "1",
                    "pose_score_model_count": "1",
                    "pose_backed_2x2": "true",
                    "representative_model": "cluster_1_model_1.pdb",
                    "haddock_score": "-10.0",
                    "native_class": geometry_class,
                    "cross_class": geometry_class,
                    "anomaly_flag": "false",
                    "job_hash": row["job_hash"],
                }
            )
        return output

    def test_current_full_protocol_and_job_manifest_validate(self) -> None:
        out = self.tmp / "validation.json"
        code = validate_protocol.main(["--protocol", str(PROTOCOL), "--jobs", str(FULL_JOBS), "--out", str(out)])
        self.assertEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["job_count"], 1050)

    def test_validate_protocol_reports_not_ready_without_jobs(self) -> None:
        out = self.tmp / "validation.json"
        code = validate_protocol.main(["--protocol", str(PROTOCOL), "--jobs", str(self.tmp / "missing.tsv"), "--out", str(out)])
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out.read_text())["status"], "NOT_READY")

    def test_validate_protocol_rejects_corrupted_cfg_hash(self) -> None:
        jobs = self.reduced_valid_jobs()[:6]
        jobs[0] = {**jobs[0], "cfg_hash": "0" * 64}
        path = self.tmp / "jobs.tsv"
        write_tsv(path, jobs, list(jobs[0]))
        out = self.tmp / "validation.json"
        code = validate_protocol.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(path), "--out", str(out), "--expected-total-jobs", str(len(jobs))]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "FAIL")
        self.assertTrue(any("cfg_hash_mismatch" in reason for reason in payload["gates"]["rendered_cfg_and_air"]["reasons"]))

    def test_aggregate_passes_complete_reduced_matrix(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        write_tsv(result_path, results, list(results[0]))
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue((self.tmp / "control_drift.tsv").is_file())
        self.assertTrue((self.tmp / "threshold_sensitivity.tsv").is_file())

    def test_aggregate_fails_when_positive_controls_collapse_to_e(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs, positive_class="E")
        write_tsv(result_path, results, list(results[0]))
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["gates"]["positive_controls_not_e_only"]["status"], "FAIL")

    def test_guard_requires_exact_passed_evaluator_lock_and_manifest(self) -> None:
        project = self.tmp / "project"
        (project / "reports").mkdir(parents=True)
        (project / "manifests").mkdir(parents=True)
        manifest = project / "manifests/docking_jobs.tsv"
        manifest.write_text("job_id\njob1\n", encoding="utf-8")
        manifest_sha = sha256_file(manifest)
        lock = {
            "status": "LOCKED",
            "protocol_core_sha256": "a" * 64,
            "protocol_lock_sha256": "b" * 64,
            "job_manifest_sha256": manifest_sha,
        }
        (project / "PROTOCOL_LOCK.json").write_text(json.dumps(lock), encoding="utf-8")
        evaluator = {
            "status": "PASS",
            "evidence_mode": "production_pose_backed",
            "protocol_core_sha256": "a" * 64,
            "protocol_lock_sha256": "b" * 64,
            "job_manifest_sha256": manifest_sha,
            "gates": {"all": {"status": "PASS"}},
        }
        evaluator_path = project / "reports/EVALUATOR_STABLE.json"
        evaluator_path.write_text(json.dumps(evaluator), encoding="utf-8")
        self.assertEqual(guard_next_generation.main(["--root", str(project)]), 0)
        evaluator["job_manifest_sha256"] = "0" * 64
        evaluator_path.write_text(json.dumps(evaluator), encoding="utf-8")
        self.assertNotEqual(guard_next_generation.main(["--root", str(project)]), 0)

    def test_current_empty_results_are_not_ready_and_guarded(self) -> None:
        out = self.tmp / "empty_eval.json"
        process = subprocess.run(
            [sys.executable, str(SCRIPTS / "aggregate_results.py"), "--protocol", str(PROTOCOL), "--jobs", str(FULL_JOBS), "--results", str(self.tmp / "missing.tsv"), "--out", str(out)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(json.loads(out.read_text())["status"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
