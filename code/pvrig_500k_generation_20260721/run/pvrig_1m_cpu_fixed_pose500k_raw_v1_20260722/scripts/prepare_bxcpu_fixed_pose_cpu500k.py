#!/usr/bin/env python3
"""Prepare 8x64 balanced fixed-pose ProteinMPNN CPU tasks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


TEMPERATURES = (0.15, 0.20, 0.20, 0.30)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose-table", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--raw-target", type=int, default=480_000)
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--workers-per-node", type=int, default=64)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    poses = read_tsv(args.pose_table)
    if not poses:
        raise ValueError("pose table is empty")
    tasks = args.nodes * args.workers_per_node
    base, remainder = divmod(args.raw_target, tasks)
    rows: list[dict[str, object]] = []
    for index in range(tasks):
        pose = poses[index % len(poses)]
        task_id = f"CPUFP500K_{index + 1:04d}"
        rows.append(
            {
                "task_id": task_id,
                "node_index": index // args.workers_per_node,
                "worker_index": index % args.workers_per_node,
                "sequence_count": base + (index < remainder),
                "generation_seed": int(hashlib.sha256((task_id + "|20260722").encode()).hexdigest()[:8], 16),
                "temperature": TEMPERATURES[index % len(TEMPERATURES)],
                "target_patch": "PVRIG_BLOCKING_INTERFACE_FIXED_POSE",
                "loop_string": "H1,H2,H3",
                **{key: pose[key] for key in (
                    "pose_id", "source_candidate_id", "source_molecule_name", "source_pose_rank",
                    "normalized_pose_relpath", "normalized_pose_sha256",
                )},
            }
        )
    for row in rows:
        node = int(row["node_index"])
        worker = int(row["worker_index"])
        write_tsv(args.output_dir / "tasks" / f"node_{node:02d}" / f"worker_{worker:02d}.tsv", [row])
    summary = {
        "status": "READY_FOR_BXCPU_SMOKE_THEN_FULL",
        "raw_target": args.raw_target,
        "tasks": len(rows),
        "nodes": args.nodes,
        "workers_per_node": args.workers_per_node,
        "pose_count": len(poses),
        "source_count": len({row["source_candidate_id"] for row in rows}),
        "temperature_counts": dict(sorted(Counter(str(row["temperature"]) for row in rows).items())),
        "design_mode": "H1,H2,H3",
        "storage_policy": "sequence_tsv_gz_only_no_threaded_pdb",
        "scientific_boundary": "fixed-pose target-conditioned proposal generation; not binding, docking, affinity, or blocking evidence",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "PREPARED.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
