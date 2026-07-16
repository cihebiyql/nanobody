#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
WATCHER = SCRIPT_DIR / "monitor_phase2_v4_d_deployment_scoring.sh"


class DeploymentWatcherTest(unittest.TestCase):
    def make_environment(
        self, root: Path, surrogate_status: str, scorer_status: str
    ) -> tuple[dict[str, str], Path, Path]:
        status_path = root / "surrogate_status.json"
        status_path.write_text(json.dumps({"status": surrogate_status}) + "\n")
        call_log = root / "scorer_calls.txt"
        scorer = root / "stub_scorer.py"
        scorer.write_text(
            """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log = Path(os.environ['STUB_CALL_LOG'])
verify = '--verify-only' in sys.argv
with log.open('a', encoding='utf-8') as handle:
    handle.write(('verify' if verify else 'run') + '\\n')
if verify:
    print(json.dumps({'status': 'PASS_DEPLOYMENT_RELEASE_HASH_CLOSURE'}))
else:
    print(json.dumps({'status': os.environ['STUB_SCORER_STATUS']}))
""",
            encoding="utf-8",
        )
        scorer.chmod(0o755)
        watcher_status_dir = root / "watcher_status"
        environment = {
            **os.environ,
            "PVRIG_EXP_DIR": str(root),
            "PYTHON": sys.executable,
            "V4D_DEPLOYMENT_SCORER": str(scorer),
            "V4D_SURROGATE_STATUS": str(status_path),
            "V4D_DEPLOYMENT_OUT": str(root / "deployment_out"),
            "V4D_DEPLOYMENT_STATUS_DIR": str(watcher_status_dir),
            "STUB_CALL_LOG": str(call_log),
            "STUB_SCORER_STATUS": scorer_status,
            "ONCE": "1",
            "POLL_SECONDS": "1",
        }
        return environment, call_log, watcher_status_dir / "status.json"

    def test_once_waits_without_invoking_scorer_before_surrogate_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, call_log, watcher_status = self.make_environment(
                root, "WAITING_OPEN_TEACHER", "PASS_DEPLOYMENT_SCORES_ROUTED"
            )
            result = subprocess.run(
                [str(WATCHER)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertFalse(call_log.exists())
            payload = json.loads(watcher_status.read_text())
            self.assertEqual(payload["status"], "WAITING_SURROGATE_COMPLETE")
            self.assertFalse(payload["prospective_test_labels_read"])
            self.assertFalse(payload["v4f_labels_read"])

    def test_complete_surrogate_runs_scorer_then_verifies_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, call_log, watcher_status = self.make_environment(
                root,
                "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED",
                "PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED",
            )
            result = subprocess.run(
                [str(WATCHER)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(call_log.read_text().splitlines(), ["run", "verify"])
            self.assertEqual(
                json.loads(watcher_status.read_text())["status"],
                "COMPLETE_V4_D_DEPLOYMENT_SCORING",
            )

    def test_stale_complete_state_with_missing_artifacts_remains_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment, call_log, watcher_status = self.make_environment(
                root,
                "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED",
                "WAITING_FROZEN_MODEL_ARTIFACTS",
            )
            result = subprocess.run(
                [str(WATCHER)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertEqual(call_log.read_text().splitlines(), ["run"])
            self.assertEqual(
                json.loads(watcher_status.read_text())["status"],
                "WAITING_FROZEN_MODEL_ARTIFACTS",
            )


if __name__ == "__main__":
    unittest.main()
