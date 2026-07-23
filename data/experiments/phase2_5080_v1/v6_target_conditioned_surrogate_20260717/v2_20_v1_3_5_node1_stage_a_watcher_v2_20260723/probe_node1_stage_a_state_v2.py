#!/usr/bin/env python3
"""Emit a read-only, machine-classifiable snapshot of the remote Stage-A paths."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
from pathlib import Path


def kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "absent"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def stable_text(path: Path) -> str | None:
    if kind(path) != "file":
        return None
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after):
        return None
    try:
        return raw.decode("ascii", "strict").strip()
    except UnicodeDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--ready-archive", type=Path, required=True)
    parser.add_argument("--partial-archive", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    rc_path = args.evidence / "PREFLIGHT_LAUNCHER.rc"
    session = subprocess.run(
        ["tmux", "has-session", "-t", args.session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    session_command = None
    if session:
        command = subprocess.run(
            ["tmux", "list-panes", "-t", args.session, "-F", "#{pane_start_command}"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        if len(command) == 1:
            session_command = command[0]
    payload = {
        "schema_version": "pvrig.v220.v1_3_5.node1_stage_a_remote_snapshot.v2",
        "package": kind(args.package),
        "stage": kind(args.stage),
        "ready_archive": kind(args.ready_archive),
        "partial_archive": kind(args.partial_archive),
        "runtime": kind(args.runtime),
        "evidence": kind(args.evidence),
        "rc": kind(rc_path),
        "rc_value": stable_text(rc_path),
        "session": session,
        "session_command": session_command,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
