#!/usr/bin/env python3
"""Nonlaunching watcher skeleton for the frozen V2.5 causal-ablation hardened V1.1 plan.

The terminal state is READY_NONLAUNCHING, never RUNNING.  This module has no
subprocess path and cannot start training, prediction, or evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Sequence


EXPECTED_LIVE_GRAPH_SHA = "ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185"


class WatcherError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise WatcherError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"json_object:{path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def verify_package(package: Path) -> dict[str, Any]:
    manifest = read_json(package / "PACKAGE_MANIFEST.json")
    require(manifest["status"] == "PASS_IMMUTABLE_NONLAUNCHING_PLAN_BUILT", "package_status")
    require(not manifest["launch_authorized"] and not manifest["training_or_prediction_executed"], "package_nonlaunch")
    require(manifest["upstream_live_job_graph_sha256"] == EXPECTED_LIVE_GRAPH_SHA, "package_graph_binding")
    for relative, expected in manifest["files"].items():
        path = package / relative
        require(path.is_file() and sha256(path) == expected, f"package_hash:{relative}")
    return manifest


def terminal_ready(runtime: Path) -> bool:
    terminal_path = runtime / "TERMINAL.json"
    final_path = runtime / "final" / "RESULT.json"
    if not terminal_path.exists() or not final_path.exists():
        return False
    terminal = read_json(terminal_path)
    require(terminal.get("status") == "PASS", "formal_terminal_status")
    require(terminal.get("completed") == 301 and terminal.get("returncode") == 0, "formal_terminal_count")
    require(terminal.get("job_graph_sha256") == EXPECTED_LIVE_GRAPH_SHA, "formal_terminal_graph")
    require(terminal.get("v4_f_test32_access_count") == 0, "formal_terminal_sealed_access")
    final = read_json(final_path)
    require(final.get("status") == "PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED", "formal_final_status")
    require(final.get("v4_f_test32_access_count") == 0, "formal_final_sealed_access")
    return True


def run(args: argparse.Namespace) -> dict[str, Any]:
    package = args.package_root.resolve()
    manifest = verify_package(package)
    waiting = {
        "status": "WAITING_FORMAL_V1_3_TERMINAL_NONLAUNCHING",
        "package_manifest_sha256": sha256(package / "PACKAGE_MANIFEST.json"),
        "contract_sha256": manifest["contract_sha256"],
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "live_301_job_graph_modified": False,
        "v4_f_test32_access_count": 0,
    }
    while not terminal_ready(args.runtime_root.resolve()):
        atomic_json(args.status_path, waiting)
        if args.once:
            return waiting
        time.sleep(args.poll_seconds)
    ready = dict(waiting)
    ready.update({
        "status": "READY_NONLAUNCHING_EXPLICIT_NEW_AUTHORIZATION_REQUIRED",
        "formal_terminal_sha256": sha256(args.runtime_root.resolve() / "TERMINAL.json"),
        "formal_final_sha256": sha256(args.runtime_root.resolve() / "final" / "RESULT.json"),
        "next_action": "Build and independently audit a future executable adapter version; this watcher must not launch it.",
    })
    atomic_json(args.status_path, ready)
    return ready


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--status-path", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args), sort_keys=True))
        return 0
    except (WatcherError, KeyError, OSError, ValueError) as exc:
        payload = {
            "status": "FAILED_CLOSED_NONLAUNCHING_WATCHER",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "launch_authorized": False,
            "training_or_prediction_executed": False,
            "live_301_job_graph_modified": False,
            "v4_f_test32_access_count": 0,
        }
        try:
            atomic_json(args.status_path, payload)
        except OSError:
            pass
        print(f"FAIL_CLOSED:{type(exc).__name__}:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

