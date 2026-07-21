#!/usr/bin/env python3
"""Merge ANARCI results into the local CPU pilot routes and freeze effective candidates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


POSITION_RE = re.compile(r"^(\d+)([A-Z]*)$")


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
    """Match the final release's equal-length, connected Hamming80 families."""
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
        family_id = f"CDR3F80_{hashlib.sha256(chr(10).join(sorted(group)).encode()).hexdigest()[:16]}"
        for sequence in group:
            mapping[sequence] = family_id
    return mapping


def read_table(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


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


def numbered_region(row: dict[str, str], start: int, end: int) -> str:
    residues: list[tuple[tuple[int, int, int], str]] = []
    for key, value in row.items():
        match = POSITION_RE.fullmatch(key or "")
        if not match or not start <= int(match.group(1)) <= end:
            continue
        aa = (value or "").strip()
        if aa and aa not in {"-", "."}:
            position = int(match.group(1))
            insertion = match.group(2)
            if position in {61, 112}:
                # IMGT's two-sided insertion runs converge on the midpoint.
                # Sequence order is ...60,60A,...,61B,61A,61 for CDR2 and
                # ...111,111A,...,112B,112A,112 for CDR3.
                order = (position, 0, -ord(insertion)) if insertion else (position, 1, 0)
            else:
                # Other insertion runs follow the base residue: 111,111A,111B,...
                order = (position, 0, 0) if not insertion else (position, 1, ord(insertion))
            residues.append((order, aa))
    return "".join(aa for _order, aa in sorted(residues))


def evaluate(candidate: dict[str, str], row: dict[str, str] | None) -> dict[str, object]:
    reasons: list[str] = []
    regions = {}
    if row is None:
        reasons.append("anarci_no_H_domain")
    else:
        if row.get("chain_type") != "H":
            reasons.append("anarci_not_H_chain")
        if row.get("23") != "C" or row.get("104") != "C":
            reasons.append("conserved_imgt_cys_23_104_missing")
        ranges = {
            "fr1": (1, 26),
            "cdr1": (27, 38),
            "fr2": (39, 55),
            "cdr2": (56, 65),
            "fr3": (66, 104),
            "cdr3": (105, 117),
            "fr4": (118, 128),
        }
        regions = {name: numbered_region(row, *bounds) for name, bounds in ranges.items()}
        if any(not regions[name] for name in ("fr1", "fr2", "fr3", "fr4", "cdr1", "cdr2", "cdr3")):
            reasons.append("incomplete_fr_or_cdr")
        for region in ("cdr1", "cdr2", "cdr3"):
            if regions[region] != candidate[f"{region}_after"]:
                reasons.append(f"{region}_sequence_order_mismatch")
    return {
        "anarci_qc_status": "PASS" if not reasons else "FAIL",
        "anarci_qc_reasons": "|".join(reasons),
        "anarci_species": row.get("hmm_species", "") if row else "",
        "anarci_score": row.get("score", "") if row else "",
        **{f"anarci_{name}": value for name, value in regions.items()},
    }


def index_anarci_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("Id") not in by_id or row.get("domain_no") == "0":
            by_id[row["Id"]] = row
    return by_id


def merge_evaluations(
    candidates: list[dict[str, str]], anarci_rows: list[dict[str, str]]
) -> list[dict[str, object]]:
    by_id = index_anarci_rows(anarci_rows)
    return [
        {**candidate, **evaluate(candidate, by_id.get(candidate["candidate_id"]))}
        for candidate in candidates
    ]


def freeze_effective(
    primary: list[dict[str, object]],
    supplemental: list[dict[str, object]],
    quota: int = 5000,
    family_cap: int = 100,
) -> list[dict[str, object]]:
    frozen: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_sequences: set[str] = set()
    eligible = [
        row for row in primary + supplemental if row["anarci_qc_status"] == "PASS"
    ]
    family_by_cdr3 = cdr3_families([str(row["cdr3_after"]) for row in eligible])
    family_counts: Counter[str] = Counter()
    for route in ("conservative_cdr_redesign", "natural_cdr_donor"):
        route_rows = [
            row
            for row in eligible
            if row["route_id"] == route
        ]
        route_selected = 0
        for row in route_rows:
            family = family_by_cdr3[str(row["cdr3_after"])]
            if family_counts[family] >= family_cap:
                continue
            candidate_id = str(row["candidate_id"])
            sequence = str(row["sequence"])
            if candidate_id in seen_ids or sequence in seen_sequences:
                raise ValueError("duplicate candidate ID or sequence in effective freeze")
            seen_ids.add(candidate_id)
            seen_sequences.add(sequence)
            frozen.append({**row, "cdr3_family_id": family})
            family_counts[family] += 1
            route_selected += 1
            if route_selected == quota:
                break
    return frozen


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_fasta(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--supplemental-candidates", type=Path)
    parser.add_argument("--supplemental-anarci", type=Path)
    args = parser.parse_args()
    if bool(args.supplemental_candidates) != bool(args.supplemental_anarci):
        parser.error("--supplemental-candidates and --supplemental-anarci must be supplied together")
    campaign = args.campaign_dir.resolve()
    candidates = read_table(campaign / "qc" / "local_cpu_routes_pre_anarci.tsv", "\t")
    anarci_rows = read_table(campaign / "qc" / "local_cpu_routes_anarci_v1_H.csv", ",")
    merged = merge_evaluations(candidates, anarci_rows)
    supplemental_candidates: list[dict[str, str]] = []
    supplemental_rows: list[dict[str, str]] = []
    supplemental_merged: list[dict[str, object]] = []
    if args.supplemental_candidates and args.supplemental_anarci:
        supplemental_candidates = read_table(args.supplemental_candidates.resolve(), "\t")
        supplemental_rows = read_table(args.supplemental_anarci.resolve(), ",")
        supplemental_merged = merge_evaluations(supplemental_candidates, supplemental_rows)
        write_tsv(campaign / "qc" / "local_cpu_routes_supplemental_anarci_qc.tsv", supplemental_merged)

    passing = freeze_effective(merged, supplemental_merged)
    route_counts = Counter(str(row["route_id"]) for row in passing)
    family_counts = Counter(str(row["cdr3_family_id"]) for row in passing)
    status = "PASS" if all(route_counts[route] == 5000 for route in ("conservative_cdr_redesign", "natural_cdr_donor")) else "HOLD"
    qc_path = campaign / "qc" / "local_cpu_routes_anarci_qc.tsv"
    final_tsv = campaign / "qc" / "local_cpu_routes_effective.tsv"
    final_fasta = campaign / "qc" / "local_cpu_routes_effective.fasta"
    write_tsv(qc_path, merged)
    write_tsv(final_tsv, passing)
    write_fasta(final_fasta, passing)
    summary = {
        "schema_version": 1,
        "status": status,
        "input_candidates": len(candidates),
        "anarci_H_rows": len(anarci_rows),
        "effective_candidates": len(passing),
        "anarci_pass": sum(row["anarci_qc_status"] == "PASS" for row in merged + supplemental_merged),
        "anarci_fail": sum(row["anarci_qc_status"] != "PASS" for row in merged + supplemental_merged),
        "primary_anarci_pass": sum(row["anarci_qc_status"] == "PASS" for row in merged),
        "primary_anarci_fail": sum(row["anarci_qc_status"] != "PASS" for row in merged),
        "supplemental_input_candidates": len(supplemental_candidates),
        "supplemental_anarci_H_rows": len(supplemental_rows),
        "supplemental_anarci_pass": sum(
            row["anarci_qc_status"] == "PASS" for row in supplemental_merged
        ),
        "supplemental_anarci_fail": sum(
            row["anarci_qc_status"] != "PASS" for row in supplemental_merged
        ),
        "pass_by_route": dict(sorted(route_counts.items())),
        "cdr3_family_definition": "equal-length connected Hamming identity >=80%",
        "cdr3_family_cap": 100,
        "cdr3_family_count": len(family_counts),
        "max_cdr3_family_size": max(family_counts.values(), default=0),
        "failure_reasons": Counter(
            reason
            for row in merged + supplemental_merged
            for reason in str(row["anarci_qc_reasons"]).split("|")
            if reason
        ).most_common(),
        "outputs": {
            "qc_tsv": str(qc_path.relative_to(campaign)),
            "effective_tsv": str(final_tsv.relative_to(campaign)),
            "effective_fasta": str(final_fasta.relative_to(campaign)),
            "supplemental_qc_tsv": (
                "qc/local_cpu_routes_supplemental_anarci_qc.tsv"
                if supplemental_merged
                else None
            ),
        },
        "output_sha256": {
            "qc_tsv": sha256_file(qc_path),
            "effective_tsv": sha256_file(final_tsv),
            "effective_fasta": sha256_file(final_fasta),
        },
    }
    (campaign / "reports" / "local_cpu_anarci_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (campaign / "status" / "LOCAL_CPU_ANARCI_TERMINAL.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
