#!/usr/bin/env python3
"""Freeze exact-unique candidates to explicit per-route quotas.

Input order is preserved.  Upstream task preparation deterministically shuffles
the campaign, so first-occurrence selection is reproducible without loading a
large table into memory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_quota(value: str) -> tuple[str, int]:
    route, sep, count = value.partition("=")
    if not sep or not route or not count.isdigit() or int(count) <= 0:
        raise argparse.ArgumentTypeError("quota must be ROUTE=POSITIVE_INTEGER")
    return route, int(count)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--quota", type=parse_quota, action="append", required=True)
    args = parser.parse_args()
    quotas = dict(args.quota)
    if len(quotas) != len(args.quota):
        parser.error("duplicate route quota")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tsv_path = output / "route_quota_exact_unique.tsv.gz"
    fasta_path = output / "route_quota_exact_unique.fasta.gz"

    available: Counter[str] = Counter()
    with gzip.open(args.input, "rt", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        for row in rows:
            available[row["route_id"]] += 1
    shortages = {route: quotas[route] - available[route] for route in quotas if available[route] < quotas[route]}
    if shortages:
        raise ValueError(f"route quota shortages: {shortages}")

    selected: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    patch_counts: Counter[str] = Counter()
    parent_counts: Counter[str] = Counter()
    seen_sequences: set[str] = set()
    seen_ids: set[str] = set()
    with gzip.open(args.input, "rt", encoding="utf-8", newline="") as src, gzip.open(
        tsv_path, "wt", encoding="utf-8", newline="", compresslevel=1
    ) as tsv, gzip.open(fasta_path, "wt", encoding="utf-8", compresslevel=1) as fasta:
        rows = csv.DictReader(src, delimiter="\t")
        if rows.fieldnames is None:
            raise ValueError("input table has no header")
        writer = csv.DictWriter(tsv, fieldnames=rows.fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            route = row["route_id"]
            if route not in quotas or selected[route] >= quotas[route]:
                continue
            sequence, candidate_id = row["sequence"], row["candidate_id"]
            if sequence in seen_sequences or candidate_id in seen_ids:
                raise ValueError(f"input is not exact-unique: {candidate_id}")
            seen_sequences.add(sequence)
            seen_ids.add(candidate_id)
            writer.writerow(row)
            fasta.write(f">{candidate_id}\n{sequence}\n")
            selected[route] += 1
            mode_counts[f"{route}|{row.get('design_mode', '')}"] += 1
            patch_counts[f"{route}|{row.get('target_patch_assignment', '')}"] += 1
            parent_counts[f"{route}|{row.get('parent_cluster', '')}"] += 1

    if dict(selected) != quotas:
        raise ValueError(f"selection count mismatch selected={dict(selected)} quotas={quotas}")
    receipt = {
        "status": "ROUTE_QUOTA_EXACT_UNIQUE_FROZEN_NOT_FINAL_ANARCI",
        "input": str(args.input.resolve()),
        "available_route_counts": dict(sorted(available.items())),
        "route_quotas": dict(sorted(quotas.items())),
        "selected_records": sum(selected.values()),
        "route_mode_counts": dict(sorted(mode_counts.items())),
        "route_patch_counts": dict(sorted(patch_counts.items())),
        "route_parent_cluster_count": {
            route: len({key.split("|", 1)[1] for key in parent_counts if key.startswith(route + "|")})
            for route in quotas
        },
        "outputs": {tsv_path.name: sha256_file(tsv_path), fasta_path.name: sha256_file(fasta_path)},
        "scientific_boundary": "Sequence generation and deterministic quota freezing only; ANARCI and predictive models remain required.",
    }
    (output / "FREEZE_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
