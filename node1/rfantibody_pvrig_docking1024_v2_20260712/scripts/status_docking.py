#!/usr/bin/env python3
"""Summarize NBB2/HADDOCK docking progress from manifests and atomic state files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

STATES = ("success", "failed", "missing", "running", "pending", "dry_run")


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def status_for(path: Path) -> str:
    status = str(read_json(path).get("status") or "pending")
    return status if status in STATES else "pending"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    docking_root = run_root / "docking"
    manifest = args.manifest or docking_root / "manifests" / "docking_candidates.tsv"
    rows = read_manifest(manifest) if manifest.is_file() else []
    candidate_ids = [row["candidate_id"] for row in rows]
    per_candidate = []
    nbb2_counts: Counter[str] = Counter()
    haddock_counts: Counter[str] = Counter()
    for cid in candidate_ids:
        nbb2 = status_for(docking_root / "state" / "nbb2" / f"{cid}.json")
        haddock = status_for(docking_root / "state" / "haddock" / f"{cid}.json")
        nbb2_counts[nbb2] += 1
        haddock_counts[haddock] += 1
        row = {
            "candidate_id": cid,
            "nbb2_status": nbb2,
            "haddock_status": haddock,
            "monomer_present": (docking_root / "haddock" / cid / "data" / f"{cid}_vhh_chainA.pdb").is_file(),
            "restraint_present": bool(list((docking_root / "haddock" / cid / "data").glob("*_ambig.tbl"))),
            "cfg_present": bool(list((docking_root / "haddock" / cid).glob("*.cfg"))),
        }
        per_candidate.append(row)
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(run_root),
        "manifest": str(manifest),
        "candidate_count": len(candidate_ids),
        "nbb2_counts": {state: nbb2_counts.get(state, 0) for state in STATES},
        "haddock_counts": {state: haddock_counts.get(state, 0) for state in STATES},
        "missingness": {
            "monomer_missing": sum(not row["monomer_present"] for row in per_candidate),
            "restraint_missing": sum(not row["restraint_present"] for row in per_candidate),
            "cfg_missing": sum(not row["cfg_present"] for row in per_candidate),
        },
        "candidates": per_candidate,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"candidate_count={payload['candidate_count']}")
        print(f"nbb2_counts={json.dumps(payload['nbb2_counts'], sort_keys=True)}")
        print(f"haddock_counts={json.dumps(payload['haddock_counts'], sort_keys=True)}")
        print(f"missingness={json.dumps(payload['missingness'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
