from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validator = load(
    ROOT / "src" / "validate_v220_cross_process_initial_state_v1.py",
    "v220_cross_process_validator_test",
)


class CrossProcessValidatorTests(unittest.TestCase):
    def make_args(self, root: Path):
        runner = root / "runner.py"
        paired = root / "paired.py"
        initial = root / "initial.bin"
        receipt = root / "initial.bin.receipt.json"
        runner.write_text("runner\n")
        paired.write_text("paired\n")
        initial.write_bytes(b"initial")
        receipt.write_text("{}\n")
        hashes = {
            "src/run_v220_contact_shared_fold_v1.py": validator.sha256_file(runner),
            "src/materialize_v220_paired_initial_state_v1.py": validator.sha256_file(paired),
        }
        prereg = root / "prereg.json"
        prereg.write_text(
            json.dumps(
                {
                    "status": "FROZEN_PRETRAINING_PHASE1_CORE_PROTOCOL",
                    "implementation_hashes_before_initial_state_materialization": hashes,
                }
            )
        )
        return types.SimpleNamespace(
            seed=43,
            fold_id=0,
            arm="C0",
            output_dir=root / "must_not_exist",
            terminal=root / "terminal.json",
            preregistration=prereg,
            runner=runner,
            paired_helper=paired,
            initial_state=initial,
            initial_state_receipt=receipt,
            expected_initial_state_sha256=validator.sha256_file(initial),
            expected_initial_state_receipt_sha256=validator.sha256_file(receipt),
        )

    def test_cross_process_validation_has_no_training_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_args(root)
            model = object()
            inputs = types.SimpleNamespace(
                model=model,
                model_identity=hashlib.sha256(b"backbone").hexdigest(),
                input_bindings={"scalar": "bound"},
            )
            config = types.SimpleNamespace(fold_id=0, arm="C0")
            runner = types.SimpleNamespace(
                prepare_production_inputs=lambda observed: (config, inputs)
            )
            calls = []

            def load_initial(*positional, **keywords):
                calls.append((positional, keywords))
                return {
                    "status": "PASS_INITIAL_STATE_LOADED_AND_VERIFIED",
                    "backbone_binding": {"runtime_state_sha256": "a" * 64},
                    "hashes": {"head_state_sha256": "b" * 64},
                }

            paired = types.SimpleNamespace(load_and_verify_initial_state=load_initial)
            result = validator.validate(
                args, runner_module=runner, paired_module=paired
            )
            self.assertEqual(
                result["status"],
                "PASS_V220_CROSS_PROCESS_INITIAL_STATE_AND_BACKBONE_BINDING",
            )
            self.assertEqual(len(calls), 1)
            self.assertFalse(result["optimizer_created"])
            self.assertEqual(result["optimizer_steps"], 0)
            self.assertFalse(result["backward_called"])
            self.assertFalse(result["training_started"])
            self.assertFalse(args.output_dir.exists())
            self.assertTrue(args.terminal.is_file())

    def test_existing_unused_training_output_fails_before_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = self.make_args(root)
            args.output_dir.mkdir()
            runner = types.SimpleNamespace(
                prepare_production_inputs=lambda observed: self.fail("prepare called")
            )
            with self.assertRaises(validator.CrossProcessValidationError):
                validator.validate(
                    args, runner_module=runner, paired_module=types.SimpleNamespace()
                )


if __name__ == "__main__":
    unittest.main()
