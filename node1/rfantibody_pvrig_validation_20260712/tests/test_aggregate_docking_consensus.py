from __future__ import annotations

import importlib.util
import unittest
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "aggregate_docking_consensus.py"
SPEC = importlib.util.spec_from_file_location("aggregate_docking_consensus", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AggregateDockingConsensusTest(unittest.TestCase):
    def test_high_requires_two_consensus_a_and_top_three_rank(self) -> None:
        classes = Counter({"CONSENSUS_BLOCKER_LIKE_A": 2})
        self.assertEqual(MODULE.candidate_label(classes, 3)[1], "FINAL_POSITIVE_HIGH")
        self.assertEqual(MODULE.candidate_label(classes, 4)[1], "FINAL_RECHECK_SINGLE_BASELINE")
        self.assertEqual(
            MODULE.candidate_label(Counter({"CONSENSUS_BLOCKER_LIKE_A": 1}), 1)[1],
            "FINAL_RECHECK_SINGLE_BASELINE",
        )

    def test_single_baseline_never_becomes_high(self) -> None:
        label = MODULE.candidate_label(Counter({"SINGLE_BASELINE_BLOCKER_RECHECK": 10}), None)[1]
        self.assertEqual(label, "FINAL_RECHECK_SINGLE_BASELINE")

    def test_plausible_and_binder_are_separate(self) -> None:
        self.assertEqual(
            MODULE.candidate_label(Counter({"BLOCKER_PLAUSIBLE_B": 1}), None)[1],
            "FINAL_POSITIVE_PLAUSIBLE",
        )
        self.assertEqual(
            MODULE.candidate_label(Counter({"BINDER_LIKE_C": 1}), None)[1],
            "FINAL_BINDER_NOT_BLOCKER",
        )

    def test_rf2_diagnostic_fallback_never_becomes_high(self) -> None:
        self.assertEqual(
            MODULE.apply_rf2_boundary(
                "FINAL_POSITIVE_HIGH",
                "RF2_DIAGNOSTIC_FALLBACK_NOT_STRICT_POSE_RECOVERY",
            ),
            "FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED",
        )


if __name__ == "__main__":
    unittest.main()
