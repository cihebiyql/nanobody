#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "run_phase2_v4_d_dev1_open258_v1_2_once_v1_1.py"

spec = importlib.util.spec_from_file_location("v1_2_once_subject", SUBJECT)
if spec is None or spec.loader is None:
    raise RuntimeError("unable_to_load_subject")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class ExecIntercept(RuntimeError):
    pass


class OneShotLauncherTests(unittest.TestCase):
    def make_layout(self, directory: str):
        root = Path(directory) / "production"
        scripts = root / "scripts"
        governance = root / "governance"
        scripts.mkdir(parents=True)
        governance.mkdir()
        self_path = scripts / m.SELF_BASENAME
        shutil.copyfile(SUBJECT, self_path)
        inner_path = scripts / m.INNER_BASENAME
        inner_path.write_text("#!/usr/bin/env bash\nexit 19\n", encoding="utf-8")
        self_sha = hashlib.sha256(self_path.read_bytes()).hexdigest()
        inner_sha = hashlib.sha256(inner_path.read_bytes()).hexdigest()
        freeze_path = governance / m.FREEZE_BASENAME
        paths = m.expected_paths(root)
        freeze = {
            "status": m.EXPECTED_FREEZE_STATUS,
            "remote_execution_authorized": True,
            "attempt_limit": 1,
            "retry_authorized": False,
            "teacher_materialization_authorized": True,
            "teacher_release_requires_runtime_gates": True,
            "formal_v4_f_unlock_eligible": False,
            "source_evaluator_status": "FAIL",
            "source_evaluator_unlockable": False,
            "test32_raw_job_files_opened": 0,
            "test32_metric_values_read": 0,
            "test32_label_rows_emitted": 0,
            "attempt_marker_path": str(paths["marker"]),
            "candidate_implementation_freeze_sha256": m.EXPECTED_CANDIDATE_FREEZE_SHA256,
            "independent_implementation_review_sha256": m.EXPECTED_IMPLEMENTATION_REVIEW_SHA256,
            "files": {
                "one_shot_launcher": {"path": str(self_path), "sha256": self_sha},
                "launcher": {"path": str(inner_path), "sha256": inner_sha},
            },
        }
        return root, self_path, inner_path, freeze_path, freeze, inner_sha

    @staticmethod
    def write_freeze(path: Path, payload):
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def call_once(self, root, self_path, freeze_path, freeze_sha, inner_sha, execve):
        with mock.patch.object(m, "EXPECTED_INNER_SHA256", inner_sha):
            m.execute_once(
                freeze_path,
                freeze_sha,
                root=root,
                self_path=self_path,
                execve=execve,
                environ={"BASE": "1"},
            )

    def test_valid_first_attempt_consumes_marker_before_exec(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            expected_inner_raw = inner_path.read_bytes()
            observed = {}

            def fake_exec(path, argv, env):
                observed.update(path=path, argv=argv, env=env, inner_raw=Path(argv[1]).read_bytes())
                raise ExecIntercept("exec intercepted")

            with self.assertRaisesRegex(ExecIntercept, "intercepted"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, fake_exec)
            marker = root / m.MARKER_RELATIVE_PATH
            self.assertTrue(marker.is_file())
            payload = json.loads(marker.read_text())
            self.assertEqual(payload["status"], "V1_2_ATTEMPT_001_CONSUMED_BEFORE_INNER_EXEC")
            self.assertEqual(payload["freeze_sha256"], freeze_sha)
            self.assertEqual(
                payload["one_shot_launcher_sha256"],
                hashlib.sha256(self_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(payload["inner_launcher_sha256"], inner_sha)
            self.assertFalse(payload["retry_authorized"])
            self.assertEqual(observed["path"], "/bin/bash")
            self.assertEqual(observed["argv"][0], "/bin/bash")
            self.assertRegex(observed["argv"][1], r"^/proc/self/fd/[0-9]+$")
            self.assertEqual(observed["inner_raw"], expected_inner_raw)
            self.assertEqual(observed["env"]["PVRIG_V4D_DEV1_V12_ROOT"], str(root))
            self.assertEqual(observed["env"]["PVRIG_V4D_DEV1_V12_LAUNCH_FREEZE"], str(freeze_path))

    def test_inner_path_swap_after_validation_executes_sealed_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            expected_inner_raw = inner_path.read_bytes()
            observed = {}

            def swap_then_exec(_path, argv, _env):
                inner_path.write_text("#!/usr/bin/env bash\necho replaced\n", encoding="utf-8")
                observed["inner_raw"] = Path(argv[1]).read_bytes()
                with self.assertRaises(OSError):
                    with open(argv[1], "wb") as handle:
                        handle.write(b"tamper")
                raise ExecIntercept("swap intercepted")

            with self.assertRaisesRegex(ExecIntercept, "swap intercepted"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, swap_then_exec)
            self.assertEqual(observed["inner_raw"], expected_inner_raw)
            self.assertNotEqual(inner_path.read_bytes(), expected_inner_raw)
            self.assertTrue((root / m.MARKER_RELATIVE_PATH).is_file())

    def test_libc_memfd_and_numeric_seal_fallback_executes_sealed_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            observed = {}

            def inspect_fallback(_path, argv, _env):
                fd = int(argv[1].rsplit("/", 1)[1])
                observed["raw"] = Path(argv[1]).read_bytes()
                observed["seals"] = m.fcntl.fcntl(fd, m.LINUX_F_GET_SEALS)
                with self.assertRaises(OSError):
                    with open(argv[1], "wb") as handle:
                        handle.write(b"tamper")
                raise ExecIntercept("fallback intercepted")

            constant_names = (
                (m.os, "MFD_ALLOW_SEALING"),
                (m.fcntl, "F_ADD_SEALS"),
                (m.fcntl, "F_GET_SEALS"),
                (m.fcntl, "F_SEAL_SEAL"),
                (m.fcntl, "F_SEAL_SHRINK"),
                (m.fcntl, "F_SEAL_GROW"),
                (m.fcntl, "F_SEAL_WRITE"),
            )
            patches = [mock.patch.object(m.os, "memfd_create", None, create=True)]
            patches.extend(mock.patch.object(namespace, name, None, create=True) for namespace, name in constant_names)
            with patches[0]:
                with patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
                    with self.assertRaisesRegex(ExecIntercept, "fallback intercepted"):
                        self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, inspect_fallback)
            expected_seals = (
                m.LINUX_F_SEAL_SEAL
                | m.LINUX_F_SEAL_SHRINK
                | m.LINUX_F_SEAL_GROW
                | m.LINUX_F_SEAL_WRITE
            )
            self.assertEqual(observed["seals"] & expected_seals, expected_seals)
            self.assertEqual(hashlib.sha256(observed["raw"]).hexdigest(), inner_sha)
            self.assertTrue((root / m.MARKER_RELATIVE_PATH).is_file())

    def test_missing_native_and_libc_memfd_fails_before_attempt_consumption(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            with mock.patch.object(m.os, "memfd_create", None, create=True):
                with mock.patch.object(m.ctypes, "CDLL", side_effect=OSError("synthetic missing libc")):
                    with self.assertRaisesRegex(m.OneShotLaunchError, "libc_memfd_create_unavailable"):
                        self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_second_attempt_is_denied_and_marker_is_not_removed(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)

            def fail_exec(_path, _argv, _env):
                raise ExecIntercept("first")

            with self.assertRaises(ExecIntercept):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, fail_exec)
            marker = root / m.MARKER_RELATIVE_PATH
            first_bytes = marker.read_bytes()
            with self.assertRaisesRegex(m.OneShotLaunchError, "already_consumed"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, fail_exec)
            self.assertEqual(marker.read_bytes(), first_bytes)

    def test_invalid_freeze_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze["remote_execution_authorized"] = False
            freeze_sha = self.write_freeze(freeze_path, freeze)
            with self.assertRaisesRegex(m.OneShotLaunchError, "not_authorized"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_each_authorization_gate_fails_before_attempt_consumption(self):
        cases = (
            ("status", "WRONG", "freeze_status_invalid"),
            ("retry_authorized", True, "retry_authorized_not_false"),
            ("teacher_materialization_authorized", False, "teacher_materialization_not_authorized"),
            ("teacher_release_requires_runtime_gates", False, "runtime_gates_not_required"),
            ("formal_v4_f_unlock_eligible", True, "formal_unlock_true"),
            ("source_evaluator_status", "PASS", "source_evaluator_status_not_fail"),
            ("source_evaluator_unlockable", True, "source_evaluator_unlockable_not_false"),
            ("test32_raw_job_files_opened", 1, "sealed_boundary_nonzero"),
            ("test32_metric_values_read", 1, "sealed_boundary_nonzero"),
            ("test32_label_rows_emitted", 1, "sealed_boundary_nonzero"),
            (
                "candidate_implementation_freeze_sha256",
                "0" * 64,
                "candidate_freeze_binding_invalid",
            ),
            (
                "independent_implementation_review_sha256",
                "0" * 64,
                "implementation_review_binding_invalid",
            ),
        )
        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
                freeze[field] = value
                freeze_sha = self.write_freeze(freeze_path, freeze)
                with self.assertRaisesRegex(m.OneShotLaunchError, message):
                    self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
                self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_self_hash_mismatch_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze["files"]["one_shot_launcher"]["sha256"] = "0" * 64
            freeze_sha = self.write_freeze(freeze_path, freeze)
            with self.assertRaisesRegex(m.OneShotLaunchError, "freeze_file_sha256_invalid:one_shot_launcher"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_inner_hash_mismatch_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze["files"]["launcher"]["sha256"] = "f" * 64
            freeze_sha = self.write_freeze(freeze_path, freeze)
            with self.assertRaisesRegex(m.OneShotLaunchError, "freeze_file_sha256_invalid:launcher"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_bound_launcher_paths_must_be_exact(self):
        for key in ("one_shot_launcher", "launcher"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as td:
                root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
                freeze["files"][key]["path"] = str(root / "scripts/wrong")
                freeze_sha = self.write_freeze(freeze_path, freeze)
                with self.assertRaisesRegex(m.OneShotLaunchError, f"freeze_file_path_invalid:{key}"):
                    self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
                self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_inner_exec_failure_still_leaves_attempt_consumed(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)

            def failed_exec(_path, _argv, _env):
                raise OSError("synthetic inner exec failure")

            with self.assertRaisesRegex(OSError, "synthetic"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, failed_exec)
            self.assertTrue((root / m.MARKER_RELATIVE_PATH).is_file())

    def test_wrong_expected_freeze_hash_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            self.write_freeze(freeze_path, freeze)
            with self.assertRaisesRegex(m.OneShotLaunchError, "freeze_sha256_mismatch"):
                self.call_once(root, self_path, freeze_path, "0" * 64, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_malformed_expected_freeze_hash_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            self.write_freeze(freeze_path, freeze)
            with self.assertRaisesRegex(m.OneShotLaunchError, "expected_freeze_sha256_invalid"):
                self.call_once(root, self_path, freeze_path, "NOT-A-SHA", inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_bool_is_not_accepted_as_attempt_limit_or_sealed_zero(self):
        cases = (
            ("attempt_limit", True, "attempt_limit_not_one"),
            ("test32_raw_job_files_opened", False, "sealed_boundary_nonzero"),
            ("test32_metric_values_read", False, "sealed_boundary_nonzero"),
            ("test32_label_rows_emitted", False, "sealed_boundary_nonzero"),
        )
        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
                freeze[field] = value
                freeze_sha = self.write_freeze(freeze_path, freeze)
                with self.assertRaisesRegex(m.OneShotLaunchError, message):
                    self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
                self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_wrong_attempt_marker_path_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze["attempt_marker_path"] = str(root / "attempts/other.json")
            freeze_sha = self.write_freeze(freeze_path, freeze)
            with self.assertRaisesRegex(m.OneShotLaunchError, "attempt_marker_path_invalid"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_noncanonical_freeze_path_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            noncanonical = freeze_path.parent / ".." / "governance" / freeze_path.name
            with self.assertRaisesRegex(m.OneShotLaunchError, "freeze_path_not_canonical"):
                self.call_once(root, self_path, noncanonical, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_authority_file_symlinks_are_rejected_without_consuming_attempt(self):
        for label in ("freeze", "self", "inner"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root, self_path, inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
                freeze_sha = self.write_freeze(freeze_path, freeze)
                selected = {"freeze": freeze_path, "self": self_path, "inner": inner_path}[label]
                target = selected.with_name(selected.name + ".target")
                selected.replace(target)
                selected.symlink_to(target)
                with self.assertRaisesRegex(m.OneShotLaunchError, "unable_to_open_snapshot"):
                    self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
                self.assertFalse((root / m.MARKER_RELATIVE_PATH).exists())

    def test_attempts_directory_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            external = Path(td) / "external_attempts"
            external.mkdir()
            (root / "attempts").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(m.OneShotLaunchError, "unable_to_open_attempts_directory"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertFalse((external / m.MARKER_RELATIVE_PATH.name).exists())

    def test_preexisting_marker_symlink_is_not_followed_or_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            attempts = root / "attempts"
            attempts.mkdir()
            target = Path(td) / "external_marker_target"
            target.write_text("unchanged\n", encoding="utf-8")
            marker = root / m.MARKER_RELATIVE_PATH
            marker.symlink_to(target)
            with self.assertRaisesRegex(m.OneShotLaunchError, "already_consumed"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged\n")
            self.assertTrue(marker.is_symlink())

    def test_marker_write_failure_still_consumes_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root, self_path, _inner_path, freeze_path, freeze, inner_sha = self.make_layout(td)
            freeze_sha = self.write_freeze(freeze_path, freeze)
            real_write = m.os.write

            def fail_marker_only(fd, raw):
                if os.readlink(f"/proc/self/fd/{fd}").startswith("/memfd:"):
                    return real_write(fd, raw)
                raise OSError("synthetic marker write failure")

            with mock.patch.object(m.os, "write", side_effect=fail_marker_only):
                with self.assertRaisesRegex(OSError, "synthetic marker write failure"):
                    self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)
            marker = root / m.MARKER_RELATIVE_PATH
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.stat().st_size, 0)
            with self.assertRaisesRegex(m.OneShotLaunchError, "already_consumed"):
                self.call_once(root, self_path, freeze_path, freeze_sha, inner_sha, lambda *_: None)

    def test_source_has_no_assert_ssh_retry_or_scientific_method_change(self):
        source = SUBJECT.read_text()
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(tree)))
        self.assertNotIn("ssh.exe", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("glob(", source)
        self.assertNotIn("rglob(", source)
        self.assertNotIn("unlink(", source)
        self.assertNotIn("Docking Gold", source.replace("not a V4-D pass, formal test, Docking Gold", ""))
        self.assertEqual(m.PRODUCTION_ROOT, Path("/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_2_20260717"))
        self.assertEqual(m.SELF_BASENAME, "run_phase2_v4_d_dev1_open258_v1_2_once_v1_1.py")
        self.assertEqual(m.MARKER_RELATIVE_PATH, Path("attempts/v1_2_attempt_001_consumed.json"))
        self.assertEqual(
            (
                m.LINUX_MFD_ALLOW_SEALING,
                m.LINUX_F_ADD_SEALS,
                m.LINUX_F_GET_SEALS,
                m.LINUX_F_SEAL_SEAL,
                m.LINUX_F_SEAL_SHRINK,
                m.LINUX_F_SEAL_GROW,
                m.LINUX_F_SEAL_WRITE,
            ),
            (2, 1033, 1034, 1, 2, 4, 8),
        )


if __name__ == "__main__":
    unittest.main()
