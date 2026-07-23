#!/usr/bin/env python3
"""Materialize the single externally frozen V2.20 Phase-1 head initial state."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch


SCHEMA_VERSION = "pvrig.v220.production_initial_state_materialization.v1"
SEED = 43


class InitialStateMaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InitialStateMaterializationError(message)


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


def seed_everything() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)


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


def materialize(
    args: argparse.Namespace,
    *,
    runner_module: Any | None = None,
    paired_module: Any | None = None,
) -> dict[str, Any]:
    require(args.fold_id == 0 and args.arm == "C0", "canonical_builder_must_use_fold0_C0")
    require(not args.initial_state.exists(), "initial_state_exists")
    receipt_path = Path(f"{args.initial_state}.receipt.json")
    require(not receipt_path.exists(), "initial_state_receipt_exists")
    require(not args.terminal.exists(), "terminal_exists")
    require(
        args.preregistration.is_file() and not args.preregistration.is_symlink(),
        "preregistration_invalid",
    )
    prereg = json.loads(args.preregistration.read_text(encoding="utf-8"))
    require(
        prereg.get("status") == "FROZEN_PRETRAINING_PHASE1_CORE_PROTOCOL",
        "preregistration_status",
    )
    runner = runner_module or load_module(args.runner, "v220_initial_state_runner")
    paired = paired_module or load_module(args.paired_helper, "v220_initial_state_helper")
    seed_everything()
    production_args = argparse.Namespace(**vars(args))
    # These runner fields are meaningful only when *loading* an already
    # externally frozen initial state.  During first materialization they are
    # internal, unreachable placeholders and are never presented as user
    # security controls.
    production_args.initial_state_receipt = receipt_path
    production_args.expected_initial_state_sha256 = "0" * 64
    production_args.expected_initial_state_receipt_sha256 = "0" * 64
    config, inputs = runner.prepare_production_inputs(production_args)
    require(config.fold_id == 0 and config.arm == "C0", "prepared_identity_drift")
    bindings = dict(inputs.input_bindings or {})
    scalar = prereg.get("data", {}).get("scalar_teacher", {})
    target = prereg.get("data", {}).get("fixed_target_graphs", {})
    contact = prereg.get("data", {}).get("contact_teacher", {})
    graph = prereg.get("data", {}).get("label_free_graph_cache", {})
    fold0 = {
        int(item["fold"]): item
        for item in prereg.get("strict_oof", {}).get("fold_bindings", [])
    }.get(0, {})
    require(
        bindings.get("scalar_contract_sha256") == fold0.get("contract_sha256"),
        "scalar_contract_prereg_mismatch",
    )
    require(
        bindings.get("training_table_sha256") == scalar.get("sha256"),
        "scalar_teacher_prereg_mismatch",
    )
    require(
        bindings.get("target_graph_sha256") == target.get("artifact_sha256"),
        "target_graph_prereg_mismatch",
    )
    require(
        bindings.get("target_graph_receipt_sha256") == target.get("receipt_sha256"),
        "target_graph_receipt_prereg_mismatch",
    )
    require(
        bindings.get("teacher_package_receipt_sha256")
        == contact.get("materialization_receipt_sha256"),
        "contact_teacher_receipt_prereg_mismatch",
    )
    require(
        bindings.get("graph_bundle_sha256") == graph.get("input_hashes"),
        "graph_bundle_prereg_mismatch",
    )
    receipt = paired.save_paired_initial_state(
        args.initial_state,
        inputs.model,
        0,
        SEED,
        backbone_identity_sha256=inputs.model_identity,
    )
    checkpoint_hash = sha256_file(args.initial_state)
    receipt_hash = sha256_file(receipt_path)
    verified = paired.load_and_verify_initial_state(
        args.initial_state,
        inputs.model,
        backbone_identity_sha256=inputs.model_identity,
        receipt_path=receipt_path,
        expected_checkpoint_sha256=checkpoint_hash,
        expected_receipt_sha256=receipt_hash,
    )
    require(verified.get("status") == "PASS_INITIAL_STATE_LOADED_AND_VERIFIED", "initial_state_verify_status")
    terminal = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V220_PHASE1_INITIAL_HEAD_STATE_MATERIALIZED_NO_TRAINING",
        "seed": SEED,
        "canonical_builder": {"fold_id": 0, "arm": "C0"},
        "serialized_state_scope": "model.head",
        "initial_state_path": str(args.initial_state),
        "initial_state_sha256": checkpoint_hash,
        "initial_state_receipt_path": str(receipt_path),
        "initial_state_receipt_sha256": receipt_hash,
        "backbone_binding": verified["backbone_binding"],
        "head_hashes": verified["hashes"],
        "training_started": False,
        "input_bindings": bindings,
        "preregistration_sha256": sha256_file(args.preregistration),
        "code_bindings": {
            "runner_sha256": sha256_file(args.runner),
            "paired_helper_sha256": sha256_file(args.paired_helper),
        },
    }
    atomic_json(args.terminal, terminal)
    return terminal


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--runner", type=Path, required=True)
    value.add_argument("--paired-helper", type=Path, required=True)
    value.add_argument("--preregistration", type=Path, required=True)
    value.add_argument("--terminal", type=Path, required=True)
    # The remaining arguments deliberately mirror the production fold runner.
    value.add_argument("--scalar-contract", type=Path, required=True)
    value.add_argument("--teacher-release", type=Path, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--initial-state", type=Path, required=True)
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
    result = materialize(args)
    print(json.dumps({"status": result["status"], "initial_state_sha256": result["initial_state_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
