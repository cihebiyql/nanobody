#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/node1_guarded_haddock3_waiter.sh"
DEPLOYER = ROOT / "scripts/deploy_guarded_haddock3_waiter_node1.sh"
PENDING_LAUNCHER = ROOT / "scripts/run_pending_haddock3_node1.sh"
CANDIDATES = ("zym_test_359954", "zym_test_3633872", "zym_test_8787")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


class GuardedWaiterBehaviorTests(unittest.TestCase):
    def make_fixture(self, tmp: Path, load1: str) -> tuple[Path, Path, Path, dict[str, str]]:
        remote_root = tmp / "remote"
        loadavg = tmp / "loadavg"
        loadavg.write_text(f"{load1} 0.00 0.00 1/1 1\n", encoding="ascii")
        fake_events = tmp / "fake_haddock_events.txt"
        fake_haddock = tmp / "fake_haddock.sh"
        fake_haddock.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
cfg=$1
cid=${cfg%_pvrig_hotspot.cfg}
run=run_${cid}_pvrig_hotspot
mkdir -p "$run/traceback" "$run/6_seletopclusts"
printf 'Model\\t6_seletopclusts_rank\\ncluster_1_model_1.pdb\\t1\\n' > "$run/traceback/consensus.tsv"
if [[ ${FAKE_ZERO_TOP:-0} == 1 ]]; then
  : > "$run/6_seletopclusts/cluster_1_model_1.pdb"
else
  printf 'ATOM\\n' > "$run/6_seletopclusts/cluster_1_model_1.pdb"
