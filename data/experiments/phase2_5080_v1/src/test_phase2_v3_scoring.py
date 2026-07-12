#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_pvrig_candidates_v3 import candidate_lane  # noqa: E402


class Phase2V3ScoringTests(unittest.TestCase):
    def test_candidate_lanes_keep_calibration_out_of_screening(self) -> None:
        self.assertEqual(candidate_lane("de_novo_binding_and_competition_screen"), "PROSPECTIVE_SCREENING")
        self.assertEqual(candidate_lane("known_positive_reference"), "CALIBRATION_ONLY")
        self.assertEqual(candidate_lane("conservative_mutant"), "PAIRED_MUTATION_ANALYSIS")
        self.assertEqual(
            candidate_lane("negative_verification_candidate_not_current_negative"),
            "UNVERIFIED_DESIGNED_CONTROL",
        )


if __name__ == "__main__":
    unittest.main()
