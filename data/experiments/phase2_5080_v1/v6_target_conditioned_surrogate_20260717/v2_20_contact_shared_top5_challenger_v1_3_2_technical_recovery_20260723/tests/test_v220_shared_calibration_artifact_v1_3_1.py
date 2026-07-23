from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "shared_calibration", ROOT / "src" / "v220_shared_calibration_artifact_v1.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(ROOT / "src"))
RUN_SPEC = importlib.util.spec_from_file_location(
    "v131_arm_runner", ROOT / "src" / "run_v220_contact_shared_fold_v1_3_1.py"
)
RUN_MODULE = importlib.util.module_from_spec(RUN_SPEC)
assert RUN_SPEC and RUN_SPEC.loader
RUN_SPEC.loader.exec_module(RUN_MODULE)


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def calibration(**updates):
    value = {
        "status": MODULE.PASS_STATUS,
        "contact_batch_count": 8,
        "lambda_grid": list(MODULE.LAMBDA_GRID),
        "selected_contact_weight": 0.0025,
        "severe_conflict_batch_count": 0,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
        "model_state_sha256_before": HEX_A,
        "model_state_sha256_after": HEX_A,
        "shared_parameter_order_sha256": HEX_B,
        "observations": [{"batch_id": f"b{i}"} for i in range(8)],
    }
    value.update(updates)
    return value


