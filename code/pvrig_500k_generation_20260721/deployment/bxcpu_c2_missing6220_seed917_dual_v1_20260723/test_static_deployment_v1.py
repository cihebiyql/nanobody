#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
OLD = HERE.parent / "bxcpu_top7500_25k_v1_20260722" / "compact_run_evidence.py"


class StaticDeploymentTests(unittest.TestCase):
    def test_compactor_is_exact_old_bytes(self) -> None:
        new = HERE / "compact_run_evidence.py"
        self.assertEqual(new.read_bytes(), OLD.read_bytes())
        self.assertEqual(hashlib.sha256(new.read_bytes()).hexdigest(),
                         "bb26f9eb282df07ddc409928385d31e8c1869bbcda995c243ee39d552e974a0d")

    def test_stage_upload_cannot_submit(self) -> None:
        text = (HERE / "stage_and_upload_no_submit_v1.sh").read_text()
        self.assertNotIn("sbatch", text)
        self.assertIn("FROZEN_INPUT_ANCHORS.json", text)

    def test_submit_resources_and_array_are_exact_old_contract(self) -> None:
        text = (HERE / "submit_c2_missing6220_12440_eight_nodes.sh").read_text()
        for token in ("--partition=amd_256q", "--cpus-per-task=64", "--mem=230G",
                      "--exclusive", "--time=24:00:00", "--array=1-8%8"):
            self.assertIn(token, text)
        self.assertIn("PVRIG_C2_NODE_CONCURRENCY=16", text)
        self.assertIn("INDEPENDENT_LAUNCH_APPROVAL.json", text)
        self.assertIn("APPROVED_TO_SUBMIT_EXACT_12440_JOBS", text)

    def test_worker_has_no_overlap_reuse_path(self) -> None:
        text = (HERE / "bxcpu_c2_missing6220_eight_node_worker.sh").read_text()
        self.assertIn("expected=1555", text)
        self.assertIn("NODE_CONCURRENCY", text)
        self.assertIn('d["overlap1280_reuse_authorized"] is False', text)
        self.assertNotIn("priority_top7500_dualreceptor_multiseed_handoff_v3", text)

    def test_relay_uses_new_campaign_only(self) -> None:
        text = (HERE / "sync_c2_missing6220_results_incremental.py").read_text()
        self.assertIn('"expected": 12440', text)
        self.assertNotIn('"expected": 25000', text)
        self.assertNotIn('"top7500_25k"', text)


if __name__ == "__main__":
    unittest.main()
