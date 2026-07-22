#!/usr/bin/env python3
"""Create ProteinMPNN fixed-position JSON for IMGT CDR-only VHH scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from abnumber import Chain


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structures", type=Path, required=True)
    parser.add_argument("--chain-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=99)
    parser.add_argument("--regions", nargs="+", choices=("CDR1", "CDR2", "CDR3"), default=["CDR1", "CDR2", "CDR3"])
    args = parser.parse_args()

    chain_map = json.loads(args.chain_map.read_text())
    fixed: dict[str, dict[str, list[int]]] = {}
    cdr_cache: dict[str, tuple[list[int], dict[str, int]]] = {}
    cdr_counts: Counter[str] = Counter()
    records = [json.loads(line) for line in args.structures.read_text().splitlines() if line.strip()]
    if len(records) != args.expected:
        raise SystemExit(f"expected {args.expected} structures, found {len(records)}")

    for record in records:
        name = record["name"]
        designed, fixed_chains = chain_map[name]
        if len(designed) != 1:
            raise SystemExit(f"expected one VHH chain for {name}: {designed}")
        vhh_chain = designed[0]
        sequence = record[f"seq_chain_{vhh_chain}"]
        if sequence not in cdr_cache:
            numbered = Chain(sequence, scheme="imgt")
            numbered_sequence = "".join(aa for _, aa in numbered)
            if numbered_sequence != sequence:
                raise SystemExit(f"ANARCI sequence mapping mismatch for {name}")
            cdr_positions: list[int] = []
            region_counts: Counter[str] = Counter()
            for index, (position, _aa) in enumerate(numbered, 1):
                if position.is_in_cdr() and position.get_region() in args.regions:
                    cdr_positions.append(index)
                    region_counts[position.get_region()] += 1
            if not cdr_positions:
                raise SystemExit(f"missing CDR positions for {name}")
            cdr_cache[sequence] = (cdr_positions, dict(region_counts))
        cdr_positions, region_counts = cdr_cache[sequence]
        fixed_positions = [index for index in range(1, len(sequence) + 1) if index not in set(cdr_positions)]
        fixed[name] = {vhh_chain: fixed_positions}
        cdr_counts.update(region_counts)

    args.output.write_text(json.dumps(fixed, sort_keys=True) + "\n")
    receipt = {
        "status": "READY",
        "structures": len(records),
        "unique_vhh_sequences": len(cdr_cache),
        "scheme": "IMGT",
        "scored_regions": args.regions,
        "total_scored_positions_across_poses": int(sum(cdr_counts.values())),
        "region_position_counts_across_poses": dict(sorted(cdr_counts.items())),
        "fixed_positions_sha256": sha256(args.output),
        "scientific_boundary": "CDR likelihood conditioned on frozen complex pose; not predicted Kd",
    }
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
