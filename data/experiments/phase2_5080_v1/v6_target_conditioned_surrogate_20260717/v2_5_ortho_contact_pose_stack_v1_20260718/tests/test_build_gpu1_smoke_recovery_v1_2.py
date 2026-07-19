import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
MODULE_PATH = ROOT / "deployment" / "build_gpu1_smoke_recovery_v1_2.py"
SPEC = importlib.util.spec_from_file_location("build_gpu1_smoke_recovery_v1_2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class TestGPU1SmokeRecoveryV12(unittest.TestCase):
    def test_v1_2_generated_supervisors_are_isolated_compilable_and_terminal_aware(self):
        for value in (
            mod.SOURCE_REMOTE_ROOT,
            mod.OVERLAY_REMOTE_ROOT,
            mod.RUNTIME_REMOTE_ROOT,
            mod.AUTH_REMOTE_PATH,
            mod.AUTOSTART_REMOTE_ROOT,
            mod.WATCH_REMOTE_ROOT,
        ):
            self.assertIn("v1_2_20260718", value)
        launcher = mod.launcher_source("1" * 64, "2" * 64, "3" * 64, "4" * 64)
        compile(launcher, "generated_v1_2_launcher.py", "exec")
        self.assertIn("FAIL_GPU1_SEQUENTIAL_REAL_SMOKE_V1_2_RECOVERY", launcher)
        self.assertIn("verify_package(SOURCE_ROOT", launcher)
        autostart = mod.autostart_source(
            source_sha256s_sha="4" * 64,
            overlay_sha256s_sha="5" * 64,
            plan_sha="1" * 64,
            overlay_sha="2" * 64,
            launcher_sha="6" * 64,
        )
        compile(autostart, "generated_v1_2_autostart.py", "exec")
        self.assertIn("process.wait()", autostart)
        self.assertIn("PASS_GPU1_RECOVERY_AUTOSTART_V1_2_CHILD_TERMINAL_VERIFIED", autostart)


if __name__ == "__main__":
    unittest.main()
