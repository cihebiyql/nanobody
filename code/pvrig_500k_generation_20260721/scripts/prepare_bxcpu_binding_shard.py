#!/usr/bin/env python3
"""Prepare one deterministic FASTA shard for DeepNano and NanoBind."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


PVRIG_SEQUENCE = (
    "TPEVWVQVRMESFTIRCGFLGSGSISLVTVSWGGPNGAGGTTLAVLHPERGIRQWAPARQARWETQSSISLILEGSPSANTTFCCKFASFPEGSWEACGSLPP"
)


def read_fasta(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    name = None
    parts: list[str] = []
    with opener(path, "rt") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(parts)
                name, parts = line[1:].split()[0], []
            else:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_fasta", type=Path)
    parser.add_argument("outdir", type=Path)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("require 0 <= shard-index < shard-count")
    args.outdir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, record in enumerate(read_fasta(args.input_fasta)):
        if index % args.shard_count == args.shard_index:
            records.append(record)
            if args.limit and len(records) >= args.limit:
                break
    if not records:
        raise SystemExit("empty shard")

    nb = args.outdir / "nanobodies.fasta"
    ag = args.outdir / "antigens.fasta"
    deep = args.outdir / "deepnano_input.fasta"
    pairs = args.outdir / "deepnano_pairs.tsv"
    with nb.open("w") as nb_out, ag.open("w") as ag_out, deep.open("w") as deep_out, pairs.open("w") as pair_out:
        pair_out.write("Nanobody-ID\tAntigen-ID\n")
        for candidate_id, sequence in records:
            nb_out.write(f">{candidate_id}\n{sequence}\n")
            ag_out.write(f">pvrig_8x6b_chainB\n{PVRIG_SEQUENCE}\n")
            deep_out.write(f">{candidate_id}\n{sequence}\n")
            pair_out.write(f"{candidate_id}\tpvrig_8x6b_chainB\n")
        deep_out.write(f">pvrig_8x6b_chainB\n{PVRIG_SEQUENCE}\n")
    (args.outdir / "PREPARED.json").write_text(json.dumps({
        "status": "PASS", "records": len(records), "shard_index": args.shard_index,
        "shard_count": args.shard_count,
    }, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
