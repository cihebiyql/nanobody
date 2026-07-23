import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MONITOR = ROOT / "monitor_and_launch_stage_a_v1_3_5.sh"
START = ROOT / "start_node1_stage_a_watcher_v1_3_5.sh"
DATA = ROOT.parents[3]
PACKAGE = (
    ROOT.parent
    / "v2_20_contact_shared_top5_challenger_v1_3_5_technical_recovery_20260723"
)
APPROVAL = (
    DATA
    / "reports/pvrig_v220_v135_python311_bxcpu_tests_v1_20260723"
    / "INDEPENDENT_STAGE_A_APPROVAL_V1_3_5.json"
)


class StageAWatcherTests(unittest.TestCase):
    def test_shell_syntax(self):
        for path in (MONITOR, START):
            subprocess.run(["bash", "-n", str(path)], check=True)

    def test_exact_freeze_and_approval_bindings(self):
        text = MONITOR.read_text()
        freeze = PACKAGE / "IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_5.json"
        expected_freeze = hashlib.sha256(freeze.read_bytes()).hexdigest()
        expected_approval = hashlib.sha256(APPROVAL.read_bytes()).hexdigest()
        self.assertIn(f'EXPECTED_FREEZE_SHA="{expected_freeze}"', text)
        self.assertIn(f'EXPECTED_APPROVAL_SHA="{expected_approval}"', text)
        self.assertIn("PASS_V1_3_5_INDEPENDENT_REVIEW_STAGE_A_PREFLIGHT_ONLY_AUTHORIZED", text)
        approval = json.loads(APPROVAL.read_text())
        self.assertFalse(approval["authorization"]["training_authorized"])
        self.assertFalse(approval["authorization"]["training_started"])

    def test_stage_a_only_and_fresh_remote_paths(self):
        text = MONITOR.read_text()
        self.assertIn("run_phase1_preflight_node1_v1_3_5.sh", text)
        self.assertIn("NODE1_V1_3_5_PREFLIGHT_RECEIPT.json", text)
        self.assertIn("test ! -e '$REMOTE_PACKAGE'", text)
        self.assertIn("test ! -e '$REMOTE_RUNTIME'", text)
        self.assertIn("test ! -e '$REMOTE_EVIDENCE'", text)
        self.assertNotIn("run_phase1_core_fold_pair_node1_v1_3_5.template.sh", text)
        self.assertNotIn("finalize_v220_v1_3_5_training_authorization.py", text)
        self.assertNotRegex(text, re.compile(r"\bsbatch\b"))

    def test_status_contract_keeps_training_forbidden(self):
        text = MONITOR.read_text()
        self.assertIn('"training_authorized": False', text)
        self.assertIn('"training_started": False', text)
        self.assertIn("WAITING_INDEPENDENT_STAGE_B_REVIEW", text)

    def test_start_uses_dedicated_tmux(self):
        text = START.read_text()
        self.assertIn('SESSION="pvrig-v220-v135-node1-stagea"', text)
        self.assertIn('tmux new-session -d -s "$SESSION"', text)
        self.assertIn("monitor_and_launch_stage_a_v1_3_5.sh", text)


if __name__ == "__main__":
    unittest.main()
