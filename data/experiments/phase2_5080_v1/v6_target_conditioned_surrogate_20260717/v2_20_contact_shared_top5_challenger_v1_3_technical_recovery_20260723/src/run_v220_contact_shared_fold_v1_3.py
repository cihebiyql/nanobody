#!/usr/bin/env python3
"""Run one fresh V2.20 V1.3 arm using a shared fold calibration artifact."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import v220_shared_calibration_artifact_v1 as shared


def require(condition: bool, message: str) -> None:
    if not condition:
        raise shared.SharedCalibrationError(message)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(shared.read_regular_snapshot(path)).hexdigest()


def load_upstream(path: Path, expected_sha256: str) -> Any:
    require(sha256_file(path) == expected_sha256, "upstream_runner_sha256")
    spec = importlib.util.spec_from_file_location("v220_v1_2_upstream_for_v1_3_arm", path)
    require(spec is not None and spec.loader is not None, "upstream_runner_spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SharedCalibrationReplay:
    def __init__(
        self,
        *,
        shared_artifact_path: Path,
        expected_artifact_sha256: str,
        fold_id: int,
        arm: str,
        frozen_bindings: Mapping[str, str],
        calibration_module: Any,
    ) -> None:
        self.shared_artifact_path = shared_artifact_path
        self.expected_artifact_sha256 = expected_artifact_sha256
        self.fold_id = fold_id
        self.arm = arm
        self.frozen_bindings = dict(frozen_bindings)
        self.calibration_module = calibration_module
        self.invocations = 0

    def __call__(self, model, trainer, batches, target_graphs, device, precision, *, grid):
        del batches
        self.invocations += 1
        require(self.invocations == 1, "arm_calibration_replay_called_more_than_once")
        require(tuple(grid) == shared.LAMBDA_GRID, "arm_lambda_grid")
        require(target_graphs is not None, "arm_target_graphs_missing")
        require(str(precision) in {"bf16", "fp32"}, "arm_precision")
        model_state = self.calibration_module.model_state_sha256(model)
        parameter_order = self.calibration_module.shared_parameter_order_sha256(
            trainer.shared_parameters(model)
        )
        artifact, _ = shared.load_shared_calibration_for_arm(
            artifact_path=self.shared_artifact_path,
            expected_artifact_sha256=self.expected_artifact_sha256,
            fold_id=self.fold_id,
            arm=self.arm,
            frozen_bindings=self.frozen_bindings,
            expected_model_state_sha256=model_state,
            expected_shared_parameter_order_sha256=parameter_order,
            optimizer_created=False,
            backward_called=False,
            training_started=False,
        )
        return artifact


def run(args: argparse.Namespace, upstream: Any) -> dict[str, Any]:
    config, inputs = upstream.prepare_production_inputs(args)
    calibration = upstream._sibling_module(
        "calibrate_v220_contact_weight_v1.py", "v220_v1_3_arm_calibration_validator"
    )
    frozen_bindings = shared.fold_frozen_bindings(
        upstream_runner_sha256=args.expected_upstream_v1_2_runner_sha256,
        input_bindings=inputs.input_bindings,
        expected_initial_state_sha256=config.expected_initial_state_sha256,
        expected_initial_state_receipt_sha256=config.expected_initial_state_receipt_sha256,
    )
    replay = SharedCalibrationReplay(
        shared_artifact_path=args.shared_calibration_artifact,
        expected_artifact_sha256=args.expected_shared_calibration_sha256,
        fold_id=config.fold_id,
        arm=config.arm,
        frozen_bindings=frozen_bindings,
        calibration_module=calibration,
    )
    result = upstream.run_fold_core(config, inputs, calibrator=replay)
    require(replay.invocations == 1, "arm_calibration_replay_invocation_count")
    require(
        sha256_file(args.shared_calibration_artifact)
        == args.expected_shared_calibration_sha256,
        "shared_artifact_changed_during_arm",
    )
    arm_copy = config.output_dir / upstream.CALIBRATION_NAME
    require(sha256_file(arm_copy) == args.expected_shared_calibration_sha256, "arm_copy_not_exact_shared_artifact")
    require(
        result["outputs"][upstream.CALIBRATION_NAME]
        == args.expected_shared_calibration_sha256,
        "result_calibration_hash",
    )
    replay_receipt = {
        "schema_version": "pvrig.v220.v1_3_shared_calibration_replay_receipt.v1",
        "status": "PASS_V220_V1_3_ARM_USED_SHARED_CALIBRATION_NO_RECALIBRATION",
        "fold_id": config.fold_id,
        "arm": config.arm,
        "seed": config.seed,
        "shared_artifact_sha256": args.expected_shared_calibration_sha256,
        "replay_invocations": replay.invocations,
        "arm_side_true_calibrator_invocations": 0,
        "arm_calibration_copy_sha256": sha256_file(arm_copy),
        "result_sha256_before_replay_receipt": sha256_file(
            config.output_dir / upstream.RESULT_NAME
        ),
    }
    shared.atomic_json_new(
        config.output_dir / "V1_3_SHARED_CALIBRATION_REPLAY_RECEIPT.json",
        replay_receipt,
    )
    return result


def parser(upstream: Any) -> argparse.ArgumentParser:
    value = upstream.parser()
    value.add_argument("--upstream-v1-2-runner", type=Path, required=True)
    value.add_argument("--expected-upstream-v1-2-runner-sha256", required=True)
    value.add_argument("--shared-calibration-artifact", type=Path, required=True)
    value.add_argument("--expected-shared-calibration-sha256", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--upstream-v1-2-runner", type=Path, required=True)
    bootstrap.add_argument("--expected-upstream-v1-2-runner-sha256", required=True)
    known, _ = bootstrap.parse_known_args(argv)
    upstream = load_upstream(
        known.upstream_v1_2_runner, known.expected_upstream_v1_2_runner_sha256
    )
    args = parser(upstream).parse_args(argv)
    result = run(args, upstream)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
