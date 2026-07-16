#!/usr/bin/env python3
"""Regression tests for protocol validation and the next-generation hard gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
                    "selected_model_count": "4",
                    "pose_score_model_count": "4",
                    "pose_backed_2x2": "true",
                    "representative_model": "cluster_1_model_1.pdb",
                    "haddock_score": "-10.0",
                    "native_class": geometry_class,
                    "cross_class": geometry_class,
                    "representative_pair_label": "STRICT_A" if geometry_class == "A" else "OTHER",
                    "model_pair_consensus_fraction": "1.0",
                    "model_native_cross_support_agreement_fraction": "1.0",
                    "model_strict_a_fraction": "1.0" if geometry_class == "A" else "0.0",
                    "anomaly_flag": "false",
                    "job_hash": row["job_hash"],
                }
            )
        return output

    def write_pose_scores(self, jobs: list[dict[str, str]], path: Path, positive_class: str = "A") -> None:
        output = []
        for job in jobs:
            is_a = job["control_class"] == "positive_control" and positive_class == "A"
            for model_index in range(1, 5):
                for reference in ("8x6b", "9e6y"):
                    output.append(
                        {
                            "job_id": job["job_id"],
                            "entity_id": job["entity_id"],
                            "entity_type": job["entity_type"],
                            "control_class": job["control_class"],
                            "dock_conformation": job["conformation"],
                            "scoring_reference": reference,
                            "seed": job["seed"],
                            "model": f"cluster_1_model_{model_index}.pdb",
                            "haddock_score": "-10.0",
                            "air_energy": "0.0",
                            "geometry_class": "A" if is_a else "E",
                            "geometry_margin": "1.2" if is_a else "0.1",
                            "hotspot_overlap": "18" if is_a else "2",
                            "anchor_overlap": "10" if is_a else "1",
                            "holdout_overlap": "8" if is_a else "1",
                            "total_occlusion": "700" if is_a else "20",
                            "cdr3_occlusion": "150" if is_a else "2",
                            "cdr3_fraction": "0.25" if is_a else "0.05",
                            "clash_atom_pairs": "0",
                            "clash_residue_pairs": "0",
                            "overlay_rmsd_a": "0.0",
                        }
                    )
        write_tsv(path, output, list(output[0]))

    def test_current_full_protocol_and_job_manifest_validate(self) -> None:
        out = self.tmp / "validation.json"
        code = validate_protocol.main(["--protocol", str(PROTOCOL), "--jobs", str(FULL_JOBS), "--out", str(out)])
        self.assertEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["job_count"], 2022)

    def test_validate_protocol_reports_not_ready_without_jobs(self) -> None:
        out = self.tmp / "validation.json"
        code = validate_protocol.main(["--protocol", str(PROTOCOL), "--jobs", str(self.tmp / "missing.tsv"), "--out", str(out)])
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out.read_text())["status"], "NOT_READY")

    def test_core_lock_validation_detects_frozen_file_drift(self) -> None:
        project = self.tmp / "core_project"
        frozen = project / "inputs/frozen.txt"
        frozen.parent.mkdir(parents=True)
        frozen.write_text("locked\n", encoding="utf-8")
        core_hash = "a" * 64
        lock = {
            "status": "CORE_LOCKED",
            "protocol_core_sha256": core_hash,
            "files": [{"path": "inputs/frozen.txt", "sha256": sha256_file(frozen)}],
        }
        (project / "PROTOCOL_CORE_LOCK.json").write_text(json.dumps(lock), encoding="utf-8")
        rows = [{"protocol_core_sha256": core_hash}]
        self.assertEqual(validate_protocol.validate_core_lock(project, rows)["status"], "PASS")
        frozen.write_text("drifted\n", encoding="utf-8")
        payload = validate_protocol.validate_core_lock(project, rows)
        self.assertEqual(payload["status"], "FAIL")
        self.assertTrue(any(reason.startswith("core_files_drifted:") for reason in payload["reasons"]))

    def test_final_lock_validation_detects_frozen_script_drift(self) -> None:
        project = self.tmp / "final_project"
        script = project / "scripts/frozen.py"
        manifest = project / "manifests/docking_jobs.tsv"
        script.parent.mkdir(parents=True)
        manifest.parent.mkdir(parents=True)
        script.write_text("print('locked')\n", encoding="utf-8")
        manifest.write_text("job_id\n", encoding="utf-8")
        core = project / "PROTOCOL_CORE_LOCK.json"
        core.write_text("{}\n", encoding="utf-8")
        lock = {
            "status": "LOCKED",
            "protocol_lock_sha256": "b" * 64,
            "core_lock_sha256": sha256_file(core),
            "job_manifest_sha256": sha256_file(manifest),
            "files": [{"path": "scripts/frozen.py", "sha256": sha256_file(script)}],
        }
        (project / "PROTOCOL_LOCK.json").write_text(json.dumps(lock), encoding="utf-8")
        self.assertEqual(validate_protocol.validate_final_lock(project)["status"], "PASS")
        script.write_text("print('drifted')\n", encoding="utf-8")
        payload = validate_protocol.validate_final_lock(project)
        self.assertEqual(payload["status"], "FAIL")
        self.assertTrue(any(reason.startswith("final_protocol_files_drifted:") for reason in payload["reasons"]))

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
        self.write_pose_scores(jobs, self.tmp / "pose_scores.tsv")
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
        self.write_pose_scores(jobs, self.tmp / "pose_scores.tsv", positive_class="E")
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["gates"]["positive_control_robust_support"]["status"], "FAIL")

    def test_aggregate_fails_when_destructive_controls_robustly_retain_a(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        for row in results:
            if row["control_class"] == "destructive_alanine":
                row.update(
                    {
                        "native_class": "A",
                        "cross_class": "A",
                        "representative_pair_label": "STRICT_A",
                        "model_strict_a_fraction": "1.0",
                        "anomaly_flag": "true",
                    }
                )
        write_tsv(result_path, results, list(results[0]))
        self.write_pose_scores(jobs, self.tmp / "pose_scores.tsv")
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["gates"]["destructive_control_strict_a_retention"]["status"], "FAIL")

    def test_aggregate_fails_when_control_seed_classes_do_not_reproduce(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        broken_ids = sorted({row["entity_id"] for row in results if row["entity_type"] == "control"})[:35]
        class_by_seed = {"917": "A", "1931": "B", "3253": "C"}
        for row in results:
            if row["entity_id"] in broken_ids and row["conformation"] == "8x6b":
                geometry_class = class_by_seed[row["seed"]]
                row["native_class"] = geometry_class
                row["cross_class"] = geometry_class
        write_tsv(result_path, results, list(results[0]))
        self.write_pose_scores(jobs, self.tmp / "pose_scores.tsv")
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["gates"]["control_seed_class_reproducibility"]["status"], "FAIL")

    def test_aggregate_fails_when_candidate_a_calls_are_threshold_fragile(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        pose_path = self.tmp / "pose_scores.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        write_tsv(result_path, results, list(results[0]))
        self.write_pose_scores(jobs, pose_path)
        pose_rows = read_tsv(pose_path)
        for row in pose_rows:
            if row["entity_type"] == "candidate":
                row.update(
                    {
                        "hotspot_overlap": "13",
                        "total_occlusion": "460",
                        "cdr3_occlusion": "90",
                        "cdr3_fraction": "0.14",
                    }
                )
        write_tsv(pose_path, pose_rows, list(pose_rows[0]))
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["gates"]["candidate_threshold_sensitivity"]["status"], "FAIL")

    def test_aggregate_fails_when_candidate_success_has_only_one_pose_model(self) -> None:
        jobs = self.reduced_valid_jobs()
        job_path = self.tmp / "jobs.tsv"
        result_path = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(job_path, jobs, list(jobs[0]))
        results = self.passing_results(jobs)
        candidate = next(row for row in results if row["entity_type"] == "candidate")
        candidate["selected_model_count"] = "1"
        candidate["pose_score_model_count"] = "1"
        write_tsv(result_path, results, list(results[0]))
        self.write_pose_scores(jobs, self.tmp / "pose_scores.tsv")
        code = aggregate_results.main(
            ["--protocol", str(PROTOCOL), "--jobs", str(job_path), "--results", str(result_path), "--out", str(out), "--expected-total-jobs", str(len(jobs)), "--allow-synthetic-results"]
        )
        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["gates"]["all_successful_jobs_have_minimum_pose_models"]["status"], "FAIL")

    def test_guard_rejects_incomplete_handwritten_unlock_reports(self) -> None:
        project = self.tmp / "project"
        (project / "reports").mkdir(parents=True)
        (project / "manifests").mkdir(parents=True)
        (project / "config").mkdir(parents=True)
        stability_spec = project / "config/evaluator_stability_gate.json"
        enrichment_spec = project / "config/next_generation_gate_spec.json"
        stability_spec.write_text("{}\n", encoding="utf-8")
        enrichment_spec.write_text(
            json.dumps({"gate_id": "test_gate", "inference_scope": "test_scope"}), encoding="utf-8"
        )
        manifest = project / "manifests/docking_jobs.tsv"
        manifest.write_text("job_id\njob1\n", encoding="utf-8")
        manifest_sha = sha256_file(manifest)
        lock = {
            "status": "LOCKED",
            "protocol_core_sha256": "a" * 64,
            "protocol_lock_sha256": "b" * 64,
            "job_manifest_sha256": manifest_sha,
            "files": [
                {"path": "config/evaluator_stability_gate.json", "sha256": sha256_file(stability_spec)},
                {"path": "config/next_generation_gate_spec.json", "sha256": sha256_file(enrichment_spec)},
            ],
        }
        lock_path = project / "PROTOCOL_LOCK.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        evaluator = {
            "status": "PASS",
            "unlockable": True,
            "evidence_mode": "production_pose_backed",
            "protocol_core_sha256": "a" * 64,
            "protocol_lock_sha256": "b" * 64,
            "protocol_lock_file_sha256": sha256_file(lock_path),
            "job_manifest_sha256": manifest_sha,
            "stability_gate_spec_sha256": sha256_file(stability_spec),
            "gates": {"all": {"status": "PASS"}},
        }
        evaluator_path = project / "reports/EVALUATOR_STABLE.json"
        evaluator_path.write_text(json.dumps(evaluator), encoding="utf-8")
        enrichment = {
            "status": "PASS",
            "unlockable": True,
            "evidence_mode": "production_pose_backed",
            "gate_id": "test_gate",
            "inference_scope": "test_scope",
            "eligible_phases": ["P2"],
            "phase_results": [{"phase": "P2", "eligible": "true"}],
            "gate_spec_file_sha256": sha256_file(enrichment_spec),
            "bindings": {
                "evaluator_file_sha256": sha256_file(evaluator_path),
                "evaluator_evidence_mode": "production_pose_backed",
                "evaluator_unlockable": True,
                "protocol_core_sha256": "a" * 64,
                "protocol_lock_sha256": "b" * 64,
                "protocol_lock_file_sha256": sha256_file(lock_path),
                "job_manifest_sha256": manifest_sha,
            },
        }
        (project / "reports/P2_P3_P4_ENRICHMENT.json").write_text(json.dumps(enrichment), encoding="utf-8")
        self.assertNotEqual(guard_next_generation.main(["--root", str(project)]), 0)
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
        payload = json.loads(out.read_text())
        self.assertEqual(payload["status"], "NOT_READY")
        self.assertEqual(payload["gates"]["complete_2x2_scoring"]["status"], "NOT_READY")
        self.assertEqual(payload["gates"]["candidate_threshold_sensitivity"]["status"], "NOT_READY")

    def test_aggregate_cli_is_nonzero_when_enrichment_does_not_pass(self) -> None:
        payload = {"status": "PASS", "evidence_mode": "production_pose_backed"}
        with mock.patch.object(aggregate_results, "aggregate", return_value=payload), mock.patch.object(
            aggregate_results.subprocess, "run", return_value=mock.Mock(returncode=1)
        ):
            code = aggregate_results.main(["--protocol", str(PROTOCOL)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
