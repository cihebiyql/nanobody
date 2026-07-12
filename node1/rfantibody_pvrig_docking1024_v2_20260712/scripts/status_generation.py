#!/usr/bin/env python3
"""Summarize generation progress without trusting PID files alone."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=Path("/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712"))
    parser.add_argument("--arms-path", type=Path)
    args = parser.parse_args()
    marker = args.run_root / "status" / "active_generation_arm_table.txt"
    if args.arms_path is not None:
        arms_path = args.arms_path
    elif marker.is_file():
        arms_path = Path(marker.read_text(encoding="utf-8").strip())
    else:
        arms_path = args.run_root / "config" / "generation_arms.tsv"
    if not arms_path.is_absolute():
        arms_path = args.run_root / arms_path
    with arms_path.open(newline="", encoding="utf-8") as handle:
        arms = list(csv.DictReader(handle, delimiter="\t"))
    rows = []
    for arm in arms:
        root = args.run_root / "generation" / "arms" / arm["arm_id"]
        state = "pending"
        status_path = root / "status" / "status.json"
        if status_path.is_file():
            state = json.loads(status_path.read_text()).get("state", "unknown")
        if (root / "complete.json").is_file():
            state = "complete"
        rows.append(
            {
                "arm_id": arm["arm_id"],
                "gpu_id": int(arm["gpu_id"]),
                "state": state,
                "backbones": len(list((root / "backbones").glob("design_*.pdb"))),
                "trb": len(list((root / "backbones").glob("design_*.trb"))),
                "sequences": len(list((root / "sequences").glob("design_*_dldesign_*.pdb"))),
            }
        )
    payload = {
        "arm_table_path": str(arms_path),
        "arm_table_sha256": hashlib.sha256(arms_path.read_bytes()).hexdigest(),
        "arm_count": len(rows),
        "state_counts": dict(sorted(Counter(row["state"] for row in rows).items())),
        "backbone_pdb_count": sum(row["backbones"] for row in rows),
        "backbone_trb_count": sum(row["trb"] for row in rows),
        "sequence_pdb_count": sum(row["sequences"] for row in rows),
        "expected_backbones": sum(int(row["target_backbones"]) for row in arms),
        "expected_sequences": sum(int(row["target_backbones"]) * int(row["seqs_per_backbone"]) for row in arms),
        "arms": rows,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
