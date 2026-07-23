#!/usr/bin/env python3
"""Fail-closed state classifier for resumable Node1 Stage-A deployment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class StateError(RuntimeError):
    pass


def classify(value: dict[str, Any]) -> str:
    allowed = {
        "package": {"absent", "directory"},
        "stage": {"absent", "directory"},
        "ready_archive": {"absent", "file"},
        "partial_archive": {"absent", "file"},
        "runtime": {"absent", "directory"},
        "evidence": {"absent", "directory"},
        "rc": {"absent", "file"},
    }
    for key, accepted in allowed.items():
        if value.get(key) not in accepted:
            return f"AMBIGUOUS_INVALID_TYPE_{key.upper()}"
    package = value["package"] == "directory"
    stage = value["stage"] == "directory"
    ready = value["ready_archive"] == "file"
    runtime = value["runtime"] == "directory"
    evidence = value["evidence"] == "directory"
    rc = value["rc"] == "file"
    session = value.get("session") is True
    rc_value = value.get("rc_value")

    if package and stage:
        return "AMBIGUOUS_FINAL_AND_STAGE"
    if not package:
        if runtime or evidence or rc or session:
            return "AMBIGUOUS_EXECUTION_WITHOUT_PACKAGE"
        if stage:
            return "STAGED_PACKAGE"
        if ready:
            return "ARCHIVE_READY"
        return "CLEAN"

    # A known ready archive may remain after the atomic stage->final rename.
    if session:
        return "RUNNING"
    if rc:
        if not evidence:
            return "AMBIGUOUS_RC_WITHOUT_EVIDENCE"
        try:
            parsed_rc = int(str(rc_value))
        except (TypeError, ValueError):
            return "AMBIGUOUS_INVALID_RC"
        if parsed_rc == 0 and not runtime:
            return "AMBIGUOUS_SUCCESS_WITHOUT_RUNTIME"
        return "TERMINAL"
    if runtime or evidence:
        return "AMBIGUOUS_PARTIAL_EXECUTION_NO_RC"
    return "READY"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.snapshot.read_text())
    result = classify(value)
    print(result)
    return 0 if not result.startswith("AMBIGUOUS") else 65


if __name__ == "__main__":
    raise SystemExit(main())
