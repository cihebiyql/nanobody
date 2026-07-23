#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DeploymentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load("deployment_contract_v1", "deployment_contract_v1.py")

    def test_pending_anchor_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self.module.load_frozen_anchors(HERE / "PENDING_INPUT_ANCHORS.json")

    def test_terminal_semantics_match_old_v2(self) -> None:
        self.assertTrue(self.module.is_terminal_state("SUCCESS"))
        self.assertTrue(self.module.is_terminal_state("FAILED"))
        self.assertTrue(self.module.is_terminal_state("FAILED_MAX_ATTEMPTS"))
        self.assertFalse(self.module.is_terminal_state("RUNNING"))
        self.assertFalse(self.module.is_terminal_state("MISSING"))

    def test_exact_eight_equal_shards(self) -> None:
        rows = [{"job_id": f"j{i}", "priority": str(i + 1)} for i in range(24)]
        shards = self.module.split_contiguous(rows, shard_count=8)
        self.assertEqual([len(x) for x in shards], [3] * 8)
        self.assertEqual([r["job_id"] for x in shards for r in x], [r["job_id"] for r in rows])

    def test_production_counts_are_not_parameterized(self) -> None:
        self.assertEqual(self.module.EXPECTED_CANDIDATES, 6220)
        self.assertEqual(self.module.EXPECTED_JOBS, 12440)
        self.assertEqual(self.module.EXPECTED_SHARD_SIZES, (1555,) * 8)
        self.assertEqual(self.module.SEED, "917")
        self.assertEqual(self.module.CONFORMATIONS, {"8x6b", "9e6y"})

    def test_manifest_rejects_overlap_reuse_or_wrong_stage(self) -> None:
        base = {
            "job_id": "a_8x6b", "entity_type": "candidate", "entity_id": "a",
            "conformation": "8x6b", "seed": "917", "sequence_sha256": "1" * 64,
            "monomer_sha256": "2" * 64, "protocol_core_sha256": self.module.PROTOCOL_CORE,
            "cfg_hash": self.module.CFG_HASHES["8x6b"], "job_hash": "3" * 64,
            "docking_stage": "OLD_OVERLAP_REUSE", "priority": "1",
        }
        other = dict(base, job_id="a_9e6y", conformation="9e6y", priority="2",
                     cfg_hash=self.module.CFG_HASHES["9e6y"], job_hash="4" * 64)
        with self.assertRaisesRegex(ValueError, "docking_stage"):
            self.module.validate_manifest_rows([base, other], expected_candidates=1, expected_jobs=2)


if __name__ == "__main__":
    unittest.main()
