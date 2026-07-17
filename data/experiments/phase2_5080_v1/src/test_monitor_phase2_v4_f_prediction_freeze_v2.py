#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("monitor_phase2_v4_f_prediction_freeze_v2.sh")
FREEZER = Path(__file__).with_name("freeze_phase2_v4_f_surrogate_predictions.py")
EXP = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


class Fixture:
    def __init__(self, root: Path) -> None:
        self.exp = root / "exp"
        self.exp.mkdir()
        self.dependency = self.exp / "captured_dependency.py"
        self.dependency.write_text("VALUE = 1\n")
        self.anchor = self.exp / "v4f_anchor.json"
        self.write_anchor()
        self.surrogate_status = self.exp / "surrogate_status.json"
        self.surrogate_receipt = self.exp / "surrogate_receipt.json"
        write_json(
            self.surrogate_status,
            {"status": "WAITING_OPEN_TEACHER", "prospective_test_labels_read": False},
        )

    def write_anchor(self) -> None:
        write_json(
            self.anchor,
            {
                "schema_version": "phase2_v4_f_prediction_implementation_trust_anchor_v2",
                "status": "FROZEN_BEFORE_V4F_PREDICTION_FREEZE",
                "anchor_kind": "v4f_prediction_freeze",
                "files": {
                    "captured_dependency": {
                        "path": str(self.dependency.resolve()),
                        "size": self.dependency.stat().st_size,
                        "sha256": sha(self.dependency),
                    }
                },
            },
        )

    def env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PVRIG_EXP_DIR": str(self.exp),
                "PYTHON": sys.executable,
                "V4F_PREDICTION_FREEZER": str(FREEZER),
                "PVRIG_V4F_WATCHER_V2_TEST_ONLY": "1",
                "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS": "1",
                "V4F_V2_TRUST_ANCHOR": str(self.anchor),
                "V4F_V2_EXPECTED_TRUST_ANCHOR_SHA": sha(self.anchor),
                "V4D_V2_EXPECTED_TRUST_ANCHOR_SHA": "a" * 64,
                "V4D_SURROGATE_STATUS": str(self.surrogate_status),
                "V4D_SURROGATE_V2_COMPLETION_RECEIPT": str(self.surrogate_receipt),
                "ONCE": "1",
                "POLL_SECONDS": "1",
                "MAX_WAIT_SECONDS": "10",
                "FREEZE_TIMEOUT_SECONDS": "10",
            }
        )
        return environment

    def status(self) -> dict[str, object]:
        return json.loads(
            (
                self.exp
                / "status/pvrig_v4_f_prediction_freeze_v2/status.json"
            ).read_text()
        )


class V4FPredictionWatcherV2Tests(unittest.TestCase):
    def test_real_production_anchor_and_launcher_are_closed(self) -> None:
        anchor = EXP / "audits/phase2_v4_f_prediction_freeze_v2_implementation_trust_anchor.json"
        launcher = EXP / "src/launch_phase2_v4_f_prediction_freeze_v2.sh"
        metadata = anchor.lstat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertFalse(stat.S_ISLNK(metadata.st_mode))
        payload = json.loads(anchor.read_text())
        self.assertEqual(payload["status"], "FROZEN_BEFORE_V4F_PREDICTION_FREEZE")
        for role, item in payload["files"].items():
            path = Path(item["path"])
            observed = path.lstat()
            self.assertTrue(stat.S_ISREG(observed.st_mode), role)
            self.assertFalse(stat.S_ISLNK(observed.st_mode), role)
            self.assertEqual(observed.st_size, item["size"], role)
            self.assertEqual(sha(path), item["sha256"], role)
        self.assertIn(sha(anchor), launcher.read_text())

    def test_waiting_state_keeps_label_paths_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            result = subprocess.run(
                [str(SCRIPT)], env=fixture.env(), text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 4, result.stderr)
            status = fixture.status()
            self.assertEqual(status["status"], "WAITING_V4_D_SURROGATES")
            self.assertIs(status["v4_f_labels_read"], False)
            self.assertEqual(status["v4_f_label_paths_accepted"], 0)

    def test_captured_dependency_tamper_fails_before_freezer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            environment = fixture.env()
            fixture.dependency.write_text("VALUE = 2\n")
            result = subprocess.run(
                [str(SCRIPT)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("AssertionError", result.stderr)
            self.assertFalse(
                (fixture.exp / "predictions/pvrig_v4_f_surrogate_predictions_v1").exists()
            )

    def test_invalid_surrogate_v2_completion_receipt_blocks_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            write_json(
                fixture.surrogate_status,
                {"status": "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED"},
            )
            write_json(
                fixture.surrogate_receipt,
                {
                    "schema_version": "phase2_v4_d_surrogate_v2_completion_receipt_v1",
                    "status": "PASS_V4_D_SURROGATE_V2_COMPLETE_TEST32_SEALED",
                    "implementation_trust_anchor_sha256": "wrong",
                    "prospective_test_labels_read": False,
                    "prospective_test_label_paths_accepted": 0,
                    "stage_receipts": {},
                },
            )
            result = subprocess.run(
                [str(SCRIPT)], env=fixture.env(), text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(
                fixture.status()["status"], "BLOCKED_INVALID_SURROGATE_V2_RECEIPT"
            )

    def test_production_path_override_is_rejected(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "V4F_MANIFEST": "/tmp/forbidden-v4f-manifest.tsv",
                "V4F_V2_EXPECTED_TRUST_ANCHOR_SHA": "0" * 64,
                "V4D_V2_EXPECTED_TRUST_ANCHOR_SHA": "0" * 64,
                "ONCE": "1",
            }
        )
        result = subprocess.run(
            [str(SCRIPT)], env=environment, text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("production path override forbidden: MANIFEST", result.stderr)


if __name__ == "__main__":
    unittest.main()
