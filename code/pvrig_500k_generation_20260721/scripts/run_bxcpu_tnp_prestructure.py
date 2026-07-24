#!/usr/bin/env python3
"""Parallel TNP scoring for one bxcpu NanoBodyBuilder2 shard."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import multiprocessing as mp
import os
from pathlib import Path
import time
from typing import Any

from tnp_score_precomputed_pdb import score_precomputed_pdb


FIELDS = [
    "candidate_id",
    "status",
    "failure_reason",
    "pdb_path",
    "total_cdr_length",
    "cdr3_length",
    "cdr3_compactness",
    "psh",
    "ppc",
    "pnc",
    "flag_L",
    "flag_L3",
    "flag_C",
    "flag_PSH",
    "flag_PPC",
    "flag_PNC",
    "red_flag_count",
    "amber_flag_count",
    "metric_semantics",
]


def read_fasta_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open() as handle:
        for line in handle:
            if line.startswith(">"):
                ids.append(line[1:].strip().split()[0])
    return ids


def load_selection(path: Path, wanted: set[str]) -> dict[str, dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: dict[str, dict[str, str]] = {}
    with opener(path, "rt", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            cid = row["candidate_id"]
            if cid in wanted:
                rows[cid] = row
    return rows


def build_pdb_map(roots: list[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in roots:
        for path in root.rglob("*.pdb"):
            result[path.stem] = path
    return result


def resolve_cdr(row: dict[str, str], number: int) -> str:
    """Return a CDR sequence across legacy ANARCI and current IMGT column names."""
    aliases = (
        f"anarci_cdr{number}",
        f"IMGT_CDR{number}",
        f"imgt_cdr{number}",
        f"CDR{number}",
        f"cdr{number}",
    )
    for key in aliases:
        value = row.get(key, "").strip()
        if value:
            return value
    raise KeyError(f"missing CDR{number}; checked {', '.join(aliases)}")


def run_one(task: tuple[str, dict[str, str], str | None]) -> dict[str, Any]:
    candidate_id, row, pdb_string = task
    if pdb_string is None:
        return {
            "candidate_id": candidate_id,
            "status": "TECHNICAL_NA",
            "failure_reason": "missing_precomputed_pdb",
            "pdb_path": "",
            "metric_semantics": "TNP structure developability proxy; not measured expression or purity",
        }
    try:
        return score_precomputed_pdb(
            candidate_id=candidate_id,
            pdb_path=Path(pdb_string),
            cdr1=resolve_cdr(row, 1),
            cdr2=resolve_cdr(row, 2),
            cdr3=resolve_cdr(row, 3),
            h_scale=0,
        )
    except Exception as exc:
        return {
            "candidate_id": candidate_id,
            "status": "TECHNICAL_NA",
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "pdb_path": pdb_string,
            "metric_semantics": "TNP structure developability proxy; not measured expression or purity",
        }


def flatten(result: dict[str, Any]) -> dict[str, Any]:
    row = {key: result.get(key, "") for key in FIELDS}
    flags = result.get("flags", {})
    for name in ("L", "L3", "C", "PSH", "PPC", "PNC"):
        row[f"flag_{name}"] = flags.get(name, "")
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fasta", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--pdb-root", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=64)
    args = parser.parse_args()

    started = time.time()
    candidate_ids = read_fasta_ids(args.fasta)
    selected = load_selection(args.selection, set(candidate_ids))
    pdbs = build_pdb_map(args.pdb_root)
    if set(candidate_ids) != set(selected):
        missing = sorted(set(candidate_ids) - set(selected))[:10]
        raise SystemExit(f"selection rows missing for {len(set(candidate_ids)-set(selected))}: {missing}")

    tasks = [(cid, selected[cid], str(pdbs[cid]) if cid in pdbs else None) for cid in candidate_ids]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = {"PASS": 0, "TECHNICAL_NA": 0}
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        with mp.Pool(args.workers) as pool:
            for result in pool.imap_unordered(run_one, tasks, chunksize=4):
                writer.writerow(flatten(result))
                counts[result["status"]] = counts.get(result["status"], 0) + 1

    receipt = {
        "status": "PASS" if counts.get("PASS", 0) == len(candidate_ids) else "COMPLETE_WITH_TECHNICAL_NA",
        "records": len(candidate_ids),
        "counts": counts,
        "workers": args.workers,
        "elapsed_seconds": time.time() - started,
        "output": str(args.output.resolve()),
        "metric_semantics": "TNP structure developability proxy; not measured expression or purity",
    }
    args.output.with_suffix(args.output.suffix + ".receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
