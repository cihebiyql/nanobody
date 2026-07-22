#!/usr/bin/env python3
"""Audit deterministic NBB2-incompatible CPU candidates and stage reserves.

The observed incompatible family is an N-terminally truncated VHH parent that
passes the historical ANARCI status gate but is rejected by ImmuneBuilder's
full-domain sanity check.  This utility does not relabel those candidates as
biological negatives.  It removes them from final-library eligibility and
selects a route-matched, parent-balanced reserve for the same full prefilter.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path


AUDIT_FIELDS = [
    "candidate_id",
    "sequence",
    "sequence_sha256",
    "route_id",
    "parent_id",
    "parent_cluster",
    "generation_batch",
    "incompatibility_reason",
]


def open_text(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", newline="")
    return path.open(mode, newline="")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def stable_key(seed: int, row: dict[str, str]) -> str:
    payload = f"{seed}\0{row['candidate_id']}\0{row['sequence_sha256']}".encode()
    return hashlib.sha256(payload).hexdigest()


def incompatible(row: dict[str, str], bad_parent_cluster: str) -> bool:
    return (
        row.get("parent_cluster") == bad_parent_cluster
        and row.get("sequence", "").startswith("GGGS")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", type=Path, action="append", required=True)
    parser.add_argument("--reserve-pool", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bad-parent-cluster", default="C0532")
    parser.add_argument("--oversample-factor", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=20260722)
    args = parser.parse_args()
    if args.oversample_factor < 1:
        raise SystemExit("oversample factor must be at least one")

    selected_ids: set[str] = set()
    selected_sequences: set[str] = set()
    invalid_rows: list[dict[str, str]] = []
    invalid_counts: Counter[str] = Counter()
    selected_counts: Counter[str] = Counter()
    for source in args.selected:
        with open_text(source, "r") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                candidate_id, sequence = row["candidate_id"], row["sequence"]
                if candidate_id in selected_ids:
                    raise SystemExit(f"duplicate selected candidate_id: {candidate_id}")
                if sequence in selected_sequences:
                    raise SystemExit(f"duplicate selected sequence: {candidate_id}")
                selected_ids.add(candidate_id)
                selected_sequences.add(sequence)
                selected_counts[row["route_id"]] += 1
                if incompatible(row, args.bad_parent_cluster):
                    invalid_counts[row["route_id"]] += 1
                    invalid_rows.append(
                        {
                            key: row.get(key, "")
                            for key in AUDIT_FIELDS
                            if key != "incompatibility_reason"
                        }
                        | {
                            "incompatibility_reason": (
                                "NBB2_FULL_DOMAIN_SANITY_REJECTS_TRUNCATED_FR1;"
                                "TECHNICAL_NA_IS_NOT_BIOLOGICAL_NEGATIVE"
                            )
                        }
                    )

    targets = {
        route: math.ceil(count * args.oversample_factor)
        for route, count in invalid_counts.items()
    }
    grouped: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    pool_fields: list[str] | None = None
    pool_records = 0
    excluded_selected = 0
    excluded_bad_parent = 0
    with open_text(args.reserve_pool, "r") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        pool_fields = list(reader.fieldnames or [])
        for row in reader:
            pool_records += 1
            if row["candidate_id"] in selected_ids or row["sequence"] in selected_sequences:
                excluded_selected += 1
                continue
            if incompatible(row, args.bad_parent_cluster) or row.get("parent_cluster") == args.bad_parent_cluster:
                excluded_bad_parent += 1
                continue
            route = row["route_id"]
            if route not in targets:
                continue
            grouped[route][row.get("parent_cluster", "UNKNOWN")].append(row)

    reserve_rows: list[dict[str, str]] = []
    reserve_counts: Counter[str] = Counter()
    reserve_parent_counts: Counter[tuple[str, str]] = Counter()
    for route, target in sorted(targets.items()):
        queues: dict[str, deque[dict[str, str]]] = {}
        for parent, rows in grouped[route].items():
            rows.sort(key=lambda row: stable_key(args.seed, row))
            queues[parent] = deque(rows)
        parents = sorted(queues, key=lambda parent: hashlib.sha256(f"{args.seed}\0{route}\0{parent}".encode()).hexdigest())
        while reserve_counts[route] < target:
            progressed = False
            for parent in parents:
                queue = queues[parent]
                if not queue:
                    continue
                row = queue.popleft()
                reserve_rows.append(row)
                reserve_counts[route] += 1
                reserve_parent_counts[(route, parent)] += 1
                progressed = True
                if reserve_counts[route] == target:
                    break
            if not progressed:
                raise SystemExit(
                    f"insufficient reserve for {route}: {reserve_counts[route]} < {target}"
                )

    reserve_ids = [row["candidate_id"] for row in reserve_rows]
    reserve_sequences = [row["sequence"] for row in reserve_rows]
    if len(reserve_ids) != len(set(reserve_ids)):
        raise SystemExit("reserve candidate IDs are not unique")
    if len(reserve_sequences) != len(set(reserve_sequences)):
        raise SystemExit("reserve sequences are not unique")
    if set(reserve_ids) & selected_ids or set(reserve_sequences) & selected_sequences:
        raise SystemExit("reserve overlaps selected 700k set")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    invalid_path = args.output_dir / "cpu700k_nbb2_incompatible.tsv.gz"
    reserve_path = args.output_dir / "cpu700k_nbb2_replacement_reserve.tsv.gz"
    fasta_path = args.output_dir / "cpu700k_nbb2_replacement_reserve.fasta.gz"
    with open_text(invalid_path, "w") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(invalid_rows, key=lambda row: row["candidate_id"]))
    with open_text(reserve_path, "w") as handle:
        writer = csv.DictWriter(handle, fieldnames=pool_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(reserve_rows)
    with gzip.open(fasta_path, "wt") as handle:
        for row in reserve_rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    receipt = {
        "status": "READY_FOR_FULL_PREFILTER",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_records": sum(selected_counts.values()),
        "selected_route_counts": dict(sorted(selected_counts.items())),
        "bad_parent_cluster": args.bad_parent_cluster,
        "technical_na_is_not_biological_negative": True,
        "incompatible_records": len(invalid_rows),
        "incompatible_route_counts": dict(sorted(invalid_counts.items())),
        "oversample_factor": args.oversample_factor,
        "reserve_targets": dict(sorted(targets.items())),
        "reserve_records": len(reserve_rows),
        "reserve_route_counts": dict(sorted(reserve_counts.items())),
        "reserve_parent_cluster_counts": {
            route: len({parent for (item_route, parent) in reserve_parent_counts if item_route == route})
            for route in sorted(reserve_counts)
        },
        "reserve_max_per_parent": {
            route: max(count for (item_route, _), count in reserve_parent_counts.items() if item_route == route)
            for route in sorted(reserve_counts)
        },
        "reserve_pool_records": pool_records,
        "reserve_pool_excluded_selected": excluded_selected,
        "reserve_pool_excluded_bad_parent": excluded_bad_parent,
        "candidate_id_exact_unique": len(reserve_ids) == len(set(reserve_ids)),
        "sequence_exact_unique": len(reserve_sequences) == len(set(reserve_sequences)),
        "selected_overlap_records": 0,
        "outputs": {
            invalid_path.name: digest(invalid_path),
            reserve_path.name: digest(reserve_path),
            fasta_path.name: digest(fasta_path),
        },
    }
    receipt_path = args.output_dir / "READY.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
