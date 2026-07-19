#!/usr/bin/env python3
"""Hash-gated watcher that stops after structural input closure."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from execution_common_v1 import atomic_write_json, read_json, require, sha256_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--validator", required=True)
    parser.add_argument("--expected-validator-sha256", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--max-polls", type=int, default=0)
    args = parser.parse_args()

    contract = Path(args.contract).resolve()
    validator = Path(args.validator).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    require(sha256_file(contract) == args.expected_contract_sha256, "watcher_contract_hash")
    require(sha256_file(validator) == args.expected_validator_sha256, "watcher_validator_hash")
    require(args.poll_seconds >= 0, "negative_poll_seconds")
    require(args.max_polls >= 0, "negative_max_polls")

    command = [
        sys.executable, str(validator),
        "--contract", str(contract),
        "--package-root", str(Path(args.package_root).resolve()),
        "--runtime-root", str(Path(args.runtime_root).resolve()),
        "--input-root", str(Path(args.input_root).resolve()),
        "--output-dir", str(output),
        "--allow-waiting",
    ]
    polls = 0
    while True:
        completed = subprocess.run(command, check=False)
        receipt_path = output / "INPUT_CLOSURE_RECEIPT.json"
        receipt = read_json(receipt_path)
        status = str(receipt.get("status"))
        atomic_write_json(output / "WATCHER_STATUS.json", {
            "schema_version": "pvrig_v2_5_strict_input_watcher_status_v1",
            "status": status,
            "poll_count": polls + 1,
            "validator_returncode": completed.returncode,
            "execution_authorized": False,
            "formal_evaluator_launched": False,
            "contract_sha256": args.expected_contract_sha256,
            "validator_sha256": args.expected_validator_sha256,
        })
        if status == "PASS_INPUTS_READY_UNAUTHORIZED":
            return 0
        if completed.returncode != 0 or status != "WAITING_STRICT_V1_2_1_TERMINAL":
            return 1
        polls += 1
        if args.max_polls and polls >= args.max_polls:
            return 2
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
