from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class Node23ReadonlyLauncherTests(unittest.TestCase):
    def test_remote_runner_pins_raw_root_and_keeps_output_separate(self) -> None:
        text = (ROOT / "launchers/node23_readonly_runner.sh").read_text(encoding="utf-8")
        self.assertIn("/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717", text)
        self.assertIn('OUTPUT_DIR="$PROJECT_ROOT/output"', text)
        self.assertIn('[[ "$OUTPUT_DIR" != "$RAW_ROOT"/* ]]', text)
        self.assertIn("--dry-run", text)
        self.assertIn("tmux new-session", text)
        self.assertNotIn("rm -", text)
        self.assertNotIn("unlink", text)
        self.assertNotIn("--delete", text)

    def test_deployer_transfers_only_compact_terminal_package_and_code(self) -> None:
        text = (ROOT / "launchers/deploy_and_launch_node23.sh").read_text(encoding="utf-8")
        self.assertIn("stage1_all_seed917.terminal.json", text)
        self.assertIn("stage1_seed917_ranking.tsv", text)
        self.assertIn("stage1_failures.tsv", text)
        self.assertIn("DEPLOYMENT_SHA256SUMS", text)
        self.assertNotIn("runs/", text)
        self.assertNotIn("results/", text)
        self.assertNotIn("rm -", text)
        self.assertNotIn("--delete", text)


if __name__ == "__main__":
    unittest.main()
