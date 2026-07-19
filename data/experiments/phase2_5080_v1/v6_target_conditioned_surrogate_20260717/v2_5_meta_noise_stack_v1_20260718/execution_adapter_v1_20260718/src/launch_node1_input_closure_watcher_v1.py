#!/usr/bin/env python3
"""Launch the frozen input-only watcher on Node1 in a detached session."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from execution_common_v1 import atomic_write_json, read_json, require, sha256_file


DEPLOY_ROOT = Path("/data1/qlyu/projects/pvrig_v2_5_strict_meta_execution_adapter_v1_20260718")
UPSTREAM_PACKAGE = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718")
UPSTREAM_RUNTIME = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_1_20260718")
CLOSURE_OUTPUT = Path("/data1/qlyu/projects/pvrig_v2_5_strict_meta_input_closure_v1_20260718")
PYTHON = Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")

HASHES = {
    "adapter/EXECUTION_CONTRACT_V1.json": "d77b6181f780c632fda05056b44aea2d7c9eec3715e24c80c3b19b777b852d55",
    "adapter/EXECUTION_MANIFEST_V1.json": "ee6264048ae4e5612aeca1d092d5ade9cb1f347ae3b54c4f06caf60ce56370c3",
    "adapter/src/validate_v1_2_1_strict_inputs_v1.py": "28aa6f93bf7b754b1723fc7fa37c6d5459db9c3f0ce8b69e736859e706be4cd5",
    "adapter/src/watch_v1_2_1_terminal_then_validate_v1.py": "28af404d726eee84b00e7573f6417d6895dc2da6df603d69e23c6e92775c98a8",
    "adapter/src/execution_common_v1.py": "6c8309bd8ca232a3ed87f562d87439fcf0f4f378c676943c2766b095c610615c",
    "adapter/src/dry_run_execution_adapter_v1.py": "47532c47504ffeb316c48f28b432cb7142124df37f5df9aa35815a4a27ecd279",
    "adapter/src/evaluate_authorized_v2_5_strict_meta_v1.py": "d8a33a36309ec3363ce470b30228193e93af5784b1d6d739f16b5b11cfed4152",
    "src/meta_noise_stack_v1.py": "1f5c2b0ed7553a76a11f7011057004637606739b5577b69053494a484eb4af21",
    "src/c2_fold_local_v1.py": "281027a8a91df4ee4567c7eff5e58eca24548e01e0709b7b454e8c0853e34075",
}


def main() -> int:
    require(PYTHON.is_file(), "node1_python_missing")
    observed = {}
    for relative, expected in HASHES.items():
        path = DEPLOY_ROOT / relative
        value = sha256_file(path)
        require(value == expected, f"deployment_hash_mismatch:{relative}:{value}")
        observed[relative] = value
    manifest = read_json(DEPLOY_ROOT / "adapter/EXECUTION_MANIFEST_V1.json")
    require(manifest["execution_authorized"] is False, "manifest_authorized")
    require(manifest["formal_evaluator_launch_allowed"] is False, "manifest_evaluator_allowed")
    dry_run = read_json(DEPLOY_ROOT / "preauthorization_dry_run/PREAUTHORIZATION_DRY_RUN_RECEIPT.json")
    require(dry_run["status"] == "PASS_PREAUTHORIZATION_BUILD_TEST_DRY_RUN", "dry_run_status")
    require(dry_run["execution_authorized"] is False, "dry_run_authorized")
    require(dry_run["formal_evaluator_launched"] is False, "dry_run_evaluator_launched")
    require(dry_run["D_lane_outer_evidence_opened"] is False, "dry_run_opened_D_outer")

    CLOSURE_OUTPUT.mkdir(parents=True, exist_ok=True)
    log_path = CLOSURE_OUTPUT / "WATCHER.log"
    receipt_path = CLOSURE_OUTPUT / "DEPLOYMENT_RECEIPT.json"
    require(not receipt_path.exists(), "deployment_receipt_already_exists")
    command = [
        str(PYTHON), str(DEPLOY_ROOT / "adapter/src/watch_v1_2_1_terminal_then_validate_v1.py"),
        "--contract", str(DEPLOY_ROOT / "adapter/EXECUTION_CONTRACT_V1.json"),
        "--expected-contract-sha256", HASHES["adapter/EXECUTION_CONTRACT_V1.json"],
        "--validator", str(DEPLOY_ROOT / "adapter/src/validate_v1_2_1_strict_inputs_v1.py"),
        "--expected-validator-sha256", HASHES["adapter/src/validate_v1_2_1_strict_inputs_v1.py"],
        "--package-root", str(UPSTREAM_PACKAGE),
        "--runtime-root", str(UPSTREAM_RUNTIME),
        "--input-root", str(DEPLOY_ROOT / "inputs"),
        "--output-dir", str(CLOSURE_OUTPUT),
        "--poll-seconds", "60",
    ]
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    atomic_write_json(receipt_path, {
        "schema_version": "pvrig_v2_5_strict_meta_input_watcher_deployment_v1",
        "status": "PASS_INPUT_ONLY_WATCHER_LAUNCHED",
        "pid": process.pid,
        "command": command,
        "deployment_hashes": observed,
        "execution_authorized": False,
        "formal_evaluator_launched": False,
        "expected_terminal_status": "PASS_INPUTS_READY_UNAUTHORIZED",
        "v4_f_test32_access_count": 0,
    })
    print(json.dumps({"status": "PASS_INPUT_ONLY_WATCHER_LAUNCHED", "pid": process.pid}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
