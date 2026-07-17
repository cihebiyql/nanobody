#!/usr/bin/env python3
"""Regression tests for the V4-D/V4-F watcher V3 trust boundary.

The tests deliberately use only noncanonical fixtures except when exercising the
production-root path gates.  They never create, replace, or read prospective
V4-F labels.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_monitor_phase2_v4_d_surrogate_training_v2 import Fixture as SurrogateFixture


SRC = Path(__file__).resolve().parent
EXP = SRC.parent
CANONICAL_PYTHON = EXP / ".venv-phase2-5080/bin/python"
SURROGATE_SCRIPT = SRC / "monitor_phase2_v4_d_surrogate_training_v3.sh"
SURROGATE_HELPER = SRC / "phase2_v4_d_surrogate_watcher_helper_v3.py"
V4F_SCRIPT = SRC / "monitor_phase2_v4_f_prediction_freeze_v3.sh"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in (
        "PVRIG_V4D_WATCHER_TEST_ONLY",
        "PVRIG_V4F_WATCHER_V3_TEST_ONLY",
        "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS",
        "V4D_V3_TRUST_ANCHOR",
        "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA",
        "V4F_V3_TRUST_ANCHOR",
        "V4F_V3_EXPECTED_TRUST_ANCHOR_SHA",
        "PYTHONPATH",
        "BASH_ENV",
    ):
        environment.pop(key, None)
    environment["PYTHONOPTIMIZE"] = "0"
    return environment


class V4FFixture:
    """Minimal fixture that can only reach a waiting or fail-closed state."""

    def __init__(self, root: Path) -> None:
        self.exp = root / "exp"
        self.exp.mkdir()
        self.surrogate_status = self.exp / "surrogate_status.json"
        self.surrogate_receipt = self.exp / "surrogate_receipt.json"
        self.marker = self.exp / "freezer_was_called"
        self.freezer = self.exp / "freezer_stub.py"
        self.freezer.write_text(
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['FREEZER_MARKER']).write_text('called\\n')\n",
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

    @property
    def status_path(self) -> Path:
        return self.exp / "status/pvrig_v4_f_prediction_freeze_v3/status.json"

    @property
    def output_path(self) -> Path:
        return self.exp / "predictions/pvrig_v4_f_surrogate_predictions_v1"

    def environment(self) -> dict[str, str]:
        environment = clean_environment()
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
                "ONCE": "1",
                "POLL_SECONDS": "1",
                "MAX_WAIT_SECONDS": "10",
                "FREEZE_TIMEOUT_SECONDS": "10",
            }
        )
        return environment


class WatcherV3TrustHardeningTests(unittest.TestCase):
    maxDiff = None

    def test_surrogate_production_input_overrides_fail_before_lock(self) -> None:
        override_cases = {
            "V4D_OPEN_TEACHER": "TEACHER",
            "V4D_OPEN_TEACHER_AUDIT": "TEACHER_AUDIT",
            "V4D_OPEN_RELEASE_RECEIPT": "RELEASE_RECEIPT",
            "V4D_OPEN_EVALUATOR": "EVALUATOR",
            "V4D_EMBEDDING_MANIFEST": "EMBEDDING_MANIFEST",
            "V4D_EMBEDDING_SUMMARY": "EMBEDDING_SUMMARY",
            "V4D_EMBEDDING_SEQUENCE_MANIFEST": "EMBEDDING_SEQUENCE_MANIFEST",
            "V4D_EMBEDDING_SHARD_DIR": "EMBEDDING_SHARD_DIR",
        }
        for variable, label in override_cases.items():
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                status_dir = root / "must_not_exist"
                environment = clean_environment()
                environment.update(
                    {
                        "PVRIG_EXP_DIR": str(EXP),
                        "PYTHON": str(CANONICAL_PYTHON),
                        "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA": "0" * 64,
                        "V4D_SURROGATE_STATUS_DIR": str(status_dir),
                        variable: str(root / "forbidden_override"),
                        "ONCE": "1",
                    }
                )
                result = subprocess.run(
                    [str(SURROGATE_SCRIPT)],
                    env=environment,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(
                    f"production path override forbidden: {label}", result.stderr
                )
                self.assertFalse(status_dir.exists(), "gate ran after lock/status creation")

    def test_v4f_test_only_is_forbidden_on_canonical_root_before_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status_dir = root / "must_not_exist"
            environment = clean_environment()
            environment.update(
                {
                    "PVRIG_EXP_DIR": str(EXP),
                    "PYTHON": str(CANONICAL_PYTHON),
                    "PVRIG_V4F_WATCHER_V3_TEST_ONLY": "1",
                    "V4F_PREDICTION_STATUS_DIR": str(status_dir),
                    "V4F_PREDICTION_OUT": str(root / "predictions"),
                    "ONCE": "1",
                }
            )
            result = subprocess.run(
                [str(V4F_SCRIPT)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("test-only", result.stderr.lower())
            self.assertIn("production", result.stderr.lower())
            self.assertFalse(status_dir.exists(), "gate ran after lock/status creation")

    def test_v4f_unfrozen_mode_is_forbidden_on_canonical_root_before_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status_dir = root / "must_not_exist"
            environment = clean_environment()
            environment.update(
                {
                    "PVRIG_EXP_DIR": str(EXP),
                    "PYTHON": str(CANONICAL_PYTHON),
                    "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS": "1",
                    "V4F_PREDICTION_STATUS_DIR": str(status_dir),
                    "V4F_PREDICTION_OUT": str(root / "predictions"),
                    "ONCE": "1",
                }
            )
            result = subprocess.run(
                [str(V4F_SCRIPT)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("test-only", result.stderr.lower())
            self.assertIn("production", result.stderr.lower())
            self.assertFalse(status_dir.exists(), "gate ran after lock/status creation")

    def test_python_optimize_cannot_bypass_v4f_anchor_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FFixture(Path(temporary))
            dependency = fixture.exp / "bound_dependency.py"
            dependency.write_text("VALUE = 1\n", encoding="utf-8")
            anchor = fixture.exp / "v4f_anchor.json"
            write_json(
                anchor,
                {
                    "schema_version": "phase2_v4_f_prediction_implementation_trust_anchor_v3",
                    "status": "FROZEN_BEFORE_V4F_PREDICTION_FREEZE",
                    "anchor_kind": "v4f_prediction_freeze",
                    "files": {
                        "bound_dependency": {
                            "path": str(dependency.resolve()),
                            "size": dependency.stat().st_size,
                            "sha256": sha256(dependency),
                        }
                    },
                },
            )
            environment = fixture.environment()
            environment.update(
                {
                    "V4F_V3_TRUST_ANCHOR": str(anchor),
                    "V4F_V3_EXPECTED_TRUST_ANCHOR_SHA": "0" * 64,
                    "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA": "a" * 64,
                    "PYTHONOPTIMIZE": "1",
                }
            )
            result = subprocess.run(
                [str(V4F_SCRIPT)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            trust_pass = (
                fixture.exp
                / "status/pvrig_v4_f_prediction_freeze_v3/implementation_trust_startup.json"
            )
            self.assertFalse(trust_pass.exists(), "bogus hash produced a PASS receipt")
            self.assertFalse(fixture.marker.exists(), "freezer ran after bogus anchor hash")

    def test_python_optimize_cannot_bypass_surrogate_anchor_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SurrogateFixture(Path(temporary))
            anchor = fixture.exp / "surrogate_anchor.json"
            # A malformed/minimal anchor is sufficient here: the expected digest is
            # deliberately wrong and must be rejected before its payload is trusted.
            write_json(
                anchor,
                {
                    "schema_version": "phase2_v4_d_surrogate_implementation_trust_anchor_v3",
                    "status": "FROZEN_BEFORE_OPEN258_TEACHER_AND_SURROGATE_TRAINING",
                    "anchor_kind": "v4d_surrogate_training",
                    "files": {},
                },
            )
            environment = fixture.env()
            environment.update(
                {
                    "WATCHER_HELPER": str(SURROGATE_HELPER),
                    "V4D_V3_TRUST_ANCHOR": str(anchor),
                    "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA": "0" * 64,
                    "PYTHONOPTIMIZE": "1",
                }
            )
            result = subprocess.run(
                [str(SURROGATE_SCRIPT)],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            trust_pass = (
                fixture.exp
                / "status/pvrig_v4_d_surrogate_training_v3/implementation_trust_preflight.json"
            )
            self.assertFalse(trust_pass.exists(), "bogus hash produced a PASS receipt")
            self.assertFalse(fixture.order.exists(), "trainer ran after bogus anchor hash")

    def test_python_optimize_cannot_accept_fake_surrogate_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FFixture(Path(temporary))
            write_json(
                fixture.surrogate_status,
                {
                    "status": "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED",
                    "prospective_test_labels_read": False,
                    "prospective_test_label_paths_accepted": 0,
                },
            )
            write_json(
                fixture.surrogate_receipt,
                {
                    "schema_version": "phase2_v4_d_surrogate_v3_completion_receipt_v1",
                    "status": "PASS_V4_D_SURROGATE_V3_COMPLETE_TEST32_SEALED",
                    "implementation_trust_anchor_sha256": "wrong",
                    "prospective_test_labels_read": False,
                    "prospective_test_label_paths_accepted": 0,
                    "stage_receipts": {},
                },
            )
            environment = fixture.environment()
            environment.update(
                {
                    "V4D_V3_EXPECTED_TRUST_ANCHOR_SHA": "a" * 64,
                    "PYTHONOPTIMIZE": "1",
                }
            )
            result = subprocess.run(
                [str(V4F_SCRIPT)], env=environment, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(
                fixture.marker.exists(), "freezer ran after a forged completion receipt"
            )
            status = json.loads(fixture.status_path.read_text(encoding="utf-8"))
            self.assertEqual(
                status["status"], "BLOCKED_INVALID_SURROGATE_V3_RECEIPT"
            )
            self.assertIs(status["v4_f_labels_read"], False)
            self.assertEqual(status["v4_f_label_paths_accepted"], 0)

    def test_noncanonical_surrogate_waiting_state_keeps_test_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SurrogateFixture(Path(temporary))
            fixture.teacher.unlink()
            environment = fixture.env()
            environment.update(
                {
                    "WATCHER_HELPER": str(SURROGATE_HELPER),
                    "PYTHONOPTIMIZE": "0",
                }
            )
            result = subprocess.run(
                [str(SURROGATE_SCRIPT)],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 4, result.stderr)
            status_path = (
                fixture.exp
                / "status/pvrig_v4_d_surrogate_training_v3/status.json"
            )
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "WAITING_OPEN_TEACHER")
            self.assertIs(status["prospective_test_labels_read"], False)
            self.assertEqual(status["prospective_test_label_paths_accepted"], 0)
            self.assertFalse(fixture.order.exists())
            for output in (
                fixture.exp / "runs/pvrig_v4_d_sequence_surrogate_v1",
                fixture.exp / "runs/pvrig_v4_d_frozen_embedding_surrogate_v1",
                fixture.exp / "runs/pvrig_v4_d_contact_fusion_surrogate_v1",
            ):
                self.assertFalse(output.exists(), f"unexpected output: {output}")

    def test_noncanonical_v4f_waiting_state_keeps_labels_and_outputs_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FFixture(Path(temporary))
            result = subprocess.run(
                [str(V4F_SCRIPT)],
                env=fixture.environment(),
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 4, result.stderr)
            status = json.loads(fixture.status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "WAITING_V4_D_SURROGATES")
            self.assertIs(status["v4_f_labels_read"], False)
            self.assertEqual(status["v4_f_label_paths_accepted"], 0)
            self.assertFalse(fixture.marker.exists())
            self.assertFalse(fixture.output_path.exists())

    def test_production_watchers_contain_no_python_assert_statements(self) -> None:
        for path in (SURROGATE_SCRIPT, V4F_SCRIPT, SURROGATE_HELPER):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(
                    re.search(r"(?m)^\s*assert(?:\s|\()", text),
                    f"production validation must not depend on assert: {path}",
                )


if __name__ == "__main__":
    unittest.main()
