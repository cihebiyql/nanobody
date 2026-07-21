#!/usr/bin/env python3
"""Build the 25k effective pilot release with exact dedup and diversity gates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


EXPECTED_ROUTES = {
    "conservative_cdr_redesign",
    "natural_cdr_donor",
    "fixed_pose_mpnn_antifold",
    "epitope_conditioned_rfantibody",
    "denovo_disagreement_control",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class UnionFind:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}
        self.size = {value: 1 for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            parent = self.parent[value]
            self.parent[value] = root
            value = parent
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]


def cdr3_families(values: list[str]) -> dict[str, str]:
    """Exact connected families for equal-length CDR3s at >=80% Hamming identity."""
    unique = sorted(set(values))
    union_find = UnionFind(unique)
    by_length: dict[int, list[str]] = defaultdict(list)
    for sequence in unique:
        by_length[len(sequence)].append(sequence)
    for length, sequences in by_length.items():
        max_distance = math.floor(0.20 * length + 1e-12)
        if max_distance <= 0:
            continue
        block_count = max_distance + 1
        boundaries = [round(index * length / block_count) for index in range(block_count + 1)]
        buckets: dict[tuple[int, str], list[str]] = defaultdict(list)
        compared: set[tuple[str, str]] = set()
        for sequence in sequences:
            candidates: set[str] = set()
            for index in range(block_count):
                candidates.update(buckets[(index, sequence[boundaries[index] : boundaries[index + 1]])])
            for other in candidates:
                pair = tuple(sorted((sequence, other)))
                if pair in compared:
                    continue
                compared.add(pair)
                if sum(left != right for left, right in zip(sequence, other)) <= max_distance:
                    union_find.union(sequence, other)
            for index in range(block_count):
                buckets[(index, sequence[boundaries[index] : boundaries[index + 1]])].append(sequence)
    members: dict[str, list[str]] = defaultdict(list)
    for sequence in unique:
        members[union_find.find(sequence)].append(sequence)
    mapping: dict[str, str] = {}
    for group in members.values():
        family_id = f"CDR3F80_{sha256_text(chr(10).join(sorted(group)))[:16]}"
        for sequence in group:
            mapping[sequence] = family_id
    return mapping


def normalize(route_id: str, row: dict[str, str]) -> dict[str, object]:
    sequence = row.get("sequence", "").strip().upper()
    cdr3 = (row.get("cdr3_after") or row.get("cdr3") or "").strip().upper()
    candidate_id = (row.get("candidate_id") or "").strip()
    parent = (row.get("parent_cluster") or row.get("backbone_group_id") or "").strip()
    if not all((sequence, cdr3, candidate_id, parent)):
        raise ValueError(f"missing release field in route={route_id} candidate={candidate_id!r}")
    return {
        **row,
        "candidate_id": candidate_id,
        "sequence": sequence,
        "sequence_sha256": sha256_text(sequence),
        "cdr3_sequence_order": cdr3,
        "effective_parent_cluster": parent,
        "route_id": route_id,
    }


def parse_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("input must be ROUTE_ID=TSV_PATH")
    route, path = value.split("=", 1)
    return route, Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=parse_input, required=True)
    parser.add_argument("--current-top20-parents", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-route-target", type=int, default=5000)
    parser.add_argument("--family-cap", type=int, default=100)
    parser.add_argument("--top20-cap-fraction", type=float, default=0.35)
    args = parser.parse_args()

    routes = {route for route, _path in args.input}
    if routes != EXPECTED_ROUTES or len(args.input) != len(EXPECTED_ROUTES):
        raise ValueError(f"exactly five frozen routes required: {sorted(EXPECTED_ROUTES)}")
    top20 = {line.strip() for line in args.current_top20_parents.read_text().splitlines() if line.strip()}
    if len(top20) != 20:
        raise ValueError(f"authoritative current-top20 list must contain exactly 20 parents, found {len(top20)}")

    rows: list[dict[str, object]] = []
    for route, path in args.input:
        route_rows = [normalize(route, row) for row in read_tsv(path)]
        if len(route_rows) != args.per_route_target:
            raise ValueError(f"route {route} has {len(route_rows)} rows, expected {args.per_route_target}")
        rows.extend(route_rows)
    expected_total = args.per_route_target * len(EXPECTED_ROUTES)
    if len(rows) != expected_total:
        raise AssertionError("effective total mismatch")
    sequence_counts = Counter(str(row["sequence_sha256"]) for row in rows)
    duplicates = {digest: count for digest, count in sequence_counts.items() if count > 1}
    if duplicates:
        raise ValueError(f"exact sequence duplicates across routes: {len(duplicates)}")

    family_by_cdr3 = cdr3_families([str(row["cdr3_sequence_order"]) for row in rows])
    for row in rows:
        row["cdr3_family_id"] = family_by_cdr3[str(row["cdr3_sequence_order"])]
    family_counts = Counter(str(row["cdr3_family_id"]) for row in rows)
    if max(family_counts.values()) > args.family_cap:
        raise ValueError(f"CDR3 family cap exceeded: max={max(family_counts.values())} cap={args.family_cap}")
    top20_count = sum(str(row["effective_parent_cluster"]) in top20 for row in rows)
    top20_fraction = top20_count / len(rows)
    if top20_fraction > args.top20_cap_fraction:
        raise ValueError(f"current-top20 parent cap exceeded: {top20_fraction:.6f}")

    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"release output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.tmp.", dir=output.parent) as temporary:
        temp = Path(temporary)
        write_tsv(temp / "pvrig_pilot25k_effective_sequences.tsv", rows)
        with (temp / "pvrig_pilot25k_effective_sequences.fasta").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")
        receipt = {
            "status": "PASS_EFFECTIVE_PILOT25K",
            "candidate_count": len(rows),
            "route_counts": dict(sorted(Counter(str(row["route_id"]) for row in rows).items())),
            "exact_duplicate_count": 0,
            "cdr3_family_count": len(family_counts),
            "max_cdr3_family_size": max(family_counts.values()),
            "cdr3_family_cap": args.family_cap,
            "current_top20_parent_fraction": top20_fraction,
            "current_top20_parent_cap_fraction": args.top20_cap_fraction,
            "scientific_boundary": "sequence generation release only; not binding, docking, or blocking evidence",
        }
        (temp / "RELEASE_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        files = sorted(path for path in temp.iterdir() if path.is_file())
        (temp / "SHA256SUMS").write_text(
            "".join(f"{sha256_file(path)}  {path.name}\n" for path in files), encoding="utf-8"
        )
        (temp / "READY.json").write_text(
            json.dumps(
                {
                    "status": "READY",
                    "release_receipt_sha256": sha256_file(temp / "RELEASE_RECEIPT.json"),
                    "sha256sums_sha256": sha256_file(temp / "SHA256SUMS"),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        os.replace(temp, output)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
