#!/usr/bin/env python3
"""Relay the 424 supplemental Docking results from bxcpu to Node1."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


BASE = (
    Path(__file__).resolve().parents[2]
    / "bxcpu_c2_new6220_dualseed_v1_20260723"
)
SOURCE = BASE / "sync_c2_new6220_results_incremental.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("pvrig_bounded_sync_base", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bounded sync implementation: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CAMPAIGNS = {
        "top200_seed_completion": {
            "expected": 424,
            "remote": (
                "pvrig_top200_common4_seed_completion106_handoff_v1_20260725"
                "_bxcpu_results"
            ),
        }
    }
    return int(module.main())


if __name__ == "__main__":
    os.environ.setdefault(
        "PVRIG_BXCPU_SYNC_NODE1_ROOT",
        "/data1/qlyu/projects/"
        "pvrig_top200_common4_seed_completion106_docking_results_v1_20260725",
    )
    raise SystemExit(main())
