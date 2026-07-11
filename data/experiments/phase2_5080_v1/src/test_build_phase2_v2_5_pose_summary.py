from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_phase2_v2_5_pose_summary import build_summary, load_gate_evidence, parse_args, run


class Phase2V25PoseSummaryTests(unittest.TestCase):
    def test_real_synced_batch_keeps_complex_coverage_separate_from_monomer_qc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = parse_args([
                "--csv-out", str(root / "pose.csv"),
                "--audit-out", str(root / "pose.json"),
                "--report-out", str(root / "pose.md"),
            ])
            frame, audit = build_summary(args)
            self.assertEqual(len(frame), 50)
            self.assertEqual(int(frame["exact_qc_passed"].sum()), 2)
            selected = frame[frame["selected_for_v2_5_batch"]]
            self.assertEqual(len(selected), 8)
            self.assertTrue(selected["monomer_sequence_exact_match"].all())
            self.assertTrue(selected["monomer_qc_status"].eq("pass").all())
            self.assertAlmostEqual(audit["exact_qc_passed_coverage"], 0.04)
            self.assertFalse(audit["global_fusion_applied"])
            self.assertEqual(audit["haddock3_status"], "GATED_NOT_RUN_DUE_NODE1_LOAD")
            self.assertAlmostEqual(audit["haddock3_load_gate_evidence"]["observed_load1"], 106.98)
            self.assertAlmostEqual(audit["haddock3_load_gate_evidence"]["threshold"], 64.0)
            run(args)
            self.assertTrue((root / "pose.csv").exists())

    def test_latest_log_cannot_be_overridden_by_older_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            remote = Path(tmp)
            logs = remote / "logs"
            logs.mkdir()
            (logs / "run_node1_v2_5_pose_batch.20260711_120000.log").write_text(
                "LOAD_GATE_REFUSE load1=100.0 threshold=64.0\n", encoding="utf-8"
            )
            newest = logs / "run_node1_v2_5_pose_batch.20260711_130000.log"
            newest.write_text("HADDOCK_RUN_COMPLETED\n", encoding="utf-8")
            evidence = load_gate_evidence(remote)
            self.assertEqual(evidence["status"], "LATEST_LOG_HAS_NO_LOAD_GATE_REFUSAL")
            self.assertEqual(evidence["log_path"], str(newest))


if __name__ == "__main__":
    unittest.main()
