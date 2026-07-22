#!/usr/bin/env python3
"""Split a gzipped FASTA into deterministic ANARCI work shards."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def records(path: Path):
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
                name = line[1:].split()[0]
                parts = []
            elif name is None:
                raise ValueError("FASTA sequence encountered before header")
            else:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=32)
    args = parser.parse_args()
    if args.shards < 1:
        parser.error("--shards must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.output_dir / f"task_{index:03d}.fasta" for index in range(args.shards)]
    handles = [path.open("w") for path in paths]
    counts = [0] * args.shards
    seen: set[str] = set()
    total = 0
    try:
        for index, (name, sequence) in enumerate(records(args.input)):
            if name in seen:
                raise ValueError(f"duplicate FASTA id: {name}")
            seen.add(name)
            if not sequence:
                raise ValueError(f"empty sequence: {name}")
            shard = index % args.shards
            handles[shard].write(f">{name}\n{sequence}\n")
            counts[shard] += 1
            total += 1
    finally:
        for handle in handles:
            handle.close()

    manifest = {
        "status": "READY",
        "input": str(args.input.resolve()),
        "input_sha256": sha256(args.input),
        "records": total,
        "shards": args.shards,
        "shard_counts": counts,
        "shard_sha256": {path.name: sha256(path) for path in paths},
    }
    (args.output_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
