import importlib.util
import pathlib
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
MODULE_PATH = ROOT / "deployment" / "build_gpu1_smoke_recovery_v1_1.py"
SPEC = importlib.util.spec_from_file_location("build_gpu1_smoke_recovery_v1_1", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class TestGPU1SmokeRecoveryV11(unittest.TestCase):
    def test_generated_launcher_and_autostart_are_checksum_closed_and_terminal_aware(self):
        launcher = mod.launcher_source("1" * 64, "2" * 64, "3" * 64, "4" * 64)
        self.assertGreaterEqual(launcher.count("verify_package("), 3)
        self.assertIn("FAIL_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY", launcher)
        self.assertIn("PASS_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY", launcher)
        autostart = mod.autostart_source(
            source_sha256s_sha="4" * 64,
            overlay_sha256s_sha="5" * 64,
            plan_sha="1" * 64,
            overlay_sha="2" * 64,
            launcher_sha="6" * 64,
        )
        self.assertGreaterEqual(autostart.count("verify_package("), 3)
        self.assertIn("process.wait()", autostart)
        self.assertIn("child_terminal_missing", autostart)
        self.assertIn("FAIL_GPU1_RECOVERY_AUTOSTART_V1_1", autostart)

    def test_file_closure_rejects_unlisted_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "A.txt").write_text("a\n")
            mod.regenerate_sha256s(root)
            self.assertEqual(set(mod.audit_file_closure(root)), {"A.txt"})
            (root / "B.txt").write_text("b\n")
            with self.assertRaisesRegex(mod.RecoveryBuildError, "file_closure"):
                mod.audit_file_closure(root)


if __name__ == "__main__":
    unittest.main()
