#!/usr/bin/env python3
"""Patch the ImmuneBuilder 1.2 OpenMM Threads property set/dict typo.

ImmuneBuilder 1.2 passes ``{'Threads', str(n_threads)}`` in the strained
side-chain recovery path.  OpenMM expects a mapping, and the set triggers a
SWIG ``new_Context`` TypeError for otherwise valid predictions.  The patch is
exact-match guarded and idempotent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time


OLD = "simulation = app.Simulation(modeller.topology, system, integrator, platform, {'Threads', str(n_threads)})"
NEW = "simulation = app.Simulation(modeller.topology, system, integrator, platform, {'Threads': str(n_threads)})"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("refine_py", type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    source = args.refine_py.read_text()
    before = digest(args.refine_py)
    if NEW in source and OLD not in source:
        status = "ALREADY_PATCHED"
    elif source.count(OLD) == 1:
        backup = args.refine_py.with_suffix(args.refine_py.suffix + ".pre_pvrig_patch")
        if not backup.exists():
            shutil.copy2(args.refine_py, backup)
        args.refine_py.write_text(source.replace(OLD, NEW))
        status = "PATCHED"
    else:
        raise SystemExit("expected exactly one ImmuneBuilder 1.2 Threads set typo")

    payload = {
        "status": status,
        "file": str(args.refine_py.resolve()),
        "sha256_before": before,
        "sha256_after": digest(args.refine_py),
        "old": OLD,
        "new": NEW,
        "reason": "OpenMM platform properties require a dict; a set raises new_Context TypeError",
        "created_epoch": time.time(),
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
