#!/usr/bin/env python3
"""Bind an adopted tmux session to the exact V2 Stage-A entry command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(value: dict, entrypoint: str, runtime: str, package: str, evidence: str, freeze_name: str, freeze_sha: str) -> int:
    if value.get("session") is not True:
        raise RuntimeError("session_not_active")
    observed = value.get("session_command")
    expected_by_gpu = {
        gpu: f'"/bin/bash \'{entrypoint}\' \'{runtime}\' \'{package}\' \'{evidence}\' \'{freeze_name}\' \'{freeze_sha}\' \'{gpu}\'"'
        for gpu in range(1, 8)
    }
    matches = [gpu for gpu, expected in expected_by_gpu.items() if observed == expected]
    if len(matches) != 1:
        raise RuntimeError(f"session_command_mismatch:{observed!r}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--freeze-name", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args()
    gpu = validate(
        json.loads(args.snapshot.read_text()), args.entrypoint, args.runtime,
        args.package, args.evidence, args.freeze_name, args.freeze_sha256,
    )
    print(json.dumps({
        "status": "PASS_EXACT_NODE1_STAGE_A_TMUX_SESSION_COMMAND",
        "physical_gpu": gpu,
        "training_authorized": False,
        "training_started": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
