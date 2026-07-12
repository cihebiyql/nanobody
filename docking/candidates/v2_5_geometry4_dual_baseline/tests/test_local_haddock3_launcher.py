#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_pending_haddock3_local.py"
SPEC = importlib.util.spec_from_file_location("local_geometry4_launcher", SCRIPT)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LocalHaddock3LauncherTests(unittest.TestCase):
    def make_pose_root(self, tmp: Path) -> Path:
        pose_root = tmp / "haddock3"
        for candidate in launcher.CANDIDATES:
            workdir = pose_root / candidate
            data = workdir / "data"
            data.mkdir(parents=True)
            (data / f"{candidate}_vhh_chainA.pdb").write_text("ATOM\n", encoding="ascii")
            (data / "pvrig_8x6b_chainB.pdb").write_text("ATOM\n", encoding="ascii")
            (data / f"{candidate}_cdr_to_pvrig_hotspot_ambig.tbl").write_text(
                "assign (resid 1) (resid 2) 2.0 2.0 0.0\n", encoding="ascii"
            )
            (workdir / f"{candidate}_pvrig_hotspot.cfg").write_text(
                f'''run_dir = "run_{candidate}_pvrig_hotspot"
mode = "local"
ncores = 8
molecules = ["data/{candidate}_vhh_chainA.pdb", "data/pvrig_8x6b_chainB.pdb"]
[rigidbody]
sampling = 40
''',
                encoding="ascii",
            )
        return pose_root

    def make_handoff(self, inputs: dict[str, dict[str, str]], **updates: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": launcher.HANDOFF_SCHEMA,
            "claim_boundary": launcher.CLAIM_BOUNDARY,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "execution_owner": "local",
            "host": "node1",
            "nonce": "a" * 64,
            "remote_waiter": {"session_running": False},
            "remote_runs": {candidate: "ABSENT" for candidate in launcher.CANDIDATES},
            "local_inputs": inputs,
        }
        payload.update(updates)
        return payload

    def test_event_log_escapes_non_ascii_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "events.tsv"
            with mock.patch.object(launcher, "EVENTS_TSV", events):
                launcher.append_event("TEST", detail="/mnt/d/work/\u6297\u4f53")
            text = events.read_text(encoding="ascii")
        self.assertIn(r"/mnt/d/work/\u6297\u4f53", text)

    def test_validate_inputs_accepts_frozen_three_candidate_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            evidence = launcher.validate_local_inputs(self.make_pose_root(Path(td)))
        self.assertEqual(set(evidence), set(launcher.CANDIDATES))
        self.assertTrue(all(row["run_state"] == "ABSENT" for row in evidence.values()))

    def test_validate_inputs_refuses_incomplete_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pose_root = self.make_pose_root(Path(td))
            candidate = launcher.CANDIDATES[0]
            (pose_root / candidate / f"run_{candidate}_pvrig_hotspot").mkdir()
            with self.assertRaisesRegex(launcher.LocalExecutionError, "incomplete existing local run"):
                launcher.validate_local_inputs(pose_root)

    def test_parse_claim_requires_all_candidate_rows(self) -> None:
        text = "\n".join(
            [
                "CLAIM_REMOTE_STATE=INTERRUPTED",
                "CLAIM_SESSION_RUNNING=0",
                "CLAIM_WAS_RUNNING=1",
                "CLAIM_NONCE=" + "a" * 64,
                "CLAIM_OWNER_FILE=/tmp/owner",
                "CLAIM_RUN_zym_test_359954=ABSENT",
            ]
        )
        with self.assertRaisesRegex(launcher.LocalExecutionError, "missing fields"):
            launcher.parse_claim_output(text)

    def test_remote_claim_freezes_and_rechecks_waiter_before_kill(self) -> None:
        script = launcher.REMOTE_CLAIM_SCRIPT
        ownership_lock = script.index('flock -w 10 8')
        freeze = script.index('kill -STOP "$waiter_pid"')
        frozen_state = script.index("frozen_state=$(read_state)")
        kill_session = script.index('tmux -L "$socket" kill-session')
        runner_lock = script.index('flock -w 10 9')
        resume = script.index("resume_waiter", kill_session)
        owner_write = script.index('printf \'owner=local')
        self.assertLess(ownership_lock, freeze)
        self.assertLess(freeze, frozen_state)
        self.assertLess(frozen_state, kill_session)
        self.assertLess(kill_session, resume)
        self.assertLess(resume, runner_lock)
        self.assertLess(runner_lock, owner_write)

    def test_handoff_rejects_stale_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            inputs = launcher.validate_local_inputs(self.make_pose_root(Path(td)))
            stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            payload = self.make_handoff(inputs, created_at=stale)
            with self.assertRaisesRegex(launcher.LocalExecutionError, "stale"):
                launcher.validate_handoff(payload, "node1", inputs, 900)

    def test_handoff_rejects_changed_local_input(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pose_root = self.make_pose_root(Path(td))
            inputs = launcher.validate_local_inputs(pose_root)
            payload = self.make_handoff(inputs)
            candidate = launcher.CANDIDATES[0]
            (pose_root / candidate / "data" / f"{candidate}_vhh_chainA.pdb").write_text(
                "CHANGED\n", encoding="ascii"
            )
            changed = launcher.validate_local_inputs(pose_root)
            with self.assertRaisesRegex(launcher.LocalExecutionError, "inputs changed"):
                launcher.validate_handoff(payload, "node1", changed, 900)

    def test_execute_is_sequential_and_refuses_nonzero_haddock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pose_root = self.make_pose_root(tmp)
            status = tmp / "status.json"
            handoff = tmp / "handoff.json"
            handoff.write_text("{}\n", encoding="ascii")
            with mock.patch.object(launcher, "find_local_conflicts", return_value=[]), mock.patch.object(
                launcher.subprocess, "run", return_value=mock.Mock(returncode=7)
            ):
                with self.assertRaisesRegex(launcher.LocalExecutionError, "exit 7"):
                    launcher.execute_local_runs(pose_root, Path("/fake/haddock3"), status, handoff)
            payload = json.loads(status.read_text())
            self.assertEqual(payload["state"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
