#!/usr/bin/env python3
"""Purge only recomputed raw PDBs after exact-ID TNP aggregation succeeds."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--nbb2-job-id", required=True)
    parser.add_argument("--tnp-job-id", required=True)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--expected", type=int, required=True)
    args = parser.parse_args()

    ready_path = args.aggregate / "READY.json"
    ready = json.loads(ready_path.read_text())
    if ready.get("records") != args.expected or not ready.get("id_set_exact_match"):
        raise SystemExit(f"aggregate is not deletion-safe: {ready}")

    derived = [
        args.campaign / f"results_{args.nbb2_job_id}",
        args.campaign / f"tnp_results_{args.tnp_job_id}",
    ]
    removed = []
    for path in derived:
        if path.exists():
            size = tree_bytes(path)
            shutil.rmtree(path)
            removed.append({"path": str(path), "bytes": size})

    receipt = {
        "status": "PURGED_RECOMPUTED_RAW_AFTER_EXACT_ID_AGGREGATE",
        "expected_records": args.expected,
        "aggregate_ready": str(ready_path),
        "removed": removed,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (args.aggregate / "RAW_PURGE_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

