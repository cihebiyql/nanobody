#!/usr/bin/env python3
from __future__ import annotations

import unittest

from verify_pvrig_v4d_evaluator_release import REQUIRED_GATES, assess


def evaluator(*, failed: int = 0) -> dict:
    gates = {name: {"status": "PASS"} for name in REQUIRED_GATES}
    gates["all_jobs_terminal"]["counts"] = {
        "SUCCESS": 2022 - failed,
        "FAILED_MAX_ATTEMPTS": failed,
    }
    gates["other_preregistered_gate"] = {"status": "PASS"}
    return {
        "status": "PASS",
        "unlockable": True,
        "evidence_mode": "production_pose_backed",
        "job_count": 2022,
        "gates": gates,
    }


class EvaluatorReleaseTests(unittest.TestCase):
    def test_allows_terminal_technical_failure_only_when_all_gates_pass(self) -> None:
        result = assess(evaluator(failed=1), 2022)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["failed_max_attempts"], 1)

    def test_blocks_any_failed_preregistered_gate(self) -> None:
        payload = evaluator(failed=1)
        payload["gates"]["other_preregistered_gate"] = {"status": "FAIL"}
        result = assess(payload, 2022)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("gate_not_pass:other_preregistered_gate", result["reason"])

    def test_blocks_missing_required_gate(self) -> None:
        payload = evaluator()
        del payload["gates"]["minimum_completed_seeds_per_entity_conformation"]
        result = assess(payload, 2022)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("required_gate_missing", result["reason"])

    def test_blocks_non_pose_backed_or_wrong_job_count(self) -> None:
        payload = evaluator()
        payload["evidence_mode"] = "synthetic"
        payload["job_count"] = 2021
        result = assess(payload, 2022)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("evidence_mode_not_production_pose_backed", result["reason"])
        self.assertIn("job_count_mismatch", result["reason"])


if __name__ == "__main__":
    unittest.main()
