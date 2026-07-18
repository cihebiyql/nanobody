import json
import tempfile
import unittest
from pathlib import Path

from .build_prefreeze_package_receipt_v1 import build, sha256


class ReceiptTests(unittest.TestCase):
    def fixture(self, root: Path):
        launcher = root / "launcher.py"; launcher.write_text("launcher\n")
        calibration_runner = root / "calibration.py"; calibration_runner.write_text("calibration\n")
        builder = root / "builder.py"; builder.write_text("builder\n")
        log = root / "tests.log"; log.write_text("Ran 24 tests in 1.0s\n\nOK\n")
        artifacts = {name: {"sha256": name * 2} for name in (
            "training_tsv", "training_receipt", "trainer", "trainer_test", "model",
            "outer_split_source", "outer_split_materialization_receipt", "contact_formula",
        )}
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "status": "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START",
            "production_authorized": False,
            "calibration_contract": {"binding_status": "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION"},
            "claim_boundary": "computational only", "artifacts": artifacts,
        }))
        dry = root / "dry.json"
        dry.write_text(json.dumps({
            "status": "PASS_PREFREEZE_DRY_RUN_BLOCKED_PENDING_CALIBRATION",
            "runtime_absent": True, "tiny_smoke_command_count": 4,
            "outer_development_planned_job_count": 20,
            "outer_development_command_count": 0, "manifest_sha256": sha256(manifest),
            "phase_order": ["OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE", "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"],
        }))
        calibration_dry = root / "calibration_dry.json"
        calibration_dry.write_text(json.dumps({
            "status": "PASS_OPEN_ONLY_PRESTEP_CALIBRATION_DRY_RUN_NO_MUTATION",
            "manifest_sha256": sha256(manifest), "command_count": 2,
            "optimizer_steps_before_observation": 0,
            "phase_order": ["OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE", "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"],
        }))
        return manifest, dry, calibration_dry, log, launcher, calibration_runner, builder

    def test_builds_non_executable_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self.fixture(root); output = root / "receipt.json"
            result = build(manifest_path=args[0], dry_run_path=args[1], calibration_dry_run_path=args[2], test_log_path=args[3], launcher_path=args[4], calibration_runner_path=args[5], manifest_builder_path=args[6], output_path=output)
            self.assertEqual(result["status"], "PASS_PREFREEZE_DEPLOYMENT_PACKAGE_CALIBRATION_PENDING_NO_FREEZE")
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["production_authorized"])
            self.assertEqual(receipt["dry_run"]["outer_executable_command_count"], 0)

    def test_rejects_outer_commands_before_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self.fixture(root); dry = json.loads(args[1].read_text())
            dry["outer_development_command_count"] = 1; args[1].write_text(json.dumps(dry))
            with self.assertRaisesRegex(RuntimeError, "outer_commands_exist"):
                build(manifest_path=args[0], dry_run_path=args[1], calibration_dry_run_path=args[2], test_log_path=args[3], launcher_path=args[4], calibration_runner_path=args[5], manifest_builder_path=args[6], output_path=root / "receipt.json")


if __name__ == "__main__":
    unittest.main()
