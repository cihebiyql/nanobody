#!/usr/bin/env python3
"""Detached launcher for the terminal-waiting formal autostart watcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--watcher", required=True)
    parser.add_argument("--expected-watcher-sha256", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("watcher_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    freeze = Path(args.freeze).resolve(); watcher = Path(args.watcher).resolve()
    if sha256_file(freeze) != args.expected_freeze_sha256:
        raise RuntimeError("freeze_hash_mismatch")
    if sha256_file(watcher) != args.expected_watcher_sha256:
        raise RuntimeError("watcher_hash_mismatch")
    token = os.environ.get("PVRIG_V2_5_AUTH_TOKEN", "")
    intent = json.loads((Path(args.package_root) / "EXPLICIT_AUTHORIZATION_INTENT_V1.json").read_text())
    if hashlib.sha256(token.encode()).hexdigest() != intent["authorization_token_sha256"]:
        raise RuntimeError("runtime_authorization_token_hash_mismatch")
    output = Path(args.output_root).resolve(); output.mkdir(parents=True, exist_ok=True)
    receipt = output / "AUTOSTART_DEPLOYMENT_RECEIPT.json"
    if receipt.exists():
        raise RuntimeError("autostart_deployment_receipt_exists")
    watcher_args = list(args.watcher_args)
    if watcher_args[:1] == ["--"]:
        watcher_args = watcher_args[1:]
    command = [
        str(Path(args.python).resolve()), str(watcher),
        "--package-root", str(Path(args.package_root).resolve()),
        "--freeze", str(freeze),
        "--expected-freeze-sha256", args.expected_freeze_sha256,
        "--output-root", str(output),
        *watcher_args,
    ]
    log_path = output / "AUTOSTART_WATCHER.log"
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env=dict(os.environ), start_new_session=True, close_fds=True,
        )
    write_json(receipt, {
        "schema_version": "pvrig_v2_5_formal_autostart_deployment_receipt_v1",
        "status": "PASS_TERMINAL_WAITING_WATCHER_LAUNCHED",
        "pid": process.pid,
        "command": command,
        "freeze_sha256": args.expected_freeze_sha256,
        "watcher_sha256": args.expected_watcher_sha256,
        "runtime_token_persisted": False,
        "watcher_must_wait_for_evaluator_terminal": True,
        "v4_f_test32_access_count": 0,
    })
    print(json.dumps({"status": "PASS_TERMINAL_WAITING_WATCHER_LAUNCHED", "pid": process.pid}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