class SharedCalibrationArtifactTests(unittest.TestCase):
    def materialize(self, root: Path, counter: list[int] | None = None):
        calls = counter if counter is not None else []

        def callback():
            calls.append(1)
            return calibration()

        path = root / "fold_0" / "SHARED_CALIBRATION.json"
        digest, raw = MODULE.materialize_shared_calibration_once(
            output_path=path,
            fold_id=0,
            calibration_fn=callback,
            frozen_bindings={"contract": HEX_C},
            expected_model_state_sha256=HEX_A,
            expected_shared_parameter_order_sha256=HEX_B,
        )
        return path, digest, raw, calls

    def test_one_materialization_two_arms_exact_same_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, digest, raw, calls = self.materialize(root)
            self.assertEqual(calls, [1])
            arm_payloads = []
            for arm in MODULE.ARMS:
                payload, observed = MODULE.load_shared_calibration_for_arm(
                    artifact_path=path,
                    expected_artifact_sha256=digest,
                    fold_id=0,
                    arm=arm,
                    frozen_bindings={"contract": HEX_C},
                    expected_model_state_sha256=HEX_A,
                    expected_shared_parameter_order_sha256=HEX_B,
                    optimizer_created=False,
                    backward_called=False,
                    training_started=False,
                )
                self.assertEqual(payload["selected_contact_weight"], 0.0025)
                arm_payloads.append(observed)
                MODULE.copy_exact_artifact_to_arm(
                    raw=observed,
                    output_path=root / arm / "fold_0" / "CONTACT_WEIGHT_CALIBRATION.json",
                    expected_sha256=digest,
                )
            self.assertEqual(arm_payloads, [raw, raw])
            self.assertEqual(
                (root / "C0/fold_0/CONTACT_WEIGHT_CALIBRATION.json").read_bytes(),
                (root / "C1/fold_0/CONTACT_WEIGHT_CALIBRATION.json").read_bytes(),
            )

    def test_existing_artifact_cannot_be_recomputed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _, _, calls = self.materialize(root)
            with self.assertRaises(MODULE.SharedCalibrationError):
                MODULE.materialize_shared_calibration_once(
                    output_path=path,
                    fold_id=0,
                    calibration_fn=lambda: calls.append(2) or calibration(),
                    frozen_bindings={"contract": HEX_C},
                    expected_model_state_sha256=HEX_A,
                    expected_shared_parameter_order_sha256=HEX_B,
                )
            self.assertEqual(calls, [1])

    def test_hash_mismatch_fails_before_optimizer(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _, _ = self.materialize(Path(directory))
            with self.assertRaisesRegex(MODULE.SharedCalibrationError, "artifact_sha256"):
                MODULE.load_shared_calibration_for_arm(
                    artifact_path=path,
                    expected_artifact_sha256="d" * 64,
                    fold_id=0,
                    arm="C0",
                    frozen_bindings={"contract": HEX_C},
                    expected_model_state_sha256=HEX_A,
                    expected_shared_parameter_order_sha256=HEX_B,
                    optimizer_created=False,
                    backward_called=False,
                    training_started=False,
                )

    def test_any_prior_optimizer_backward_or_training_activity_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path, digest, _, _ = self.materialize(Path(directory))
            for field in ("optimizer_created", "backward_called", "training_started"):
                flags = dict(optimizer_created=False, backward_called=False, training_started=False)
                flags[field] = True
                with self.subTest(field=field), self.assertRaises(MODULE.SharedCalibrationError):
                    MODULE.load_shared_calibration_for_arm(
                        artifact_path=path,
                        expected_artifact_sha256=digest,
                        fold_id=0,
                        arm="C1",
                        frozen_bindings={"contract": HEX_C},
                        expected_model_state_sha256=HEX_A,
                        expected_shared_parameter_order_sha256=HEX_B,
                        **flags,
                    )

    def test_fold_seed_and_binding_are_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, digest, raw, _ = self.materialize(root)
            common = dict(
                artifact_path=path,
                expected_artifact_sha256=digest,
                arm="C0",
                expected_model_state_sha256=HEX_A,
                expected_shared_parameter_order_sha256=HEX_B,
                optimizer_created=False,
                backward_called=False,
                training_started=False,
            )
            with self.assertRaisesRegex(MODULE.SharedCalibrationError, "artifact_fold"):
                MODULE.load_shared_calibration_for_arm(fold_id=1, frozen_bindings={"contract": HEX_C}, **common)
            with self.assertRaisesRegex(MODULE.SharedCalibrationError, "artifact_bindings"):
                MODULE.load_shared_calibration_for_arm(fold_id=0, frozen_bindings={"contract": "d" * 64}, **common)
            value = json.loads(raw)
            value["seed"] = 917
            tampered = MODULE.canonical_json_bytes(value)
            path.write_bytes(tampered)
            with self.assertRaisesRegex(MODULE.SharedCalibrationError, "artifact_seed"):
                MODULE.load_shared_calibration_for_arm(
                    fold_id=0,
                    frozen_bindings={"contract": HEX_C},
                    expected_artifact_sha256=MODULE.sha256_bytes(tampered),
                    **{k: v for k, v in common.items() if k not in {"artifact_path", "expected_artifact_sha256"}},
                    artifact_path=path,
                )

    def test_semantic_contract_rejects_every_frozen_violation(self):
        invalid = [
            {"status": "FAIL"},
            {"contact_batch_count": 7},
            {"lambda_grid": [0.1]},
            {"selected_contact_weight": 0.1},
            {"severe_conflict_batch_count": 3},
            {"optimizer_created": True},
            {"optimizer_steps": 1},
            {"backward_called": True},
            {"training_started": True},
            {"model_state_sha256_after": "d" * 64},
            {"model_state_sha256_before": "d" * 64, "model_state_sha256_after": "d" * 64},
            {"shared_parameter_order_sha256": "d" * 64},
        ]
        for updates in invalid:
            with self.subTest(updates=updates), self.assertRaises(MODULE.SharedCalibrationError):
                MODULE.validate_calibration_payload(
                    calibration(**updates),
                    expected_model_state_sha256=HEX_A,
                    expected_shared_parameter_order_sha256=HEX_B,
                )

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, digest, _, _ = self.materialize(root)
            link = root / "link.json"
            link.symlink_to(path)
            with self.assertRaises(MODULE.SharedCalibrationError):
                MODULE.load_shared_calibration_for_arm(
                    artifact_path=link,
                    expected_artifact_sha256=digest,
                    fold_id=0,
                    arm="C0",
                    frozen_bindings={"contract": HEX_C},
                    expected_model_state_sha256=HEX_A,
                    expected_shared_parameter_order_sha256=HEX_B,
                    optimizer_created=False,
                    backward_called=False,
                    training_started=False,
                )

    def test_arm_replay_returns_shared_payload_once_without_true_calibration(self):
        class FakeCalibration:
            @staticmethod
            def model_state_sha256(model):
                self.assertIs(model, fake_model)
                return HEX_A

            @staticmethod
            def shared_parameter_order_sha256(parameters):
                self.assertEqual(parameters, [("p", "parameter")])
                return HEX_B

        class FakeTrainer:
            @staticmethod
            def shared_parameters(model):
                self.assertIs(model, fake_model)
                return [("p", "parameter")]

        with tempfile.TemporaryDirectory() as directory:
            path, digest, _, _ = self.materialize(Path(directory))
            fake_model = object()
            replay = RUN_MODULE.SharedCalibrationReplay(
                shared_artifact_path=path,
                expected_artifact_sha256=digest,
                fold_id=0,
                arm="C1",
                frozen_bindings={"contract": HEX_C},
                calibration_module=FakeCalibration,
            )
            payload = replay(
                fake_model,
                FakeTrainer,
                [],
                {"8x6b": object(), "9e6y": object()},
                "cuda:0",
                "bf16",
                grid=MODULE.LAMBDA_GRID,
            )
            self.assertEqual(payload["selected_contact_weight"], 0.0025)
            self.assertEqual(replay.invocations, 1)
            with self.assertRaisesRegex(RUN_MODULE.shared.SharedCalibrationError, "more_than_once"):
                replay(
                    fake_model,
                    FakeTrainer,
                    [],
                    {"8x6b": object()},
                    "cuda:0",
                    "bf16",
                    grid=MODULE.LAMBDA_GRID,
                )

    def test_execution_sources_preserve_single_materializer_and_zero_arm_calibrator(self):
        materializer = (ROOT / "src/materialize_v220_shared_fold_calibration_v1_3_1.py").read_text()
        arm = (ROOT / "src/run_v220_contact_shared_fold_v1_3_1.py").read_text()
        self.assertIn("calibration.calibrate_contact_weight(", materializer)
        self.assertIn("require(calls == 1", materializer)
        self.assertNotIn("build_optimizer(", materializer)
        self.assertNotIn(".backward(", materializer)
        self.assertNotIn("calibration.calibrate_contact_weight(", arm)
        self.assertIn("upstream.run_fold_core(config, inputs, calibrator=replay)", arm)
        prereg = json.loads((ROOT / "PREREGISTRATION_PHASE1_TECHNICAL_RECOVERY_V1_3_2.json").read_text())
        self.assertFalse(prereg["authorization"]["training_authorized"])
        self.assertTrue(prereg["non_interference"]["all_ten_arms_must_rerun"])
        self.assertFalse(prereg["non_interference"]["v1_2_or_rejected_v1_3_training_output_input"])


if __name__ == "__main__":
    unittest.main()
