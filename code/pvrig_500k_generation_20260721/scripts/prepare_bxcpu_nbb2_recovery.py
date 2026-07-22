#!/usr/bin/env python3
"""Prepare recoverable NBB2 refinement failures from an initial 8-node run."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


FIELDS = ["candidate_id", "sequence", "source_partial", "original_failure_reason", "original_node"]


def fasta_records(path: Path):
    name = None
    parts: list[str] = []
    for raw in path.read_text().splitlines():
        if raw.startswith(">"):
            if name is not None:
                yield name, "".join(parts)
            name = raw[1:].split()[0]
            parts = []
        else:
            parts.append(raw.strip())
    if name is not None:
        yield name, "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--initial-job-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    sequence_by_id: dict[str, str] = {}
    node_by_id: dict[str, str] = {}
    for fasta in sorted((args.campaign / "input").glob("task_*.fasta")):
        node = fasta.stem.split("_")[-1]
        for cid, seq in fasta_records(fasta):
            sequence_by_id[cid] = seq
            node_by_id[cid] = node

    results = args.campaign / f"results_{args.initial_job_id}"
    rows_by_node: dict[str, list[dict[str, str]]] = {f"{i:03d}": [] for i in range(8)}
    unrecoverable: list[dict[str, str]] = []
    technical = 0
    for manifest in sorted(results.glob("node_*/raw/worker_*/manifest.tsv")):
        with manifest.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["status"] == "SUCCESS":
                    continue
                technical += 1
                cid = row["candidate_id"]
                partial = manifest.parent / f"{cid}.pdb.partial"
                recoverable = (
                    "new_Context" in row["failure_reason"]
                    and partial.is_file()
                    and partial.stat().st_size > 10_000
                )
                if not recoverable:
                    unrecoverable.append(
                        {"candidate_id": cid, "failure_reason": row["failure_reason"]}
                    )
                    continue
                node = node_by_id[cid]
                rows_by_node[node].append(
                    {
                        "candidate_id": cid,
                        "sequence": sequence_by_id[cid],
                        "source_partial": str(partial.resolve()),
                        "original_failure_reason": row["failure_reason"],
                        "original_node": node,
                    }
                )

    args.output.mkdir(parents=True, exist_ok=True)
    recoverable_count = 0
    for node, rows in rows_by_node.items():
        path = args.output / f"task_{node}.tsv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        recoverable_count += len(rows)

    receipt = {
        "status": "PREPARED",
        "initial_job_id": args.initial_job_id,
        "technical_na": technical,
        "recoverable_openmm_threads_bug": recoverable_count,
        "unrecoverable": len(unrecoverable),
        "unrecoverable_sample": unrecoverable[:20],
        "shard_counts": {node: len(rows) for node, rows in rows_by_node.items()},
    }
    (args.output / "PREPARED.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
