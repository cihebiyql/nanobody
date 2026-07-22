#!/usr/bin/env python3
"""Prepare the CPU-route top-up used to expand the frozen PVRIG library to 1M.

The 1M target doubles the original method allocation while preserving the
already frozen 394,295 CPU candidates.  This script intentionally creates a
raw oversupply; global exact-sequence deduplication and route-aware freezing
happen after generation.
"""

from __future__ import annotations

import argparse
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


DEFAULT_RAW_COUNTS = {
    "conservative_cdr_redesign": 260_000,
    "natural_cdr_donor": 120_000,
    "profile_diversified_exploration_control": 50_000,
}

EXISTING_FROZEN_COUNTS = {
    "conservative_cdr_redesign": 204_265,
    "natural_cdr_donor": 129_079,
    "profile_diversified_exploration_control": 60_951,
}

TARGET_1M_ROUTE_TOTALS = {
    "conservative_cdr_redesign": 400_000,
    "natural_cdr_donor": 200_000,
    "profile_diversified_exploration_control": 100_000,
    "epitope_conditioned_rfantibody": 150_000,
    "fixed_pose_mpnn_antifold": 150_000,
}


def make_route(route: str, count: int, parents: list[dict[str, str]]) -> list[dict[str, object]]:
    base_route = "conservative_cdr_redesign" if route == "profile_diversified_exploration_control" else route
    rows = BASE.build_route(base_route, count, parents)
    if route == "profile_diversified_exploration_control":
        modes = BASE.labels(count, {"H3": 0.40, "H1H3": 0.35, "H1H2H3": 0.25}, 1_000_022)
    elif route == "natural_cdr_donor":
        modes = BASE.labels(count, {"H1H2H3": 0.55, "H1H3": 0.45, "H3": 0.0}, 1_000_021)
    else:
        modes = [str(row["design_mode"]) for row in rows]
    route_token = route.upper()
    for index, (row, mode) in enumerate(zip(rows, modes), start=1):
        task_id = f"P1M__{route_token}__TOPUP__{index:07d}"
        row["task_id"] = task_id
        row["route_id"] = route
        row["route_ordinal"] = index
        row["generation_seed"] = int(BASE.sha256_text(task_id + "|pvrig_1m_topup_v1")[:8], 16)
        row["implementation_status"] = "BXCPU_CPU_1M_TOPUP_READY"
        row["design_mode"] = mode
        row["generation_batch"] = "pvrig_1m_cpu_topup_v1_20260722"
        row["existing_frozen_route_count"] = EXISTING_FROZEN_COUNTS[route]
        row["target_1m_route_total"] = TARGET_1M_ROUTE_TOTALS[route]
        row["requested_new_route_quota"] = (
            TARGET_1M_ROUTE_TOTALS[route] - EXISTING_FROZEN_COUNTS[route]
        )
    random.Random(1_000_000 + len(route)).shuffle(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-campaign", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--conservative-count", type=int, default=DEFAULT_RAW_COUNTS["conservative_cdr_redesign"])
    parser.add_argument("--natural-count", type=int, default=DEFAULT_RAW_COUNTS["natural_cdr_donor"])
    parser.add_argument("--exploration-count", type=int, default=DEFAULT_RAW_COUNTS["profile_diversified_exploration_control"])
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--workers-per-node", type=int, default=64)
    args = parser.parse_args()
    counts = {
        "conservative_cdr_redesign": args.conservative_count,
        "natural_cdr_donor": args.natural_count,
        "profile_diversified_exploration_control": args.exploration_count,
    }
    if any(value <= 0 for value in (*counts.values(), args.nodes, args.workers_per_node)):
        parser.error("all counts, nodes, and workers-per-node must be positive")

    source = args.pilot_campaign.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(output)
    parents = BASE.parent_rows(BASE.read_tsv(source / "manifests" / "pilot_generation_tasks.tsv"))
    if len(parents) != 180:
        raise ValueError(f"expected 180 frozen parents, found {len(parents)}")

    rows: list[dict[str, object]] = []
    for route, count in counts.items():
        rows.extend(make_route(route, count, parents))
    random.Random(1_000_000).shuffle(rows)
    shard_count = args.nodes * args.workers_per_node
    shards: list[list[dict[str, object]]] = [[] for _ in range(shard_count)]
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
        "status": "READY_FOR_BXCPU_1M_CPU_TOPUP",
        "campaign": "pvrig_1m_cpu_topup_v1_20260722",
        "raw_task_count": len(rows),
        "raw_route_counts": dict(sorted(Counter(str(row["route_id"]) for row in rows).items())),
        "existing_frozen_cpu_records": sum(EXISTING_FROZEN_COUNTS.values()),
        "existing_frozen_route_counts": EXISTING_FROZEN_COUNTS,
        "target_1m_route_totals": TARGET_1M_ROUTE_TOTALS,
        "requested_new_cpu_route_quotas": {
            route: TARGET_1M_ROUTE_TOTALS[route] - existing
            for route, existing in EXISTING_FROZEN_COUNTS.items()
        },
        "nodes": args.nodes,
        "workers_per_node": args.workers_per_node,
        "shard_count": shard_count,
        "min_shard_size": min(map(len, shards)),
        "max_shard_size": max(map(len, shards)),
        "parent_count": len(parents),
        "scientific_boundary": "Sequence generation and fast QC only; not binding, affinity, expression, purity, docking, or blocking evidence.",
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
