#!/usr/bin/env python3
"""Materialize one V2.20 V1.3.1 shared fold calibration before either arm."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
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
    spec = importlib.util.spec_from_file_location("v220_v1_2_upstream_for_v1_3_materializer", path)
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


def validate_exact_once_lock(args: argparse.Namespace, fold_id: int) -> tuple[Path, str, Path]:
    """Require the helper-created fold lock before any calibration call."""

    lock_dir = args.shared_lock_dir.resolve(strict=True)
    artifact_parent = args.shared_calibration_artifact.parent.resolve(strict=True)
    require(lock_dir.is_dir() and not args.shared_lock_dir.is_symlink(), "shared_lock_dir")
    require(artifact_parent == lock_dir, "artifact_parent_not_shared_lock_dir")
    require(args.shared_calibration_artifact.name == "CONTACT_WEIGHT_CALIBRATION.json", "artifact_name")
    require(lock_dir.name == f"fold_{fold_id}", "lock_fold_binding")
    require(lock_dir.parent.name == "shared_calibration", "lock_parent_name")
    helper_sha = sha256_file(args.exact_once_helper)
    require(helper_sha == args.expected_exact_once_helper_sha256, "exact_once_helper_sha256")
    require(os.environ.get("V220_V131_EXACT_ONCE_HELPER_SHA256") == helper_sha, "helper_environment_binding")
    require(os.environ.get("V220_V131_EXACT_ONCE_LOCK_DIR") == str(lock_dir), "lock_environment_binding")
    token = os.environ.get("V220_V131_EXACT_ONCE_LOCK_TOKEN", "")
    require(len(token) == 64 and all(char in "0123456789abcdef" for char in token), "lock_token_environment")
    lock_receipt_path = lock_dir / "EXACT_ONCE_LOCK.json"
    lock_receipt = json.loads(shared.read_regular_snapshot(lock_receipt_path))
    require(lock_receipt.get("schema_version") == "pvrig.v220.v1_3_1.exact_once_lock.v1", "lock_receipt_schema")
    require(lock_receipt.get("helper_sha256") == helper_sha, "lock_receipt_helper")
    require(lock_receipt.get("token") == token, "lock_receipt_token")
    return lock_dir, helper_sha, lock_receipt_path


def materialize(args: argparse.Namespace, upstream: Any) -> dict[str, Any]:
    validate_upstream_siblings(args)
    config, inputs = upstream.prepare_production_inputs(args)
    config.validate()
    require(config.fold_id in range(5), "fold_id")
    require(config.seed == shared.SEED, "seed")
    require(not config.output_dir.exists(), "training_output_exists_before_calibration")
    lock_dir, helper_sha, lock_receipt_path = validate_exact_once_lock(args, config.fold_id)

    paired = upstream._sibling_module(
        "materialize_v220_paired_initial_state_v1.py", "v220_v1_3_shared_paired_state"
    )
    calibration = upstream._sibling_module(
        "calibrate_v220_contact_weight_v1.py", "v220_v1_3_shared_calibrator"
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
    truth_percentiles = inputs.base.training_truth_percentiles(
        inputs.rows, inputs.split.train_indices
    )
    weights = {
        index: inputs.rows[index].sample_weight
        * inputs.base.top_weight(
            truth_percentiles[index],
            config.top_weight_strength,
            config.top_weight_center,
            config.top_weight_scale,
        )
        for index in inputs.split.train_indices
    }
    collator = inputs.base.CleanCollator(
        inputs.rows, inputs.tokenizer, inputs.graph_store, weights, truth_percentiles
    )
    device = torch.device(config.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_unavailable")
    require(config.precision == "fp32" or device.type == "cuda", "bf16_requires_cuda")
    inputs.model.to(device)
    scalar_loss = inputs.trainer.OrthoLossConfig(
        receptor_weight=config.receptor_weight,
        dual_weight=config.dual_weight,
        marginal_weight=0.0,
        pair_weight=0.0,
        huber_beta=config.huber_beta,
        softmin_tau=config.softmin_tau,
    )
    batches = upstream._prepare_calibration_batches(config, inputs, collator)
    adapter = upstream.CalibrationTrainerAdapter(inputs.base, inputs.trainer, scalar_loss)
    model_state = calibration.model_state_sha256(inputs.model)
    parameter_order = calibration.shared_parameter_order_sha256(
        adapter.shared_parameters(inputs.model)
    )
    frozen_bindings = shared.fold_frozen_bindings(
        upstream_runner_sha256=args.expected_upstream_v1_2_runner_sha256,
        input_bindings=inputs.input_bindings,
        expected_initial_state_sha256=config.expected_initial_state_sha256,
        expected_initial_state_receipt_sha256=config.expected_initial_state_receipt_sha256,
    )
    frozen_bindings.update({
        "upstream_calibrator": args.expected_calibrator_sha256,
        "upstream_paired_initial_state": args.expected_paired_initial_state_sha256,
        "upstream_contact_teacher_store": args.expected_contact_teacher_store_sha256,
        "exact_once_helper": helper_sha,
    })
    calls = 0

    def calibrate_once():
        nonlocal calls
        calls += 1
        require(calls == 1, "calibrator_called_more_than_once")
        return calibration.calibrate_contact_weight(
            inputs.model,
            adapter,
            batches,
            inputs.target_graphs,
            device,
            config.precision,
            grid=upstream.FIXED_LAMBDA_GRID,
        )

    digest, _ = shared.materialize_shared_calibration_once(
        output_path=args.shared_calibration_artifact,
        fold_id=config.fold_id,
        calibration_fn=calibrate_once,
        frozen_bindings=frozen_bindings,
        expected_model_state_sha256=model_state,
        expected_shared_parameter_order_sha256=parameter_order,
    )
    require(calls == 1, "calibrator_invocation_count")
    require(not config.output_dir.exists(), "materializer_created_training_output")
    return {
        "schema_version": "pvrig.v220.shared_fold_calibration_materializer.v1_3_1",
        "status": "PASS_V220_SHARED_FOLD_CALIBRATION_MATERIALIZED_NO_TRAINING",
        "fold_id": config.fold_id,
        "seed": config.seed,
        "shared_calibration_path": str(args.shared_calibration_artifact),
        "shared_calibration_sha256": digest,
        "shared_lock_dir": str(lock_dir),
        "exact_once_helper_sha256": helper_sha,
        "exact_once_lock_receipt_sha256": sha256_file(lock_receipt_path),
        "calibrator_invocations": calls,
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
    }


def parser(upstream: Any) -> argparse.ArgumentParser:
    value = upstream.parser()
    value.add_argument("--upstream-v1-2-runner", type=Path, required=True)
    value.add_argument("--expected-upstream-v1-2-runner-sha256", required=True)
    value.add_argument("--shared-calibration-artifact", type=Path, required=True)
    value.add_argument("--shared-lock-dir", type=Path, required=True)
    value.add_argument("--exact-once-helper", type=Path, required=True)
    value.add_argument("--expected-exact-once-helper-sha256", required=True)
    value.add_argument("--expected-calibrator-sha256", required=True)
    value.add_argument("--expected-paired-initial-state-sha256", required=True)
    value.add_argument("--expected-contact-teacher-store-sha256", required=True)
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
    result = materialize(args, upstream)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
