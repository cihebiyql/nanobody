#!/usr/bin/env python3
"""Separate-process V1.3.1 shared-calibration load-only validator."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import torch

import v220_shared_calibration_artifact_v1 as shared


def require(condition: bool, message: str) -> None:
    if not condition:
        raise shared.SharedCalibrationError(message)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(shared.read_regular_snapshot(path)).hexdigest()


def load_upstream(path: Path, expected_sha256: str) -> Any:
    require(sha256_file(path) == expected_sha256, "upstream_runner_sha256")
    spec = importlib.util.spec_from_file_location("v220_v1_2_upstream_for_v1_3_1_load_only", path)
    require(spec is not None and spec.loader is not None, "upstream_runner_spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_upstream_siblings(args: argparse.Namespace) -> None:
    root = args.upstream_v1_2_runner.resolve().parent
    bindings = {
        "calibrate_v220_contact_weight_v1.py": args.expected_calibrator_sha256,
        "materialize_v220_paired_initial_state_v1.py": args.expected_paired_initial_state_sha256,
        "v220_contact_teacher_store_v1.py": args.expected_contact_teacher_store_sha256,
    }
    for name, expected in bindings.items():
        require(sha256_file(root / name) == expected, f"upstream_sibling_sha256:{name}")


def require_disjoint_output_paths(training_output_dir: Path, output_receipt: Path) -> None:
    output_dir = training_output_dir.resolve(strict=False)
    receipt = output_receipt.resolve(strict=False)
    require(output_dir != receipt, "receipt_training_output_same_path")
    require(output_dir not in receipt.parents, "receipt_inside_training_output")
    require(receipt not in output_dir.parents, "training_output_inside_receipt_path")


def validate(args: argparse.Namespace, upstream: Any) -> dict[str, Any]:
    validate_upstream_siblings(args)
    require(sha256_file(args.exact_once_helper) == args.expected_exact_once_helper_sha256, "exact_once_helper_sha256")
    config, inputs = upstream.prepare_production_inputs(args)
    config.validate()
    require(config.fold_id in range(5), "fold_id")
    require(config.seed == shared.SEED, "seed")
    require(not config.output_dir.exists(), "load_only_created_or_reused_training_output")
    require_disjoint_output_paths(config.output_dir, args.output_receipt)
    paired = upstream._sibling_module(
        "materialize_v220_paired_initial_state_v1.py", "v220_v1_3_1_load_only_paired"
    )
    calibration = upstream._sibling_module(
        "calibrate_v220_contact_weight_v1.py", "v220_v1_3_1_load_only_calibration"
    )
    inputs.base.seed_everything(config.seed)
    paired.load_and_verify_initial_state(
        config.initial_state_path,
        inputs.model,
        backbone_identity_sha256=inputs.model_identity,
        receipt_path=config.initial_state_receipt_path,
        expected_checkpoint_sha256=config.expected_initial_state_sha256,
        expected_receipt_sha256=config.expected_initial_state_receipt_sha256,
    )
    device = torch.device(config.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_unavailable")
    inputs.model.to(device)
    scalar_loss = inputs.trainer.OrthoLossConfig(
        receptor_weight=config.receptor_weight,
        dual_weight=config.dual_weight,
        marginal_weight=0.0,
        pair_weight=0.0,
        huber_beta=config.huber_beta,
        softmin_tau=config.softmin_tau,
    )
    adapter = upstream.CalibrationTrainerAdapter(inputs.base, inputs.trainer, scalar_loss)
    model_state = calibration.model_state_sha256(inputs.model)
    parameter_order = calibration.shared_parameter_order_sha256(
        adapter.shared_parameters(inputs.model)
    )
    bindings = shared.fold_frozen_bindings(
        upstream_runner_sha256=args.expected_upstream_v1_2_runner_sha256,
        input_bindings=inputs.input_bindings,
        expected_initial_state_sha256=config.expected_initial_state_sha256,
        expected_initial_state_receipt_sha256=config.expected_initial_state_receipt_sha256,
    )
    bindings.update({
        "upstream_calibrator": args.expected_calibrator_sha256,
        "upstream_paired_initial_state": args.expected_paired_initial_state_sha256,
        "upstream_contact_teacher_store": args.expected_contact_teacher_store_sha256,
        "exact_once_helper": args.expected_exact_once_helper_sha256,
    })
    loaded = {}
    raw_by_arm = {}
    for arm in shared.ARMS:
        artifact, raw = shared.load_shared_calibration_for_arm(
            artifact_path=args.shared_calibration_artifact,
            expected_artifact_sha256=args.expected_shared_calibration_sha256,
            fold_id=config.fold_id,
            arm=arm,
            frozen_bindings=bindings,
            expected_model_state_sha256=model_state,
            expected_shared_parameter_order_sha256=parameter_order,
            optimizer_created=False,
            backward_called=False,
            training_started=False,
        )
        loaded[arm] = {
            "selected_contact_weight": artifact["selected_contact_weight"],
            "shared_artifact_sha256": sha256_file(args.shared_calibration_artifact),
        }
        raw_by_arm[arm] = raw
    require(raw_by_arm["C0"] == raw_by_arm["C1"], "arm_load_bytes_differ")
    require(
        sha256_file(args.shared_calibration_artifact)
        == args.expected_shared_calibration_sha256,
        "artifact_changed_during_load_only",
    )
    require(not config.output_dir.exists(), "load_only_created_training_output")
    receipt_payload = {
        "schema_version": "pvrig.v220.v1_3_1_shared_calibration_load_only.v1",
        "status": "PASS_V220_V1_3_1_SHARED_CALIBRATION_SEPARATE_PROCESS_LOAD_ONLY",
        "fold_id": config.fold_id,
        "seed": config.seed,
        "loaded_arms": loaded,
        "same_bytes_for_both_arms": True,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
        "run_fold_core_called": False,
        "training_output_created": False,
    }
    shared.atomic_json_new(args.output_receipt, receipt_payload)
    require(not config.output_dir.exists(), "load_only_created_training_output_after_receipt")
    return receipt_payload


def parser(upstream: Any) -> argparse.ArgumentParser:
    value = upstream.parser()
    value.add_argument("--upstream-v1-2-runner", type=Path, required=True)
    value.add_argument("--expected-upstream-v1-2-runner-sha256", required=True)
    value.add_argument("--shared-calibration-artifact", type=Path, required=True)
    value.add_argument("--expected-shared-calibration-sha256", required=True)
    value.add_argument("--output-receipt", type=Path, required=True)
    value.add_argument("--expected-calibrator-sha256", required=True)
    value.add_argument("--expected-paired-initial-state-sha256", required=True)
    value.add_argument("--expected-contact-teacher-store-sha256", required=True)
    value.add_argument("--exact-once-helper", type=Path, required=True)
    value.add_argument("--expected-exact-once-helper-sha256", required=True)
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
    result = validate(args, upstream)
    print(json.dumps({"status": result["status"], "fold_id": result["fold_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
