from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "parse_rf2_outputs.py"
SPEC = importlib.util.spec_from_file_location("parse_rf2_outputs", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ParseRf2OutputsTest(unittest.TestCase):
    def test_pose_recovery_thresholds(self) -> None:
        scores = {
            "interaction_pae": 9.99,
            "pred_lddt": 0.8,
            "target_aligned_antibody_rmsd": 1.99,
            "target_aligned_cdr_rmsd": 1.99,
        }
        self.assertEqual(MODULE.classify(scores)[0], "RF2_POSE_RECOVERED")
        scores["interaction_pae"] = 10.0
        self.assertEqual(MODULE.classify(scores)[0], "RF2_LOW_INTERACTION_CONFIDENCE")

    def test_missing_target_aligned_metric_fails_closed(self) -> None:
        scores = {"interaction_pae": 5.0, "pred_lddt": 0.9}
        status, reason = MODULE.classify(scores)
        self.assertEqual(status, "RF2_FAILED_MISSING_METRICS")
        self.assertIn("target_aligned_antibody_rmsd", reason)

    def test_parses_score_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.pdb"
            path.write_text("ATOM      1\nSCORE interaction_pae: 8.29\nSCORE pred_lddt: 0.94\n")
            self.assertEqual(MODULE.parse_scores(path)["interaction_pae"], 8.29)


if __name__ == "__main__":
    unittest.main()

