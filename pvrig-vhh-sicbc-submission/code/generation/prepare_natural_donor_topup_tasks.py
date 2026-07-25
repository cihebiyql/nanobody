#!/usr/bin/env python3
"""Prepare combination-CDR natural-donor top-up tasks after global deduplication."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import random
import shutil
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("fullscale", HERE / "prepare_fullscale_cpu_tasks.py")
BASE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BASE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-campaign", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=60_000)
    parser.add_argument("--ordinal-offset", type=int, default=120_000)
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--workers-per-node", type=int, default=64)
    args = parser.parse_args()
    if args.count <= 0 or args.ordinal_offset < 0 or args.nodes <= 0 or args.workers_per_node <= 0:
        parser.error("count/nodes/workers must be positive and ordinal-offset must be non-negative")
    source = args.pilot_campaign.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(output)
    parents = BASE.parent_rows(BASE.read_tsv(source / "manifests" / "pilot_generation_tasks.tsv"))
    rows = BASE.build_route("natural_cdr_donor", args.count, parents)
    modes = BASE.labels(args.count, {"H1H2H3": 0.55, "H1H3": 0.45, "H3": 0.0}, 20260721)
    for index, (row, mode) in enumerate(zip(rows, modes), start=1):
        ordinal = args.ordinal_offset + index
        task_id = f"P500K__NATURAL_CDR_DONOR_TOPUP__{ordinal:07d}"
        row["task_id"] = task_id
        row["route_ordinal"] = ordinal
        row["generation_seed"] = int(BASE.sha256_text(task_id + "|natural_topup_v1")[:8], 16)
        row["design_mode"] = mode
        row["generation_batch"] = "natural_donor_combination_topup_v1"
    random.Random(20260721).shuffle(rows)
    shard_count = args.nodes * args.workers_per_node
    shards = [[] for _ in range(shard_count)]
    for index, row in enumerate(rows):
        shards[index % shard_count].append(row)
    fields = list(rows[0])
    for shard_index, shard in enumerate(shards):
        node = shard_index // args.workers_per_node
        worker = shard_index % args.workers_per_node
        BASE.write_tsv(output / "tasks" / f"node_{node:02d}" / f"worker_{worker:02d}.tsv", shard, fields)
    (output / "inputs").mkdir(parents=True)
    for name in ("known_positive_CDR_table.csv", "known_positive_antibodies.fasta", "top_200_vhh_scaffolds_for_design.csv"):
        shutil.copy2(source / "inputs" / name, output / "inputs" / name)
    summary = {
        "status": "READY_FOR_BXCPU_TOPUP",
        "route": "natural_cdr_donor",
        "generation_batch": "natural_donor_combination_topup_v1",
        "raw_task_count": len(rows),
        "design_mode_counts": dict(sorted(Counter(str(row["design_mode"]) for row in rows).items())),
        "ordinal_offset": args.ordinal_offset,
        "nodes": args.nodes,
        "workers_per_node": args.workers_per_node,
        "shard_count": shard_count,
        "min_shard_size": min(map(len, shards)),
        "max_shard_size": max(map(len, shards)),
        "reason": "Primary 120k natural-donor run yielded 82,607 exact-unique FAST-QC PASS sequences; H3-only donor space was saturated.",
    }
    (output / "PREPARED.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    files = sorted(path for path in output.rglob("*") if path.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(f"{BASE.sha256_file(path)}  {path.relative_to(output)}\n" for path in files),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
