#!/usr/bin/env python3
"""Tests for the frozen-panel P2/P3/P4 enrichment gate."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SCRIPT = ROOT / "scripts/analyze_p2_p3_p4_enrichment.py"
GUARD = ROOT / "scripts/guard_next_generation.py"
CONFIG = ROOT / "config/next_generation_gate_spec.json"
STABILITY_CONFIG = ROOT / "config/evaluator_stability_gate.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class EnrichmentGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        for rel in ("config", "inputs", "reports", "manifests"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "config/next_generation_gate_spec.json").write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
        (self.root / "config/evaluator_stability_gate.json").write_text(
            STABILITY_CONFIG.read_text(encoding="utf-8"), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def run_gate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, str(SCRIPT), "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_guard(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, str(GUARD), "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def seed_fixture(self, mode: str = "pass", evaluator_status: str = "PASS") -> None:
        candidates: list[dict[str, str]] = []
        phase_counts = {"P1": 22, "P2": 21, "P3": 24, "P4": 23, "P5": 23, "P6": 15}
        for phase, count in phase_counts.items():
            for index in range(1, count + 1):
                candidate_id = f"PVRIG_RFAb_v2_{phase}_qkg_L_bb{index:03d}_mpn00"
                candidates.append({"candidate_id": candidate_id, "arm_id": f"{phase}_qkg_L"})
        write_tsv(self.root / "inputs/candidates_128.tsv", candidates, ["candidate_id", "arm_id"])

        if mode == "pass":
            robust_limits = {"P1": 1, "P2": 12, "P3": 2, "P4": 2, "P5": 2, "P6": 1}
        elif mode == "fail":
            robust_limits = {phase: 3 for phase in phase_counts}
        else:
            raise ValueError(mode)

        jobs: list[dict[str, str]] = []
        results: list[dict[str, str]] = []
        seeds = ["917", "1931", "3253"]
        conformations = ["8x6b", "9e6y"]
        phase_seen = {phase: 0 for phase in phase_counts}
        for candidate in candidates:
            phase = candidate["arm_id"].split("_", 1)[0]
            phase_seen[phase] += 1
            is_robust = phase_seen[phase] <= robust_limits[phase]
            for conformation in conformations:
                for seed_index, seed in enumerate(seeds):
                    job_id = f"{candidate['candidate_id']}_{conformation}_s{seed}"
                    jobs.append(
                        {
                            "job_id": job_id,
                            "entity_type": "candidate",
                            "entity_id": candidate["candidate_id"],
                            "conformation": conformation,
                            "seed": seed,
                            "protocol_core_sha256": "a" * 64,
                            "protocol_hash": "a" * 64,
                            "job_hash": hashlib.sha256(job_id.encode()).hexdigest(),
                        }
                    )
                    supports = is_robust and seed_index < 2
                    geometry = "A" if supports else "C"
                    results.append(
                        {
                            "job_id": job_id,
                            "entity_id": candidate["candidate_id"],
                            "entity_type": "candidate",
                            "control_class": "",
                            "expected_behavior": "",
                            "conformation": conformation,
                            "seed": seed,
                            "state": "SUCCESS",
                            "selected_model_count": "4",
                            "pose_score_model_count": "4",
                            "pose_backed_2x2": "true",
                            "representative_model": "cluster_1_model_1.pdb",
                            "haddock_score": "-10.0",
                            "air_energy": "1.0",
                            "native_class": geometry,
                            "cross_class": geometry,
                            "model_pair_consensus_fraction": "0.80" if supports else "0.50",
                            "model_strict_a_fraction": "0.75" if supports else "0.0",
                            "job_hash": hashlib.sha256(job_id.encode()).hexdigest(),
                        }
                    )
        write_tsv(
            self.root / "manifests/docking_jobs.tsv",
            jobs,
            ["job_id", "entity_type", "entity_id", "conformation", "seed", "protocol_core_sha256", "protocol_hash", "job_hash"],
        )
        write_tsv(
            self.root / "reports/job_results.tsv",
            results,
            [
                "job_id",
                "entity_id",
                "entity_type",
                "control_class",
                "expected_behavior",
                "conformation",
                "seed",
                "state",
                "selected_model_count",
                "pose_score_model_count",
                "pose_backed_2x2",
                "representative_model",
                "haddock_score",
                "air_energy",
                "native_class",
                "cross_class",
                "model_pair_consensus_fraction",
                "model_strict_a_fraction",
                "job_hash",
            ],
        )
        (self.root / "reports/pose_scores.tsv").write_text("job_id\n", encoding="utf-8")
        core_lock = {
            "status": "CORE_LOCKED",
            "protocol_core_sha256": "a" * 64,
            "files": [
                {
                    "path": "inputs/candidates_128.tsv",
                    "sha256": sha256_file(self.root / "inputs/candidates_128.tsv"),
                }
            ],
        }
        (self.root / "PROTOCOL_CORE_LOCK.json").write_text(
            json.dumps(core_lock, sort_keys=True), encoding="utf-8"
        )
        manifest_sha = sha256_file(self.root / "manifests/docking_jobs.tsv")
        lock = {
            "status": "LOCKED",
            "protocol_core_sha256": "a" * 64,
            "protocol_lock_sha256": "b" * 64,
            "core_lock_sha256": sha256_file(self.root / "PROTOCOL_CORE_LOCK.json"),
            "job_manifest_sha256": manifest_sha,
            "files": [
                {
                    "path": "config/next_generation_gate_spec.json",
                    "sha256": sha256_file(self.root / "config/next_generation_gate_spec.json"),
                },
                {
                    "path": "config/evaluator_stability_gate.json",
                    "sha256": sha256_file(self.root / "config/evaluator_stability_gate.json"),
                },
            ],
        }
        (self.root / "PROTOCOL_LOCK.json").write_text(json.dumps(lock, sort_keys=True), encoding="utf-8")
        evaluator = {
            "status": evaluator_status,
            "unlockable": evaluator_status == "PASS",
            "evidence_mode": "production_pose_backed",
            "protocol_core_sha256": "a" * 64,
            "protocol_core_lock_file_sha256": sha256_file(self.root / "PROTOCOL_CORE_LOCK.json"),
            "protocol_lock_sha256": "b" * 64,
            "protocol_lock_file_sha256": sha256_file(self.root / "PROTOCOL_LOCK.json"),
            "job_manifest_sha256": manifest_sha,
            "candidates_sha256": sha256_file(self.root / "inputs/candidates_128.tsv"),
            "job_results_sha256": sha256_file(self.root / "reports/job_results.tsv"),
            "pose_scores_sha256": sha256_file(self.root / "reports/pose_scores.tsv"),
            "stability_gate_spec_sha256": sha256_file(
                self.root / "config/evaluator_stability_gate.json"
            ),
            "gates": {"all": {"status": evaluator_status, "reasons": []}},
        }
        (self.root / "reports/EVALUATOR_STABLE.json").write_text(json.dumps(evaluator, sort_keys=True), encoding="utf-8")

    def test_evaluator_not_ready_blocks_analysis(self) -> None:
        self.seed_fixture(mode="pass", evaluator_status="NOT_READY")
        process = self.run_gate()
        self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
        payload = json.loads((self.root / "reports/P2_P3_P4_ENRICHMENT.json").read_text())
        self.assertEqual(payload["status"], "NOT_READY")
        self.assertTrue(any("evaluator_status_not_pass" in reason for reason in payload["reasons"]))

    def test_constructed_p2_strong_enrichment_passes(self) -> None:
        self.seed_fixture(mode="pass")
        process = self.run_gate()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        payload = json.loads((self.root / "reports/P2_P3_P4_ENRICHMENT.json").read_text())
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["eligible_phases"], ["P2"])
        p2 = next(row for row in payload["phase_results"] if row["phase"] == "P2")
        self.assertGreaterEqual(p2["risk_difference"], 0.1)
        self.assertLessEqual(p2["holm_adjusted_p"], 0.1)

    def test_guard_recomputes_and_accepts_exact_p2_enrichment(self) -> None:
        self.seed_fixture(mode="pass")
        gate = self.run_gate()
        self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)
        guard = self.run_guard()
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)
        self.assertIn('"status": "UNLOCKED"', guard.stdout)

    def test_guard_rejects_result_drift_after_enrichment(self) -> None:
        self.seed_fixture(mode="pass")
        self.assertEqual(self.run_gate().returncode, 0)
        with (self.root / "reports/job_results.tsv").open("a", encoding="utf-8") as handle:
            handle.write("# drift\n")
        guard = self.run_guard()
        self.assertNotEqual(guard.returncode, 0)
        self.assertIn("evaluator_job_results_sha256_mismatch", guard.stderr)

    def test_complete_production_data_without_enrichment_fails(self) -> None:
        self.seed_fixture(mode="fail")
        process = self.run_gate()
        self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
        payload = json.loads((self.root / "reports/P2_P3_P4_ENRICHMENT.json").read_text())
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("complete_production_data_no_reliable_p2_p3_p4_enrichment", payload["reasons"])
        self.assertEqual(payload["eligible_phases"], [])

    def test_hash_mismatch_is_not_ready(self) -> None:
        self.seed_fixture(mode="pass")
        with (self.root / "manifests/docking_jobs.tsv").open("a", encoding="utf-8") as handle:
            handle.write("# drift\n")
        process = self.run_gate()
        self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
        payload = json.loads((self.root / "reports/P2_P3_P4_ENRICHMENT.json").read_text())
        self.assertEqual(payload["status"], "NOT_READY")
        self.assertIn("job_manifest_sha256_mismatch", payload["reasons"])


if __name__ == "__main__":
    unittest.main()
