#!/usr/bin/env python3
"""Build a deterministic label-free 20-candidate V4-H smoke manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tsv(path: Path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main(args: argparse.Namespace) -> None:
    pool_path = Path(args.research_pool).resolve()
    monomer_manifest_path = Path(args.monomer_manifest).resolve()
    monomer_root = monomer_manifest_path.parent
    pool = {row["candidate_id"]: row for row in read_tsv(pool_path)}
    monomers = {row["candidate_id"]: row for row in read_tsv(monomer_manifest_path)}
    candidates = []
    for candidate_id in sorted(pool.keys() & monomers.keys()):
        p, m = pool[candidate_id], monomers[candidate_id]
        pdb = (monomer_root / m["frozen_monomer_path"]).resolve()
        if sha256_file(pdb) != m["sha256"] or p["sequence_sha256"] != m["sequence_sha256"]:
            raise ValueError(f"input closure failure: {candidate_id}")
        candidates.append((candidate_id, p, m, pdb))

    selected = []
    used = set()
    by_parent = defaultdict(list)
    for item in candidates:
        by_parent[item[1]["parent_framework_cluster"]].append(item)
    for parent in sorted(by_parent):
        item = by_parent[parent][0]
        selected.append(item)
        used.add(item[0])
    strata = defaultdict(list)
    for item in candidates:
        if item[0] not in used:
            key = (item[1]["target_patch_id"], item[1]["design_mode"])
            strata[key].append(item)
    while len(selected) < args.count:
        progressed = False
        for key in sorted(strata):
            while strata[key] and strata[key][0][0] in used:
                strata[key].pop(0)
            if strata[key] and len(selected) < args.count:
                item = strata[key].pop(0)
                selected.append(item)
                used.add(item[0])
                progressed = True
        if not progressed:
            raise ValueError("not enough candidates for requested smoke panel")

    output = Path(args.output_tsv)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id",
        "design_mode", "cdr1", "cdr2", "cdr3", "monomer_pdb", "monomer_sha256",
        "claim_boundary",
    ]
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for candidate_id, p, m, pdb in selected:
            writer.writerow(
                {
                    "candidate_id": candidate_id,
                    "sequence_sha256": p["sequence_sha256"],
                    "parent_framework_cluster": p["parent_framework_cluster"],
                    "target_patch_id": p["target_patch_id"],
                    "design_mode": p["design_mode"],
                    "cdr1": p["cdr1_after"],
                    "cdr2": p["cdr2_after"],
                    "cdr3": p["cdr3_after"],
                    "monomer_pdb": str(pdb),
                    "monomer_sha256": m["sha256"],
                    "claim_boundary": "Label-free candidate sequence/CDR/monomer input only; no candidate Docking pose or teacher label.",
                }
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-pool", required=True)
    parser.add_argument("--monomer-manifest", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--count", type=int, default=20)
    main(parser.parse_args())
