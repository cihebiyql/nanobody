#!/usr/bin/env python3
"""Map exact 80%-identity connected CDR3 families back to all candidates."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anarci", type=Path, required=True)
    parser.add_argument("--family-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    component_members: dict[tuple[int, str], list[str]] = defaultdict(list)
    cdr3_component: dict[str, tuple[int, str]] = {}
    result_paths = sorted(args.family_results.glob("task_*.tsv"))
    if len(result_paths) != 8:
        raise ValueError(f"expected 8 result shards, found {len(result_paths)}")
    for path in result_paths:
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                cdr3 = row["cdr3"]
                key = (len(cdr3), row["component_key"])
                if cdr3 in cdr3_component:
                    raise ValueError(f"duplicate CDR3 result: {cdr3}")
                cdr3_component[cdr3] = key
                component_members[key].append(cdr3)

    family_for_component = {}
    unique_size = {}
    for key, members in component_members.items():
        digest = hashlib.sha256("\n".join(sorted(members)).encode()).hexdigest()[:16]
        family_for_component[key] = f"CDR3F80_{key[0]:02d}_{digest}"
        unique_size[key] = len(members)

    rows = []
    candidate_counts: Counter[tuple[int, str]] = Counter()
    with gzip.open(args.anarci, "rt", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            cdr3 = row["cdr3"]
            if cdr3 not in cdr3_component:
                raise ValueError(f"missing family for CDR3: {cdr3}")
            key = cdr3_component[cdr3]
            candidate_counts[key] += 1
            rows.append((row["candidate_id"], cdr3, key))

    fields = ["candidate_id", "cdr3", "cdr3_length", "cdr3_family_id",
              "cdr3_family_unique_size", "cdr3_family_candidate_size", "family_over_cap_100"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for candidate_id, cdr3, key in rows:
            size = candidate_counts[key]
            writer.writerow({
                "candidate_id": candidate_id, "cdr3": cdr3, "cdr3_length": len(cdr3),
                "cdr3_family_id": family_for_component[key],
                "cdr3_family_unique_size": unique_size[key],
                "cdr3_family_candidate_size": size,
                "family_over_cap_100": str(size > 100).lower(),
            })

    summary = {
        "status": "PASS", "records": len(rows), "unique_cdr3": len(cdr3_component),
        "family_count": len(component_members),
        "max_family_candidate_size": max(candidate_counts.values(), default=0),
        "families_over_cap_100": sum(size > 100 for size in candidate_counts.values()),
        "candidates_in_families_over_cap_100": sum(
            size for size in candidate_counts.values() if size > 100
        ),
        "definition": "equal-length connected components at Hamming identity >=80%",
        "output": str(args.output.resolve()), "output_sha256": sha256(args.output),
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
