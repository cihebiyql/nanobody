#!/usr/bin/env python3
"""Run the proven bounded relay for the 4,220-candidate seed42/3047 campaign."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


BASE = Path(__file__).resolve().parents[1] / "bxcpu_c2_new6220_dualseed_v1_20260723"
SOURCE = BASE / "sync_c2_new6220_results_incremental.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("pvrig_bounded_sync_base", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bounded sync implementation: {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CAMPAIGNS = {
        "c2_new4220_seed42_3047": {
            "expected": 16880,
            "remote": "pvrig_c2_new4220_seed42_3047_v1_20260723_bxcpu_results",
        }
    }
    return int(module.main())


if __name__ == "__main__":
    os.environ.setdefault(
        "PVRIG_BXCPU_SYNC_NODE1_ROOT",
        "/data1/qlyu/projects/pvrig_c2_new4220_seed42_3047_docking_results_v1_20260723",
    )
    raise SystemExit(main())
