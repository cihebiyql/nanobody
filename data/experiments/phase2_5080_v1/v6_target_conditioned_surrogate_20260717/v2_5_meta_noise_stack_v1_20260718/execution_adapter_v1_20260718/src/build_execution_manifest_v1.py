#!/usr/bin/env python3
"""Build an immutable, explicitly unauthorized V2.5 execution manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from execution_common_v1 import (
    assert_exact_model_matrix,
    atomic_write_json,
    read_json,
    require,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--base-freeze", required=True)
    parser.add_argument("--validator", required=True)
    parser.add_argument("--watcher", required=True)
    parser.add_argument("--evaluator", required=True)
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--common", required=True)
    parser.add_argument("--meta-module", required=True)
    parser.add_argument("--c2-module", required=True)
    parser.add_argument("--node1-package-root", required=True)
    parser.add_argument("--node1-runtime-root", required=True)
    parser.add_argument("--node1-input-root", required=True)
    parser.add_argument("--node1-closure-output", required=True)
    parser.add_argument("--node1-adapter-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    contract_path = Path(args.contract).resolve()
    contract = read_json(contract_path)
    require(contract["status"] == "FROZEN_DESIGN_UNAUTHORIZED_DO_NOT_EVALUATE", "contract_status")
    require(contract["authorization"]["execution_authorized"] is False, "contract_authorized")
    assert_exact_model_matrix(contract)
    code_paths = {
        "validator": Path(args.validator).resolve(),
        "watcher": Path(args.watcher).resolve(),
        "evaluator": Path(args.evaluator).resolve(),
        "dry_run": Path(args.dry_run).resolve(),
        "common": Path(args.common).resolve(),
        "meta_noise_module": Path(args.meta_module).resolve(),
        "c2_fold_local_module": Path(args.c2_module).resolve(),
    }
    manifest = {
        "schema_version": "pvrig_v2_5_strict_meta_execution_manifest_v1",
        "status": "FROZEN_UNAUTHORIZED_INPUT_VALIDATION_ONLY",
        "execution_authorized": False,
        "formal_evaluator_launch_allowed": False,
        "contract": {
            "path": str(contract_path),
            "node1_path": str(Path(args.node1_adapter_root) / "adapter" / contract_path.name),
            "sha256": sha256_file(contract_path),
        },
        "base_implementation_freeze": {
            "path": str(Path(args.base_freeze).resolve()),
            "sha256": sha256_file(Path(args.base_freeze).resolve()),
        },
        "code": {
            name: {
                "path": str(path),
                "node1_path": str(
                    Path(args.node1_adapter_root)
                    / ("src" if name in {"meta_noise_module", "c2_fold_local_module"} else "adapter/src")
                    / path.name
                ),
                "sha256": sha256_file(path),
            }
            for name, path in code_paths.items()
        },
        "canonical_inputs": contract["canonical_inputs"],
        "formal_model_matrix": contract["formal_model_matrix"],
        "formal_gates": contract["formal_gates"],
        "node1": {
            "upstream_package_root": args.node1_package_root,
            "upstream_runtime_root": args.node1_runtime_root,
            "adapter_input_root": args.node1_input_root,
            "input_closure_output": args.node1_closure_output,
        },
        "preauthorization_action": "WATCH_FOR_STRICT_TERMINAL_THEN_VALIDATE_D_LANE_INPUT_CLOSURE_ONLY",
        "postauthorization_command_template": [
            "python", str(Path(args.node1_adapter_root) / "adapter/src" / code_paths["evaluator"].name),
            "--execution-manifest", str(Path(args.node1_adapter_root) / "adapter" / "EXECUTION_MANIFEST_V1.json"),
            "--input-closure-receipt", "<PINNED_INPUT_CLOSURE_RECEIPT>",
            "--authorization-overlay", "<SEPARATELY_CREATED_AUTHORIZATION_OVERLAY>",
            "--authorization-token", "<RUNTIME_ONLY_NOT_STORED>",
            "--output-dir", "<NEW_EMPTY_FORMAL_OUTPUT_DIRECTORY>",
        ],
        "authorization_requirements": contract["authorization"],
        "v4_f_test32_access_count": 0,
        "claim_boundary": contract["claim_boundary"],
    }
    atomic_write_json(Path(args.output).resolve(), manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
