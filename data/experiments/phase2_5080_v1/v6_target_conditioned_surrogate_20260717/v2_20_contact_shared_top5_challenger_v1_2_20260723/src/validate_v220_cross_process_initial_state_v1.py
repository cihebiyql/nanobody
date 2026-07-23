#!/usr/bin/env python3
"""Validate the frozen V2.20 initial state in a fresh production process."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig.v220.cross_process_initial_state_validation.v1"


class CrossProcessValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CrossProcessValidationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"file_invalid:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    require(path.is_file() and not path.is_symlink(), f"module_invalid:{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate(
    args: argparse.Namespace,
    *,
    runner_module: Any | None = None,
    paired_module: Any | None = None,
) -> dict[str, Any]:
    require(args.seed == 43, "seed_must_be_43")
    require(args.fold_id == 0 and args.arm == "C0", "canonical_fold0_C0_required")
    require(not args.output_dir.exists(), "unused_output_dir_must_not_exist")
    prereg = json.loads(args.preregistration.read_text(encoding="utf-8"))
    require(prereg.get("status") == "FROZEN_PRETRAINING_PHASE1_CORE_PROTOCOL", "prereg_status")
    hashes = prereg.get("implementation_hashes_before_initial_state_materialization") or {}
    require(hashes.get("src/run_v220_contact_shared_fold_v1.py") == sha256_file(args.runner), "runner_prereg_hash")
    require(hashes.get("src/materialize_v220_paired_initial_state_v1.py") == sha256_file(args.paired_helper), "paired_prereg_hash")
    runner = runner_module or load_module(args.runner, "v220_cross_process_runner")
    paired = paired_module or load_module(args.paired_helper, "v220_cross_process_paired")
    config, inputs = runner.prepare_production_inputs(args)
    require(config.fold_id == 0 and config.arm == "C0", "prepared_identity")
    receipt = paired.load_and_verify_initial_state(
        args.initial_state,
        inputs.model,
        backbone_identity_sha256=inputs.model_identity,
        receipt_path=args.initial_state_receipt,
        expected_checkpoint_sha256=args.expected_initial_state_sha256,
        expected_receipt_sha256=args.expected_initial_state_receipt_sha256,
    )
    require(receipt.get("status") == "PASS_INITIAL_STATE_LOADED_AND_VERIFIED", "load_status")
    require(not args.output_dir.exists(), "training_output_created")
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V220_CROSS_PROCESS_INITIAL_STATE_AND_BACKBONE_BINDING",
        "seed": 43,
        "fold_id": 0,
        "arm": "C0",
        "initial_state_sha256": sha256_file(args.initial_state),
        "initial_state_receipt_sha256": sha256_file(args.initial_state_receipt),
        "preregistration_sha256": sha256_file(args.preregistration),
        "runner_sha256": sha256_file(args.runner),
        "paired_helper_sha256": sha256_file(args.paired_helper),
        "backbone_binding": receipt["backbone_binding"],
        "head_hashes": receipt["hashes"],
        "input_bindings": dict(inputs.input_bindings or {}),
        "optimizer_created": False,
        "optimizer_steps": 0,
        "backward_called": False,
        "training_started": False,
        "unused_output_dir_created": False,
    }
    atomic_json(args.terminal, result)
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--runner", type=Path, required=True)
    value.add_argument("--paired-helper", type=Path, required=True)
    value.add_argument("--preregistration", type=Path, required=True)
    value.add_argument("--terminal", type=Path, required=True)
    value.add_argument("--scalar-contract", type=Path, required=True)
    value.add_argument("--teacher-release", type=Path, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--initial-state", type=Path, required=True)
    value.add_argument("--initial-state-receipt", type=Path, required=True)
    value.add_argument("--expected-initial-state-sha256", required=True)
    value.add_argument("--expected-initial-state-receipt-sha256", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--arm", choices=("C0",), default="C0")
    value.add_argument("--fold-id", type=int, choices=(0,), default=0)
    value.add_argument("--v213-runner", type=Path, required=True)
    value.add_argument("--device", default="cuda:0")
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--epochs", type=int, default=8)
    value.add_argument("--batch-size", type=int, default=8)
    value.add_argument("--eval-batch-size", type=int, default=16)
    value.add_argument("--gradient-accumulation", type=int, default=4)
    value.add_argument("--precision", default="bf16")
    value.add_argument("--learning-rate", type=float, default=1e-4)
    value.add_argument("--weight-decay", type=float, default=0.02)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--graph-hidden-dim", type=int, default=128)
    value.add_argument("--dropout", type=float, default=0.25)
    value.add_argument("--receptor-weight", type=float, default=1.0)
    value.add_argument("--dual-weight", type=float, default=0.5)
    value.add_argument("--huber-beta", type=float, default=0.03)
    value.add_argument("--softmin-tau", type=float, default=0.02)
    value.add_argument("--top-weight-strength", type=float, default=3.0)
    value.add_argument("--top-weight-center", type=float, default=0.85)
    value.add_argument("--top-weight-scale", type=float, default=0.05)
    value.add_argument("--backbone-kind", default="hf")
    value.add_argument("--backbone-dtype", default="bf16")
    value.add_argument("--model-path", type=Path, required=True)
    value.add_argument("--model-identity-file", type=Path, required=True)
    value.add_argument("--expected-model-sha256", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = validate(args)
    print(json.dumps({"status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