fi
printf '%s\\n' "$cid" >> "$FAKE_HADDOCK_EVENTS"
""",
            encoding="ascii",
        )
        fake_haddock.chmod(0o755)
        for cid in CANDIDATES:
            candidate = remote_root / "haddock3" / cid
            (candidate / "data").mkdir(parents=True)
            (candidate / f"{cid}_pvrig_hotspot.cfg").write_text("run_dir = dummy\n", encoding="ascii")
            (candidate / "data" / f"{cid}_vhh_chainA.pdb").write_text("ATOM\n", encoding="ascii")
            (candidate / "data/pvrig_8x6b_chainB.pdb").write_text("ATOM\n", encoding="ascii")
        env = {
            **os.environ,
            "GEOMETRY4_REMOTE_ROOT": str(remote_root),
            "GEOMETRY4_HADDOCK_BIN": str(fake_haddock),
            "GEOMETRY4_LOADAVG_FILE": str(loadavg),
            "GEOMETRY4_MAX_LOAD1": "64",
            "GEOMETRY4_POLL_SECONDS": "10",
            "GEOMETRY4_MAX_WAIT_SECONDS": "20",
            "FAKE_HADDOCK_EVENTS": str(fake_events),
        }
        return remote_root, loadavg, fake_events, env

    def test_low_load_completes_all_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(events.read_text().splitlines(), list(CANDIDATES))
            self.assertEqual(read_env_file(remote_root / "geometry4_waiter/status.env")["state"], "COMPLETE")

    def test_high_load_times_out_without_starting_haddock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "100")
            env["GEOMETRY4_MAX_WAIT_SECONDS"] = "10"
            result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 31, result.stderr)
            self.assertFalse(events.exists())
            self.assertEqual(read_env_file(remote_root / "geometry4_waiter/status.env")["state"], "TIMED_OUT")

    def test_signal_interruption_never_reports_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "100")
            env["GEOMETRY4_MAX_WAIT_SECONDS"] = "100"
            proc = subprocess.Popen(
                ["bash", str(RUNNER)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            status = remote_root / "geometry4_waiter/status.env"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if status.exists() and read_env_file(status).get("state") == "WAITING_FOR_LOAD":
                    break
                time.sleep(0.05)
            else:
                self.fail("runner did not enter WAITING_FOR_LOAD")
            os.killpg(proc.pid, signal.SIGTERM)
            proc.communicate(timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(events.exists())
            self.assertEqual(read_env_file(status)["state"], "INTERRUPTED")

    def test_fractional_or_nonfinite_overrides_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _, _, _, base_env = self.make_fixture(Path(td), "100")
            for key, value in (
                ("GEOMETRY4_POLL_SECONDS", "10.5"),
                ("GEOMETRY4_POLL_SECONDS", "010"),
                ("GEOMETRY4_MAX_WAIT_SECONDS", "20.5"),
                ("GEOMETRY4_MAX_LOAD1", "nan"),
            ):
                with self.subTest(key=key, value=value):
                    env = {**base_env, key: value}
                    result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
                    self.assertNotEqual(result.returncode, 0)

    def test_candidate_lock_blocks_duplicate_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            lock_path = remote_root / "haddock3" / CANDIDATES[0] / ".geometry4_haddock.lock"
            with lock_path.open("w", encoding="ascii") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 27, result.stderr)
            self.assertFalse(events.exists())
            self.assertEqual(read_env_file(remote_root / "geometry4_waiter/status.env")["state"], "FAILED")

    def test_ownership_handoff_lock_blocks_waiter_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            state_dir = remote_root / "geometry4_waiter"
            state_dir.mkdir()
            lock_path = state_dir / "ownership.lock"
            with lock_path.open("w", encoding="ascii") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 33, result.stderr)
            self.assertIn("WAITER_OWNERSHIP_HANDOFF_BUSY", result.stderr)
            self.assertFalse(events.exists())

    def test_incomplete_existing_run_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            run_dir = remote_root / "haddock3" / CANDIDATES[0] / f"run_{CANDIDATES[0]}_pvrig_hotspot"
            run_dir.mkdir()
            result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 25, result.stderr)
            self.assertFalse(events.exists())
            self.assertTrue(run_dir.is_dir())
            self.assertEqual(read_env_file(remote_root / "geometry4_waiter/status.env")["state"], "FAILED")

    def test_zero_byte_top_pose_is_never_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            candidate = CANDIDATES[0]
            run_dir = remote_root / "haddock3" / candidate / f"run_{candidate}_pvrig_hotspot"
            (run_dir / "traceback").mkdir(parents=True)
            (run_dir / "6_seletopclusts").mkdir()
            (run_dir / "traceback/consensus.tsv").write_text("Model\npose\n", encoding="ascii")
            (run_dir / "6_seletopclusts/cluster_1_model_1.pdb").touch()
            result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 25, result.stderr)
            self.assertFalse(events.exists())

    def test_zero_byte_top_pose_after_haddock_fails_completion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            env["FAKE_ZERO_TOP"] = "1"
            result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 26, result.stderr)
            self.assertEqual(events.read_text().splitlines(), [CANDIDATES[0]])
            self.assertEqual(read_env_file(remote_root / "geometry4_waiter/status.env")["state"], "FAILED")

    def test_local_execution_owner_blocks_waiter_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            remote_root, _, events, env = self.make_fixture(Path(td), "1")
            state_dir = remote_root / "geometry4_waiter"
            state_dir.mkdir()
            (state_dir / "execution_owner.env").write_text(
                "owner=local\nnonce=test-only\n", encoding="ascii"
            )
            result = subprocess.run(["bash", str(RUNNER)], env=env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 32, result.stderr)
            self.assertIn("REFUSE_LOCAL_EXECUTION_OWNER", result.stderr)
            self.assertFalse(events.exists())

    def test_deployer_rejects_bad_values_before_ssh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            marker = tmp / "ssh_called"
            fake_ssh = tmp / "fake_ssh.sh"
            fake_ssh.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="ascii")
            fake_ssh.chmod(0o755)
            env = {
                **os.environ,
                "GEOMETRY4_SSH_BIN": str(fake_ssh),
                "GEOMETRY4_MAX_WAIT_SECONDS": "10'; touch /tmp/should_not_run; echo '",
            }
            result = subprocess.run(["bash", str(DEPLOYER), "--deploy"], env=env, text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_pending_launcher_rejects_nan_before_ssh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            marker = tmp / "ssh_called"
            fake_ssh = tmp / "fake_ssh.sh"
            fake_ssh.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="ascii")
            fake_ssh.chmod(0o755)
            env = {
                **os.environ,
                "GEOMETRY4_SSH_BIN": str(fake_ssh),
                "GEOMETRY4_MAX_LOAD1": "nan",
            }
            result = subprocess.run(
                ["bash", str(PENDING_LAUNCHER), "--plan"],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
