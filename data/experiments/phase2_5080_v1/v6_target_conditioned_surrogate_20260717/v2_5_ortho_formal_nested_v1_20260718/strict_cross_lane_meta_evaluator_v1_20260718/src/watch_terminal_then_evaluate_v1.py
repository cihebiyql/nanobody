#!/usr/bin/env python3
"""Wait for the unchanged V1.3 graph, then launch the frozen evaluator once."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence


EXPECTED_GRAPH_SHA = "ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185"
EXPECTED_CONTRACT_SHA = "0329a4749d9874f3bef7bda30d744d57b85b626783df9dc33a7fd931f3f75eb2"


class WatcherError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise WatcherError(message)


def sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"json_not_object:{path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)


def verify_package(package_root: Path) -> dict[str, Any]:
    manifest = read_json(package_root / "PACKAGE_MANIFEST.json")
    require(manifest["status"] == "FROZEN_NONLAUNCHING_PACKAGE", "package_status")
    require(manifest["contract_sha256"] == EXPECTED_CONTRACT_SHA, "package_contract_binding")
    for relative, expected in manifest["files"].items():
        path = package_root / relative
        require(path.is_file() and sha256(path) == expected, f"package_hash:{relative}")
    return manifest


def terminal_ready(runtime: Path) -> bool:
    terminal_path, final_path = runtime / "TERMINAL.json", runtime / "final" / "RESULT.json"
    if not terminal_path.exists() or not final_path.exists():
        return False
    terminal = read_json(terminal_path)
    if terminal.get("status") == "FAIL":
        raise WatcherError("upstream_terminal_failure:FAIL")
    require(terminal.get("status") == "PASS", "terminal_status")
    require(terminal.get("completed") == 301 and terminal.get("returncode") == 0, "terminal_job_count")
    require(terminal.get("job_graph_sha256") == EXPECTED_GRAPH_SHA, "terminal_graph_sha")
    require(terminal.get("v4_f_test32_access_count") == 0, "terminal_sealed_access")
    final = read_json(final_path)
    require(final.get("status") == "PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED", "terminal_final_status")
    require(final.get("v4_f_test32_access_count") == 0, "terminal_final_sealed_access")
    return True


def evaluator_command(args: argparse.Namespace) -> list[str]:
    package = args.package_root.resolve()
    inputs = package / "inputs"
    return [
        str(args.python), str(package / "src" / "evaluate_strict_cross_lane_meta_v1.py"),
        "--contract", str(inputs / "CROSS_LANE_NESTED_META_EVALUATION_CONTRACT_V1.json"),
        "--runtime-root", str(args.runtime_root.resolve()),
        "--labels", str(inputs / "v6_supervised1507_v2_4.tsv"),
        "--raw-features", str(inputs / "open1507_coarse_pose_features_36d.tsv"),
        "--outer-manifest", str(inputs / "outer_development_manifest.tsv"),
        "--inner-manifest", str(inputs / "inner_nested_oof_manifest.tsv"),
        "--c2-outer-oof", str(inputs / "open1507_double_crossfit_predictions.tsv"),
        "--c2-alpha-selection", str(inputs / "inner_c2_alpha_selection.tsv"),
        "--output-dir", str(args.output_dir.resolve()),
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = verify_package(args.package_root.resolve())
    require(not args.output_dir.exists(), "formal_output_already_exists")
    args.status_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.status_path, {"status": "WAITING_V1_3_TERMINAL", "package_manifest_sha256": sha256(args.package_root / "PACKAGE_MANIFEST.json"), "contract_sha256": EXPECTED_CONTRACT_SHA, "live_graph_modified": False, "v4_f_test32_access_count": 0})
    while not terminal_ready(args.runtime_root.resolve()):
        time.sleep(args.poll_seconds)
    command = evaluator_command(args)
    atomic_json(args.status_path, {"status": "RUNNING_FROZEN_EVALUATOR", "command": command, "package_manifest_sha256": sha256(args.package_root / "PACKAGE_MANIFEST.json"), "contract_sha256": EXPECTED_CONTRACT_SHA, "live_graph_modified": False, "v4_f_test32_access_count": 0})
    result = subprocess.run(command, text=True, capture_output=True)
    args.log_path.write_text(result.stdout + result.stderr)
    require(result.returncode == 0, f"evaluator_failed:{result.returncode}")
    receipt = read_json(args.output_dir / "FORMAL_EXECUTION_RECEIPT.json")
    require(receipt["status"] == "PASS_FORMAL_CROSS_LANE_META_EVALUATION_COMPLETED", "evaluator_receipt_status")
    require(receipt["contract_sha256"] == EXPECTED_CONTRACT_SHA, "evaluator_receipt_contract")
    payload = {"status": "PASS_FROZEN_EVALUATOR_TERMINAL", "output_dir": str(args.output_dir.resolve()), "formal_receipt_sha256": sha256(args.output_dir / "FORMAL_EXECUTION_RECEIPT.json"), "package_manifest_sha256": sha256(args.package_root / "PACKAGE_MANIFEST.json"), "contract_sha256": EXPECTED_CONTRACT_SHA, "live_graph_modified": False, "v4_f_test32_access_count": 0}
    atomic_json(args.status_path, payload)
    return payload


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--python", type=Path, required=True)
    value.add_argument("--package-root", type=Path, required=True)
    value.add_argument("--runtime-root", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--status-path", type=Path, required=True)
    value.add_argument("--log-path", type=Path, required=True)
    value.add_argument("--poll-seconds", type=float, default=60.0)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    print(json.dumps(run(args), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WatcherError, KeyError, OSError, ValueError) as exc:
        print(f"FAIL_CLOSED:{type(exc).__name__}:{exc}")
        raise SystemExit(2)
