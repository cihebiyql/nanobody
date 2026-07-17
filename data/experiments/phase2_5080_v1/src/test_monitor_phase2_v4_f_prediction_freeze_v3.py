#!/usr/bin/env python3
"""Functional fail-closed tests for the V4-F prediction watcher V3."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent
SCRIPT = SRC / "monitor_phase2_v4_f_prediction_freeze_v3.sh"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class Fixture:
    def __init__(self, root: Path) -> None:
        self.exp = root / "exp"
        self.exp.mkdir()
        self.surrogate_dir = (
            self.exp / "status/pvrig_v4_d_surrogate_training_v3"
        )
        self.surrogate_status = self.surrogate_dir / "status.json"
        self.surrogate_receipt = (
            self.surrogate_dir / "surrogate_v3_completion_receipt.json"
        )
        self.v4f_status = (
            self.exp / "status/pvrig_v4_f_prediction_freeze_v3/status.json"
        )
        self.output = self.exp / "predictions/pvrig_v4_f_surrogate_predictions_v1"
        self.marker = self.exp / "freezer_was_called"
        self.freezer = self.exp / "freezer_stub.py"
        self.freezer.write_text(
            "from pathlib import Path\n"
            "import os, sys\n"
            "Path(os.environ['FREEZER_MARKER']).write_text('called\\n')\n"
            "raise SystemExit(97)\n",
            encoding="utf-8",
        )
        write_json(
            self.surrogate_status,
            {
                "status": "WAITING_OPEN_TEACHER",
                "prospective_test_labels_read": False,
                "prospective_test_label_paths_accepted": 0,
            },
        )

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for variable in (
            "V4F_V3_TRUST_ANCHOR",
            "V4F_V3_EXPECTED_TRUST_ANCHOR_SHA",
            "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA",
            "BASH_ENV",
            "PYTHONPATH",
        ):
            environment.pop(variable, None)
        environment.update(
            {
                "PVRIG_EXP_DIR": str(self.exp),
                "PYTHON": sys.executable,
                "V4F_PREDICTION_FREEZER": str(self.freezer),
                "PVRIG_V4F_WATCHER_V3_TEST_ONLY": "1",
                "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS": "1",
                "V4D_SURROGATE_STATUS": str(self.surrogate_status),
                "V4D_SURROGATE_V3_COMPLETION_RECEIPT": str(
                    self.surrogate_receipt
                ),
                "FREEZER_MARKER": str(self.marker),
                "PYTHONOPTIMIZE": "0",
                "ONCE": "1",
                "POLL_SECONDS": "1",
                "MAX_WAIT_SECONDS": "10",
                "FREEZE_TIMEOUT_SECONDS": "10",
            }
        )
        return environment

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT)],
            env=self.environment(),
            text=True,
            capture_output=True,
        )

    def status(self) -> dict[str, object]:
        return json.loads(self.v4f_status.read_text(encoding="utf-8"))

    def write_forged_completion(self) -> None:
        write_json(
            self.surrogate_status,
            {
                "status": "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED",
                "prospective_test_labels_read": False,
                "prospective_test_label_paths_accepted": 0,
            },
        )
        stages: dict[str, dict[str, str]] = {}
        for name in ("base_stage", "embedding_stage", "contact_stage"):
            path = self.surrogate_dir / f"{name}.json"
            write_json(
                path,
                {
                    "status": f"PASS_FORGED_{name.upper()}",
                    "prospective_test_labels_read": False,
                },
            )
            stages[name] = {"path": str(path.resolve()), "sha256": sha256(path)}
        # Preserve the expected schema and stage paths, but forge one bound digest.
        stages["contact_stage"]["sha256"] = "0" * 64
        write_json(
            self.surrogate_receipt,
            {
                "schema_version": "phase2_v4_d_surrogate_v3_completion_receipt_v1",
                "status": "PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED",
                "implementation_trust_anchor_sha256": "",
                "prospective_test_labels_read": False,
                "prospective_test_label_paths_accepted": 0,
                "stage_receipts": stages,
            },
        )


class V4FPredictionWatcherV3FunctionalTests(unittest.TestCase):
    def test_waiting_upstream_keeps_labels_outputs_and_freezer_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            result = fixture.run()
            self.assertEqual(result.returncode, 4, result.stderr)
            status = fixture.status()
            self.assertEqual(status["status"], "WAITING_V4_D_SURROGATES")
            self.assertIs(status["v4_f_labels_read"], False)
            self.assertEqual(status["v4_f_label_paths_accepted"], 0)
            self.assertFalse(fixture.marker.exists())
            self.assertFalse(fixture.output.exists())

    def test_forged_surrogate_completion_receipt_is_rejected_before_freezer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.write_forged_completion()
            result = fixture.run()
            self.assertEqual(result.returncode, 2, result.stderr)
            status = fixture.status()
            self.assertEqual(
                status["status"], "BLOCKED_INVALID_SURROGATE_V3_RECEIPT"
            )
            self.assertIs(status["v4_f_labels_read"], False)
            self.assertEqual(status["v4_f_label_paths_accepted"], 0)
            self.assertFalse(fixture.marker.exists())
            self.assertFalse(fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
