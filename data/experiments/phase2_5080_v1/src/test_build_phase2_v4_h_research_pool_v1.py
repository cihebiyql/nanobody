#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_phase2_v4_h_research_pool_v1.py")
SPEC = importlib.util.spec_from_file_location("research_pool", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ResearchStateTests(unittest.TestCase):
    def test_hard_pass_is_research_ready(self) -> None:
        state, reason = MODULE.research_state(
            {}, {"full_qc_state": "HARD_PASS", "parent_framework_cluster": "C0162"}, {}
        )
        self.assertEqual(state, "RESEARCH_READY")
        self.assertIn("hard_pass", reason)

    def test_c0371_missing_n_terminal_is_quarantined_not_mutated(self) -> None:
        state, reason = MODULE.research_state(
            {},
            {"full_qc_state": "HARD_FAIL", "parent_framework_cluster": "C0371"},
            {"official_validator_failed_reason": "missing_n_terminal"},
        )
        self.assertEqual(state, "QUARANTINE_REPAIRABLE_PARENT_N_TERMINUS")
        self.assertIn("new_versioned", reason)

    def test_other_hard_fail_stays_quarantined(self) -> None:
        state, reason = MODULE.research_state(
            {},
            {"full_qc_state": "HARD_FAIL", "parent_framework_cluster": "C9999"},
            {
                "official_validator_failed_reason": "invalid_sequence",
                "reason_summary": "invalid_sequence",
            },
        )
        self.assertEqual(state, "QUARANTINE_OTHER_QC")
        self.assertEqual(reason, "invalid_sequence")

    def test_text_hash_is_stable(self) -> None:
        self.assertEqual(
            MODULE.sha256_text("QVQL"),
            "40284552a0c1e0630e2634b159453e2ccfb5f5e88997b360a30f64523b3bc125",
        )


if __name__ == "__main__":
    unittest.main()
