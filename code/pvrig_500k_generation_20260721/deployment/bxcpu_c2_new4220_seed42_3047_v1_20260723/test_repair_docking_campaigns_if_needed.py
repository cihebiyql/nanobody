#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import json


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "repair_target", HERE / "repair_docking_campaigns_if_needed.py"
)
assert SPEC and SPEC.loader
TARGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TARGET)


class RepairDecisionTests(unittest.TestCase):
    def test_current_incomplete_terminal_campaign_gets_resume_safe_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(TARGET, "CURRENT_ROOT", root),
                mock.patch.object(TARGET, "CURRENT_DEPLOY", root / "deploy"),
                mock.patch.object(TARGET, "state", return_value="FAILED"),
                mock.patch.object(TARGET, "active_for", return_value=False),
                mock.patch.object(TARGET, "active_named", return_value=False),
                mock.patch.object(TARGET, "current_exports", return_value="ALL,TEST=1"),
            ):
                snapshot, actions = TARGET.maybe_repair_current(dry_run=True)
            self.assertEqual(snapshot["terminal"], 0)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["status"], "DRY_RUN_REPAIR")
            self.assertEqual(actions[0]["campaign"], "pvrig-c2new-r1")

    def test_active_current_campaign_is_never_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(TARGET, "CURRENT_ROOT", root),
                mock.patch.object(TARGET, "state", return_value="PENDING"),
                mock.patch.object(TARGET, "active_for", return_value=True),
                mock.patch.object(TARGET, "active_named", return_value=False),
            ):
                _, actions = TARGET.maybe_repair_current(dry_run=True)
            self.assertEqual(actions, [])

    def test_completed_current_campaign_with_failed_audit_gets_audit_only_repair(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_4220 = root / "batch_4220/status/jobs"
            status_2000 = root / "batch_2000/status/jobs"
            status_4220.mkdir(parents=True)
            status_2000.mkdir(parents=True)
            for index in range(16880):
                (status_4220 / f"a{index}.json").write_text(
                    json.dumps({"status": "SUCCESS"})
                )
            for index in range(8000):
                (status_2000 / f"b{index}.json").write_text(
                    json.dumps({"status": "SUCCESS"})
                )
            with (
                mock.patch.object(TARGET, "CURRENT_ROOT", root),
                mock.patch.object(TARGET, "CURRENT_DEPLOY", root / "deploy"),
                mock.patch.object(TARGET, "state", return_value="FAILED"),
                mock.patch.object(TARGET, "active_for", return_value=False),
                mock.patch.object(TARGET, "active_named", return_value=False),
                mock.patch.object(TARGET, "current_exports", return_value="ALL,TEST=1"),
            ):
                snapshot, actions = TARGET.maybe_repair_current(dry_run=True)
            self.assertEqual(snapshot["terminal"], 24880)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["status"], "DRY_RUN_AUDIT_REPAIR")
            self.assertEqual(actions[0]["campaign"], "pvrig-c2new-r1-audit-only")

    def test_failed_extra_preflight_is_replaced_without_docking_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markers = root / "markers"
            markers.mkdir(parents=True)
            (markers / "PREFLIGHT_JOB_ID").write_text("12345\n")
            with (
                mock.patch.object(TARGET, "EXTRA_ROOT", root),
                mock.patch.object(TARGET, "EXTRA_DEPLOY", root / "deploy"),
                mock.patch.object(TARGET, "state", return_value="FAILED"),
                mock.patch.object(TARGET, "active_named", return_value=False),
                mock.patch.object(TARGET, "extra_exports", return_value="ALL,TEST=1"),
            ):
                snapshot, actions = TARGET.maybe_repair_extra(dry_run=True)
            self.assertEqual(snapshot["preflight_job_id"], "12345")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["status"], "DRY_RUN_PREFLIGHT_REPAIR")

    def test_current_snapshot_tracks_latest_repair_job_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repair_dir = root / "markers/watchdog_repairs"
            repair_dir.mkdir(parents=True)
            (repair_dir / "pvrig-c2new-r1_round_01.json").write_text(
                json.dumps({"array_job_id": "777", "audit_job_id": "888"})
            )
            with (
                mock.patch.object(TARGET, "CURRENT_ROOT", root),
                mock.patch.object(TARGET, "state", return_value="PENDING"),
                mock.patch.object(TARGET, "active_for", return_value=False),
                mock.patch.object(TARGET, "active_named", return_value=False),
            ):
                snapshot, actions = TARGET.maybe_repair_current(dry_run=True)
            self.assertEqual(snapshot["array_job_id"], "777")
            self.assertEqual(snapshot["audit_job_id"], "888")
            self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
