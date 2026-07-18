from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "run_preliminary_calibration_diagnostic_v1",
    HERE / "run_preliminary_calibration_diagnostic_v1.py",
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class PreliminaryDiagnosticRunnerTests(unittest.TestCase):
    def test_runs_both_lanes_and_never_authorizes_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            runtime = base / "runtime"
            command = [
                sys.executable, "-c", "import sys; raise SystemExit(0)",
                "--calibration-only",
            ]
            plan = {
                "status": mod.EXPECTED_STATUS,
                "optimizer_steps": 0,
                "outer_metrics_access_count": 0,
                "runtime_root": str(runtime),
                "claim_boundary": "diagnostic only",
                "commands": {
                    lane: {"gpu": gpu, "command": command}
                    for lane, gpu in (("C_SPLIT_MARGINAL", 4), ("D_SPLIT_PAIR", 5))
                },
            }
            plan_path = base / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result = mod.run(plan_path)
            self.assertEqual(result["status"], "PASS_PRELIMINARY_DIAGNOSTIC_EXECUTION")
            self.assertFalse(result["promotion_authorized"])
            self.assertFalse(result["implementation_freeze_authorized"])
            self.assertEqual(result["optimizer_steps"], 0)

    def test_rejects_missing_calibration_only_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            plan = {
                "status": mod.EXPECTED_STATUS,
                "optimizer_steps": 0,
                "outer_metrics_access_count": 0,
                "runtime_root": str(base / "runtime"),
                "claim_boundary": "diagnostic only",
                "commands": {
                    lane: {"gpu": gpu, "command": [sys.executable, "-c", "pass"]}
                    for lane, gpu in (("C_SPLIT_MARGINAL", 4), ("D_SPLIT_PAIR", 5))
                },
            }
            plan_path = base / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "diagnostic_not_calibration_only"):
                mod.run(plan_path)


if __name__ == "__main__":
    unittest.main()
