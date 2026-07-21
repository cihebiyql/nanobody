#!/usr/bin/env python3
"""Materialize deterministic full-scale CPU-route tasks into 8x64 bxcpu shards."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path


ROUTE_RAW_TARGETS = {
    "conservative_cdr_redesign": 220_000,
    "natural_cdr_donor": 120_000,
}
PATCH_WEIGHTS = {"C_CROSS": 0.40, "B_LOWER": 0.35, "A_CENTER": 0.25}
MODE_WEIGHTS = {"H1H2H3": 0.45, "H1H3": 0.35, "H3": 0.20}
LENGTH_WEIGHTS = {"18_22": 0.70, "16_17": 0.20, "10_15": 0.10}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def labels(total: int, weights: dict[str, float], seed: int) -> list[str]:
    counts = {key: math.floor(total * value) for key, value in weights.items()}
    for key in list(weights)[: total - sum(counts.values())]:
        counts[key] += 1
    result = [key for key, count in counts.items() for _ in range(count)]
    random.Random(seed).shuffle(result)
    return result


def cdr3_bin(length: int) -> str:
    if 18 <= length <= 22:
        return "18_22"
    if 16 <= length <= 17:
        return "16_17"
    if 10 <= length <= 15:
        return "10_15"
    return "other"


def parent_rows(pilot_tasks: list[dict[str, str]]) -> list[dict[str, str]]:
    by_parent: dict[str, dict[str, str]] = {}
    for row in pilot_tasks:
        by_parent.setdefault(
            row["parent_id"],
            {
                "parent_id": row["parent_id"],
                "parent_cluster": row["parent_cluster"],
                "parent_is_current_v29": row["parent_is_current_v29"],
                "parent_sequence": row["parent_sequence"],
                "parent_sequence_sha256": row["parent_sequence_sha256"],
                "parent_cdr1": row["parent_cdr1"],
                "parent_cdr2": row["parent_cdr2"],
                "parent_cdr3": row["parent_cdr3"],
                "parent_cdr3_len": row["parent_cdr3_len"],
            },
        )
    return sorted(by_parent.values(), key=lambda row: row["parent_id"])


def build_route(route: str, total: int, parents: list[dict[str, str]]) -> list[dict[str, object]]:
    patches = labels(total, PATCH_WEIGHTS, 917 + total)
    modes = labels(total, MODE_WEIGHTS, 1931 + total)
    bins = labels(total, LENGTH_WEIGHTS, 3253 + total)
    by_bin: dict[str, list[dict[str, str]]] = defaultdict(list)
    for parent in parents:
        by_bin[cdr3_bin(int(parent["parent_cdr3_len"]))].append(parent)
    if any(not by_bin[key] for key in LENGTH_WEIGHTS):
        raise ValueError("parent panel lacks a requested CDR3 length bin")
    cursors: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    for index in range(total):
        bucket = bins[index]
        pool = by_bin[bucket]
        parent = pool[cursors[bucket] % len(pool)]
        cursors[bucket] += 1
        task_id = f"P500K__{route.upper()}__{index + 1:07d}"
        rows.append(
            {
                "task_id": task_id,
                "route_id": route,
                "route_ordinal": index + 1,
                "generation_seed": int(sha256_text(task_id + "|20260721")[:8], 16),
                "implementation_status": "BXCPU_CPU_READY",
                "target_patch_assignment": patches[index],
                "patch_conditioned_generation": "false",
                "design_mode": modes[index],
                "requested_cdr3_length_bin": bucket,
                **parent,
                "status": "PENDING",
            }
        )
    return rows


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-campaign", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--workers-per-node", type=int, default=64)
    args = parser.parse_args()
    if args.nodes <= 0 or args.workers_per_node <= 0:
        parser.error("--nodes and --workers-per-node must be positive")
    source = args.pilot_campaign.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(output)
    pilot_tasks = read_tsv(source / "manifests" / "pilot_generation_tasks.tsv")
    parents = parent_rows(pilot_tasks)
    if len(parents) != 180:
        raise ValueError(f"expected 180 frozen parents, found {len(parents)}")
    rows: list[dict[str, object]] = []
    for route, total in ROUTE_RAW_TARGETS.items():
        rows.extend(build_route(route, total, parents))
    shard_count = args.nodes * args.workers_per_node
    shards: list[list[dict[str, object]]] = [[] for _ in range(shard_count)]
    for index, row in enumerate(rows):
        shards[index % shard_count].append(row)
    fields = list(rows[0])
    for shard_index, shard in enumerate(shards):
        node = shard_index // args.workers_per_node
        worker = shard_index % args.workers_per_node
        write_tsv(output / "tasks" / f"node_{node:02d}" / f"worker_{worker:02d}.tsv", shard, fields)
    (output / "inputs").mkdir(parents=True)
    for name in ("known_positive_CDR_table.csv", "known_positive_antibodies.fasta", "top_200_vhh_scaffolds_for_design.csv"):
        shutil.copy2(source / "inputs" / name, output / "inputs" / name)
    summary = {
        "status": "READY_FOR_BXCPU",
        "raw_task_count": len(rows),
        "route_counts": dict(sorted(Counter(str(row["route_id"]) for row in rows).items())),
        "nodes": args.nodes,
        "workers_per_node": args.workers_per_node,
        "shard_count": shard_count,
        "min_shard_size": min(map(len, shards)),
        "max_shard_size": max(map(len, shards)),
        "parent_count": len(parents),
    }
    (output / "PREPARED.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    files = sorted(path for path in output.rglob("*") if path.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(output)}\n" for path in files),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
